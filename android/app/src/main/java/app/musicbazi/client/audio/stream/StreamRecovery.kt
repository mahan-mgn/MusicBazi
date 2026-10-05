/*
 * Copyright (C) 2026 Music Bazi / Unstream
 *
 * Licensed under the GNU General Public License v3.0 (GPL-3.0)
 */

package app.musicbazi.client.audio.stream

import android.net.Uri

/**
 * Strategy and callback contract for recovering from stream errors (403, 410, 416, URL expiry).
 */
interface StreamRecoveryHandler {
    /**
     * Called when a stream request fails with an HTTP error or connection failure.
     * Returns a new [ResolvedAudioStream] if re-resolution succeeded, or null if unrecoverable.
     */
    suspend fun onStreamError(
        failedStream: ResolvedAudioStream,
        errorCode: Int,
        exception: Throwable,
    ): ResolvedAudioStream?
}

object DefaultStreamRecoveryHandler : StreamRecoveryHandler {
    override suspend fun onStreamError(
        failedStream: ResolvedAudioStream,
        errorCode: Int,
        exception: Throwable,
    ): ResolvedAudioStream? {
        // Default no-op resolver: bridge to JS/Backend will plug in here
        return null
    }
}
