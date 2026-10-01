package app.musicbazi.client;

import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.PowerManager;
import android.provider.Settings;
import android.util.DisplayMetrics;
import android.view.View;

import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowInsetsCompat;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/**
 * حاشیه‌های امنِ سیستم (نوار وضعیت، نوار ناوبری، ناچ).
 *
 * چرا دستی؟ چون `env(safe-area-inset-*)` داخل WebViewِ اندروید قابل‌اتکا نیست:
 * بسته به نسخه‌ی WebView، حالتِ لبه‌تاـلبه و حالتِ ناوبری (دکمه‌ای یا ژستی)
 * گاهی صفر برمی‌گرداند. نتیجه‌اش هدری بود که زیرِ ساعت می‌رفت و نوارِ پخشی که
 * روی نوارِ ناوبری می‌افتاد.
 *
 * اینجا همان مقدارها را از خودِ سیستم می‌گیریم و JS آن‌ها را روی همان
 * متغیرهای CSS (`--safe-t` و برادرانش) می‌نشاند. روی وب هیچ‌کدام اجرا نمی‌شود
 * و `env()` سرِ جایش می‌ماند.
 */
@CapacitorPlugin(name = "Shell")
public class ShellPlugin extends Plugin {

    /**
     * متنی که با «اشتراک‌گذاری» از اپِ دیگری آمده و هنوز به JS تحویل نشده.
     *
     * لازم است چون اپ ممکن است *به‌خاطرِ همین اشتراک‌گذاری* تازه بالا آمده
     * باشد: آن‌وقت اینتنت پیش از آماده‌شدنِ رابط رسیده و هیچ شنونده‌ای نبوده.
     * JS بعد از سوار شدن با `takeSharedText` می‌آید و برش می‌دارد.
     */
    private String pendingShare;

    /**
     * فایلِ نشانِ کرشِ موتورِ رندر.
     *
     * اندروید وقتی WebView می‌میرد (معمولاً OOM روی گوشی‌های کم‌رم) هیچ لاگی
     * جا نمی‌گذارد و اپ بی‌صدا بسته می‌شود. تنها چیزی که می‌ماند *خبرِ مرگ*
     * است، نه علتش — و همان خبر هم باید در دیسک بماند چون پروسه از نو بالا
     * می‌آید. پس اینجا می‌نویسیم و JS در اجرای بعدی با `takeCrash` می‌خواندش و
     * به `/api/client-error` می‌فرستد.
     */
    private boolean restarted;

    /**
     * میان‌بُرِ لانچری که هنوز به JS تحویل نشده.
     *
     * همان مسئله‌ی `pendingShare`: اگر اپ بسته بوده، اینتنتِ میان‌بُر پیش از
     * سوارشدنِ رابط رسیده و هیچ شنونده‌ای نیست. JS بعد از بالا آمدن با
     * `takeRoute` می‌آید و برش می‌دارد.
     */
    private String pendingRoute;

    /** مقدارِ `musicbazi.route` از اینتنتِ میان‌بُر (res/xml/shortcuts.xml) */
    private void readRoute(Intent intent) {
        if (intent == null) return;
        String route = intent.getStringExtra("musicbazi.route");
        if (route != null && !route.trim().isEmpty()) pendingRoute = route.trim();
    }

    /**
     * یک آدرس را بیرونِ اپ باز می‌کند (مرورگر/اپِ دانلود).
     *
     * برای نصبِ APK لازم است: اندروید اجازه نمی‌دهد اپِ خودش یک بسته‌ی نصب را
     * از داخلِ WebView پایین بیاورد، و کاربر باید به «دانلودها» برود. بیرون
     * رفتن از اپ، تنها راهِ مجاز و همان کاری است که دستی انجام می‌شد.
     */
    @PluginMethod
    public void openExternal(PluginCall call) {
        String url = call.getString("url", "");
        if (url.isEmpty()) {
            call.reject("url لازم است");
            return;
        }
        try {
            Intent open = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
            open.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            getContext().startActivity(open);
            call.resolve();
        } catch (Exception error) {
            // هیچ اپی آن آدرس را باز نمی‌کند (مرورگر غیرفعال/حذف‌شده)
            call.reject("باز نشد");
        }
    }

