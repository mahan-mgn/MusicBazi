/*
 * Copyright (C) 2026 Music Bazi / Unstream
 *
 * Licensed under the GNU General Public License v3.0 (GPL-3.0)
 */

package app.musicbazi.client.audio.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.os.Build
import android.os.IBinder
import android.support.v4.media.MediaMetadataCompat
import android.support.v4.media.session.MediaSessionCompat
import android.support.v4.media.session.PlaybackStateCompat
import androidx.core.app.NotificationCompat
import androidx.media.app.NotificationCompat.MediaStyle
import androidx.media.session.MediaButtonReceiver
import androidx.media3.common.util.UnstableApi
import app.musicbazi.client.MainActivity
import app.musicbazi.client.R
import app.musicbazi.client.audio.core.AudioState
import app.musicbazi.client.audio.core.MusicBaziAudioEngine
import app.musicbazi.client.audio.stream.ResolvedAudioStream
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors

/**
 * Foreground Service for Music Bazi Native Audio Playback.
 *
 * Holds the authoritative Native Audio Engine, MediaSession, and system notification controls.
 */
@UnstableApi
class NativePlaybackService : Service() {

    private val scope = CoroutineScope(Dispatchers.Main)
    private val imageExecutor = Executors.newSingleThreadExecutor()
    private var stateObserverJob: Job? = null

    private lateinit var mediaSession: MediaSessionCompat
    private var notificationManager: NotificationManager? = null

    private var currentTitle: String = ""
    private var currentArtist: String = ""
    private var currentAlbum: String = ""
    private var currentArtworkUrl: String = ""
    private var currentArtworkBitmap: Bitmap? = null

    override fun onCreate() {
        super.onCreate()
        ensureInstance(applicationContext)
        notificationManager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        createNotificationChannel()
        initMediaSession()
        observeAudioEngineState()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        MediaButtonReceiver.handleIntent(mediaSession, intent)
        when (intent?.action) {
            ACTION_PLAY -> audioEngine?.resume()
            ACTION_PAUSE -> audioEngine?.pause()
            ACTION_STOP -> {
                audioEngine?.stop()
                stopForeground(true)
                stopSelf()
            }
        }
        return START_NOT_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        stateObserverJob?.cancel()
        mediaSession.release()
        imageExecutor.shutdown()
        super.onDestroy()
    }

    private fun initMediaSession() {
        mediaSession = MediaSessionCompat(this, "MusicBaziMediaSession").apply {
            setCallback(object : MediaSessionCompat.Callback() {
                override fun onPlay() {
                    audioEngine?.resume()
                }

                override fun onPause() {
                    audioEngine?.pause()
                }

                override fun onStop() {
                    audioEngine?.stop()
                    stopForeground(true)
                    stopSelf()
                }

                override fun onSeekTo(pos: Long) {
                    audioEngine?.seekTo(pos)
                }

                override fun onSkipToNext() {
                    onActionCallback?.invoke("next", 0L)
                }

                override fun onSkipToPrevious() {
                    onActionCallback?.invoke("prev", 0L)
                }
            })
            isActive = true
        }
    }

    private fun observeAudioEngineState() {
        val engine = audioEngine ?: return
        stateObserverJob = scope.launch {
            engine.state.collect { state ->
                updatePlaybackState(state)
                updateNotification(state)
            }
        }
    }

    private fun updatePlaybackState(state: AudioState) {
        val playbackState = when {
            state.isBuffering -> PlaybackStateCompat.STATE_BUFFERING
            state.isPlaying -> PlaybackStateCompat.STATE_PLAYING
            state.status == AudioState.Status.READY -> PlaybackStateCompat.STATE_PAUSED
            state.status == AudioState.Status.ERROR -> PlaybackStateCompat.STATE_ERROR
            else -> PlaybackStateCompat.STATE_NONE
        }

        val stateBuilder = PlaybackStateCompat.Builder()
            .setActions(
                PlaybackStateCompat.ACTION_PLAY or
                    PlaybackStateCompat.ACTION_PAUSE or
                    PlaybackStateCompat.ACTION_SKIP_TO_NEXT or
                    PlaybackStateCompat.ACTION_SKIP_TO_PREVIOUS or
                    PlaybackStateCompat.ACTION_SEEK_TO or
                    PlaybackStateCompat.ACTION_STOP,
            )
            .setState(playbackState, state.positionMs, 1.0f)

        mediaSession.setPlaybackState(stateBuilder.build())
    }

