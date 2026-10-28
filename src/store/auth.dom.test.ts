// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * استورِ حساب کاربری.
 *
 * چیزی که این فایل از آن محافظت می‌کند: توکن هرگز در جای غلط نماند. توکنِ
 * کهنه یعنی کاربر بعدِ خروج هنوز داده‌ی حسابِ قبلی را می‌بیند، و توکنی که با
 * ۴۰۱ پاک نشود یعنی هر درخواست بعدی هم ۴۰۱ می‌گیرد.
 */

const authMe = vi.fn()
const authLogin = vi.fn()
const authLogout = vi.fn()
const authMediaToken = vi.fn()
const clearAll = vi.fn()

vi.mock('../lib/api', () => ({
  api: {
    authMe: (...a: unknown[]) => authMe(...a),
    authLogin: (...a: unknown[]) => authLogin(...a),
    authLogout: (...a: unknown[]) => authLogout(...a),
    authMediaToken: (...a: unknown[]) => authMediaToken(...a),
  },
  API_MODE: 'http',
}))

vi.mock('../lib/api/http', () => ({
  setUnauthorizedHandler: (run: (() => void) | null) => {
    handler = run
  },
}))

vi.mock('../lib/pageCache', () => ({ pageCache: { clearAll: () => clearAll() } }))

vi.mock('../lib/i18n', () => ({
  useI18n: Object.assign(() => ({ t: { sessionExpired: 'نشستت تمام شد' } }), {
    getState: () => ({ t: { sessionExpired: 'نشستت تمام شد', avatarSaved: 'ذخیره شد' } }),
  }),
}))

vi.mock('./toasts', () => ({ useToasts: { getState: () => ({ push: () => {} }) } }))

let handler: (() => void) | null = null

/** درخواستِ در جریانِ مدیا، همان‌طور که یک پاسخِ واقعی هم دوباره صدایش می‌زند */
const mediaTokenRef: { current: (() => Promise<string | null>) | null } = { current: null }

async function freshStore() {
  // فقط ماژول را از نو بار می‌کند؛ `localStorage` دست نمی‌خورد چون تست‌ها
  // قبل از این صدا زدن، توکنِ شروع را می‌نشانند
  vi.resetModules()
  return import('./auth')
}

beforeEach(() => {
  localStorage.clear()
  authMe.mockReset()
  authLogin.mockReset()
  authLogout.mockReset()
  authMediaToken.mockReset()
  clearAll.mockReset()
  handler = null
  mediaTokenRef.current = null
})

afterEach(() => {
  localStorage.clear()
})

