// @vitest-environment jsdom
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { downloadFile, openExternal } from './native'
import * as server from './server'

describe('downloadFile & openExternal', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('روی وب تگ <a> با ویژگی download می‌سازد و کلیک می‌کند', async () => {
    vi.spyOn(server, 'isNativeApp').mockReturnValue(false)
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    await downloadFile('https://example.com/test.zip', 'test.zip')
    expect(clickSpy).toHaveBeenCalled()
  })

  it('در وب openExternal یک تب جدید باز می‌کند', async () => {
    vi.spyOn(server, 'isNativeApp').mockReturnValue(false)
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null)

    const res = await openExternal('https://example.com/file.apk')
    expect(res).toBe(true)
    expect(openSpy).toHaveBeenCalledWith('https://example.com/file.apk', '_blank', 'noopener')
  })
})
