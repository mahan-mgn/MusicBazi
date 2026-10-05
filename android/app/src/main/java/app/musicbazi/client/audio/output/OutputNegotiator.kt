/*
 * Copyright (C) 2024-2026 Kushagra Singh / BitChord Contributors
 * Ported to Music Bazi (app.musicbazi.client.audio.output)
 *
 * Licensed under the GNU General Public License v3.0 (GPL-3.0)
 */

package app.musicbazi.client.audio.output

import android.media.AudioFormat
import app.musicbazi.client.audio.bluetooth.BluetoothTelemetry
import app.musicbazi.client.audio.pcm.PcmEncoding

enum class TransportType(val label: String) {
    AUDIO_TRACK("AudioTrack"),
    AUDIO_TRACK_DIRECT("AudioTrack (Direct)"),
    DIRECT_USB("Direct USB"),
}

enum class FallbackReason(val label: String) {
    NONE("None"),
    UNSUPPORTED_FORMAT("Unsupported source format"),
    ROUTE_LIMITATION("Route limitation (device profile)"),
    OS_LIMITATION("OS limitation (system audio policy)"),
    DIRECT_USB_UNAVAILABLE("Direct USB unavailable"),
    DECODER_LIMITATION("Decoder limitation"),
}

data class SourceDescriptor(
    val encoding: String,
    val sampleRateHz: Int,
    val channelCount: Int,
    val bitDepth: Int?,
)

data class DecoderDescriptor(
    val name: String?,
    val encoding: String = "Float32",
    val sampleRateHz: Int,
    val channelCount: Int,
)

data class DspDescriptor(
    val format: String = "Float32",
    val sampleRateHz: Int,
    val channelCount: Int,
)

data class RouteDescriptor(
    val kind: AudioRouting.Kind,
    val deviceName: String,
    val isDirectUsbCapable: Boolean = false,
    val advertisedEncodings: List<Int> = emptyList(),
    val advertisedSampleRates: List<Int> = emptyList(),
    val directSupport: DirectAudioProbe.DirectSupport = DirectAudioProbe.DirectSupport.NONE,
    val bluetoothTelemetry: BluetoothTelemetry? = null,
)

data class OutputDescriptor(
    val transport: TransportType,
    val encoding: PcmEncoding,
    val sampleRateHz: Int,
    val channelCount: Int,
    val isDirect: Boolean = false,
    val systemMixerRateHz: Int? = null,
    val fallbackReason: FallbackReason = FallbackReason.NONE,
    val fallbackDetail: String? = null,
)

data class OutputNegotiationResult(
    val source: SourceDescriptor,
    val decoder: DecoderDescriptor,
    val dsp: DspDescriptor,
    val route: RouteDescriptor,
    val output: OutputDescriptor,
) {
    val isSampleRatePreserved: Boolean
        get() = output.isDirect || output.systemMixerRateHz == null || output.sampleRateHz == output.systemMixerRateHz
}

object OutputNegotiator {

    fun negotiate(
        source: SourceDescriptor,
        decoderName: String?,
        decoderEncoding: String = "Float32",
        sampleRateHz: Int,
        channelCount: Int,
        routeKind: AudioRouting.Kind,
        deviceName: String,
        advertisedEncodings: List<Int>,
        advertisedSampleRates: List<Int>,
        requestedMode: OutputPcmMode = OutputPcmMode.FLOAT_32,
        directSupport: DirectAudioProbe.DirectSupport = DirectAudioProbe.DirectSupport.NONE,
        bluetoothTelemetry: BluetoothTelemetry? = null,
        delegateSupportsFloat: Boolean = true,
        delegateSupportsPcm24: Boolean = true,
        knownSystemMixerRateHz: Int? = null,
    ): OutputNegotiationResult {
        val decoder = DecoderDescriptor(
            name = decoderName,
            encoding = decoderEncoding,
            sampleRateHz = sampleRateHz,
            channelCount = channelCount,
        )

        val dsp = DspDescriptor(
            format = "Float32",
            sampleRateHz = sampleRateHz,
            channelCount = channelCount,
        )

        val route = RouteDescriptor(
            kind = routeKind,
            deviceName = deviceName,
            isDirectUsbCapable = false,
            advertisedEncodings = advertisedEncodings,
            advertisedSampleRates = advertisedSampleRates,
            directSupport = directSupport,
            bluetoothTelemetry = bluetoothTelemetry,
        )

        val output = selectBestOutput(
            source = source,
            sampleRateHz = sampleRateHz,
            channelCount = channelCount,
            routeKind = routeKind,
            advertisedEncodings = advertisedEncodings,
            advertisedSampleRates = advertisedSampleRates,
            requestedMode = requestedMode,
            directSupport = directSupport,
            bluetoothTelemetry = bluetoothTelemetry,
            delegateSupportsFloat = delegateSupportsFloat,
            delegateSupportsPcm24 = delegateSupportsPcm24,
            knownSystemMixerRateHz = knownSystemMixerRateHz,
        )

        return OutputNegotiationResult(
            source = source,
            decoder = decoder,
            dsp = dsp,
            route = route,
            output = output,
        )
    }

