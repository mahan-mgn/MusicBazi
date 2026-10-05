/*
 * Copyright (C) 2024-2026 Kushagra Singh / BitChord Contributors
 * Ported to Music Bazi (app.musicbazi.client.audio.dsp)
 *
 * Licensed under the GNU General Public License v3.0 (GPL-3.0)
 */

package app.musicbazi.client.audio.dsp

import androidx.media3.common.AudioAttributes
import androidx.media3.common.AuxEffectInfo
import androidx.media3.common.C
import androidx.media3.common.Format
import androidx.media3.common.MimeTypes
import androidx.media3.common.PlaybackParameters
import androidx.media3.common.util.UnstableApi
import androidx.media3.common.util.Util
import androidx.media3.exoplayer.audio.AudioSink
import app.musicbazi.client.audio.output.AudioOutputStatus
import app.musicbazi.client.audio.pcm.PcmEncoding
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.ByteBuffer
import java.nio.ByteOrder

@androidx.annotation.OptIn(UnstableApi::class)
class PrecisionAudioSinkTest {

    private class FakeAudioSink : AudioSink {
        var configuredConfig: AudioSink.AudioSinkConfig? = null
        private var sinkListener: AudioSink.Listener? = null
        var flushed: Boolean = false
        var resetCount: Int = 0
        var discontinuityHandled: Boolean = false
        var playedToEndOfStream: Boolean = false
        var isEndedReturn: Boolean = false
        var hasPendingDataReturn: Boolean = false

        var bytesToConsumePerCall: Int = Int.MAX_VALUE
        var lastHandledBuffer: ByteBuffer? = null
        var handleBufferCallCount: Int = 0
        var lastPresentationTimeUs: Long = C.TIME_UNSET
        var lastEncodedAccessUnitCount: Int = 0

        var formatSupportReturn: Int = AudioSink.SINK_FORMAT_SUPPORTED_DIRECTLY
        var supportsFormatReturn: Boolean = true
        var supportsFormatPredicate: ((Format) -> Boolean)? = null
        var formatSupportPredicate: ((Format) -> Int)? = null

        override fun setListener(listener: AudioSink.Listener) {
            this.sinkListener = listener
        }

        override fun supportsFormat(format: Format): Boolean {
            return supportsFormatPredicate?.invoke(format) ?: supportsFormatReturn
        }

        override fun getFormatSupport(format: Format): Int =
            formatSupportPredicate?.invoke(format) ?: formatSupportReturn

        override fun getCurrentPositionUs(sourceEnded: Boolean): Long = 0L

        override fun configure(audioSinkConfig: AudioSink.AudioSinkConfig) {
            this.configuredConfig = audioSinkConfig
        }

        override fun play() {}

        override fun handleDiscontinuity() {
            discontinuityHandled = true
        }

        override fun handleBuffer(
            buffer: ByteBuffer,
            presentationTimeUs: Long,
            encodedAccessUnitCount: Int,
        ): Boolean {
            handleBufferCallCount++
            lastHandledBuffer = buffer
            lastPresentationTimeUs = presentationTimeUs
            lastEncodedAccessUnitCount = encodedAccessUnitCount

            val remaining = buffer.remaining()
            val consume = minOf(remaining, bytesToConsumePerCall)
            buffer.position(buffer.position() + consume)

            return !buffer.hasRemaining()
        }

        override fun playToEndOfStream() {
            playedToEndOfStream = true
        }

        override fun isEnded(): Boolean = isEndedReturn

        override fun hasPendingData(): Boolean = hasPendingDataReturn

        override fun setPlaybackParameters(playbackParameters: PlaybackParameters) {}

        override fun getPlaybackParameters(): PlaybackParameters = PlaybackParameters.DEFAULT

        override fun setSkipSilenceEnabled(skipSilenceEnabled: Boolean) {}

        override fun getSkipSilenceEnabled(): Boolean = false

        override fun setAudioAttributes(audioAttributes: AudioAttributes) {}

        override fun getAudioAttributes(): AudioAttributes? = null

