// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { LibraryItem, LibraryPage } from '../lib/types'
import { usePlayer } from '../store/player'
import LibraryView from './LibraryView'

// @ts-expect-error React act environment flag
globalThis.IS_REACT_ACT_ENVIRONMENT = true

let observerCallbacks: ((entries: IntersectionObserverEntry[]) => void)[] = []

class MockObserver {
  constructor(cb: (entries: IntersectionObserverEntry[]) => void) {
    observerCallbacks.push(cb)
  }
  observe = vi.fn()
  unobserve = vi.fn()
  disconnect = vi.fn()
}
window.IntersectionObserver = MockObserver as unknown as typeof IntersectionObserver
window.ResizeObserver = MockObserver as unknown as typeof ResizeObserver
window.HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue(undefined)
window.HTMLMediaElement.prototype.pause = vi.fn()

const { mockPage } = vi.hoisted(() => {
  const items: LibraryItem[] = [
    {
      jobId: 'j1',
      track: {
        id: 't1',
        title: 'Track One',
        artist: 'Artist A',
        album: 'Album A',
        durationMs: 200000,
        artworkUrl: 'https://example.com/1.jpg',
        source: 'spotify',
        sourceUrl: 'https://spotify.com/1',
        previewUrl: null,
        energy: 0.8,
      },
      quality: '320',
      format: 'mp3',
      bytes: 4000000,
      fileUrl: '/1.mp3',
      streamUrl: '/1.mp3',
      createdAt: 1000,
      playCount: 15,
      lastPlayedAt: 1700001000,
    },
    {
      jobId: 'j2',
      track: {
        id: 't2',
        title: 'Track Two',
        artist: 'Artist B',
        album: 'Album B',
        durationMs: 220000,
        artworkUrl: 'https://example.com/2.jpg',
        source: 'youtube',
        sourceUrl: 'https://youtube.com/2',
        previewUrl: null,
        energy: 0.2,
      },
      quality: 'flac',
      format: 'flac',
      bytes: 25000000,
      fileUrl: '/2.flac',
      streamUrl: '/2.flac',
      createdAt: 2000,
      playCount: 10,
      lastPlayedAt: 1700002000,
    },
    {
      jobId: 'j3',
      track: {
        id: 't3',
        title: 'Track Three',
        artist: 'Artist C',
        album: 'Album C',
        durationMs: 180000,
        artworkUrl: 'https://example.com/3.jpg',
        source: 'soundcloud',
        sourceUrl: 'https://soundcloud.com/3',
        previewUrl: null,
      },
      quality: '192',
      format: 'mp3',
      bytes: 3000000,
      fileUrl: '/3.mp3',
      streamUrl: '/3.mp3',
      createdAt: 3000,
      playCount: 0,
      lastPlayedAt: undefined,
    },
    {
      jobId: 'j4',
      track: {
        id: 't4',
        title: 'Track Four',
        artist: 'Artist A',
        album: 'Album A',
        durationMs: 250000,
        artworkUrl: 'https://example.com/4.jpg',
        source: 'spotify',
        sourceUrl: 'https://spotify.com/4',
        previewUrl: null,
        energy: 0.9,
      },
      quality: 'flac',
      format: 'flac',
      bytes: 28000000,
      fileUrl: '/4.flac',
      streamUrl: '/4.flac',
      createdAt: 4000,
      playCount: 25,
      lastPlayedAt: 1700004000,
    },
    {
      jobId: 'j5',
      track: {
        id: 't5',
        title: 'Track Five',
        artist: 'Artist D',
        album: 'Album D',
        durationMs: 210000,
        artworkUrl: 'https://example.com/5.jpg',
        source: 'deezer',
        sourceUrl: 'https://deezer.com/5',
        previewUrl: null,
      },
      quality: '320',
      format: 'mp3',
      bytes: 5000000,
      fileUrl: '/5.mp3',
      streamUrl: '/5.mp3',
      createdAt: 5000,
      playCount: 8,
      lastPlayedAt: 1700005000,
    },
  ]

  const page: LibraryPage = {
    items,
    total: items.length,
    totalBytes: items.reduce((acc, x) => acc + x.bytes, 0),
  }

  return { mockPage: page }
})

vi.mock('../lib/api', () => ({
  api: {
    library: vi.fn().mockResolvedValue(mockPage),
    favorites: vi.fn().mockResolvedValue([]),
    removeFromLibrary: vi.fn().mockResolvedValue(undefined),
    recordPlay: vi.fn().mockResolvedValue(undefined),
  },
  API_MODE: 'http',
}))

let host: HTMLDivElement
let root: Root

beforeEach(() => {
  observerCallbacks = []
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  usePlayer.setState({ queue: [], index: 0, playing: false })
})

afterEach(() => {
  act(() => root.unmount())
  host.remove()
})

