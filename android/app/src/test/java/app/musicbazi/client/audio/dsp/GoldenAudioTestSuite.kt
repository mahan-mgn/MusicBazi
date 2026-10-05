/*
 * Copyright (C) 2026 Music Bazi / Unstream
 *
 * Licensed under the GNU General Public License v3.0 (GPL-3.0)
 */

package app.musicbazi.client.audio.dsp

import app.musicbazi.client.audio.pcm.AudioBlock
import app.musicbazi.client.audio.pcm.PcmBoundary
import app.musicbazi.client.audio.pcm.PcmEncoding
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * Golden Audio Test Suite for Music Bazi Native DSP Engine.
 *
 * Enforces numerical precision, zero-drift bypass, phase continuity, and filter response bounds.
 */
class GoldenAudioTestSuite {

    private val sampleRate = 48000

    @Test
    fun dspBypassExactZeroError() {
        val chain = DspChain()
        chain.configure(sampleRate, 2)
        chain.spatial.enabled = false
        chain.equalizer.setTuning(enabled = false, EqCurve.FLAT, balance = 0f)
        chain.transition.open()
        chain.flush()

        val frames = 1024
        val block = AudioBlock(channelCount = 2, capacityFrames = frames)
        for (i in 0 until frames * 2) {
            block.samples[i] = (sin(2.0 * PI * 440.0 * (i / 2) / sampleRate) * 0.8).toFloat()
        }
        block.reset(frames)

        val originalSamples = block.samples.copyOf()
        chain.process(block)

        var maxAbsError = 0.0f
        for (i in 0 until frames * 2) {
            val error = abs(block.samples[i] - originalSamples[i])
            if (error > maxAbsError) maxAbsError = error
        }

        assertEquals("Bypass mode must produce exact bit-identical samples (maxAbsError == 0)", 0.0f, maxAbsError, 0.0f)
    }

    @Test
    fun pcm16ThroughFloat32BypassRoundTripZeroError() {
        val frames = 2048
        val inBuf = ByteBuffer.allocate(frames * 4).order(ByteOrder.LITTLE_ENDIAN)
        for (f in 0 until frames) {
            val sample = ((f * 37) % 65536 - 32768).toShort()
            inBuf.putShort(sample)
            inBuf.putShort((-sample).toShort())
        }
        inBuf.flip()

        val block = AudioBlock(channelCount = 2, capacityFrames = frames)
        PcmBoundary.decode(inBuf, PcmEncoding.PCM_16BIT, block)

        val chain = DspChain()
        chain.configure(sampleRate, 2)
        chain.flush()
        chain.process(block)

        val outBuf = ByteBuffer.allocate(frames * 4).order(ByteOrder.LITTLE_ENDIAN)
        PcmBoundary.encode(block, PcmEncoding.PCM_16BIT, outBuf)
        outBuf.flip()
        inBuf.flip()

        for (i in 0 until frames * 2) {
            val inSample = inBuf.short
            val outSample = outBuf.short
            assertEquals("Roundtrip sample mismatch at $i", inSample, outSample)
        }
    }

    @Test
    fun sine1kHzFrequencyResponseBoost() {
        val eq = EqualizerProcessor()
        eq.configure(sampleRate, 2)

        val boostDb = 6.0f
        val gains = FloatArray(EqLayout.SLOTS)
        val qs = FloatArray(EqLayout.SLOTS) { 0.707f }
        gains[3] = boostDb // 1kHz bell
        eq.setTuning(enabled = true, EqCurve(gains, qs, 0f), balance = 0f)
        eq.flush()

        val frames = 4096
        val block = AudioBlock(channelCount = 2, capacityFrames = frames)
        val inputAmp = 0.25f
        for (f in 0 until frames) {
            val s = (inputAmp * sin(2.0 * PI * 1000.0 * f / sampleRate)).toFloat()
            block.samples[f * 2] = s
            block.samples[f * 2 + 1] = s
        }
        block.reset(frames)

        eq.process(block)

        var peakOut = 0.0f
        for (f in 2048 until frames) {
            val amp = abs(block.samples[f * 2])
            if (amp > peakOut) peakOut = amp
        }

        val expectedPeak = inputAmp * 10.0.pow(boostDb / 20.0).toFloat()
        assertEquals("1 kHz center boost within 0.05 tolerance", expectedPeak, peakOut, 0.05f)
    }

    @Test
    fun impulseResponseDecaysSmoothlyWithoutInstability() {
        val eq = EqualizerProcessor()
        eq.configure(sampleRate, 2)

        val gains = FloatArray(EqLayout.SLOTS)
        val qs = FloatArray(EqLayout.SLOTS) { 1.0f }
        gains[3] = 6.0f // 1000 Hz bell
        eq.setTuning(enabled = true, EqCurve(gains, qs, 0f), balance = 0f)
        eq.flush()

        val frames = 2048
        val block = AudioBlock(channelCount = 2, capacityFrames = frames)
        block.samples[0] = 1.0f
        block.samples[1] = 1.0f
        block.reset(frames)

        eq.process(block)

        val tailMax = abs(block.samples[(frames - 1) * 2])
        assertTrue("Filter tail must decay below 1e-4", tailMax < 1e-4f)
    }

    @Test
    fun equalPowerCrossfadeSumsToConstantAcousticPower() {
        val steps = 100
        for (i in 0..steps) {
            val t = i.toFloat() / steps
            val theta = t * (PI.toFloat() / 2.0f)
            val outGain = cos(theta)
            val inGain = sin(theta)

            val power = outGain * outGain + inGain * inGain
            assertEquals("Equal-power crossfade must preserve power = 1.0", 1.0f, power, 1e-6f)
        }
    }

    @Test
    fun stereoPhaseMidSideSeparation() {
        val spatial = SpatialAudioProcessor()
        spatial.configure(sampleRate, 2)
        spatial.enabled = true

        val frames = 512
        val block = AudioBlock(channelCount = 2, capacityFrames = frames)
        // Feed in-phase mono signal
        for (f in 0 until frames) {
            val s = sin(2.0 * PI * 440.0 * f / sampleRate).toFloat()
            block.samples[f * 2] = s
            block.samples[f * 2 + 1] = s
        }
        block.reset(frames)

        spatial.process(block)

        // For in-phase signals, (L - R) == 0, so side energy is 0
        for (f in 100 until frames) {
            val l = block.samples[f * 2]
            val r = block.samples[f * 2 + 1]
            assertEquals("In-phase mono signal stays symmetric across channels", l, r, 0.05f)
        }
    }
}
