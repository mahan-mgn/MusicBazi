import { describe, expect, it } from 'vitest'
import { fallbackTint, tidalBgColor, tintVars } from './artColor'

/** luminance معکوس‌شده از خروجیِ color-mixِ --pb-strong */
function strongLum(strong: string): number {
  const m = strong.match(
    /^color-mix\(in srgb, rgb\((\d+) (\d+) (\d+)\) (\d+)%/,
  )
  if (!m) throw new Error(`unexpected strong value: ${strong}`)
  const [, r, g, b, pct] = m
  const w = (100 - Number(pct)) / 100
  const mix = (c: number) => c + (255 - c) * w
  return (0.2126 * mix(+r) + 0.7152 * mix(+g) + 0.0722 * mix(+b)) / 255
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

