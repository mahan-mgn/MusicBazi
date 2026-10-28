// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AlbumDetail, ArtistDetail } from './lib/types'

// @ts-expect-error React act environment flag
globalThis.IS_REACT_ACT_ENVIRONMENT = true

/*
 * شکل‌های محیطیِ jsdom که App روی مسیرِ رندر لازم دارد. بدونِ این‌ها خطا از
 * عمقِ یک کامپوننتِ بی‌ربط می‌آید و تشخیصش دشوار است.
 */
window.matchMedia = ((query: string) => ({
  matches: false,
  media: query,
  onchange: null,
  addEventListener: () => {},
  removeEventListener: () => {},
  addListener: () => {},
  removeListener: () => {},
  dispatchEvent: () => false,
})) as unknown as typeof window.matchMedia

class MockObserver {
  observe = vi.fn()
  unobserve = vi.fn()
  disconnect = vi.fn()
}
window.IntersectionObserver = MockObserver as unknown as typeof IntersectionObserver
window.ResizeObserver = MockObserver as unknown as typeof ResizeObserver
HTMLCanvasElement.prototype.getContext = vi.fn(
  () => null,
) as unknown as typeof HTMLCanvasElement.prototype.getContext

/*
 * قراردادِ پس‌زمینه‌ی تمام‌صفحه در سطحِ *شل*.
 *
 * چرا جدا از تست‌های خودِ ویوها: لایه بیرونِ ویو می‌نشیند (اولین فرزندِ
 * `.app-shell`) و ویوها فقط مصرف‌کننده‌ی متغیرهای ارثی‌اند. پس اگر کسی مالکیت
 * را جابه‌جا کند، تست‌های ویو سبز می‌مانند ولی صفحه مشکی می‌شود. این فایل
 * همان مرز را می‌سنجد.
 */

const TOKENS = [
  '--tint-r', '--tint-g', '--tint-b',
  '--page-r', '--page-g', '--page-b',
  '--mesh1-r', '--mesh1-g', '--mesh1-b',
  '--mesh2-r', '--mesh2-g', '--mesh2-b',
  '--mesh3-r', '--mesh3-g', '--mesh3-b',
]

/*
 * رشته‌های رنگِ آماده، جدا از سه‌گانه‌های عددی.
 *
 * `--accent-fg` این‌جاست چون باید هم‌تم با اکسنتِ تصویرِ همان صفحه عوض شود:
 * روی صفحهٔ تم‌دارِ روشن، inkِ ثابتِ تم متنِ دکمهٔ پخش را ناخوانا می‌کرد.
 */
const COLOR_TOKENS = ['--accent', '--accent-dim', '--accent-fg']

/*
 * شکل‌ها باید کامل باشند، نه حداقلی: `ArtistView` روی فیلدهای اختیاری مثل
 * `artist.playlists.length` بدونِ چکِ وجود کار می‌کند، پس یک ماکِ ناقص باعثِ
 * ترکیدنِ رندر می‌شود و تست به‌جای سنجیدنِ تم، خطای بی‌ربط می‌دهد.
 */
const artist: ArtistDetail = {
  id: 'sp:artist:1',
  name: 'Tikhoon',
  artworkUrl: 'https://example.com/artist.jpg',
  bannerUrl: null,
  source: 'spotify',
  kind: 'artist',
  sourceUrl: 'https://open.spotify.com/artist/1',
  topTracks: [],
  albums: [],
  playlists: [],
  likedTracks: [],
  repostedTracks: [],
  radio: [],
  appearsOn: [],
  relatedArtists: [],
  videos: [],
} as unknown as ArtistDetail

const album: AlbumDetail = {
  id: 'sp:album:1',
  title: 'LOL',
  artist: 'Tikhoon',
  artistId: 'sp:artist:1',
  artworkUrl: 'https://example.com/cover.jpg',
  source: 'spotify',
  kind: 'album',
  sourceUrl: 'https://open.spotify.com/album/1',
  tracks: [],
} as unknown as AlbumDetail

/*
 * `getArtist`/`getAlbum` ماک می‌شوند تا صفحه بلاک نشود و رنگ از کشِ رنگ بیاید
 * (همان مسیرِ گرمی که در اپِ واقعی هم بعدِ ناوبری رخ می‌دهد).
 */
vi.mock('./lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./lib/api')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      getArtist: vi.fn(() => Promise.resolve(artist)),
      getAlbum: vi.fn(() => Promise.resolve(album)),
      search: vi.fn(() => Promise.resolve({ tracks: [], albums: [], artists: [], playlists: [] })),
    },
  }
})