    private fun selectBestOutput(
        source: SourceDescriptor,
        sampleRateHz: Int,
        channelCount: Int,
        routeKind: AudioRouting.Kind,
        advertisedEncodings: List<Int>,
        advertisedSampleRates: List<Int>,
        requestedMode: OutputPcmMode,
        directSupport: DirectAudioProbe.DirectSupport,
        bluetoothTelemetry: BluetoothTelemetry?,
        delegateSupportsFloat: Boolean,
        delegateSupportsPcm24: Boolean,
        knownSystemMixerRateHz: Int?,
    ): OutputDescriptor {
        val advertisesFloat = advertisedEncodings.contains(AudioFormat.ENCODING_PCM_FLOAT)
        val advertisesPcm24 = advertisedEncodings.contains(AudioFormat.ENCODING_PCM_24BIT_PACKED)

        // 1. Phone Speaker Safety Rule: Always cap at PCM16
        if (routeKind == AudioRouting.Kind.PHONE) {
            val fallbackReason = if (requestedMode == OutputPcmMode.FLOAT_32) {
                FallbackReason.ROUTE_LIMITATION
            } else {
                FallbackReason.NONE
            }
            val fallbackDetail = if (fallbackReason != FallbackReason.NONE) {
                "Speaker output capped at 16-bit PCM to prevent OEM mixer distortion"
            } else {
                null
            }
            return OutputDescriptor(
                transport = TransportType.AUDIO_TRACK,
                encoding = PcmEncoding.PCM_16BIT,
                sampleRateHz = sampleRateHz,
                channelCount = channelCount,
                isDirect = false,
                systemMixerRateHz = knownSystemMixerRateHz,
                fallbackReason = fallbackReason,
                fallbackDetail = fallbackDetail,
            )
        }

        // 2. Android DIRECT Playback Evaluation (API 33+)
        if (requestedMode == OutputPcmMode.FLOAT_32 && directSupport.supportsFloat && delegateSupportsFloat) {
            return OutputDescriptor(
                transport = TransportType.AUDIO_TRACK_DIRECT,
                encoding = PcmEncoding.PCM_FLOAT,
                sampleRateHz = sampleRateHz,
                channelCount = channelCount,
                isDirect = true,
                systemMixerRateHz = null,
                fallbackReason = FallbackReason.NONE,
                fallbackDetail = null,
            )
        }

        val isSourceHighRes = (source.bitDepth ?: 16) > 16
        if (requestedMode != OutputPcmMode.PCM_16 && isSourceHighRes && directSupport.supportsPcm24 && delegateSupportsPcm24) {
            val fallbackReason = if (requestedMode == OutputPcmMode.FLOAT_32 && !directSupport.supportsFloat) {
                FallbackReason.ROUTE_LIMITATION
            } else {
                FallbackReason.NONE
            }
            val fallbackDetail = if (fallbackReason != FallbackReason.NONE) {
                "Route exposes direct 24-bit PCM (Float32 converted to packed 24-bit)"
            } else {
                null
            }
            return OutputDescriptor(
                transport = TransportType.AUDIO_TRACK_DIRECT,
                encoding = PcmEncoding.PCM_24BIT_PACKED,
                sampleRateHz = sampleRateHz,
                channelCount = channelCount,
                isDirect = true,
                systemMixerRateHz = null,
                fallbackReason = fallbackReason,
                fallbackDetail = fallbackDetail,
            )
        }

        if (directSupport.supportsPcm16) {
            val fallbackReason = when {
                requestedMode == OutputPcmMode.PCM_16 -> FallbackReason.NONE
                requestedMode == OutputPcmMode.FLOAT_32 -> FallbackReason.ROUTE_LIMITATION
                isSourceHighRes -> FallbackReason.ROUTE_LIMITATION
                else -> FallbackReason.NONE
            }
            val fallbackDetail = when {
                requestedMode == OutputPcmMode.FLOAT_32 ->
                    "Route does not expose direct Float32 or 24-bit PCM (using direct 16-bit PCM)"
                isSourceHighRes ->
                    "Route does not expose direct 24-bit PCM (using direct 16-bit PCM)"
                else -> null
            }
            return OutputDescriptor(
                transport = TransportType.AUDIO_TRACK_DIRECT,
                encoding = PcmEncoding.PCM_16BIT,
                sampleRateHz = sampleRateHz,
                channelCount = channelCount,
                isDirect = true,
                systemMixerRateHz = null,
                fallbackReason = fallbackReason,
                fallbackDetail = fallbackDetail,
            )
        }

        // 3. External Route Advertised Capabilities
        val canUseFloat = AudioOutputPolicy.shouldUseFloatOutput(requestedMode, routeKind, advertisesFloat) &&
            delegateSupportsFloat
        if (canUseFloat) {
            return OutputDescriptor(
                transport = TransportType.AUDIO_TRACK,
                encoding = PcmEncoding.PCM_FLOAT,
                sampleRateHz = sampleRateHz,
                channelCount = channelCount,
                isDirect = false,
                systemMixerRateHz = knownSystemMixerRateHz,
                fallbackReason = FallbackReason.NONE,
                fallbackDetail = null,
            )
        }

        if (requestedMode != OutputPcmMode.PCM_16 && isSourceHighRes && advertisesPcm24 && delegateSupportsPcm24) {
            val fallbackReason = if (requestedMode == OutputPcmMode.FLOAT_32) {
                FallbackReason.ROUTE_LIMITATION
            } else {
                FallbackReason.NONE
            }
            val fallbackDetail = if (fallbackReason != FallbackReason.NONE) {
                "${routeKind.name} route advertises 24-bit PCM (Float32 converted to packed 24-bit)"
            } else {
                null
            }
            return OutputDescriptor(
                transport = TransportType.AUDIO_TRACK,
                encoding = PcmEncoding.PCM_24BIT_PACKED,
                sampleRateHz = sampleRateHz,
                channelCount = channelCount,
                isDirect = false,
                systemMixerRateHz = knownSystemMixerRateHz,
                fallbackReason = fallbackReason,
                fallbackDetail = fallbackDetail,
            )
        }

        // 4. 16-bit PCM Fallback
        val (reason, detail) = when {
            routeKind == AudioRouting.Kind.BLUETOOTH -> {
                val btSummary = bluetoothTelemetry?.codecName?.let { " ($it)" }.orEmpty()
                Pair(
                    FallbackReason.ROUTE_LIMITATION,
                    "Bluetooth route$btSummary advertises 16-bit PCM only",
                )
            }
            requestedMode == OutputPcmMode.FLOAT_32 -> {
                Pair(
                    FallbackReason.ROUTE_LIMITATION,
                    "${routeKind.name} route advertises 16-bit PCM only",
                )
            }
            isSourceHighRes && requestedMode != OutputPcmMode.PCM_16 -> {
                Pair(
                    FallbackReason.ROUTE_LIMITATION,
                    "${routeKind.name} route does not expose high-res output",
                )
            }
            else -> {
                Pair(FallbackReason.NONE, null)
            }
        }

        return OutputDescriptor(
            transport = TransportType.AUDIO_TRACK,
            encoding = PcmEncoding.PCM_16BIT,
            sampleRateHz = sampleRateHz,
            channelCount = channelCount,
            isDirect = false,
            systemMixerRateHz = knownSystemMixerRateHz,
            fallbackReason = reason,
            fallbackDetail = detail,
        )
    }
}
