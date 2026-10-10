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
  it('prefetches every upcoming online item in order with at most two active requests', async () => {
    const pending: Array<() => void> = []
    const active: string[] = []
    let maxActive = 0
    const prefetch = vi.fn((track: Track) => {
      active.push(track.id)
      maxActive = Math.max(maxActive, active.length)
      return new Promise<void>((resolve) => {
        pending.push(() => {
          active.splice(active.indexOf(track.id), 1)
          resolve()
        })
      })
    })
    const scheduler = new QueuePrefetcher(prefetch)

    scheduler.sync([item('current'), item('one'), item('local', '320', false), item('two'), item('three')], 0)
    await flush()

    expect(prefetch.mock.calls.map(([track]) => track.id)).toEqual(['track-one', 'track-two'])
    expect(maxActive).toBe(2)

    pending.shift()?.()
    await flush()
    expect(prefetch.mock.calls.map(([track]) => track.id)).toEqual(['track-one', 'track-two', 'track-three'])
    expect(maxActive).toBe(2)
  })

  it('uses the queue item quality, deduplicates matching tracks, and continues after failure', async () => {
    const prefetch = vi.fn(async (track: Track, _quality: Quality | null) => {
      if (track.id === 'track-fails') throw new Error('unavailable')
    })
    const scheduler = new QueuePrefetcher(prefetch)

    scheduler.sync([item('current'), item('fails', 'flac'), item('fails', 'flac'), item('next', 'opus')], 0)
    await flush()
    await flush()

    expect(prefetch.mock.calls.map(([track, quality]) => [track.id, quality])).toEqual([
      ['track-fails', 'flac'],
      ['track-next', 'opus'],
    ])
  })

  it('includes earlier tracks when repeat-all wraps', async () => {
    const prefetch = vi.fn(async (_track: Track, _quality: Quality | null) => {})
    const scheduler = new QueuePrefetcher(prefetch)
    const queue = [item('one'), item('current'), item('three')]

    scheduler.sync(queue, 1, true)
    await flush()

    expect(prefetch.mock.calls.map(([track]) => track.id)).toEqual(['track-three', 'track-one'])
  })

  it('prioritizes the selected next item and includes all candidates when shuffle is enabled', async () => {
    const prefetch = vi.fn(async (_track: Track, _quality: Quality | null) => {})
    const scheduler = new QueuePrefetcher(prefetch)
    const queue = [item('one'), item('current'), item('three'), item('four')]

    scheduler.sync(queue, 1, false, true, 0)
    await flush()

    expect(prefetch.mock.calls.map(([track]) => track.id)).toEqual([
      'track-one',
      'track-three',
      'track-four',
    ])
  })

  it('uses the updated queue after an in-flight request completes', async () => {
    const pending = new Map<string, () => void>()
    const prefetch = vi.fn((track: Track) =>
      new Promise<void>((resolve) => pending.set(track.id, resolve)),
    )
    const scheduler = new QueuePrefetcher(prefetch)

    scheduler.sync([item('current'), item('old-one'), item('old-two'), item('removed')], 0)
    await flush()
    scheduler.sync([item('current'), item('new')], 0)
    pending.get('track-old-one')?.()
    await flush()

    expect(prefetch.mock.calls.map(([track]) => track.id)).toEqual([
      'track-old-one',
      'track-old-two',
      'track-new',
    ])
  })

  it('refreshes the nearest cached queue items as playback advances', async () => {
    const prefetch = vi.fn(async (_track: Track, _quality: Quality | null) => {})
    const scheduler = new QueuePrefetcher(prefetch)
    const queue = [item('one'), item('two'), item('three'), item('four')]

    scheduler.sync(queue, 0)
    await flush()
    scheduler.sync(queue, 1)
    await flush()

    expect(prefetch.mock.calls.map(([track]) => track.id)).toEqual([
      'track-two',
      'track-three',
      'track-four',
      'track-three',
      'track-four',
    ])
  })
})
