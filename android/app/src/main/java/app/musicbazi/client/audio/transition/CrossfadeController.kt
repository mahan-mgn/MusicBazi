/*
 * Copyright (C) 2024-2026 Kushagra Singh / BitChord Contributors
 * Ported to Music Bazi (app.musicbazi.client.audio.transition)
 *
 * Licensed under the GNU General Public License v3.0 (GPL-3.0)
 */

package app.musicbazi.client.audio.transition

import android.os.SystemClock
import android.util.Log
import androidx.media3.common.C
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.ExoPlayer
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * Shared operation lock enforcing mutual exclusion between Crossfade and Quality Upgrade.
 */
object TransitionLock {
    @Volatile
    var isCrossfadeActive: Boolean = false

    @Volatile
    var isQualityUpgradeActive: Boolean = false
}

/**
 * Dual-ExoPlayer peer crossfade controller with equal-power curves and safe state-machine bailing.
 *
 * Curve:
 * - out = cos(t * PI / 2)
 * - in  = sin(t * PI / 2)
 * Holds constant total acoustic power (cos^2 + sin^2 = 1.0) without volume dips.
 */
@UnstableApi
class CrossfadeController(
    private val scope: CoroutineScope,
    private val active: () -> ExoPlayer,
    private val standby: () -> ExoPlayer,
    private val onHandoff: (outgoing: ExoPlayer, incoming: ExoPlayer) -> Unit,
    private val crossfadeSeconds: () -> Float = { 0f },
    private val onBlendHeadroom: (Float) -> Unit = {},
) {

    enum class Phase {
        IDLE,
        ARMING,
        FADING,
        BAILING,
    }

    @Volatile
    var phase: Phase = Phase.IDLE
        private set

    private var tickerJob: Job? = null
    private var fadeDurationMs: Long = 0L
    private var fadeStartElapsedMs: Long = 0L
    private var handedOff: Boolean = false

    private var outgoingPlayer: ExoPlayer? = null
    private var incomingPlayer: ExoPlayer? = null
    private var listeningTo: ExoPlayer? = null

    private val playerListener = object : Player.Listener {
        override fun onPositionDiscontinuity(
            oldPosition: Player.PositionInfo,
            newPosition: Player.PositionInfo,
            reason: Int,
        ) {
            if (reason == Player.DISCONTINUITY_REASON_SEEK) {
                bail()
            }
        }

        override fun onMediaItemTransition(mediaItem: androidx.media3.common.MediaItem?, reason: Int) {
            when (reason) {
                Player.MEDIA_ITEM_TRANSITION_REASON_PLAYLIST_CHANGED,
                Player.MEDIA_ITEM_TRANSITION_REASON_SEEK -> bail()
            }
        }

        override fun onPlayerError(error: PlaybackException) {
            bail()
        }
    }

    fun start() {
        listenTo(active())
        tickerJob?.cancel()
        tickerJob = scope.launch {
            while (isActive) {
                tick()
                delay(
                    when (phase) {
                        Phase.IDLE -> IDLE_STEP_MS
                        Phase.ARMING -> ARM_STEP_MS
                        Phase.FADING -> FADE_STEP_MS
                        Phase.BAILING -> BAIL_STEP_MS
                    },
                )
            }
        }
    }

    fun release() {
        tickerJob?.cancel()
        tickerJob = null
        listeningTo?.removeListener(playerListener)
        listeningTo = null
        active().volume = 1.0f
        onBlendHeadroom(1.0f)
        TransitionLock.isCrossfadeActive = false
        phase = Phase.IDLE
    }

    fun onSkipRequested() {
        if (phase != Phase.IDLE) {
            bail()
        }
    }

    fun bail() {
        if (phase == Phase.IDLE) return
        phase = Phase.BAILING
        incomingPlayer?.let { inc ->
            inc.volume = 1.0f
        }
        outgoingPlayer?.let { out ->
            out.stop()
            out.volume = 1.0f
        }
        onBlendHeadroom(1.0f)
        TransitionLock.isCrossfadeActive = false
        phase = Phase.IDLE
    }

    private fun tick() {
        val player = active()
        listenTo(player)

        // Sync play/pause between active and standby during transition
        if (phase == Phase.FADING) {
            val out = outgoingPlayer
            val inc = incomingPlayer
            if (out != null && inc != null) {
                if (handedOff) {
                    out.playWhenReady = inc.playWhenReady
                } else {
                    inc.playWhenReady = out.playWhenReady
                }
            }
        }

        when (phase) {
            Phase.IDLE -> considerAutoTransition()
            Phase.ARMING -> driveArming()
            Phase.FADING -> driveFade()
            Phase.BAILING -> driveBail()
        }
    }

    private fun considerAutoTransition() {
        val seconds = crossfadeSeconds()
        if (seconds <= 0f) return
        if (TransitionLock.isQualityUpgradeActive) return // Quality upgrade has priority lock

        val player = active()
        if (!player.isPlaying) return

        val duration = player.duration
        if (duration == C.TIME_UNSET || duration <= 0L) return

        val position = player.currentPosition
        val remaining = duration - position
        val fadeMs = (seconds * 1000).toLong().coerceIn(MIN_FADE_MS, MAX_FADE_MS)

        // Arm before fade starts
        if (remaining <= fadeMs + ARM_LEAD_MS && remaining > 0L) {
            beginArming(fadeMs)
        }
    }

    private fun beginArming(fadeMs: Long) {
        if (phase != Phase.IDLE) return
        TransitionLock.isCrossfadeActive = true
        fadeDurationMs = fadeMs
        outgoingPlayer = active()
        incomingPlayer = standby()
        phase = Phase.ARMING
    }

    private fun driveArming() {
        val out = outgoingPlayer ?: run { bail(); return }
        val remaining = out.duration - out.currentPosition

        if (remaining <= fadeDurationMs) {
            beginFade()
        }
    }

    private fun beginFade() {
        phase = Phase.FADING
        fadeStartElapsedMs = SystemClock.elapsedRealtime()
        handedOff = false

        val inc = incomingPlayer ?: run { bail(); return }
        inc.volume = 0.0f
        inc.play()
    }

    private fun driveFade() {
        val out = outgoingPlayer ?: run { bail(); return }
        val inc = incomingPlayer ?: run { bail(); return }

        val elapsed = SystemClock.elapsedRealtime() - fadeStartElapsedMs
        val t = (elapsed.toFloat() / fadeDurationMs).coerceIn(0.0f, 1.0f)

        // Equal-power crossfade curve
        val theta = t * (PI.toFloat() / 2.0f)
        val outVol = cos(theta).coerceIn(0.0f, 1.0f)
        val inVol = sin(theta).coerceIn(0.0f, 1.0f)

        out.volume = outVol
        inc.volume = inVol

        // Blend headroom trim to prevent summing clipping
        val headroom = (1.0f / sqrt(outVol + inVol)).coerceIn(0.707f, 1.0f)
        onBlendHeadroom(headroom)

        // Role swap handoff at midpoint
        if (t >= 0.5f && !handedOff) {
            handedOff = true
            onHandoff(out, inc)
            listenTo(inc)
        }

        // Completion
        if (t >= 1.0f) {
            finishFade()
        }
    }

    private fun finishFade() {
        val out = outgoingPlayer
        val inc = incomingPlayer
        out?.stop()
        out?.volume = 1.0f
        inc?.volume = 1.0f
        onBlendHeadroom(1.0f)

        outgoingPlayer = null
        incomingPlayer = null
        handedOff = false
        TransitionLock.isCrossfadeActive = false
        phase = Phase.IDLE
    }

    private fun driveBail() {
        finishFade()
    }

    private fun listenTo(target: ExoPlayer) {
        if (listeningTo === target) return
        listeningTo?.removeListener(playerListener)
        target.addListener(playerListener)
        listeningTo = target
    }

    companion object {
        private const val TAG = "CrossfadeController"
        private const val IDLE_STEP_MS = 250L
        private const val ARM_STEP_MS = 50L
        private const val FADE_STEP_MS = 30L
        private const val BAIL_STEP_MS = 30L

        private const val MIN_FADE_MS = 500L
        private const val MAX_FADE_MS = 12000L
        private const val ARM_LEAD_MS = 2500L
    }
}
