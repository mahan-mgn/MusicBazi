// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { LibraryItem } from '../lib/types'
import { usePlayer } from '../store/player'
import { LibraryRow, toPlayItem } from './LibraryRow'

window.HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue(undefined)
window.HTMLMediaElement.prototype.pause = vi.fn()

const mockItem: LibraryItem = {
  jobId: 'job-123',
  track: {
    id: 'track-123',
    title: 'Gole Yakh',
    artist: 'Kourosh Yaghmaei',
    artistId: 'sp:artist:kourosh',
    album: 'Back from the Brink',
    albumId: 'sp:album:backbrink',
    durationMs: 240000,
    artworkUrl: 'https://example.com/art.jpg',
    source: 'spotify',
    sourceUrl: 'https://open.spotify.com/track/123',
    previewUrl: null,
  },
  quality: '320',
  format: 'mp3',
  bytes: 5000000,
  fileUrl: '/api/files/123.mp3',
  streamUrl: '/api/stream/123',
  createdAt: 1700000000,
  playCount: 15,
}

let host: HTMLDivElement
let root: Root

beforeEach(() => {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  usePlayer.setState({ queue: [], index: 0, playing: false })
})

afterEach(() => {
  act(() => root.unmount())
  host.remove()
})

describe('LibraryRow', () => {
  it('کلیک روی نام هنرمند رویداد musicbazi:open-artist را با شناسه هنرمند می‌فرستد', () => {
    let capturedDetail: unknown = null
    const handler = (e: Event) => {
      capturedDetail = (e as CustomEvent).detail
    }
    window.addEventListener('musicbazi:open-artist', handler)

    act(() => {
      root.render(
        <LibraryRow
          item={mockItem}
          queue={[toPlayItem(mockItem)]}
          index={0}
          number={1}
          onRemove={() => {}}
          selectable={false}
          selected={false}
          onToggleSelect={() => {}}
        />,
      )
    })

    const artistBtn = host.querySelector('button[title*="Kourosh Yaghmaei"]') as HTMLButtonElement
    expect(artistBtn).not.toBeNull()
    act(() => {
      artistBtn.click()
    })

    expect(capturedDetail).toEqual({ ref: 'sp:artist:kourosh' })
    window.removeEventListener('musicbazi:open-artist', handler)
  })

  it('کلیک روی نام آلبوم رویداد musicbazi:open-album را با شناسه آلبوم می‌فرستد', () => {
    let capturedDetail: unknown = null
    const handler = (e: Event) => {
      capturedDetail = (e as CustomEvent).detail
    }
    window.addEventListener('musicbazi:open-album', handler)

    act(() => {
      root.render(
        <LibraryRow
          item={mockItem}
          queue={[toPlayItem(mockItem)]}
          index={0}
          number={1}
          onRemove={() => {}}
          selectable={false}
          selected={false}
          onToggleSelect={() => {}}
        />,
      )
    })

    const albumBtn = host.querySelector('button[title*="Back from the Brink"]') as HTMLButtonElement
    expect(albumBtn).not.toBeNull()
    act(() => {
      albumBtn.click()
    })

    expect(capturedDetail).toEqual({ ref: 'sp:album:backbrink' })
    window.removeEventListener('musicbazi:open-album', handler)
  })

  it('منوی سه نقطه شامل گزینه‌های «پخش بعدی» و «افزودن به صف» است و با کلیک فراخوانی می‌شوند', () => {
    const playNextSpy = vi.spyOn(usePlayer.getState(), 'playNext')
    const enqueueSpy = vi.spyOn(usePlayer.getState(), 'enqueue')

    act(() => {
      root.render(
        <LibraryRow
          item={mockItem}
          queue={[toPlayItem(mockItem)]}
          index={0}
          number={1}
          onRemove={() => {}}
          selectable={false}
          selected={false}
          onToggleSelect={() => {}}
        />,
      )
    })

    // دکمه منوی سه نقطه
    const dotsBtn = host.querySelector('button[aria-haspopup="menu"]') as HTMLButtonElement
    expect(dotsBtn).not.toBeNull()
    act(() => {
      dotsBtn.click()
    })

    // منوی بازشده در سند
    const menu = document.querySelector('[role="menu"]')
    expect(menu).not.toBeNull()

    const menuItems = Array.from(menu!.querySelectorAll('button[role="menuitem"]'))
    const playNextBtn = menuItems.find((b) => b.textContent?.includes('پخش بعدی')) as HTMLButtonElement
    const queueBtn = menuItems.find((b) => b.textContent?.includes('افزودن به صف')) as HTMLButtonElement

    expect(playNextBtn).toBeDefined()
    expect(queueBtn).toBeDefined()

    act(() => {
      playNextBtn.click()
    })
    expect(playNextSpy).toHaveBeenCalledWith([toPlayItem(mockItem)])

    // باز کردن مجدد برای تست دکمه صف
    act(() => {
      dotsBtn.click()
    })
    const menu2 = document.querySelector('[role="menu"]')
    const queueBtn2 = Array.from(menu2!.querySelectorAll('button[role="menuitem"]')).find(
      (b) => b.textContent?.includes('افزودن به صف'),
    ) as HTMLButtonElement

    act(() => {
      queueBtn2.click()
    })
    expect(enqueueSpy).toHaveBeenCalledWith([toPlayItem(mockItem)])
  })

  it('سوایپ افقی Start-to-End ترک را به صف پخش اضافه می‌کند', () => {
    document.documentElement.dir = 'rtl'
    const enqueueSpy = vi.spyOn(usePlayer.getState(), 'enqueue')

    act(() => {
      root.render(
        <LibraryRow
          item={mockItem}
          queue={[toPlayItem(mockItem)]}
          index={0}
          number={1}
          onRemove={() => {}}
          selectable={false}
          selected={false}
          onToggleSelect={() => {}}
        />,
      )
    })

    const row = host.querySelector('.hold-menu') as HTMLDivElement
    expect(row).not.toBeNull()

    // سوایپ از راست به چپ (dx = -75 در RTL)
    row.dispatchEvent(new TouchEvent('touchstart', { touches: [{ clientX: 200, clientY: 100 } as Touch] }))
    row.dispatchEvent(new TouchEvent('touchmove', { cancelable: true, touches: [{ clientX: 125, clientY: 100 } as Touch] }))
    row.dispatchEvent(new TouchEvent('touchend'))

    expect(enqueueSpy).toHaveBeenCalledWith([toPlayItem(mockItem)])
  })
})
