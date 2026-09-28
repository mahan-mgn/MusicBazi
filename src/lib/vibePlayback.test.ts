import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('./api', () => ({
  api: {
    download: vi.fn(),
  },
}))

import { api } from './api'
import { itemFromJob, prefetchTracks } from './vibePlayback'
import type { Track } from './types'

function track(id: string): Track {
  return {
    id,
    title: id,
    artist: 'x',
    durationMs: 1,
    artworkUrl: null,
    source: 'deezer',
    sourceUrl: `https://example.com/${id}`,
    previewUrl: null,
  }
}

/** download را طوری می‌سازد که همان لحظه نتیجه بدهد — ready با streamUrl یا error */
function stubDownload(streamUrlFor: (t: Track) => string | null) {
  vi.mocked(api.download).mockImplementation((req, onProgress) => {
    const streamUrl = streamUrlFor(req.track)
    onProgress(
      streamUrl
        ? { status: 'ready', percent: 100, streamUrl }
        : { status: 'error', percent: 0, error: 'no source' },
    )
    return () => {}
  })
}

describe('itemFromJob', () => {
  it('keys the item by jobId so the same file keeps one identity', () => {
    const item = itemFromJob(track('t1'), { jobId: 'j9', streamUrl: '/api/downloads/j9/stream' })
    expect(item.id).toBe('lib-j9')
    expect(item.streamUrl).toBe('/api/downloads/j9/stream')
    expect(item.gainDb).toBe(0)
  })
})

describe('prefetchTracks', () => {
  afterEach(() => vi.clearAllMocks())

  it('never re-downloads a track the library already has', async () => {
    stubDownload(() => null)
    const done: string[] = []
    await prefetchTracks([track('a'), track('b')], '320', (t) =>
      t.id === 'a' ? { jobId: 'j1', streamUrl: '/api/downloads/j1/stream' } : null, (t, res) => {
      done.push(`${t.id}:${res.item ? 'ok' : 'fail'}:${res.jobId ?? '-'}`)
    })

    // فقط «b» باید دانلود شده باشد — «a» از قبل روی دیسک بود
    expect(vi.mocked(api.download)).toHaveBeenCalledTimes(1)
    expect(done).toContain('a:ok:j1')
  })

  it('reports the jobId of a freshly downloaded file', async () => {
    stubDownload((t) => `/api/downloads/j-${t.id}/stream`)
    const seen: Record<string, string | undefined> = {}

    await prefetchTracks([track('x')], '320', () => null, (t, res) => {
      seen[t.id] = res.jobId
    })

    expect(seen.x).toBe('j-x')
  })

  it('caps concurrent downloads', async () => {
    let live = 0
    let peak = 0
    vi.mocked(api.download).mockImplementation((req, onProgress) => {
      live++
      peak = Math.max(peak, live)
      setTimeout(() => {
        live--
        onProgress({ status: 'ready', percent: 100, streamUrl: `/api/downloads/j-${req.track.id}/stream` })
      }, 5)
      return () => {}
    })

    await prefetchTracks(Array.from({ length: 8 }, (_, i) => track(`t${i}`)), '320', () => null, () => {})

    expect(peak).toBeLessThanOrEqual(3)
  })

  it('keeps going after one track fails', async () => {
    stubDownload((t) => (t.id === 'bad' ? null : '/api/downloads/j/stream'))
    const results: Record<string, string> = {}

    await prefetchTracks([track('bad'), track('good')], '320', () => null, (t, res) => {
      results[t.id] = res.item ? 'ok' : res.error ?? 'fail'
    })

    expect(results.bad).toBe('no source')
    expect(results.good).toBe('ok')
  })
})
