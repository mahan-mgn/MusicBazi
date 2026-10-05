/*
 * Copyright (C) 2026 Music Bazi / Unstream
 *
 * Licensed under the GNU General Public License v3.0 (GPL-3.0)
 */

package app.musicbazi.client.audio.quality

import android.net.Uri
import app.musicbazi.client.audio.transition.TransitionLock

enum class AudioQuality(val bitrateKbps: Int, val label: String) {
    LOW(128, "128 kbps"),
    STANDARD(160, "160 kbps"),
    HIGH(320, "320 kbps"),
    LOSSLESS(1411, "Lossless FLAC"),
    HI_RES(9216, "Hi-Res Lossless"),
}

data class QualityCandidate(
    val sourceId: String,
    val quality: AudioQuality,
    val bitrateBps: Int,
    val codec: String,
    val isLossless: Boolean,
    val streamUri: Uri? = null,
)

object QualityPolicy {

    /**
     * Evaluates whether an alternative candidate is worth upgrading to mid-playback.
     *
     * Rules (Plan Section 27 & 29):
     * - Best-effort Low-Disruption Upgrade.
     * - Blocked if a crossfade transition is currently active.
     * - Must have higher audio tier or higher bitrate.
     * - Never downgrades or replaces during critical buffer states.
     */
    fun isWorthUpgrading(
        current: QualityCandidate,
        candidate: QualityCandidate,
    ): Boolean {
        if (TransitionLock.isCrossfadeActive) {
            return false // Crossfade lock: upgrade blocked during transition
        }

        // Lossless beats lossy
        if (!current.isLossless && candidate.isLossless) {
            return true
        }

        // Higher bitrate within lossy
        if (!current.isLossless && !candidate.isLossless && candidate.bitrateBps > current.bitrateBps + 32_000) {
            return true
        }

        // Hi-Res beats standard lossless
        if (current.isLossless && candidate.isLossless && candidate.quality == AudioQuality.HI_RES && current.quality != AudioQuality.HI_RES) {
            return true
        }

        return false
    }
}
