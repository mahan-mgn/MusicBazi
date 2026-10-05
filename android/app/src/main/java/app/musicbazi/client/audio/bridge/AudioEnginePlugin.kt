/*
 * Copyright (C) 2026 Music Bazi / Unstream
 *
 * Licensed under the GNU General Public License v3.0 (GPL-3.0)
 */

package app.musicbazi.client.audio.bridge

import android.net.Uri
import androidx.media3.common.util.UnstableApi
import app.musicbazi.client.audio.core.AudioState
import app.musicbazi.client.audio.core.MusicBaziAudioEngine
import app.musicbazi.client.audio.output.AudioOutputStatus
import app.musicbazi.client.audio.service.NativePlaybackService
import app.musicbazi.client.audio.stream.ResolvedAudioStream
import app.musicbazi.client.audio.stream.StreamType
import com.getcapacitor.JSObject
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.CapacitorPlugin
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch

/**
 * Capacitor plugin bridging the Native Audiophile Audio Engine to React/Zustand UI.
 */
@UnstableApi
@CapacitorPlugin(name = "AudioEngine")
class AudioEnginePlugin : Plugin() {

    private val scope = CoroutineScope(Dispatchers.Main)
    private var stateJob: Job? = null
    private var lastEmittedPosition = -1L

    private val audioEngine: MusicBaziAudioEngine
        get() = NativePlaybackService.ensureInstance(context)

    override fun load() {
        super.load()
        stateJob = scope.launch {
            audioEngine.state.collectLatest { state ->
                emitStateEvents(state)
            }
        }

        NativePlaybackService.onActionCallback = { action, value ->
            val event = JSObject().apply {
                put("action", action)
                put("value", value / 1000.0)
            }
            notifyListeners("transport", event)
        }
    }

    override fun handleOnDestroy() {
        stateJob?.cancel()
        super.handleOnDestroy()
    }

    @PluginMethod
    fun play(call: PluginCall) {
        val urlString = call.getString("url")
        if (urlString.isNullOrEmpty()) {
            call.reject("URL cannot be empty")
            return
        }

        val streamTypeStr = call.getString("streamType") ?: "PROGRESSIVE"
        val streamType = runCatching { StreamType.valueOf(streamTypeStr.uppercase()) }.getOrDefault(StreamType.PROGRESSIVE)

        val stream = ResolvedAudioStream(
            uri = Uri.parse(urlString),
            mimeType = call.getString("mimeType"),
            codec = call.getString("codec"),
            bitrateBps = call.getInt("bitrate"),
            sampleRateHz = call.getInt("sampleRate"),
            bitDepth = call.getInt("bitDepth"),
            durationMs = call.getDouble("duration")?.let { (it * 1000).toLong() },
            isLossless = call.getBoolean("isLossless", false) ?: false,
            gainDb = call.getDouble("gainDb")?.toFloat(),
            sourceId = call.getString("sourceId") ?: "",
            streamType = streamType,
        )

        val title = call.getString("title") ?: ""
        val artist = call.getString("artist") ?: ""
        val album = call.getString("album") ?: ""
        val artworkUrl = call.getString("artworkUrl") ?: ""

        NativePlaybackService.updateMetadata(context, title, artist, album, artworkUrl)
        audioEngine.play(stream)
        call.resolve()
    }

    @PluginMethod
    fun pause(call: PluginCall) {
        audioEngine.pause()
        call.resolve()
    }

    @PluginMethod
    fun resume(call: PluginCall) {
        audioEngine.resume()
        call.resolve()
    }

    @PluginMethod
    fun stop(call: PluginCall) {
        audioEngine.stop()
        call.resolve()
    }

    @PluginMethod
    fun seek(call: PluginCall) {
        val positionSeconds = call.getDouble("position") ?: 0.0
        audioEngine.seekTo((positionSeconds * 1000).toLong())
        call.resolve()
    }

    @PluginMethod
    fun setVolume(call: PluginCall) {
        val volume = (call.getDouble("volume") ?: 1.0).toFloat()
        audioEngine.setVolume(volume)
        call.resolve()
    }

    @PluginMethod
    fun setEqualizer(call: PluginCall) {
        val enabled = call.getBoolean("enabled", false) ?: false
        val bandsArray = call.getArray("bands")

        if (bandsArray != null && bandsArray.length() > 0) {
            val bandsList = mutableListOf<Float>()
            for (i in 0 until bandsArray.length()) {
                bandsList.add(bandsArray.getDouble(i).toFloat())
            }
            audioEngine.setEqualizerBands(bandsList)
        }
        audioEngine.setEqualizerEnabled(enabled)
        call.resolve()
    }

    @PluginMethod
    fun setSpatialAudio(call: PluginCall) {
        val enabled = call.getBoolean("enabled", false) ?: false
        audioEngine.setSpatialAudioEnabled(enabled)
        call.resolve()
    }

    @PluginMethod
    fun getPlaybackState(call: PluginCall) {
        val state = audioEngine.state.value
        val result = JSObject().apply {
            put("status", state.status.name)
            put("isPlaying", state.isPlaying)
            put("currentTrackId", state.currentTrackId)
            put("position", state.positionMs / 1000.0)
            put("duration", state.durationMs / 1000.0)
            put("volume", state.volume)
            put("isBuffering", state.isBuffering)
            put("errorMessage", state.errorMessage)
        }
        call.resolve(result)
    }

    @PluginMethod
    fun getAudioDiagnostics(call: PluginCall) {
        val snapshot = AudioOutputStatus.current.value
        val result = JSObject().apply {
            put("sink", snapshot.sink)
            put("deviceName", snapshot.deviceName)
            put("routeKind", snapshot.routeKind.name)
            put("actualEncoding", snapshot.actualEncoding)
            put("actualSampleRateHz", snapshot.actualSampleRateHz)
            put("systemMixerRateHz", snapshot.systemMixerRateHz)
            put("decoderName", snapshot.decoderName)
            put("decoderOutputEncoding", snapshot.decoderOutputEncoding)
            put("dspFormat", snapshot.dspFormat)
            put("dspAvailable", snapshot.dspAvailable)
            put("directPlaybackSupported", snapshot.directPlaybackSupported)
            put("directPlaybackActual", snapshot.directPlaybackActual)
            put("outputExact", snapshot.outputExact)
            put("outputExactDetail", snapshot.outputExactDetail)
            put("loudnessGainDb", snapshot.loudnessGainDb)
            put("loudnessLufs", snapshot.loudnessLufs)
        }
        call.resolve(result)
    }

    private fun emitStateEvents(state: AudioState) {
        val stateEvent = JSObject().apply {
            put("status", state.status.name)
            put("isPlaying", state.isPlaying)
            put("isBuffering", state.isBuffering)
            put("currentTrackId", state.currentTrackId)
            put("duration", state.durationMs / 1000.0)
        }
        notifyListeners("playbackStateChanged", stateEvent)

        // Throttle position updates to 250ms interval
        val posSeconds = state.positionMs / 1000.0
        val posRounded = (posSeconds * 4).toLong()
        if (posRounded != lastEmittedPosition) {
            lastEmittedPosition = posRounded
            val posEvent = JSObject().apply {
                put("position", posSeconds)
                put("duration", state.durationMs / 1000.0)
            }
            notifyListeners("positionChanged", posEvent)
        }
    }
}
