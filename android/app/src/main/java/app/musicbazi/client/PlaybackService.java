package app.musicbazi.client;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.media.AudioAttributes;
import android.media.AudioFocusRequest;
import android.media.AudioManager;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;
import android.support.v4.media.MediaMetadataCompat;
import android.support.v4.media.session.MediaSessionCompat;
import android.support.v4.media.session.PlaybackStateCompat;

import androidx.annotation.Nullable;
import androidx.core.app.NotificationCompat;
import androidx.media.app.NotificationCompat.MediaStyle;
import androidx.media.session.MediaButtonReceiver;

import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * سرویسِ پیش‌زمینه‌ی پخش.
 *
 * صدا اینجا پخش *نمی‌شود* — آن کار همچنان مالِ WebView و موتور صوتیِ جاوااسکریپت
 * است. کارِ این سرویس سه چیز است که وب به‌تنهایی روی اندروید نمی‌تواند:
 *
 *  ۱. پروسه را «پیش‌زمینه» نگه می‌دارد، وگرنه اندروید کمی بعد از رفتنِ اپ به
 *     پس‌زمینه پروسه را می‌کشد و پخش وسطِ آهنگ قطع می‌شود.
 *  ۲. یک نوتیفیکیشنِ مدیا با کاور و دکمه‌های پخش می‌سازد — همان چیزی که کاربر
 *     از هر پخش‌کننده‌ی اندرویدی انتظار دارد، و روی صفحه‌ی قفل هم می‌آید.
 *  ۳. دکمه‌های رسانه‌ایِ سخت‌افزاری (هدفون، بلوتوثِ ماشین) را می‌گیرد.
 *
 * `navigator.mediaSession` داخل WebView هیچ‌کدام از این‌ها را نمی‌دهد؛ آن API
 * فقط در خودِ کروم به نوتیفیکیشن وصل است، نه در WebViewی که اپ میزبانش است.
 */
public class PlaybackService extends Service {

    public static final String ACTION_SYNC = "app.musicbazi.client.SYNC";
    public static final String ACTION_STOP = "app.musicbazi.client.STOP";
    public static final String ACTION_SLEEP = "app.musicbazi.client.SLEEP";

    private static final String CHANNEL_ID = "musicbazi.playback";
    private static final int NOTIFICATION_ID = 0x555;

    /** رابطِ برگشت به جاوااسکریپت — پلاگین خودش را اینجا ثبت می‌کند */
    public interface TransportListener {
        void onTransport(String action, long value);
    }

    @Nullable
    private static TransportListener listener;

    public static void setListener(@Nullable TransportListener value) {
        listener = value;
    }

    private static void emit(String action, long value) {
        TransportListener current = listener;
        if (current != null) current.onTransport(action, value);
    }

    private MediaSessionCompat session;
    private PowerManager.WakeLock wakeLock;
    private AudioManager audioManager;
    private AudioFocusRequest focusRequest;
    private boolean hasAudioFocus = false;
    private boolean noisyReceiverRegistered = false;
    private boolean pausedDueToTransientFocusLoss = false;

    private final AudioManager.OnAudioFocusChangeListener focusListener = new AudioManager.OnAudioFocusChangeListener() {
        @Override
        public void onAudioFocusChange(int focusChange) {
            switch (focusChange) {
                case AudioManager.AUDIOFOCUS_LOSS_TRANSIENT:
                case AudioManager.AUDIOFOCUS_LOSS:
                    hasAudioFocus = false;
                    pausedDueToTransientFocusLoss = false;
                    // وب‌ویوی داخلی کرومیوم خود مستقلاً فکوس صوتی را مدیریت می‌کند.
                    // ارسال دستی pause از سرویس نیتیو باعث توقف فوری پخش در حین شروع می‌شود
                    // چون کرومیوم و سرویس هر دو به صورت همزمان درخواست فکوس می‌دهند.
                    break;
                case AudioManager.AUDIOFOCUS_LOSS_TRANSIENT_CAN_DUCK:
                    // اجازه می‌دهیم سیستم خودش ولوم را کم کند؛ قطع و وصل ناگهانی صدا در هدفون ایجاد نمی‌کنیم
                    break;
                case AudioManager.AUDIOFOCUS_GAIN:
                    hasAudioFocus = true;
                    break;
            }
        }
    };

