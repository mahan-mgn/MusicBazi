// @vitest-environment jsdom
import { describe, expect, it, beforeEach } from 'vitest'
import {
  getSavedSinkId,
  saveSinkId,
  isSetSinkIdSupported,
} from './AudioRouting'

describe('AudioRouting (DAC and Device Selection)', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('getSavedSinkId & saveSinkId: ذخیره و بازیابی شناسه دستگاه خروجی', () => {
    expect(getSavedSinkId()).toBe('')
    saveSinkId('usb-dac-device-123')
    expect(getSavedSinkId()).toBe('usb-dac-device-123')
    saveSinkId('')
    expect(getSavedSinkId()).toBe('')
  })

  it('isSetSinkIdSupported: عدم پرتاب خطا در محیط تست', () => {
    expect(typeof isSetSinkIdSupported()).toBe('boolean')
  })
})
