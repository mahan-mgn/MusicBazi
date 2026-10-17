// @vitest-environment jsdom
//
// منوی «منبع متن». مهم‌ترین چیزی که اینجا قفل می‌شود: **باز شدنِ منو هیچ
// درخواستی به Provider نمی‌زند** — فقط `GET /api/lyrics/sources`. پس هر
// fetchِ اضافه‌ای تست را می‌شکند.
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Track } from '../lib/types'
import LyricsSourceMenu from './LyricsSourceMenu'

const track: Track = {
  id: 'spotify:track:1',
  title: 'Song',
  artist: 'Artist',
  album: 'Album',
  durationMs: 180000,
  source: 'spotify',
  sourceUrl: 'https://example.test/1',
  artworkUrl: null,
  previewUrl: null,
}

const sourcesBody = {
  trackId: track.id,
  preferred: null,
  sources: [
    {
      id: 'lrclib',
      label: 'LRCLIB',
      capabilities: ['line'],
      in_auto_chain: true,
      selectable: true,
      status: 'available',
      experimental: false,
      unavailable_reason: null,
      terms_note: null,
      setup_hint: null,
    },
    {
      id: 'paxsenix',
      label: 'PaxSenix',
      capabilities: ['ttml'],
      in_auto_chain: false,
      selectable: true,
      status: 'cached',
      experimental: true,
      unavailable_reason: null,
      terms_note: null,
      setup_hint: null,
    },
    {
      id: 'genius',
      label: 'Genius',
      capabilities: ['plain'],
      in_auto_chain: false,
      selectable: false,
      status: 'needs_setup',
      experimental: false,
      unavailable_reason: 'needs_setup',
      terms_note: 'Terms prohibit scraping.',
      setup_hint: 'Set the token.',
    },
    {
      id: 'kugou',
      label: 'KuGou',
      capabilities: [],
      in_auto_chain: false,
      selectable: false,
      status: 'blocked',
      experimental: false,
      unavailable_reason: 'Requires bypassing the provider app authentication.',
      terms_note: 'Not implemented.',
      setup_hint: null,
    },
  ],
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

function render(props: Partial<Parameters<typeof LyricsSourceMenu>[0]> = {}) {
  act(() =>
    root.render(
      <LyricsSourceMenu
        track={track}
        current={null}
        onSelect={() => {}}
        {...props}
      />,
    ),
  )
}

function stubFetch(body: unknown, ok = true) {
  const calls: string[] = []
  vi.stubGlobal('fetch', (url: string) => {
    calls.push(String(url))
    return Promise.resolve({
      ok,
      json: () => Promise.resolve(body),
      text: () => Promise.resolve(''),
    })
  })
  return calls
}

async function tick() {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
  })
}

