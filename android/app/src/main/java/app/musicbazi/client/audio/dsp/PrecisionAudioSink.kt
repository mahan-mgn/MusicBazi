/*
 * Copyright (C) 2024-2026 Kushagra Singh / BitChord Contributors
 * Ported to Music Bazi (app.musicbazi.client.audio.dsp)
 *
 * Licensed under the GNU General Public License v3.0 (GPL-3.0)
 */

package app.musicbazi.client.audio.dsp

import android.util.Log
import androidx.media3.common.C
import androidx.media3.common.Format
import androidx.media3.common.MimeTypes
import androidx.media3.common.util.UnstableApi
import androidx.media3.common.util.Util
import androidx.media3.exoplayer.audio.AudioSink
import androidx.media3.exoplayer.audio.ForwardingAudioSink
import app.musicbazi.client.BuildConfig
import app.musicbazi.client.audio.output.AudioOutputStatus
import app.musicbazi.client.audio.pcm.AudioBlock
import app.musicbazi.client.audio.pcm.PcmBoundary
import app.musicbazi.client.audio.pcm.PcmEncoding
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Precision audio sink intercepting decoder PCM buffers before Media3's internal
 * processing pipeline can bypass Music Bazi's custom DSP chain.
 *
 * Pipeline:
 * Decoder PCM -> PcmBoundary.decode -> AudioBlock (Float32) -> DspChain (Spatial -> EQ -> Transition -> Loudness)
 *   -> PcmBoundary.encode -> delegate [AudioSink].
 */
