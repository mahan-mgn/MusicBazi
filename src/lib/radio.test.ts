import { describe, expect, it } from 'vitest'
import { normalizeTrackTitle, pickRadioTrack, radioKey, trackDedupeKey } from './radio'
import type { Track } from './types'

function track(id: string, title: string, artist = 'Farhad Mehrad'): Track {
  return {
    id,
    title,
    artist,
    durationMs: 180_000,
    artworkUrl: null,
    source: 'deezer',
    sourceUrl: `https://example.com/${id}`,
    previewUrl: null,
  }
}

describe('radioKey', () => {
  it('normalizes case and surrounding whitespace', () => {
    expect(radioKey(track('a', '  Gonjeshkak ', ' Farhad Mehrad '))).toBe(
      radioKey(track('b', 'gonjeshkak', 'farhad mehrad')),
    )
  })

  it('treats different titles as different keys', () => {
    expect(radioKey(track('a', 'Gonjeshkak'))).not.toBe(radioKey(track('b', 'Saghf')))
  })
})

describe('pickRadioTrack', () => {
  it('returns null for an empty pool', () => {
    expect(pickRadioTrack([], new Set())).toBeNull()
  })

  it('returns null once every track in the pool is excluded', () => {
    const pool = [track('a', 'Gonjeshkak'), track('b', 'Saghf')]
    const exclude = new Set(pool.map(radioKey))
    expect(pickRadioTrack(pool, exclude)).toBeNull()
  })

  it('only picks from tracks not in exclude', () => {
    const pool = [track('a', 'Gonjeshkak'), track('b', 'Saghf'), track('c', 'Avar')]
    const exclude = new Set([radioKey(pool[0]), radioKey(pool[1])])
    const picked = pickRadioTrack(pool, exclude)
    expect(picked?.id).toBe('c')
  })
})

describe('normalizeTrackTitle', () => {
  it('strips release tags like - Single, - EP, (Remastered)', () => {
    expect(normalizeTrackTitle('Baraye - Single')).toBe('baraye')
    expect(normalizeTrackTitle('Baraye (Single Version)')).toBe('baraye')
    expect(normalizeTrackTitle('Song - Remastered 2021')).toBe('song')
    expect(normalizeTrackTitle('Track (Album Version)')).toBe('track')
  })

  it('preserves artistic tags like Remix and Acoustic', () => {
    expect(normalizeTrackTitle('Baraye (Remix)')).toBe('baraye (remix)')
    expect(normalizeTrackTitle('Song (Acoustic Version)')).toBe('song (acoustic version)')
  })
})

describe('trackDedupeKey', () => {
  it('deduplicates a single release against an album track', () => {
    const single = track('1', 'Baraye - Single', 'Shervin Hajipour')
    const albumTrack = track('2', 'Baraye', 'Shervin Hajipour')
    expect(trackDedupeKey(single)).toBe(trackDedupeKey(albumTrack))
  })
})
