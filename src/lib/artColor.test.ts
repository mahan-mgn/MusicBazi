import { describe, expect, it } from 'vitest'
import { tidalBgColor, tintVars } from './artColor'

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

