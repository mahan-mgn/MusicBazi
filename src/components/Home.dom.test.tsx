// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Home from './Home'
import { useMoodChat } from '../store/moodChat'

// @ts-expect-error React act environment flag
globalThis.IS_REACT_ACT_ENVIRONMENT = true

class MockObserver {
  observe = vi.fn()
  unobserve = vi.fn()
  disconnect = vi.fn()
}
window.IntersectionObserver = MockObserver as unknown as typeof IntersectionObserver
window.ResizeObserver = MockObserver as unknown as typeof ResizeObserver

let host: HTMLDivElement
let root: Root

beforeEach(() => {
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  useMoodChat.setState({ open: false, pendingVibe: null })
})

afterEach(() => {
  act(() => root.unmount())
  host.remove()
  vi.restoreAllMocks()
})

interface RenderOpts {
  onOpenRef?: () => void
  onOpenLibrary?: () => void
  onFocusSearch?: () => void
  onSearch?: (q: string) => void
  onIdentify?: () => void
}

function renderHome(opts: RenderOpts = {}) {
  const onOpenRef = opts.onOpenRef ?? vi.fn()
  const onOpenLibrary = opts.onOpenLibrary ?? vi.fn()
  const onFocusSearch = opts.onFocusSearch ?? vi.fn()
  const onSearch = opts.onSearch ?? vi.fn()

  act(() => {
    root.render(
      <Home
        onOpenRef={onOpenRef}
        onOpenLibrary={onOpenLibrary}
        onFocusSearch={onFocusSearch}
        onSearch={onSearch}
        onIdentify={opts.onIdentify}
      />,
    )
  })

  return { host, onOpenRef, onOpenLibrary, onFocusSearch, onSearch }
}

describe('Home Hero', () => {
  it('بخش هیرو و لوگوهای ثابت پلتفرم‌ها را رندر می‌کند', () => {
    renderHome()

    // لوگوهای ۵ سرویس اصلی
    const sourceLogos = host.querySelectorAll('section ul li')
    expect(sourceLogos.length).toBe(5)

    // دکمه‌های حذف‌شده نباید در هیرو وجود داشته باشند
    const buttons = host.querySelectorAll('button')
    const buttonTexts = Array.from(buttons).map((b) => b.textContent?.trim() ?? '')
    expect(buttonTexts.some((t) => t.includes('جستجو یا چسباندن لینک'))).toBe(false)
    expect(buttonTexts.some((t) => t.includes('چسباندن لینک'))).toBe(false)
    expect(buttonTexts.some((t) => t.includes('شناسایی با صدا'))).toBe(false)
    expect(buttonTexts.some((t) => t.includes('چت حال‌وهوا'))).toBe(false)
  })
})
