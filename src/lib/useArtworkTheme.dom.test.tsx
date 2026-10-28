// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { dominantColor, peekArtworkColor, type RGB } from './artColor'
import type { PageTheme } from './pageTheme'
import { useArtworkTheme } from './useArtworkTheme'

/*
 * فقط دو تابعِ ورودی/خروجی ماک می‌شوند؛ ریاضیاتِ پالت واقعی می‌ماند تا تست
 * رفتارِ هوک را بسنجد، نه یک نسخه‌ی جعلیِ `pageTheme` را.
 */
vi.mock('./artColor', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./artColor')>()
  return {
    ...actual,
    dominantColor: vi.fn(),
    peekArtworkColor: vi.fn(() => null),
  }
})

const dominantColorMock = vi.mocked(dominantColor)
const peekMock = vi.mocked(peekArtworkColor)

// @ts-expect-error React act environment flag
globalThis.IS_REACT_ACT_ENVIRONMENT = true

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((r) => {
    resolve = r
  })
  return { promise, resolve }
}

let host: HTMLDivElement
let root: Root
let themes: PageTheme[]
/** مسیرِ پیش‌فرضِ استخراج؛ هر تست می‌تواند عوضش کند */
let resolveSrc: (src: string) => Promise<RGB | null>

function Probe({
  src,
  seed,
  initial,
}: {
  src: string | null
  seed: string
  initial?: RGB | null
}) {
  const theme = useArtworkTheme(src, seed, initial)
  themes.push(theme)
  return <span data-key={theme.key} />
}

function render(props: { src: string | null; seed: string; initial?: RGB | null }) {
  act(() => {
    root.render(<Probe {...props} />)
  })
}

async function flush() {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
  })
}

function key(): string | null {
  return host.querySelector('span')?.getAttribute('data-key') ?? null
}

beforeEach(() => {
  themes = []
  resolveSrc = () => Promise.resolve(null)
  peekMock.mockReset()
  peekMock.mockReturnValue(null)
  dominantColorMock.mockReset()
  dominantColorMock.mockImplementation((src: string | null) =>
    src ? resolveSrc(src) : Promise.resolve(null)
  )
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
})

afterEach(() => {
  act(() => {
    root.unmount()
  })
  host.remove()
})

describe('useArtworkTheme first paint', () => {
  it('paints the real colour on the very first frame when the cache is warm', () => {
    peekMock.mockReturnValue([10, 20, 30])
    render({ src: '/api/art/a', seed: 'track-1' })
    expect(themes[0].extracted).toEqual([10, 20, 30])
    // هیچ فریمِ میانیِ سید وجود ندارد
    expect(themes.map((t) => t.key)).toEqual(['art:10 20 30:dark'])
    expect(dominantColorMock).not.toHaveBeenCalled()
  })

  it('uses the caller hint for the first paint, then reconciles with the cache', () => {
    peekMock.mockReturnValue([1, 1, 1])
    render({ src: '/api/art/a', seed: 'track-1', initial: [2, 2, 2] })
    // فریمِ اول از مقدارِ فراخوان می‌آید تا پرشِ رنگ نداشته باشیم …
    expect(themes[0].extracted).toEqual([2, 2, 2])
    // … و بعد کش حرفِ آخر را می‌زند، چون رنگِ واقعیِ همین کاور است
    expect(key()).toBe('art:1 1 1:dark')
  })

  it('adds no extra render when the hint is the cached colour itself', () => {
    // مسیرِ واقعیِ تولید: hint از `dominantColor` آمده، پس همان شیءِ کش است
    const shared: RGB = [2, 2, 2]
    peekMock.mockReturnValue(shared)
    render({ src: '/api/art/a', seed: 'track-1', initial: shared })
    expect(themes).toHaveLength(1)
    expect(key()).toBe('art:2 2 2:dark')
  })

  it('shows the seeded palette first and then eases to the extracted colour', async () => {
    resolveSrc = async () => [4, 5, 6]
    render({ src: '/api/art/a', seed: 'album-7' })
    expect(themes[0].extracted).toBeNull()
    expect(themes[0].key.startsWith('seed:')).toBe(true)

    await flush()
    expect(key()).toBe('art:4 5 6:dark')
    expect(themes[themes.length - 1].extracted).toEqual([4, 5, 6])
  })

  it('keeps the seeded palette when extraction fails instead of going grey', async () => {
    resolveSrc = async () => null
    render({ src: '/api/art/broken', seed: 'album-7' })
    await flush()
    const theme = themes[themes.length - 1]
    expect(theme.extracted).toBeNull()
    expect(theme.key.startsWith('seed:')).toBe(true)
    expect(theme.source).not.toEqual([107, 107, 107])
  })

  it('treats a missing cover as "no colour" rather than "not yet"', () => {
    render({ src: null, seed: 'album-7' })
    expect(themes[0].extracted).toBeNull()
    expect(themes[0].key.startsWith('seed:')).toBe(true)
    expect(dominantColorMock).not.toHaveBeenCalled()
  })
})