describe('LibraryView ارتقایافته', () => {
  it('نوار چیپ‌های فیلتر سریع (همه، منابع، Lossless، پخش‌نشده) را رندر می‌کند', async () => {
    await act(async () => {
      root.render(<LibraryView />)
    })

    const buttons = Array.from(host.querySelectorAll('button'))
    const allBtn = buttons.find((b) => b.textContent?.trim() === 'همه')
    const spotifyBtn = buttons.find((b) => b.textContent?.includes('Spotify'))
    const losslessBtn = buttons.find((b) => b.textContent?.includes('کیفیت بالا (FLAC)'))
    const unplayedBtn = buttons.find((b) => b.textContent?.includes('پخش‌نشده'))

    expect(allBtn).toBeDefined()
    expect(spotifyBtn).toBeDefined()
    expect(losslessBtn).toBeDefined()
    expect(unplayedBtn).toBeDefined()
  })

  it('فیلتر با چیپ منبع، فقط ترک‌های همان منبع را نگه می‌دارد', async () => {
    await act(async () => {
      root.render(<LibraryView />)
    })

    const buttons = Array.from(host.querySelectorAll('button'))
    const spotifyBtn = buttons.find((b) => b.textContent?.includes('Spotify'))!

    await act(async () => {
      spotifyBtn.click()
    })

    expect(host.textContent).toContain('Track One')
    expect(host.textContent).toContain('Track Four')
    expect(host.textContent).not.toContain('Track Two') // YouTube
    expect(host.textContent).not.toContain('Track Three') // SoundCloud
  })

  it('فیلتر با چیپ کیفیت بالا (FLAC) فقط ترک‌های Lossless را نمایش می‌دهد', async () => {
    await act(async () => {
      root.render(<LibraryView />)
    })

    const buttons = Array.from(host.querySelectorAll('button'))
    const losslessBtn = buttons.find((b) => b.textContent?.includes('کیفیت بالا (FLAC)'))!

    await act(async () => {
      losslessBtn.click()
    })

    expect(host.textContent).toContain('Track Two') // FLAC
    expect(host.textContent).toContain('Track Four') // FLAC
    expect(host.textContent).not.toContain('Track One') // MP3 320
  })

  it('فیلتر با چیپ پخش‌نشده فقط ترک‌های بدون پلی را نشان می‌دهد', async () => {
    await act(async () => {
      root.render(<LibraryView />)
    })

    const buttons = Array.from(host.querySelectorAll('button'))
    const unplayedBtn = buttons.find((b) => b.textContent?.includes('پخش‌نشده'))!

    await act(async () => {
      unplayedBtn.click()
    })

    expect(host.textContent).toContain('Track Three') // playCount 0
    expect(host.textContent).not.toContain('Track One') // playCount 15
  })

  it('قفسه هوشمند «بیشترین پخش» هنگام وجود ۴ ترک یا بیشتر پخش‌شده نمایش داده می‌شود', async () => {
    await act(async () => {
      root.render(<LibraryView />)
    })

    // j1 (15), j2 (10), j4 (25), j5 (8) are >= 4 tracks with playCount > 0
    expect(host.textContent).toContain('بیشترین پخش')
    expect(host.textContent).toContain('آهنگ‌هایی که بیشتر از همه گوش داده‌اید')
  })

  it('در حالت انتخاب گروهی، دکمه‌های «پخش بعدی» و «افزودن به صف» کار می‌کنند', async () => {
    const playNextSpy = vi.spyOn(usePlayer.getState(), 'playNext')
    const enqueueSpy = vi.spyOn(usePlayer.getState(), 'enqueue')

    await act(async () => {
      root.render(<LibraryView />)
    })

    // ورود به حالت انتخاب
    const selectToggleBtn = host.querySelector('button[title*="انتخاب چندتایی"]') as HTMLButtonElement
    expect(selectToggleBtn).not.toBeNull()
    await act(async () => {
      selectToggleBtn.click()
    })

    // انتخاب همه
    const selectAllBtn = Array.from(host.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('انتخاب همه'),
    ) as HTMLButtonElement
    expect(selectAllBtn).toBeDefined()
    await act(async () => {
      selectAllBtn.click()
    })

    // کلیک روی پخش بعدی
    const bulkPlayNextBtn = Array.from(host.querySelectorAll('button')).find(
      (b) => b.getAttribute('title') === 'پخش بعدی',
    ) as HTMLButtonElement
    expect(bulkPlayNextBtn).toBeDefined()
    await act(async () => {
      bulkPlayNextBtn.click()
    })
    expect(playNextSpy).toHaveBeenCalled()
    expect(playNextSpy.mock.calls[0][0].length).toBe(5)

    // کلیک روی افزودن به صف
    const bulkQueueBtn = Array.from(host.querySelectorAll('button')).find(
      (b) => b.getAttribute('title') === 'افزودن به صف',
    ) as HTMLButtonElement
    expect(bulkQueueBtn).toBeDefined()
    await act(async () => {
      bulkQueueBtn.click()
    })
    expect(enqueueSpy).toHaveBeenCalled()
    expect(enqueueSpy.mock.calls[0][0].length).toBe(5)
  })

  it('با اسکرول به پایین و خروج هدر اصلی از صفحه، نوار فشرده سرصفحه فعال می‌شود', async () => {
    await act(async () => {
      root.render(<LibraryView />)
    })

    // تحریک خروج هدر اصلی از کادر
    await act(async () => {
      observerCallbacks.forEach((cb) => cb([{ isIntersecting: false } as IntersectionObserverEntry]))
    })

    // بررسی وجود نوار فشرده با کلاس grid-rows-[1fr]
    const compactBar = host.querySelector('.grid-rows-\\[1fr\\]')
    expect(compactBar).not.toBeNull()
    expect(compactBar?.textContent).toContain('کتابخانه')
    expect(compactBar?.textContent).toContain('آهنگ‌ها')
  })
})
