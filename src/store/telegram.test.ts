import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Track } from '../lib/types'

/**
 * دکمه‌ی «فرستادن به تلگرام».
 *
 * چیزی که اینجا اهمیت دارد رفتارِ دکمه است، نه خودِ ارسال: کلیک روی نصبی که
 * هنوز وصل نیست باید پنجره‌ی کد را باز کند نه خطا بدهد، کلیکِ دوباره نباید
 * آهنگ را دوبار در صف بگذارد، و «تمام شد» فقط وقتی است که خودِ بات گفته باشد.
 */

const api = {
  telegramStatus: vi.fn(),
  telegramPair: vi.fn(),
  telegramUnlink: vi.fn(),
  telegramSend: vi.fn(),
  telegramSendStatus: vi.fn(),
}

vi.mock('../lib/api', () => ({ api, API_MODE: 'http' }))

// i18n موقعِ ایمپورت به localStorage دست می‌زند و تست‌ها در node اجرا می‌شوند؛
// متنِ دقیقِ فارسی هم اینجا موضوع نیست، فقط اینکه چه چیزی به کاربر گفته می‌شود
vi.mock('../lib/i18n', () => ({
  useI18n: {
    getState: () => ({
      t: {
        telegramQueued: 'در صف',
        telegramSent: (title: string) => `رسید:${title}`,
        telegramSendFailed: (title: string, why: string) => `نرسید:${title}:${why}`,
        telegramFailed: 'ناموفق',
      },
    }),
  },
}))

const toasts: { text: string; tone: string }[] = []
vi.mock('./toasts', () => ({
  useToasts: { getState: () => ({ push: (text: string, tone: string) => toasts.push({ text, tone }) }) },
}))

const { albumKey, trackKey, usable, useTelegram } = await import('./telegram')

const track: Track = {
  id: 'itunes:track:1',
  title: 'Mard-e Tanha',
  artist: 'Farhad Mehrad',
  durationMs: 185_000,
  artworkUrl: null,
  source: 'apple',
  sourceUrl: 'https://music.apple.com/us/album/x/1?i=2',
  previewUrl: null,
}

const status = (over: Partial<{ connected: boolean; linked: boolean }> = {}) => ({
  connected: true,
  linked: true,
  chatTitle: 'پیوی من',
  botUsername: 'musicbazi_bot',
  ...over,
})

/** یک تیکِ پیگیری (۱۵۰۰ms) به‌علاوه‌ی فرصتِ حل‌شدنِ promiseها */
async function tick(): Promise<void> {
  await vi.advanceTimersByTimeAsync(1600)
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.clearAllMocks()
  toasts.length = 0
  useTelegram.setState({
    status: null,
    supported: false,
    checked: false,
    sends: {},
    errors: {},
    pairing: null,
    pairingBusy: false,
    pairingError: null,
    pending: null,
  })
  api.telegramStatus.mockResolvedValue(status())
  api.telegramSend.mockResolvedValue({ id: 'send-1', status: 'pending', error: null })
  api.telegramSendStatus.mockResolvedValue({ id: 'send-1', status: 'done', error: null })
  api.telegramPair.mockResolvedValue({ code: 'ABC123', expiresIn: 600, deepLink: 't.me/x' })
})

describe('refresh', () => {
  it('سروری که بات ندارد دکمه‌ای هم نشان نمی‌دهد', async () => {
    api.telegramStatus.mockResolvedValue(null)

    await useTelegram.getState().refresh()

    expect(useTelegram.getState().supported).toBe(false)
  })

  it('وقتی سرویسِ بات پایین است دکمه‌ای نشان داده نمی‌شود، ولی فوتر دلیلش را می‌داند', async () => {
    api.telegramStatus.mockResolvedValue(status({ connected: false }))

    await useTelegram.getState().refresh()

    expect(usable(useTelegram.getState())).toBe(false)
    expect(useTelegram.getState().supported).toBe(true)
  })

  it('قطعیِ شبکه دکمه را پنهان می‌کند، نه اینکه خطا پرت کند', async () => {
    api.telegramStatus.mockRejectedValue(new Error('offline'))

    await expect(useTelegram.getState().refresh()).resolves.toBeNull()
    expect(useTelegram.getState().checked).toBe(true)
  })
})

