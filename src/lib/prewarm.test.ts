// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from './api'
import { _resetPrewarmCache, prewarmTrack } from './prewarm'
import type { Track } from './types'
import { useDownloads } from '../store/downloads'

vi.mock('./api', () => ({
  api: {
    prefetchStream: vi.fn().mockResolvedValue(true),
  },
}))

const makeTrack = (id: string): Track => ({
  id,
  title: `Title ${id}`,
  artist: 'Artist',
  durationMs: 200_000,
  artworkUrl: null,
  source: 'spotify',
  sourceUrl: `https://example.com/${id}`,
  previewUrl: null,
})

describe('prewarmTrack', () => {
  beforeEach(() => {
    _resetPrewarmCache()
    vi.clearAllMocks()
    useDownloads.setState({ jobs: [] })
  })

  it('triggers api.prefetchStream for a new track', () => {
    const track = makeTrack('t1')
    prewarmTrack(track, '320')

    expect(api.prefetchStream).toHaveBeenCalledTimes(1)
    expect(api.prefetchStream).toHaveBeenCalledWith(track, '320')
  })

  it('deduplicates rapid prewarm calls for the same track within TTL', () => {
    const track = makeTrack('t2')
    prewarmTrack(track)
    prewarmTrack(track)
    prewarmTrack(track)

    expect(api.prefetchStream).toHaveBeenCalledTimes(1)
  })

  it('skips prewarming if track is already downloaded in library', () => {
    const track = makeTrack('t-downloaded')
    useDownloads.setState({
      jobs: [
        {
          id: 'job-1',
          track,
          status: 'ready',
          streamUrl: '/downloads/job-1/stream',
        } as any,
      ],
    })

    prewarmTrack(track)
    expect(api.prefetchStream).not.toHaveBeenCalled()
  })

  it('handles api failure gracefully without throwing', () => {
    vi.mocked(api.prefetchStream!).mockRejectedValueOnce(new Error('Network offline'))
    const track = makeTrack('t-err')

    expect(() => prewarmTrack(track)).not.toThrow()
  })
})
