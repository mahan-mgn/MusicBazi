/*
 * Copyright (C) 2024-2026 Kushagra Singh / BitChord Contributors
 * Ported to Music Bazi (app.musicbazi.client.audio.output)
 *
 * Licensed under the GNU General Public License v3.0 (GPL-3.0)
 */

package app.musicbazi.client.audio.output

import android.media.AudioAttributes
import android.media.AudioDeviceInfo
import android.media.AudioFormat
import android.media.AudioManager
import android.os.Build
import androidx.annotation.RequiresApi

/**
 * Live capability probe testing Android's runtime direct-playback APIs (API 33+).
 */
object DirectAudioProbe {

    data class DirectSupport(
        val isDirectSupported: Boolean,
        val isOffloadSupported: Boolean,
        val supportsFloat: Boolean,
        val supportsPcm24: Boolean,
        val supportsPcm16: Boolean,
        val directProfiles: List<DirectProfileInfo> = emptyList(),
        val description: String,
    ) {
        companion object {
            val NONE = DirectSupport(
                isDirectSupported = false,
                isOffloadSupported = false,
                supportsFloat = false,
                supportsPcm24 = false,
                supportsPcm16 = false,
                description = "Direct playback not supported or API < 33",
            )
        }
    }

    data class DirectProfileInfo(
        val format: Int,
        val sampleRates: List<Int>,
        val channelMasks: List<Int>,
    )

    fun probeDirectSupport(
        audioManager: AudioManager?,
        sampleRateHz: Int,
        channelCount: Int,
        activeDevice: AudioDeviceInfo? = null,
    ): DirectSupport {
        if (audioManager == null || Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
            return DirectSupport.NONE
        }

        return try {
            probeDirectSupportApi33(audioManager, sampleRateHz, channelCount, activeDevice)
        } catch (_: Throwable) {
            DirectSupport.NONE
        }
    }

    @RequiresApi(Build.VERSION_CODES.TIRAMISU)
    private fun probeDirectSupportApi33(
        audioManager: AudioManager,
        sampleRateHz: Int,
        channelCount: Int,
        activeDevice: AudioDeviceInfo?,
    ): DirectSupport {
        val channelMask = if (channelCount == 1) {
            AudioFormat.CHANNEL_OUT_MONO
        } else {
            AudioFormat.CHANNEL_OUT_STEREO
        }

        val attributes = AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_MEDIA)
            .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
            .build()

        val directProfilesList = mutableListOf<DirectProfileInfo>()
        try {
            val profiles = audioManager.getDirectProfilesForAttributes(attributes)
            for (p in profiles) {
                directProfilesList.add(
                    DirectProfileInfo(
                        format = p.format,
                        sampleRates = p.sampleRates.toList(),
                        channelMasks = p.channelMasks.toList(),
                    ),
                )
            }
        } catch (_: Throwable) {
        }

        val floatFormat = AudioFormat.Builder()
            .setEncoding(AudioFormat.ENCODING_PCM_FLOAT)
            .setSampleRate(sampleRateHz)
            .setChannelMask(channelMask)
            .build()
        val floatSupport = AudioManager.getDirectPlaybackSupport(floatFormat, attributes)
        val supportsFloatDirect = (floatSupport != AudioManager.DIRECT_PLAYBACK_NOT_SUPPORTED)

        val pcm24Format = AudioFormat.Builder()
            .setEncoding(AudioFormat.ENCODING_PCM_24BIT_PACKED)
            .setSampleRate(sampleRateHz)
            .setChannelMask(channelMask)
            .build()
        val pcm24Support = AudioManager.getDirectPlaybackSupport(pcm24Format, attributes)
        val supportsPcm24Direct = (pcm24Support != AudioManager.DIRECT_PLAYBACK_NOT_SUPPORTED)

        val pcm16Format = AudioFormat.Builder()
            .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
            .setSampleRate(sampleRateHz)
            .setChannelMask(channelMask)
            .build()
        val pcm16Support = AudioManager.getDirectPlaybackSupport(pcm16Format, attributes)
        val supportsPcm16Direct = (pcm16Support != AudioManager.DIRECT_PLAYBACK_NOT_SUPPORTED)

        val anyDirect = supportsFloatDirect || supportsPcm24Direct || supportsPcm16Direct
        val anyOffload = (floatSupport and AudioManager.DIRECT_PLAYBACK_OFFLOAD_SUPPORTED) != 0 ||
            (pcm24Support and AudioManager.DIRECT_PLAYBACK_OFFLOAD_SUPPORTED) != 0 ||
            (pcm16Support and AudioManager.DIRECT_PLAYBACK_OFFLOAD_SUPPORTED) != 0

        val desc = when {
            anyDirect -> "Direct playback supported"
            anyOffload -> "Offload supported"
            else -> "Standard mixed AudioTrack path"
        }

        return DirectSupport(
            isDirectSupported = anyDirect,
            isOffloadSupported = anyOffload,
            supportsFloat = supportsFloatDirect,
            supportsPcm24 = supportsPcm24Direct,
            supportsPcm16 = supportsPcm16Direct,
            directProfiles = directProfilesList,
            description = desc,
        )
    }
}
