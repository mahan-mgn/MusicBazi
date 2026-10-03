// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { usePlayer } from '../store/player'
import type { PlayItem } from '../store/player'
import NowPlaying from './NowPlaying'

vi.mock('../lib/audioEngine', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/audioEngine')>()
  return {
    ...actual,
    engine: {
      ...actual.engine,
      bassLevel: () => 0.5,
      currentTime: () => 0,
    },
  }
})

vi.mock('../lib/artColor', () => ({
  dominantColor: vi.fn().mockResolvedValue([100, 150, 200]),
  fallbackTint: vi.fn().mockReturnValue([100, 150, 200]),
  tidalBgColor: vi.fn().mockReturnValue('rgb(20, 30, 40)'),
  tintVars: vi.fn().mockReturnValue({ rgb: '100 150 200', strong: '#ffffff' }),
  deriveHarmonics: vi.fn().mockReturnValue({
    dominant: [100, 150, 200],
    secondary: [150, 100, 200],
    accent: [200, 150, 100],
    muted: [30, 40, 50],
  }),
}))

const mockTrackItem: PlayItem = {
  id: 'test-track-1',
  streamUrl: 'https://example.com/audio.mp3',
  lyricsUrl: 'https://example.com/lyrics.lrc',
  track: {
    id: 'track-1',
    title: 'Rollercoaster',
    artist: 'Alborz',
    album: 'High Altitude',
    albumId: 'album-1',
    durationMs: 134000,
    artworkUrl: 'https://example.com/art.jpg',
    source: 'soundcloud',
    sourceUrl: 'https://soundcloud.com/alborz/rollercoaster',
    previewUrl: null,
  },
}

let host: HTMLDivElement
let root: Root

beforeEach(() => {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: false,
    media: query,
    addEventListener() {},
    removeEventListener() {},
  }))
  document.documentElement.requestFullscreen = vi.fn().mockResolvedValue(undefined)
  document.exitFullscreen = vi.fn().mockResolvedValue(undefined)

  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)

  usePlayer.setState({
    queue: [mockTrackItem],
    index: 0,
    playing: true,
    position: 30,
    duration: 134,
    volume: 0.8,
    muted: false,
    repeat: 'off',
    shuffle: false,
  })
})

afterEach(() => {
  act(() => {
    root.unmount()
  })
  host.remove()
  vi.restoreAllMocks()
})

