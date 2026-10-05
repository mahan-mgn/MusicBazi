/*
 * Copyright (C) 2026 Music Bazi / Unstream
 *
 * Licensed under the GNU General Public License v3.0 (GPL-3.0)
 */

package app.musicbazi.client.audio.quality

import android.util.Log
import app.musicbazi.client.audio.core.MusicBaziAudioEngine
import app.musicbazi.client.audio.stream.ResolvedAudioStream
import app.musicbazi.client.audio.transition.TransitionLock
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

/**
 * Best-effort, low-disruption background quality upgrade engine.
 */
class QualityEngine(
    private val scope: CoroutineScope = CoroutineScope(Dispatchers.Main),
    private val candidateResolver: suspend (target: TrackMatcher.Target) -> List<ResolvedAudioStream> = { emptyList() },
) {

    fun checkAndUpgrade(
        engine: MusicBaziAudioEngine,
        currentStream: ResolvedAudioStream,
        target: TrackMatcher.Target,
    ) {
        if (TransitionLock.isCrossfadeActive) return

        val currentCandidate = QualityCandidate(
            sourceId = currentStream.sourceId,
            quality = if (currentStream.isLossless) AudioQuality.LOSSLESS else AudioQuality.STANDARD,
            bitrateBps = currentStream.bitrateBps ?: 160_000,
            codec = currentStream.codec ?: "unknown",
            isLossless = currentStream.isLossless,
            streamUri = currentStream.uri,
        )

        scope.launch {
            try {
                val candidates = candidateResolver(target)
                for (stream in candidates) {
                    val candidateDesc = TrackMatcher.Candidate(
                        title = target.title,
                        artist = target.artist,
                        durationSec = target.durationSec,
                    )
                    // 1. Verify candidate matches the exact recording
                    if (!TrackMatcher.matches(candidateDesc, target)) {
                        continue
                    }

                    val candidateQuality = QualityCandidate(
                        sourceId = stream.sourceId,
                        quality = if (stream.isLossless) AudioQuality.LOSSLESS else AudioQuality.HIGH,
                        bitrateBps = stream.bitrateBps ?: 320_000,
                        codec = stream.codec ?: "unknown",
                        isLossless = stream.isLossless,
                        streamUri = stream.uri,
                    )

                    // 2. Verify candidate is worth upgrading
                    if (QualityPolicy.isWorthUpgrading(currentCandidate, candidateQuality)) {
                        applyUpgrade(engine, stream)
                        break
                    }
                }
            } catch (e: Exception) {
                Log.w(TAG, "Quality upgrade check failed gracefully: ${e.message}")
            }
        }
    }

    private fun applyUpgrade(engine: MusicBaziAudioEngine, newStream: ResolvedAudioStream) {
        if (TransitionLock.isCrossfadeActive) return

        try {
            TransitionLock.isQualityUpgradeActive = true
            val currentPos = engine.state.value.positionMs
            engine.play(newStream)
            if (currentPos > 0L) {
                engine.seekTo(currentPos)
            }
            Log.i(TAG, "Successfully upgraded stream to ${newStream.codec} (${newStream.bitrateBps} bps)")
        } finally {
            TransitionLock.isQualityUpgradeActive = false
        }
    }

    companion object {
        private const val TAG = "QualityEngine"
    }
}
