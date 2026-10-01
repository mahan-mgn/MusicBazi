package app.musicbazi.client;

import android.Manifest;
import android.content.ContentResolver;
import android.content.ContentValues;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;

import com.getcapacitor.JSObject;
import com.getcapacitor.PermissionState;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;

import java.io.File;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * ذخیره‌ی یک ترک در حافظه‌ی خودِ گوشی.
 *
 * چرا `MediaStore` و نه فایل‌سیستمِ ساده؟ چون خواسته‌ی واقعیِ کاربر «فایل توی
 * گوشیم باشد» نیست، «آهنگ توی موزیک‌پلیرِ گوشیم پیدا شود» است. فایلی که در
 * حافظه‌ی خصوصیِ اپ بنشیند نه در گالریِ موسیقی دیده می‌شود، نه با اپِ دیگری باز
 * می‌شود، و با حذفِ موزیک بازی پاک می‌شود.
 *
 * فقط همین یک قابلیت اینجاست و نه یک لایه‌ی عمومیِ فایل: هر چیزِ دیگری (کتابخانه،
 * پخشِ آفلاین) از قبل با سرویس‌ورکر کار می‌کند و آوردنش به نیتیو یعنی دو
 * انبارِ موازی که باید هم‌زمان نگه داشته شوند.
 */
@CapacitorPlugin(
        name = "Downloads",
        permissions = {
                @Permission(
                        alias = "storage",
                        // اندروید ۱۰ به بعد برای نوشتن در کالکشنِ خودِ اپ هیچ اجازه‌ای
                        // نمی‌خواهد؛ این فقط برای گوشی‌های قدیمی‌تر است
                        strings = { Manifest.permission.WRITE_EXTERNAL_STORAGE })
        }
)
public class DownloadsPlugin extends Plugin {

    /** پوشه‌ای که ترک‌ها زیرِ Music/ می‌نشینند */
    private static final String FOLDER = "MusicBazi";

    private final ExecutorService pool = Executors.newSingleThreadExecutor();

    @PluginMethod
    public void save(PluginCall call) {
        if (call.getString("url") == null) {
            call.reject("url لازم است");
            return;
        }

        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q
                && getPermissionState("storage") != PermissionState.GRANTED) {
            // نتیجه‌ی درخواست دوباره به همین متد برمی‌گردد
            requestPermissionForAlias("storage", call, "storageResult");
            return;
        }