@UnstableApi
class PrecisionAudioSink(
    private val delegate: AudioSink,
    val dspChain: DspChain,
    private val enableFloatOutput: Boolean = true,
    private val preferredOutputEncodingProvider: ((Format) -> PcmEncoding?)? = null,
    private val isAudible: () -> Boolean = { true },
) : ForwardingAudioSink(delegate) {

    var isPrecisionActive: Boolean = false
        private set

    var inputPcmEncoding: PcmEncoding? = null
        private set

    var targetOutputEncoding: PcmEncoding? = null
        private set

    var activeFormat: Format? = null
        private set

    private var processCounter: Long = 0L
    private var configuredSampleRate: Int = 0

    private var audioBlock: AudioBlock = AudioBlock(
        channelCount = AudioBlock.DEFAULT_CHANNELS,
        capacityFrames = DEFAULT_CAPACITY_FRAMES,
    )

    private var outputByteBuffer: ByteBuffer = ByteBuffer.allocateDirect(0).order(ByteOrder.nativeOrder())

    private var pendingPresentationTimeUs: Long = C.TIME_UNSET
    private var pendingAccessUnitCount: Int = 0
    private var timestampedInputTimeUs: Long = C.TIME_UNSET
    private var framesEmittedForInput: Long = 0L
    private var streaming = false
    private var processedEndUs: Long = C.TIME_UNSET

    override fun configure(audioSinkConfig: AudioSink.AudioSinkConfig) {
        val format = audioSinkConfig.format
        activeFormat = format

        if (shouldActivatePrecision(format)) {
            val encoding = mapToPcmEncoding(format.pcmEncoding)
            if (encoding != null) {
                val sampleRate = format.sampleRate
                val channelCount = format.channelCount

                dspChain.configure(sampleRate, channelCount)
                ensureBuffers(channelCount)
                configuredSampleRate = sampleRate

                val floatFormat = format.buildUpon()
                    .setPcmEncoding(C.ENCODING_PCM_FLOAT)
                    .build()
                val pcm16Format = format.buildUpon()
                    .setPcmEncoding(C.ENCODING_PCM_16BIT)
                    .build()

                val targetEncoding = resolveTargetEncoding(
                    preferred = preferredOutputEncodingProvider?.invoke(format),
                    floatFormat = floatFormat,
                )

                val delegateFormat = format.buildUpon()
                    .setPcmEncoding(targetEncoding.toMedia3PcmEncoding())
                    .build()

                val delegateConfig = AudioSink.AudioSinkConfig.Builder(delegateFormat)
                    .setPreferredBufferSizeOverride(audioSinkConfig.preferredBufferSizeOverride)
                    .setOutputChannelMapping(audioSinkConfig.outputChannelMapping)
                    .setTimeline(audioSinkConfig.timeline)
                    .setMediaPeriodId(audioSinkConfig.mediaPeriodId)
                    .build()

                try {
                    delegate.configure(delegateConfig)
                    inputPcmEncoding = encoding
                    targetOutputEncoding = targetEncoding
                    isPrecisionActive = true
                    publishTelemetry(encoding, targetEncoding)
                    logConfig(
                        precisionActive = true,
                        inputEncoding = encoding.name,
                        sampleRate = sampleRate,
                        channelCount = channelCount,
                        targetOutputEncoding = targetEncoding.name,
                        enableFloatOutput = enableFloatOutput,
                        delegateEncoding = delegateFormat.pcmEncoding,
                    )
                    return
                } catch (e: Exception) {
                    if (targetEncoding != PcmEncoding.PCM_16BIT) {
                        try {
                            val fallbackPcm16Config = AudioSink.AudioSinkConfig.Builder(pcm16Format)
                                .setPreferredBufferSizeOverride(audioSinkConfig.preferredBufferSizeOverride)
                                .setOutputChannelMapping(audioSinkConfig.outputChannelMapping)
                                .setTimeline(audioSinkConfig.timeline)
                                .setMediaPeriodId(audioSinkConfig.mediaPeriodId)
                                .build()
                            delegate.configure(fallbackPcm16Config)
                            inputPcmEncoding = encoding
                            targetOutputEncoding = PcmEncoding.PCM_16BIT
                            isPrecisionActive = true
                            publishTelemetry(encoding, PcmEncoding.PCM_16BIT)
                            logConfig(
                                precisionActive = true,
                                inputEncoding = encoding.name,
                                sampleRate = sampleRate,
                                channelCount = channelCount,
                                targetOutputEncoding = PcmEncoding.PCM_16BIT.name,
                                enableFloatOutput = enableFloatOutput,
                                delegateEncoding = pcm16Format.pcmEncoding,
                            )
                            return
                        } catch (_: Exception) {
                        }
                    }
                    isPrecisionActive = false
                    inputPcmEncoding = null
                    targetOutputEncoding = null
                }
            }
        }

        isPrecisionActive = false
        inputPcmEncoding = null
        targetOutputEncoding = null
        configuredSampleRate = 0
        if (isAudible()) {
            AudioOutputStatus.publishOutputExactness(
                exact = false,
                detail = "${encodingLabel(format.pcmEncoding)} is not linear PCM",
            )
            AudioOutputStatus.publishDsp(
                decoderOutputEncoding = null,
                dspFormat = "Legacy PCM",
                dspAvailable = false,
            )
        }
        delegate.configure(audioSinkConfig)
    }

    override fun handleBuffer(
        inputBuffer: ByteBuffer,
        presentationTimeUs: Long,
        encodedAccessUnitCount: Int,
    ): Boolean {
        if (!isPrecisionActive) {
            return delegate.handleBuffer(inputBuffer, presentationTimeUs, encodedAccessUnitCount)
        }

        val inEncoding = inputPcmEncoding ?: return delegate.handleBuffer(
            inputBuffer,
            presentationTimeUs,
            encodedAccessUnitCount,
        )
        val outEncoding = targetOutputEncoding ?: return delegate.handleBuffer(
            inputBuffer,
            presentationTimeUs,
            encodedAccessUnitCount,
        )

        val channelCount = audioBlock.channelCount
        val bytesPerFrame = inEncoding.bytesPerFrame(channelCount)
        if (bytesPerFrame <= 0) return true
        streaming = true

        if (outputByteBuffer.hasRemaining()) {
            val consumed = delegate.handleBuffer(
                outputByteBuffer,
                pendingPresentationTimeUs,
                pendingAccessUnitCount,
            )
            if (!consumed || outputByteBuffer.hasRemaining()) {
                return false
            }
        }

        if (presentationTimeUs != timestampedInputTimeUs) {
            timestampedInputTimeUs = presentationTimeUs
            framesEmittedForInput = 0L
        }
        while (inputBuffer.remaining() >= bytesPerFrame) {
            val availableFrames = inputBuffer.remaining() / bytesPerFrame
            if (availableFrames <= 0) break

            val framesToRead = minOf(availableFrames, audioBlock.capacityFrames)
            val decodedFrames = PcmBoundary.decode(
                inputBuffer = inputBuffer,
                encoding = inEncoding,
                destinationBlock = audioBlock,
                maxFrames = framesToRead,
            )
            if (decodedFrames <= 0) break

            if (BuildConfig.DEBUG) {
                processCounter++
                if (processCounter == 1L || processCounter % 500L == 0L) {
                    try {
                        val count = processCounter
                        val active = isPrecisionActive
                        val inEnc = inEncoding.name
                        val outEnc = outEncoding.name
                        val frames = decodedFrames
                        Log.d(
                            TAG,
                            "handleBuffer() #$count precisionActive=$active inEnc=$inEnc outEnc=$outEnc frames=$frames",
                        )
                    } catch (_: Throwable) {
                    }
                }
            }

            dspChain.process(audioBlock)

            outputByteBuffer.clear()
            PcmBoundary.encode(
                sourceBlock = audioBlock,
                encoding = outEncoding,
                outputBuffer = outputByteBuffer,
            )
            outputByteBuffer.flip()

            val blockTimeUs = advanceTimestamp(presentationTimeUs, framesEmittedForInput)
            if (blockTimeUs != C.TIME_UNSET && configuredSampleRate > 0) {
                processedEndUs = blockTimeUs + Util.sampleCountToDurationUs(decodedFrames.toLong(), configuredSampleRate)
            }
            val blockAccessUnits = if (framesEmittedForInput == 0L) encodedAccessUnitCount else 0
            pendingPresentationTimeUs = blockTimeUs
            pendingAccessUnitCount = blockAccessUnits
            framesEmittedForInput += decodedFrames

            val consumed = delegate.handleBuffer(
                outputByteBuffer,
                blockTimeUs,
                blockAccessUnits,
            )

            if (!consumed || outputByteBuffer.hasRemaining()) {
                return false
            }
        }

        if (inputBuffer.remaining() in 1 until bytesPerFrame) {
            inputBuffer.position(inputBuffer.limit())
        }

        return !inputBuffer.hasRemaining() && !outputByteBuffer.hasRemaining()
    }

    private fun advanceTimestamp(presentationTimeUs: Long, frames: Long): Long {
        if (frames <= 0L || configuredSampleRate <= 0 || presentationTimeUs == C.TIME_UNSET) {
            return presentationTimeUs
        }
        return presentationTimeUs + Util.sampleCountToDurationUs(frames, configuredSampleRate)
    }

    override fun setOutputStreamOffsetUs(outputStreamOffsetUs: Long) {
        if (streaming) dspChain.onStreamBoundary()
        super.setOutputStreamOffsetUs(outputStreamOffsetUs)
    }

    override fun getCurrentPositionUs(sourceEnded: Boolean): Long {
        val position = super.getCurrentPositionUs(sourceEnded)
        val processed = processedEndUs
        if (position != AudioSink.CURRENT_POSITION_NOT_SET && processed != C.TIME_UNSET) {
            dspChain.transition.leadUs = (processed - position).coerceAtLeast(0L)
        }
        return position
    }

    override fun flush() {
        processedEndUs = C.TIME_UNSET
        dspChain.transition.leadUs = 0L
        streaming = false
        outputByteBuffer.clear()
        outputByteBuffer.flip()
        audioBlock.clear()
        pendingPresentationTimeUs = C.TIME_UNSET
        pendingAccessUnitCount = 0
        timestampedInputTimeUs = C.TIME_UNSET
        framesEmittedForInput = 0L
        if (isPrecisionActive) {
            dspChain.flush()
        }
        delegate.flush()
    }

    override fun reset() {
        processedEndUs = C.TIME_UNSET
        dspChain.transition.leadUs = 0L
        streaming = false
        processCounter = 0L
        outputByteBuffer.clear()
        outputByteBuffer.flip()
        audioBlock.clear()
        pendingPresentationTimeUs = C.TIME_UNSET
        pendingAccessUnitCount = 0
        timestampedInputTimeUs = C.TIME_UNSET
        framesEmittedForInput = 0L
        if (isPrecisionActive) {
            dspChain.reset()
        }
        isPrecisionActive = false
        inputPcmEncoding = null
        targetOutputEncoding = null
        activeFormat = null
        configuredSampleRate = 0
        if (isAudible()) {
            AudioOutputStatus.publishOutputExactness(exact = false, detail = null)
            AudioOutputStatus.publishDsp(
                decoderOutputEncoding = null,
                dspFormat = "Float32",
                dspAvailable = true,
            )
        }
        delegate.reset()
    }

    override fun handleDiscontinuity() {
        delegate.handleDiscontinuity()
    }

    override fun playToEndOfStream() {
        if (isPrecisionActive && outputByteBuffer.hasRemaining()) {
            delegate.handleBuffer(outputByteBuffer, pendingPresentationTimeUs, pendingAccessUnitCount)
        }
        delegate.playToEndOfStream()
    }

    override fun isEnded(): Boolean {
        if (isPrecisionActive && outputByteBuffer.hasRemaining()) {
            return false
        }
        return delegate.isEnded()
    }

    override fun hasPendingData(): Boolean {
        if (isPrecisionActive && outputByteBuffer.hasRemaining()) {
            return true
        }
        return delegate.hasPendingData()
    }

    override fun supportsFormat(format: Format): Boolean =
        getFormatSupport(format) != AudioSink.SINK_FORMAT_UNSUPPORTED

    override fun getFormatSupport(format: Format): Int {
        if (shouldActivatePrecision(format)) {
            val pcm16Format = format.buildUpon()
                .setPcmEncoding(C.ENCODING_PCM_16BIT)
                .build()
            val floatFormat = format.buildUpon()
                .setPcmEncoding(C.ENCODING_PCM_FLOAT)
                .build()

            val pcm16Playable =
                delegate.getFormatSupport(pcm16Format) != AudioSink.SINK_FORMAT_UNSUPPORTED
            val floatIsNative = floatIsNative(floatFormat)

            if (format.pcmEncoding == C.ENCODING_PCM_FLOAT) {
                return when {
                    floatIsNative -> AudioSink.SINK_FORMAT_SUPPORTED_DIRECTLY
                    pcm16Playable -> AudioSink.SINK_FORMAT_SUPPORTED_WITH_TRANSCODING
                    else -> AudioSink.SINK_FORMAT_UNSUPPORTED
                }
            }
            if (floatIsNative || pcm16Playable) {
                return AudioSink.SINK_FORMAT_SUPPORTED_DIRECTLY
            }
        }
        return delegate.getFormatSupport(format)
    }

    private fun floatIsNative(floatFormat: Format): Boolean =
        enableFloatOutput &&
            delegate.getFormatSupport(floatFormat) == AudioSink.SINK_FORMAT_SUPPORTED_DIRECTLY

    private fun resolveTargetEncoding(preferred: PcmEncoding?, floatFormat: Format): PcmEncoding {
        val wantsAbove16Bit = when (preferred) {
            PcmEncoding.PCM_16BIT -> return PcmEncoding.PCM_16BIT
            PcmEncoding.PCM_FLOAT, PcmEncoding.PCM_24BIT_PACKED, PcmEncoding.PCM_32BIT -> true
            null -> enableFloatOutput
        }
        return if (wantsAbove16Bit && floatIsNative(floatFormat)) {
            PcmEncoding.PCM_FLOAT
        } else {
            PcmEncoding.PCM_16BIT
        }
    }

    private fun shouldActivatePrecision(format: Format): Boolean {
        val sampleMimeType = format.sampleMimeType
        if (sampleMimeType != null && sampleMimeType != MimeTypes.AUDIO_RAW) return false
        if (!Util.isEncodingLinearPcm(format.pcmEncoding)) return false
        if (mapToPcmEncoding(format.pcmEncoding) == null) return false
        if (format.channelCount !in 1..MAX_CHANNELS) return false
        if (format.sampleRate <= 0) return false
        return true
    }

    private fun ensureBuffers(channelCount: Int) {
        if (audioBlock.channelCount != channelCount) {
            audioBlock = AudioBlock(channelCount = channelCount, capacityFrames = DEFAULT_CAPACITY_FRAMES)
        } else {
            audioBlock.reset(0)
        }

        val requiredCapacity = audioBlock.capacityFrames * channelCount * PcmEncoding.PCM_FLOAT.bytesPerSample
        if (outputByteBuffer.capacity() < requiredCapacity) {
            outputByteBuffer = ByteBuffer.allocateDirect(requiredCapacity).order(ByteOrder.nativeOrder())
        }
        outputByteBuffer.clear()
        outputByteBuffer.flip()
    }

    private fun publishOutputExactness(source: PcmEncoding, target: PcmEncoding) {
        val exact = when (source) {
            PcmEncoding.PCM_16BIT -> target == PcmEncoding.PCM_16BIT
            PcmEncoding.PCM_24BIT_PACKED -> target == PcmEncoding.PCM_FLOAT
            PcmEncoding.PCM_FLOAT -> target == PcmEncoding.PCM_FLOAT
            PcmEncoding.PCM_32BIT -> false
        }
        val sourceLabel = encodingLabel(mapFromPcmEncoding(source))
        val detail = when {
            exact -> "$sourceLabel → ${encodingLabel(mapFromPcmEncoding(target))}"
            source == PcmEncoding.PCM_32BIT ->
                "32-bit PCM exceeds what AudioTrack can carry; 8 bits lost"
            else -> "$sourceLabel → 16-bit; this route cannot open a float track"
        }
        AudioOutputStatus.publishOutputExactness(exact = exact, detail = detail)
    }

    private fun publishTelemetry(inEncoding: PcmEncoding, outEncoding: PcmEncoding) {
        if (!isAudible()) return
        publishOutputExactness(inEncoding, outEncoding)
        AudioOutputStatus.publishDsp(
            decoderOutputEncoding = encodingLabel(mapFromPcmEncoding(inEncoding)),
            dspFormat = "Float32",
            dspAvailable = true,
        )
    }

    private fun logConfig(
        precisionActive: Boolean,
        inputEncoding: String,
        sampleRate: Int,
        channelCount: Int,
        targetOutputEncoding: String,
        enableFloatOutput: Boolean,
        delegateEncoding: Int,
    ) {
        if (BuildConfig.DEBUG) {
            try {
                Log.d(
                    TAG,
                    "configure() precisionActive=$precisionActive inputEncoding=$inputEncoding sr=$sampleRate ch=$channelCount targetOutputEncoding=$targetOutputEncoding enableFloatOutput=$enableFloatOutput delegateEncoding=$delegateEncoding",
                )
            } catch (_: Throwable) {
            }
        }
    }

    companion object {
        private const val TAG = "PrecisionAudioSink"
        const val DEFAULT_CAPACITY_FRAMES: Int = 4096
        const val MAX_CHANNELS: Int = 8

        fun encodingLabel(pcmEncoding: Int): String = when (pcmEncoding) {
            C.ENCODING_PCM_16BIT -> "16-bit PCM"
            C.ENCODING_PCM_24BIT -> "24-bit PCM"
            C.ENCODING_PCM_32BIT -> "32-bit PCM"
            C.ENCODING_PCM_FLOAT -> "Float32"
            else -> "Non-PCM"
        }

        fun mapToPcmEncoding(pcmEncoding: Int): PcmEncoding? = when (pcmEncoding) {
            C.ENCODING_PCM_16BIT -> PcmEncoding.PCM_16BIT
            C.ENCODING_PCM_24BIT -> PcmEncoding.PCM_24BIT_PACKED
            C.ENCODING_PCM_32BIT -> PcmEncoding.PCM_32BIT
            C.ENCODING_PCM_FLOAT -> PcmEncoding.PCM_FLOAT
            else -> null
        }

        fun mapFromPcmEncoding(pcmEncoding: PcmEncoding): Int = when (pcmEncoding) {
            PcmEncoding.PCM_16BIT -> C.ENCODING_PCM_16BIT
            PcmEncoding.PCM_24BIT_PACKED -> C.ENCODING_PCM_24BIT
            PcmEncoding.PCM_32BIT -> C.ENCODING_PCM_32BIT
            PcmEncoding.PCM_FLOAT -> C.ENCODING_PCM_FLOAT
        }

        fun PcmEncoding.toMedia3PcmEncoding(): Int = mapFromPcmEncoding(this)
    }
}
