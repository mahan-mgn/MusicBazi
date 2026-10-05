package app.musicbazi.client;

import android.content.Context;
import android.graphics.Color;
import android.media.AudioManager;
import android.os.Build;
import android.os.Bundle;
import android.view.WindowManager;

import androidx.core.view.WindowCompat;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {

    @Override
    public void onCreate(Bundle savedInstanceState) {
        // ثبت باید *قبل* از super باشد؛ Capacitor پل را همان‌جا می‌سازد و
        // پلاگینی که دیرتر معرفی شود دیگر سوار نمی‌شود
        registerPlugin(PlaybackPlugin.class);
        registerPlugin(app.musicbazi.client.audio.bridge.AudioEnginePlugin.class);
        registerPlugin(ShellPlugin.class);
        registerPlugin(DownloadsPlugin.class);
        super.onCreate(savedInstanceState);

        enforceMediaAudio();

        /*
         * لبه‌تاـلبه.
         *
         * محتوا زیرِ نوار وضعیت و نوار ناوبری کشیده می‌شود و هر دو نوار شفاف
         * می‌شوند — همان چیزی که یک اپِ موسیقیِ امروزی شبیهش است، و شرطِ این‌که
         * گرادیانِ پشتِ کاور تا خودِ لبه‌ی صفحه برود.
         *
         * جای خالی‌شان از `ShellPlugin` به CSS می‌رسد، پس هیچ چیزی زیرِ ساعت یا
         * زیرِ نوارِ ژست گم نمی‌شود.
         */
        WindowCompat.setDecorFitsSystemWindows(getWindow(), false);
        getWindow().setStatusBarColor(Color.TRANSPARENT);
        getWindow().setNavigationBarColor(Color.TRANSPARENT);

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            // بدون این، روی گوشیِ ناچ‌دار اندروید یک نوارِ مشکی به‌جای ناچ می‌گذارد
            getWindow().getAttributes().layoutInDisplayCutoutMode =
                    WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES;
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            // خطِ جداکننده‌ای که اندروید خودش پشتِ نوار ناوبریِ شفاف می‌کشد
            getWindow().setNavigationBarContrastEnforced(false);
        }
    }

    @Override
    public void onResume() {
        super.onResume();
        enforceMediaAudio();
    }

    /**
     * دکمه‌های فیزیکی بلندی صدای گوشی را مستقیم به جریان پخش موسیقی متصل می‌کند.
     */
    private void enforceMediaAudio() {
        try {
            setVolumeControlStream(AudioManager.STREAM_MUSIC);
            AudioManager audioManager = (AudioManager) getSystemService(Context.AUDIO_SERVICE);
            if (audioManager != null && audioManager.getMode() != AudioManager.MODE_NORMAL) {
                audioManager.setMode(AudioManager.MODE_NORMAL);
            }
        } catch (Exception ignored) {
        }
    }
}