describe('auth store', () => {
  it('starts as a guest when nothing is stored', async () => {
    const { useAuth } = await freshStore()
    expect(useAuth.getState().user).toBeNull()
    expect(useAuth.getState().loading).toBe(false)
  })

  it('reports loading when a token is already stored', async () => {
    localStorage.setItem('auth:token', 'stored-token')
    const { useAuth } = await freshStore()
    // رندر نباید بلوکه شود ولی وضعیت باید بگوید پروفایل در راه است
    expect(useAuth.getState().loading).toBe(true)
  })

  it('persists the token on login', async () => {
    authLogin.mockResolvedValue({
      token: 'tok-1',
      expiresAt: Date.now() / 1000 + 100,
      user: { id: 'u1', displayName: 'مهان' },
    })
    const { useAuth } = await freshStore()
    await useAuth.getState().login('mahan', 'hunter2hunter2')
    expect(localStorage.getItem('auth:token')).toBe('tok-1')
    expect(useAuth.getState().user?.id).toBe('u1')
  })

  it('clears the token and the page cache on logout', async () => {
    /**
     * پاک‌کردنِ کشِ صفحه بخشی از کارِ خروج است، نه یک بهینه‌سازی: صفحه‌ی
     * کش‌شده‌ی حسابِ قبلی اگر بماند، کاربر بعدِ ورود با حسابِ دوم هنوز
     * کتابخانه‌ی اولی را می‌بیند.
     */
    localStorage.setItem('auth:token', 'tok-1')
    authMe.mockResolvedValue({ id: 'u1', displayName: 'مهان' })
    const { useAuth } = await freshStore()
    await useAuth.getState().refresh()
    expect(useAuth.getState().user).not.toBeNull()

    useAuth.getState().logout()
    expect(localStorage.getItem('auth:token')).toBeNull()
    expect(useAuth.getState().user).toBeNull()
    expect(clearAll).toHaveBeenCalled()
  })

  it('drops the session when the server answers 401', async () => {
    authMe.mockResolvedValue({ id: 'u1', displayName: 'مهان' })
    localStorage.setItem('auth:token', 'tok-1')
    const { useAuth } = await freshStore()
    await useAuth.getState().refresh()

    // `http.ts` توکن را خودش پاک می‌کند و بعد این هوک را صدا می‌زند
    localStorage.removeItem('auth:token')
    expect(handler).not.toBeNull()
    handler!()

    expect(useAuth.getState().user).toBeNull()
    expect(clearAll).toHaveBeenCalled()
  })

  it('exposes a single shared media token per session', async () => {
    authMe.mockResolvedValue({ id: 'u1', displayName: 'مهان' })
    authMediaToken.mockResolvedValue({ token: 'media-1', expiresAt: Date.now() / 1000 + 600 })
    localStorage.setItem('auth:token', 'tok-1')
    const { mediaToken } = await freshStore()

    expect(await mediaToken()).toBe('media-1')
    // بارِ دوم نباید دوباره از سرور بگیرد
    expect(await mediaToken()).toBe('media-1')
    expect(authMediaToken).toHaveBeenCalledTimes(1)
  })

  it('adopts a token from the Google return and reads the profile', async () => {
    authMe.mockResolvedValue({ id: 'u1', displayName: 'مهان' })
    const { useAuth } = await freshStore()

    const ok = await useAuth.getState().adoptToken('tok-from-google')

    expect(ok).toBe(true)
    expect(localStorage.getItem('auth:token')).toBe('tok-from-google')
    expect(useAuth.getState().user?.id).toBe('u1')
    expect(useAuth.getState().loading).toBe(false)
  })

  it('retries once when the first profile read fails', async () => {
    /*
     * بازگشتِ گوگل یک‌شات است: تنها فرصتی که توکن را مصرف می‌کند. یک شکستِ
     * گذرا (تایم‌اوت، ۵۰۳ِ اینترانت، رقابت با درخواست‌های هم‌زمانِ بوت) نباید
     * کاربر را تا رفرشِ دستی «مهمان» نگه دارد.
     */
    authMe.mockRejectedValueOnce(new Error('network')).mockResolvedValueOnce({ id: 'u1', displayName: 'مهان' })
    const { useAuth } = await freshStore()

    const ok = await useAuth.getState().adoptToken('tok-from-google')

    expect(ok).toBe(true)
    expect(authMe).toHaveBeenCalledTimes(2)
    expect(useAuth.getState().user?.id).toBe('u1')
  })

  it('reports failure when the profile never arrives, keeping the token', async () => {
    // شکست باید صریح باشد تا لایه‌ی بالا بتواند پشتیبانِ رفرش را اجرا کند؛
    // پاک‌کردنِ توکن غلط است چون توکنِ خودش سالم است.
    authMe.mockRejectedValue(new Error('network'))
    const { useAuth } = await freshStore()

    const ok = await useAuth.getState().adoptToken('tok-from-google')

    expect(ok).toBe(false)
    expect(useAuth.getState().user).toBeNull()
    expect(localStorage.getItem('auth:token')).toBe('tok-from-google')
    expect(useAuth.getState().loading).toBe(false)
  })

  it('marks the account offline when the profile read fails under a live token', async () => {
    /*
     * این تفکیک همان چیزی است که تاپ‌بار را صادق نگه می‌دارد: توکنِ سالم و
     * پروفایلِ ناموجود «مهمان» نیست. بدونِ `offline`، UI دکمه‌ی «ورود» نشان
     * می‌داد — علامتی که کاربر از آن به «ورودم نگرفت» می‌رسد.
     */
    authMe.mockRejectedValue(new Error('network'))
    localStorage.setItem('auth:token', 'tok-1')
    const { useAuth } = await freshStore()

    await useAuth.getState().refresh()

    expect(useAuth.getState().offline).toBe(true)
    expect(useAuth.getState().user).toBeNull()
    expect(localStorage.getItem('auth:token')).toBe('tok-1')
  })

  it('clears the offline mark once the profile arrives', async () => {
    authMe.mockRejectedValueOnce(new Error('network')).mockResolvedValueOnce({ id: 'u1', displayName: 'مهان' })
    localStorage.setItem('auth:token', 'tok-1')
    const { useAuth } = await freshStore()

    await useAuth.getState().refresh()
    expect(useAuth.getState().offline).toBe(true)

    await useAuth.getState().refresh()
    expect(useAuth.getState().offline).toBe(false)
    expect(useAuth.getState().user?.id).toBe('u1')
  })

  it('does not mark a real guest as offline', async () => {
    const { useAuth } = await freshStore()
    await useAuth.getState().refresh()
    expect(useAuth.getState().offline).toBe(false)
  })

  it('picks up a sign-in that happened in another tab', async () => {
    /*
     * `storage` فقط در تب‌های دیگر پرت می‌شود، پس این تنها راهِ بیدار کردنِ تبی
     * است که از قبل باز بوده. بدونِ این شاخه، تا رفرشِ دستی «مهمان» می‌ماند —
     * همان علامتی که کاربر گزارش کرد.
     */
    const { useAuth } = await freshStore()
    authMe.mockResolvedValue({ id: 'u1', displayName: 'مهان' })

    localStorage.setItem('auth:token', 'tok-from-other-tab')
    localStorage.setItem('auth:stamp', String(Date.now()))
    window.dispatchEvent(new StorageEvent('storage', { key: 'auth:stamp' }))

    await vi.waitFor(() => expect(useAuth.getState().user?.id).toBe('u1'))
  })

  it('shares one media-token request instead of recursing', async () => {
    /*
     * پاسخِ `/auth/media` خودش از `readJson` می‌گذرد و `attachMediaToken` را
     * صدا می‌زند — یعنی دوباره `mediaToken()`. بدونِ اشتراکِ درخواستِ در جریان،
     * هر پاسخ یک درخواستِ تازه می‌ساخت و تا ابد ادامه می‌داد؛ در عمل `refresh`
     * هرگز تمام نمی‌شد و تاپ‌بار روی «ورود» می‌ماند.
     */
    authMediaToken.mockImplementation(async () => {
      // پاسخِ در جریان، درست مثلِ یک پاسخِ واقعی، دوباره توکن می‌خواهد — ولی
      // از مسیرِ HTTP (یک tick بعد)، نه داخلِ ساختنِ همان promise
      setTimeout(() => void mediaTokenRef.current?.(), 0)
      return { token: 'media-1', expiresAt: Date.now() / 1000 + 600 }
    })
    localStorage.setItem('auth:token', 'tok-1')
    const mod = await freshStore()
    mediaTokenRef.current = mod.mediaToken

    const first = await mod.mediaToken()
    expect(first).toBe('media-1')
    expect(authMediaToken).toHaveBeenCalledTimes(1)
  })

  it('never asks for a media token as a guest', async () => {
    const { mediaToken } = await freshStore()
    expect(await mediaToken()).toBeNull()
    expect(authMediaToken).not.toHaveBeenCalled()
  })
})
