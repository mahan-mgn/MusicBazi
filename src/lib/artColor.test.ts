// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  artworkColorCacheSize,
  clampLuminance,
  clearArtworkColorCache,
  contrastRatio,
  dominantColor,
  fallbackTint,
  peekArtworkColor,
  relativeLuminance,
  tidalBgColor,
  tintVars,
  type RGB,
} from './artColor'

/** luminance معکوس‌شده از خروجیِ color-mixِ --pb-strong */
function strongLum(strong: string): number {
  const m = strong.match(
    /^color-mix\(in srgb, rgb\((\d+) (\d+) (\d+)\) (\d+)%/
  )
  if (!m) throw new Error(`unexpected strong value: ${strong}`)
  const [, r, g, b, pct] = m
  const w = (100 - Number(pct)) / 100
  const mix = (c: number) => c + (255 - c) * w
  return (0.2126 * mix(+r) + 0.7152 * mix(+g) + 0.0722 * mix(+b)) / 255
}

/** همان مخلوطی که color-mixِ `--pb-strong` می‌سازد، به‌صورت RGB */
function strongRgb(strong: string): RGB {
  const m = strong.match(
    /^color-mix\(in srgb, rgb\((\d+) (\d+) (\d+)\) (\d+)%/
  )
  if (!m) throw new Error(`unexpected strong value: ${strong}`)
  const [, r, g, b, pct] = m
  const w = (100 - Number(pct)) / 100
  const mix = (c: number) => Math.round(c + (255 - c) * w)
  return [mix(+r), mix(+g), mix(+b)]
}

describe('tintVars', () => {
  it('rgb triad is the raw dominant color', () => {
    expect(tintVars([12, 200, 60]).rgb).toBe('12 200 60')
  })

  it('lifts a dark cover to the ~0.55 luminance target', () => {
    expect(strongLum(tintVars([20, 30, 90]).strong)).toBeCloseTo(0.55, 1)
  })

  it('leaves an already-bright color untouched', () => {
    expect(tintVars([255, 235, 120]).strong).toContain('rgb(255 235 120) 100%')
  })

  it('never asks for negative white (pure black lifts, not overshoots)', () => {
    const { strong } = tintVars([0, 0, 0])
    expect(strong).toMatch(/^color-mix\(in srgb, rgb\(0 0 0\) \d{1,3}%/)
    expect(strongLum(strong)).toBeCloseTo(0.55, 1)
  })

  /*
   * قراردادِ کنتراستِ اکسنت: `--accent-fg` روی همه‌ی اکسنت‌ها `#0b0b0b` است
   * (index.css:823 و 871)، پس `strong` باید با آن کنتراستِ خوانا داشته باشد —
   * حتی برای کاورهای اشباعِ تک‌کاناله.
   */
  it('keeps WCAG AA contrast against --accent-fg for every cover colour', () => {
    const accentFg: RGB = [11, 11, 11]
    const covers: RGB[] = [
      [0, 0, 0],
      [7, 7, 7],
      [255, 255, 0],
      [255, 235, 120],
      [0, 196, 0],
      [0, 0, 255],
      [255, 0, 0],
      [180, 20, 50],
      [128, 128, 128],
      [20, 30, 90],
      [12, 200, 60],
      [255, 255, 255],
    ]
    for (const cover of covers) {
      expect(
        contrastRatio(strongRgb(tintVars(cover).strong), accentFg)
      ).toBeGreaterThanOrEqual(4.5)
    }
  })
})

describe('relativeLuminance / contrastRatio', () => {
  it('anchors at the two ends of the scale', () => {
    expect(relativeLuminance([0, 0, 0])).toBe(0)
    expect(relativeLuminance([255, 255, 255])).toBeCloseTo(1, 5)
  })

  it('gives the reference 21:1 for black on white', () => {
    expect(contrastRatio([0, 0, 0], [255, 255, 255])).toBeCloseTo(21, 1)
  })

  it('is order independent and 1:1 for identical colors', () => {
    expect(contrastRatio([128, 128, 128], [128, 128, 128])).toBe(1)
    expect(contrastRatio([10, 20, 30], [200, 210, 220])).toBeCloseTo(
      contrastRatio([200, 210, 220], [10, 20, 30]),
      10
    )
  })
})

describe('clampLuminance', () => {
  it('leaves a colour that is already dark enough untouched', () => {
    expect(clampLuminance([0, 0, 0], 0.22)).toEqual([0, 0, 0])
    expect(clampLuminance([10, 10, 10], 0.22)).toEqual([10, 10, 10])
  })

  it('brings a saturated bright colour down to the ceiling', () => {
    const clamped = clampLuminance([255, 255, 0], 0.22)
    expect(relativeLuminance(clamped)).toBeLessThanOrEqual(0.22)
    expect(relativeLuminance(clamped)).toBeGreaterThan(0.19)
  })

  it('preserves hue and channel ordering', () => {
    const [r, g, b] = clampLuminance([255, 255, 0], 0.22)
    expect(r).toBe(g)
    expect(b).toBe(0)
    const warm = clampLuminance([255, 0, 0], 0.22)
    expect(warm[0]).toBeGreaterThan(warm[1])
    expect(warm[1]).toBe(warm[2])
  })

  it('keeps grays neutral', () => {
    const [r, g, b] = clampLuminance([255, 255, 255], 0.22)
    expect(r).toBe(g)
    expect(g).toBe(b)
  })

  it('never exceeds the requested ceiling', () => {
    const covers: RGB[] = [
      [255, 255, 0],
      [255, 235, 120],
      [0, 196, 0],
      [255, 0, 255],
      [12, 200, 60],
    ]
    for (const cover of covers) {
      expect(relativeLuminance(clampLuminance(cover, 0.2))).toBeLessThanOrEqual(0.2)
    }
  })
})

describe('tidalBgColor', () => {
  it('returns fallback dark color for null', () => {
    expect(tidalBgColor(null)).toBe('#121214')
  })

  it('returns deep dark color for red locker cover', () => {
    const bg = tidalBgColor([180, 20, 50])
    expect(bg).toMatch(/^rgb\(\d+, \d+, \d+\)$/)
    const [r, g, b] = bg.replace(/[^\d,]/g, '').split(',').map(Number)
    expect(r).toBeGreaterThan(b)
    expect(r).toBeGreaterThan(g)
    expect(r).toBeLessThan(120)
  })

  it('returns dark charcoal for black and white cover', () => {
    expect(tidalBgColor([128, 128, 128])).toBe('#141416')
  })
})

describe('fallbackTint', () => {
  it('returns stable rgb triad for given seed', () => {
    const t1 = fallbackTint('album-123')
    const t2 = fallbackTint('album-123')
    expect(t1).toEqual(t2)
    expect(t1).toHaveLength(3)
    expect(t1.every((v) => v >= 0 && v <= 255)).toBe(true)
  })

  it('never returns pure gray/black fallback', () => {
    const [r, g, b] = fallbackTint('track-abc')
    const max = Math.max(r, g, b)
    const min = Math.min(r, g, b)
    expect(max - min).toBeGreaterThan(0)
  })
})

/* ------------------------------------------------------------------ */
/* کش و مسیرهای خطا                                                     */
/* ------------------------------------------------------------------ */

const SIZE = 24

function fillPixels(r: number, g: number, b: number): Uint8ClampedArray {
  const data = new Uint8ClampedArray(SIZE * SIZE * 4)
  for (let i = 0; i < SIZE * SIZE; i++) {
    data[i * 4] = r
    data[i * 4 + 1] = g
    data[i * 4 + 2] = b
    data[i * 4 + 3] = 255
  }
  return data
}

let pixels: Uint8ClampedArray
let behaviour: 'load' | 'error' | 'no-context'
let created: { src: string; crossOrigin: string | null }[]
const getImageData = vi.fn()

class FakeImage {
  crossOrigin: string | null = null
  onload: (() => void) | null = null
  onerror: ((err?: unknown) => void) | null = null
  private current = ''

  get src(): string {
    return this.current
  }

  set src(next: string) {
    this.current = next
    created.push({ src: next, crossOrigin: this.crossOrigin })
    queueMicrotask(() => {
      if (behaviour === 'error') this.onerror?.(new Error('boom'))
      else this.onload?.()
    })
  }
}

describe('dominantColor cache', () => {
  beforeEach(() => {
    clearArtworkColorCache()
    pixels = fillPixels(120, 160, 200)
    behaviour = 'load'
    created = []
    getImageData.mockImplementation(
      () => ({ data: pixels }) as unknown as ImageData
    )
    HTMLCanvasElement.prototype.getContext = vi.fn(() =>
      behaviour === 'no-context' ? null : { drawImage: () => {}, getImageData }
    ) as unknown as typeof HTMLCanvasElement.prototype.getContext
    vi.stubGlobal('Image', FakeImage)
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('returns null for an empty source without touching the DOM', async () => {
    expect(await dominantColor(null)).toBeNull()
    expect(await dominantColor('')).toBeNull()
    expect(created).toHaveLength(0)
    expect(artworkColorCacheSize()).toBe(0)
  })

  it('extracts the dominant colour and reads it back synchronously', async () => {
    expect(peekArtworkColor('/api/art/aa')).toBeNull()
    expect(await dominantColor('/api/art/aa')).toEqual([120, 160, 200])
    expect(peekArtworkColor('/api/art/aa')).toEqual([120, 160, 200])
  })

  it('serves a cached colour without building a second image', async () => {
    await dominantColor('/api/art/aa')
    expect(created).toHaveLength(1)
    expect(await dominantColor('/api/art/aa')).toEqual([120, 160, 200])
    expect(created).toHaveLength(1)
  })

  it('dedupes concurrent requests for the same cover', async () => {
    const [a, b, c] = await Promise.all([
      dominantColor('/api/art/aa'),
      dominantColor('/api/art/aa'),
      dominantColor('/api/art/aa'),
    ])
    expect(a).toEqual([120, 160, 200])
    expect(b).toEqual(a)
    expect(c).toEqual(a)
    expect(created).toHaveLength(1)
  })

  it('returns null when the image fails to load and does not retry inside the TTL', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-01-01T00:00:00Z'))
    behaviour = 'error'

    expect(await dominantColor('/api/art/broken')).toBeNull()
    expect(created).toHaveLength(1)
    expect(await dominantColor('/api/art/broken')).toBeNull()
    expect(created).toHaveLength(1)
    // کشِ منفی هیچوقت رنگ نمی‌دهد، حتی اگر بعداً تصویر سالم شود
    expect(peekArtworkColor('/api/art/broken')).toBeNull()
  })

  it('re-attempts a failed cover once the negative TTL expires', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-01-01T00:00:00Z'))
    behaviour = 'error'
    await dominantColor('/api/art/broken')
    expect(created).toHaveLength(1)

    vi.setSystemTime(new Date('2026-01-01T00:02:00Z'))
    behaviour = 'load'
    expect(await dominantColor('/api/art/broken')).toEqual([120, 160, 200])
    expect(created).toHaveLength(2)
  })

  it('treats a missing 2d context as a cacheable failure', async () => {
    behaviour = 'no-context'
    expect(await dominantColor('/api/art/nocanvas')).toBeNull()
    expect(await dominantColor('/api/art/nocanvas')).toBeNull()
    expect(created).toHaveLength(1)
  })

  it('evicts the least recently used entry at the cache ceiling', async () => {
    const urls = Array.from({ length: 129 }, (_, i) => `/api/art/${i}`)
    for (const url of urls) await dominantColor(url)
    expect(artworkColorCacheSize()).toBe(128)
    expect(peekArtworkColor(urls[0])).toBeNull()
    expect(peekArtworkColor(urls[128])).toEqual([120, 160, 200])
  })

  it('keeps a re-read entry alive by moving it to the most-recent slot', async () => {
    const urls = Array.from({ length: 128 }, (_, i) => `/api/art/${i}`)
    for (const url of urls) await dominantColor(url)
    // خواندنِ دوباره‌ی قدیمی‌ترین، آن را از eviction نجات می‌دهد
    expect(peekArtworkColor(urls[0])).toEqual([120, 160, 200])
    await dominantColor('/api/art/extra')
    expect(peekArtworkColor(urls[0])).toEqual([120, 160, 200])
    expect(peekArtworkColor(urls[1])).toBeNull()
  })

  it('drops everything on clearArtworkColorCache', async () => {
    await dominantColor('/api/art/aa')
    expect(artworkColorCacheSize()).toBe(1)
    clearArtworkColorCache()
    expect(artworkColorCacheSize()).toBe(0)
    expect(peekArtworkColor('/api/art/aa')).toBeNull()
  })

  it('requests CORS only for a cross-origin cover', async () => {
    await dominantColor('/api/art/same-origin')
    await dominantColor('https://cdn.example.com/cover.jpg')
    expect(created).toEqual([
      { src: '/api/art/same-origin', crossOrigin: null },
      { src: 'https://cdn.example.com/cover.jpg', crossOrigin: 'anonymous' },
    ])
  })
})
