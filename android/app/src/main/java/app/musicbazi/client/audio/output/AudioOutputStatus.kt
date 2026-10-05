/*
 * Copyright (C) 2024-2026 Kushagra Singh / BitChord Contributors
 * Ported to Music Bazi (app.musicbazi.client.audio.output)
 *
 * Licensed under the GNU General Public License v3.0 (GPL-3.0)
 */

package app.musicbazi.client.audio.output

import android.media.AudioFormat
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Live runtime state of the Android audio output pipeline and DSP status.
 */
object AudioOutputStatus {

    data class Snapshot(
        val sink: String = "AudioTrack",
        val deviceName: String = "System default",
        val activeDeviceId: Int? = null,
        val routeKind: AudioRouting.Kind = AudioRouting.Kind.PHONE,
        val actualEncoding: Int? = null,
        val actualSampleRateHz: Int? = null,
        val systemMixerRateHz: Int? = null,
        val decoderName: String? = null,
        val bufferSize: Int? = null,
        val decoderOutputEncoding: String? = null,
        val dspFormat: String = "Float32",
        val dspAvailable: Boolean = true,
        val directPlaybackSupported: Boolean = false,
        val directPlaybackActual: Boolean = false,
        val outputExact: Boolean = false,
        val outputExactDetail: String? = null,
        val loudnessGainDb: Float? = null,
        val loudnessLufs: Float? = null,
    )

    private val _current = MutableStateFlow(Snapshot())
    val current: StateFlow<Snapshot> = _current.asStateFlow()

    fun publishDecoder(decoderName: String?) {
        _current.value = _current.value.copy(decoderName = decoderName)
    }

    fun publishDsp(
        decoderOutputEncoding: String?,
        dspFormat: String = "Float32",
        dspAvailable: Boolean = true,
    ) {
        _current.value = _current.value.copy(
            decoderOutputEncoding = decoderOutputEncoding,
            dspFormat = dspFormat,
            dspAvailable = dspAvailable,
        )
    }

    fun publishOutputExactness(exact: Boolean, detail: String?) {
        _current.value = _current.value.copy(
            outputExact = exact,
            outputExactDetail = detail,
        )
    }

    fun publishLoudness(gainDb: Float?, lufs: Float?) {
        val snapshot = _current.value
        if (snapshot.loudnessGainDb == gainDb && snapshot.loudnessLufs == lufs) return
        _current.value = snapshot.copy(loudnessGainDb = gainDb, loudnessLufs = lufs)
    }

    fun publishAudioTrack(encoding: Int, sampleRateHz: Int, bufferSize: Int? = null) {
        _current.value = _current.value.copy(
            actualEncoding = encoding,
            actualSampleRateHz = sampleRateHz,
            bufferSize = bufferSize ?: _current.value.bufferSize,
        )
    }

    fun publishRoute(deviceName: String, routeKind: AudioRouting.Kind, activeDeviceId: Int?) {
        _current.value = _current.value.copy(
            deviceName = deviceName,
            routeKind = routeKind,
            activeDeviceId = activeDeviceId,
        )
    }
}
