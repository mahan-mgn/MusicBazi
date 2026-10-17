import { describe, expect, it } from 'vitest'
import { isSheetLayout, placeMenu, type Rect } from './popoverPlacement'

const VIEWPORT = { width: 1200, height: 800 }

function rect(top: number, left: number, width = 100, height = 36): Rect {
  return { top, left, right: left + width, bottom: top + height, width, height }
}

describe('placeMenu', () => {
  it('opens below the anchor when there is room', () => {
    const p = placeMenu({
      anchor: rect(100, 300),
      menu: { width: 280, height: 300 },
      viewport: VIEWPORT,
    })

    expect(p.placement).toBe('bottom')
    expect(p.top).toBeGreaterThan(100)
  })

  it('flips above when there is no room below but room above', () => {
    // دکمه پایینِ صفحه است: پایین فقط ~۵۰px جا دارد
    const p = placeMenu({
      anchor: rect(740, 300),
      menu: { width: 280, height: 300 },
      viewport: VIEWPORT,
    })

    expect(p.placement).toBe('top')
    // لبهٔ پایینِ منو نباید از بالای دکمه پایین‌تر برود
    expect(p.top + p.maxHeight).toBeLessThanOrEqual(740)
  })

  it('picks the side with more room when neither fits', () => {
    // لنگر در وسطِ صفحه: فضاى بالا ۳۸۶ و پايين ۳۵۰ → بالا برنده است.
    // قاعده «بيشترين فضا» است، نه «هميشه پايين».
    const p = placeMenu({
      anchor: rect(400, 300),
      menu: { width: 280, height: 700 },
      viewport: VIEWPORT,
    })

    expect(p.placement).toBe('top')
  })

  it('stays below when the space below is genuinely larger', () => {
    // لنگر بالاتر: حالا پايين فضاى بيشترى دارد
    const p = placeMenu({
      anchor: rect(100, 300),
      menu: { width: 280, height: 700 },
      viewport: VIEWPORT,
    })

    expect(p.placement).toBe('bottom')
  })

  it('flips above when neither fits but above has more room', () => {
    const p = placeMenu({
      anchor: rect(600, 300),
      menu: { width: 280, height: 700 },
      viewport: VIEWPORT,
    })

    expect(p.placement).toBe('top')
  })

  it('never lets the menu extend past the bottom edge', () => {
    const p = placeMenu({
      anchor: rect(740, 300),
      menu: { width: 280, height: 600 },
      viewport: VIEWPORT,
    })

    expect(p.top + p.maxHeight).toBeLessThanOrEqual(VIEWPORT.height)
  })

  it('never lets the menu extend past the top edge', () => {
    const p = placeMenu({
      anchor: rect(20, 300),
      menu: { width: 280, height: 600 },
      viewport: VIEWPORT,
    })

    expect(p.top).toBeGreaterThanOrEqual(0)
  })

  it('caps the height so the content scrolls instead of being clipped', () => {
    const p = placeMenu({
      anchor: rect(100, 300),
      menu: { width: 280, height: 900 },
      viewport: VIEWPORT,
    })

    expect(p.maxHeight).toBeLessThan(900)
    expect(p.maxHeight).toBeGreaterThan(120)
  })

  it('keeps a very small space scrollable rather than overflowing', () => {
    // فضای بسیار کم از هر دو طرف: ارتفاعِ اجباری نباید منو را بیرون ببرد
    const p = placeMenu({
      anchor: rect(30, 300),
      menu: { width: 280, height: 400 },
      viewport: { width: 1200, height: 90 },
    })

    expect(p.top).toBeGreaterThanOrEqual(0)
    expect(p.top + p.maxHeight).toBeLessThanOrEqual(90)
  })

  it('clamps horizontally at the right edge', () => {
    const p = placeMenu({
      anchor: rect(100, 1150),
      menu: { width: 280, height: 300 },
      viewport: VIEWPORT,
    })

    expect(p.left + 280).toBeLessThanOrEqual(VIEWPORT.width)
  })

  it('clamps horizontally at the left edge', () => {
    const p = placeMenu({
      anchor: rect(100, 0),
      menu: { width: 280, height: 300 },
      viewport: VIEWPORT,
    })

    expect(p.left).toBeGreaterThanOrEqual(0)
  })

  it('aligns with the anchor by default', () => {
    const p = placeMenu({
      anchor: rect(100, 300),
      menu: { width: 280, height: 300 },
      viewport: VIEWPORT,
    })

    expect(p.left).toBe(300)
  })

  it('caps the height at 70 percent of the viewport', () => {
    const p = placeMenu({
      anchor: rect(10, 300),
      menu: { width: 280, height: 5000 },
      viewport: { width: 1200, height: 1000 },
    })

    expect(p.maxHeight).toBeLessThanOrEqual(700)
  })

  it('works in a narrow viewport', () => {
    const p = placeMenu({
      anchor: rect(400, 20, 60, 30),
      menu: { width: 300, height: 400 },
      viewport: { width: 320, height: 640 },
    })

    expect(p.left).toBeGreaterThanOrEqual(0)
    expect(p.left + 300).toBeLessThanOrEqual(320)
  })

  it('respects a custom margin and gap', () => {
    const p = placeMenu({
      anchor: rect(100, 300),
      menu: { width: 280, height: 100 },
      viewport: VIEWPORT,
      margin: 20,
      gap: 10,
    })

    expect(p.top).toBe(146)
  })
})

describe('isSheetLayout', () => {
  it('uses a sheet on phone widths', () => {
    expect(isSheetLayout(360)).toBe(true)
    expect(isSheetLayout(639)).toBe(true)
  })

  it('uses a popover from the breakpoint up', () => {
    expect(isSheetLayout(640)).toBe(false)
    expect(isSheetLayout(1440)).toBe(false)
  })
})
