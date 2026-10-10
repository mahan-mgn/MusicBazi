import { describe, expect, it } from 'vitest'
import type { Track } from './types'
import { tracksFromSelectedDiscography } from './artistDiscography'

const makeTrack = (id: string, album: string, albumId?: string): Track => ({
  id,
  title: id,
  artist: 'Artist',
  album,
  albumId,
  durationMs: 180000,
  artworkUrl: null,
  source: 'spotify',
  sourceUrl: `https://example.com/${id}`,
  previewUrl: null,
})

describe('tracksFromSelectedDiscography', () => {
  it('orders tracks by the captured release order and starts at the selected track', () => {
    const tracks = [
      makeTrack('old-1', 'Old', 'release-old'),
      makeTrack('new-1', 'New', 'release-new'),
      makeTrack('old-2', 'Old', 'release-old'),
      makeTrack('new-2', 'New', 'release-new'),
    ]

    expect(
      tracksFromSelectedDiscography(
        tracks,
        [
          { id: 'release-new', title: 'New' },
          { id: 'release-old', title: 'Old' },
        ],
        'new-1',
      ).map((track) => track.id),
    ).toEqual(['new-1', 'new-2', 'old-1', 'old-2'])
  })

  it('matches releases by title when tracks do not have album ids', () => {
    const tracks = [makeTrack('a', 'Earlier'), makeTrack('b', 'Later')]
    expect(
      tracksFromSelectedDiscography(
        tracks,
        [
          { id: 'later-id', title: 'Later' },
          { id: 'earlier-id', title: 'Earlier' },
        ],
        'b',
      ).map((track) => track.id),
    ).toEqual(['b', 'a'])
  })

  it('uses platform disc and track numbers when API results are out of order', () => {
    const tracks = [
      { ...makeTrack('later-track', 'Selected', 'selected'), discNumber: 1, trackNumber: 2 },
      { ...makeTrack('first-track', 'Selected', 'selected'), discNumber: 1, trackNumber: 1 },
      { ...makeTrack('next-release', 'Later', 'later'), discNumber: 1, trackNumber: 1 },
    ]

    expect(
      tracksFromSelectedDiscography(
        tracks,
        [
          { id: 'selected', title: 'Selected' },
          { id: 'later', title: 'Later' },
        ],
        'first-track',
      ).map((track) => track.id),
    ).toEqual(['first-track', 'later-track', 'next-release'])
  })

  it('matches SoundCloud single releases by their track id', () => {
    const single = {
      ...makeTrack('sc:track:single-1', 'Single track', 'Unmatched metadata'),
      source: 'soundcloud' as const,
    }
    const later = {
      ...makeTrack('sc:track:single-2', 'Later track', 'Also unmatched'),
      source: 'soundcloud' as const,
    }

    expect(
      tracksFromSelectedDiscography(
        [later, single],
        [
          { id: single.id, title: 'Single' },
          { id: later.id, title: 'Later Single' },
        ],
        single.id,
      ).map((track) => track.id),
    ).toEqual([single.id, later.id])
  })

  it('filters out tracks from a different provider even when the release id matches', () => {
    const apple = { ...makeTrack('apple-track', 'Release', 'release'), source: 'apple' as const }
    const spotify = { ...makeTrack('spotify-track', 'Release', 'release'), source: 'spotify' as const }

    expect(
      tracksFromSelectedDiscography(
        [apple, spotify],
        [{ id: 'release', title: 'Release' }],
        'apple-track',
        'apple',
      ).map((track) => track.id),
    ).toEqual(['apple-track'])
  })

  it('returns no replacement queue when the selected track is absent', () => {
    expect(
      tracksFromSelectedDiscography(
        [makeTrack('a', 'Release', 'release')],
        [{ id: 'release', title: 'Release' }],
        'missing',
      ),
    ).toEqual([])
  })
})
