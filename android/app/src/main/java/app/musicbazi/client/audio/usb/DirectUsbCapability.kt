/*
 * Copyright (C) 2026 BitChord Project
 * Ported to Music Bazi (app.musicbazi.client.audio.usb)
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 *
 * Architectural concepts for USB descriptor parsing adapted from:
 * decent-player (https://github.com/Ma145/decent-player)
 * Copyright (c) 2026 Ma145 (MIT License)
 */

package app.musicbazi.client.audio.usb

/**
 * Result of a dynamic runtime probe of USB audio devices connected to the system.
 */
data class DirectUsbProbeResult(
    val isViable: Boolean,
    val productName: String?,
    val vendorId: Int = 0,
    val productId: Int = 0,
    val uacVersion: Int = 0,
    val hasPermission: Boolean = false,
    val endpointOutAddress: Int = -1,
    val maxPacketSize: Int = 0,
    val altSettingCount: Int = 0,
    val isInterfaceClaimed: Boolean = false,
    val supportedBitDepths: List<Int> = emptyList(),
    val maxCalculatedSampleRate: Int = 0,
    val diagnosticReason: String,
) {
    companion object {
        fun notPresent(reason: String = "No USB audio device connected"): DirectUsbProbeResult =
            DirectUsbProbeResult(
                isViable = false,
                productName = null,
                diagnosticReason = reason,
            )
    }
}