    @PluginMethod
    public void takeRoute(PluginCall call) {
        JSObject result = new JSObject();
        result.put("route", pendingRoute == null ? "" : pendingRoute);
        pendingRoute = null;
        call.resolve(result);
    }

    private java.io.File crashMarker() {
        return new java.io.File(getContext().getFilesDir(), "webview-crash.txt");
    }

    @Override
    public void load() {
        View root = getBridge().getWebView();

        readShare(getActivity().getIntent());
        readRoute(getActivity().getIntent());

        /*
         * حاشیه‌ها ثابت نیستند: چرخاندن گوشی، باز شدنِ کیبورد، و عوض‌شدنِ حالتِ
         * ناوبری همه عوضشان می‌کنند. بدون این شنونده، مقدارِ لحظه‌ی باز شدنِ اپ
         * برای همیشه می‌ماند.
         */
        ViewCompat.setOnApplyWindowInsetsListener(root, (view, insets) -> {
            notifyListeners("insets", read(insets));
            return insets;
        });

        getBridge().addWebViewListener(new com.getcapacitor.WebViewListener() {
            @Override
            public boolean onRenderProcessGone(
                    android.webkit.WebView view, android.webkit.RenderProcessGoneDetail detail) {
                return onRendererGone(view, detail);
            }
        });
    }

    /**
     * مرگِ موتورِ رندر را ثبت می‌کند و صفحه را دوباره بالا می‌آورد.
     *
     * `true` برگرداندن یعنی «خودم هندلش کردم». اگر `false` برود، رفتارِ
     * پیش‌فرضِ اندروید کشتنِ کلِ پروسه است — یعنی کاربر به‌جای یک رفرشِ یک‌
     * ثانیه‌ای، اپِ بسته‌شده می‌بیند. پخشِ موسیقی هم با پروسه می‌رود، ولی
     * سرویسِ پیش‌زمینه زنده می‌ماند و کاربر با یک ضربه ادامه می‌دهد.
     */
    private boolean onRendererGone(
            android.webkit.WebView view, android.webkit.RenderProcessGoneDetail detail) {
        try (java.io.FileWriter writer = new java.io.FileWriter(crashMarker())) {
            writer.write("didCrash=" + (detail != null && detail.didCrash())
                    + " at=" + System.currentTimeMillis());
        } catch (Exception ignored) {
            // نوشتنِ نشان نشد؛ گزارشِ کرش قربانیِ حافظه‌ی کم نیست
        }
        if (view == null) return false;
        /*
         * بعد از مرگِ رندر، خودِ WebView دیگر قابل‌استفاده نیست (کروم آن را
         * دور می‌اندازد) — `reload()` روی جسدِ آن هیچ کاری نمی‌کند. تنها راهِ
         * بازگشت، ساختنِ دوباره‌ی اکتیویتی است که پل و WebView را از نو می‌سازد.
         *
         * یک‌بار در هر پروسه: اگر علتِ مرگ OOM باشد و صفحه بی‌درنگ بمیرد،
         * recreate حلقه‌ی بی‌پایان می‌سازد و کاربر به‌جای اپِ مرده، گوشیِ داغ
         * می‌بیند. آن‌وقت بگذار سیستم خودش ببندد و نشانِ کرش برای اجرای بعدی
         * بماند.
         */
        if (restarted) return false;
        restarted = true;
        view.post(() -> getActivity().recreate());
        return true;
    }

