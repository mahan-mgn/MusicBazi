// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * استورِ تنظیمات.
 *
 * این استور تا حالا تست نداشت و بیشترِ تصمیم‌هایش «حالتِ اولیه از حافظه‌ی
 * محلی» است — دقیقاً جایی که یک کلیدِ خراب یا مقدارِ خارج از بازه بی‌صدا به
 * رفتارِ غلط تبدیل می‌شود. هر تست، ماژول را تازه import می‌کند تا مقدارهای
 * سطحِ ماژول دوباره از صفر خوانده شوند.
 */

/** `matchMedia` در jsdom نیست؛ اینجا فقط برای تمِ `system` لازم است */
function stubMatchMedia(light: boolean, listeners: Array<() => void> = []) {
  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      matches: query.includes('prefers-color-scheme') ? light : false,
      media: query,
      addEventListener: (_: string, cb: () => void) => listeners.push(cb),
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      onchange: null,
      dispatchEvent: () => false,
    })),
  )
  return listeners
}

async function freshStore() {
  vi.resetModules()
  return await import('../store/settings')
}

describe('settings store', () => {
  beforeEach(() => {
    localStorage.clear()
    stubMatchMedia(false)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
    localStorage.clear()
  })

  it('با حافظه‌ی خالی، پیش‌فرض‌های مستندشده را می‌دهد', async () => {
    const { useSettings } = await freshStore()
    const s = useSettings.getState()
    expect(s.theme).toBe('dark')
    expect(s.quality).toBe('320')
    expect(s.liquidGlass).toBe(true)
    expect(s.reduceMotion).toBe(false)
    expect(s.normalize).toBe(true)
    expect(s.crossfade).toBe(0)
    expect(s.eqBands).toEqual([0, 0, 0, 0, 0, 0, 0])
    expect(s.eqEnabled).toBe(false)
    expect(s.spatialAudio).toBe(false)
    expect(s.nativeAudioEngine).toBe('auto')
    expect(s.boost).toBe(0)
    expect(s.maxConcurrentDownloads).toBe(3)
    expect(s.errorReporting).toBe(true)
  })

  it('عددِ خراب در حافظه را به پیش‌فرض برمی‌گرداند، نه صفر', async () => {
    // `Number('')` صفر است؛ اگر خواننده محافظت نکند، یک کلیدِ خالی سقفِ
    // دانلود را بی‌صدا صفر می‌کند و هیچ دانلودی شروع نمی‌شود
    localStorage.setItem('downloads:maxConcurrent', '')
    const { useSettings } = await freshStore()
    expect(useSettings.getState().maxConcurrentDownloads).toBe(3)
  })

  it('مقدارِ خارج از بازه‌ی سقفِ دانلود را به پیش‌فرض می‌برد', async () => {
    localStorage.setItem('downloads:maxConcurrent', '999')
    const { useSettings } = await freshStore()
    expect(useSettings.getState().maxConcurrentDownloads).toBe(3)
  })

  it('setMaxConcurrentDownloads را در همان بازه می‌بندد و ذخیره می‌کند', async () => {
    const { useSettings, MIN_CONCURRENT_DOWNLOADS, MAX_CONCURRENT_DOWNLOADS } = await freshStore()
    useSettings.getState().setMaxConcurrentDownloads(999)
    expect(useSettings.getState().maxConcurrentDownloads).toBe(MAX_CONCURRENT_DOWNLOADS)
    expect(localStorage.getItem('downloads:maxConcurrent')).toBe(String(MAX_CONCURRENT_DOWNLOADS))

    useSettings.getState().setMaxConcurrentDownloads(-5)
    expect(useSettings.getState().maxConcurrentDownloads).toBe(MIN_CONCURRENT_DOWNLOADS)
  })

  it('تم را ذخیره می‌کند و روی ریشه اعمالش می‌کند', async () => {
    const { useSettings } = await freshStore()
    useSettings.getState().setTheme('light')
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(localStorage.getItem('theme')).toBe('light')
  })

  it('تمِ system را می‌پذیرد ولی مقدارِ حل‌شده را روی ریشه می‌گذارد', async () => {
    stubMatchMedia(true) // سیستم روشن است
    const { useSettings } = await freshStore()
    useSettings.getState().setTheme('system')
    // خودِ انتخاب `system` می‌ماند تا اگر کاربر سیستمش را عوض کرد، اپ هم عوض شود
    expect(localStorage.getItem('theme')).toBe('system')
    // ولی چیزی که *اعمال* می‌شود باید یکی از دو تمِ واقعی باشد
    expect(document.documentElement.dataset.theme).toBe('light')
  })

  it('toggleTheme از حالتِ system به یک تمِ واقعی می‌رود (دکمه‌ی هدر بی‌اثر نماند)', async () => {
    stubMatchMedia(false) // سیستم تاریک
    const { useSettings } = await freshStore()
    useSettings.getState().setTheme('system')
    useSettings.getState().toggleTheme()
    expect(useSettings.getState().theme).toBe('light')
    expect(document.documentElement.dataset.theme).toBe('light')
  })

  it('setReduceMotion را به مسیرِ انیمیشن‌ها وصل می‌کند، نه فقط UI', async () => {
    /*
     * مهم‌ترین ادعا: کلید باید رفتار را عوض کند. اگر فقط مقدارِ استور عوض شود
     * و `motion` بی‌خبر بماند، یک دکمه‌ی بی‌اثر ساخته‌ایم.
     */
    stubMatchMedia(false) // سیستم می‌گوید «حرکت کم نکن»
    const { useSettings } = await freshStore()
    const motion = await import('../lib/motion')

    expect(motion.reducedMotion()).toBe(false)
    useSettings.getState().setReduceMotion(true)
    expect(motion.reducedMotion()).toBe(true)
    expect(localStorage.getItem('ui:reduceMotion')).toBe('1')

    // خاموش‌کردن باید *به سیستم برگردد*، نه به «حرکت زیاد»
    useSettings.getState().setReduceMotion(false)
    expect(motion.reducedMotion()).toBe(false)
  })

  it('setErrorReporting را به مسیرِ ارسال وصل می‌کند', async () => {
    const { useSettings } = await freshStore()
    const telemetry = await import('../lib/telemetry')

    expect(telemetry.isErrorReportingEnabled()).toBe(true)
    useSettings.getState().setErrorReporting(false)
    expect(telemetry.isErrorReportingEnabled()).toBe(false)
    expect(localStorage.getItem('privacy:errorReports')).toBe('0')
  })

  it('خاموشیِ گزارش را از اجرای قبلی به‌خاطر می‌سپارد', async () => {
    localStorage.setItem('privacy:errorReports', '0')
    await freshStore()
    const telemetry = await import('../lib/telemetry')
    expect(telemetry.isErrorReportingEnabled()).toBe(false)
  })

  it('شیشه‌ی مایع را روی data-attribute می‌نشاند', async () => {
    const { useSettings } = await freshStore()
    useSettings.getState().setLiquidGlass(false)
    expect(document.documentElement.dataset.liquidGlass).toBe('false')
    expect(localStorage.getItem('ui:liquidGlass')).toBe('0')
  })

  it('کراس‌فید را در بازه می‌بندد و موتور را خبر می‌کند', async () => {
    const { useSettings, MAX_CROSSFADE } = await freshStore()
    const engine = await import('../lib/audioEngine')
    const spy = vi.spyOn(engine.engine, 'setCrossfade')

    useSettings.getState().setCrossfade(999)
    expect(useSettings.getState().crossfade).toBe(MAX_CROSSFADE)
    expect(spy).toHaveBeenCalledWith(MAX_CROSSFADE)

    useSettings.getState().setCrossfade(-3)
    expect(useSettings.getState().crossfade).toBe(0)
  })

  it('setEqEnabled را در حافظه ذخیره و وضعیت را به‌روز می‌کند', async () => {
    const { useSettings } = await freshStore()
    const engine = await import('../lib/audioEngine')
    const spy = vi.spyOn(engine.engine, 'setEq7')

    useSettings.getState().setEqEnabled(true)
    expect(useSettings.getState().eqEnabled).toBe(true)
    expect(localStorage.getItem('audio:eqEnabled')).toBe('1')
    // setEq7(params، enabled) — پارامتر اول منحنی، دومی کلیدِ فعال‌بودن
    expect(spy).toHaveBeenLastCalledWith(expect.objectContaining({ bandsDb: expect.anything() }), true)

    useSettings.getState().setEqEnabled(false)
    expect(useSettings.getState().eqEnabled).toBe(false)
    expect(localStorage.getItem('audio:eqEnabled')).toBe('0')
    expect(spy).toHaveBeenLastCalledWith(expect.objectContaining({ bandsDb: expect.anything() }), false)
  })

  it('اگر از قبل پریست غیر off در حافظه باشد، به باندهای ۷تایی مهاجرت و eqEnabled خودکار true می‌شود', async () => {
    localStorage.setItem('audio:eq', 'bass')
    const { useSettings } = await freshStore()
    // نگاشتِ نزدیک‌ترین باند: ۶/۳/۰/−۱/−۱ → باندهای ۶۰/۱۵۰/۱۰۰۰/۲۵۰۰/۱۴۰۰۰
    expect(useSettings.getState().eqBands).toEqual([6, 3, 0, 0, -1, 0, -1])
    expect(useSettings.getState().eqEnabled).toBe(true)
    expect(localStorage.getItem('audio:eq')).toBeNull()
    expect(JSON.parse(localStorage.getItem('audio:eqBands') ?? '[]')).toEqual([6, 3, 0, 0, -1, 0, -1])
  })

  it('ترجیحِ زبان را دست نمی‌زند (زبان مالِ i18n است، نه این استور)', async () => {
    const { useSettings } = await freshStore()
    // فقط برای اینکه کسی اشتباهاً کلیدِ lang را این‌جا اضافه نکند
    expect('setLang' in useSettings.getState()).toBe(false)
  })
})
