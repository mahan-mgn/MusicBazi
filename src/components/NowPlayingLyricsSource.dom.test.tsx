// @vitest-environment jsdom
//
// یکپارچگیِ انتخابِ منبع در NowPlaying.
//
// اینجا فقط رفتارِ *خودِ* ویژگی سنجیده می‌شود: ترجیحِ ذخیره‌شده بارگذاری
// می‌شود، انتخاب ذخیره می‌شود، و نتیجهٔ دیررس به آهنگِ بعدی نشت نمی‌کند.
// رگرسیونِ بقیه‌ی NowPlaying در فایلِ اصلیِ همان کامپوننت پوشش داده شده.
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { usePlayer } from '../store/player'
import type { PlayItem } from '../store/player'
import NowPlaying from './NowPlaying'

vi.mock('../lib/audioEngine', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/audioEngine')>()
  return {
    ...actual,
    engine: { ...actual.engine, bassLevel: () => 0.5, currentTime: () => 0 },
  }
})

vi.mock('../lib/artColor', () => ({
  dominantColor: vi.fn().mockResolvedValue([100, 150, 200]),
  fallbackTint: vi.fn().mockReturnValue([100, 150, 200]),
  tidalBgColor: vi.fn().mockReturnValue('rgb(20, 30, 40)'),
  tintVars: vi.fn().mockReturnValue({ rgb: '100 150 200', strong: '#ffffff' }),
  deriveHarmonics: vi.fn().mockReturnValue({
    dominant: [100, 150, 200],
    secondary: [150, 100, 200],
    accent: [200, 150, 100],
    muted: [30, 40, 50],
  }),
}))

const item: PlayItem = {
  id: 'test-track-1',
  streamUrl: 'https://example.com/audio.mp3',
  lyricsUrl: 'https://example.com/lyrics.lrc',
  track: {
    id: 'track-1',
    title: 'Rollercoaster',
    artist: 'Alborz',
    album: 'High Altitude',
    albumId: 'album-1',
    durationMs: 134000,
    artworkUrl: null,
    source: 'soundcloud',
    sourceUrl: 'https://soundcloud.com/alborz/rollercoaster',
    previewUrl: null,
  },
}

const secondItem: PlayItem = {
  ...item,
  id: 'test-track-2',
  lyricsUrl: 'https://example.com/lyrics2.lrc',
  track: { ...item.track, id: 'track-2', title: 'Second' },
}

let host: HTMLDivElement
let root: Root
let calls: { url: string; init?: RequestInit }[]

/** پاسخ‌های ساختگی به‌ازای هر الگوی URL. */
function stubFetch(handlers: Record<string, () => unknown>) {
  calls = []
  vi.stubGlobal('fetch', (url: string, init?: RequestInit) => {
    calls.push({ url: String(url), init })
    for (const [pattern, make] of Object.entries(handlers)) {
      if (String(url).includes(pattern)) {
        return Promise.resolve(make())
      }
    }
    return Promise.resolve({ ok: false, json: () => Promise.resolve({}), text: () => Promise.resolve('') })
  })
}

function ok(json: unknown) {
  return { ok: true, json: () => Promise.resolve(json), text: () => Promise.resolve('') }
}

function text(body: string) {
  return { ok: true, json: () => Promise.resolve({}), text: () => Promise.resolve(body) }
}

beforeEach(() => {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: false,
    media: query,
    addEventListener() {},
    removeEventListener() {},
  }))
  document.documentElement.requestFullscreen = vi.fn().mockResolvedValue(undefined)
  document.exitFullscreen = vi.fn().mockResolvedValue(undefined)

  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)

  usePlayer.setState({
    queue: [item],
    index: 0,
    playing: true,
    position: 30,
    duration: 134,
    volume: 0.8,
    muted: false,
    repeat: 'off',
    shuffle: false,
  })
})

afterEach(() => {
  act(() => root.unmount())
  host.remove()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

async function settle() {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
    await Promise.resolve()
  })
}

/** پنلِ متن را باز می‌کند. */
async function openLyricsPanel() {
  await act(async () => {
    root.render(<NowPlaying onClose={() => {}} />)
  })
  await settle()
  // دو دکمه با همین برچسب وجود دارد: یکی داخلِ منوی «گزینه‌های بیشتر» که
  // فقط وقتی منو باز است رندر می‌شود، و یکی در هدر که همیشه هست. دومی را
  // می‌خواهیم — با `title` تشخیصش می‌دهیم که فقط روی همان یکی هست.
  const button = [...host.querySelectorAll('button')].find(
    (b) => b.getAttribute('aria-label') === 'متن هم‌زمان‌شده' && b.getAttribute('title'),
  )
  await act(async () => {
    button?.click()
  })
  await settle()
}

