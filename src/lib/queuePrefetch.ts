import type { Quality, Track } from './types'

export interface QueuePrefetchItem {
  id: string
  track: Track
  streamUrl: string
}

type Prefetch = (track: Track, quality: Quality | null) => Promise<void>

const MAX_CONCURRENT_PREFETCHES = 2

function qualityFor(item: QueuePrefetchItem): Quality | null {
  try {
    const url = new URL(item.streamUrl, 'http://musicbazi.local')
    return (url.searchParams.get('quality') as Quality | null) ?? null
  } catch {
    return null
  }
}

function keyFor(item: QueuePrefetchItem, quality: Quality | null): string {
  return `${item.track.id}\u0000${quality ?? ''}`
}

/**
 * Prepares upcoming online queue items in order, while limiting background
 * traffic and coalescing duplicate tracks/qualities within this player.
 */
export class QueuePrefetcher {
  private desired: Array<{ item: QueuePrefetchItem; quality: Quality | null; key: string }> = []
  private readonly inFlight = new Set<string>()
  private readonly ready = new Set<string>()
  private readonly failed = new Set<string>()

  constructor(private readonly prefetch: Prefetch) {}

  sync(
    queue: QueuePrefetchItem[],
    currentIndex: number,
    repeatAll = false,
    shuffle = false,
    immediateNextIndex: number | null = null,
  ): void {
    let upcoming: QueuePrefetchItem[]
    if (shuffle) {
      upcoming = [
        ...(immediateNextIndex !== null && immediateNextIndex !== currentIndex
          ? [queue[immediateNextIndex]]
          : []),
        ...queue.filter((_, index) => index !== currentIndex && index !== immediateNextIndex),
      ]
    } else {
      upcoming = [
        ...queue.slice(Math.max(0, currentIndex + 1)),
        ...(repeatAll && currentIndex > 0 ? queue.slice(0, currentIndex) : []),
      ]
    }
    const seen = new Set<string>()
    this.desired = upcoming
      .filter((item) => item.id.startsWith('stream:'))
      .map((item) => {
        const quality = qualityFor(item)
        return { item, quality, key: keyFor(item, quality) }
      })
      .filter(({ key }) => {
        if (seen.has(key)) return false
        seen.add(key)
        return true
      })

    const desiredKeys = new Set(this.desired.map(({ key }) => key))
    // Refresh the two closest files through the API on each queue advance.
    // A cache hit only updates its LRU timestamp, protecting likely next tracks
    // when a long queue would otherwise evict them before playback.
    for (const { key } of this.desired.slice(0, MAX_CONCURRENT_PREFETCHES)) {
      this.ready.delete(key)
    }
    for (const key of this.ready) {
      if (!desiredKeys.has(key)) this.ready.delete(key)
    }
    for (const key of this.failed) {
      if (!desiredKeys.has(key)) this.failed.delete(key)
    }
    this.pump()
  }

  private pump(): void {
    while (this.inFlight.size < MAX_CONCURRENT_PREFETCHES) {
      const next = this.desired.find(
        ({ key }) => !this.inFlight.has(key) && !this.ready.has(key) && !this.failed.has(key),
      )
      if (!next) return

      this.inFlight.add(next.key)
      void Promise.resolve()
        .then(() => this.prefetch(next.item.track, next.quality))
        .then(
          () => {
            if (this.desired.some(({ key }) => key === next.key)) this.ready.add(next.key)
          },
          () => {
            if (this.desired.some(({ key }) => key === next.key)) this.failed.add(next.key)
          },
        )
        .finally(() => {
          this.inFlight.delete(next.key)
          this.pump()
        })
    }
  }
}
