// @vitest-environment jsdom
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { downloadFile, openExternal } from './native'
import * as server from './server'

describe('downloadFile & openExternal', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('روی وب از location.href استفاده می‌کند', async () => {
    vi.spyOn(server, 'isNativeApp').mockReturnValue(false)
    const originalHref = window.location.href
    try {
      // @ts-expect-error jsdom allows setting href or delete
      delete window.location
      // @ts-expect-error mock location
      window.location = { href: originalHref }

      await downloadFile('https://example.com/test.zip')
      expect(window.location.href).toBe('https://example.com/test.zip')
    } finally {
      // @ts-expect-error restore location
      window.location = { href: originalHref }
    }
  })

  it('در وب openExternal یک تب جدید باز می‌کند', async () => {
    vi.spyOn(server, 'isNativeApp').mockReturnValue(false)
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null)

    const res = await openExternal('https://example.com/file.apk')
    expect(res).toBe(true)
    expect(openSpy).toHaveBeenCalledWith('https://example.com/file.apk', '_blank', 'noopener')
  })
})
