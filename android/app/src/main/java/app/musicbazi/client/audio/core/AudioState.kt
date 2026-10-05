/*
 * Copyright (C) 2026 Music Bazi / Unstream
 *
 * Licensed under the GNU General Public License v3.0 (GPL-3.0)
 */

package app.musicbazi.client.audio.core

/**
 * State representation of the native audio engine.
 */
data class AudioState(
    val status: Status = Status.IDLE,
    val isPlaying: Boolean = false,
    val currentTrackId: String? = null,
    val positionMs: Long = 0L,
    val durationMs: Long = 0L,
    val volume: Float = 1.0f,
    val isBuffering: Boolean = false,
    val errorMessage: String? = null,
) {
    enum class Status {
        IDLE,
        BUFFERING,
        READY,
        ENDED,
        ERROR
    }
}
