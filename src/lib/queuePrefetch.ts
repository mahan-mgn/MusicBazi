import type { Quality, Track } from './types'

export interface QueuePrefetchItem {
  id: string
  track: Track
  streamUrl: string
}

type Prefetch = (track: Track, quality: Quality | null) => Promise<void>

const MAX_CONCURRENT_PREFETCHES = 1

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
 * Prepares upcoming online queue items Spotify-style:
 * - Depth = 2: Prefetches the next 2 upcoming tracks in queue sequentially.
 * - Single concurrency: At most 1 background download/warm at any time so the currently playing
 *   track is never starved of bandwidth.
 * - Gated trigger: Armed once the current track is actively playing, disarmed while starting.
 */
export class QueuePrefetcher {
  private desired: Array<{ item: QueuePrefetchItem; quality: Quality | null; key: string }> = []
  private readonly inFlight = new Set<string>()
  private readonly ready = new Set<string>()
  private readonly failed = new Set<string>()
  private armed = true

  constructor(private readonly prefetch: Prefetch) {}

  sync(
    queue: QueuePrefetchItem[],
    currentIndex: number,
    repeatAll = false,
    shuffle = false,
    immediateNextIndex: number | null = null,
    autoPump = true,
  ): void {
    const nextItems: QueuePrefetchItem[] = []

    if (shuffle) {
      if (
        immediateNextIndex !== null &&
        immediateNextIndex !== currentIndex &&
        queue[immediateNextIndex]
      ) {
        nextItems.push(queue[immediateNextIndex])
        const secondCandidate = queue.find(
          (_, index) => index !== currentIndex && index !== immediateNextIndex,
        )
        if (secondCandidate) nextItems.push(secondCandidate)
      } else {
        const candidate = queue.find((_, index) => index !== currentIndex)
        if (candidate) {
          nextItems.push(candidate)
          const secondCandidate = queue.find(
            (item, index) => index !== currentIndex && item !== candidate,
          )
          if (secondCandidate) nextItems.push(secondCandidate)
        }
      }
    } else {
      if (currentIndex + 1 < queue.length) {
        nextItems.push(queue[currentIndex + 1])
        if (currentIndex + 2 < queue.length) {
          nextItems.push(queue[currentIndex + 2])
        } else if (repeatAll && queue.length > 1) {
          nextItems.push(queue[0])
        }
      } else if (repeatAll && currentIndex > 0 && queue.length > 0) {
        nextItems.push(queue[0])
        if (queue.length > 1 && currentIndex !== 1) {
          nextItems.push(queue[1])
        }
      }
    }

    const streamTargets = nextItems.filter((item) => item.id.startsWith('stream:'))
    this.desired = streamTargets.map((item) => {
      const quality = qualityFor(item)
      return { item, quality, key: keyFor(item, quality) }
    })

    const desiredKeys = new Set(this.desired.map(({ key }) => key))
    for (const key of this.ready) {
      if (!desiredKeys.has(key)) this.ready.delete(key)
    }
    for (const key of this.failed) {
      if (!desiredKeys.has(key)) this.failed.delete(key)
    }

    if (autoPump) {
      this.pump()
    }
  }

  /**
   * Explicitly triggers prefetching for the next track in queue once
   * the current track has successfully started playing.
   */
  trigger(): void {
    this.armed = true
    this.pump()
  }

  /**
   * Pauses prefetching (e.g. while a new track is establishing its initial connection).
   */
  disarm(): void {
    this.armed = false
  }

  /**
   * Clears all prefetch targets.
   */
  clear(): void {
    this.desired = []
  }

  private pump(): void {
    if (!this.armed) return
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
