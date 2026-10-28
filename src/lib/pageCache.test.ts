import { afterEach, describe, expect, it, vi } from 'vitest'
import { createLane, pageCache } from './pageCache'

// نقشه‌های سطحِ ماژول بینِ تست‌های همین فایل باقی می‌مانند (Vitest ماژول را بینِ
// فایل‌ها تازه می‌کند، بینِ تست‌های یک فایل نه)
afterEach(() => pageCache.clearAll())

describe('createLane', () => {
  it('reads nothing for a key it never wrote', () => {
    const lane = createLane<string>(4)
    expect(lane.read('nope')).toBeUndefined()
    expect(lane.size()).toBe(0)
  })

  it('round-trips a written value', () => {
    const lane = createLane<{ v: number }>(4)
    const value = { v: 1 }
    lane.write('k', value)
    expect(lane.read('k')).toBe(value)
    expect(lane.size()).toBe(1)
  })

  it('evicts the least recently used key past the cap', () => {
    const lane = createLane<number>(2)
    lane.write('a', 1)
    lane.write('b', 2)
    lane.write('c', 3)
    expect(lane.read('a')).toBeUndefined()
    expect(lane.read('b')).toBe(2)
    expect(lane.read('c')).toBe(3)
    expect(lane.size()).toBe(2)
  })

  it('rewriting a key refreshes its recency, not just its value', () => {
    // بدونِ این، `a` که تازه بازخوانی/نوشته شده بود قربانیِ بعدی می‌شد
    const lane = createLane<number>(2)
    lane.write('a', 1)
    lane.write('b', 2)
    lane.write('a', 10)
    lane.write('c', 3)
    expect(lane.read('a')).toBe(10)
    expect(lane.read('b')).toBeUndefined()
  })

  it('dedupes concurrent loads of the same key into one request', async () => {
    // معادلِ اجرای دوباره‌ی افکت در StrictMode: دو مصرف‌کننده، یک درخواست
    const lane = createLane<number>(4)
    const run = vi.fn(() => Promise.resolve(7))
    const a = lane.load('k', run)
    const b = lane.load('k', run)
    // همان Promise، پس مصرف‌کننده‌ی دوم منتظرِ درخواستِ اول می‌ماند
    expect(a).toBe(b)
    // `run` یک ریزکار بعد صدا زده می‌شود (پایین‌تر) — همان چیزی که پرت‌کردنِ
    // همگام را هم بی‌خطر می‌کند
    await a
    expect(run).toHaveBeenCalledTimes(1)
  })

  it('writes the result of a load into the cache', async () => {
    const lane = createLane<number>(4)
    await expect(lane.load('k', () => Promise.resolve(7))).resolves.toBe(7)
    expect(lane.read('k')).toBe(7)
  })

  it('does not leave a failed load in flight', async () => {
    // وگرنه «تلاش دوباره» همیشه همان شکستِ قبلی را می‌دید
    const lane = createLane<number>(4)
    await expect(lane.load('k', () => Promise.reject(new Error('boom')))).rejects.toThrow('boom')
    const retry = vi.fn(() => Promise.resolve(1))
    await expect(lane.load('k', retry)).resolves.toBe(1)
    expect(retry).toHaveBeenCalledTimes(1)
  })

  it('does not cache a failure', async () => {
    const lane = createLane<number>(4)
    await lane.load('k', () => Promise.reject(new Error('boom'))).catch(() => {})
    expect(lane.read('k')).toBeUndefined()
  })

  it('survives a run that throws synchronously', async () => {
    const lane = createLane<number>(4)
    await expect(
      lane.load('k', () => {
        throw new Error('sync')
      }),
    ).rejects.toThrow('sync')
    // کلیدِ در جریان باید پاک شده باشد، نه گیرکرده
    await expect(lane.load('k', () => Promise.resolve(2))).resolves.toBe(2)
  })

  it('lets a load be retried after the previous one finished', async () => {
    const lane = createLane<number>(4)
    await lane.load('k', () => Promise.resolve(1))
    // درخواست تمام شده، پس این یکی *باید* اجرا شود — این همان چیزی است که
    // تازه‌سازیِ پس‌زمینه را ممکن می‌کند
    await expect(lane.load('k', () => Promise.resolve(2))).resolves.toBe(2)
    expect(lane.read('k')).toBe(2)
  })

  it('owns the signal it passes, so one caller leaving does not kill the shared request', async () => {
    /*
     * ریشه‌ی همین تصمیم: افکتِ `App` با هر ناوبری و دو بار در StrictMode اجرا
     * می‌شود و پاک‌سازی‌اش `abort` می‌زند. اگر سیگنالِ مصرف‌کننده به خط می‌رسید،
     * دورِ اول درخواستِ مشترک را می‌کشت و مصرف‌کننده‌ی دوم — که سیگنالش سالم
     * است — یک `AbortError` می‌گرفت و صفحه تا ابد اسکلتون می‌ماند.
     */
    const lane = createLane<number>(4)
    let seen: AbortSignal | undefined
    const run = (signal: AbortSignal) => {
      seen = signal
      return Promise.resolve(1)
    }
    await lane.load('k', run)
    expect(seen).toBeInstanceOf(AbortSignal)
    expect(seen?.aborted).toBe(false)
  })

  it('aborts the in-flight request when the key is dropped', async () => {
    const lane = createLane<number>(4)
    let seen: AbortSignal | undefined
    const load = lane.load('k', (signal) => {
      seen = signal
      return new Promise<never>(() => {})
    })
    void load.catch(() => {})
    // `run` یک ریزکار بعد صدا زده می‌شود، پس سیگنالش تا آن لحظه نرسیده
    await Promise.resolve()
    lane.drop('k')
    expect(seen?.aborted).toBe(true)
    // و کلید دیگر «در جریان» نیست، پس درخواستِ تازه‌ای می‌شود فرستاد
    await expect(lane.load('k', () => Promise.resolve(9))).resolves.toBe(9)
  })

  it('drops a key from both the cache and in-flight', async () => {
    const lane = createLane<number>(4)
    lane.write('k', 1)
    lane.drop('k')
    expect(lane.read('k')).toBeUndefined()
  })

  it('clears everything', () => {
    const lane = createLane<number>(4)
    lane.write('a', 1)
    lane.write('b', 2)
    lane.clear()
    expect(lane.size()).toBe(0)
    expect(lane.read('a')).toBeUndefined()
  })
})
