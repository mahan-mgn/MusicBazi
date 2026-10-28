// @vitest-environment jsdom
//
// F2 — تستِ قرارداد با پاسخِ **واقعیِ** بک‌اند.
//
// تفاوت مهم با بقیهٔ تست‌های این پوشه: ماژولِ کلاینت (`lib/lyricsSources`)
// **mock نمی‌شود**. فقط `fetch` عوض می‌شود و بدنهٔ واقعیِ پاسخ را برمی‌گرداند
// — همان fixture‌ای که `server/tests/test_lyrics_frontend_contract.py` از
// `TestClient` تولید می‌کند. پس اگر نامِ فیلدی بین بک‌اند و فرانت نخواند،
// این تست می‌شکند در حالی که بقیه سبز می‌مانند.
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Track } from '../lib/types'
import { fetchLyricsSources } from '../lib/lyricsSources'
import nowPlayingFixture from '../lib/__fixtures__/lyrics_sources.json'
import LyricsSourceMenu from './LyricsSourceMenu'

const track: Track = {
  id: 'spotify:track:4uLU6hMCjMI75M1A2tKUQC',
  title: 'Blinding Lights',
  artist: 'The Weeknd',
  album: 'After Hours',
  durationMs: 200040,
  source: 'spotify',
  sourceUrl: 'https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC',
  artworkUrl: null,
  previewUrl: null,
}

let host: HTMLDivElement
let root: Root

beforeEach(() => {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
})

afterEach(() => {
  act(() => root.unmount())
  host.remove()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

async function tick() {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
    await Promise.resolve()
  })
}

describe('backend response contract', () => {
  it('the client parses the real payload without losing sources', async () => {
    vi.stubGlobal('fetch', () =>
      Promise.resolve({ ok: true, json: () => Promise.resolve(nowPlayingFixture) }),
    )

    const body = await fetchLyricsSources(track)

    expect(body).not.toBeNull()
    expect(body!.sources).toHaveLength(12)
    expect(body!.sources.filter((s) => s.selectable)).toHaveLength(8)
  })

  it('the client keeps the snake_case fields the backend sends', async () => {
    vi.stubGlobal('fetch', () =>
      Promise.resolve({ ok: true, json: () => Promise.resolve(nowPlayingFixture) }),
    )

    const body = await fetchLyricsSources(track)
    const row = body!.sources.find((s) => s.id === 'lrclib')!

    // اگر بک‌اند camelCase می‌فرستاد، این‌ها undefined می‌شدند
    expect(row.selectable).toBe(true)
    expect(row.in_auto_chain).toBe(true)
    expect(row.status).toBe('available')
    expect(row.experimental).toBe(false)
    expect(Array.isArray(row.capabilities)).toBe(true)
  })
})

