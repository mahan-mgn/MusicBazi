// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import Artwork from './Artwork'

// @ts-expect-error React act environment flag
globalThis.IS_REACT_ACT_ENVIRONMENT = true

/*
 * زنجیره‌ی فالبکِ کاور.
 *
 * هیرو `src`ش را از مسیرِ بلورِ سمتِ سرور می‌گیرد و آن مسیر تنبل ساخته می‌شود.
 * اگر پیش از آینه‌شدنِ کاورِ اصلی صدا زده شود ۴۰۴ می‌دهد. بدونِ فالبک، کلِ
 * هیرو به گرادیانِ سید می‌افتاد و کاورِ سالم هرگز امتحان نمی‌شد — این تست
 * همان رگرسیون را می‌گیرد.
 */
describe('Artwork image fallback', () => {
  let container: HTMLDivElement
  let root: Root

  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => root.unmount())
    container.remove()
  })

  const render = (props: Parameters<typeof Artwork>[0]) => {
    act(() => root.render(<Artwork {...props} />))
  }

  const img = () => container.querySelector('img')

  const failCurrent = () => {
    const el = img()
    if (!el) throw new Error('no <img> rendered to fail')
    act(() => {
      el.dispatchEvent(new Event('error'))
    })
  }

  it('وقتی src سالم است همان را می‌کشد', () => {
    render({ src: '/api/art/aaa', fallbackSrc: '/api/art/bbb', alt: 'x', seed: 's' })
    expect(img()?.getAttribute('src')).toBe('/api/art/aaa')
  })

  it('با شکستِ src به fallbackSrc می‌رود، نه به گرادیان', () => {
    render({ src: '/api/art-blur/aaa', fallbackSrc: '/api/art/aaa', alt: 'x', seed: 's' })
    failCurrent()
    expect(img()?.getAttribute('src')).toBe('/api/art/aaa')
  })

  it('با شکستِ هر دو، به گرادیانِ سید می‌افتد', () => {
    render({ src: '/api/art-blur/aaa', fallbackSrc: '/api/art/aaa', alt: 'x', seed: 's' })
    failCurrent()
    failCurrent()
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('[role="img"]')).not.toBeNull()
  })

  it('بدونِ fallbackSrc، شکستِ src مستقیم به گرادیان می‌رود', () => {
    render({ src: '/api/art/aaa', alt: 'x', seed: 's' })
    failCurrent()
    expect(container.querySelector('img')).toBeNull()
  })

  it('شکستِ src مانعِ امتحان‌شدنِ آدرسِ تازه در رندرِ بعدی نمی‌شود', () => {
    render({ src: '/api/art/aaa', alt: 'x', seed: 's' })
    failCurrent()
    expect(container.querySelector('img')).toBeNull()

    render({ src: '/api/art/zzz', alt: 'x', seed: 's' })
    expect(img()?.getAttribute('src')).toBe('/api/art/zzz')
  })
})
