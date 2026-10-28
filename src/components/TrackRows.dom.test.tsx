// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Track } from '../lib/types'
import { useDownloads } from '../store/downloads'
import { usePlayer } from '../store/player'
import AlbumTrackRow from './AlbumTrackRow'
import ArtistTrackRow, { ARTIST_TRACK_GRID } from './ArtistTrackRow'
import TrackRow from './TrackRow'

// @ts-expect-error React act environment flag
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const mockTrack: Track = {
  id: 'sp:track:abc',
  title: 'Test Song',
  artist: 'Great Artist',
  album: 'Great Album',
  albumId: 'sp:album:xyz',
  durationMs: 210000,
  artworkUrl: 'https://example.com/cover.jpg',
  source: 'spotify',
  sourceUrl: 'https://open.spotify.com/track/abc',
  previewUrl: null,
  explicit: true,
}

describe('AlbumTrackRow & TrackRow interactions', () => {
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

  it('clicking track title in AlbumTrackRow calls onTogglePlay', () => {
    const onTogglePlay = vi.fn()
    act(() => {
      root.render(
        <AlbumTrackRow
          track={mockTrack}
          index={1}
          playingId={null}
          onTogglePlay={onTogglePlay}
        />,
      )
    })

    const titleBtn = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent?.trim() === 'Test Song',
    )
    expect(titleBtn).toBeDefined()

    act(() => {
      titleBtn?.click()
    })

    expect(onTogglePlay).toHaveBeenCalledWith(mockTrack)
  })

  it('AlbumTrackRow renders animated equalizer when playing and static when paused', () => {
    usePlayer.setState({
      queue: [{ id: mockTrack.id, track: mockTrack, streamUrl: 'https://example.com/stream' }],
      index: 0,
      playing: true,
    })

    act(() => {
      root.render(
        <AlbumTrackRow
          track={mockTrack}
          index={1}
          playingId={mockTrack.id}
          onTogglePlay={vi.fn()}
        />,
      )
    })

    // Equalizer icon is present and animated
    let eqSvg = container.querySelector('svg.text-accent')
    expect(eqSvg).not.toBeNull()
    expect(container.querySelector('.wave-bar')).not.toBeNull()

    // Now pause player
    act(() => {
      usePlayer.setState({ playing: false })
    })

    // Equalizer icon is still present but static (wave-bar is absent)
    eqSvg = container.querySelector('svg.text-accent')
    expect(eqSvg).not.toBeNull()
    expect(container.querySelector('.wave-bar')).toBeNull()
  })

  it('clicking artwork or title in TrackRow triggers onTogglePlay', () => {
    const onTogglePlay = vi.fn()
    act(() => {
      root.render(
        <TrackRow
          track={mockTrack}
          playingId={null}
          onTogglePlay={onTogglePlay}
          showSource
        />,
      )
    })

    const titleBtn = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent?.trim() === 'Test Song',
    )
    expect(titleBtn).toBeDefined()

    act(() => {
      titleBtn?.click()
    })

    expect(onTogglePlay).toHaveBeenCalledWith(mockTrack)
  })

  it('TrackRow reflects playing state with accent styling', () => {
    usePlayer.setState({
      queue: [{ id: mockTrack.id, track: mockTrack, streamUrl: 'https://example.com/stream' }],
      index: 0,
      playing: true,
    })

    act(() => {
      root.render(
        <TrackRow
          track={mockTrack}
          playingId={mockTrack.id}
          onTogglePlay={vi.fn()}
        />,
      )
    })

    const row = container.querySelector('div.group')
    expect(row?.classList.contains('bg-accent/8')).toBe(true)
    expect(container.querySelector('span.text-accent')).not.toBeNull()
  })

  it('ArtistTrackRow uses ARTIST_TRACK_GRID for stable column alignment', () => {
    act(() => {
      root.render(
        <ArtistTrackRow
          track={mockTrack}
          index={1}
          playingId={null}
          onTogglePlay={vi.fn()}
        />,
      )
    })

    const row = container.querySelector('div.group')
    expect(row).not.toBeNull()
    for (const cls of ARTIST_TRACK_GRID.split(' ')) {
      expect(row?.classList.contains(cls)).toBe(true)
    }

    // Actions container has justify-self-end to keep actions cleanly at the column end
    const actionsDiv = row?.querySelector('.justify-self-end')
    expect(actionsDiv).not.toBeNull()
  })

  it('ArtistTrackRow preserves ARTIST_TRACK_GRID when track is downloaded with lyrics', () => {
    useDownloads.setState({
      jobs: [
        {
          id: 'job-1',
          batchId: 'batch-1',
          track: mockTrack,
          quality: '320',
          status: 'ready',
          percent: 100,
          format: 'mp3_320',
          fileUrl: 'https://example.com/audio.mp3',
          lyricsUrl: 'https://example.com/lyrics.lrc',
          createdAt: Date.now(),
        },
      ],
    })

    act(() => {
      root.render(
        <ArtistTrackRow
          track={mockTrack}
          index={1}
          playingId={null}
          onTogglePlay={vi.fn()}
        />,
      )
    })

    const row = container.querySelector('div.group')
    expect(row).not.toBeNull()
    for (const cls of ARTIST_TRACK_GRID.split(' ')) {
      expect(row?.classList.contains(cls)).toBe(true)
    }

    // Both lyrics link and download badge are present
    const lyricsLink = container.querySelector('a[href="https://example.com/lyrics.lrc"]')
    expect(lyricsLink).not.toBeNull()

    const downloadLink = container.querySelector('a[href="https://example.com/audio.mp3"]')
    expect(downloadLink).not.toBeNull()

    // Actions container maintains stable alignment classes
    const actionsDiv = row?.querySelector('.justify-self-end')
    expect(actionsDiv?.classList.contains('justify-end')).toBe(true)
  })
})
