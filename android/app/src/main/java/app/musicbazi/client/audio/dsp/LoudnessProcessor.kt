/*
 * Copyright (C) 2024-2026 Kushagra Singh / BitChord Contributors
 * Ported to Music Bazi (app.musicbazi.client.audio.dsp)
 *
 * Licensed under the GNU General Public License v3.0 (GPL-3.0)
 */

package app.musicbazi.client.audio.dsp

import app.musicbazi.client.audio.pcm.AudioBlock
import kotlin.math.abs
import kotlin.math.exp

/**
 * Loudness normalization, applied inside one player's own DSP chain, plus the
 * peak limiter that keeps the result — and a crossfade built on it — from clipping.
 */
class LoudnessProcessor : FloatAudioProcessor {

    /** Linear gain for a media id: 1 when unknown or normalization is off. Must be thread-safe. */
    @Volatile
    var gainFor: (String) -> Float = { 1f }

    /** The track this chain is currently processing. */
    @Volatile
    var mediaId: String? = null

    /** The track that follows [mediaId] gaplessly on this player, if any. */
    @Volatile
    var nextMediaId: String? = null

    @Volatile
    private var trimTarget = 1f

    private var sampleRate = 0
    private var channelCount = 0
    private var currentGain = 1f
    private var currentTrim = 1f
    private var reduction = 1f
    private var glideCoef = 1f
    private var releaseCoef = 1f

    @Volatile
    private var snap = true

    /** Points this chain at a track, and the one after it. Called from the app thread. */
    fun track(mediaId: String?, nextMediaId: String?) {
        this.mediaId = mediaId
        this.nextMediaId = nextMediaId
    }

    /**
     * Headroom taken off this track while it overlaps another: 1 between
     * transitions, a little lower during one. Glided on the audio thread.
     */
    fun setBlendTrim(value: Float) {
        trimTarget = value.coerceIn(MIN_TRIM, 1f)
    }

    fun onStreamBoundary() {
        nextMediaId?.let { mediaId = it }
        snap = true
    }

    override fun configure(sampleRate: Int, channelCount: Int) {
        this.sampleRate = sampleRate
        this.channelCount = channelCount
        glideCoef = coefficient(GLIDE_SECONDS, sampleRate)
        releaseCoef = coefficient(RELEASE_SECONDS, sampleRate)
        snap = true
    }

    override fun flush() {
        reduction = 1f
        snap = true
    }

    override fun reset() {
        sampleRate = 0
        channelCount = 0
        reduction = 1f
        snap = true
    }

    override fun process(block: AudioBlock) {
        val frames = block.frameCount
        val channels = channelCount
        if (frames == 0 || channels < 1 || sampleRate <= 0) return

        val targetGain = targetGain()
        val targetTrim = trimTarget
        if (snap) {
            currentGain = targetGain
            currentTrim = targetTrim
            snap = false
        }

        if (targetGain == 1f && targetTrim >= 1f &&
            abs(currentGain - 1f) < SETTLED && currentTrim >= 1f - SETTLED && reduction >= 1f - SETTLED
        ) {
            currentGain = 1f
            currentTrim = 1f
            reduction = 1f
            return
        }

        val samples = block.samples
        var gain = currentGain
        var trim = currentTrim
        var gr = reduction
        var index = 0
        for (frame in 0 until frames) {
            gain += (targetGain - gain) * glideCoef
            trim += (targetTrim - trim) * glideCoef
            val scale = gain * trim
            var peak = 0f
            for (channel in 0 until channels) {
                val magnitude = abs(samples[index + channel])
                if (magnitude > peak) peak = magnitude
            }
            peak *= scale
            val wanted = if (peak > LIMIT) LIMIT / peak else 1f
            gr = if (wanted < gr) wanted else gr + (wanted - gr) * releaseCoef
            val applied = scale * gr
            for (channel in 0 until channels) {
                samples[index + channel] *= applied
            }
            index += channels
        }
        currentGain = gain
        currentTrim = trim
        reduction = gr
    }

    private fun targetGain(): Float = mediaId?.let { runCatching { gainFor(it) }.getOrNull() } ?: 1f

    private fun coefficient(seconds: Double, rate: Int): Float =
        if (rate <= 0) 1f else (1.0 - exp(-1.0 / (seconds * rate))).toFloat()

    companion object {
        private const val LIMIT = 0.985f
        private const val MIN_TRIM = 0.5f
        private const val GLIDE_SECONDS = 0.04
        private const val RELEASE_SECONDS = 0.08
        private const val SETTLED = 1e-4f
    }
}
