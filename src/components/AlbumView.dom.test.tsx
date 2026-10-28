// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { peekArtworkColor } from '../lib/artColor'
import type { AlbumDetail, Track } from '../lib/types'
import { usePlayer } from '../store/player'
import AlbumView from './AlbumView'

// @ts-expect-error React act environment flag
globalThis.IS_REACT_ACT_ENVIRONMENT = true

// Mock ResizeObserver and IntersectionObserver for jsdom
class MockObserver {
  observe = vi.fn()
  unobserve = vi.fn()
  disconnect = vi.fn()
}
window.IntersectionObserver = MockObserver as unknown as typeof IntersectionObserver
window.ResizeObserver = MockObserver as unknown as typeof ResizeObserver
HTMLCanvasElement.prototype.getContext = vi.fn(() => null) as unknown as typeof HTMLCanvasElement.prototype.getContext
window.HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue(undefined)
window.HTMLMediaElement.prototype.pause = vi.fn()

/*
 * ماکِ جزئی، نه کامل: فقط کشِ رنگ کنترل می‌شود و `dominantColor` واقعی می‌ماند.
 * پس بقیه‌ی تست‌های این فایل همان مسیرِ «استخراج نشد» را می‌روند (بومِ این‌جا
 * `null` برمی‌گرداند) و بلوکِ تم می‌تواند مسیرِ «رنگ از قبل معلوم است» را
 * مستقل از canvas بسنجد.
 */
vi.mock('../lib/artColor', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/artColor')>()
  return { ...actual, peekArtworkColor: vi.fn(() => null) }
})

const mockTrack: Track = {
  id: 'sp:track:123',
  title: 'Eshgh',
  artist: 'Dorcci & Ashkan Kagan',
  durationMs: 245000,
  artworkUrl: 'https://example.com/cover.jpg',
  source: 'apple',
  sourceUrl: 'https://music.apple.com/album/123?i=456',
  previewUrl: null,
  explicit: true,
}

const mockAlbum: AlbumDetail = {
  id: 'apple:album:123',
  title: 'Eshgh - Single',
  artist: 'Dorcci & Ashkan Kagan',
  year: 2023,
  artworkUrl: 'https://example.com/cover.jpg',
  trackCount: 1,
  durationMs: 245000,
  source: 'apple',
  sourceUrl: 'https://music.apple.com/album/123',
  tracks: [mockTrack],
}

