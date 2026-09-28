// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { LoadFailed } from './App'

/**
 * رگرسنِ «اسکلت ابدی»: شکستِ بارگذاریِ صفحه‌ی جزئیات باید پیامِ خطا را با
 * «تلاش دوباره» و راهِ فرار به خانه نشان بدهد — نه یک اسکنلتونِ تا-ابد.
 */
let host: HTMLDivElement
let root: Root

beforeEach(() => {
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
})
afterEach(() => {
  act(() => root.unmount())
  host.remove()
})

function render(text = 'بک‌اند ۵۰۲ داد') {
  const onRetry = vi.fn()
  const onHome = vi.fn()
  act(() => {
    root.render(<LoadFailed text={text} onRetry={onRetry} onHome={onHome} />)
  })
  return { onRetry, onHome }
}

const buttons = () => [...host.querySelectorAll<HTMLButtonElement>('button')]

describe('LoadFailed', () => {
  it('متنِ خطا و دو دکمه را نشان می‌دهد، هیچ اسکلتونی نه', () => {
    render()
    expect(host.textContent).toContain('بک‌اند ۵۰۲ داد')
    expect(buttons()).toHaveLength(2)
    expect(host.querySelector('.skeleton, [data-skeleton]')).toBeNull()
  })

  it('«تلاش دوباره» رتلاگ را صدا می‌زند و دکمه‌ی دوم به خانه می‌برد', () => {
    const { onRetry, onHome } = render()
    act(() => buttons()[0].click())
    act(() => buttons()[1].click())
    expect(onRetry).toHaveBeenCalledTimes(1)
    expect(onHome).toHaveBeenCalledTimes(1)
  })
})
