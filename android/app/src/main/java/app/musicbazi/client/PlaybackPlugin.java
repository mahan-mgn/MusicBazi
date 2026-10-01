package app.musicbazi.client;

import android.Manifest;
import android.content.Intent;
import android.os.Build;

import com.getcapacitor.JSObject;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.Plugin;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;

/**
 * پلِ بینِ پخش‌کننده‌ی جاوااسکریپتی و {@link PlaybackService}.
 *
 * جهتِ رفت: هر تغییرِ ترک یا وضعیت از JS با `sync` می‌آید و نوتیفیکیشن را
 * به‌روز می‌کند. جهتِ برگشت: هر دکمه‌ای که روی نوتیفیکیشن یا صفحه‌ی قفل یا
 * هدفون زده شود، به‌شکلِ رویدادِ `transport` به JS می‌رسد.
 *
 * عمداً یک لایه‌ی نازک است: هیچ منطقِ پخشی اینجا نیست، چون منطق (صف، شافل،
 * تکرار، رادیو) همه در `store/player.ts` است و دوتا شدنش یعنی دو رفتارِ
 * متفاوت که دیر یا زود از هم واگرا می‌شوند.
 */
@CapacitorPlugin(
        name = "Playback",
        permissions = {
                @Permission(alias = "notifications", strings = { Manifest.permission.POST_NOTIFICATIONS })
        }
)
public class PlaybackPlugin extends Plugin {

    @Override
    public void load() {
        PlaybackService.setListener((action, value) -> {
            JSObject event = new JSObject();
            event.put("action", action);
            // فقط `seek` مقدار دارد؛ بقیه صفر می‌فرستند و JS نگاهش نمی‌کند
            event.put("value", value / 1000.0);
            notifyListeners("transport", event);
        });
    }