describe('useArtworkTheme transitions', () => {
  it('holds the previous colour while the next cover resolves', async () => {
    resolveSrc = async () => [1, 2, 3]
    render({ src: '/api/art/a', seed: 's' })
    await flush()
    expect(key()).toBe('art:1 2 3:dark')

    const next = deferred<RGB | null>()
    resolveSrc = () => next.promise
    render({ src: '/api/art/b', seed: 's' })

    // رنگِ قبلی روی صفحه مانده — نه خاکستری، نه سید
    expect(key()).toBe('art:1 2 3:dark')

    next.resolve([4, 5, 6])
    await flush()
    expect(key()).toBe('art:4 5 6:dark')
  })

  it('clears to the seeded palette when the next cover fails', async () => {
    resolveSrc = async () => [1, 2, 3]
    render({ src: '/api/art/a', seed: 'album-2' })
    await flush()
    expect(key()).toBe('art:1 2 3:dark')

    resolveSrc = async () => null
    render({ src: '/api/art/broken', seed: 'album-2' })
    await flush()
    expect(themes[themes.length - 1].extracted).toBeNull()
  })

  it('drops the colour immediately when the next item has no cover at all', async () => {
    resolveSrc = async () => [1, 2, 3]
    render({ src: '/api/art/a', seed: 's' })
    await flush()
    expect(key()).toBe('art:1 2 3:dark')

    render({ src: null, seed: 's' })
    expect(themes[themes.length - 1].extracted).toBeNull()
  })

  it('never lets a late result for the previous cover land', async () => {
    const slow = deferred<RGB | null>()
    resolveSrc = (src) => (src === '/api/art/a' ? slow.promise : Promise.resolve(null))
    render({ src: '/api/art/a', seed: 's' })

    const fast = deferred<RGB | null>()
    resolveSrc = () => fast.promise
    render({ src: '/api/art/b', seed: 's' })

    slow.resolve([9, 9, 9])
    await flush()
    expect(key()).not.toBe('art:9 9 9:dark')

    fast.resolve([4, 5, 6])
    await flush()
    expect(key()).toBe('art:4 5 6:dark')
  })

  it('reuses a warm cache entry instead of hitting the network again', async () => {
    render({ src: '/api/art/a', seed: 's' })
    await flush()
    expect(dominantColorMock).toHaveBeenCalledTimes(1)

    peekMock.mockReturnValue([7, 8, 9])
    render({ src: '/api/art/warm', seed: 's' })
    expect(key()).toBe('art:7 8 9:dark')
    expect(dominantColorMock).toHaveBeenCalledTimes(1)
  })
})

describe('useArtworkTheme identity', () => {
  it('returns the same theme object across unrelated re-renders', async () => {
    resolveSrc = async () => [1, 2, 3]
    render({ src: '/api/art/a', seed: 's' })
    await flush()

    const before = themes[themes.length - 1]
    render({ src: '/api/art/a', seed: 's' })
    render({ src: '/api/art/a', seed: 's' })

    expect(themes[themes.length - 1]).toBe(before)
  })

  it('changes identity when the cover colour changes', async () => {
    resolveSrc = async () => [1, 2, 3]
    render({ src: '/api/art/a', seed: 's' })
    await flush()
    const first = themes[themes.length - 1]

    resolveSrc = async () => [4, 5, 6]
    render({ src: '/api/art/b', seed: 's' })
    await flush()
    expect(themes[themes.length - 1]).not.toBe(first)
    expect(themes[themes.length - 1].key).toBe('art:4 5 6:dark')
  })
})
