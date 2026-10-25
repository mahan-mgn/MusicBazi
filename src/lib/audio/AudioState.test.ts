import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  EngineStatePublisher,
  HIDDEN_PROGRESS_INTERVAL_MS,
  PROGRESS_INTERVAL_MS,
  type AudioStateSnapshot,
} from './AudioState'

describe('EngineStatePublisher', () => {
  it('شروعش IDLE خام است — نه بافرینگ، نه خطا', () => {
    const publisher = new EngineStatePublisher(() => 0, () => 0)
    const state = publisher.snapshot()
    expect(state.status).toBe('IDLE')
    expect(state.isPlaying).toBe(false)
    expect(state.isBuffering).toBe(false)
    expect(state.errorMessage).toBeNull()
    expect(state.volume).toBe(1)
  })

  it('patch ادغام می‌کند — فیلدهای نیامده دست‌نخورده می‌مانند', () => {
    const publisher = new EngineStatePublisher(() => 0, () => 0)
    publisher.patch({ status: 'BUFFERING', isBuffering: true })
    publisher.patch({ status: 'READY', isBuffering: false, durationMs: 180000 })
    const state = publisher.snapshot()
    expect(state.status).toBe('READY')
    expect(state.isBuffering).toBe(false)
    expect(state.durationMs).toBe(180000)
  })

  it('شنونده فقط با تغییر واقعی بیدار می‌شود — patch بی‌اثر emit نمی‌کند', () => {
    const publisher = new EngineStatePublisher(() => 0, () => 0)
    const seen: AudioStateSnapshot[] = []
    publisher.subscribe((s) => seen.push(s))
    expect(seen).toHaveLength(1) // اسنپ‌شات اولیه همان لحظه می‌آید

    publisher.patch({ status: 'READY' })
    expect(seen).toHaveLength(2)

    // همان وضعیت دوباره — نه تیک، نه شنونده
    publisher.patch({ status: 'READY' })
    expect(seen).toHaveLength(2)
  })

  it('unsubscribe کار می‌کند', () => {
    const publisher = new EngineStatePublisher(() => 0, () => 0)
    const seen: AudioStateSnapshot[] = []
    const off = publisher.subscribe((s) => seen.push(s))
    off()
    publisher.patch({ status: 'READY' })
    expect(seen).toHaveLength(1)
  })

  describe('تیکر پیشرفت', () => {
    beforeEach(() => {
      vi.useFakeTimers()
    })
    afterEach(() => {
      vi.useRealTimers()
    })

    it('در READY موقعیت را هر ۲۵۰ms می‌خواند و منتشر می‌کند', () => {
      let position = 1000
      const publisher = new EngineStatePublisher(
        () => position,
        () => 200000,
      )
      const seen: AudioStateSnapshot[] = []
      publisher.subscribe((s) => seen.push(s))

      publisher.patch({ status: 'READY', isPlaying: true })
      position = 1500
      vi.advanceTimersByTime(PROGRESS_INTERVAL_MS)

      expect(publisher.snapshot().positionMs).toBe(1500)
      expect(seen.length).toBeGreaterThan(1)
      publisher.dispose()
    })

    it('در IDLE تیک نمی‌خورد — موقعیتِ مرده دوباره‌نویسی نمی‌شود', () => {
      let position = 5000
      const publisher = new EngineStatePublisher(
        () => position,
        () => 200000,
      )
      publisher.patch({ status: 'IDLE', positionMs: 5000 })
      position = 9999
      vi.advanceTimersByTime(PROGRESS_INTERVAL_MS * 4)

      expect(publisher.snapshot().positionMs).toBe(5000)
      publisher.dispose()
    })

    it('ورود به ERROR تیکر را می‌ایستاند', () => {
      let position = 1000
      const publisher = new EngineStatePublisher(
        () => position,
        () => 200000,
      )
      publisher.patch({ status: 'READY', isPlaying: true })
      vi.advanceTimersByTime(PROGRESS_INTERVAL_MS)
      const positionAtReady = publisher.snapshot().positionMs
      publisher.patch({ status: 'ERROR', errorMessage: 'boom' })
      position = 7777
      vi.advanceTimersByTime(PROGRESS_INTERVAL_MS * 4)

      expect(publisher.snapshot().positionMs).toBe(positionAtReady)
      expect(publisher.snapshot().errorMessage).toBe('boom')
      publisher.dispose()
    })

    it('در تب مخفی، فاصله تیک به ۱ ثانیه می‌افتد', () => {
      let position = 0
      const publisher = new EngineStatePublisher(
        () => position,
        () => 200000,
      )
      publisher.patch({ status: 'READY', isPlaying: true })

      // شبیه‌سازی تب مخفی بدون jsdom: متد خصوصی از طریق سندِ ساختگی
      const originalDoc = globalThis.document
      ;(globalThis as { document?: unknown }).document = { visibilityState: 'hidden' }
      try {
        publisher.patch({ status: 'BUFFERING', isBuffering: true }) // syncTicker دوباره
        position = HIDDEN_PROGRESS_INTERVAL_MS
        vi.advanceTimersByTime(PROGRESS_INTERVAL_MS) // کمتر از فاصله مخفی
        expect(publisher.snapshot().positionMs).toBe(0)
        vi.advanceTimersByTime(HIDDEN_PROGRESS_INTERVAL_MS)
        expect(publisher.snapshot().positionMs).toBe(HIDDEN_PROGRESS_INTERVAL_MS)
      } finally {
        ;(globalThis as { document?: unknown }).document = originalDoc
        publisher.dispose()
      }
    })
  })
})