/*
 * کشِ رنگ گرم: تمِ هر دو صفحه در همان فریمِ اول از تصویر می‌آید، پس تست
 * لازم نیست منتظرِ canvas بماند و همان مسیرِ واقعی سنجیده می‌شود.
 */
vi.mock('./lib/artColor', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./lib/artColor')>()
  return {
    ...actual,
    peekArtworkColor: vi.fn(() => [255, 45, 149]),
    dominantColor: vi.fn(() => Promise.resolve([255, 45, 149])),
  }
})

vi.mock('./lib/liquidGlass', () => ({
  mountLiquidGlass: vi.fn(() => Promise.resolve()),
  unmountLiquidGlass: vi.fn(),
}))

const App = (await import('./App')).default

let host: HTMLDivElement
let root: Root

/** اپ را روی یک مسیرِ مشخص رندر می‌کند (ناوبری از طریق `location.search` است). */
async function renderAt(search: string) {
  history.replaceState(null, '', `/${search}`)
  await act(async () => {
    root.render(<App />)
  })
  await settle()
}

/*
 * صبر تا ته‌نشینیِ زنجیره‌ی بارگذاری.
 *
 * ویوهای جزئیات با `lazy(() => import(...))` می‌آیند، پس تنها چند
 * `Promise.resolve()` کافی نیست — باید macrotask هم رد شود تا خودِ import حل
 * شود، بعد `api` بنشیند، و بعد رندرِ ویو کامل شود. تعدادش با ۸ کمتر از
 * حدِ لازم بود و اسکلتون روی صفحه می‌ماند.
 */
async function settle() {
  for (let i = 0; i < 12; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0))
    })
  }
}

const shell = () => host.querySelector<HTMLElement>('.app-shell')
const layer = () => host.querySelector<HTMLElement>('.page-tint')

beforeEach(() => {
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  document.documentElement.dataset.theme = 'dark'
})

afterEach(() => {
  act(() => root.unmount())
  host.remove()
})