    /**
     * نشانِ کرش را می‌خواند و پاک می‌کند — «گرفتن و پاک‌کردن» مثلِ `takeSharedText`:
     * یک مرگ باید یک بار گزارش شود، نه هر بار که اپ بالا آمد.
     */
    @PluginMethod
    public void takeCrash(PluginCall call) {
        JSObject result = new JSObject();
        java.io.File marker = crashMarker();
        String text = "";
        if (marker.exists()) {
            try {
                text = new String(java.nio.file.Files.readAllBytes(marker.toPath()),
                        java.nio.charset.StandardCharsets.UTF_8);
                marker.delete();
            } catch (Exception ignored) {
                text = "";
            }
        }
        result.put("text", text);
        call.resolve(result);
    }

    @PluginMethod
    public void insets(PluginCall call) {
        View root = getBridge().getWebView();
        WindowInsetsCompat insets = ViewCompat.getRootWindowInsets(root);
        if (insets == null) {
            // هنوز به پنجره وصل نشده — JS همان `env()` را نگه می‌دارد
            JSObject empty = new JSObject();
            empty.put("ready", false);
            call.resolve(empty);
            return;
        }
        call.resolve(read(insets));
    }

    /**
     * لینکِ اشتراک‌گذاری‌شده را می‌گیرد و پاکش می‌کند.
     *
     * «گرفتن و پاک‌کردن» عمدی است: بدونش هر بار که کاربر اپ را از پس‌زمینه
     * برمی‌گرداند، همان لینکِ قدیمی دوباره باز می‌شد.
     */
    @PluginMethod
    public void takeSharedText(PluginCall call) {
        JSObject result = new JSObject();
        result.put("text", pendingShare == null ? "" : pendingShare);
        pendingShare = null;
        call.resolve(result);
    }

    /** اپ باز بود و کاربر از اپِ دیگری چیزی به آن اشتراک گذاشت */
    @Override
    protected void handleOnNewIntent(Intent intent) {
        super.handleOnNewIntent(intent);
        readShare(intent);
        if (pendingShare != null) {
            JSObject event = new JSObject();
            event.put("text", pendingShare);
            pendingShare = null;
            notifyListeners("shared", event);
        }

        // اپ باز بود و کاربر میان‌بُر زد: همان لحظه باید صفحه عوض شود
        readRoute(intent);
        if (pendingRoute == null) return;
        JSObject event = new JSObject();
        event.put("route", pendingRoute);
        pendingRoute = null;
        notifyListeners("route", event);
    }

    private void readShare(Intent intent) {
        if (intent == null) return;
        if (!Intent.ACTION_SEND.equals(intent.getAction())) return;
        String text = intent.getStringExtra(Intent.EXTRA_TEXT);
        if (text == null || text.trim().isEmpty()) return;
        pendingShare = text.trim();
    }

    /**
     * نسخه‌ی نصب‌شده، برای مقایسه با `GET /api/release`.
     *
     * `versionCode` عدد است نه رشته: «۱۰» از نظر رشته از «۹» کوچک‌تر است و آن
     * مقایسه یعنی بنرِ بروزرسانی برای همیشه روی همان نسخه بماند.
     */
    @PluginMethod
    public void appInfo(PluginCall call) {
        JSObject result = new JSObject();
        try {
            Context ctx = getContext();
            PackageInfo info = ctx.getPackageManager()
                    .getPackageInfo(ctx.getPackageName(), 0);
            result.put("versionCode", longCode(info));
            result.put("versionName", info.versionName == null ? "" : info.versionName);
        } catch (PackageManager.NameNotFoundException error) {
            result.put("versionCode", 0);
            result.put("versionName", "");
        }
        call.resolve(result);
    }