        override fun setAudioSessionId(audioSessionId: Int) {}

        override fun setAuxEffectInfo(auxEffectInfo: AuxEffectInfo) {}

        override fun getAudioTrackBufferSizeUs(): Long = 0L

        override fun enableTunnelingV21() {}

        override fun disableTunneling() {}

        override fun setVolume(volume: Float) {}

        override fun pause() {}

        override fun flush() {
            flushed = true
        }

        override fun reset() {
            resetCount++
            configuredConfig = null
        }

        override fun release() {}
    }

    private fun createSink(
        delegate: AudioSink,
        enableFloatOutput: Boolean = true,
        dspChain: DspChain = idleDspChain(),
    ): PrecisionAudioSink {
        return PrecisionAudioSink(
            delegate = delegate,
            dspChain = dspChain,
            enableFloatOutput = enableFloatOutput,
        )
    }

    private fun rawFormat(pcmEncoding: Int, channelCount: Int = 2): Format = Format.Builder()
        .setSampleMimeType(MimeTypes.AUDIO_RAW)
        .setPcmEncoding(pcmEncoding)
        .setChannelCount(channelCount)
        .setSampleRate(48000)
        .build()

    private fun idleDspChain(): DspChain = DspChain(
        spatial = SpatialAudioProcessor(),
        equalizer = EqualizerProcessor(),
        transition = TransitionFilterProcessor(),
    )

    @Test
    fun pcm16RoundTripIsExactWithIdleChain() {
        val fakeDelegate = FakeAudioSink()
        val sink = createSink(fakeDelegate, enableFloatOutput = false)
        sink.configure(AudioSink.AudioSinkConfig.Builder(rawFormat(C.ENCODING_PCM_16BIT)).build())

        assertEquals(PcmEncoding.PCM_16BIT, sink.targetOutputEncoding)
        assertTrue(AudioOutputStatus.current.value.outputExact)

        val samples = shortArrayOf(
            0, 1, -1, 1000, -1000, 32767, -32768, 12345, -12345, 255, -256, 4096,
        )
        val input = ByteBuffer.allocate(samples.size * 2).order(ByteOrder.nativeOrder())
        samples.forEach(input::putShort)
        input.flip()

        sink.handleBuffer(input, 0L, 1)

        val handed = fakeDelegate.lastHandledBuffer!!.order(ByteOrder.nativeOrder())
        handed.rewind()
        samples.forEachIndexed { i, expected ->
            assertEquals("sample $i altered", expected, handed.getShort())
        }
    }

    @Test
    fun pcm24GoesToFloatAndSurvivesExactly() {
        val fakeDelegate = FakeAudioSink()
        val sink = createSink(fakeDelegate)
        sink.configure(AudioSink.AudioSinkConfig.Builder(rawFormat(C.ENCODING_PCM_24BIT)).build())

        assertEquals(PcmEncoding.PCM_24BIT_PACKED, sink.inputPcmEncoding)
        assertEquals(PcmEncoding.PCM_FLOAT, sink.targetOutputEncoding)
        assertEquals(C.ENCODING_PCM_FLOAT, fakeDelegate.configuredConfig!!.format.pcmEncoding)
        assertTrue(AudioOutputStatus.current.value.outputExact)

        val samples = intArrayOf(0, 1, -1, 8388607, -8388608, 0x0000FF, 0x7FFFFF, -0x7FFFFF)
        val input = ByteBuffer.allocate(samples.size * 3).order(ByteOrder.nativeOrder())
        samples.forEach {
            input.put((it and 0xFF).toByte())
            input.put(((it shr 8) and 0xFF).toByte())
            input.put(((it shr 16) and 0xFF).toByte())
        }
        input.flip()

        sink.handleBuffer(input, 0L, 1)

        val handed = fakeDelegate.lastHandledBuffer!!.order(ByteOrder.nativeOrder())
        handed.rewind()
        samples.forEachIndexed { i, expected ->
            val recovered = Math.round(handed.getFloat() * 8388608.0f)
            assertEquals("sample $i altered", expected, recovered)
        }
    }