    private final BroadcastReceiver noisyReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            if (AudioManager.ACTION_AUDIO_BECOMING_NOISY.equals(intent.getAction())) {
                if (playing) {
                    emit("pause", 0);
                }
            }
        }
    };

    /*
     * تایمرِ خواب روی نخِ *سیستم*، نه تایمرِ جاوااسکریپتی.
     *
     * `setTimeout` داخل WebView با خوابیدنِ صفحه throttle می‌شود (بعضی ROMها آن
     * را چند دقیقه‌ای به تعویق می‌اندازند)، پس «۲۰ دقیقه» عملاً «۲۵ دقیقه» یا
     * بیشتر می‌شد — و بدترین حالت این است که چیزی که باید خاموش کند، خاموش
     * نکند. اینجا همان زمان‌سنجی را اندروید انجام می‌دهد و فقط زنگش را به JS
     * می‌فرستد؛ منطقِ «چه چیزی پخش شود» همچنان مالِ JS می‌ماند.
     */
    private final Handler clock = new Handler(Looper.getMainLooper());
    private Runnable sleepTask;
    private final ExecutorService artworkPool = Executors.newSingleThreadExecutor();

    /* آخرین متادیتای دریافتی — نوتیفیکیشن با هر همگام‌سازی از همین‌ها بازساخته می‌شود */
    private String title = "";
    private String artist = "";
    private String album = "";
    private String artworkUrl = "";
    private boolean playing = false;
    private long positionMs = 0;
    private long durationMs = 0;

    /*
     * کاورِ دانلودشده کش می‌شود. بدون این، هر تیکِ موقعیت (هر ثانیه) یک درخواستِ
     * شبکه برای همان تصویر می‌فرستاد.
     */
    @Nullable
    private Bitmap artwork;

    @Override
    public void onCreate() {
        super.onCreate();
        createChannel();

        session = new MediaSessionCompat(this, "musicbazi");
        session.setCallback(new MediaSessionCompat.Callback() {
            @Override
            public void onPlay() {
                emit("play", 0);
            }

            @Override
            public void onPause() {
                emit("pause", 0);
            }

            @Override
            public void onSkipToNext() {
                emit("next", 0);
            }

            @Override
            public void onSkipToPrevious() {
                emit("prev", 0);
            }

            @Override
            public void onStop() {
                emit("stop", 0);
            }

            @Override
            public void onSeekTo(long pos) {
                emit("seek", pos);
            }
        });
        session.setActive(true);

        /*
         * قفلِ بیداریِ نیمه: پردازنده بیدار می‌ماند ولی صفحه خاموش می‌شود. بدون
         * آن، با خاموش‌شدنِ صفحه تایمرهای WebView کند می‌شوند و پخش می‌لنگد.
         * فقط تا وقتی چیزی در حال پخش است گرفته می‌شود.
         */
        PowerManager power = (PowerManager) getSystemService(Context.POWER_SERVICE);
        wakeLock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "musicbazi:playback");
        wakeLock.setReferenceCounted(false);

        audioManager = (AudioManager) getSystemService(Context.AUDIO_SERVICE);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent == null) {
            stopSelf();
            return START_NOT_STICKY;
        }

        if (ACTION_STOP.equals(intent.getAction())) {
            shutdown();
            return START_NOT_STICKY;
        }

        if (ACTION_SLEEP.equals(intent.getAction())) {
            // صفر یعنی لغو. `minutes` از JS می‌آید و همان چیزی است که کاربر در
            // اسلایدر دیده — اینجا فقط زمان‌سنجی می‌کند، تصمیم نمی‌گیرد
            armSleep(intent.getIntExtra("minutes", 0));
        }

        if (ACTION_SYNC.equals(intent.getAction())) {
            title = orEmpty(intent.getStringExtra("title"));
            artist = orEmpty(intent.getStringExtra("artist"));
            album = orEmpty(intent.getStringExtra("album"));
            playing = intent.getBooleanExtra("playing", false);
            positionMs = intent.getLongExtra("position", 0);
            durationMs = intent.getLongExtra("duration", 0);

            String url = orEmpty(intent.getStringExtra("artworkUrl"));
            if (!url.equals(artworkUrl)) {
                artworkUrl = url;
                artwork = null;
                loadArtwork(url);
            }

            publish();
        }

        // دکمه‌های هدفون و بلوتوث از همین‌جا به سشن می‌رسند
        MediaButtonReceiver.handleIntent(session, intent);
        return START_NOT_STICKY;
    }

    /** تایمرِ خواب را می‌نشاند (۰ = لغو) و قبلی را باطل می‌کند */
    private void armSleep(int minutes) {
        if (sleepTask != null) clock.removeCallbacks(sleepTask);
        sleepTask = null;
        if (minutes <= 0) return;

        sleepTask = () -> {
            sleepTask = null;
            // فقط زنگ: JS خودش pause می‌کند، نوتیفیکیشن را به‌روز می‌کند و
            // تایمرِ خودش را پاک می‌کند. مسیرِ موازیِ خاموش‌کردن نمی‌سازیم.
            emit("sleep", 0);
        };
        clock.postDelayed(sleepTask, minutes * 60_000L);
    }

    /** متادیتا + وضعیت + نوتیفیکیشن را با هم به‌روز می‌کند */
    private void publish() {
        session.setMetadata(new MediaMetadataCompat.Builder()
                .putString(MediaMetadataCompat.METADATA_KEY_TITLE, title)
                .putString(MediaMetadataCompat.METADATA_KEY_ARTIST, artist)
                .putString(MediaMetadataCompat.METADATA_KEY_ALBUM, album)
                .putLong(MediaMetadataCompat.METADATA_KEY_DURATION, durationMs)
                .putBitmap(MediaMetadataCompat.METADATA_KEY_ALBUM_ART, artwork)
                .build());

        session.setPlaybackState(new PlaybackStateCompat.Builder()
                .setActions(PlaybackStateCompat.ACTION_PLAY
                        | PlaybackStateCompat.ACTION_PAUSE
                        | PlaybackStateCompat.ACTION_PLAY_PAUSE
                        | PlaybackStateCompat.ACTION_SKIP_TO_NEXT
                        | PlaybackStateCompat.ACTION_SKIP_TO_PREVIOUS
                        | PlaybackStateCompat.ACTION_SEEK_TO
                        | PlaybackStateCompat.ACTION_STOP)
                .setState(
                        playing ? PlaybackStateCompat.STATE_PLAYING : PlaybackStateCompat.STATE_PAUSED,
                        positionMs,
                        playing ? 1f : 0f)
                .build());

        Notification notification = buildNotification();

        /*
         * سرویس فقط تا وقتی «پیش‌زمینه» است که چیزی پخش شود. با مکث از حالتِ
         * پیش‌زمینه بیرون می‌آید ولی نوتیفیکیشن می‌ماند (DETACH) تا کاربر بتواند
         * از همان‌جا دوباره ادامه بدهد — و اندروید هم اپِ مکث‌شده را دیگر
         * «در حال استفاده از منابع» حساب نکند.
         */
        if (playing) {
            requestAudioFocus();
            registerNoisyReceiver();
            startForeground(NOTIFICATION_ID, notification);
            if (!wakeLock.isHeld()) wakeLock.acquire(3 * 60 * 60 * 1000L);
        } else {
            pausedDueToTransientFocusLoss = false;
            abandonAudioFocus();
            unregisterNoisyReceiver();
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
                stopForeground(Service.STOP_FOREGROUND_DETACH);
            } else {
                stopForeground(false);
            }
            NotificationManager manager =
                    (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
            manager.notify(NOTIFICATION_ID, notification);
            if (wakeLock.isHeld()) wakeLock.release();
        }

        try {
            PlaybackWidget.update(this, title, artist, artwork, playing);
        } catch (Exception ignored) {
        }
    }

    private Notification buildNotification() {
        Intent open = new Intent(this, MainActivity.class);
        open.setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        PendingIntent content = PendingIntent.getActivity(
                this, 0, open, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);

        PendingIntent stop = MediaButtonReceiver.buildMediaButtonPendingIntent(
                this, PlaybackStateCompat.ACTION_STOP);

        NotificationCompat.Builder builder = new NotificationCompat.Builder(this, CHANNEL_ID)
                .setSmallIcon(R.drawable.ic_stat_playback)
                .setContentTitle(title)
                .setContentText(artist)
                .setSubText(album)
                .setLargeIcon(artwork)
                .setContentIntent(content)
                .setDeleteIntent(stop)
                .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
                .setShowWhen(false)
                .setOnlyAlertOnce(true)
                .setPriority(NotificationCompat.PRIORITY_LOW);

        builder.addAction(new NotificationCompat.Action(
                R.drawable.ic_media_prev,
                getString(R.string.media_prev),
                MediaButtonReceiver.buildMediaButtonPendingIntent(
                        this, PlaybackStateCompat.ACTION_SKIP_TO_PREVIOUS)));

        builder.addAction(new NotificationCompat.Action(
                playing ? R.drawable.ic_media_pause : R.drawable.ic_media_play,
                getString(playing ? R.string.media_pause : R.string.media_play),
                MediaButtonReceiver.buildMediaButtonPendingIntent(
                        this, PlaybackStateCompat.ACTION_PLAY_PAUSE)));

        builder.addAction(new NotificationCompat.Action(
                R.drawable.ic_media_next,
                getString(R.string.media_next),
                MediaButtonReceiver.buildMediaButtonPendingIntent(
                        this, PlaybackStateCompat.ACTION_SKIP_TO_NEXT)));

        builder.setStyle(new MediaStyle()
                .setMediaSession(session.getSessionToken())
                // هر سه دکمه در حالتِ جمع‌شده هم دیده می‌شوند
                .setShowActionsInCompactView(0, 1, 2)
                .setShowCancelButton(true)
                .setCancelButtonIntent(stop));

        return builder.build();
    }

    /**
     * کاور را در نخِ جدا می‌گیرد و بعد نوتیفیکیشن را دوباره می‌سازد.
     *
     * شکستش بی‌صداست: نوتیفیکیشنِ بدون کاور از نبودِ نوتیفیکیشن خیلی بهتر است،
     * و آدرسِ کاور ممکن است از CDNی بیاید که همان لحظه در دسترس نیست.
     */
    private void loadArtwork(final String url) {
        if (url.isEmpty()) return;

        artworkPool.execute(() -> {
            Bitmap bitmap = null;
            HttpURLConnection connection = null;
            try {
                connection = (HttpURLConnection) new URL(url).openConnection();
                connection.setConnectTimeout(8000);
                connection.setReadTimeout(8000);
                connection.setInstanceFollowRedirects(true);
                InputStream stream = connection.getInputStream();
                BitmapFactory.Options options = new BitmapFactory.Options();
                // کاورِ سه‌هزارپیکسلی برای نوتیفیکیشن اسراف است و حافظه را می‌خورد
                options.inSampleSize = 2;
                bitmap = BitmapFactory.decodeStream(stream, null, options);
                stream.close();
            } catch (Exception ignored) {
                // بدون کاور ادامه می‌دهیم
            } finally {
                if (connection != null) connection.disconnect();
            }

            if (bitmap == null) return;
            // نتیجه‌ی کاورِ ترکِ قبلی نباید روی ترکِ فعلی بنشیند
            if (!url.equals(artworkUrl)) return;

            final Bitmap decoded = bitmap;
            clock.post(() -> {
                if (!url.equals(artworkUrl)) return;
                artwork = decoded;
                publish();
            });
        });
    }

    private void shutdown() {
        abandonAudioFocus();
        unregisterNoisyReceiver();
        try {
            PlaybackWidget.update(this, "", "", null, false);
        } catch (Exception ignored) {
        }
        if (sleepTask != null) {
            clock.removeCallbacks(sleepTask);
            sleepTask = null;
        }
        if (wakeLock != null && wakeLock.isHeld()) wakeLock.release();
        session.setActive(false);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            stopForeground(Service.STOP_FOREGROUND_REMOVE);
        } else {
            stopForeground(true);
        }
        stopSelf();
    }

    private void createChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return;
        NotificationManager manager =
                (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager.getNotificationChannel(CHANNEL_ID) != null) return;

        NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID,
                getString(R.string.channel_playback),
                // IMPORTANCE_LOW: نوتیفیکیشنِ پخش نباید صدا یا لرزش بدهد
                NotificationManager.IMPORTANCE_LOW);
        channel.setDescription(getString(R.string.channel_playback_desc));
        channel.setShowBadge(false);
        channel.setLockscreenVisibility(Notification.VISIBILITY_PUBLIC);
        manager.createNotificationChannel(channel);
    }

    @Override
    public void onTaskRemoved(Intent rootIntent) {
        /*
         * کاربر اپ را از لیستِ اپ‌های اخیر بیرون انداخته. اگر چیزی پخش نمی‌شود
         * سرویس هم باید برود — وگرنه یک نوتیفیکیشنِ یتیم می‌ماند که هیچ صدایی
         * پشتش نیست. اگر پخش ادامه دارد، عمداً زنده می‌ماند.
         */
        if (!playing) shutdown();
        super.onTaskRemoved(rootIntent);
    }

    @Override
    public void onDestroy() {
        abandonAudioFocus();
        unregisterNoisyReceiver();
        if (sleepTask != null) clock.removeCallbacks(sleepTask);
        if (wakeLock != null && wakeLock.isHeld()) wakeLock.release();
        session.release();
        artworkPool.shutdownNow();
        super.onDestroy();
    }

    private void requestAudioFocus() {
        if (audioManager != null && audioManager.getMode() != AudioManager.MODE_NORMAL) {
            try {
                audioManager.setMode(AudioManager.MODE_NORMAL);
            } catch (Exception ignored) {
            }
        }
        if (hasAudioFocus || audioManager == null) return;
        int res;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            if (focusRequest == null) {
                AudioAttributes attrs = new AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_MEDIA)
                        .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
                        .build();
                focusRequest = new AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN)
                        .setAudioAttributes(attrs)
                        .setAcceptsDelayedFocusGain(true)
                        .setOnAudioFocusChangeListener(focusListener)
                        .build();
            }
            res = audioManager.requestAudioFocus(focusRequest);
        } else {
            res = audioManager.requestAudioFocus(
                    focusListener,
                    AudioManager.STREAM_MUSIC,
                    AudioManager.AUDIOFOCUS_GAIN
            );
        }
        hasAudioFocus = (res == AudioManager.AUDIOFOCUS_REQUEST_GRANTED);
    }

    private void abandonAudioFocus() {
        if (!hasAudioFocus || audioManager == null) return;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            if (focusRequest != null) {
                audioManager.abandonAudioFocusRequest(focusRequest);
            }
        } else {
            audioManager.abandonAudioFocus(focusListener);
        }
        hasAudioFocus = false;
    }

    private void registerNoisyReceiver() {
        if (noisyReceiverRegistered) return;
        try {
            registerReceiver(noisyReceiver, new IntentFilter(AudioManager.ACTION_AUDIO_BECOMING_NOISY));
            noisyReceiverRegistered = true;
        } catch (Exception ignored) {
        }
    }

    private void unregisterNoisyReceiver() {
        if (!noisyReceiverRegistered) return;
        try {
            unregisterReceiver(noisyReceiver);
        } catch (Exception ignored) {
        }
        noisyReceiverRegistered = false;
    }

    @Nullable
    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    private static String orEmpty(@Nullable String value) {
        return value == null ? "" : value;
    }
}
