/*
 * Copyright (C) 2026 Music Bazi / Unstream
 *
 * Licensed under the GNU General Public License v3.0 (GPL-3.0)
 */

package app.musicbazi.client.audio.usb

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class UsbDirectManagerTest {

    @Test
    fun bitDepthCalculationMatchesPacketBudget() {
        val depthsSmall = UsbDirectManager.calculateSupportedBitDepths(100)
        assertTrue(depthsSmall.isEmpty())

        val depths16 = UsbDirectManager.calculateSupportedBitDepths(200)
        assertEquals(listOf(16), depths16)

        val depths24 = UsbDirectManager.calculateSupportedBitDepths(300)
        assertEquals(listOf(16, 24), depths24)

        val depths32 = UsbDirectManager.calculateSupportedBitDepths(512)
        assertEquals(listOf(16, 24, 32), depths32)
    }

    @Test
    fun sampleRateCalculationMatchesBandwidth() {
        assertEquals(44100, UsbDirectManager.calculateMaxSampleRate(100))
        assertEquals(48000, UsbDirectManager.calculateMaxSampleRate(200))
        assertEquals(96000, UsbDirectManager.calculateMaxSampleRate(500))
        assertEquals(192000, UsbDirectManager.calculateMaxSampleRate(1600))
    }

    @Test
    fun viabilityRequiresPermissionAndUac2() {
        // Without permission -> false
        val (viableNoPerm, reasonNoPerm) = UsbDirectManager.evaluateViability(
            productName = "FiiO KA13",
            uacVersion = 2,
            maxPacketSize = 1024,
            hasPermission = false,
        )
        assertFalse(viableNoPerm)
        assertTrue(reasonNoPerm.contains("requires USB host permission"))

        // With permission but UAC1 -> false
        val (viableUac1, reasonUac1) = UsbDirectManager.evaluateViability(
            productName = "Apple USB-C Adapter",
            uacVersion = 1,
            maxPacketSize = 192,
            hasPermission = true,
        )
        assertFalse(viableUac1)
        assertTrue(reasonUac1.contains("UAC1 device"))

        // With permission and UAC2 -> true
        val (viableUac2, reasonUac2) = UsbDirectManager.evaluateViability(
            productName = "Chord Mojo 2",
            uacVersion = 2,
            maxPacketSize = 1024,
            hasPermission = true,
        )
        assertTrue(viableUac2)
        assertTrue(reasonUac2.contains("ready for direct userspace transfer"))
    }
}