    private fun updateNotification(state: AudioState) {
        if (state.status == AudioState.Status.IDLE) {
            stopForeground(false)
            return
        }

        val notification = buildNotification(state)
        if (state.isPlaying) {
            try {
                startForeground(NOTIFICATION_ID, notification)
            } catch (_: Exception) {
            }
        } else {
            notificationManager?.notify(NOTIFICATION_ID, notification)
        }
    }

    private fun buildNotification(state: AudioState): Notification {
        val contentIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )

        val playPauseIcon = if (state.isPlaying) {
            R.drawable.ic_media_pause
        } else {
            R.drawable.ic_media_play
        }

        val playPauseAction = if (state.isPlaying) {
            NotificationCompat.Action(
                playPauseIcon,
                "Pause",
                MediaButtonReceiver.buildMediaButtonPendingIntent(this, PlaybackStateCompat.ACTION_PAUSE),
            )
        } else {
            NotificationCompat.Action(
                playPauseIcon,
                "Play",
                MediaButtonReceiver.buildMediaButtonPendingIntent(this, PlaybackStateCompat.ACTION_PLAY),
            )
        }

        val prevAction = NotificationCompat.Action(
            R.drawable.ic_media_prev,
            "Previous",
            MediaButtonReceiver.buildMediaButtonPendingIntent(this, PlaybackStateCompat.ACTION_SKIP_TO_PREVIOUS),
        )

        val nextAction = NotificationCompat.Action(
            R.drawable.ic_media_next,
            "Next",
            MediaButtonReceiver.buildMediaButtonPendingIntent(this, PlaybackStateCompat.ACTION_SKIP_TO_NEXT),
        )

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_stat_playback)
            .setContentTitle(currentTitle.ifEmpty { "Music Bazi" })
            .setContentText(currentArtist)
            .setSubText(currentAlbum)
            .setLargeIcon(currentArtworkBitmap)
            .setContentIntent(contentIntent)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .setOngoing(state.isPlaying)
            .setShowWhen(false)
            .addAction(prevAction)
            .addAction(playPauseAction)
            .addAction(nextAction)
            .setStyle(
                MediaStyle()
                    .setMediaSession(mediaSession.sessionToken)
                    .setShowActionsInCompactView(0, 1, 2),
            )
            .build()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Music Bazi Playback",
                NotificationManager.IMPORTANCE_LOW,
            ).apply {
                description = "Music Bazi Media Playback Controls"
                setShowBadge(false)
            }
            notificationManager?.createNotificationChannel(channel)
        }
    }

    companion object {
        const val ACTION_PLAY = "app.musicbazi.client.ACTION_PLAY"
        const val ACTION_PAUSE = "app.musicbazi.client.ACTION_PAUSE"
        const val ACTION_STOP = "app.musicbazi.client.ACTION_STOP"
        private const val CHANNEL_ID = "musicbazi.native.playback"
        private const val NOTIFICATION_ID = 0x556

        @Volatile
        var audioEngine: MusicBaziAudioEngine? = null
            private set

        @Volatile
        var onActionCallback: ((action: String, value: Long) -> Unit)? = null

        fun ensureInstance(context: Context): MusicBaziAudioEngine {
            return audioEngine ?: synchronized(this) {
                audioEngine ?: MusicBaziAudioEngine(context.applicationContext).also {
                    audioEngine = it
                }
            }
        }

        fun updateMetadata(
            context: Context,
            title: String,
            artist: String,
            album: String,
            artworkUrl: String,
        ) {
            val intent = Intent(context, NativePlaybackService::class.java).apply {
                putExtra("title", title)
                putExtra("artist", artist)
                putExtra("album", album)
                putExtra("artworkUrl", artworkUrl)
            }
            try {
                context.startService(intent)
            } catch (_: Exception) {
            }
        }
    }
}