describe('NowPlaying component', () => {
  it('renders track title, artist and album link', () => {
    act(() => {
      root.render(<NowPlaying onClose={vi.fn()} />)
    })

    expect(host.textContent).toContain('Rollercoaster')
    expect(host.textContent).toContain('Alborz')
    expect(host.textContent).toContain('High Altitude')
  })

  it('dispatches musicbazi:open-artist event when clicking the artist name', () => {
    const artistListener = vi.fn()
    window.addEventListener('musicbazi:open-artist', artistListener)

    act(() => {
      root.render(<NowPlaying onClose={vi.fn()} />)
    })

    const artistBtn = Array.from(host.querySelectorAll('button')).find(
      (b) => b.textContent?.includes('Alborz'),
    )
    expect(artistBtn).toBeDefined()

    act(() => {
      artistBtn?.click()
    })

    expect(artistListener).toHaveBeenCalledTimes(1)
    const customEvent = artistListener.mock.calls[0][0] as CustomEvent
    expect(customEvent.detail).toEqual({ ref: 'Alborz' })

    window.removeEventListener('musicbazi:open-artist', artistListener)
  })

  it('dispatches musicbazi:open-album event when clicking the album name', () => {
    const albumListener = vi.fn()
    window.addEventListener('musicbazi:open-album', albumListener)

    act(() => {
      root.render(<NowPlaying onClose={vi.fn()} />)
    })

    const albumBtn = Array.from(host.querySelectorAll('button')).find(
      (b) => b.textContent?.includes('High Altitude'),
    )
    expect(albumBtn).toBeDefined()

    act(() => {
      albumBtn?.click()
    })

    expect(albumListener).toHaveBeenCalledTimes(1)
    const customEvent = albumListener.mock.calls[0][0] as CustomEvent
    expect(customEvent.detail).toEqual({ ref: 'album-1' })

    window.removeEventListener('musicbazi:open-album', albumListener)
  })

  it('toggles fullscreen mode when clicking fullscreen button', async () => {
    act(() => {
      root.render(<NowPlaying onClose={vi.fn()} />)
    })

    const fsBtn = Array.from(host.querySelectorAll('button')).find(
      (b) => b.getAttribute('aria-label') === 'تمام‌صفحه' || b.getAttribute('aria-label') === 'Full screen',
    )
    expect(fsBtn).toBeDefined()

    await act(async () => {
      fsBtn?.click()
    })

    expect(document.documentElement.requestFullscreen).toHaveBeenCalled()
  })

  it('navigates with artistId when present', () => {
    usePlayer.setState({
      queue: [
        {
          ...mockTrackItem,
          track: {
            ...mockTrackItem.track,
            artistId: 'sp:artist:12345',
          },
        },
      ],
      index: 0,
    })

    const artistListener = vi.fn()
    window.addEventListener('musicbazi:open-artist', artistListener)

    act(() => {
      root.render(<NowPlaying onClose={vi.fn()} />)
    })

    const artistBtn = Array.from(host.querySelectorAll('button')).find(
      (b) => b.textContent?.includes('Alborz'),
    )
    expect(artistBtn).toBeDefined()

    act(() => {
      artistBtn?.click()
    })

    expect(artistListener).toHaveBeenCalledWith(
      expect.objectContaining({
        detail: { ref: 'sp:artist:12345' },
      }),
    )

    window.removeEventListener('musicbazi:open-artist', artistListener)
  })

  it('handles track without lyricsUrl without perpetual loading', async () => {
    usePlayer.setState({
      queue: [
        {
          ...mockTrackItem,
          lyricsUrl: undefined,
        },
      ],
      index: 0,
    })

    act(() => {
      root.render(<NowPlaying onClose={vi.fn()} />)
    })

    // Lyrics button should not be present when lyricsUrl is undefined
    const lyricsBtn = Array.from(host.querySelectorAll('button')).find(
      (b) => b.getAttribute('aria-label') === 'متن آهنگ' || b.getAttribute('aria-label') === 'Lyrics',
    )
    expect(lyricsBtn).toBeUndefined()
  })

  it('renders audio quality badge and toggles quality menu on click', () => {
    act(() => {
      root.render(<NowPlaying onClose={vi.fn()} />)
    })

    const qualityBtn = Array.from(host.querySelectorAll('button')).find(
      (b) => b.getAttribute('aria-label') === 'انتخاب کیفیت' || b.getAttribute('aria-label') === 'Pick a quality',
    )
    expect(qualityBtn).toBeDefined()

    act(() => {
      qualityBtn?.click()
    })

    // Popover dialog opens
    const dialogs = host.querySelectorAll('[role="dialog"]')
    expect(dialogs.length).toBeGreaterThanOrEqual(1)
  })

  it('switches to lyrics panel when clicking lyrics button', () => {
    act(() => {
      root.render(<NowPlaying onClose={vi.fn()} />)
    })

    const lyricsBtn = Array.from(host.querySelectorAll('button')).find(
      (b) =>
        b.getAttribute('aria-label')?.includes('متن') ||
        b.getAttribute('aria-label')?.toLowerCase().includes('lyrics'),
    )
    expect(lyricsBtn).toBeDefined()

    act(() => {
      lyricsBtn?.click()
    })

    const updatedLyricsBtn = Array.from(host.querySelectorAll('button')).find(
      (b) =>
        b.getAttribute('aria-label')?.includes('متن') ||
        b.getAttribute('aria-label')?.toLowerCase().includes('lyrics'),
    )
    expect(updatedLyricsBtn?.getAttribute('aria-pressed')).toBe('true')
  })

  it('switches to queue panel when clicking queue button and multiple tracks exist', () => {
    usePlayer.setState({
      queue: [
        mockTrackItem,
        {
          ...mockTrackItem,
          id: 'test-track-2',
          track: { ...mockTrackItem.track, id: 'track-2', title: 'Next Song' },
        },
      ],
      index: 0,
    })

    act(() => {
      root.render(<NowPlaying onClose={vi.fn()} />)
    })

    const queueBtn = Array.from(host.querySelectorAll('button')).find(
      (b) => b.getAttribute('aria-label') === 'بعدی در صف' || b.getAttribute('aria-label') === 'Up next',
    )
    expect(queueBtn).toBeDefined()

    act(() => {
      queueBtn?.click()
    })

    const updatedQueueBtn = Array.from(host.querySelectorAll('button')).find(
      (b) => b.getAttribute('aria-label') === 'بعدی در صف' || b.getAttribute('aria-label') === 'Up next',
    )
    expect(updatedQueueBtn?.getAttribute('aria-pressed')).toBe('true')
    expect(host.textContent).toContain('Next Song')
  })

  it('renders explicit [E] badge when track.explicit is true', () => {
    usePlayer.setState({
      queue: [
        {
          ...mockTrackItem,
          track: { ...mockTrackItem.track, explicit: true },
        },
      ],
      index: 0,
    })

    act(() => {
      root.render(<NowPlaying onClose={vi.fn()} />)
    })

    const explicitBadge = host.querySelector('[title="Explicit"]')
    expect(explicitBadge).toBeDefined()
    expect(explicitBadge?.textContent).toBe('E')
  })

  it('renders artist initials in header', () => {
    act(() => {
      root.render(<NowPlaying onClose={vi.fn()} />)
    })

    // Alborz -> initial 'A' (TIDAL single-word initial rule)
    const initialBadge = Array.from(host.querySelectorAll('button')).find(
      (b) => b.textContent === 'A' && b.getAttribute('title') === 'Alborz',
    )
    expect(initialBadge).toBeDefined()
  })

  it('renders artist platform profile image in header button when artistArtworkUrl is present', () => {
    usePlayer.setState({
      queue: [
        {
          ...mockTrackItem,
          track: {
            ...mockTrackItem.track,
            artistArtworkUrl: 'https://example.com/artist-profile.jpg',
          },
        },
      ],
      index: 0,
    })

    act(() => {
      root.render(<NowPlaying onClose={vi.fn()} />)
    })

    const artistBadgeBtn = Array.from(host.querySelectorAll('button')).find(
      (b) => b.getAttribute('title') === 'Alborz' && b.querySelector('img'),
    )
    expect(artistBadgeBtn).toBeDefined()
    const img = artistBadgeBtn?.querySelector('img')
    expect(img?.getAttribute('src')).toBe('https://example.com/artist-profile.jpg')
  })

  it('renders add button (+) and toggles playlist picker on click', () => {
    act(() => {
      root.render(<NowPlaying onClose={vi.fn()} />)
    })

    const plusBtn = Array.from(host.querySelectorAll('button')).find(
      (b) => b.getAttribute('aria-label') === 'افزودن به پلی‌لیست' || b.getAttribute('aria-label') === 'Add to playlist',
    )
    expect(plusBtn).toBeDefined()

    act(() => {
      plusBtn?.click()
    })

    const menu = host.querySelector('[role="menu"]')
    expect(menu).toBeDefined()
  })

  it('renders with sheet-in and backdrop-in classes, and applies exit animation on dismiss', () => {
    vi.useFakeTimers()
    const onClose = vi.fn()
    act(() => {
      root.render(<NowPlaying onClose={onClose} initialTint={[50, 100, 150]} />)
    })

    const dialogEl = host.querySelector('[role="dialog"]')
    expect(dialogEl).toBeDefined()
    expect(dialogEl?.className).toContain('np-sheet-in')

    const minimizeBtn = Array.from(host.querySelectorAll('button')).find(
      (b) =>
        b.getAttribute('aria-label')?.includes('کوچک') ||
        b.getAttribute('aria-label')?.toLowerCase().includes('minimize'),
    )
    expect(minimizeBtn).toBeDefined()

    act(() => {
      minimizeBtn?.click()
    })

    expect(dialogEl?.className).toContain('np-sheet-out')
    expect(onClose).not.toHaveBeenCalled()

    act(() => {
      vi.advanceTimersByTime(300)
    })

    expect(onClose).toHaveBeenCalledTimes(1)
    vi.useRealTimers()
  })
})


