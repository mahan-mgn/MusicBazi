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
import androidx.media3.datasource.cache.CacheDataSource
import androidx.media3.exoplayer.DefaultRenderersFactory
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.audio.AudioSink
import androidx.media3.exoplayer.audio.DefaultAudioSink
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import app.musicbazi.client.audio.dsp.DspChain
import app.musicbazi.client.audio.dsp.EqualizerPreset
import app.musicbazi.client.audio.dsp.EqCurve
import app.musicbazi.client.audio.dsp.PrecisionAudioSink
import app.musicbazi.client.audio.dsp.manualCurve
import app.musicbazi.client.audio.output.AudioOutputStatus
import app.musicbazi.client.audio.stream.AudioCacheManager
import app.musicbazi.client.audio.stream.MusicBaziDataSource
import app.musicbazi.client.audio.stream.ResolvedAudioStream
import app.musicbazi.client.audio.stream.StreamType
import app.musicbazi.client.audio.transition.CrossfadeController
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
 * Implements a Dual-ExoPlayer peer architecture with:
 * - Two full ExoPlayers (Player A and Player B) that trade roles upon handoff
 * - Dedicated per-player Float32 DspChain and PrecisionAudioSink instances
 * - CrossfadeController driving equal-power transitions and blend headroom trim
 * - Temporary LRU stream caching via Media3 SimpleCache
 * - Direct hardware / AudioTrack output negotiation telemetry
 */
