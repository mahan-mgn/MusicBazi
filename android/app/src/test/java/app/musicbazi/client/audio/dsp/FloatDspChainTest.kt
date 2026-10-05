/*
 * Copyright (C) 2024-2026 Kushagra Singh / BitChord Contributors
 * Ported to Music Bazi (app.musicbazi.client.audio.dsp)
 *
 * Licensed under the GNU General Public License v3.0 (GPL-3.0)
 */

package app.musicbazi.client.audio.dsp

import app.musicbazi.client.audio.pcm.AudioBlock
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.sin

/**
 * Comprehensive verification of the Float32 DSP processors:
 * - EqualizerProcessor (FloatAudioProcessor)
 * - SpatialAudioProcessor (FloatAudioProcessor)
 * - TransitionFilterProcessor (FloatAudioProcessor)
 * - DspChain composite pipeline
 */
class FloatDspChainTest {

    private val sampleRate = 44100

    @Test
    fun eqImpulseResponseRingsWithBiquadFilterDecay() {
        val eq = EqualizerProcessor()
        eq.configure(sampleRate, 2)

        val gains = FloatArray(EqLayout.SLOTS)
        val qs = FloatArray(EqLayout.SLOTS) { 0.707f }
        gains[3] = 6.0f // 1000 Hz bell
        eq.setTuning(enabled = true, EqCurve(gains, qs, 0f), balance = 0f)
        eq.flush()

        val frames = 256
        val block = AudioBlock(channelCount = 2, capacityFrames = frames)
        block.samples[0] = 1.0f
        block.samples[1] = 0.0f
        block.reset(frames)

        eq.process(block)

        var nonZeroCount = 0
        for (f in 1 until frames) {
            if (abs(block.samples[f * 2]) > 1e-4f) nonZeroCount++
        }
        assertTrue("Filter impulse response must ring over multiple frames", nonZeroCount > 10)
    }

    @Test
    fun eqGainResponseLiftsCentreFrequency() {
        val eq = EqualizerProcessor()
        eq.configure(sampleRate, 2)

        val boostDb = 6.0f
        val gains = FloatArray(EqLayout.SLOTS)
        val qs = FloatArray(EqLayout.SLOTS) { 0.707f }
        val targetSlot = 3
        gains[targetSlot] = boostDb
        eq.setTuning(enabled = true, EqCurve(gains, qs, 0f), balance = 0f)
        eq.flush()

        val frames = 4096
        val block = AudioBlock(channelCount = 2, capacityFrames = frames)
        val freq = 1000.0
        val inputAmp = 0.25f
        for (f in 0 until frames) {
            val s = (inputAmp * sin(2.0 * PI * freq * f / sampleRate)).toFloat()
            block.samples[f * 2] = s
            block.samples[f * 2 + 1] = s
        }
        block.reset(frames)

        eq.process(block)

        var peakOut = 0f
        for (f in 2048 until frames) {
            val amp = abs(block.samples[f * 2])
            if (amp > peakOut) peakOut = amp
        }

        val expectedGainLinear = Math.pow(10.0, (boostDb / 20.0)).toFloat()
        val expectedPeak = inputAmp * expectedGainLinear
        assertEquals("1 kHz center must be amplified by ~+6 dB", expectedPeak, peakOut, 0.08f)
    }

    @Test
    fun eqMultipleSimultaneousBandsBoostBothEnds() {
        val eq = EqualizerProcessor()
        eq.configure(sampleRate, 2)

        val gains = FloatArray(EqLayout.SLOTS)
        val qs = FloatArray(EqLayout.SLOTS) { 0.707f }
        gains[0] = 6.0f // 60 Hz shelf
        gains[9] = 6.0f // 14 kHz shelf
        eq.setTuning(enabled = true, EqCurve(gains, qs, 0f), balance = 0f)
        eq.flush()

        val frames = 1024
        val block = AudioBlock(channelCount = 2, capacityFrames = frames)
        for (f in 0 until frames) {
            val s = (0.2 * sin(2.0 * PI * 60.0 * f / sampleRate) +
                    0.2 * sin(2.0 * PI * 14000.0 * f / sampleRate)).toFloat()
            block.samples[f * 2] = s
            block.samples[f * 2 + 1] = s
        }
        block.reset(frames)

        eq.process(block)

        var maxAmp = 0f
        for (f in 512 until frames) {
            val amp = abs(block.samples[f * 2])
            if (amp > maxAmp) maxAmp = amp
        }
        assertTrue("Simultaneous shelves must increase composite peak energy", maxAmp > 0.4f)
    }

    @Test
    fun eqBypassWhenFlatPassesUntouched() {
        val eq = EqualizerProcessor()
        eq.configure(sampleRate, 2)
        eq.setTuning(enabled = false, EqCurve.FLAT, balance = 0f)
        eq.flush()

        val frames = 64
        val block = AudioBlock(channelCount = 2, capacityFrames = frames)
        for (i in 0 until frames * 2) {
            block.samples[i] = (i + 1) * 0.01f
        }
        block.reset(frames)

        eq.process(block)

        for (i in 0 until frames * 2) {
            assertEquals((i + 1) * 0.01f, block.samples[i], 0.0f)
        }
    }

    @Test
    fun eqMaintainsStereoIndependence() {
        val eq = EqualizerProcessor()
        eq.configure(sampleRate, 2)

        val gains = FloatArray(EqLayout.SLOTS) { 3f }
        val qs = FloatArray(EqLayout.SLOTS) { 0.707f }
        eq.setTuning(enabled = true, EqCurve(gains, qs, 0f), balance = 0f)
        eq.flush()

        val frames = 256
        val block = AudioBlock(channelCount = 2, capacityFrames = frames)
        for (f in 0 until frames) {
            block.samples[f * 2] = 0.5f
            block.samples[f * 2 + 1] = 0.0f
        }
        block.reset(frames)

        eq.process(block)

        for (f in 0 until frames) {
            assertEquals(0.0f, block.samples[f * 2 + 1], 0.0f)
        }
    }

