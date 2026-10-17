import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  capabilityLabel,
  clearLyricsPreference,
  fetchLyricsPreference,
  fetchLyricsSources,
  saveLyricsPreference,
  streamLyricsUrlForProvider,
} from './lyricsSources'
import type { Track } from './types'

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

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function stub(response: unknown, ok = true) {
  const calls: { url: string; init?: RequestInit }[] = []
  vi.stubGlobal('fetch', (url: string, init?: RequestInit) => {
    calls.push({ url: String(url), init })
    return Promise.resolve({
      ok,
      json: () => Promise.resolve(response),
      text: () => Promise.resolve(''),
    })
  })
  return calls
}

describe('fetchLyricsSources', () => {
  it('returns the parsed body', async () => {
    stub({ trackId: 't', preferred: null, sources: [{ id: 'a' }] })

    const body = await fetchLyricsSources(track)

    expect(body?.sources[0].id).toBe('a')
  })

  it('sends the track identity and metadata', async () => {
    const calls = stub({ sources: [] })

    await fetchLyricsSources(track)

    expect(calls[0].url).toContain('track_id=spotify%3Atrack%3A1')
    expect(calls[0].url).toContain('title=Song')
    expect(calls[0].url).toContain('artist=Artist')
    expect(calls[0].url).toContain('duration_ms=180000')
  })

  it('forwards the optional hints when present', async () => {
    const calls = stub({ sources: [] })

    await fetchLyricsSources({ ...track, videoId: 'dQw4w9WgXcQ', isrc: 'US1234567890' })

    expect(calls[0].url).toContain('videoId=dQw4w9WgXcQ')
    expect(calls[0].url).toContain('isrc=US1234567890')
  })

  it('omits the hints when absent so the URL stays short', async () => {
    const calls = stub({ sources: [] })

    await fetchLyricsSources(track)

    expect(calls[0].url).not.toContain('videoId')
    expect(calls[0].url).not.toContain('isrc')
  })

  it('returns null on a non-ok response', async () => {
    stub({}, false)

    expect(await fetchLyricsSources(track)).toBeNull()
  })

  it('returns null on a network error', async () => {
    vi.stubGlobal('fetch', () => Promise.reject(new Error('offline')))

    expect(await fetchLyricsSources(track)).toBeNull()
  })

  it('returns null when the body has no sources array', async () => {
    stub({ trackId: 't' })

    expect(await fetchLyricsSources(track)).toBeNull()
  })
})

describe('preference endpoints', () => {
  it('reads the stored preference', async () => {
    stub({ provider: 'lrclib' })

    expect(await fetchLyricsPreference('t1')).toBe('lrclib')
  })

  it('returns null when there is no preference', async () => {
    stub({ provider: null })

    expect(await fetchLyricsPreference('t1')).toBeNull()
  })

  it('returns null on error', async () => {
    vi.stubGlobal('fetch', () => Promise.reject(new Error('offline')))

    expect(await fetchLyricsPreference('t1')).toBeNull()
  })

  it('saves a preference with PUT', async () => {
    const calls = stub({})

    const ok = await saveLyricsPreference('t1', 'lrclib')

    expect(ok).toBe(true)
    expect(calls[0].init?.method).toBe('PUT')
    expect(calls[0].url).toContain('provider=lrclib')
  })

  it('clears a preference with DELETE', async () => {
    const calls = stub({})

    const ok = await clearLyricsPreference('t1')

    expect(ok).toBe(true)
    expect(calls[0].init?.method).toBe('DELETE')
  })

  it('reports failure without throwing', async () => {
    stub({}, false)

    expect(await saveLyricsPreference('t1', 'x')).toBe(false)
    expect(await clearLyricsPreference('t1')).toBe(false)
  })
})

describe('streamLyricsUrlForProvider', () => {
  it('adds the provider parameter', () => {
    const url = streamLyricsUrlForProvider(track, 'unison')

    expect(url).toContain('/api/stream/lyrics?')
    expect(url).toContain('provider=unison')
    expect(url).toContain('track_id=spotify%3Atrack%3A1')
  })

  it('keeps the same track parameters as the automatic path', () => {
    const url = streamLyricsUrlForProvider(track, 'unison')

    expect(url).toContain('title=Song')
    expect(url).toContain('artist=Artist')
    expect(url).toContain('duration_ms=180000')
  })
})

describe('capabilityLabel', () => {
  it('prefers the richest capability', () => {
    expect(capabilityLabel(['line', 'word'])).toBe('word')
  })

  it('falls back through the list', () => {
    expect(capabilityLabel(['line'])).toBe('line')
    expect(capabilityLabel(['ttml'])).toBe('ttml')
  })

  it('defaults to plain', () => {
    expect(capabilityLabel([])).toBe('plain')
  })
})
