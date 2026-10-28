import { describe, expect, it, vi } from 'vitest'
import { QueuePrefetcher, type QueuePrefetchItem } from './queuePrefetch'
import type { Quality, Track } from './types'

function item(id: string, quality = '320', online = true): QueuePrefetchItem {
  const track: Track = {
    id: `track-${id}`,
    title: `Track ${id}`,
    artist: 'Artist',
    durationMs: 180_000,
    artworkUrl: null,
    source: 'spotify',
    sourceUrl: `https://example.com/${id}`,
    previewUrl: null,
  }
  return {
    id: online ? `stream:${track.id}` : track.id,
    track,
    streamUrl: `/api/stream?track_id=${track.id}&quality=${quality}`,
  }
}

const flush = async () => {
  await new Promise((resolve) => setTimeout(resolve, 0))
}

describe('QueuePrefetcher', () => {
  it('prefetches up to 2 upcoming online items sequentially with at most one active request', async () => {
    const active: string[] = []
    let maxActive = 0
    const prefetch = vi.fn((track: Track) => {
      active.push(track.id)
      maxActive = Math.max(maxActive, active.length)
      return new Promise<void>((resolve) => {
        setTimeout(() => {
          active.splice(active.indexOf(track.id), 1)
          resolve()
        }, 10)
      })
    })
    const scheduler = new QueuePrefetcher(prefetch)

    scheduler.sync([item('current'), item('one'), item('two'), item('three')], 0)
    await new Promise((resolve) => setTimeout(resolve, 35))

    // Spotify-like behavior: 2 upcoming tracks in queue are prefetched sequentially!
    expect(prefetch.mock.calls.map(([track]) => track.id)).toEqual(['track-one', 'track-two'])
    expect(maxActive).toBe(1)
  })

  it('skips prefetching if upcoming items are local/downloaded', async () => {
    const prefetch = vi.fn(async (_track: Track) => {})
    const scheduler = new QueuePrefetcher(prefetch)

    scheduler.sync([item('current'), item('local1', '320', false), item('local2', '320', false)], 0)
    await flush()

    expect(prefetch).not.toHaveBeenCalled()
  })

  it('uses the queue item quality', async () => {
    const prefetch = vi.fn(async (_track: Track, _quality: Quality | null) => {})
    const scheduler = new QueuePrefetcher(prefetch)

    scheduler.sync([item('current'), item('next', 'flac')], 0)
    await flush()

    expect(prefetch.mock.calls.map(([track, quality]) => [track.id, quality])).toEqual([
      ['track-next', 'flac'],
    ])
  })

  it('includes wrapped tracks when repeat-all reaches the end of queue', async () => {
    const prefetch = vi.fn(async (_track: Track, _quality: Quality | null) => {})
    const scheduler = new QueuePrefetcher(prefetch)
    const queue = [item('one'), item('two'), item('current')]

    scheduler.sync(queue, 2, true)
    await flush()

    expect(prefetch.mock.calls.map(([track]) => track.id)).toEqual(['track-one', 'track-two'])
  })

  it('prioritizes the selected next item when shuffle is enabled', async () => {
    const prefetch = vi.fn(async (_track: Track, _quality: Quality | null) => {})
    const scheduler = new QueuePrefetcher(prefetch)
    const queue = [item('one'), item('current'), item('three'), item('four')]

    scheduler.sync(queue, 1, false, true, 3)
    await flush()

    expect(prefetch.mock.calls[0]?.[0].id).toBe('track-four')
  })

  it('prefetches step-by-step as playback advances one track at a time', async () => {
    const prefetch = vi.fn(async (_track: Track, _quality: Quality | null) => {})
    const scheduler = new QueuePrefetcher(prefetch)
    const queue = [item('one'), item('two'), item('three'), item('four')]

    scheduler.sync(queue, 0)
    await flush()
    expect(prefetch.mock.calls.map(([track]) => track.id)).toEqual(['track-two', 'track-three'])

    scheduler.sync(queue, 1)
    await flush()
    expect(prefetch.mock.calls.map(([track]) => track.id)).toEqual(['track-two', 'track-three', 'track-four'])

    scheduler.sync(queue, 2)
    await flush()
    expect(prefetch.mock.calls.map(([track]) => track.id)).toEqual(['track-two', 'track-three', 'track-four'])
  })

  it('respects disarm and trigger to wait until current track is playing', async () => {
    const prefetch = vi.fn(async (_track: Track) => {})
    const scheduler = new QueuePrefetcher(prefetch)

    scheduler.disarm()
    scheduler.sync([item('current'), item('next')], 0)
    await flush()
    expect(prefetch).not.toHaveBeenCalled()

    scheduler.trigger()
    await flush()
    expect(prefetch.mock.calls.map(([track]) => track.id)).toEqual(['track-next'])
  })
})
