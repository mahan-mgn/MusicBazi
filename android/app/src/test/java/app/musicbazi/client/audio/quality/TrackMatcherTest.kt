/*
 * Copyright (C) 2026 Music Bazi / Unstream
 *
 * Licensed under the GNU General Public License v3.0 (GPL-3.0)
 */

package app.musicbazi.client.audio.quality

import android.net.Uri
import app.musicbazi.client.audio.transition.TransitionLock
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TrackMatcherTest {

    @Test
    fun exactRecordingMatches() {
        val target = TrackMatcher.Target(
            title = "Bohemian Rhapsody",
            artist = "Queen",
            durationSec = 354,
        )
        val candidate = TrackMatcher.Candidate(
            title = "Bohemian Rhapsody (Official Video)",
            artist = "Queen",
            durationSec = 355,
        )
        assertTrue(TrackMatcher.matches(candidate, target))
    }

    @Test
    fun versionMismatchRejectsRemixAgainstOriginal() {
        val target = TrackMatcher.Target(
            title = "Blinding Lights",
            artist = "The Weeknd",
            durationSec = 200,
        )
        val remixCandidate = TrackMatcher.Candidate(
            title = "Blinding Lights (Remix)",
            artist = "The Weeknd",
            durationSec = 200,
        )
        assertFalse(TrackMatcher.matches(remixCandidate, target))
    }

    @Test
    fun versionMismatchRejectsLiveAgainstOriginal() {
        val target = TrackMatcher.Target(
            title = "Hotel California",
            artist = "Eagles",
            durationSec = 390,
        )
        val liveCandidate = TrackMatcher.Candidate(
            title = "Hotel California (Live at the Forum)",
            artist = "Eagles",
            durationSec = 390,
        )
        assertFalse(TrackMatcher.matches(liveCandidate, target))
    }

    @Test
    fun severeDurationMismatchRejectsCandidate() {
        val target = TrackMatcher.Target(
            title = "Shape of You",
            artist = "Ed Sheeran",
            durationSec = 233,
        )
        val loopCandidate = TrackMatcher.Candidate(
            title = "Shape of You",
            artist = "Ed Sheeran",
            durationSec = 600, // 10-minute loop
        )
        assertFalse(TrackMatcher.matches(loopCandidate, target))
    }

    @Test
    fun qualityUpgradePolicyPrefersLossless() {
        val current = QualityCandidate(
            sourceId = "1",
            quality = AudioQuality.STANDARD,
            bitrateBps = 160_000,
            codec = "opus",
            isLossless = false,
        )
        val candidate = QualityCandidate(
            sourceId = "2",
            quality = AudioQuality.LOSSLESS,
            bitrateBps = 1_411_000,
            codec = "flac",
            isLossless = true,
        )
        assertTrue(QualityPolicy.isWorthUpgrading(current, candidate))
    }

    @Test
    fun qualityUpgradeBlockedDuringCrossfade() {
        TransitionLock.isCrossfadeActive = true
        try {
            val current = QualityCandidate(
                sourceId = "1",
                quality = AudioQuality.STANDARD,
                bitrateBps = 160_000,
                codec = "opus",
                isLossless = false,
            )
            val candidate = QualityCandidate(
                sourceId = "2",
                quality = AudioQuality.LOSSLESS,
                bitrateBps = 1_411_000,
                codec = "flac",
                isLossless = true,
            )
            assertFalse(QualityPolicy.isWorthUpgrading(current, candidate))
        } finally {
            TransitionLock.isCrossfadeActive = false
        }
    }
}
