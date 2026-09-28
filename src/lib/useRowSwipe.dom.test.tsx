// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { haptic } from './native'
import {
  shouldCommitRowSwipe,
  useRowSwipe,
  THRESHOLD,
  VELOCITY,
} from './useRowSwipe'

vi.mock('./native', () => ({
  haptic: {
    select: vi.fn(),
    medium: vi.fn(),
    tap: vi.fn(),
    success: vi.fn(),
    warn: vi.fn(),
  },
}))

describe('shouldCommitRowSwipe math helper', () => {
  it('اگر فاصله از آستانه بیشتر باشد، سوایپ ثبت می‌شود', () => {
    expect(shouldCommitRowSwipe(THRESHOLD, 0)).toBe(true)
    expect(shouldCommitRowSwipe(-THRESHOLD, 0)).toBe(true)
    expect(shouldCommitRowSwipe(THRESHOLD + 10, 0.1)).toBe(true)
  })

  it('اگر فاصله کمتر از آستانه و سرعت کم باشد، ثبت نمی‌شود', () => {
    expect(shouldCommitRowSwipe(THRESHOLD - 5, 0.2)).toBe(false)
    expect(shouldCommitRowSwipe(-30, -0.1)).toBe(false)
  })

  it('اگر سرعت پرتاب (flick) در جهت حرکت از حد نصاب بیشتر باشد، حتی با مسافت کم ثبت می‌شود', () => {
    expect(shouldCommitRowSwipe(35, VELOCITY + 0.1)).toBe(true)
    expect(shouldCommitRowSwipe(-35, -(VELOCITY + 0.1))).toBe(true)
  })

  it('اگر جهت سرعت خلاف جهت جابجایی باشد، ثبت نمی‌شود', () => {
    expect(shouldCommitRowSwipe(35, -(VELOCITY + 0.5))).toBe(false)
  })
})

describe('useRowSwipe DOM hook', () => {
  let host: HTMLDivElement
  let root: Root

  beforeEach(() => {
    // @ts-expect-error React act environment
    globalThis.IS_REACT_ACT_ENVIRONMENT = true
    host = document.createElement('div')
    document.body.appendChild(host)
    root = createRoot(host)
    document.documentElement.dir = 'rtl' // فارسی
    vi.clearAllMocks()
  })

  afterEach(() => {
    act(() => root.unmount())
    host.remove()
  })

  function TestComponent({
    onStartToEnd,
    onEndToStart,
    enabled = true,
  }: {
    onStartToEnd?: () => void
    onEndToStart?: () => void
    enabled?: boolean
  }) {
    const ref = useRowSwipe<HTMLDivElement>({ onStartToEnd, onEndToStart, enabled })
    return <div ref={ref} data-testid="row" style={{ width: '300px', height: '50px' }} />
  }

  it('اولویت را به اسکرول عمودی می‌دهد اگر dy >= dx باشد', () => {
    const onStartToEnd = vi.fn()
    act(() => {
      root.render(<TestComponent onStartToEnd={onStartToEnd} />)
    })

    const el = host.querySelector('[data-testid="row"]') as HTMLDivElement
    expect(el).not.toBeNull()

    // شروع لمس
    el.dispatchEvent(
      new TouchEvent('touchstart', {
        touches: [{ clientX: 100, clientY: 100 } as Touch],
      }),
    )

    // حرکت بیشتر عمودی (dy = 25, dx = 12)
    const moveEv = new TouchEvent('touchmove', {
      cancelable: true,
      touches: [{ clientX: 112, clientY: 125 } as Touch],
    })
    const prevented = !el.dispatchEvent(moveEv)

    expect(prevented).toBe(false) // نباید اسکرول صفحه لغو شود
    expect(el.style.transform).toBe('') // ردیف نباید جابجا شده باشد
  })

  it('در سوایپ افقی، استایل transform تغییر می‌کند و ویبره لمسی ثبت می‌شود', () => {
    const onStartToEnd = vi.fn()
    act(() => {
      root.render(<TestComponent onStartToEnd={onStartToEnd} />)
    })

    const el = host.querySelector('[data-testid="row"]') as HTMLDivElement

    el.dispatchEvent(
      new TouchEvent('touchstart', {
        touches: [{ clientX: 200, clientY: 100 } as Touch],
      }),
    )

    // حرکت افقی (dx = -70 یعنی در RTL از راست به چپ = Start to End)
    const moveEv = new TouchEvent('touchmove', {
      cancelable: true,
      touches: [{ clientX: 130, clientY: 100 } as Touch],
    })
    el.dispatchEvent(moveEv)

    expect(el.style.transform).toContain('translateX(-70px)')
    expect(haptic.select).toHaveBeenCalled()

    // پایان لمس و ثبت
    el.dispatchEvent(new TouchEvent('touchend'))
    expect(haptic.medium).toHaveBeenCalled()
    expect(onStartToEnd).toHaveBeenCalled()
  })

  it('کلیک متعاقب سوایپ را خنثی (swallow) می‌کند', () => {
    act(() => {
      root.render(<TestComponent />)
    })

    const el = host.querySelector('[data-testid="row"]') as HTMLDivElement

    el.dispatchEvent(
      new TouchEvent('touchstart', {
        touches: [{ clientX: 200, clientY: 100 } as Touch],
      }),
    )
    el.dispatchEvent(
      new TouchEvent('touchmove', {
        cancelable: true,
        touches: [{ clientX: 120, clientY: 100 } as Touch],
      }),
    )
    el.dispatchEvent(new TouchEvent('touchend'))

    // شبیه‌سازی کلیک بعد از رها کردن انگشت
    const clickEv = new MouseEvent('click', { cancelable: true, bubbles: true })
    const notPrevented = el.dispatchEvent(clickEv)
    expect(notPrevented).toBe(false)
  })
})
