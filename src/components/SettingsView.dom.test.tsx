// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SettingsView from './SettingsView'
import { useI18n } from '../lib/i18n'
import { useDownloads } from '../store/downloads'
import { useOffline } from '../store/offline'
import { useRecent } from '../store/recent'
import { useSearchHistory } from '../store/searchHistory'
import { useSettings } from '../store/settings'

// پرچمِ ری‌اکت برای اینکه `act` بیرونِ درختِ تست هم کار کند. با cast نوشته
// می‌شود نه انتسابِ مستقیم: تایپِ `globalThis` ایندکس‌پذیر نیست و انتسابِ
// خام در `tsc -b` رد می‌شود (`noEmit` ولی سخت‌گیر)
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

/**
 * صفحه‌ی تنظیمات.
 *
 * بیشترِ ادعاها روی *رفتار* است نه مارک‌آپ: هر کنترل باید همان استوری را
 * عوض کند که مصرف‌کننده‌ی واقعی‌اش می‌خواند. تستِ «دکمه رندر شد» این‌جا
 * بی‌ارزش است چون تخته‌سنگ‌های کلیدهای i18n از قبل وجود داشتند.
 *
 * `fetch` کور می‌شود: این صفحه وضعیتِ سرور را می‌خواند و در تست هیچ سروری
 * نیست؛ بدونِ آن هر رندر یک درخواستِ ناموفق و یک unhandled rejection می‌سازد.
 */

/** چرخ‌دنده‌ی تنظیمات روی دسکتاپ دیده می‌شود؛ `isNativeApp` همیشه false است */
vi.mock('../lib/server', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/server')>()
  return { ...actual, isNativeApp: () => false, serverBase: () => '' }
})

function render(props: Partial<{ onSetup: () => void; onServer: () => void }> = {}) {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  act(() => {
    root.render(<SettingsView onSetup={props.onSetup ?? vi.fn()} onServer={props.onServer ?? vi.fn()} />)
  })
  return { container, root }
}

/** اولین دکمه‌ای که متنش دقیقاً برابر است */
function button(container: HTMLElement, text: string): HTMLButtonElement {
  const found = [...container.querySelectorAll('button')].find(
    (b) => b.textContent?.trim() === text,
  )
  if (!found) throw new Error(`no button labelled "${text}"`)
  return found as HTMLButtonElement
}