        run(call);
    }

    @PermissionCallback
    private void storageResult(PluginCall call) {
        if (getPermissionState("storage") != PermissionState.GRANTED) {
            call.reject("اجازه‌ی نوشتن در حافظه داده نشد");
            return;
        }
        run(call);
    }

    private void run(PluginCall call) {
        final String url = call.getString("url");
        final String title = orFallback(call.getString("title"), "track");
        final String artist = orEmpty(call.getString("artist"));
        final String album = orEmpty(call.getString("album"));
        final String mime = orFallback(call.getString("mime"), "audio/mpeg");
        final String name = fileName(title, artist, call.getString("ext"));

        pool.execute(() -> {
            try {
                Uri target = insert(name, mime, title, artist, album);
                if (target == null) {
                    call.reject("جایی برای فایل ساخته نشد");
                    return;
                }
                download(url, target);
                publish(target);

                JSObject result = new JSObject();
                result.put("uri", target.toString());
                result.put("name", name);
                call.resolve(result);
            } catch (Exception error) {
                call.reject(error.getMessage() == null ? "ذخیره نشد" : error.getMessage());
            }
        });
    }

    /** ردیفِ خالی را در کتابخانه‌ی موسیقیِ سیستم می‌سازد و آدرسِ نوشتنش را می‌دهد */
    private Uri insert(String name, String mime, String title, String artist, String album) {
        ContentResolver resolver = getContext().getContentResolver();
        ContentValues values = new ContentValues();
        values.put(MediaStore.Audio.Media.DISPLAY_NAME, name);
        values.put(MediaStore.Audio.Media.MIME_TYPE, mime);
        values.put(MediaStore.Audio.Media.TITLE, title);
        if (!artist.isEmpty()) values.put(MediaStore.Audio.Media.ARTIST, artist);
        if (!album.isEmpty()) values.put(MediaStore.Audio.Media.ALBUM, album);
        values.put(MediaStore.Audio.Media.IS_MUSIC, 1);

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            values.put(MediaStore.Audio.Media.RELATIVE_PATH,
                    Environment.DIRECTORY_MUSIC + File.separator + FOLDER);
            /*
             * «در حالِ نوشتن». تا وقتی این پرچم بالاست هیچ اپِ دیگری فایلِ
             * نیمه‌دانلودشده را نمی‌بیند — وگرنه موزیک‌پلیرِ گوشی وسطِ دانلود
             * یک فایلِ خرابِ صفر ثانیه‌ای به کتابخانه‌اش اضافه می‌کرد.
             */
            values.put(MediaStore.Audio.Media.IS_PENDING, 1);
            return resolver.insert(MediaStore.Audio.Media.getContentUri(
                    MediaStore.VOLUME_EXTERNAL_PRIMARY), values);
        }

        // اندروید ۹ و پایین‌تر: مسیر را خودمان می‌سازیم و بعد به سیستم خبر می‌دهیم
        File dir = new File(
                Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_MUSIC), FOLDER);
        if (!dir.exists() && !dir.mkdirs()) return null;
        File file = new File(dir, name);
        values.put(MediaStore.Audio.Media.DATA, file.getAbsolutePath());
        return resolver.insert(MediaStore.Audio.Media.EXTERNAL_CONTENT_URI, values);
    }

    private void download(String url, Uri target) throws Exception {
        ContentResolver resolver = getContext().getContentResolver();
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) new URL(url).openConnection();
            connection.setConnectTimeout(15000);
            connection.setReadTimeout(30000);
            connection.setInstanceFollowRedirects(true);

            int status = connection.getResponseCode();
            if (status < 200 || status >= 300) throw new Exception("سرور " + status + " برگرداند");

            long total = connection.getContentLengthLong();
            try (InputStream in = connection.getInputStream();
                 OutputStream out = resolver.openOutputStream(target)) {
                if (out == null) throw new Exception("فایل باز نشد");

                byte[] buffer = new byte[64 * 1024];
                long received = 0;
                long lastReport = 0;
                int read;
                while ((read = in.read(buffer)) != -1) {
                    out.write(buffer, 0, read);
                    received += read;

                    // گزارشِ هر ۲۵۶ کیلوبایت: هر بافر یک رویداد یعنی صدها پیام
                    // روی پلِ Capacitor برای یک فایلِ چندمگابایتی
                    if (received - lastReport < 256 * 1024) continue;
                    lastReport = received;
                    JSObject event = new JSObject();
                    event.put("url", url);
                    event.put("received", received);
                    event.put("total", total);
                    notifyListeners("progress", event);
                }
            }
        } finally {
            if (connection != null) connection.disconnect();
        }
    }

    /** فایل تمام شد: از حالتِ «در حالِ نوشتن» درش می‌آورد تا بقیه ببینندش */
    private void publish(Uri target) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return;
        ContentValues done = new ContentValues();
        done.put(MediaStore.Audio.Media.IS_PENDING, 0);
        getContext().getContentResolver().update(target, done, null, null);
    }

    /**
     * نامِ فایل.
     *
     * کاراکترهایی که در FAT32 (کارت حافظه) ممنوع‌اند حذف می‌شوند و طولش کوتاه
     * می‌ماند — بعضی فایل‌سیستم‌ها بالای ۲۵۵ بایت را رد می‌کنند و نامِ فارسی در
     * UTF-8 دو برابرِ حروفش بایت می‌گیرد.
     */
    private static String fileName(String title, String artist, String ext) {
        String base = artist.isEmpty() ? title : artist + " - " + title;
        String safe = base.replaceAll("[\\\\/:*?\"<>|]", "").trim();
        if (safe.isEmpty()) safe = "track";
        if (safe.length() > 80) safe = safe.substring(0, 80).trim();
        String suffix = (ext == null || ext.isEmpty()) ? "mp3" : ext.replace(".", "");
        return safe + "." + suffix;
    }

    private static String orEmpty(String value) {
        return value == null ? "" : value;
    }

    private static String orFallback(String value, String fallback) {
        return value == null || value.isEmpty() ? fallback : value;
    }
}
