/*
 * Copyright (C) 2024-2026 Kushagra Singh / BitChord Contributors
 * Ported to Music Bazi (app.musicbazi.client.audio.output)
 *
 * Licensed under the GNU General Public License v3.0 (GPL-3.0)
 */

package app.musicbazi.client.audio.output

import android.media.AudioDeviceInfo
import android.media.AudioManager
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Audio output routing manager for Music Bazi.
 */
object AudioRouting {

    enum class Kind { PHONE, WIRED, USB, BLUETOOTH, HDMI, OTHER }

    data class Device(
        val id: Int,
        val type: Int,
        val name: String,
        val kind: Kind,
        val isActive: Boolean = false,
    )

    private val _selectedId = MutableStateFlow<Int?>(null)
    val selectedId: StateFlow<Int?> = _selectedId.asStateFlow()

    fun select(id: Int?) {
        _selectedId.value = id
    }

    fun forget() {
        _selectedId.value = null
    }

    fun infoFor(manager: AudioManager, id: Int?): AudioDeviceInfo? {
        if (id == null) return null
        return runCatching { manager.getDevices(AudioManager.GET_DEVICES_OUTPUTS) }
            .getOrNull()
            ?.firstOrNull { it.id == id }
    }

    fun outputs(manager: AudioManager): List<Device> {
        val infos = runCatching { manager.getDevices(AudioManager.GET_DEVICES_OUTPUTS) }
            .getOrNull()
            ?: return emptyList()
        val active = activeOf(infos, _selectedId.value)
        return infos
            .mapNotNull { info -> kindOf(info.type)?.let { info to it } }
            .map { (info, kind) ->
                Device(
                    id = info.id,
                    type = info.type,
                    name = nameOf(info, kind),
                    kind = kind,
                    isActive = info.id == active?.id,
                )
            }
            .distinctBy { it.name.ifEmpty { it.kind.name } }
    }

    internal fun kindOf(type: Int): Kind? = when (type) {
        AudioDeviceInfo.TYPE_BUILTIN_SPEAKER -> Kind.PHONE
        AudioDeviceInfo.TYPE_WIRED_HEADPHONES,
        AudioDeviceInfo.TYPE_WIRED_HEADSET,
        AudioDeviceInfo.TYPE_LINE_ANALOG,
        AudioDeviceInfo.TYPE_AUX_LINE -> Kind.WIRED
        AudioDeviceInfo.TYPE_USB_DEVICE,
        AudioDeviceInfo.TYPE_USB_HEADSET,
        AudioDeviceInfo.TYPE_USB_ACCESSORY -> Kind.USB
        AudioDeviceInfo.TYPE_BLUETOOTH_A2DP,
        AudioDeviceInfo.TYPE_BLE_HEADSET,
        AudioDeviceInfo.TYPE_BLE_SPEAKER,
        AudioDeviceInfo.TYPE_BLE_BROADCAST,
        AudioDeviceInfo.TYPE_HEARING_AID -> Kind.BLUETOOTH
        AudioDeviceInfo.TYPE_HDMI,
        AudioDeviceInfo.TYPE_HDMI_ARC -> Kind.HDMI
        else -> null
    }

    private fun nameOf(info: AudioDeviceInfo, kind: Kind): String = when (kind) {
        Kind.PHONE, Kind.WIRED -> ""
        else -> info.productName?.toString().orEmpty()
    }

    private fun activeOf(infos: Array<AudioDeviceInfo>, chosenId: Int?): AudioDeviceInfo? {
        if (chosenId != null) {
            val chosen = infos.firstOrNull { it.id == chosenId }
            if (chosen != null) return chosen
        }
        val order = listOf(
            AudioDeviceInfo.TYPE_USB_DEVICE,
            AudioDeviceInfo.TYPE_USB_HEADSET,
            AudioDeviceInfo.TYPE_WIRED_HEADSET,
            AudioDeviceInfo.TYPE_WIRED_HEADPHONES,
            AudioDeviceInfo.TYPE_BLUETOOTH_A2DP,
            AudioDeviceInfo.TYPE_BLE_HEADSET,
            AudioDeviceInfo.TYPE_BUILTIN_SPEAKER,
        )
        for (type in order) {
            val found = infos.firstOrNull { it.type == type }
            if (found != null) return found
        }
        return infos.firstOrNull()
    }
}
