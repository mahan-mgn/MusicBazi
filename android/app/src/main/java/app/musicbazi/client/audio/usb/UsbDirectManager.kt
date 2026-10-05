/*
 * Copyright (C) 2024-2026 Kushagra Singh / BitChord Contributors
 * Ported to Music Bazi (app.musicbazi.client.audio.usb)
 *
 * Licensed under the GNU General Public License v3.0 (GPL-3.0)
 *
 * Architectural concepts for USB descriptor parsing adapted from:
 * decent-player (https://github.com/Ma145/decent-player)
 * Copyright (c) 2026 Ma145 (MIT License)
 */

package app.musicbazi.client.audio.usb

import android.content.Context
import android.hardware.usb.UsbConstants
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbEndpoint
import android.hardware.usb.UsbInterface
import android.hardware.usb.UsbManager
import android.util.Log

/**
 * Probes and audits USB Audio Class (UAC1 / UAC2) hardware attached to the device.
 */
object UsbDirectManager {

    private const val TAG = "UsbDirectManager"

    private const val UAC_VERSION_1_PROTOCOL = 0x00
    private const val UAC_VERSION_2_PROTOCOL = 0x20
    private const val UAC_VERSION_3_PROTOCOL = 0x30

    fun probe(context: Context): DirectUsbProbeResult {
        val usbManager = context.getSystemService(Context.USB_SERVICE) as? UsbManager
            ?: return DirectUsbProbeResult.notPresent("UsbManager system service unavailable")

        val deviceList = try {
            usbManager.deviceList
        } catch (e: Exception) {
            Log.w(TAG, "Failed to read USB device list", e)
            return DirectUsbProbeResult.notPresent("Permission or OS error reading USB device list: ${e.message}")
        }

        if (deviceList.isEmpty()) {
            return DirectUsbProbeResult.notPresent("No USB devices connected")
        }

        for (device in deviceList.values) {
            val audioInfo = auditDevice(device, usbManager)
            if (audioInfo != null) {
                return audioInfo
            }
        }

        return DirectUsbProbeResult.notPresent("No USB Audio Class device found among ${deviceList.size} connected device(s)")
    }

    private fun auditDevice(device: UsbDevice, usbManager: UsbManager): DirectUsbProbeResult? {
        var hasAudioInterface = false
        var streamingInterface: UsbInterface? = null
        var uacVersion = 0
        var altSettingCount = 0
        var isoOutEndpoint: UsbEndpoint? = null

        for (i in 0 until device.interfaceCount) {
            val iface = device.getInterface(i)
            if (iface.interfaceClass == UsbConstants.USB_CLASS_AUDIO) {
                hasAudioInterface = true

                if (iface.interfaceSubclass == 1) {
                    when (iface.interfaceProtocol) {
                        UAC_VERSION_2_PROTOCOL -> uacVersion = maxOf(uacVersion, 2)
                        UAC_VERSION_3_PROTOCOL -> uacVersion = maxOf(uacVersion, 3)
                        UAC_VERSION_1_PROTOCOL -> if (uacVersion == 0) uacVersion = 1
                    }
                } else if (iface.interfaceSubclass == 2) {
                    altSettingCount++
                    when (iface.interfaceProtocol) {
                        UAC_VERSION_2_PROTOCOL -> uacVersion = maxOf(uacVersion, 2)
                        UAC_VERSION_3_PROTOCOL -> uacVersion = maxOf(uacVersion, 3)
                        UAC_VERSION_1_PROTOCOL -> if (uacVersion == 0) uacVersion = 1
                    }

                    for (e in 0 until iface.endpointCount) {
                        val ep = iface.getEndpoint(e)
                        if (ep.type == UsbConstants.USB_ENDPOINT_XFER_ISOC &&
                            ep.direction == UsbConstants.USB_DIR_OUT
                        ) {
                            if (isoOutEndpoint == null || ep.maxPacketSize > isoOutEndpoint.maxPacketSize) {
                                isoOutEndpoint = ep
                                streamingInterface = iface
                            }
                        }
                    }
                }
            }
        }

        if (!hasAudioInterface) return null

        val productName = device.productName ?: "USB Audio Device"
        val vendorId = device.vendorId
        val productId = device.productId

        if (isoOutEndpoint == null) {
            return DirectUsbProbeResult(
                isViable = false,
                productName = productName,
                vendorId = vendorId,
                productId = productId,
                uacVersion = uacVersion,
                hasPermission = usbManager.hasPermission(device),
                diagnosticReason = "AudioStreaming interface found, but no isochronous OUT endpoint is exposed",
            )
        }

        val maxPacketSize = isoOutEndpoint.maxPacketSize
        val hasPermission = usbManager.hasPermission(device)

        val supportedDepths = calculateSupportedBitDepths(maxPacketSize)
        val maxCalculatedSr = calculateMaxSampleRate(maxPacketSize)
        val (isViable, diagnosticReason) = evaluateViability(productName, uacVersion, maxPacketSize, hasPermission)

        return DirectUsbProbeResult(
            isViable = isViable,
            productName = productName,
            vendorId = vendorId,
            productId = productId,
            uacVersion = uacVersion,
            hasPermission = hasPermission,
            endpointOutAddress = isoOutEndpoint.address,
            maxPacketSize = maxPacketSize,
            altSettingCount = altSettingCount,
            isInterfaceClaimed = false,
            supportedBitDepths = supportedDepths,
            maxCalculatedSampleRate = maxCalculatedSr,
            diagnosticReason = diagnosticReason,
        )
    }

    internal fun calculateSupportedBitDepths(maxPacketSize: Int): List<Int> {
        val depths = mutableListOf<Int>()
        if (maxPacketSize >= 176) depths.add(16)
        if (maxPacketSize >= 288) depths.add(24)
        if (maxPacketSize >= 384) depths.add(32)
        return depths
    }

    internal fun calculateMaxSampleRate(maxPacketSize: Int): Int = when {
        maxPacketSize >= 1536 -> 192000
        maxPacketSize >= 768 -> 96000
        maxPacketSize >= 384 -> 96000
        maxPacketSize >= 192 -> 48000
        else -> 44100
    }

    internal fun evaluateViability(
        productName: String,
        uacVersion: Int,
        maxPacketSize: Int,
        hasPermission: Boolean,
    ): Pair<Boolean, String> {
        val isViable = hasPermission && uacVersion >= 2
        val reason = buildString {
            if (!hasPermission) {
                append("Direct USB requires USB host permission for '$productName' (managed by Android ALSA driver)")
            } else if (uacVersion < 2) {
                append("UAC1 device (max packet $maxPacketSize bytes) currently owned by kernel snd-usb-audio driver")
            } else {
                append("UAC2 device ready for direct userspace transfer (max packet $maxPacketSize bytes)")
            }
        }
        return Pair(isViable, reason)
    }
}
