/*
 * Copyright (C) 2026 Music Bazi / Unstream
 *
 * Licensed under the GNU General Public License v3.0 (GPL-3.0)
 */

package app.musicbazi.client.audio.core

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.util.Log
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DefaultDataSource
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.DefaultRenderersFactory
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.audio.AudioSink
import androidx.media3.exoplayer.audio.DefaultAudioSink
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import app.musicbazi.client.audio.dsp.DspChain
import app.musicbazi.client.audio.dsp.EqualizerPreset
import app.musicbazi.client.audio.dsp.PrecisionAudioSink
import app.musicbazi.client.audio.dsp.manualCurve
import app.musicbazi.client.audio.output.AudioOutputStatus
import app.musicbazi.client.audio.output.AudioRouting
import app.musicbazi.client.audio.stream.MusicBaziDataSource
import app.musicbazi.client.audio.stream.ResolvedAudioStream
import app.musicbazi.client.audio.stream.StreamType
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * Native Audiophile Audio Engine for Music Bazi on Android.
 *
 * Provider-independent audio runtime using Media3 ExoPlayer + PrecisionAudioSink + Float32 DspChain.
 * Serves as the authoritative playback state on Android.
 */
@UnstableApi
class MusicBaziAudioEngine(
    private val context: Context,
    val dspChain: DspChain = DspChain(),
    private val scope: CoroutineScope = CoroutineScope(Dispatchers.Main),
) {

    private val mainHandler = Handler(Looper.getMainLooper())
    private val _state = MutableStateFlow(AudioState())
    val state: StateFlow<AudioState> = _state.asStateFlow()

    private var player: ExoPlayer? = null
    private var progressJob: Job? = null
    private var currentStream: ResolvedAudioStream? = null

    init {
        runOnMain {
            initPlayer()
        }
    }

    private fun initPlayer() {
        val renderersFactory = object : DefaultRenderersFactory(context) {
            override fun buildAudioSink(
                context: Context,
                enableFloatOutput: Boolean,
                enableAudioTrackPlaybackParams: Boolean,
            ): AudioSink {
                val defaultSink = DefaultAudioSink.Builder(context)
                    .setEnableFloatOutput(enableFloatOutput)
                    .setEnableAudioTrackPlaybackParams(enableAudioTrackPlaybackParams || enableFloatOutput)
                    .build()

                return PrecisionAudioSink(
                    delegate = defaultSink,
                    dspChain = dspChain,
                    enableFloatOutput = enableFloatOutput,
                    isAudible = { true },
                )
            }
        }

        val httpDataSourceFactory = DefaultHttpDataSource.Factory()
            .setAllowCrossProtocolRedirects(true)
            .setConnectTimeoutMs(15000)
            .setReadTimeoutMs(15000)

        val upstreamDataSourceFactory = DefaultDataSource.Factory(context, httpDataSourceFactory)
        val musicBaziDataSourceFactory = androidx.media3.datasource.DataSource.Factory {
            MusicBaziDataSource(upstream = upstreamDataSourceFactory.createDataSource())
        }

        val mediaSourceFactory = DefaultMediaSourceFactory(context)
            .setDataSourceFactory(musicBaziDataSourceFactory)

        val audioAttributes = AudioAttributes.Builder()
            .setContentType(C.AUDIO_CONTENT_TYPE_MUSIC)
            .setUsage(C.USAGE_MEDIA)
            .build()

        player = ExoPlayer.Builder(context, renderersFactory)
            .setMediaSourceFactory(mediaSourceFactory)
            .setAudioAttributes(audioAttributes, true) // true = handle audio focus automatically
            .setHandleAudioBecomingNoisy(true)
            .setWakeMode(C.WAKE_MODE_LOCAL)
            .build().apply {
                addListener(PlayerEventListener())
            }
    }

    fun play(stream: ResolvedAudioStream) {
        runOnMain {
            currentStream = stream
            val p = player ?: return@runOnMain

            // Notify loudness processor of the new track's gain
            stream.gainDb?.let { gain ->
                dspChain.loudness.gainFor = { id -> if (id == stream.sourceId) gain else 1f }
                dspChain.loudness.track(stream.sourceId, null)
                AudioOutputStatus.publishLoudness(gain, null)
            }

            val mediaItem = buildMediaItem(stream)
            p.setMediaItem(mediaItem)
            p.prepare()
            p.play()

            _state.value = _state.value.copy(
                currentTrackId = stream.sourceId,
                status = AudioState.Status.BUFFERING,
                isBuffering = true,
                errorMessage = null,
            )
            startProgressTracker()
        }
    }

    fun pause() {
        runOnMain {
            player?.pause()
            _state.value = _state.value.copy(isPlaying = false)
        }
    }

    fun resume() {
        runOnMain {
            player?.play()
            _state.value = _state.value.copy(isPlaying = true)
        }
    }

    fun stop() {
        runOnMain {
            player?.stop()
            stopProgressTracker()
            _state.value = _state.value.copy(
                status = AudioState.Status.IDLE,
                isPlaying = false,
                isBuffering = false,
                positionMs = 0L,
            )
        }
    }

    fun seekTo(positionMs: Long) {
        runOnMain {
            player?.seekTo(positionMs)
            _state.value = _state.value.copy(positionMs = positionMs)
        }
    }

    fun setVolume(volume: Float) {
        runOnMain {
            val clamped = volume.coerceIn(0.0f, 1.0f)
            player?.volume = clamped
            _state.value = _state.value.copy(volume = clamped)
        }
    }

    // ---- DSP Controls ------------------------------------------------------

    fun setEqualizerEnabled(enabled: Boolean) {
        dspChain.equalizer.setTuning(
            enabled = enabled,
            curve = app.musicbazi.client.audio.dsp.EqCurve.FLAT,
            balance = 0f,
        )
    }

    fun setEqualizerPreset(preset: EqualizerPreset) {
        dspChain.equalizer.setTuning(
            enabled = true,
            curve = manualCurve(preset.bands),
            balance = 0f,
        )
    }

    fun setEqualizerBands(bandsDb: List<Float>) {
        dspChain.equalizer.setTuning(
            enabled = true,
            curve = manualCurve(bandsDb),
            balance = 0f,
        )
    }

    fun setSpatialAudioEnabled(enabled: Boolean) {
        dspChain.spatial.enabled = enabled
    }

    fun release() {
        runOnMain {
            stopProgressTracker()
            player?.release()
            player = null
        }
    }

    private fun buildMediaItem(stream: ResolvedAudioStream): MediaItem {
        val builder = MediaItem.Builder()
            .setUri(stream.uri)
            .setMediaId(stream.sourceId)

        when (stream.streamType) {
            StreamType.HLS -> builder.setMimeType(androidx.media3.common.MimeTypes.APPLICATION_M3U8)
            StreamType.DASH -> builder.setMimeType(androidx.media3.common.MimeTypes.APPLICATION_MPD)
            else -> stream.mimeType?.let { builder.setMimeType(it) }
        }

        return builder.build()
    }

    private fun startProgressTracker() {
        progressJob?.cancel()
        progressJob = scope.launch {
            while (isActive) {
                player?.let { p ->
                    if (p.isPlaying) {
                        _state.value = _state.value.copy(
                            positionMs = p.currentPosition,
                            durationMs = if (p.duration > 0) p.duration else _state.value.durationMs,
                            isPlaying = true,
                        )
                    }
                }
                delay(PROGRESS_INTERVAL_MS)
            }
        }
    }

    private fun stopProgressTracker() {
        progressJob?.cancel()
        progressJob = null
    }

    private fun runOnMain(block: () -> Unit) {
        if (Looper.myLooper() == Looper.getMainLooper()) {
            block()
        } else {
            mainHandler.post(block)
        }
    }

    private inner class PlayerEventListener : Player.Listener {
        override fun onPlaybackStateChanged(playbackState: Int) {
            val status = when (playbackState) {
                Player.STATE_IDLE -> AudioState.Status.IDLE
                Player.STATE_BUFFERING -> AudioState.Status.BUFFERING
                Player.STATE_READY -> AudioState.Status.READY
                Player.STATE_ENDED -> AudioState.Status.ENDED
                else -> AudioState.Status.IDLE
            }

            val p = player
            val duration = if (p != null && p.duration > 0) p.duration else 0L

            _state.value = _state.value.copy(
                status = status,
                isBuffering = playbackState == Player.STATE_BUFFERING,
                durationMs = duration,
                isPlaying = p?.isPlaying == true,
            )
        }

        override fun onIsPlayingChanged(isPlaying: Boolean) {
            _state.value = _state.value.copy(isPlaying = isPlaying)
        }

        override fun onPlayerError(error: PlaybackException) {
            Log.e(TAG, "ExoPlayer error [${error.errorCode}]: ${error.message}", error)
            _state.value = _state.value.copy(
                status = AudioState.Status.ERROR,
                isPlaying = false,
                isBuffering = false,
                errorMessage = error.message,
            )
        }
    }

    companion object {
        private const val TAG = "MusicBaziAudioEngine"
        private const val PROGRESS_INTERVAL_MS = 250L
    }
}
