/*
 * مسیریابی صوتی وب و پشتیبانی از خروجی مستقیم سخت‌افزار (DAC / Audio Output Devices)
 *
 * استفاده از API مدرن `setSinkId` برای هدایت مستقیم جریان صوتی به DACهای خارجی،
 * کارت‌های صدای استودیویی و هدفون‌های باکیفیت بدون افت و تأخیر میکسر عمومی.
 */

export interface AudioDevice {
  deviceId: string
  label: string
  isDefault: boolean
  isUsb: boolean
}

const STORAGE_KEY = 'mb_audio_sink_id'

export function isSetSinkIdSupported(): boolean {
  if (typeof window === 'undefined') return false
  return (
    'setSinkId' in HTMLMediaElement.prototype ||
    ('AudioContext' in window && 'setSinkId' in AudioContext.prototype)
  )
}

export async function getAudioOutputDevices(): Promise<AudioDevice[]> {
  if (typeof navigator === 'undefined' || !navigator.mediaDevices?.enumerateDevices) {
    return []
  }
  try {
    const devices = await navigator.mediaDevices.enumerateDevices()
    const audioOutputs = devices.filter((d) => d.kind === 'audiooutput')

    return audioOutputs.map((d, index) => {
      const isDefault = d.deviceId === 'default' || (!d.deviceId && index === 0)
      const label = d.label || (isDefault ? 'بلندگو / خروجی پیش‌فرض سیستم' : `خروجی صوتی ${index + 1}`)
      const isUsb = /usb|dac|fiio|schiit|topping|audioengine|chord|dragonfly/i.test(label)

      return {
        deviceId: d.deviceId,
        label,
        isDefault,
        isUsb,
      }
    })
  } catch (err) {
    console.warn('[AudioRouting] Failed to enumerate audio devices:', err)
    return []
  }
}

export function getSavedSinkId(): string {
  if (typeof localStorage === 'undefined') return ''
  return localStorage.getItem(STORAGE_KEY) || ''
}

export function saveSinkId(sinkId: string): void {
  if (typeof localStorage === 'undefined') return
  if (sinkId) {
    localStorage.setItem(STORAGE_KEY, sinkId)
  } else {
    localStorage.removeItem(STORAGE_KEY)
  }
}

export async function routeAudioElements(
  elements: HTMLMediaElement[],
  sinkId: string,
): Promise<boolean> {
  let allSuccess = true
  for (const el of elements) {
    if ('setSinkId' in el && typeof (el as any).setSinkId === 'function') {
      try {
        await (el as any).setSinkId(sinkId)
      } catch (err) {
        console.warn('[AudioRouting] Failed to setSinkId on element:', err)
        allSuccess = false
      }
    }
  }
  return allSuccess
}

export async function routeAudioContext(
  ctx: AudioContext | null,
  sinkId: string,
): Promise<boolean> {
  if (!ctx) return false
  if ('setSinkId' in ctx && typeof (ctx as any).setSinkId === 'function') {
    try {
      await (ctx as any).setSinkId(sinkId)
      return true
    } catch (err) {
      console.warn('[AudioRouting] Failed to setSinkId on AudioContext:', err)
      return false
    }
  }
  return false
}
