/*
 * Copyright (C) 2024-2026 Kushagra Singh / BitChord Contributors
 * Ported to Music Bazi (app.musicbazi.client.audio.output)
 *
 * Licensed under the GNU General Public License v3.0 (GPL-3.0)
 */

package app.musicbazi.client.audio.output

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AudioOutputPolicyTest {

    @Test
    fun floatRequiresPreferredUsbRouteAndAdvertisedSupport() {
        assertTrue(
            AudioOutputPolicy.shouldUseFloatOutput(
                OutputPcmMode.FLOAT_32,
                isPreferredUsbRoute = true,
                advertisesPcmFloat = true,
            ),
        )
    }

    @Test
    fun floatFallsBackOnSpeakerEvenWhenRequested() {
        assertFalse(
            AudioOutputPolicy.shouldUseFloatOutput(
                OutputPcmMode.FLOAT_32,
                isPreferredUsbRoute = false,
                advertisesPcmFloat = true,
            ),
        )
    }

    @Test
    fun floatFallsBackWhenUsbDoesNotAdvertiseIt() {
        assertFalse(
            AudioOutputPolicy.shouldUseFloatOutput(
                OutputPcmMode.FLOAT_32,
                isPreferredUsbRoute = true,
                advertisesPcmFloat = false,
            ),
        )
    }

    @Test
    fun pcm16NeverRequestsFloat() {
        assertFalse(
            AudioOutputPolicy.shouldUseFloatOutput(
                OutputPcmMode.PCM_16,
                isPreferredUsbRoute = true,
                advertisesPcmFloat = true,
            ),
        )
    }

    @Test
    fun routeAwarePhoneIsAlwaysCappedAt16Bit() {
        assertFalse(
            AudioOutputPolicy.shouldUseFloatOutput(
                OutputPcmMode.FLOAT_32,
                routeKind = AudioRouting.Kind.PHONE,
                advertisesPcmFloat = true,
            ),
        )
    }

    @Test
    fun routeAwareUsbAllowsFloatWhenAdvertised() {
        assertTrue(
            AudioOutputPolicy.shouldUseFloatOutput(
                OutputPcmMode.FLOAT_32,
                routeKind = AudioRouting.Kind.USB,
                advertisesPcmFloat = true,
            ),
        )
        assertFalse(
            AudioOutputPolicy.shouldUseFloatOutput(
                OutputPcmMode.FLOAT_32,
                routeKind = AudioRouting.Kind.USB,
                advertisesPcmFloat = false,
            ),
        )
    }

    @Test
    fun routeAwareBluetoothAllowsFloatOnlyWhenAdvertised() {
        assertTrue(
            AudioOutputPolicy.shouldUseFloatOutput(
                OutputPcmMode.FLOAT_32,
                routeKind = AudioRouting.Kind.BLUETOOTH,
                advertisesPcmFloat = true,
            ),
        )
        assertFalse(
            AudioOutputPolicy.shouldUseFloatOutput(
                OutputPcmMode.FLOAT_32,
                routeKind = AudioRouting.Kind.BLUETOOTH,
                advertisesPcmFloat = false,
            ),
        )
    }

    @Test
    fun samsungVendorFlacDecoderIsBlockedForFloatOutput() {
        assertTrue(AudioOutputPolicy.isUnsafeFloatFlacDecoder("c2.sec.flac.decoder"))
        assertTrue(AudioOutputPolicy.isUnsafeFloatFlacDecoder("OMX.SEC.FLAC.Decoder"))
        assertFalse(AudioOutputPolicy.isUnsafeFloatFlacDecoder("c2.android.flac.decoder"))
    }
}