    @Test
    fun spatialCrossfeedLeaksToOppositeChannel() {
        val spatial = SpatialAudioProcessor()
        spatial.configure(sampleRate, 2)
        spatial.enabled = true

        val frames = 1000
        val block = AudioBlock(channelCount = 2, capacityFrames = frames)
        for (f in 0 until frames) {
            block.samples[f * 2] = (0.5 * sin(2.0 * PI * 500.0 * f / sampleRate)).toFloat()
            block.samples[f * 2 + 1] = 0.0f
        }
        block.reset(frames)

        spatial.process(block)

        var rightEnergy = 0.0
        for (f in 700 until frames) {
            rightEnergy += abs(block.samples[f * 2 + 1].toDouble())
        }
        assertTrue("Crossfeed must produce non-zero signal on right channel", rightEnergy > 1.0)
    }

    @Test
    fun spatialBypassPassesUntouchedWhenDisabled() {
        val spatial = SpatialAudioProcessor()
        spatial.configure(sampleRate, 2)
        spatial.enabled = false

        val frames = 64
        val block = AudioBlock(channelCount = 2, capacityFrames = frames)
        for (i in 0 until frames * 2) {
            block.samples[i] = (i + 1) * 0.01f
        }
        block.reset(frames)

        spatial.process(block)

        for (i in 0 until frames * 2) {
            assertEquals((i + 1) * 0.01f, block.samples[i], 0.0f)
        }
    }

    @Test
    fun transitionLowPassAttenuatesHighFrequency() {
        val transition = TransitionFilterProcessor()
        transition.configure(sampleRate, 2)
        transition.setCutoffs(lowPassHz = 500f, highPassHz = TransitionFilterProcessor.OFF_HZ)
        transition.flush()

        val frames = 1024
        val block = AudioBlock(channelCount = 2, capacityFrames = frames)
        val freq = 5000.0
        for (f in 0 until frames) {
            val s = sin(2.0 * PI * freq * f / sampleRate).toFloat()
            block.samples[f * 2] = s
            block.samples[f * 2 + 1] = s
        }
        block.reset(frames)

        transition.process(block)

        var peakOut = 0f
        for (f in 512 until frames) {
            val amp = abs(block.samples[f * 2])
            if (amp > peakOut) peakOut = amp
        }
        assertTrue("5 kHz through 500 Hz low-pass must be attenuated (got peak $peakOut)", peakOut < 0.1f)
    }

    @Test
    fun transitionBypassPassesUntouchedWhenOpen() {
        val transition = TransitionFilterProcessor()
        transition.configure(sampleRate, 2)
        transition.open()
        transition.flush()

        val frames = 64
        val block = AudioBlock(channelCount = 2, capacityFrames = frames)
        for (i in 0 until frames * 2) {
            block.samples[i] = (i + 1) * 0.01f
        }
        block.reset(frames)

        transition.process(block)

        for (i in 0 until frames * 2) {
            assertEquals((i + 1) * 0.01f, block.samples[i], 0.0f)
        }
    }

    @Test
    fun dspChainPreservesHeadroomAboveOne() {
        val chain = DspChain()
        chain.configure(sampleRate, 2)

        chain.spatial.enabled = false
        val gains = FloatArray(EqLayout.SLOTS)
        val qs = FloatArray(EqLayout.SLOTS) { 0.707f }
        chain.equalizer.setTuning(enabled = true, EqCurve(gains, qs, preampDb = 3.0f), balance = 0f)
        chain.transition.open()
        chain.flush()

        val frames = 64
        val block = AudioBlock(channelCount = 2, capacityFrames = frames)
        for (i in 0 until frames * 2) {
            block.samples[i] = 0.9f
        }
        block.reset(frames)

        chain.process(block)

        val sample = block.samples[frames * 2 - 2]
        assertTrue("Headroom must be preserved above 1.0f (got $sample)", sample > 1.1f)
    }

    @Test
    fun zeroLengthInputHandledSafely() {
        val chain = DspChain()
        chain.configure(sampleRate, 2)
        val block = AudioBlock(channelCount = 2, capacityFrames = 64)
        block.reset(0)

        chain.process(block)
        assertEquals(0, block.frameCount)
    }

    @Test
    fun repeatedBlockProcessingMaintainsStability() {
        val chain = DspChain()
        chain.configure(sampleRate, 2)

        chain.spatial.enabled = true
        val gains = FloatArray(EqLayout.SLOTS)
        val qs = FloatArray(EqLayout.SLOTS) { 0.707f }
        gains[2] = 4.0f
        chain.equalizer.setTuning(enabled = true, EqCurve(gains, qs, 0f), balance = 0f)
        chain.transition.setCutoffs(lowPassHz = 8000f, highPassHz = 100f)

        val blockSize = 512
        val block = AudioBlock(channelCount = 2, capacityFrames = blockSize)

        for (iteration in 0 until 50) {
            for (f in 0 until blockSize) {
                val totalFrame = iteration * blockSize + f
                val s = sin(2.0 * PI * 440.0 * totalFrame / sampleRate).toFloat()
                block.samples[f * 2] = s
                block.samples[f * 2 + 1] = s
            }
            block.reset(blockSize)
            chain.process(block)

            for (i in 0 until blockSize * 2) {
                val v = block.samples[i]
                assertFalse("Sample must not be NaN at block $iteration", v.isNaN())
                assertFalse("Sample must not be Infinite at block $iteration", v.isInfinite())
            }
        }
    }
}
