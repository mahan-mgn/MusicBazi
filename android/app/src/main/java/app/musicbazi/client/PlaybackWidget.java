package app.musicbazi.client;

import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.support.v4.media.session.PlaybackStateCompat;
import android.widget.RemoteViews;

import androidx.media.session.MediaButtonReceiver;

public class PlaybackWidget extends AppWidgetProvider {

    private static String lastTitle = "";
    private static String lastArtist = "";
    private static Bitmap lastArtwork = null;
    private static boolean lastPlaying = false;

    @Override
    public void onUpdate(Context context, AppWidgetManager appWidgetManager, int[] appWidgetIds) {
        updateViews(context, appWidgetManager, appWidgetIds, lastTitle, lastArtist, lastArtwork, lastPlaying);
    }

    public static void update(Context context, String title, String artist, Bitmap artwork, boolean playing) {
        lastTitle = title != null ? title : "";
        lastArtist = artist != null ? artist : "";
        lastArtwork = artwork;
        lastPlaying = playing;

        AppWidgetManager manager = AppWidgetManager.getInstance(context);
        ComponentName component = new ComponentName(context, PlaybackWidget.class);
        int[] ids = manager.getAppWidgetIds(component);
        if (ids != null && ids.length > 0) {
            updateViews(context, manager, ids, lastTitle, lastArtist, lastArtwork, lastPlaying);
        }
    }

    private static void updateViews(
            Context context,
            AppWidgetManager manager,
            int[] appWidgetIds,
            String title,
            String artist,
            Bitmap artwork,
            boolean playing) {

        for (int id : appWidgetIds) {
            RemoteViews views = new RemoteViews(context.getPackageName(), R.layout.widget_playback);

            views.setTextViewText(R.id.widget_title, title.isEmpty() ? context.getString(R.string.app_name) : title);
            views.setTextViewText(R.id.widget_artist, artist);

            if (artwork != null) {
                views.setImageViewBitmap(R.id.widget_artwork, artwork);
            } else {
                views.setImageViewResource(R.id.widget_artwork, R.mipmap.ic_launcher);
            }

            views.setImageViewResource(
                    R.id.widget_btn_play_pause,
                    playing ? R.drawable.ic_media_pause : R.drawable.ic_media_play);

            Intent openApp = new Intent(context, MainActivity.class);
            openApp.setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP);
            PendingIntent openPending = PendingIntent.getActivity(
                    context, 0, openApp, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
            views.setOnClickPendingIntent(R.id.widget_root, openPending);

            views.setOnClickPendingIntent(
                    R.id.widget_btn_prev,
                    MediaButtonReceiver.buildMediaButtonPendingIntent(
                            context, PlaybackStateCompat.ACTION_SKIP_TO_PREVIOUS));

            views.setOnClickPendingIntent(
                    R.id.widget_btn_play_pause,
                    MediaButtonReceiver.buildMediaButtonPendingIntent(
                            context, PlaybackStateCompat.ACTION_PLAY_PAUSE));

            views.setOnClickPendingIntent(
                    R.id.widget_btn_next,
                    MediaButtonReceiver.buildMediaButtonPendingIntent(
                            context, PlaybackStateCompat.ACTION_SKIP_TO_NEXT));

            manager.updateAppWidget(id, views);
        }
    }
}