describe('AlbumView', () => {
  let container: HTMLDivElement
  let root: Root

  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    usePlayer.setState({
      queue: [],
      index: 0,
      playing: false,
      shuffle: false,
    })
  })

  afterEach(() => {
    act(() => root.unmount())
    container.remove()
  })

  it('renders album title, artist, badges and metadata', () => {
    act(() => {
      root.render(
        <AlbumView
          album={mockAlbum}
          playingId={null}
          onTogglePlay={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    expect(container.textContent).toContain('Eshgh - Single')
    expect(container.textContent).toContain('Dorcci & Ashkan Kagan')
    expect(container.textContent).toContain('Eshgh')
    // Check for Explicit badge
    expect(container.textContent).toContain('E')

    // Check responsive centering classes on mobile vs desktop
    const heroMeta = container.querySelector('[data-album-hero-meta]')
    expect(heroMeta?.classList.contains('text-center')).toBe(true)
    expect(heroMeta?.classList.contains('sm:text-start')).toBe(true)

    const titleH1 = container.querySelector('h1')
    expect(titleH1?.classList.contains('bidi-hero')).toBe(true)
    expect(titleH1?.classList.contains('text-center')).toBe(true)
    expect(titleH1?.classList.contains('sm:text-start')).toBe(true)
  })

  it('renders play, shuffle, and action buttons', () => {
    act(() => {
      root.render(
        <AlbumView
          album={mockAlbum}
          playingId={null}
          onTogglePlay={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    // Play button
    const playBtn = container.querySelector('button[title*="پخش"]')
    expect(playBtn).not.toBeNull()

    // Back to results button
    expect(container.textContent).toContain('برگشت به نتایج')
  })

  it('toggles selection mode when clicking select multiple button', () => {
    act(() => {
      root.render(
        <AlbumView
          album={mockAlbum}
          playingId={null}
          onTogglePlay={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    // Before clicking select multiple, track checkbox is not visible
    expect(container.querySelector('button[role="checkbox"]')).toBeNull()

    // Click select multiple button
    const selectModeBtn = Array.from(container.querySelectorAll('button')).find(
      (btn) => btn.textContent?.includes('انتخاب چندتایی'),
    )
    expect(selectModeBtn).toBeDefined()

    act(() => {
      selectModeBtn?.click()
    })

    // Now checkbox should be visible
    expect(container.querySelector('button[role="checkbox"]')).not.toBeNull()
  })

  it('handles shuffle play click with multiple tracks', () => {
    const multiTrackAlbum: AlbumDetail = {
      ...mockAlbum,
      tracks: [
        mockTrack,
        { ...mockTrack, id: 'sp:track:456', title: 'Track 2' },
      ],
      trackCount: 2,
    }

    act(() => {
      root.render(
        <AlbumView
          album={multiTrackAlbum}
          playingId={null}
          onTogglePlay={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    const shuffleBtn = container.querySelector('button[title*="پخش تصادفی"]')
    expect(shuffleBtn).not.toBeNull()

    act(() => {
      ;(shuffleBtn as HTMLButtonElement)?.click()
    })

    expect(usePlayer.getState().shuffle).toBe(true)
    expect(usePlayer.getState().queue.length).toBe(2)
  })

  it('handles downloading a track from album view without crashing', () => {
    act(() => {
      root.render(
        <AlbumView
          album={mockAlbum}
          playingId={null}
          onTogglePlay={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    const downloadBtn = container.querySelector('button[aria-label="دانلود Eshgh"]') as HTMLButtonElement
    expect(downloadBtn).not.toBeNull()

    act(() => {
      downloadBtn.click()
    })

    expect(container.textContent).toContain('Eshgh')
  })

  it('shifts hero metadata away from the vinyl while this album is playing', () => {
    act(() => {
      root.render(
        <AlbumView
          album={mockAlbum}
          playingId={null}
          onTogglePlay={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    const idle = container.querySelector('[data-album-hero-meta]')
    expect(idle).not.toBeNull()
    expect(idle?.hasAttribute('data-playing')).toBe(false)
    expect(idle?.classList.contains('album-hero-meta')).toBe(true)

    act(() => {
      usePlayer.setState({
        queue: [{ id: mockTrack.id, track: mockTrack, streamUrl: 'https://example.com/a.mp3' }],
        index: 0,
        playing: true,
      })
    })

    const playing = container.querySelector('[data-album-hero-meta]')
    expect(playing?.hasAttribute('data-playing')).toBe(true)
  })

  it('clicking Play All turns off shuffle if previously on, and plays sequentially', () => {
    usePlayer.setState({
      queue: [],
      index: 0,
      playing: false,
      shuffle: true,
    })

    const multiTrackAlbum: AlbumDetail = {
      ...mockAlbum,
      tracks: [
        mockTrack,
        { ...mockTrack, id: 'sp:track:456', title: 'Track 2' },
      ],
      trackCount: 2,
    }

    act(() => {
      root.render(
        <AlbumView
          album={multiTrackAlbum}
          playingId={null}
          onTogglePlay={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    const playAllBtn = container.querySelector('button[title*="پخش"]') as HTMLButtonElement
    expect(playAllBtn).not.toBeNull()

    act(() => {
      playAllBtn.click()
    })

    expect(usePlayer.getState().shuffle).toBe(false)
    expect(usePlayer.getState().queue.length).toBe(2)
    expect(usePlayer.getState().index).toBe(0)
  })

  it('allows clicking track title button to toggle/play track', () => {
    const onTogglePlay = vi.fn()
    act(() => {
      root.render(
        <AlbumView
          album={mockAlbum}
          playingId={null}
          onTogglePlay={onTogglePlay}
          onBack={vi.fn()}
        />,
      )
    })

    const titleBtn = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent?.trim() === 'Eshgh',
    )
    expect(titleBtn).toBeDefined()

    act(() => {
      titleBtn?.click()
    })

    expect(onTogglePlay).toHaveBeenCalledWith(
      expect.objectContaining({
        id: mockTrack.id,
        title: 'Eshgh',
      }),
    )
  })

  it('replaces single search track queue with full album when Play All is clicked', () => {
    // User was listening to just 1 track from search results
    usePlayer.setState({
      queue: [{ id: 'sp:track:123', track: mockTrack, streamUrl: 'https://example.com/single.mp3' }],
      index: 0,
      playing: true,
    })

    const multiTrackAlbum: AlbumDetail = {
      ...mockAlbum,
      tracks: [
        mockTrack,
        { ...mockTrack, id: 'sp:track:456', title: 'Track 2' },
        { ...mockTrack, id: 'sp:track:789', title: 'Track 3' },
      ],
      trackCount: 3,
    }

    act(() => {
      root.render(
        <AlbumView
          album={multiTrackAlbum}
          playingId={mockTrack.id}
          onTogglePlay={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    // Click Play All button in hero
    const playAllBtn = container.querySelector('button[title*="پخش"]') as HTMLButtonElement
    expect(playAllBtn).not.toBeNull()

    act(() => {
      playAllBtn.click()
    })

    // Queue should now contain all 3 tracks of the album
    expect(usePlayer.getState().queue.length).toBe(3)
  })

  it('renders EmptyState when album has 0 tracks', () => {
    const emptyAlbum: AlbumDetail = {
      ...mockAlbum,
      tracks: [],
      trackCount: 0,
    }

    act(() => {
      root.render(
        <AlbumView
          album={emptyAlbum}
          playingId={null}
          onTogglePlay={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    expect(container.textContent).toContain('چیزی پیدا نشد')
  })

  /*
   * تمِ بر پایه‌ی تصویر.
   *
   * مالکیتِ توکن‌ها عوض شده: پس‌زمینه‌ی تمام‌صفحه در شل می‌نشیند تا ستون‌های
   * کناریِ `max-w-5xl` و کفِ صفحه را هم بگیرد. این ویو دیگر تم نمی‌سازد؛ فقط
   * مصرف‌کننده‌ی متغیرهایی است که با `@property … inherits: true` از شل به
   * این‌جا می‌رسند. عددهای خودِ تم و قراردادِ کنتراستش در
   * `lib/pageTheme.test.ts` و `App.pageTheme.dom.test.tsx` سنجیده می‌شوند.
   */
  describe('artwork theme', () => {
    const TOKENS = [
      '--tint-r', '--tint-g', '--tint-b',
      '--page-r', '--page-g', '--page-b',
      '--mesh1-r', '--mesh1-g', '--mesh1-b',
      '--mesh2-r', '--mesh2-g', '--mesh2-b',
      '--mesh3-r', '--mesh3-g', '--mesh3-b',
    ]

    const renderAlbum = (album: AlbumDetail) => {
      act(() => {
        root.render(
          <AlbumView album={album} playingId={null} onTogglePlay={vi.fn()} onBack={vi.fn()} />,
        )
      })
    }

    beforeEach(() => {
      vi.mocked(peekArtworkColor).mockReturnValue(null)
    })

    afterEach(() => {
      vi.mocked(peekArtworkColor).mockReturnValue(null)
    })

    /*
     * قفلِ «یک منبعِ حقیقت».
     *
     * اگر سه‌گانه‌ها هم روی ریشه‌ی ویو بنشینند و هم روی شل، کار می‌کند ولی دو
     * گذارِ موازی روی یک رنگ می‌افتد و مقادیر می‌توانند واگرا شوند — و
     * بدتر، تمِ این ویو روی صفحه‌ی بعدی باقی می‌ماند. این تست همان تفکیک را
     * قفل می‌کند: ویو هیچ توکنی ندارد.
     */
    it('owns no theme tokens of its own; the shell does', () => {
      renderAlbum(mockAlbum)

      const viewRoot = container.querySelector<HTMLElement>('.tint-page')
      expect(viewRoot).not.toBeNull()
      for (const token of TOKENS) {
        expect((viewRoot as HTMLElement).style.getPropertyValue(token)).toBe('')
      }
    })

    it('keeps the hero reading the inherited tokens and lays the text guard over it', () => {
      renderAlbum(mockAlbum)

      /*
       * گرادیانِ هیرو باید *خواننده‌ی* متغیرها بماند و هیچ رنگِ هاردکدِ قبلی
       * برنگردد؛ وگرنه با انتقالِ تم به شل، هیرو رنگِ ثابتِ قدیمی می‌گرفت.
       */
      const hero = container.querySelector<HTMLElement>('.tint-text-guard')?.parentElement
      expect(hero).not.toBeNull()
      const bg = (hero as HTMLElement).style.background
      expect(bg).toContain('var(--tint-r)')
      expect(bg).not.toMatch(/rgb\(\d+,\s*\d+,\s*\d+/)

      const guard = container.querySelector('.tint-text-guard')
      expect(guard).not.toBeNull()
      expect(guard?.getAttribute('aria-hidden')).toBe('true')
      expect(guard?.classList.contains('pointer-events-none')).toBe(true)
    })

    it('leaves the full-page background layer to the shell', () => {
      renderAlbum(mockAlbum)
      // لایه‌ی تمام‌صفحه این‌جا نیست؛ اگر کسی دوباره اضافه‌اش کند، دوتا می‌شود
      expect(container.querySelector('.page-tint')).toBeNull()
    })
  })
})