/** دکمه‌ای که برچسبِ دسترس‌پذیری‌اش برابر است */
function labelled(container: HTMLElement, label: string): HTMLButtonElement {
  const found = container.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`)
  if (!found) throw new Error(`no button labelled "${label}"`)
  return found
}

/** ردیفی که متنش شاملِ این برچسب است */
function row(container: HTMLElement, label: string): HTMLElement {
  const p = [...container.querySelectorAll('p')].find((el) => el.textContent?.trim() === label)
  const found = p?.closest('div.flex') as HTMLElement | null
  if (!found) throw new Error(`no row labelled "${label}"`)
  return found
}

describe('SettingsView', () => {
  let container: HTMLDivElement
  let root: Root

  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 })),
    )
    localStorage.clear()
    useI18n.getState().setLang('fa')
    useSettings.setState({
      theme: 'dark',
      quality: '320',
      liquidGlass: true,
      reduceMotion: false,
      normalize: true,
      crossfade: 0,
      eqBands: [0, 0, 0, 0, 0, 0, 0],
      tone: { x: 0, y: 0 },
      balance: 0,
      eqEnabled: false,
      spatialAudio: false,
      nativeAudioEngine: 'auto',
      boost: 0,
      maxConcurrentDownloads: 3,
      errorReporting: true,
    })
    useSearchHistory.setState({ items: [] })
    useRecent.setState({ items: [] })
    useOffline.setState({ items: {}, busy: [] })
    useDownloads.setState({ jobs: [], batches: [] })
  })

  /**
   * رندر با داده‌های از پیش کاشته‌شده.
   *
   * ردیف‌های پاک‌کردن وقتی فهرست خالی است غیرفعال‌اند، پس کاشتنِ داده *بعد*
   * از رندر یعنی کلیک روی دکمه‌ی `disabled` که React هم آن را رد می‌کند —
   * تست سبز می‌شد ولی هیچ رفتاری را نمی‌سنجید.
   */
  function mount(seed: { history?: string[]; recent?: never[]; pins?: Record<string, never> } = {}) {
    if (seed.history) useSearchHistory.setState({ items: seed.history })
    if (seed.recent) useRecent.setState({ items: seed.recent })
    if (seed.pins) useOffline.setState({ items: seed.pins, busy: [] })
    const rendered = render()
    container = rendered.container
    root = rendered.root
    // برچسب‌های انگلیسی برای ادعاهای قابل‌خواندن
    act(() => useI18n.getState().setLang('en'))
  }

  afterEach(() => {
    act(() => root.unmount())
    container.remove()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
    localStorage.clear()
    useI18n.getState().setLang('fa')
  })

  it('همه‌ی بخش‌ها را نشان می‌دهد', () => {
    mount()
    const headings = [...container.querySelectorAll('h2')].map((h) => h.textContent)
    for (const expected of [
      'Appearance',
      'Playback & audio',
      'Downloads & offline',
      'Lyrics',
      'Data & privacy',
      'Server & setup',
      'About',
    ]) {
      expect(headings).toContain(expected)
    }
  })

  it('عنوان و زیرعنوان صفحه را دارد', () => {
    mount()
    expect(container.querySelector('h1')?.textContent).toBe('Settings')
  })

  it('تغییرِ تم را روی ریشه اعمال می‌کند و ذخیره می‌کند', () => {
    mount()
    act(() => button(container, 'Light').click())
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(localStorage.getItem('theme')).toBe('light')
    expect(useSettings.getState().theme).toBe('light')
  })

  it('تمِ خودکار را به یک تمِ واقعی حل می‌کند', () => {
    mount()
    act(() => button(container, 'Auto').click())
    // خودِ انتخاب `system` می‌ماند، ولی چیزی که اعمال می‌شود یکی از دو تم است
    expect(useSettings.getState().theme).toBe('system')
    expect(['dark', 'light']).toContain(document.documentElement.dataset.theme)
  })

  it('زبان را عوض می‌کند و جهتِ صفحه را می‌چرخاند', () => {
    mount()
    expect(document.documentElement.dir).toBe('ltr')
    act(() => button(container, 'فارسی').click())
    expect(document.documentElement.dir).toBe('rtl')
    expect(localStorage.getItem('lang')).toBe('fa')
    act(() => button(container, 'English').click())
    expect(document.documentElement.dir).toBe('ltr')
  })

  it('شیشه‌ی مایع را روی data-attribute می‌نشاند', () => {
    mount()
    const toggle = [...container.querySelectorAll('input[type=checkbox]')].find((i) =>
      i.closest('label')?.textContent?.includes('Liquid Glass'),
    ) as HTMLInputElement
    act(() => toggle.click())
    expect(document.documentElement.dataset.liquidGlass).toBe('false')
    expect(localStorage.getItem('ui:liquidGlass')).toBe('0')
  })

  it('کاهش انیمیشن را به مسیرِ واقعیِ انیمیشن وصل می‌کند، نه فقط UI', async () => {
    mount()
    const motion = await import('../lib/motion')
    expect(motion.reducedMotion()).toBe(false)
    const toggle = [...container.querySelectorAll('input[type=checkbox]')].find((i) =>
      i.closest('label')?.textContent?.includes('Reduce motion'),
    ) as HTMLInputElement
    act(() => toggle.click())
    expect(motion.reducedMotion()).toBe(true)
  })

  it('اکولایزر را روشن و خاموش می‌کند', () => {
    mount()
    const toggle = [...container.querySelectorAll('input[type=checkbox]')].find((i) =>
      i.closest('label')?.textContent?.includes('Equalizer'),
    ) as HTMLInputElement
    expect(toggle).toBeDefined()
    expect(toggle.checked).toBe(false)
    act(() => toggle.click())
    expect(useSettings.getState().eqEnabled).toBe(true)
    expect(localStorage.getItem('audio:eqEnabled')).toBe('1')
  })

  it('سقفِ دانلود را با − و + تغییر می‌دهد و در بازه نگه می‌دارد', () => {
    mount()
    const plus = labelled(container, 'Concurrent downloads +')
    const minus = labelled(container, 'Concurrent downloads −')

    act(() => plus.click())
    expect(useSettings.getState().maxConcurrentDownloads).toBe(4)
    expect(localStorage.getItem('downloads:maxConcurrent')).toBe('4')

    act(() => {
      minus.click()
      minus.click()
    })
    expect(useSettings.getState().maxConcurrentDownloads).toBe(2)
  })

  it('بالا بردنِ سقف، صفِ دانلود را همان لحظه جلو می‌برد', () => {
    mount()
    // اگر تنظیم فقط نوشته شود و صف بی‌خبر بماند، کاربر فکر می‌کند کار نکرده
    const pump = vi.spyOn(useDownloads.getState(), 'pump')
    act(() => labelled(container, 'Concurrent downloads +').click())
    expect(pump).toHaveBeenCalled()
  })

  it('پایین آوردنِ سقف صف را جلو نمی‌برد (دانلودِ نیمه‌کاره کشته نمی‌شود)', () => {
    mount()
    act(() => labelled(container, 'Concurrent downloads +').click())
    const pump = vi.spyOn(useDownloads.getState(), 'pump')
    act(() => labelled(container, 'Concurrent downloads −').click())
    expect(pump).not.toHaveBeenCalled()
  })

  it('خاموش‌کردنِ گزارشِ خطا را به مسیرِ ارسال وصل می‌کند', async () => {
    mount()
    const telemetry = await import('../lib/telemetry')
    expect(telemetry.isErrorReportingEnabled()).toBe(true)
    const toggle = [...container.querySelectorAll('input[type=checkbox]')].find((i) =>
      i.closest('label')?.textContent?.includes('crash reports'),
    ) as HTMLInputElement
    act(() => toggle.click())
    expect(telemetry.isErrorReportingEnabled()).toBe(false)
  })

  describe('پاک‌کردنِ داده‌ها', () => {
    it('تاریخچه‌ی جستجو را با تأییدِ دو مرحله‌ای پاک می‌کند', () => {
      mount({ history: ['alpha', 'beta'] })
      const clearAll = button(row(container, 'Search history'), 'Clear all')

      act(() => clearAll.click())
      // ضربه‌ی اول فقط می‌پرسد و چیزی را نمی‌بَرد
      expect(useSearchHistory.getState().items).toHaveLength(2)

      const confirm = button(row(container, 'Search history'), 'Clear')
      act(() => confirm.click())
      expect(useSearchHistory.getState().items).toHaveLength(0)
    })

    it('بدونِ تأیید چیزی پاک نمی‌کند', () => {
      mount({ history: ['alpha'] })
      act(() => button(row(container, 'Search history'), 'Clear all').click())
      expect(useSearchHistory.getState().items).toEqual(['alpha'])
    })

    it('«ادامه بده» را پاک می‌کند', () => {
      mount({
        recent: [
          {
            kind: 'track',
            key: 'track:1',
            title: 'A',
            subtitle: 'B',
            artworkUrl: null,
            seed: '1',
            at: Date.now(),
            item: { id: '1', track: { id: '1', title: 'A', artist: 'B' }, streamUrl: '/x' },
          } as never,
        ],
      })
      act(() => button(row(container, 'Continue listening'), 'Clear all').click())
      act(() => button(row(container, 'Continue listening'), 'Clear').click())
      expect(useRecent.getState().items).toHaveLength(0)
    })

    it('نقطه‌ی ادامه‌ی پخش را بدونِ تأیید پاک می‌کند (بی‌خطر است)', () => {
      mount()
      localStorage.setItem('player:resume', '{"position":42}')
      act(() => button(row(container, 'Resume position'), 'Clear').click())
      expect(localStorage.getItem('player:resume')).toBeNull()
    })

    it('بازگشت به پیش‌فرض فقط کلیدهای تنظیم را می‌برد، نه داده‌های کاربر', () => {
      mount()
      /*
       * مهم‌ترین ادعای این بخش: «بازگرداندنِ تنظیمات» نباید تاریخچه و
       * کتابخانه را با خودش ببرد. آن‌ها محتوایند نه تنظیم.
       */
      localStorage.setItem('quality', 'flac')
      localStorage.setItem('search:history', '["kept"]')
      localStorage.setItem('offline:pinned', '{"kept":1}')

      const reload = vi.fn()
      // jsdom اجازه‌ی ناوبری نمی‌دهد؛ متد را برای همین تست جایگزین می‌کنیم
      const original = window.location.reload
      Object.defineProperty(window, 'location', {
        configurable: true,
        value: { ...window.location, reload },
      })

      act(() => button(row(container, 'Reset settings to defaults'), 'Reset').click())
      act(() => button(row(container, 'Reset settings to defaults'), 'Sure? All settings will be cleared').click())

      expect(localStorage.getItem('quality')).toBeNull()
      expect(localStorage.getItem('search:history')).toBe('["kept"]')
      expect(localStorage.getItem('offline:pinned')).toBe('{"kept":1}')

      Object.defineProperty(window, 'location', {
        configurable: true,
        value: { ...window.location, reload: original ?? (() => {}) },
      })
    })

    it('پاک‌کردنِ سنجاق‌ها از مسیرِ unpin رد می‌شود (متادیتا و کش با هم)', async () => {
      // کاشتنِ سنجاق‌ها *قبل* از رندر تا دکمه در حالتِ فعال باشد
      const pins = {
        a: { jobId: 'a', streamUrl: '/x' },
        b: { jobId: 'b', streamUrl: '/y' },
      } as never
      // خودِ کنشِ استور دور زده می‌شود: واسطِ واقعی به Cache Storage نیاز دارد
      // و آن‌چه این‌جا مهم است *این است که کنترل از همان مسیر رد شود*
      const unpin = vi.fn().mockResolvedValue(undefined)
      useOffline.setState({ items: pins, busy: [], unpin })
      mount()

      act(() => button(row(container, 'Pinned for offline'), 'Remove all').click())
      await act(async () => {
        await Promise.resolve()
      })
      expect(unpin).toHaveBeenCalledTimes(2)
    })
  })

  it('تنظیم‌های فقط‌اندروید در مرورگر رندر نمی‌شوند', () => {
    mount()
    const text = container.textContent ?? ''
    expect(text).not.toContain('Native audio engine')
    expect(text).not.toContain('Server address')
  })

  it('وقتی سروری نیست، «در حال بررسی…» ابدی نشان نمی‌دهد', () => {
    mount()
    // حالتِ demo/mock: سروری وجود ندارد، پس وضعیت هم نمایش داده نمی‌شود —
    // نه اسپینرِ بی‌پایان
    expect(container.textContent).not.toContain('Checking…')
  })

  it('در حالتِ demo، متن را «آماده نیست» اعلام نمی‌کند', () => {
    /*
     * همان تله‌ی بخشِ سرور، این‌بار برای متن: بدونِ سرور، `health` هیچ‌وقت
     * نمی‌آید و مقدارش `undefined` می‌ماند. اگر مستقیم به `ready()` داده شود،
     * صفحه می‌گوید «متن: آماده نیست» — هشدارِ دروغ درباره‌ی قابلیتی که
     * اصلاً سروری برای فراهم‌کردنش وجود ندارد.
     */
    mount()
    const lyrics = [...container.querySelectorAll('section')].find((s) =>
      s.querySelector('h2')?.textContent?.includes('Lyrics'),
    )
    expect(lyrics?.textContent).not.toContain('Not available')
  })

  it('در حالتِ انگلیسی هیچ کاراکترِ فارسی چاپ نمی‌کند', () => {
    mount()
    // همان گاردی که ArtistView دارد: نبودِ ترجمه‌ی یک کلید نباید بی‌صدا
    // متنِ فارسی را در رابطِ انگلیسی بچپاند
    const text = container.textContent ?? ''
    // «فارسی» تنها استثناست و *باید* باشد: نامِ خودِ زبان در فهرستِ انتخابِ
    // زبان، عمداً به خطِ خودش نوشته می‌شود تا کسی که رابط را نمی‌فهمد هم
    // زبانش را پیدا کند. حذفش یعنی کسی که انگلیسی نمی‌داند گم می‌شود.
    const withoutEndonym = text.replace(/فارسی/g, '')
    expect(withoutEndonym).not.toMatch(/[؀-ۿ]/)
  })
})
