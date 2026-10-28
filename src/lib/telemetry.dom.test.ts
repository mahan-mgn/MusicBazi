// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * گزارشِ خطا.
 *
 * تمرکزِ تست روی همان چیزی است که به‌راحتی می‌شکند: کلیدِ «فرستادن گزارش» در
 * صفحه‌ی تنظیمات باید *واقعاً* ارسال را متوقف کند. اگر فقط در UI اعمال شود،
 * کاربر فکر می‌کند خاموشش کرده و خطاها همچنان می‌روند — که بدترین حالت است.
 *
 * چرا `window.dispatchEvent` و نه صدا زدنِ هندلر: `window` در jsdom بینِ
 * تست‌های یک فایل باقی می‌ماند، پس شنونده‌ی تستِ قبلی هم زنده می‌ماند و
 * ماژولِ تازه‌اش‌نشده‌ی این تست را دور می‌زند. پس شنونده‌ها را خودمان ضبط
 * می‌کنیم و دقیقاً همان تست را صدا می‌زنیم — قرنطینه‌ی کامل.
 */

async function freshTelemetry() {
  vi.resetModules()
  return await import('./telemetry')
}

/** آدرسِ سرور را ست می‌کند تا `send` شرطِ «سروری هست» را رد کند */
function withServer() {
  localStorage.setItem('server:base', 'http://192.168.1.10:8000')
}

/** شنونده‌های ثبت‌شده روی window را ضبط می‌کند */
function captureListeners() {
  const handlers = new Map<string, Array<(e: unknown) => void>>()
  vi.spyOn(window, 'addEventListener').mockImplementation((type, fn) => {
    const list = handlers.get(type) ?? []
    list.push(fn as (e: unknown) => void)
    handlers.set(type, list)
  })
  return {
    fireError(message: string) {
      for (const fn of handlers.get('error') ?? []) fn({ message })
    },
    fireRejection(reason: unknown) {
      for (const fn of handlers.get('unhandledrejection') ?? []) fn({ reason })
    },
  }
}

describe('telemetry', () => {
  let fetchSpy: ReturnType<typeof vi.fn>

  beforeEach(() => {
    localStorage.clear()
    withServer()
    fetchSpy = vi.fn().mockResolvedValue(new Response('{}'))
    vi.stubGlobal('fetch', fetchSpy)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
    localStorage.clear()
  })

  it('با تنظیمِ روشن، خطای نگرفته‌شده را می‌فرستد', async () => {
    const bus = captureListeners()
    const { installErrorReporting } = await freshTelemetry()
    installErrorReporting()
    bus.fireError('boom')

    expect(fetchSpy).toHaveBeenCalledTimes(1)
    expect(String(fetchSpy.mock.calls[0][0])).toContain('/api/client-error')
  })

  it('با تنظیمِ خاموش، حتی یک درخواست هم نمی‌فرستد', async () => {
    const bus = captureListeners()
    const { installErrorReporting, setErrorReportingEnabled } = await freshTelemetry()
    setErrorReportingEnabled(false)
    installErrorReporting()
    bus.fireError('boom')

    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('خاموش‌کردن وسطِ کار، ارسال‌های بعدی را می‌بندد', async () => {
    const bus = captureListeners()
    const { installErrorReporting, setErrorReportingEnabled } = await freshTelemetry()
    installErrorReporting()

    bus.fireError('first')
    expect(fetchSpy).toHaveBeenCalledTimes(1)

    setErrorReportingEnabled(false)
    bus.fireError('second')
    expect(fetchSpy).toHaveBeenCalledTimes(1)
  })

  it('ردِ promise را هم وقتی خاموش است نمی‌فرستد', async () => {
    const bus = captureListeners()
    const { installErrorReporting, setErrorReportingEnabled } = await freshTelemetry()
    setErrorReportingEnabled(false)
    installErrorReporting()
    bus.fireRejection(new Error('nope'))

    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('خطای بدونِ پیام را نمی‌فرستد (شکستِ بارگذاریِ تصویر، کرشِ اپ نیست)', async () => {
    const bus = captureListeners()
    const { installErrorReporting } = await freshTelemetry()
    installErrorReporting()
    bus.fireError('')

    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('بدون آدرسِ سرور چیزی نمی‌فرستد', async () => {
    localStorage.clear()
    const bus = captureListeners()
    const { installErrorReporting } = await freshTelemetry()
    installErrorReporting()
    bus.fireError('boom')

    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('خاموش شروع‌کردن مانعِ روشن‌کردنِ بعدی نمی‌شود', async () => {
    /*
     * شنونده‌ها همیشه ثبت می‌شوند و تصمیم در لحظه‌ی ارسال گرفته می‌شود.
     *
     * اگر `install` وقتِ خاموش‌بودن شنونده ثبت نکند، کاربری که بعداً از
     * تنظیمات روشنش می‌کند تا رفرشِ بعدی هیچ خطایی نمی‌فرستد — یعنی کلید
     * «کار می‌کند ولی نه تا وقتی صفحه را نبندی»، که از نبودنش بدتر است.
     */
    const bus = captureListeners()
    const { installErrorReporting, setErrorReportingEnabled, isErrorReportingEnabled } =
      await freshTelemetry()
    setErrorReportingEnabled(false)
    installErrorReporting()

    bus.fireError('while off')
    expect(fetchSpy).not.toHaveBeenCalled()

    setErrorReportingEnabled(true)
    expect(isErrorReportingEnabled()).toBe(true)
    bus.fireError('while on')
    expect(fetchSpy).toHaveBeenCalledTimes(1)
  })

  it('پیش‌فرض روشن است', async () => {
    const { isErrorReportingEnabled } = await freshTelemetry()
    expect(isErrorReportingEnabled()).toBe(true)
  })
})
