/*
 * Copyright (C) 2024-2026 Kushagra Singh / BitChord Contributors
 * Ported to Music Bazi (app.musicbazi.client.audio.usb)
 *
 * Licensed under the GNU General Public License v3.0 (GPL-3.0)
 */

package app.musicbazi.client.audio.usb

import app.musicbazi.client.audio.pcm.PcmEncoding
import java.nio.ByteBuffer

/**
 * Isolated abstraction for direct USB hardware audio streaming.
 *
 * When direct streaming is inactive, unavailable, or unpermitted, Music Bazi
 * cleanly falls back to [app.musicbazi.client.audio.dsp.PrecisionAudioSink] and AudioTrack.
 */
interface DirectAudioOutput {

    val isActive: Boolean

    val probeResult: DirectUsbProbeResult

    fun configure(
        sampleRate: Int,
        channelCount: Int,
        encoding: PcmEncoding,
    ): Boolean

    fun write(buffer: ByteBuffer): Int

    fun flush()

    fun release()
}

class DefaultDirectAudioOutput(
    override val probeResult: DirectUsbProbeResult = DirectUsbProbeResult.notPresent(),
) : DirectAudioOutput {

    override val isActive: Boolean = false

    override fun configure(sampleRate: Int, channelCount: Int, encoding: PcmEncoding): Boolean = false

    override fun write(buffer: ByteBuffer): Int = 0

    override fun flush() {}

    override fun release() {}
}