    @Test
    fun reportsInexactWhenRouteRefusesFloat() {
        val fakeDelegate = FakeAudioSink()
        fakeDelegate.formatSupportReturn = AudioSink.SINK_FORMAT_SUPPORTED_WITH_TRANSCODING
        val sink = createSink(fakeDelegate)
        sink.configure(AudioSink.AudioSinkConfig.Builder(rawFormat(C.ENCODING_PCM_24BIT)).build())

        assertEquals(PcmEncoding.PCM_16BIT, sink.targetOutputEncoding)
        assertFalse(AudioOutputStatus.current.value.outputExact)
    }

    @Test
    fun floatIsTakenOnlyWhenDelegateSupportsItDirectly() {
        val transcoding = FakeAudioSink().apply {
            formatSupportReturn = AudioSink.SINK_FORMAT_SUPPORTED_WITH_TRANSCODING
            supportsFormatReturn = true
        }
        val direct = FakeAudioSink().apply {
            formatSupportReturn = AudioSink.SINK_FORMAT_SUPPORTED_DIRECTLY
        }

        createSink(transcoding).also {
            it.configure(AudioSink.AudioSinkConfig.Builder(rawFormat(C.ENCODING_PCM_24BIT)).build())
            assertEquals(PcmEncoding.PCM_16BIT, it.targetOutputEncoding)
        }
        createSink(direct).also {
            it.configure(AudioSink.AudioSinkConfig.Builder(rawFormat(C.ENCODING_PCM_24BIT)).build())
            assertEquals(PcmEncoding.PCM_FLOAT, it.targetOutputEncoding)
        }
    }

    @Test
    fun pcm32IsAdmittedToBeInexact() {
        val fakeDelegate = FakeAudioSink()
        val sink = createSink(fakeDelegate)
        sink.configure(AudioSink.AudioSinkConfig.Builder(rawFormat(C.ENCODING_PCM_32BIT)).build())

        assertFalse(AudioOutputStatus.current.value.outputExact)
        assertTrue(
            AudioOutputStatus.current.value.outputExactDetail.orEmpty().contains("8 bits lost"),
        )
    }

    @Test
    fun precisionStaysActiveForMultichannel() {
        val fakeDelegate = FakeAudioSink()
        val equalizer = EqualizerProcessor().apply {
            setTuning(enabled = true, curve = EqCurve.FLAT, balance = 0f)
        }
        val sink = createSink(
            fakeDelegate,
            enableFloatOutput = false,
            dspChain = DspChain(equalizer = equalizer),
        )
        sink.configure(
            AudioSink.AudioSinkConfig.Builder(
                rawFormat(C.ENCODING_PCM_16BIT, channelCount = 6),
            ).build(),
        )

        assertTrue(sink.isPrecisionActive)
        assertTrue(AudioOutputStatus.current.value.dspAvailable)
        assertEquals(6, fakeDelegate.configuredConfig!!.format.channelCount)
    }

    @Test
    fun passthroughBitstreamReportsDspUnavailable() {
        val fakeDelegate = FakeAudioSink()
        val sink = createSink(fakeDelegate)
        val eac3 = Format.Builder()
            .setSampleMimeType(MimeTypes.AUDIO_E_AC3_JOC)
            .setChannelCount(6)
            .setSampleRate(48000)
            .build()

        sink.configure(AudioSink.AudioSinkConfig.Builder(eac3).build())

        assertFalse(sink.isPrecisionActive)
        assertFalse(AudioOutputStatus.current.value.dspAvailable)
    }

