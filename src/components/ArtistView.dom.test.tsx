// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../lib/api'
import type { AlbumDetail, ArtistDetail, Track } from '../lib/types'
import { useDownloads } from '../store/downloads'
import { usePlayer } from '../store/player'
import ArtistView from './ArtistView'

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

const createTrack = (id: string, title: string, albumTitle = 'Album 1'): Track => ({
  id,
  title,
  artist: 'Shervin Hajipour',
  album: albumTitle,
  durationMs: 200000,
  artworkUrl: 'https://example.com/cover.jpg',
  source: 'spotify',
  sourceUrl: `https://open.spotify.com/track/${id}`,
  previewUrl: null,
  explicit: false,
})

const mockArtist: ArtistDetail = {
  id: 'sp:artist:123',
  name: 'Shervin Hajipour',
  artworkUrl: 'https://example.com/shervin.jpg',
  source: 'spotify',
  sourceUrl: 'https://open.spotify.com/artist/123',
  subtitle: '1,500,000 monthly listeners',
  kind: 'artist',
  topTracks: [
    createTrack('1', 'Baraye'),
    createTrack('2', 'Cheshmhaat'),
    createTrack('3', 'Bahar Oomad'),
    createTrack('4', 'Telepathy'),
    createTrack('5', 'Pirehan'),
    createTrack('6', 'Ghol'),
    createTrack('7', 'Booseh'),
  ],
  albums: [
    {
      id: 'sp:album:1',
      title: 'Album 1',
      artist: 'Shervin Hajipour',
      year: 2023,
      trackCount: 10,
      artworkUrl: 'https://example.com/album1.jpg',
      source: 'spotify',
      sourceUrl: 'https://open.spotify.com/album/1',
    },
  ],
  playlists: [],
  likedTracks: [],
  repostedTracks: [],
  related: [],
}

