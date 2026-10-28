// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * تعویضِ هویت بدونِ رفرش.
 *
 * ورود و خروج از خودِ اپ اتفاق می‌افتد، پس صفحه دوباره لود نمی‌شود. استورهایی
 * که داده‌شان را در سطحِ ماژول خوانده‌اند (تاریخچه، «ادامه بده»، سنجاق‌ها،
 * صفِ دانلود، قلب‌ها) بدونِ گوش دادن به این رویداد، داده‌ی حسابِ قبلی را در
 * حسابِ تازه نگه می‌داشتند — نشتِ اطلاعاتی، و در موردِ دانلود صفی پر از
 * شناسه‌هایی که سرور برای این حساب ۴۰۴ می‌دهد.
 *
 * کلیدهای `:<user>` هم بخشی از قراردادند: داده‌ی دو حساب روی یک دستگاه نباید
 * از یک کلید بخواند.
 */

vi.mock('../lib/api', () => ({
  api: { authMe: vi.fn(), authLogout: vi.fn(), authMediaToken: vi.fn() },
  API_MODE: 'http',
}))

vi.mock('../lib/api/http', () => ({ setUnauthorizedHandler: () => {} }))

vi.mock('../lib/i18n', () => ({
  useI18n: Object.assign(() => ({ t: {} }), { getState: () => ({ t: {} }) }),
}))

vi.mock('./toasts', () => ({ useToasts: { getState: () => ({ push: () => {} }) } }))

function signIn(userId: string) {
  // فرمتِ توکن `<user_id>:<exp>:<sig>` — `storage.ts` شناسه را از همین می‌خواند
  localStorage.setItem('auth:token', `${userId}:9999999999:sig`)
}

function signOut() {
  localStorage.removeItem('auth:token')
}

beforeEach(() => {
  localStorage.clear()
})

afterEach(() => {
  vi.resetModules()
})

describe('کلیدهای حساب‌محور', () => {
  it('مهمان پسوند نمی‌گیرد — داده‌ی نسخه‌ی تک‌کاربره سرِ جایش می‌ماند', async () => {
    const { scopedKey } = await import('../lib/storage')
    expect(scopedKey('recent:played')).toBe('recent:played')
  })

  it('کاربرِ وارد‌شده کلیدِ جدا می‌گیرد', async () => {
    signIn('u-42')
    const { scopedKey } = await import('../lib/storage')
    expect(scopedKey('recent:played')).toBe('recent:played:u-42')
  })
})

describe('تعویضِ هویت', () => {
  it('تاریخچه‌ی جستجو را به داده‌ی حسابِ تازه عوض می‌کند', async () => {
    signIn('u-1')
    const { useSearchHistory } = await import('./searchHistory')
    useSearchHistory.getState().add('گوگوش')

    // حسابِ تازه با تاریخچه‌ی خودش؛ خروج نباید چیزی از u-1 نشان بدهد
    signOut()
    localStorage.setItem('search:history', JSON.stringify(['همایون']))
    const { emitIdentityChange } = await import('../lib/identity')
    emitIdentityChange()

    expect(useSearchHistory.getState().items).toEqual(['همایون'])
  })

  it('«ادامه بده» را از کلیدِ حسابِ تازه می‌خواند', async () => {
    signIn('u-1')
    const { useRecent } = await import('./recent')
    useRecent.getState().push({
      kind: 'artist',
      key: 'artist:1',
      title: 'گوگوش',
      subtitle: '',
      artworkUrl: null,
      seed: 'g',
      ref: '1',
    })

    signOut()
    const { emitIdentityChange } = await import('../lib/identity')
    emitIdentityChange()

    expect(useRecent.getState().items).toEqual([])
  })

  it('قلب‌ها را خالی می‌کند و نسخه را بالا می‌برد تا فهرست تازه شود', async () => {
    const { useFavorites } = await import('./favorites')
    useFavorites.setState({ items: { j1: true }, version: 3 })

    const { emitIdentityChange } = await import('../lib/identity')
    emitIdentityChange()

    expect(useFavorites.getState().items).toEqual({})
    expect(useFavorites.getState().version).toBe(4)
  })

  it('صفِ دانلود را خالی می‌کند و کلیدِ ماندگاری را به حسابِ تازه می‌برد', async () => {
    const { useDownloads } = await import('./downloads')
    useDownloads.setState({
      jobs: [
        {
          id: 'local-1',
          batchId: 'b1',
          track: saveTrack(),
          quality: '320',
          status: 'ready',
          percent: 100,
          createdAt: 1,
        },
      ],
      batches: [{ id: 'b1', title: 'b', artworkUrl: null, quality: '320', createdAt: 1 }],
    })

    signIn('u-2')
    const { emitIdentityChange } = await import('../lib/identity')
    emitIdentityChange()

    expect(useDownloads.getState().jobs).toEqual([])
    expect(useDownloads.getState().batches).toEqual([])
    expect(useDownloads.persist.getOptions().name).toBe('musicbazi-downloads:u-2')
  })

  it('صفِ ذخیره‌شده‌ی حسابِ تازه را به جای خالی‌کردن برمی‌گرداند', async () => {
    const { useDownloads } = await import('./downloads')
    // صفِ حسابِ قبلی که هنوز در حافظه است
    useDownloads.setState({
      jobs: [{ id: 'other', batchId: 'b', track: saveTrack(), quality: '320', status: 'ready', percent: 100, createdAt: 1 }],
      batches: [],
    })

    // حسابِ تازه از قبل صفی روی این دستگاه دارد (مثلاً قبلاً وارد شده بود)
    signIn('u-9')
    localStorage.setItem(
      'musicbazi-downloads:u-9',
      JSON.stringify({
        state: { jobs: [{ id: 'saved-job', batchId: 'b', track: saveTrack(), quality: '320', status: 'error', percent: 0, createdAt: 1 }], batches: [] },
        version: 0,
      }),
    )

    const { emitIdentityChange } = await import('../lib/identity')
    emitIdentityChange()
    // `rehydrate` حتی با localStorage همگام، یک میکروتسک بعد برمی‌گردد
    await Promise.resolve()
    await Promise.resolve()

    expect(useDownloads.getState().jobs.map((j) => j.id)).toEqual(['saved-job'])
  })
})

function saveTrack() {
  return {
    id: 't',
    title: 't',
    artist: 'a',
    durationMs: 1,
    artworkUrl: null,
    source: 'deezer' as const,
    sourceUrl: 'https://example.com/t',
    previewUrl: null,
  }
}