describe('send', () => {
  it('ترک را در صف می‌گذارد و تا جوابِ بات پیگیری می‌کند', async () => {
    const queued = await useTelegram.getState().send({ kind: 'track', track, quality: '320' })

    expect(queued).toBe(true)
    expect(useTelegram.getState().sends[trackKey(track.id)]).toBe('pending')

    await tick()
    expect(useTelegram.getState().sends[trackKey(track.id)]).toBe('done')
  })

  it('شکستِ خودِ بات با دلیلش دیده می‌شود، نه یک مثلثِ خاموش', async () => {
    api.telegramSendStatus.mockResolvedValue({
      id: 'send-1',
      status: 'error',
      error: 'باز کردنِ آلبوم ناموفق بود: ۴۰۴',
    })

    await useTelegram.getState().send({ kind: 'track', track, quality: '320' })
    await tick()

    expect(useTelegram.getState().sends[trackKey(track.id)]).toBe('error')
    // دلیل هم برای tooltip می‌ماند هم توی toast می‌رود
    expect(useTelegram.getState().errors[trackKey(track.id)]).toContain('۴۰۴')
    expect(toasts.at(-1)).toEqual({
      text: `نرسید:${track.title}:باز کردنِ آلبوم ناموفق بود: ۴۰۴`,
      tone: 'error',
    })
  })

  it('رسیدنِ فایل هم خبر داده می‌شود', async () => {
    await useTelegram.getState().send({ kind: 'track', track, quality: '320' })
    await tick()

    expect(toasts.at(-1)).toEqual({ text: `رسید:${track.title}`, tone: 'success' })
  })

  it('وقتی هنوز وصل نیست، به‌جای خطا پنجره‌ی کد باز می‌شود', async () => {
    api.telegramStatus.mockResolvedValue(status({ linked: false }))

    const queued = await useTelegram.getState().send({ kind: 'track', track, quality: '320' })

    expect(queued).toBe(false)
    expect(api.telegramSend).not.toHaveBeenCalled()
    expect(useTelegram.getState().pairing?.code).toBe('ABC123')
  })

  it('کارِ معطل‌مانده بعد از وصل‌شدن خودش می‌رود', async () => {
    api.telegramStatus.mockResolvedValue(status({ linked: false }))
    await useTelegram.getState().send({ kind: 'track', track, quality: '320' })

    // کاربر کد را در تلگرام خرج کرد
    api.telegramStatus.mockResolvedValue(status())
    await vi.advanceTimersByTimeAsync(2100)
    // چکِ وضعیت و ارسالِ بعدش دو promiseِ زنجیره‌ای‌اند، نه یکی
    await vi.advanceTimersByTimeAsync(0)

    expect(api.telegramSend).toHaveBeenCalledOnce()
    expect(useTelegram.getState().pairing).toBeNull()
  })

  it('کلیکِ دوباره روی کاری که در راه است دوبار نمی‌فرستد', async () => {
    await useTelegram.getState().send({ kind: 'track', track, quality: '320' })
    await useTelegram.getState().send({ kind: 'track', track, quality: '320' })

    expect(api.telegramSend).toHaveBeenCalledOnce()
  })

  it('آلبوم با همان مرجعش می‌رود، نه ترک‌به‌ترک', async () => {
    await useTelegram
      .getState()
      .send({ kind: 'album', ref: 'deezer:album:5', title: 'آلبوم', quality: 'flac' })

    expect(api.telegramSend).toHaveBeenCalledWith({
      kind: 'album',
      ref: 'deezer:album:5',
      title: 'آلبوم',
      quality: 'flac',
    })
    expect(useTelegram.getState().sends[albumKey('deezer:album:5')]).toBe('pending')
  })

  it('ردشدنِ خودِ درخواست هم روی دکمه می‌نشیند و هم به کاربر گفته می‌شود', async () => {
    api.telegramSend.mockRejectedValue(new Error('بات بالا نیست'))

    // پرت نمی‌کند — سه جای مختلف که این دکمه را دارند نباید هرکدام خطا بگیرند
    await expect(
      useTelegram.getState().send({ kind: 'track', track, quality: '320' }),
    ).resolves.toBe(false)
    expect(useTelegram.getState().sends[trackKey(track.id)]).toBe('error')
    expect(toasts.at(-1)?.tone).toBe('error')
  })

  it('قطعیِ لحظه‌ایِ سرور وسطِ پیگیری، ارسال را شکست‌خورده اعلام نمی‌کند', async () => {
    api.telegramSendStatus
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValue({ id: 'send-1', status: 'done', error: null })

    await useTelegram.getState().send({ kind: 'track', track, quality: '320' })
    await tick()
    expect(useTelegram.getState().sends[trackKey(track.id)]).toBe('pending')

    await tick()
    expect(useTelegram.getState().sends[trackKey(track.id)]).toBe('done')
  })
})

describe('unlink', () => {
  it('بعد از قطع، دکمه دوباره سراغ وصل‌شدن می‌رود', async () => {
    await useTelegram.getState().refresh()
    api.telegramStatus.mockResolvedValue(status({ linked: false }))

    await useTelegram.getState().unlink()

    expect(api.telegramUnlink).toHaveBeenCalledOnce()
    expect(useTelegram.getState().status?.linked).toBe(false)
  })
})