describe('NowPlaying lyrics source integration', () => {
  it('loads the default lyrics when no preference is stored', async () => {
    stubFetch({
      '/api/lyrics/preference': () => ok({ provider: null }),
      'lyrics.lrc': () => text('[00:01.00]hello'),
    })

    await openLyricsPanel()

    expect(calls.some((c) => c.url === 'https://example.com/lyrics.lrc')).toBe(true)
    // هیچ درخواستِ منبع‌محوری نباید زده شود
    expect(calls.some((c) => c.url.includes('provider='))).toBe(false)
  })

  it('uses the stored source instead of the default url', async () => {
    stubFetch({
      '/api/lyrics/preference': () => ok({ provider: 'unison' }),
      '/api/stream/lyrics': () => text('[00:02.00]from provider'),
    })

    await openLyricsPanel()

    const providerCall = calls.find((c) => c.url.includes('provider=unison'))
    expect(providerCall).toBeDefined()
  })

  it('marks the source as failed and falls back when it errors', async () => {
    stubFetch({
      '/api/lyrics/preference': () => ok({ provider: 'unison' }),
      '/api/stream/lyrics': () => ({ ok: false, json: () => Promise.resolve({}), text: () => Promise.resolve('') }),
    })

    await openLyricsPanel()

    // به خودکار برگشتیم: درخواستِ آدرسِ پیش‌فرض زده شده
    expect(calls.some((c) => c.url === 'https://example.com/lyrics.lrc')).toBe(true)
  })

  it('does not leak a late result into the next track', async () => {
    let resolveFirst: ((v: unknown) => void) | null = null

    calls = []
    vi.stubGlobal('fetch', (url: string) => {
      calls.push({ url: String(url) })
      if (String(url).includes('/api/lyrics/preference')) {
        return Promise.resolve(ok({ provider: null }))
      }
      if (String(url) === 'https://example.com/lyrics.lrc') {
        // اولین آهنگ را در حالتِ معلق نگه می‌دارد
        return new Promise((resolve) => {
          resolveFirst = resolve
        })
      }
      return Promise.resolve(text('[00:09.00]second track'))
    })

    await openLyricsPanel()

    // تغییرِ آهنگ قبل از رسیدنِ پاسخِ اولی
    await act(async () => {
      usePlayer.setState({ queue: [secondItem], index: 0 })
    })
    await settle()

    // حالا پاسخِ آهنگِ اول می‌رسد — نباید جایی بنشیند
    await act(async () => {
      resolveFirst?.(text('[00:01.00]STALE'))
      await Promise.resolve()
    })
    await settle()

    expect(host.textContent).not.toContain('STALE')
  })

  it('saves the selection when a source is chosen', async () => {
    stubFetch({
      '/api/lyrics/preference': () => ok({ provider: null }),
      '/api/lyrics/sources': () =>
        ok({
          trackId: 'track-1',
          preferred: null,
          sources: [
            {
              id: 'lrclib',
              label: 'LRCLIB',
              capabilities: ['line'],
              in_auto_chain: true,
              selectable: true,
              status: 'available',
              experimental: false,
              unavailable_reason: null,
            },
          ],
        }),
      'lyrics.lrc': () => text('[00:01.00]auto'),
      '/api/stream/lyrics': () => text('[00:03.00]picked'),
    })

    await openLyricsPanel()

    // منوی منبع را باز کن
    const trigger = [...host.querySelectorAll<HTMLButtonElement>('button')].find(
      (b) => b.getAttribute('aria-label') === 'منبع متن',
    )
    await act(async () => {
      trigger?.click()
    })
    await settle()

    const option = [...document.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]')].find((b) =>
      b.textContent?.includes('LRCLIB'),
    )
    await act(async () => {
      option?.click()
    })
    await settle()

    const save = calls.find((c) => c.init?.method === 'PUT' && c.url.includes('provider=lrclib'))
    expect(save).toBeDefined()
  })

  it('clears the preference when automatic is chosen', async () => {
    stubFetch({
      '/api/lyrics/preference': () => ok({ provider: 'lrclib' }),
      '/api/lyrics/sources': () =>
        ok({
          trackId: 'track-1',
          preferred: 'lrclib',
          sources: [
            {
              id: 'lrclib',
              label: 'LRCLIB',
              capabilities: ['line'],
              in_auto_chain: true,
              selectable: true,
              status: 'available',
              experimental: false,
              unavailable_reason: null,
            },
          ],
        }),
      '/api/stream/lyrics': () => text('[00:03.00]picked'),
      'lyrics.lrc': () => text('[00:01.00]auto'),
    })

    await openLyricsPanel()

    const trigger = [...host.querySelectorAll<HTMLButtonElement>('button')].find(
      (b) => b.getAttribute('aria-label') === 'منبع متن',
    )
    await act(async () => {
      trigger?.click()
    })
    await settle()

    const auto = [...document.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]')].find((b) =>
      b.textContent?.includes('خودکار'),
    )
    await act(async () => {
      auto?.click()
    })
    await settle()

    const cleared = calls.find((c) => c.init?.method === 'DELETE')
    expect(cleared).toBeDefined()
  })

  it('opens the source menu without contacting a provider', async () => {
    stubFetch({
      '/api/lyrics/preference': () => ok({ provider: null }),
      '/api/lyrics/sources': () => ok({ trackId: 'track-1', preferred: null, sources: [] }),
      'lyrics.lrc': () => text('[00:01.00]x'),
    })

    await openLyricsPanel()

    const trigger = [...host.querySelectorAll<HTMLButtonElement>('button')].find(
      (b) => b.getAttribute('aria-label') === 'منبع متن',
    )
    await act(async () => {
      trigger?.click()
    })
    await settle()

    // تنها تماسِ مربوط به منو، فهرستِ منابع است
    expect(calls.filter((c) => c.url.includes('/api/lyrics/sources'))).toHaveLength(1)
    expect(calls.some((c) => c.url.includes('provider='))).toBe(false)
  })
})