    @Test
    fun splitSubBlocksAdvanceTimestamp() {
        val fakeDelegate = FakeAudioSink()
        val sink = createSink(fakeDelegate, enableFloatOutput = false)
        sink.configure(AudioSink.AudioSinkConfig.Builder(rawFormat(C.ENCODING_PCM_16BIT)).build())

        val frames = PrecisionAudioSink.DEFAULT_CAPACITY_FRAMES * 2
        val input = ByteBuffer.allocate(frames * 2 * 2).order(ByteOrder.nativeOrder())
        repeat(frames * 2) { input.putShort(0) }
        input.flip()

        sink.handleBuffer(input, 1_000_000L, 1)

        val expected = 1_000_000L + Util.sampleCountToDurationUs(
            PrecisionAudioSink.DEFAULT_CAPACITY_FRAMES.toLong(),
            48000,
        )
        assertEquals(2, fakeDelegate.handleBufferCallCount)
        assertEquals(expected, fakeDelegate.lastPresentationTimeUs)
    }

    @Test
    fun dspChainIsReachedWhenSwitchedOn() {
        val equalizer = EqualizerProcessor().apply {
            setTuning(enabled = true, curve = EqCurve.FLAT, balance = 1f)
        }
        val fakeDelegate = FakeAudioSink()
        val sink = createSink(
            fakeDelegate,
            enableFloatOutput = false,
            dspChain = DspChain(equalizer = equalizer),
        )
        sink.configure(AudioSink.AudioSinkConfig.Builder(rawFormat(C.ENCODING_PCM_16BIT)).build())

        val input = ByteBuffer.allocate(8).order(ByteOrder.nativeOrder())
        shortArrayOf(8000, 8000, 8000, 8000).forEach(input::putShort)
        input.flip()

        sink.handleBuffer(input, 0L, 1)

        val handed = fakeDelegate.lastHandledBuffer!!.order(ByteOrder.nativeOrder())
        handed.rewind()
        assertEquals(0.toShort(), handed.getShort())
    }

    @Test
    fun handleBufferRespectsBackpressure() {
        val fakeDelegate = FakeAudioSink()
        fakeDelegate.bytesToConsumePerCall = 256

        val sink = createSink(fakeDelegate, enableFloatOutput = true)
        val format = Format.Builder()
            .setSampleMimeType(MimeTypes.AUDIO_RAW)
            .setPcmEncoding(C.ENCODING_PCM_16BIT)
            .setChannelCount(2)
            .setSampleRate(44100)
            .build()
        sink.configure(AudioSink.AudioSinkConfig.Builder(format).build())

        val frameCount = 128
        val inputBuffer = ByteBuffer.allocateDirect(frameCount * 2 * 2).order(ByteOrder.LITTLE_ENDIAN)
        for (i in 0 until frameCount * 2) {
            inputBuffer.putShort(8000.toShort())
        }
        inputBuffer.flip()

        val result1 = sink.handleBuffer(inputBuffer, 1000L, 1)
        assertFalse("Must return false when delegate has backpressure", result1)
        val firstBufferRef = fakeDelegate.lastHandledBuffer
        assertNotNull(firstBufferRef)

        fakeDelegate.bytesToConsumePerCall = Int.MAX_VALUE
        val result2 = sink.handleBuffer(inputBuffer, 1000L, 1)
        assertTrue("Must return true once delegate fully consumes", result2)
        val secondBufferRef = fakeDelegate.lastHandledBuffer

        assertSame("Must reuse exact same ByteBuffer instance across backpressure ticks", firstBufferRef, secondBufferRef)
    }

    @Test
    fun handleBufferInFallbackModeForwardsUntouched() {
        val fakeDelegate = FakeAudioSink()
        val sink = createSink(fakeDelegate, enableFloatOutput = false)

        val format = Format.Builder()
            .setSampleMimeType(MimeTypes.AUDIO_AAC)
            .setChannelCount(2)
            .setSampleRate(44100)
            .build()
        sink.configure(AudioSink.AudioSinkConfig.Builder(format).build())

        val inputBuffer = ByteBuffer.allocateDirect(64).order(ByteOrder.LITTLE_ENDIAN)
        inputBuffer.putInt(0x12345678)
        inputBuffer.flip()

        val handled = sink.handleBuffer(inputBuffer, 5000L, 0)
        assertTrue(handled)
        assertSame(inputBuffer, fakeDelegate.lastHandledBuffer)
    }
}
