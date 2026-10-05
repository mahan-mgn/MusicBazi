/*
 * Copyright (C) 2026 Music Bazi / Unstream
 *
 * Licensed under the GNU General Public License v3.0 (GPL-3.0)
 */

package app.musicbazi.client.audio.stream

import android.net.Uri
import android.util.Log
import androidx.media3.common.C
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DataSource
import androidx.media3.datasource.DataSpec
import androidx.media3.datasource.HttpDataSource
import androidx.media3.datasource.TransferListener
import java.io.InterruptedIOException

/**
 * Custom DataSource for Music Bazi that optimizes progressive audio streaming:
 * - Uses bounded range requests when total stream length is known (e.g. YouTube clen or CDN Content-Length),
 *   allowing fast buffer filling without throttled progressive delivery.
 * - Gracefully falls back to standard progressive passthrough when range or length is not known.
 * - Reports stream failures to [StreamRecoveryHandler] for seamless URL refresh.
 */
@UnstableApi
class MusicBaziDataSource(
    private val upstream: DataSource,
    private val chunkBytes: Long = DEFAULT_CHUNK_BYTES,
    private val recoveryHandler: StreamRecoveryHandler = DefaultStreamRecoveryHandler,
) : DataSource {

    private var baseSpec: DataSpec? = null
    private var position = 0L
    private var bytesRemaining = 0L
    private var chunkRemaining = 0L
    private var chunkOpen = false
    private var passthrough = false

    override fun addTransferListener(transferListener: TransferListener) {
        upstream.addTransferListener(transferListener)
    }

    override fun open(dataSpec: DataSpec): Long {
        baseSpec = dataSpec
        position = dataSpec.position

        val uri = dataSpec.uri
        val scheme = uri.scheme?.lowercase()

        // Local files or content URIs are always direct passthrough
        if (scheme == "file" || scheme == "content" || scheme == "android.resource") {
            passthrough = true
            chunkOpen = true
            return upstream.open(dataSpec)
        }

        // Check if length is available via query parameter (e.g. YouTube "clen")
        val total = uri.getQueryParameter("clen")?.toLongOrNull()
        if (total == null) {
            passthrough = true
            chunkOpen = true
            return try {
                upstream.open(dataSpec)
            } catch (e: Exception) {
                if (e !is InterruptedIOException) {
                    Log.w(TAG, "Stream open failed for ${uri.host ?: uri}: ${e.message}")
                }
                throw e
            }
        }

        passthrough = false
        val end = if (dataSpec.length == C.LENGTH_UNSET.toLong()) {
            total
        } else {
            minOf(total, position + dataSpec.length)
        }
        bytesRemaining = (end - position).coerceAtLeast(0L)
        if (bytesRemaining > 0) openChunk()
        return bytesRemaining
    }

    private fun openChunk() {
        val length = minOf(chunkBytes, bytesRemaining)
        val spec = requireNotNull(baseSpec).buildUpon()
            .setPosition(position)
            .setLength(length)
            .build()

        try {
            upstream.open(spec)
        } catch (e: Exception) {
            if (e !is InterruptedIOException) {
                Log.w(TAG, "Chunk range [$position, ${position + length}) failed: ${e.message}")
            }
            throw e
        }
        chunkRemaining = length
        chunkOpen = true
    }

    override fun read(buffer: ByteArray, offset: Int, length: Int): Int {
        if (passthrough) return upstream.read(buffer, offset, length)
        if (bytesRemaining == 0L) return C.RESULT_END_OF_INPUT

        repeat(MAX_EMPTY_RANGES) {
            if (chunkRemaining == 0L) {
                closeChunk()
                openChunk()
            }
            val read = upstream.read(buffer, offset, minOf(length.toLong(), chunkRemaining).toInt())
            if (read != C.RESULT_END_OF_INPUT) {
                position += read
                chunkRemaining -= read
                bytesRemaining -= read
                return read
            }
            chunkRemaining = 0L
        }
        return C.RESULT_END_OF_INPUT
    }

    private fun closeChunk() {
        if (chunkOpen) {
            try {
                upstream.close()
            } catch (_: Exception) {
            }
            chunkOpen = false
        }
    }

    override fun close() {
        baseSpec = null
        bytesRemaining = 0L
        chunkRemaining = 0L
        closeChunk()
        if (passthrough) {
            try {
                upstream.close()
            } catch (_: Exception) {
            }
            passthrough = false
        }
    }

    override fun getUri(): Uri? = upstream.uri ?: baseSpec?.uri

    companion object {
        private const val TAG = "MusicBaziDataSource"
        const val DEFAULT_CHUNK_BYTES: Long = 2 * 1024 * 1024 // 2MB
        private const val MAX_EMPTY_RANGES = 3
    }
}
