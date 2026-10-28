// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { engine, type EngineHandlers } from './audioEngine'

describe('audioEngine deck priming & gapless swap', () => {
  let playMock: ReturnType<typeof vi.fn>
  let pauseMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    playMock = vi.fn().mockResolvedValue(undefined)
    pauseMock = vi.fn()
    window.HTMLMediaElement.prototype.play = playMock as unknown as () => Promise<void>
    window.HTMLMediaElement.prototype.pause = pauseMock as unknown as () => void
  })

  it('setNext primes the idle deck with preload auto without calling play', () => {
    const handlers: EngineHandlers = {
      onPlay: vi.fn(),
      onPause: vi.fn(),
      onTime: vi.fn(),
      onDuration: vi.fn(),
      onEnded: vi.fn(),
      onError: vi.fn(),
      onAdvance: vi.fn(),
    }
    engine.init(handlers)

    // لود ترک فعلی روی دک فعال
    engine.load('http://test/track1.mp3', { autoplay: true })
    const activeEl = engine.element()
    expect(activeEl.src).toBe('http://test/track1.mp3')

    // ست کردن ترک بعدی
    engine.setNext('http://test/track2.mp3', -1.5)

    // نباید play روی ترک بعدی صدا زده شده باشد
    expect(playMock).toHaveBeenCalledTimes(1) // فقط برای ترک اول

    // ست کردن null دک بعدی را خالی می‌کند
    engine.setNext(null)
  })

  it('ended event triggers gapless deck swap and onAdvance when nextSource is primed', async () => {
    const handlers: EngineHandlers = {
      onPlay: vi.fn(),
      onPause: vi.fn(),
      onTime: vi.fn(),
      onDuration: vi.fn(),
      onEnded: vi.fn(),
      onError: vi.fn(),
      onAdvance: vi.fn(),
    }
    engine.init(handlers)
    engine.setCrossfade(0) // بدون کراس‌فید

    engine.load('http://test/trackA.mp3', { autoplay: true })
    const deckA = engine.element()
    engine.setNext('http://test/trackB.mp3', 0)

    // تریگر پایان آهنگ روی دک فعلی
    deckA.dispatchEvent(new Event('ended'))

    // برای اینکه پرامیس play() در دکِ بعدی اجرا شود منتظر یک تیک می‌مانیم
    await new Promise((r) => setTimeout(r, 0))

    // دک تعویض شده و onAdvance صدا زده شده است، بدون آنکه onEnded فراخوانی شود
    expect(handlers.onAdvance).toHaveBeenCalledTimes(1)
    expect(handlers.onEnded).not.toHaveBeenCalled()
    expect(engine.element().src).toBe('http://test/trackB.mp3')
  })

  it('if primed deck play rejects, it safely falls back to onEnded without silence', async () => {
    const handlers: EngineHandlers = {
      onPlay: vi.fn(),
      onPause: vi.fn(),
      onTime: vi.fn(),
      onDuration: vi.fn(),
      onEnded: vi.fn(),
      onError: vi.fn(),
      onAdvance: vi.fn(),
    }
    engine.init(handlers)
    engine.setCrossfade(0)

    engine.load('http://test/trackX.mp3', { autoplay: true })
    const deckX = engine.element()
    engine.setNext('http://test/trackY.mp3', 0)

    // دفعه بعد که play فراخوانی شود reject می‌کند
    playMock.mockRejectedValueOnce(new Error('Autoplay prevented'))

    deckX.dispatchEvent(new Event('ended'))

    await new Promise((r) => setTimeout(r, 0))

    // به جای قطعی پخش، به onEnded فال‌بک داده می‌شود تا صف به طور نرمال پیش برود
    expect(handlers.onAdvance).not.toHaveBeenCalled()
    expect(handlers.onEnded).toHaveBeenCalledTimes(1)
  })

  it('calling load() with the primed next source performs an instant gapless swap', () => {
    const handlers: EngineHandlers = {
      onPlay: vi.fn(),
      onPause: vi.fn(),
      onTime: vi.fn(),
      onDuration: vi.fn(),
      onEnded: vi.fn(),
      onError: vi.fn(),
      onAdvance: vi.fn(),
    }
    engine.init(handlers)

    // ترک اول لود می‌شود
    engine.load('http://test/song1.mp3', { autoplay: true })
    const deck1 = engine.element()
    expect(deck1.src).toBe('http://test/song1.mp3')

    // ترک بعدی در پس‌زمینه پرلود می‌شود
    engine.setNext('http://test/song2.mp3', 0)

    // کاربر دکمه Next می‌زند یا دستی ترک دوم را لود می‌کند
    playMock.mockClear()
    engine.load('http://test/song2.mp3', { autoplay: true })

    // دک سوئیچ شده و ترک دوم بلافاصله پلی می‌شود
    expect(engine.element().src).toBe('http://test/song2.mp3')
    expect(playMock).toHaveBeenCalledTimes(1)
    expect(handlers.onAdvance).toHaveBeenCalledTimes(1)

    // دک قبلی متوقف و پاک شده است
    expect(pauseMock).toHaveBeenCalled()
  })
})