describe('LyricsSourceMenu', () => {
  it('opens the menu without contacting any provider', async () => {
    const calls = stubFetch(sourcesBody)
    render()

    act(() => {
      host.querySelector('button')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await tick()

    // تنها درخواست، فهرستِ منابع است
    expect(calls).toHaveLength(1)
    expect(calls[0]).toContain('/api/lyrics/sources')
    expect(calls[0]).not.toContain('stream/lyrics')
  })

  it('does not fetch anything before the menu is opened', () => {
    const calls = stubFetch(sourcesBody)

    render()

    expect(calls).toHaveLength(0)
  })

  it('lists selectable sources with their status', async () => {
    stubFetch(sourcesBody)
    render()

    act(() => {
      host.querySelector('button')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await tick()

    const text = host.textContent ?? ''
    expect(text).toContain('LRCLIB')
    expect(text).toContain('PaxSenix')
  })

  it('marks experimental sources', async () => {
    stubFetch(sourcesBody)
    render()

    act(() => {
      host.querySelector('button')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await tick()

    expect(host.textContent).toContain('آزمایشی')
  })

  it('shows unusable sources with a reason instead of hiding them', async () => {
    stubFetch(sourcesBody)
    render()

    act(() => {
      host.querySelector('button')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await tick()

    const text = host.textContent ?? ''
    expect(text).toContain('Genius')
    expect(text).toContain('KuGou')
    expect(text).toContain('غیرقابل استفاده')
  })

  it('offers the automatic option', async () => {
    stubFetch(sourcesBody)
    render({ current: 'lrclib' })

    act(() => {
      host.querySelector('button')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await tick()

    expect(host.textContent).toContain('خودکار')
  })

  it('calls onSelect with the provider id', async () => {
    stubFetch(sourcesBody)
    const onSelect = vi.fn()
    render({ onSelect })

    act(() => {
      host.querySelector('button')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await tick()

    const item = [...host.querySelectorAll('button')].find((b) =>
      b.textContent?.includes('LRCLIB'),
    )
    act(() => {
      item!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    expect(onSelect).toHaveBeenCalledWith('lrclib')
  })

  it('calls onSelect with an empty string for automatic', async () => {
    stubFetch(sourcesBody)
    const onSelect = vi.fn()
    render({ current: 'lrclib', onSelect })

    act(() => {
      host.querySelector('button')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await tick()

    const item = [...host.querySelectorAll('button')].find((b) =>
      b.textContent?.includes('خودکار'),
    )
    act(() => {
      item!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    expect(onSelect).toHaveBeenCalledWith('')
  })

  it('shows the current source on the trigger', () => {
    stubFetch(sourcesBody)

    render({ current: 'lrclib' })

    expect(host.querySelector('button')!.textContent).toContain('lrclib')
  })

  it('shows "automatic" when no source is chosen', () => {
    stubFetch(sourcesBody)

    render({ current: null })

    expect(host.querySelector('button')!.textContent).toContain('خودکار')
  })

  it('survives a failed sources request without crashing', async () => {
    stubFetch({}, false)
    render()

    act(() => {
      host.querySelector('button')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await tick()

    // منو باز است ولی فهرست خالی — بدونِ استثنا
    expect(host.textContent).toContain('خودکار')
  })

  it('survives a network error', async () => {
    vi.stubGlobal('fetch', () => Promise.reject(new Error('offline')))
    render()

    act(() => {
      host.querySelector('button')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await tick()

    expect(host.textContent).toContain('خودکار')
  })

  it('has an accessible trigger with the right ARIA state', () => {
    stubFetch(sourcesBody)
    render()

    const trigger = host.querySelector('button')!
    expect(trigger.getAttribute('aria-label')).toBe('منبع متن')
    expect(trigger.getAttribute('aria-haspopup')).toBe('menu')
    expect(trigger.getAttribute('aria-expanded')).toBe('false')

    act(() => {
      trigger.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    expect(host.querySelector('button')!.getAttribute('aria-expanded')).toBe('true')
  })

  it('exposes the menu role while open', async () => {
    stubFetch(sourcesBody)
    render()

    act(() => {
      host.querySelector('button')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await tick()

    expect(host.querySelector('[role="menu"]')).not.toBeNull()
  })

  it('marks the selected source with aria-checked', async () => {
    stubFetch(sourcesBody)
    render({ current: 'lrclib' })

    act(() => {
      host.querySelector('button')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await tick()

    const item = [...host.querySelectorAll('[role="menuitemradio"]')].find((b) =>
      b.textContent?.includes('LRCLIB'),
    )
    expect(item!.getAttribute('aria-checked')).toBe('true')
  })

  it('offers a retry action only when a source is active', async () => {
    stubFetch(sourcesBody)
    render({ current: null })

    act(() => {
      host.querySelector('button')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await tick()
    expect(host.textContent).not.toContain('تلاش دوباره')
  })

  it('calls onRetry when retry is pressed', async () => {
    stubFetch(sourcesBody)
    const onRetry = vi.fn()
    render({ current: 'lrclib', onRetry })

    act(() => {
      host.querySelector('button')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await tick()

    const item = [...host.querySelectorAll('button')].find((b) =>
      b.textContent?.includes('تلاش دوباره'),
    )
    act(() => {
      item!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    expect(onRetry).toHaveBeenCalled()
  })

  it('lists each provider only once even when mixed with unusable ones', async () => {
    stubFetch(sourcesBody)
    render()

    act(() => {
      host.querySelector('button')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await tick()

    const text = host.textContent ?? ''
    expect(text.split('LRCLIB').length - 1).toBe(1)
    expect(text.split('Genius').length - 1).toBe(1)
  })
})