    @SuppressWarnings("deprecation")
    private static long longCode(PackageInfo info) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            return info.getLongVersionCode();
        }
        return info.versionCode;
    }

    /**
     * آیا اپ از دست‌کاریِ باتری مستثناست؟
     *
     * این تنها جوابِ «آهنگ وسطِ خواب قطع می‌شود» است: اندروید (و به‌شکلِ
     * تهاجمی‌تر ROMهای شیائومی/وان‌پلاس) پروسه‌ی پس‌زمینه را می‌کشد. سرویسِ
     * پیش‌زمینه تنها *نیمی* از ماجراست؛ نیمه‌ی دیگر این است که کاربر خودش
     * استثنا را داده باشد یا نه.
     */
    @PluginMethod
    public void batteryStatus(PluginCall call) {
        JSObject result = new JSObject();
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) {
            // پیش از اندروید ۶ این چیزی وجود نداشت؛ پس «مشکلی نیست»
            result.put("ignoring", true);
            result.put("canAsk", false);
            call.resolve(result);
            return;
        }
        PowerManager power = (PowerManager) getContext().getSystemService(Context.POWER_SERVICE);
        result.put("ignoring", power.isIgnoringBatteryOptimizations(getContext().getPackageName()));
        result.put("canAsk", true);
        call.resolve(result);
    }

    /**
     * صفحه‌ی «اپ‌های بدونِ دست‌کاریِ باتری» را باز می‌کند.
     *
     * عمداً `ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS` و نه
     * `ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS`: دومی یک دیالوگِ یک‌کلیکی
     * است که فقط روی توزیعِ گوگل‌پلی ممنوع حساب می‌شود و سیاستِ مبهمی دارد؛
     * اولی یک صفحه‌ی تنظیماتِ معمولی است، اجازه‌ای نمی‌خواهد، و کاربر خودش
     * فهرست را می‌بیند — که برای یک اپِ موسیقیِ پس‌زمینه دقیقاً همان چیزی است
     * که باید توضیح بدهد.
     */
    @PluginMethod
    public void openBatterySettings(PluginCall call) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) {
            call.reject("این اندروید دست‌کاریِ باتری ندارد");
            return;
        }
        Intent settings = new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS);
        if (settings.resolveActivity(getContext().getPackageManager()) == null) {
            // بعضی ROMها این صفحه را ندارند؛ صفحه‌ی اطلاعاتِ اپ همیشه هست
            openAppDetails(call);
            return;
        }
        try {
            getContext().startActivity(settings);
            call.resolve();
        } catch (Exception error) {
            call.reject("باز نشد");
        }
    }

    /** تنظیماتِ خودِ اپ — آخرین راهِ رسیدن به «اجازه‌ها» و «باتری» */
    @PluginMethod
    public void openAppSettings(PluginCall call) {
        openAppDetails(call);
    }

    private void openAppDetails(PluginCall call) {
        Intent details = new Intent(
                Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                Uri.fromParts("package", getContext().getPackageName(), null));
        details.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        try {
            getContext().startActivity(details);
            call.resolve();
        } catch (Exception error) {
            call.reject("باز نشد");
        }
    }

    private JSObject read(WindowInsetsCompat insets) {
        /*
         * `systemBars` نوار وضعیت و نوار ناوبری را می‌دهد و `displayCutout` ناچ
         * را. جمعشان لازم است نه یکی‌شان: روی گوشیِ ناچ‌دار در حالتِ افقی، ناچ
         * از کنار می‌آید جایی که نوار وضعیت اصلاً نیست.
         *
         * کیبورد (`ime`) عمداً بیرون است: با `interactive-widget=resizes-content`
         * خودِ WebView کوچک می‌شود و اضافه‌کردنش حاشیه را دوبار حساب می‌کرد.
         */
        Insets value = insets.getInsets(
                WindowInsetsCompat.Type.systemBars() | WindowInsetsCompat.Type.displayCutout());

        DisplayMetrics metrics = getContext().getResources().getDisplayMetrics();
        float density = metrics.density <= 0 ? 1f : metrics.density;

        JSObject result = new JSObject();
        result.put("ready", true);
        // CSS با پیکسلِ منطقی کار می‌کند، اندروید با پیکسلِ فیزیکی
        result.put("top", value.top / density);
        result.put("bottom", value.bottom / density);
        result.put("left", value.left / density);
        result.put("right", value.right / density);
        return result;
    }
}