describe('ArtistView', () => {
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
    useDownloads.setState({
      jobs: [],
    })
  })

  afterEach(() => {
    act(() => root.unmount())
    container.remove()
    useDownloads.setState({
      jobs: [],
    })
    vi.restoreAllMocks()
  })

  it('renders artist name, platform chip and metadata without a fake verified badge', () => {
    act(() => {
      root.render(
        <ArtistView
          artist={mockArtist}
          playingId={null}
          onTogglePlay={vi.fn()}
          onOpenAlbum={vi.fn()}
          onOpenPlaylist={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    expect(container.textContent).toContain('Shervin Hajipour')
    expect(container.textContent).not.toContain('هنرمند تأیید شده')
    expect(container.textContent).toContain('Spotify')
    expect(container.textContent).toContain('آهنگ‌های محبوب')

    // Check responsive centering classes on artist title
    const artistH1 = container.querySelector('h1')
    expect(artistH1?.classList.contains('bidi-hero')).toBe(true)
    expect(artistH1?.classList.contains('text-center')).toBe(true)
    expect(artistH1?.classList.contains('sm:text-start')).toBe(true)
  })

  it('shows the verified badge only when the platform said so', () => {
    act(() => {
      root.render(
        <ArtistView
          artist={{ ...mockArtist, verified: true }}
          playingId={null}
          onTogglePlay={vi.fn()}
          onOpenAlbum={vi.fn()}
          onOpenPlaylist={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    expect(container.textContent).toContain('هنرمند تأیید شده')
  })

  it('renders top 5 tracks initially and expands on show more click', () => {
    act(() => {
      root.render(
        <ArtistView
          artist={mockArtist}
          playingId={null}
          onTogglePlay={vi.fn()}
          onOpenAlbum={vi.fn()}
          onOpenPlaylist={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    // Initially top 5 tracks should be visible
    expect(container.textContent).toContain('Baraye')
    expect(container.textContent).toContain('Pirehan')
    // 6th and 7th tracks should not be visible yet
    expect(container.textContent).not.toContain('Ghol')
    expect(container.textContent).not.toContain('Booseh')

    // Find and click "نمایش بیشتر" button
    const showMoreBtn = Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('نمایش بیشتر'),
    )
    expect(showMoreBtn).toBeDefined()

    act(() => {
      showMoreBtn?.click()
    })

    // Now all 7 tracks should be visible
    expect(container.textContent).toContain('Ghol')
    expect(container.textContent).toContain('Booseh')
    expect(container.textContent).toContain('نمایش کمتر')
  })

  it('calls onOpenAlbum when album title in top tracks row is clicked', () => {
    const onOpenAlbum = vi.fn()
    act(() => {
      root.render(
        <ArtistView
          artist={mockArtist}
          playingId={null}
          onTogglePlay={vi.fn()}
          onOpenAlbum={onOpenAlbum}
          onOpenPlaylist={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    const albumLink = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent?.trim() === 'Album 1',
    )
    expect(albumLink).toBeDefined()

    act(() => {
      albumLink?.click()
    })

    expect(onOpenAlbum).toHaveBeenCalledWith(mockArtist.albums[0])
  })

  it('triggers shuffle play on shuffle button click', () => {
    act(() => {
      root.render(
        <ArtistView
          artist={mockArtist}
          playingId={null}
          onTogglePlay={vi.fn()}
          onOpenAlbum={vi.fn()}
          onOpenPlaylist={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    const shuffleBtn = container.querySelector('button[aria-label="پخش تصادفی"]') as HTMLButtonElement
    expect(shuffleBtn).toBeDefined()

    act(() => {
      shuffleBtn.click()
    })

    expect(usePlayer.getState().shuffle).toBe(true)
    expect(usePlayer.getState().queue.length).toBe(7)
  })

  it('renders Latest Release Spotlight card', () => {
    act(() => {
      root.render(
        <ArtistView
          artist={mockArtist}
          playingId={null}
          onTogglePlay={vi.fn()}
          onOpenAlbum={vi.fn()}
          onOpenPlaylist={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    expect(container.textContent).toContain('جدیدترین انتشار')
    expect(container.textContent).toContain('مشاهده اثر')
    expect(container.textContent).toContain('Album 1')
  })

  it('spotlights the newest SoundCloud release, not the most-played track', () => {
    const scArtist: ArtistDetail = {
      ...mockArtist,
      source: 'soundcloud',
      topTracks: [
        { ...createTrack('gonah', 'GONAH'), source: 'soundcloud' },
        { ...createTrack('wind', 'WIND'), source: 'soundcloud' },
      ],
      albums: [
        {
          id: 'sc:track:wind',
          title: 'WIND',
          artist: 'Dorcci',
          year: 2026,
          trackCount: 1,
          artworkUrl: 'https://example.com/wind.jpg',
          source: 'soundcloud',
          sourceUrl: 'https://soundcloud.com/dorcci/wind',
          releaseType: 'single',
        },
        {
          id: 'sc:playlist:1',
          title: 'YOUNG MORVARID',
          artist: 'Dorcci',
          year: 2025,
          trackCount: 12,
          artworkUrl: 'https://example.com/ym.jpg',
          source: 'soundcloud',
          sourceUrl: 'https://soundcloud.com/dorcci/sets/young-morvarid',
          releaseType: 'album',
        },
      ],
    }

    act(() => {
      root.render(
        <ArtistView
          artist={scArtist}
          playingId={null}
          onTogglePlay={vi.fn()}
          onOpenAlbum={vi.fn()}
          onOpenPlaylist={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    expect(container.textContent).toContain('جدیدترین انتشار')
    const spotlight = Array.from(container.querySelectorAll('h3')).find(
      (h) => h.textContent?.trim() === 'WIND',
    )
    expect(spotlight).toBeDefined()
    const card = spotlight?.closest('div.relative.overflow-hidden')
    expect(card?.textContent).toContain('WIND')
    expect(card?.textContent).not.toContain('YOUNG MORVARID')
    expect(card?.textContent).toContain('مشاهده اثر')
  })

  it('shows SoundCloud Top Tracks and puts uploads in Singles & EP', () => {
    const scArtist: ArtistDetail = {
      ...mockArtist,
      source: 'soundcloud',
      topTracks: [
        { ...createTrack('gonah', 'GONAH'), source: 'soundcloud' },
        { ...createTrack('wind', 'WIND'), source: 'soundcloud' },
      ],
      albums: [
        {
          id: 'sc:track:wind',
          title: 'WIND',
          artist: 'Dorcci',
          year: 2026,
          trackCount: 1,
          artworkUrl: null,
          source: 'soundcloud',
          sourceUrl: 'https://soundcloud.com/dorcci/wind',
          releaseType: 'single',
        },
        {
          id: 'sc:playlist:ep',
          title: 'NIGHT EP',
          artist: 'Dorcci',
          year: 2025,
          trackCount: 4,
          artworkUrl: null,
          source: 'soundcloud',
          sourceUrl: 'https://soundcloud.com/dorcci/sets/night-ep',
          releaseType: 'ep',
        },
        {
          id: 'sc:playlist:1',
          title: 'YOUNG MORVARID',
          artist: 'Dorcci',
          year: 2025,
          trackCount: 12,
          artworkUrl: null,
          source: 'soundcloud',
          sourceUrl: 'https://soundcloud.com/dorcci/sets/young-morvarid',
          releaseType: 'album',
        },
      ],
    }

    act(() => {
      root.render(
        <ArtistView
          artist={scArtist}
          playingId={null}
          onTogglePlay={vi.fn()}
          onOpenAlbum={vi.fn()}
          onOpenPlaylist={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    expect(container.textContent).toContain('محبوب‌ترین‌ها')
    expect(container.textContent).not.toContain('آهنگ‌های محبوب')

    const singlesChip = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent?.trim() === 'تک‌آهنگ‌ها و EP',
    )
    act(() => {
      singlesChip?.click()
    })
    expect(container.textContent).toContain('WIND')
    expect(container.textContent).toContain('NIGHT EP')
    expect(container.textContent).not.toContain('YOUNG MORVARID')

    const albumsChip = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent?.trim() === 'آلبوم‌ها',
    )
    act(() => {
      albumsChip?.click()
    })
    expect(container.textContent).toContain('YOUNG MORVARID')
    // WIND در محبوب‌ترین‌ها می‌ماند؛ فقط EP باید از دیسکوگرافی برود
    expect(container.textContent).not.toContain('NIGHT EP')
  })

  it('renders in your library section and triggers offline playback when jobs exist', () => {
    useDownloads.setState({
      jobs: [
        {
          id: 'job-ready-1',
          batchId: 'batch-1',
          track: mockArtist.topTracks[0],
          quality: 'original',
          status: 'ready',
          percent: 100,
          createdAt: Date.now(),
        },
      ],
    })

    act(() => {
      root.render(
        <ArtistView
          artist={mockArtist}
          playingId={null}
          onTogglePlay={vi.fn()}
          onOpenAlbum={vi.fn()}
          onOpenPlaylist={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    expect(container.textContent).toContain('در کتابخانه شما')
    expect(container.textContent).toContain('پخش آفلاین')

    const offlinePlayBtn = Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('پخش آفلاین'),
    )
    expect(offlinePlayBtn).toBeDefined()

    act(() => {
      offlinePlayBtn?.click()
    })

    expect(usePlayer.getState().queue.length).toBe(1)
    expect(usePlayer.getState().queue[0].track.id).toBe(mockArtist.topTracks[0].id)
  })

  it('does not mix offline tracks from another platform artist with the same name', () => {
    const otherArtistTrack: Track = {
      ...createTrack('dz:track:1', 'Different Baraye'),
      source: 'deezer',
      artistId: 'dz:artist:someone-else',
    }
    useDownloads.setState({
      jobs: [
        {
          id: 'job-other-artist',
          batchId: 'batch-other-artist',
          track: otherArtistTrack,
          quality: 'original',
          status: 'ready',
          percent: 100,
          createdAt: Date.now(),
        },
      ],
    })

    act(() => {
      root.render(
        <ArtistView
          artist={{ ...mockArtist, topTracks: [] }}
          playingId={null}
          onTogglePlay={vi.fn()}
          onOpenAlbum={vi.fn()}
          onOpenPlaylist={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    expect(container.textContent).not.toContain('در کتابخانه شما')
    expect(container.textContent).not.toContain('Different Baraye')
  })

  it('filters tracks and albums when searching in catalog', () => {
    act(() => {
      root.render(
        <ArtistView
          artist={mockArtist}
          playingId={null}
          onTogglePlay={vi.fn()}
          onOpenAlbum={vi.fn()}
          onOpenPlaylist={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    const searchInput = container.querySelector('input[type="text"]') as HTMLInputElement
    expect(searchInput).toBeDefined()

    act(() => {
      const nativeSetter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype,
        'value',
      )?.set
      nativeSetter?.call(searchInput, 'Baraye')
      searchInput.dispatchEvent(new Event('input', { bubbles: true }))
    })

    expect(container.textContent).toContain('Baraye')
    expect(container.textContent).not.toContain('Cheshmhaat')
  })

  it('switches discography view mode between grid and list', () => {
    act(() => {
      root.render(
        <ArtistView
          artist={mockArtist}
          playingId={null}
          onTogglePlay={vi.fn()}
          onOpenAlbum={vi.fn()}
          onOpenPlaylist={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    const listBtn = container.querySelector('button[aria-label="نمای فهرستی"]') as HTMLButtonElement
    expect(listBtn).toBeDefined()

    act(() => {
      listBtn.click()
    })

    // Now list view item is rendered
    expect(container.querySelector('button[aria-label="نمای فهرستی"]')?.classList.contains('bg-white/10')).toBe(true)
  })

  it('opens and closes about artist modal', () => {
    act(() => {
      root.render(
        <ArtistView
          artist={mockArtist}
          playingId={null}
          onTogglePlay={vi.fn()}
          onOpenAlbum={vi.fn()}
          onOpenPlaylist={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    const aboutBtn = container.querySelector('button[aria-label="درباره هنرمند"]') as HTMLButtonElement
    expect(aboutBtn).toBeDefined()

    act(() => {
      aboutBtn.click()
    })

    const dialog = container.querySelector('div[role="dialog"]')
    expect(dialog).not.toBeNull()
    expect(dialog?.textContent).toContain('Shervin Hajipour')
    expect(dialog?.textContent).toContain('monthly listeners')

    // Close button
    const closeBtn = dialog?.querySelector('button[aria-label="بستن"]') as HTMLButtonElement
    expect(closeBtn).toBeDefined()

    act(() => {
      closeBtn.click()
    })

    expect(container.querySelector('div[role="dialog"]')).toBeNull()
  })

  it('downloads a track from artist top tracks without crashing', () => {
    act(() => {
      root.render(
        <ArtistView
          artist={mockArtist}
          playingId={null}
          onTogglePlay={vi.fn()}
          onOpenAlbum={vi.fn()}
          onOpenPlaylist={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    const downloadBtn = container.querySelector('button[aria-label="دانلود Baraye"]') as HTMLButtonElement
    expect(downloadBtn).not.toBeNull()

    act(() => {
      downloadBtn.click()
    })

    expect(container.textContent).toContain('Baraye')
    expect(useDownloads.getState().jobs.some((j) => j.track.title === 'Baraye')).toBe(true)
  })

  it('starts playback immediately when Play All is clicked and responds to play/pause state', () => {
    const getAlbumSpy = vi.spyOn(api, 'getAlbum').mockResolvedValue({
      ...mockArtist.albums[0],
      durationMs: 400000,
      tracks: [],
    })

    act(() => {
      root.render(
        <ArtistView
          artist={mockArtist}
          playingId={null}
          onTogglePlay={vi.fn()}
          onOpenAlbum={vi.fn()}
          onOpenPlaylist={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    const playAllBtn = container.querySelector('button[aria-label="پخش همه"]') as HTMLButtonElement
    expect(playAllBtn).not.toBeNull()

    act(() => {
      playAllBtn.click()
    })

    expect(usePlayer.getState().queue.length).toBe(7)
    expect(usePlayer.getState().queue[0].track.title).toBe('Baraye')

    // Simulate playback active in player store
    act(() => {
      usePlayer.setState({ playing: true })
    })

    // Now button should show pause
    const pauseBtn = container.querySelector('button[aria-label="مکث"]') as HTMLButtonElement
    expect(pauseBtn).not.toBeNull()

    // Clicking pause should call pause on the player
    const pauseSpy = vi.spyOn(usePlayer.getState(), 'pause')
    act(() => {
      pauseBtn.click()
    })
    expect(pauseSpy).toHaveBeenCalled()

    getAlbumSpy.mockRestore()
  })

  it('expands queue in background with deduplicated discography tracks', async () => {
    const mockAlbumDetail: AlbumDetail = {
      ...mockArtist.albums[0],
      durationMs: 400000,
      tracks: [
        createTrack('album-baraye', 'Baraye - Album Version'), // duplicate of Baraye
        createTrack('album-new-song', 'New Song 1'), // new track
      ],
    }
    const getAlbumSpy = vi.spyOn(api, 'getAlbum').mockResolvedValue(mockAlbumDetail)

    act(() => {
      root.render(
        <ArtistView
          artist={mockArtist}
          playingId={null}
          onTogglePlay={vi.fn()}
          onOpenAlbum={vi.fn()}
          onOpenPlaylist={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    const playAllBtn = container.querySelector('button[aria-label="پخش همه"]') as HTMLButtonElement
    await act(async () => {
      playAllBtn.click()
      // Allow background promises to resolve
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(getAlbumSpy).toHaveBeenCalled()
    const queue = usePlayer.getState().queue
    // 7 top tracks + 1 new track (Baraye was deduplicated) = 8 tracks
    expect(queue.length).toBe(8)
    expect(queue.some((item) => item.track.title === 'New Song 1')).toBe(true)

    getAlbumSpy.mockRestore()
  })

  it('does not toggle shuffle off when it is already on', () => {
    usePlayer.setState({ shuffle: true })
    act(() => {
      root.render(
        <ArtistView
          artist={mockArtist}
          playingId={null}
          onTogglePlay={vi.fn()}
          onOpenAlbum={vi.fn()}
          onOpenPlaylist={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    const shuffleBtn = container.querySelector('button[aria-label="پخش تصادفی"]') as HTMLButtonElement
    act(() => {
      shuffleBtn.click()
    })

    expect(usePlayer.getState().shuffle).toBe(true)
  })

  it('keeps a Deezer album with unknown track count in the albums filter', () => {
    const deezerArtist: ArtistDetail = {
      ...mockArtist,
      source: 'deezer',
      albums: [
        {
          id: 'dz:album:1',
          title: 'YOUNG MORVARID',
          artist: 'Dorcci',
          year: 2025,
          trackCount: 0,
          artworkUrl: null,
          source: 'deezer',
          sourceUrl: 'https://www.deezer.com/album/1',
          releaseType: 'album',
        },
        {
          id: 'dz:album:2',
          title: 'EDGEBAR',
          artist: 'Dorcci',
          year: 2025,
          trackCount: 1,
          artworkUrl: null,
          source: 'deezer',
          sourceUrl: 'https://www.deezer.com/album/2',
          releaseType: 'single',
        },
      ],
    }

    act(() => {
      root.render(
        <ArtistView
          artist={deezerArtist}
          playingId={null}
          onTogglePlay={vi.fn()}
          onOpenAlbum={vi.fn()}
          onOpenPlaylist={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    const albumsChip = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent?.trim() === 'آلبوم‌ها',
    )
    act(() => {
      albumsChip?.click()
    })

    expect(container.textContent).toContain('YOUNG MORVARID')
    expect(container.textContent).not.toContain('EDGEBAR')
  })

  it('renders related artists and opens them', () => {
    const onOpenArtist = vi.fn()
    const related = {
      id: 'deezer:artist:99',
      name: 'Related Act',
      artworkUrl: null,
      source: 'deezer' as const,
      sourceUrl: 'https://www.deezer.com/artist/99',
      subtitle: 'هنرمند',
    }

    act(() => {
      root.render(
        <ArtistView
          artist={{ ...mockArtist, related: [related] }}
          playingId={null}
          onTogglePlay={vi.fn()}
          onOpenAlbum={vi.fn()}
          onOpenPlaylist={vi.fn()}
          onOpenArtist={onOpenArtist}
          onBack={vi.fn()}
        />,
      )
    })

    expect(container.textContent).toContain('هنرمندان مشابه')
    expect(container.textContent).toContain('Related Act')

    const card = Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('Related Act'),
    )
    act(() => {
      card?.click()
    })
    expect(onOpenArtist).toHaveBeenCalledWith(related)
  })

  it('does not show empty state when a SoundCloud user only has likes', () => {
    const scOnlyLikes: ArtistDetail = {
      ...mockArtist,
      source: 'soundcloud',
      topTracks: [],
      albums: [],
      playlists: [],
      likedTracks: [createTrack('liked-1', 'Liked Song')],
      repostedTracks: [],
    }

    act(() => {
      root.render(
        <ArtistView
          artist={scOnlyLikes}
          playingId={null}
          onTogglePlay={vi.fn()}
          onOpenAlbum={vi.fn()}
          onOpenPlaylist={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    expect(container.textContent).not.toContain('صفحه‌ی این هنرمند در دسترس نیست')
    expect(container.textContent).toContain('Liked Song')
    expect(container.textContent).toContain('لایک‌ها')
  })

  it('resets in-page search when the artist identity changes', () => {
    act(() => {
      root.render(
        <ArtistView
          artist={mockArtist}
          playingId={null}
          onTogglePlay={vi.fn()}
          onOpenAlbum={vi.fn()}
          onOpenPlaylist={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    const searchInput = container.querySelector('input[type="text"]') as HTMLInputElement
    act(() => {
      const nativeSetter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype,
        'value',
      )?.set
      nativeSetter?.call(searchInput, 'Baraye')
      searchInput.dispatchEvent(new Event('input', { bubbles: true }))
    })
    expect(container.textContent).not.toContain('Cheshmhaat')

    act(() => {
      root.render(
        <ArtistView
          artist={{ ...mockArtist, id: 'sp:artist:other', name: 'Other Artist' }}
          playingId={null}
          onTogglePlay={vi.fn()}
          onOpenAlbum={vi.fn()}
          onOpenPlaylist={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    expect((container.querySelector('input[type="text"]') as HTMLInputElement).value).toBe('')
    expect(container.textContent).toContain('Cheshmhaat')
  })

  it('renders pause button and toggles playback when latest release track is active', () => {
    const trackOnlyArtist: ArtistDetail = {
      ...mockArtist,
      albums: [],
      topTracks: [createTrack('single-1', 'Fresh Single')],
    }

    act(() => {
      root.render(
        <ArtistView
          artist={trackOnlyArtist}
          playingId="single-1"
          onTogglePlay={vi.fn()}
          onOpenAlbum={vi.fn()}
          onOpenPlaylist={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    // Latest release card is rendered for the track
    expect(container.textContent).toContain('جدیدترین انتشار')
    expect(container.textContent).toContain('Fresh Single')
    // When playing, the button should display pause
    const spotlightCard = container.querySelector('h3')?.closest('div.relative.overflow-hidden')
    expect(spotlightCard?.textContent).toContain('مکث')
  })

  it('allows clicking track title in ArtistTrackRow to trigger playback', () => {
    const onTogglePlay = vi.fn()
    act(() => {
      root.render(
        <ArtistView
          artist={mockArtist}
          playingId={null}
          onTogglePlay={onTogglePlay}
          onOpenAlbum={vi.fn()}
          onOpenPlaylist={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    const titleBtn = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent?.trim() === 'Baraye',
    )
    expect(titleBtn).toBeDefined()

    act(() => {
      titleBtn?.click()
    })

    expect(onTogglePlay).toHaveBeenCalledWith(mockArtist.topTracks[0])
  })

  it('navigates to album using track.albumId even when album is not in artist.albums', () => {
    const onOpenAlbum = vi.fn()
    const trackWithForeignAlbum: Track = {
      ...createTrack('rare-track', 'Rare Track', 'Unlisted Album'),
      albumId: 'itunes:album:999999',
    }

    act(() => {
      root.render(
        <ArtistView
          artist={{
            ...mockArtist,
            topTracks: [trackWithForeignAlbum],
            albums: [], // No albums listed
          }}
          playingId={null}
          onTogglePlay={vi.fn()}
          onOpenAlbum={onOpenAlbum}
          onOpenPlaylist={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    const albumLink = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent?.trim() === 'Unlisted Album',
    )
    expect(albumLink).toBeDefined()

    act(() => {
      albumLink?.click()
    })

    expect(onOpenAlbum).toHaveBeenCalledWith(
      expect.objectContaining({
        id: 'itunes:album:999999',
        title: 'Unlisted Album',
      }),
    )
  })

  it('directly loads SoundCloud singles in loadDiscography without calling api.getAlbum', async () => {
    const getAlbumSpy = vi.spyOn(api, 'getAlbum')
    const scArtistWithSingles: ArtistDetail = {
      ...mockArtist,
      source: 'soundcloud',
      topTracks: [createTrack('sc-1', 'Track 1')],
      albums: [
        {
          id: 'sc:track:single-1',
          title: 'Direct Single',
          artist: 'SoundCloud Artist',
          year: 2026,
          trackCount: 1,
          artworkUrl: 'https://example.com/single.jpg',
          source: 'soundcloud',
          sourceUrl: 'https://soundcloud.com/artist/direct-single',
          releaseType: 'single',
        },
      ],
    }

    act(() => {
      root.render(
        <ArtistView
          artist={scArtistWithSingles}
          playingId={null}
          onTogglePlay={vi.fn()}
          onOpenAlbum={vi.fn()}
          onOpenPlaylist={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    const playAllBtn = container.querySelector('button[aria-label="پخش همه"]') as HTMLButtonElement
    await act(async () => {
      playAllBtn.click()
      await Promise.resolve()
    })

    // api.getAlbum should NOT have been called for sc:track:single-1!
    expect(getAlbumSpy).not.toHaveBeenCalled()
    // The single should be present in queue
    expect(usePlayer.getState().queue.some((item) => item.track.title === 'Direct Single')).toBe(true)

    getAlbumSpy.mockRestore()
  })

  it('shows friendly empty message when discography filter has no releases', () => {
    const singlesOnlyArtist: ArtistDetail = {
      ...mockArtist,
      albums: [
        {
          id: 'sp:album:s1',
          title: 'Only Single',
          artist: 'Artist',
          year: 2024,
          trackCount: 1,
          artworkUrl: null,
          source: 'spotify',
          sourceUrl: 'https://open.spotify.com/album/s1',
          releaseType: 'single',
        },
      ],
    }

    act(() => {
      root.render(
        <ArtistView
          artist={singlesOnlyArtist}
          playingId={null}
          onTogglePlay={vi.fn()}
          onOpenAlbum={vi.fn()}
          onOpenPlaylist={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    const albumsChip = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent?.trim() === 'آلبوم‌ها',
    )
    act(() => {
      albumsChip?.click()
    })

    expect(container.textContent).toContain('هیچ آلبومی برای این هنرمند در دسترس نیست.')
  })

  it('matches Arabic and Persian letter variants in in-page search', () => {
    const persianArtist: ArtistDetail = {
      ...mockArtist,
      topTracks: [
        createTrack('p-1', 'یک قطعه با ی فارسی'),
      ],
    }

    act(() => {
      root.render(
        <ArtistView
          artist={persianArtist}
          playingId={null}
          onTogglePlay={vi.fn()}
          onOpenAlbum={vi.fn()}
          onOpenPlaylist={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    const searchInput = container.querySelector('input[type="text"]') as HTMLInputElement
    // Search with Arabic Yeh 'ي'
    act(() => {
      const nativeSetter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype,
        'value',
      )?.set
      nativeSetter?.call(searchInput, 'يك قطعه')
      searchInput.dispatchEvent(new Event('input', { bubbles: true }))
    })

    // Should still match 'یک قطعه'
    expect(container.textContent).toContain('یک قطعه با ی فارسی')
  })

  it('adapts About Artist modal for user kind and SoundCloud/Deezer metadata', () => {
    const scUser: ArtistDetail = {
      ...mockArtist,
      kind: 'user',
      source: 'soundcloud',
      albums: [],
      playlists: [
        {
          id: 'sc:playlist:p1',
          title: 'My Mix',
          owner: 'User',
          trackCount: 10,
          artworkUrl: null,
          source: 'soundcloud',
          sourceUrl: 'https://soundcloud.com/user/sets/p1',
        },
      ],
      likedTracks: [createTrack('liked-1', 'Liked Track')],
      repostedTracks: [createTrack('repost-1', 'Reposted Track')],
    }

    act(() => {
      root.render(
        <ArtistView
          artist={scUser}
          playingId={null}
          onTogglePlay={vi.fn()}
          onOpenAlbum={vi.fn()}
          onOpenPlaylist={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    const aboutBtn = container.querySelector('button[aria-label="درباره هنرمند"]') as HTMLButtonElement
    act(() => {
      aboutBtn.click()
    })

    const dialog = container.querySelector('div[role="dialog"]')
    expect(dialog).not.toBeNull()
    // Shows playlists count instead of albums for user
    expect(dialog?.textContent).toContain('پلی‌لیست‌ها')
    // Shows liked and reposted for soundcloud
    expect(dialog?.textContent).toContain('لایک‌ها')
    expect(dialog?.textContent).toContain('ریپست‌ها')
  })

  it('turns off shuffle when Play All is clicked if shuffle was previously on', () => {
    usePlayer.setState({
      queue: [],
      index: 0,
      playing: false,
      shuffle: true,
    })

    act(() => {
      root.render(
        <ArtistView
          artist={mockArtist}
          playingId={null}
          onTogglePlay={vi.fn()}
          onOpenAlbum={vi.fn()}
          onOpenPlaylist={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    const getAlbumSpy = vi.spyOn(api, 'getAlbum').mockResolvedValue({
      ...mockArtist.albums[0],
      durationMs: 400000,
      tracks: [],
    })

    const playAllBtn = container.querySelector('button[aria-label="پخش همه"]') as HTMLButtonElement
    expect(playAllBtn).not.toBeNull()

    act(() => {
      playAllBtn.click()
    })

    expect(usePlayer.getState().shuffle).toBe(false)
    expect(usePlayer.getState().index).toBe(0)

    getAlbumSpy.mockRestore()
  })

  it('loads artist top tracks when user had a single search track playing and clicks Play All', () => {
    // User had 1 track from search playing
    usePlayer.setState({
      queue: [{ id: '1', track: mockArtist.topTracks[0], streamUrl: 'https://example.com/single.mp3' }],
      index: 0,
      playing: true,
    })

    const getAlbumSpy = vi.spyOn(api, 'getAlbum').mockResolvedValue({
      ...mockArtist.albums[0],
      durationMs: 400000,
      tracks: [],
    })

    act(() => {
      root.render(
        <ArtistView
          artist={mockArtist}
          playingId="1"
          onTogglePlay={vi.fn()}
          onOpenAlbum={vi.fn()}
          onOpenPlaylist={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    const playAllBtn = container.querySelector('button[aria-label="پخش همه"]') as HTMLButtonElement
    expect(playAllBtn).not.toBeNull()

    act(() => {
      playAllBtn.click()
    })

    // Now queue should have all 7 top tracks
    expect(usePlayer.getState().queue.length).toBe(7)

    getAlbumSpy.mockRestore()
  })

  it('expands background discography for tracks without artistId or featuring artists', async () => {
    // Simulate YouTube/SoundCloud artist with tracks having artistId undefined or featuring artist
    const collabTrack: Track = {
      ...createTrack('yt-1', 'Collab Song'),
      artist: 'Shervin Hajipour & Friends',
      artistId: undefined,
    }
    const ytArtist: ArtistDetail = {
      ...mockArtist,
      source: 'youtube',
      topTracks: [collabTrack],
      albums: [
        {
          id: 'yt:playlist:1',
          title: 'Playlist 1',
          artist: 'Shervin Hajipour',
          year: 2024,
          trackCount: 2,
          artworkUrl: null,
          source: 'youtube',
          sourceUrl: 'https://youtube.com/playlist?list=1',
        },
      ],
    }

    const mockPlaylistDetail: AlbumDetail = {
      ...ytArtist.albums[0],
      durationMs: 300000,
      tracks: [
        collabTrack,
        { ...createTrack('yt-2', 'Solo Song'), artist: 'Shervin Hajipour', artistId: undefined },
      ],
    }
    const getAlbumSpy = vi.spyOn(api, 'getAlbum').mockResolvedValue(mockPlaylistDetail)

    act(() => {
      root.render(
        <ArtistView
          artist={ytArtist}
          playingId={null}
          onTogglePlay={vi.fn()}
          onOpenAlbum={vi.fn()}
          onOpenPlaylist={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    const playAllBtn = container.querySelector('button[aria-label="پخش همه"]') as HTMLButtonElement
    await act(async () => {
      playAllBtn.click()
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(getAlbumSpy).toHaveBeenCalled()
    // Should have both collabTrack and Solo Song
    const queue = usePlayer.getState().queue
    expect(queue.length).toBe(2)
    expect(queue.some((i) => i.track.title === 'Solo Song')).toBe(true)

    getAlbumSpy.mockRestore()
  })

  it('queues all music present on the artist page including topTracks, likedTracks, repostedTracks, and singles', () => {
    const scFullArtist: ArtistDetail = {
      ...mockArtist,
      source: 'soundcloud',
      topTracks: [createTrack('sc-top-1', 'Top Track 1')],
      likedTracks: [createTrack('sc-liked-1', 'Liked Track 1')],
      repostedTracks: [createTrack('sc-repost-1', 'Reposted Track 1')],
      albums: [
        {
          id: 'sc:track:single-1',
          title: 'Single 1',
          artist: 'Shervin Hajipour',
          year: 2024,
          trackCount: 1,
          artworkUrl: null,
          source: 'soundcloud',
          sourceUrl: 'https://soundcloud.com/shervin/single-1',
        },
      ],
      playlists: [],
    }

    act(() => {
      root.render(
        <ArtistView
          artist={scFullArtist}
          playingId={null}
          onTogglePlay={vi.fn()}
          onOpenAlbum={vi.fn()}
          onOpenPlaylist={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    const getAlbumSpy = vi.spyOn(api, 'getAlbum').mockResolvedValue({
      ...mockArtist.albums[0],
      durationMs: 400000,
      tracks: [],
    })

    const playAllBtn = container.querySelector('button[aria-label="پخش همه"]') as HTMLButtonElement
    expect(playAllBtn).not.toBeNull()

    act(() => {
      playAllBtn.click()
    })

    // Queue must immediately have all 4 tracks from topTracks, single, likedTracks, repostedTracks
    const queue = usePlayer.getState().queue
    expect(queue.length).toBe(4)
    expect(queue.some((i) => i.track.title === 'Top Track 1')).toBe(true)
    expect(queue.some((i) => i.track.title === 'Single 1')).toBe(true)
    expect(queue.some((i) => i.track.title === 'Liked Track 1')).toBe(true)
    expect(queue.some((i) => i.track.title === 'Reposted Track 1')).toBe(true)

    getAlbumSpy.mockRestore()
  })

  it('downloads all artist tracks using getArtistDiscography when available', async () => {
    const discoTracks = [
      createTrack('d-1', 'Track D1'),
      createTrack('d-2', 'Track D2'),
      createTrack('d-3', 'Track D3'),
    ]
    const discoSpy = vi.spyOn(api, 'getArtistDiscography').mockResolvedValue(discoTracks)

    act(() => {
      root.render(
        <ArtistView
          artist={mockArtist}
          playingId={null}
          onTogglePlay={vi.fn()}
          onOpenAlbum={vi.fn()}
          onOpenPlaylist={vi.fn()}
          onBack={vi.fn()}
        />,
      )
    })

    const downloadAllBtn = Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('دانلود همه') || b.textContent?.includes('Download all'),
    )
    expect(downloadAllBtn).toBeDefined()

    await act(async () => {
      downloadAllBtn?.click()
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(discoSpy).toHaveBeenCalled()
    expect(useDownloads.getState().jobs.some((j) => j.track.title === 'Track D1')).toBe(true)
    expect(useDownloads.getState().jobs.some((j) => j.track.title === 'Track D2')).toBe(true)
    expect(useDownloads.getState().jobs.some((j) => j.track.title === 'Track D3')).toBe(true)

    discoSpy.mockRestore()
  })
})
