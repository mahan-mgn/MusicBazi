/*
 * Copyright (C) 2026 Music Bazi / Unstream
 *
 * Licensed under the GNU General Public License v3.0 (GPL-3.0)
 */

package app.musicbazi.client.audio.stream

/**
 * Underlying stream delivery protocol/type for audio playback.
 */
enum class StreamType {
    /** Standard progressive HTTP(S) stream (supports byte-range requests). */
    PROGRESSIVE,

    /** HTTP Live Streaming manifest (.m3u8). */
    HLS,

    /** Dynamic Adaptive Streaming over HTTP (.mpd). */
    DASH,

    /** Local on-device file (e.g. downloads, cache, local storage). */
    LOCAL_FILE,

    /** Local Area Network stream (home server, Termux local instance). */
    LAN_STREAM
}
