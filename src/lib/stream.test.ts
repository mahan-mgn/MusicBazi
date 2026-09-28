import { describe, expect, it } from 'vitest'
import { findBestJob, streamLyricsUrlFor, streamUrlFor, toPlayItem } from './stream'
import type { Track } from './types'

describe('stream utilities', () => {
  const mockTrack: Track = {
    id: 'spotify:track:123',
    title: 'Test Song',
    artist: 'Test Artist',
    album: 'Test Album',
    durationMs: 200000,
    source: 'spotify',
    sourceUrl: 'https://open.spotify.com/track/123',
    artworkUrl: 'https://example.com/art.jpg',
    previewUrl: null,
  }

  it('generates correct streamUrl for a track with quality', () => {
    const url = streamUrlFor(mockTrack, 'flac')
    expect(url).toContain('/api/stream?')
    expect(url).toContain('track_id=spotify%3Atrack%3A123')
    expect(url).toContain('title=Test+Song')
    expect(url).toContain('artist=Test+Artist')
    expect(url).toContain('duration_ms=200000')
    expect(url).toContain('quality=flac')
  })

  it('generates correct streamLyricsUrl for a track', () => {
    const url = streamLyricsUrlFor(mockTrack)
    expect(url).toContain('/api/stream/lyrics?')
    expect(url).toContain('track_id=spotify%3Atrack%3A123')
    expect(url).toContain('title=Test+Song')
  })

  it('toPlayItem returns local downloaded streamUrl when available', () => {
    const downloadedJob = {
      streamUrl: '/api/downloads/job-999/stream',
      lyricsUrl: '/api/downloads/job-999/lyrics',
      gainDb: -2.5,
    }
    const item = toPlayItem(mockTrack, downloadedJob)
    expect(item.id).toBe(mockTrack.id)
    expect(item.streamUrl).toBe('/api/downloads/job-999/stream')
    expect(item.lyricsUrl).toBe('/api/downloads/job-999/lyrics')
    expect(item.gainDb).toBe(-2.5)
  })

  it('toPlayItem returns online stream item when not downloaded', () => {
    const item = toPlayItem(mockTrack, null, '320')
    expect(item.id).toBe(`stream:${mockTrack.id}`)
    expect(item.streamUrl).toContain('/api/stream?')
    expect(item.streamUrl).toContain('quality=320')
    expect(item.lyricsUrl).toContain('/api/stream/lyrics?')
    expect(item.gainDb).toBeUndefined()
  })

  it('findBestJob selects highest quality job among multiple downloads', () => {
    const jobs = [
      { track: { id: mockTrack.id }, quality: '128', createdAt: 100 },
      { track: { id: mockTrack.id }, quality: '320', createdAt: 200 },
      { track: { id: mockTrack.id }, quality: 'flac', createdAt: 300 },
      { track: { id: 'other-track' }, quality: 'flac', createdAt: 400 },
    ]

    const best = findBestJob(jobs, mockTrack.id)
    expect(best).toBeDefined()
    expect(best?.quality).toBe('flac')
  })

  it('findBestJob respects preferredQuality if available', () => {
    const jobs = [
      { track: { id: mockTrack.id }, quality: '128', createdAt: 100 },
      { track: { id: mockTrack.id }, quality: '320', createdAt: 200 },
      { track: { id: mockTrack.id }, quality: 'flac', createdAt: 300 },
    ]

    const preferred = findBestJob(jobs, mockTrack.id, '320')
    expect(preferred?.quality).toBe('320')
  })
})