@UnstableApi
class MusicBaziAudioEngine(
    private val context: Context,
    val dspChainA: DspChain = DspChain(),
    val dspChainB: DspChain = DspChain(),
    private val scope: CoroutineScope = CoroutineScope(Dispatchers.Main),
) {

    val dspChain: DspChain
        get() = activeDspChain

    private val mainHandler = Handler(Looper.getMainLooper())
    private val _state = MutableStateFlow(AudioState())
    val state: StateFlow<AudioState> = _state.asStateFlow()

    private var playerA: ExoPlayer? = null
    private var playerB: ExoPlayer? = null

    private var activePlayer: ExoPlayer? = null
    private var sparePlayer: ExoPlayer? = null
    private var activeDspChain: DspChain = dspChainA
    private var spareDspChain: DspChain = dspChainB

    private var crossfadeController: CrossfadeController? = null
    var crossfadeSeconds: Float = 0f

    private var progressJob: Job? = null
    private var currentStream: ResolvedAudioStream? = null

    init {
        runOnMain {
            initPlayers()
        }
    }

    private fun initPlayers() {
        playerA = buildPlayer(dspChainA) { activePlayer === playerA }
        playerB = buildPlayer(dspChainB) { activePlayer === playerB }

        activePlayer = playerA
        sparePlayer = playerB
        activeDspChain = dspChainA
        spareDspChain = dspChainB

        crossfadeController = CrossfadeController(
            scope = scope,
            active = { activePlayer ?: playerA!! },
            standby = { sparePlayer ?: playerB!! },
            onHandoff = { outgoing, incoming ->
                activePlayer = incoming
                sparePlayer = outgoing
                activeDspChain = if (incoming === playerA) dspChainA else dspChainB
                spareDspChain = if (incoming === playerA) dspChainB else dspChainA
            },
            crossfadeSeconds = { crossfadeSeconds },
            onBlendHeadroom = { /* Headroom scaling managed in sink */ },
        )
        crossfadeController?.start()
    }

    private fun buildPlayer(
        chain: DspChain,
        isAudibleFunc: () -> Boolean,
    ): ExoPlayer {
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
                    dspChain = chain,
                    enableFloatOutput = enableFloatOutput,
                    isAudible = isAudibleFunc,
                )
            }
        }

        val httpDataSourceFactory = DefaultHttpDataSource.Factory()
            .setAllowCrossProtocolRedirects(true)
            .setConnectTimeoutMs(15000)
            .setReadTimeoutMs(15000)

        val upstreamDataSourceFactory = DefaultDataSource.Factory(context, httpDataSourceFactory)

        // Integrated Media3 SimpleCache with LRU eviction for smooth streaming
        val cache = AudioCacheManager.getCache(context)
        val cacheDataSourceFactory = CacheDataSource.Factory()
            .setCache(cache)
            .setUpstreamDataSourceFactory(upstreamDataSourceFactory)
            .setFlags(CacheDataSource.FLAG_IGNORE_CACHE_ON_ERROR)

        val musicBaziDataSourceFactory = androidx.media3.datasource.DataSource.Factory {
            MusicBaziDataSource(upstream = cacheDataSourceFactory.createDataSource())
        }

        val mediaSourceFactory = DefaultMediaSourceFactory(context)
            .setDataSourceFactory(musicBaziDataSourceFactory)

        val audioAttributes = AudioAttributes.Builder()
            .setContentType(C.AUDIO_CONTENT_TYPE_MUSIC)
            .setUsage(C.USAGE_MEDIA)
            .build()

        return ExoPlayer.Builder(context, renderersFactory)
            .setMediaSourceFactory(mediaSourceFactory)
            .setAudioAttributes(audioAttributes, true)
            .setHandleAudioBecomingNoisy(true)
            .setWakeMode(C.WAKE_MODE_LOCAL)
            .build().apply {
                addListener(PlayerEventListener(this))
            }
    }

    fun play(stream: ResolvedAudioStream) {
        runOnMain {
            currentStream = stream
            val p = activePlayer ?: return@runOnMain

            // Level current track's loudness
            stream.gainDb?.let { gain ->
                activeDspChain.loudness.gainFor = { id -> if (id == stream.sourceId) gain else 1f }
                activeDspChain.loudness.track(stream.sourceId, null)
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
            activePlayer?.pause()
            sparePlayer?.pause()
            _state.value = _state.value.copy(isPlaying = false)
        }
    }

    fun resume() {
        runOnMain {
            activePlayer?.play()
            _state.value = _state.value.copy(isPlaying = true)
        }
    }

    fun stop() {
        runOnMain {
            crossfadeController?.bail()
            activePlayer?.stop()
            sparePlayer?.stop()
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
            crossfadeController?.onSkipRequested()
            activePlayer?.seekTo(positionMs)
            _state.value = _state.value.copy(positionMs = positionMs)
        }
    }

    fun setVolume(volume: Float) {
        runOnMain {
            val clamped = volume.coerceIn(0.0f, 1.0f)
            activePlayer?.volume = clamped
            _state.value = _state.value.copy(volume = clamped)
        }
    }

    // ---- DSP Controls (applied synchronously to both A & B peer chains) -----

    fun setEqualizerEnabled(enabled: Boolean) {
        dspChainA.equalizer.setTuning(enabled, EqCurve.FLAT, 0f)
        dspChainB.equalizer.setTuning(enabled, EqCurve.FLAT, 0f)
    }

    fun setEqualizerPreset(preset: EqualizerPreset) {
        val curve = manualCurve(preset.bands)
        dspChainA.equalizer.setTuning(true, curve, 0f)
        dspChainB.equalizer.setTuning(true, curve, 0f)
    }

    fun setEqualizerBands(bandsDb: List<Float>) {
        val curve = manualCurve(bandsDb)
        dspChainA.equalizer.setTuning(true, curve, 0f)
        dspChainB.equalizer.setTuning(true, curve, 0f)
    }

    fun setSpatialAudioEnabled(enabled: Boolean) {
        dspChainA.spatial.enabled = enabled
        dspChainB.spatial.enabled = enabled
    }

    fun release() {
        runOnMain {
            stopProgressTracker()
            crossfadeController?.release()
            crossfadeController = null
            playerA?.release()
            playerB?.release()
            playerA = null
            playerB = null
            activePlayer = null
            sparePlayer = null
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
                activePlayer?.let { p ->
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

    private inner class PlayerEventListener(private val sourcePlayer: ExoPlayer) : Player.Listener {
        override fun onPlaybackStateChanged(playbackState: Int) {
            if (sourcePlayer !== activePlayer) return

            val status = when (playbackState) {
                Player.STATE_IDLE -> AudioState.Status.IDLE
                Player.STATE_BUFFERING -> AudioState.Status.BUFFERING
                Player.STATE_READY -> AudioState.Status.READY
                Player.STATE_ENDED -> AudioState.Status.ENDED
                else -> AudioState.Status.IDLE
            }

            val duration = if (sourcePlayer.duration > 0) sourcePlayer.duration else 0L

            _state.value = _state.value.copy(
                status = status,
                isBuffering = playbackState == Player.STATE_BUFFERING,
                durationMs = duration,
                isPlaying = sourcePlayer.isPlaying,
            )
        }

        override fun onIsPlayingChanged(isPlaying: Boolean) {
            if (sourcePlayer === activePlayer) {
                _state.value = _state.value.copy(isPlaying = isPlaying)
            }
        }

        override fun onPlayerError(error: PlaybackException) {
            if (sourcePlayer === activePlayer) {
                Log.e(TAG, "ExoPlayer error [${error.errorCode}]: ${error.message}", error)
                _state.value = _state.value.copy(
                    status = AudioState.Status.ERROR,
                    isPlaying = false,
                    isBuffering = false,
                    errorMessage = error.message,
                )
            }
        }
    }

    companion object {
        private const val TAG = "MusicBaziAudioEngine"
        private const val PROGRESS_INTERVAL_MS = 250L
    }
}
