/*
 * Copyright (C) 2026 Music Bazi / Unstream
 *
 * Licensed under the GNU General Public License v3.0 (GPL-3.0)
 */

package app.musicbazi.client.audio.stream

import android.net.Uri

/**
 * Provider-independent audio stream contract consumed by Music Bazi Native Audio Engine.
 *
 * Captures all essential transport, container, codec, dynamic range and lifetime
 * properties without binding to any specific provider implementation (YouTube, SoundCloud, Local, etc.).
 */
data class ResolvedAudioStream(
    val uri: Uri,
    val mimeType: String? = null,
    val codec: String? = null,
    val bitrateBps: Int? = null,
    val sampleRateHz: Int? = null,
    val bitDepth: Int? = null,
    val channelCount: Int? = null,
    val durationMs: Long? = null,
    val isLossless: Boolean = false,
    val gainDb: Float? = null,
    val sourceId: String = "",
    val expiresAtMs: Long? = null,
    val streamType: StreamType = StreamType.PROGRESSIVE,
    val headers: Map<String, String> = emptyMap()
)