describe('the menu renders the real payload', () => {
  async function openMenu() {
    vi.stubGlobal('fetch', (url: string) =>
      Promise.resolve(
        String(url).includes('/api/lyrics/sources')
          ? { ok: true, json: () => Promise.resolve(nowPlayingFixture), text: () => Promise.resolve('') }
          : { ok: true, json: () => Promise.resolve({}), text: () => Promise.resolve('') },
      ),
    )
    act(() =>
      root.render(<LyricsSourceMenu track={track} current={null} onSelect={() => {}} />),
    )
    await act(async () => {
      host.querySelector('button')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await tick()
  }

  it('shows all eight selectable sources', async () => {
    await openMenu()

    const items = document.querySelectorAll('[role="menuitemradio"]')

    // ۸ قابلِ انتخاب + گزینهٔ «خودکار»
    expect(items).toHaveLength(9)
  })

  it('lists every real selectable source by label', async () => {
    await openMenu()

    const text = document.body.textContent ?? ''
    for (const id of ['lrclib', 'lyricsplus', 'unison', 'betterlyrics', 'binilyrics', 'lrc_red', 'simpmusic', 'paxsenix']) {
      const row = nowPlayingFixture.sources.find((s) => s.id === id)!
      expect(text).toContain(row.label)
    }
  })

  it('shows the automatic option', async () => {
    await openMenu()

    expect(document.body.textContent).toContain('خودکار')
  })

  it('puts the unusable sources in a separate, collapsible section', async () => {
    await openMenu()

    // سرصفحهٔ بخش وجود دارد، ولی محتوایش تا باز نشدن پنهان است
    const header = [...document.querySelectorAll('button')].find((b) =>
      b.textContent?.includes('غیرقابل استفاده'),
    )
    expect(header).toBeDefined()
    expect(document.body.textContent).not.toContain('KuGou')

    act(() => {
      header!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(document.body.textContent).toContain('KuGou')
  })

  it('does not fetch the lyric text when the menu opens', async () => {
    const calls: string[] = []
    vi.stubGlobal('fetch', (url: string) => {
      calls.push(String(url))
      return Promise.resolve(
        String(url).includes('/api/lyrics/sources')
          ? { ok: true, json: () => Promise.resolve(nowPlayingFixture), text: () => Promise.resolve('') }
          : { ok: true, json: () => Promise.resolve({}), text: () => Promise.resolve('') },
      )
    })
    act(() =>
      root.render(<LyricsSourceMenu track={track} current={null} onSelect={() => {}} />),
    )
    await act(async () => {
      host.querySelector('button')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await tick()

    expect(calls.filter((u) => u.includes('/api/lyrics/sources'))).toHaveLength(1)
    expect(calls.some((u) => u.includes('stream/lyrics'))).toBe(false)
  })

  it('sends the same track parameters the backend expects', async () => {
    const calls: string[] = []
    vi.stubGlobal('fetch', (url: string) => {
      calls.push(String(url))
      return Promise.resolve({ ok: true, json: () => Promise.resolve(nowPlayingFixture), text: () => Promise.resolve('') })
    })
    act(() =>
      root.render(<LyricsSourceMenu track={track} current={null} onSelect={() => {}} />),
    )
    await act(async () => {
      host.querySelector('button')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await tick()

    const url = calls.find((u) => u.includes('/api/lyrics/sources'))!
    expect(url).toContain('track_id=spotify%3Atrack%3A4uLU6hMCjMI75M1A2tKUQC')
    expect(url).toContain('title=Blinding+Lights')
    expect(url).toContain('artist=The+Weeknd')
    expect(url).toContain('album=After+Hours')
    expect(url).toContain('duration_ms=200040')
  })
})

describe('failure and empty states are always visible', () => {
  async function openWith(handler: () => Promise<unknown>) {
    vi.stubGlobal('fetch', handler)
    act(() =>
      root.render(<LyricsSourceMenu track={track} current={null} onSelect={() => {}} />),
    )
    await act(async () => {
      host.querySelector('button')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await tick()
  }

  it('shows an error message and a retry when the request fails', async () => {
    await openWith(() => Promise.reject(new Error('offline')))

    const text = document.body.textContent ?? ''
    expect(text).toContain('فهرست منابع بارگذاری نشد')
    expect(text).toContain('تلاش دوباره')
  })

  it('shows an error message on a non-ok response', async () => {
    await openWith(() =>
      Promise.resolve({ ok: false, json: () => Promise.resolve({}), text: () => Promise.resolve('') }),
    )

    expect(document.body.textContent).toContain('فهرست منابع بارگذاری نشد')
  })

  it('shows an empty message when nothing is selectable', async () => {
    await openWith(() =>
      Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            trackId: track.id,
            preferred: null,
            sources: nowPlayingFixture.sources.filter((s) => !s.selectable),
          }),
        text: () => Promise.resolve(''),
      }),
    )

    expect(document.body.textContent).toContain('منبعی برای نمایش نیست')
  })

  it('the menu never disappears in a failure state', async () => {
    await openWith(() => Promise.reject(new Error('offline')))

    // منو باید باز بماند و پیام نشان بدهد، نه اینکه محو شود
    expect(document.querySelector('[role="menu"]')).not.toBeNull()
  })
})

describe('error codes drive distinct messages', () => {
  // ماتریسِ رفتارِ G3: هر کدِ خطا پیامِ خودش را می‌گیرد.
  it('maps a not_found code to a neutral message naming the source', async () => {
    const { sourceErrorLabel } = await import('../lib/lyricsSources')

    // پیامِ not_found باید نامِ منبع را داشته باشد و «خطا» نباشد
    const text = sourceErrorLabel({ srcNotFound: (n: string) => `در ${n} متنی پیدا نشد` }, 'lrclib', 'not_found')
    expect(text).toContain('lrclib')
  })

  it('gives rate limiting its own message', async () => {
    const { sourceErrorLabel } = await import('../lib/lyricsSources')

    const text = sourceErrorLabel({}, 'lrclib', 'rate_limited')
    expect(text).not.toBe(sourceErrorLabel({}, 'lrclib', 'provider_error'))
  })

  it('distinguishes needs_setup, blocked, and disabled', async () => {
    const { sourceErrorLabel } = await import('../lib/lyricsSources')

    const a = sourceErrorLabel({}, 'x', 'needs_setup')
    const b = sourceErrorLabel({}, 'x', 'blocked')
    const c = sourceErrorLabel({}, 'x', 'disabled')
    expect(new Set([a, b, c]).size).toBe(3)
  })

  it('reads the machine code from the backend error body', async () => {
    const { readSourceError } = await import('../lib/lyricsSources')

    const e = readSourceError({ code: 'rate_limited', provider: 'lrclib', http_status: 429 }, 'x')
    expect(e.code).toBe('rate_limited')
    expect(e.provider).toBe('lrclib')
    expect(e.httpStatus).toBe(429)
  })

  it('falls back safely when the body has no code', async () => {
    const { readSourceError } = await import('../lib/lyricsSources')

    const e = readSourceError(null, 'lrclib')
    expect(e.code).toBe('provider_error')
    expect(e.provider).toBe('lrclib')
    expect(e.httpStatus).toBeNull()
  })

  it('the menu shows the source in use when one is selected', async () => {
    vi.stubGlobal('fetch', () =>
      Promise.resolve({ ok: true, json: () => Promise.resolve(nowPlayingFixture), text: () => Promise.resolve('') }),
    )
    act(() =>
      root.render(<LyricsSourceMenu track={track} current="lrclib" onSelect={() => {}} />),
    )

    expect(host.textContent).toContain('lrclib')
  })

  it('the trigger shows which source supplied the automatic lyrics', async () => {
    vi.stubGlobal('fetch', () =>
      Promise.resolve({ ok: true, json: () => Promise.resolve(nowPlayingFixture), text: () => Promise.resolve('') }),
    )
    act(() =>
      root.render(
        <LyricsSourceMenu track={track} current={null} usedSource="LRCLIB" onSelect={() => {}} />,
      ),
    )

    expect(host.textContent).toContain('LRCLIB')
  })
})
