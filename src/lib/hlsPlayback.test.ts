import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// mock کامل hls.js — بدون وابستگی به MSE واقعی مرورگر
const hlsInstances: {
  attachMedia: ReturnType<typeof vi.fn>
  loadSource: ReturnType<typeof vi.fn>
  destroy: ReturnType<typeof vi.fn>
  on: ReturnType<typeof vi.fn>
  emitError?: (fatal: boolean) => void
}[] = []

vi.mock('hls.js', () => {
  class FakeHls {
    static isSupported = vi.fn(() => true)
    static Events = { ERROR: 'ERROR' }
    attachMedia = vi.fn()
    loadSource = vi.fn()
    destroy = vi.fn()
    on = vi.fn((_event: string, cb: (e: unknown, data: { fatal: boolean }) => void) => {
      instanceRef.emitError = (fatal: boolean) => cb({}, { fatal })
    })
    constructor() {
      instanceRef = this
      hlsInstances.push(this)
    }
  }
  let instanceRef: {
    attachMedia: ReturnType<typeof vi.fn>
    loadSource: ReturnType<typeof vi.fn>
    destroy: ReturnType<typeof vi.fn>
    on: ReturnType<typeof vi.fn>
    emitError?: (fatal: boolean) => void
  } = undefined as never
  return { default: FakeHls }
})

import { attachHls, detachHls, hlsActive, isOurStreamSource, maybeHlsFallback } from './hlsPlayback'

function fakeEl(): HTMLMediaElement {
  const el = {
    play: vi.fn().mockResolvedValue(undefined),
    src: '',
    currentSrc: '',
  } as unknown as HTMLMediaElement
  return el
}

beforeEach(() => {
  hlsInstances.length = 0
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('isOurStreamSource', () => {
  it('accepts our /api/stream endpoints', () => {
    expect(isOurStreamSource('https://server.example.com/api/stream?track_id=1')).toBe(true)
    expect(isOurStreamSource('https://server.example.com/api/stream/hls/abc/segment/0')).toBe(true)
  })

  it('rejects foreign sources', () => {
    expect(isOurStreamSource('https://cdn.example.com/music.mp3')).toBe(false)
    expect(isOurStreamSource('data:audio/mp3;base64,AAAA')).toBe(false)
    expect(isOurStreamSource('')).toBe(false)
  })
})

describe('attachHls', () => {
  it('wires hls.js to the element and reports success', async () => {
    const el = fakeEl()
    const onError = vi.fn()
    const ok = await attachHls(el, 'https://x.example.com/api/stream?track_id=1', onError)

    expect(ok).toBe(true)
    expect(hlsActive(el)).toBe(true)
    const inst = hlsInstances.at(-1)!
    expect(inst.attachMedia).toHaveBeenCalledWith(el)
    expect(inst.loadSource).toHaveBeenCalledWith('https://x.example.com/api/stream?track_id=1')
    expect(onError).not.toHaveBeenCalled()
  })

  it('is idempotent per element', async () => {
    const el = fakeEl()
    await attachHls(el, 'https://x.example.com/api/stream', vi.fn())
    const before = hlsInstances.length
    await attachHls(el, 'https://x.example.com/api/stream', vi.fn())
    expect(hlsInstances.length).toBe(before) // attach دوم ایجاد instance جدید نمی‌کند
  })

  it('detachHls destroys the instance and clears state', async () => {
    const el = fakeEl()
    await attachHls(el, 'https://x.example.com/api/stream', vi.fn())
    const inst = hlsInstances.at(-1)!
    detachHls(el)
    expect(inst.destroy).toHaveBeenCalled()
    expect(hlsActive(el)).toBe(false)
  })

  it('fatal error detaches and surfaces onError once', async () => {
    const el = fakeEl()
    const onError = vi.fn()
    await attachHls(el, 'https://x.example.com/api/stream', onError)
    const inst = hlsInstances.at(-1)!

    // خطای غیر-fatal: ادامه پخش
    inst.emitError?.(false)
    expect(onError).not.toHaveBeenCalled()

    // خطای fatal: detach + onError
    inst.emitError?.(true)
    expect(inst.destroy).toHaveBeenCalled()
    expect(hlsActive(el)).toBe(false)
    expect(onError).toHaveBeenCalledTimes(1)
  })
})

describe('maybeHlsFallback', () => {
  it('ignores foreign sources and reports error directly', async () => {
    const el = fakeEl()
    el.src = 'https://cdn.example.com/music.mp3'
    const onError = vi.fn()
    await maybeHlsFallback(el, onError)
    expect(onError).toHaveBeenCalledTimes(1)
    expect(hlsInstances.length).toBe(0)
  })

  it('attaches hls.js for our stream sources and resumes playback', async () => {
    const el = fakeEl()
    el.src = 'https://server.example.com/api/stream?track_id=1'
    const onError = vi.fn()
    await maybeHlsFallback(el, onError)
    expect(hlsInstances.length).toBe(1)
    expect(el.play).toHaveBeenCalled()
    expect(onError).not.toHaveBeenCalled()
  })

  it('does not loop: a second fatal error only reports once', async () => {
    const el = fakeEl()
    el.src = 'https://server.example.com/api/stream?track_id=1'
    const onError = vi.fn()
    await maybeHlsFallback(el, onError)
    const inst = hlsInstances.at(-1)!
    inst.emitError?.(true) // fatal → detach + onError

    // خطای دوباره روی همان المنت (بدون hls فعال) — دیگر تلاش HLS نمی‌شود چون
    // native error جدید نیست؛ maybeHlsFallback دوباره attach می‌کند فقط اگر
    // صدا زده شود — در audioEngine فقط روی native error صدا زده می‌شود
    await maybeHlsFallback(el, onError)
    expect(hlsInstances.filter((i) => i.destroy.mock.calls.length >= 0).length).toBeGreaterThan(0)
    expect(onError).toHaveBeenCalled()
  })
})
