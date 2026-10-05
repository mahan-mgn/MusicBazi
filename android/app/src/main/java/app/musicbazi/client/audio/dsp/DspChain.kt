/*
 * Copyright (C) 2024-2026 Kushagra Singh / BitChord Contributors
 * Ported to Music Bazi (app.musicbazi.client.audio.dsp)
 *
 * Licensed under the GNU General Public License v3.0 (GPL-3.0)
 */

package app.musicbazi.client.audio.dsp

import android.util.Log
import androidx.media3.common.util.UnstableApi
import app.musicbazi.client.BuildConfig
import app.musicbazi.client.audio.pcm.AudioBlock

/**
 * Composite DSP chain executing Music Bazi's audio processors in their canonical sequence:
 *
 * AudioBlock(Float32) -> SpatialAudioProcessor -> EqualizerProcessor
 *   -> TransitionFilterProcessor -> LoudnessProcessor -> AudioBlock(Float32)
 *
 * Operates purely on in-place Float32 audio blocks without intermediate fixed-point quantization,
 * preserving full dynamic range and headroom.
 */
@UnstableApi
class DspChain(
    val spatial: SpatialAudioProcessor = SpatialAudioProcessor(),
    val equalizer: EqualizerProcessor = EqualizerProcessor(),
    val transition: TransitionFilterProcessor = TransitionFilterProcessor(),
    val loudness: LoudnessProcessor = LoudnessProcessor(),
) : FloatAudioProcessor {

    private var currentSampleRate: Int = 0
    private var processCounter: Long = 0L

    override fun configure(sampleRate: Int, channelCount: Int) {
        this.currentSampleRate = sampleRate
        spatial.configure(sampleRate, channelCount)
        equalizer.configure(sampleRate, channelCount)
        transition.configure(sampleRate, channelCount)
        loudness.configure(sampleRate, channelCount)
    }

    /** A new track has begun gaplessly on this sink; updates Loudness boundary. */
    fun onStreamBoundary() {
        loudness.onStreamBoundary()
    }

    override fun process(block: AudioBlock) {
        if (block.frameCount == 0) return

        if (BuildConfig.DEBUG) {
            processCounter++
            if (processCounter == 1L || processCounter % 500L == 0L) {
                try {
                    val count = processCounter
                    val frames = block.frameCount
                    val sr = currentSampleRate
                    val spatialOn = spatial.enabled
                    val eqOn = equalizer.isEnabled
                    val transitionOn = transition.isFiltering
                    Log.d(
                        TAG,
                        "process() #$count frames=$frames sr=$sr " +
                            "spatial=$spatialOn eq=$eqOn transition=$transitionOn",
                    )
                } catch (_: Throwable) {
                }
            }
        }

        spatial.process(block)
        equalizer.process(block)
        transition.process(block)
        loudness.process(block)
    }

    override fun flush() {
        spatial.flush()
        equalizer.flush()
        transition.flush()
        loudness.flush()
    }

    override fun reset() {
        processCounter = 0L
        spatial.reset()
        equalizer.reset()
        transition.reset()
        loudness.reset()
    }

    companion object {
        private const val TAG = "DspChain"
    }
}