describe('full-page artwork background', () => {
  it('mounts one fixed layer inside the shell', async () => {
    await renderAt('?artist=sp:artist:1')

    const shellEl = shell()
    expect(shellEl).not.toBeNull()
    expect(layer()).not.toBeNull()
    // اولین فرزند: هیچ محتوایی نباید زیرش بیفتد و ترتیبِ نقاشی عوض شود
    expect(shellEl?.firstElementChild).toBe(layer())
  })

  it('puts every theme token on the shell, not on the view root', async () => {
    await renderAt('?artist=sp:artist:1')

    const shellEl = shell()
    expect(shellEl?.classList.contains('tint-scope')).toBe(true)
    for (const token of TOKENS) {
      expect(shellEl?.style.getPropertyValue(token), token).toMatch(/^\d{1,3}$/)
    }
    for (const token of COLOR_TOKENS) {
      expect(shellEl?.style.getPropertyValue(token), token).toMatch(/^rgb\(/)
    }

    // ویو نباید هیچ‌کدام را تکرار کند
    const viewRoot = host.querySelector<HTMLElement>('.tint-page')
    expect(viewRoot, host.querySelector('main')?.innerHTML.slice(0, 800)).not.toBeNull()
    for (const token of [...TOKENS, ...COLOR_TOKENS]) {
      expect(viewRoot?.style.getPropertyValue(token), token).toBe('')
    }
  })

  it('re-inks the accent for the page instead of leaving the theme default', async () => {
    /*
     * روی صفحهٔ تم‌دار، `--accent` از تصویر آمده پس inkش هم باید از تم بیاید
     * (تیره: مشکیِ سبزفام، روشن: سفید). اگر این توکن نوشته نشود، مقدارِ
     * ثابتِ تم می‌ماند و در تمِ روشن متنِ دکمه ناخوانا می‌شود.
     */
    await renderAt('?artist=sp:artist:1')

    const dark = shell()?.style.getPropertyValue('--accent-fg')
    expect(dark).toBe('rgb(13 26 0)')

    document.documentElement.dataset.theme = 'light'
    await settle()
    expect(shell()?.style.getPropertyValue('--accent-fg')).toBe('rgb(255 255 255)')
  })

  it('activates for the album view too, seeding from its artwork', async () => {
    await renderAt('?url=https%3A%2F%2Fmusic.apple.com%2Falbum%2F1')

    const shellEl = shell()
    expect(shellEl?.hasAttribute('data-page-tint')).toBe(true)
    for (const token of TOKENS) {
      expect(shellEl?.style.getPropertyValue(token), token).toMatch(/^\d{1,3}$/)
    }
  })

  it('keeps the layer inert on pages with no artwork to theme from', async () => {
    await renderAt('')

    const shellEl = shell()
    expect(shellEl).not.toBeNull()
    expect(shellEl?.hasAttribute('data-page-tint')).toBe(false)
    /*
     * هیچ توکنی نوشته نمی‌شود: `@property`ها `initial-value` خاکستری دارند و
     * اگر روی صفحه‌ی خانه هم بنشینند، گذارِ خانه→هنرمند از خاکستری شروع
     * می‌شود. نبودشان یعنی `--page-*` به مقدارِ `--bg` می‌افتد.
     */
    for (const token of TOKENS) {
      expect(shellEl?.style.getPropertyValue(token), token).toBe('')
    }
  })

  it('derives the page base from the artwork instead of the flat theme background', async () => {
    await renderAt('?artist=sp:artist:1')

    const shellEl = shell() as HTMLElement
    const page: [number, number, number] = [
      Number(shellEl.style.getPropertyValue('--page-r')),
      Number(shellEl.style.getPropertyValue('--page-g')),
      Number(shellEl.style.getPropertyValue('--page-b')),
    ]
    // کاورِ صورتی باید پایه‌ی صورتی‌مایل بدهد، نه یک خاکستریِ تخت
    expect(page[0]).toBeGreaterThan(page[1])
    expect(page[0]).toBeGreaterThan(page[2])
    expect(page[1]).toBeLessThan(page[2])
    // و هرگز مشکیِ مطلق
    expect(Math.max(...page)).toBeGreaterThan(7)
  })
})

/*
 * بازخوانیِ صفحه بعد از تغییرِ هویت.
 *
 * خانه، کتابخانه و آمار داده‌شان را یک بار از سرور می‌گیرند و آن داده به حساب
 * گره خورده است. بدونِ این، کاربر بعدِ ورود همچنان کتابخانه‌ی مهمان را می‌بیند
 * تا خودش رفرش کند — همان چیزی که گزارش شد.
 *
 * عمداً **بدونِ** `location.reload()`: نوارِ پخش بخشی از همین سند است و رفرشِ
 * کامل صدای در حالِ پخش را می‌کشد. پس مکانیزم، دوباره‌سوارکردنِ همان بخشِ
 * صفحه است و این تست همان را می‌سنجد.
 */
describe('page data after an identity change', () => {
  /*
   * مکانیزم این است که ویو از نو سوار شود: فقط آن‌وقت افکت‌های `[]`ِ خودش
   * دوباره اجرا می‌شوند و داده‌ی حساب‌محور تازه خوانده می‌شود. پس همین مرز
   * سنجیده می‌شود — نه شمارشِ درخواست‌ها، که به مودِ API وابسته است.
   */
  it('remounts the page so its data effects run again', async () => {
    await renderAt('')
    const before = host.querySelector('.app-shell > main')

    const { emitIdentityChange } = await import('./lib/identity')
    await act(async () => {
      emitIdentityChange()
    })
    await settle()

    const after = host.querySelector('.app-shell > main')
    // همان عنصر یعنی هیچ چیزی دوباره سوار نشده؛ عنصرِ تازه یعنی ریمونت شده
    expect(after).not.toBe(before)
    expect(after).not.toBeNull()
  })

  it('remounts a non-home view for the same reason', async () => {
    await renderAt('?library=1')
    const before = host.querySelector('.page-drill-in')

    const { emitIdentityChange } = await import('./lib/identity')
    await act(async () => {
      emitIdentityChange()
    })
    await settle()

    expect(host.querySelector('.page-drill-in')).not.toBe(before)
  })

  it('does not reload the document, which would cut the audio', async () => {
    /*
     * رفرشِ کامل ارزان‌ترین راه بود، ولی صفِ پخش و صدای در جریان بخشی از همین
     * سند است؛ ورود نباید موسیقی را قطع کند. `location.reload` در jsdom
     * پیاده‌سازی ندارد، پس هر صدا زدنی هم پرت می‌کند و هم این تست را قرمز.
     */
    const reload = vi.fn()
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...window.location, reload },
    })
    await renderAt('')

    const { emitIdentityChange } = await import('./lib/identity')
    await act(async () => {
      emitIdentityChange()
    })
    await settle()

    expect(reload).not.toHaveBeenCalled()
  })

  it('keeps the same DOM when nothing about the identity changed', async () => {
    // ریمونتِ بی‌دلیل یعنی هر رندر صفحه از نو داده بگیرد؛ نباید رخ دهد
    await renderAt('')
    const before = host.querySelector('.app-shell > main')

    await act(async () => {
      await new Promise((r) => setTimeout(r, 0))
    })

    expect(host.querySelector('.app-shell > main')).toBe(before)
  })
})