    /**
     * وضعیتِ فعلی را روی نوتیفیکیشن می‌نشاند و در صورت لزوم سرویس را بالا
     * می‌آورد. زمان‌ها از JS به ثانیه می‌آیند و اینجا میلی‌ثانیه می‌شوند، چون
     * قراردادِ `MediaSession` اندروید میلی‌ثانیه است.
     */
    @PluginMethod
    public void sync(PluginCall call) {
        Intent intent = new Intent(getContext(), PlaybackService.class);
        intent.setAction(PlaybackService.ACTION_SYNC);
        intent.putExtra("title", call.getString("title", ""));
        intent.putExtra("artist", call.getString("artist", ""));
        intent.putExtra("album", call.getString("album", ""));
        intent.putExtra("artworkUrl", call.getString("artworkUrl", ""));
        intent.putExtra("playing", Boolean.TRUE.equals(call.getBoolean("playing", false)));
        intent.putExtra("position", (long) (call.getDouble("position", 0.0) * 1000));
        intent.putExtra("duration", (long) (call.getDouble("duration", 0.0) * 1000));

        /*
         * `startForegroundService` فقط وقتی مجاز است که اپ دیده شود یا سرویس
         * قبلاً پیش‌زمینه باشد؛ از اندروید ۱۲ به بعد صدا زدنش از پس‌زمینه
         * استثنا پرت می‌کند. همیشه در واکنش به کنشِ کاربر صدا زده می‌شود، ولی
         * یک حالتِ مرزی هست: مکث از خودِ نوتیفیکیشن وقتی اپ پس‌زمینه است.
         * آن استثنا نباید پخش را بترکاند، پس بی‌صدا رد می‌شود.
         */
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                getContext().startForegroundService(intent);
            } else {
                getContext().startService(intent);
            }
        } catch (Exception ignored) {
            // نوتیفیکیشن به‌روز نشد؛ خودِ پخش دست‌نخورده ادامه دارد
        }

        call.resolve();
    }

    /**
     * تایمرِ خواب را به ساعتِ سیستم می‌سپارد.
     *
     * `minutes: 0` یعنی لغو. چرا نیتیو؟ چون `setTimeout` داخل WebView با
     * خاموش‌شدنِ صفحه throttle می‌شود و تایمری که باید گوشی را خاموش کند،
     * خاموش نمی‌کند. بقیه‌ی کار (مکثِ واقعی، پاک‌شدنِ UI) در JS می‌ماند و از
     * همین‌جا با رویدادِ `sleep` خبردار می‌شود.
     */
    @PluginMethod
    public void setSleepTimer(PluginCall call) {
        int minutes = call.getInt("minutes", 0);
        Intent intent = new Intent(getContext(), PlaybackService.class);
        intent.setAction(PlaybackService.ACTION_SLEEP);
        intent.putExtra("minutes", minutes);
        try {
            // سرویس در این لحظه بالا نیست مگر چیزی در حالِ پخش باشد؛ اگر نبود،
            // startService معمولی کافی است و startForegroundService لازم نیست
            getContext().startService(intent);
        } catch (Exception ignored) {
            // پروسه در حالِ کشته‌شدن است؛ JS تایمرِ خودش را نگه می‌دارد
        }
        call.resolve();
    }

    /** پخش بسته شد — نوتیفیکیشن و سرویس هر دو می‌روند */
    @PluginMethod
    public void stop(PluginCall call) {
        Intent intent = new Intent(getContext(), PlaybackService.class);
        intent.setAction(PlaybackService.ACTION_STOP);
        try {
            getContext().startService(intent);
        } catch (Exception ignored) {
            // سرویس از قبل مرده بود
        }
        call.resolve();
    }

    /**
     * از اندروید ۱۳ نوتیفیکیشن اجازه‌ی زمانِ‌اجرا می‌خواهد. بدونش پخش کار
     * می‌کند ولی نوتیفیکیشنِ مدیا نامرئی است — و چون سرویسِ پیش‌زمینه
     * نوتیفیکیشنِ قابل‌نمایش ندارد، اندروید بعد از مدتی پروسه را می‌کشد.
     */
    @PluginMethod
    public void ensurePermission(PluginCall call) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
            call.resolve(granted(true));
            return;
        }
        if (isGranted()) {
            call.resolve(granted(true));
            return;
        }
        // اگر خودِ درخواستِ اجازه نشد، بی‌سروصدا «داده‌نشده» جواب می‌دهیم —
        // پخش نباید به‌خاطرِ یک نوتیفیکیشن بمیرد
        try {
            requestPermissionForAlias("notifications", call, "permissionResult");
        } catch (Exception ignored) {
            call.resolve(granted(false));
        }
    }

    @PermissionCallback
    private void permissionResult(PluginCall call) {
        call.resolve(granted(isGranted()));
    }

    /**
     * وضعیتِ اجازه‌ی نوتیفیکیشن، مستقیم از API اندروید.
     *
     * عمداً از `getPermissionState("notifications")` استفاده نمی‌کنیم: آن متد
     * آرایه‌ی `@Permission` را از راهِ بازتاب می‌خواند، و اگر R8 نوعِ آنوتیشن
     * را حذف کرده باشد همان‌جا `NullPointerException` می‌دهد — روی نخِ
     * `CapacitorPlugins`، یعنی کلِ اپ. آن کرش دقیقاً لحظه‌ی «پخشِ اولین
     * آهنگ» می‌افتاد (این‌جا اولین بار اجازه پرسیده می‌شود). `checkSelfPermission`
     * هیچ بازتابی ندارد و همان مقدارِ درست را می‌دهد.
     *
     * قواعدِ `-keep` در `proguard-rules.pro` علتِ اصلی را حل می‌کنند؛ این
     * فقط کمربندِ ایمنی است تا یک بارِ دیگر، شکستِ APIیِ اجازه، پخش را نکشد.
     */
    private boolean isGranted() {
        return androidx.core.content.ContextCompat.checkSelfPermission(
                getContext(), Manifest.permission.POST_NOTIFICATIONS)
                == android.content.pm.PackageManager.PERMISSION_GRANTED;
    }

    private static JSObject granted(boolean value) {
        JSObject result = new JSObject();
        result.put("granted", value);
        return result;
    }
}
