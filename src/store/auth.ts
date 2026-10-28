import { create } from 'zustand'

import { api } from '../lib/api'
import { setUnauthorizedHandler } from '../lib/api/http'
import {
  cachedMediaToken,
  clearToken,
  onStampChange,
  setMediaResolver,
  setMediaToken,
  setToken,
  token,
} from '../lib/auth'
import { useI18n } from '../lib/i18n'
import { emitIdentityChange } from '../lib/identity'
import { pageCache } from '../lib/pageCache'
import type { AuthProviders, AuthUser } from '../lib/types'
import { useToasts } from './toasts'

/**
 * وضعیتِ حساب کاربری.
 *
 * ورود اختیاری است، پس `user === null` یعنی «مهمان» — نه «خطا» و نه «در حال
 * بارگذاری». رندر اول با همین حالت انجام می‌شود: توکن از `localStorage` خوانده
 * می‌شود (کارِ همگام و ارزان) و پروفایل در پس‌زمینه تازه می‌شود. اگر منتظرِ
 * پاسخِ شبکه می‌ماندیم، اپِ آفلاین تا تایم‌اوت یک صفحه‌ی خالی نشان می‌داد.
 *
 * برخلاف بقیه‌ی استورها، اکشن‌های ورود/ثبت‌نام عمداً خطا *پرت می‌کنند* — صفحه‌ی
 * ورود باید متنِ خطا را زیر فرم نشان بدهد، نه اینکه یک toast شناور بپرد.
 */

interface AuthState {
  user: AuthUser | null
  providers: AuthProviders
  /** توکنی ذخیره شده ولی هنوز پروفایلش خوانده نشده */
  loading: boolean
  /** توکن هست ولی پروفایلش نیامد (شبکه/سرور) — یا همان تلاش بعدی */
  offline: boolean
  busy: boolean
  login: (username: string, password: string) => Promise<void>
  register: (username: string, password: string, displayName?: string) => Promise<void>
  /**
   * نشستی که از بازگشتِ گوگل در `#auth=` آمده.
   *
   * مقدارِ برگشتی می‌گوید پروفایل واقعاً خوانده شد یا نه — بازگشتِ گوگل یک
   * بارگذاریِ تازه‌ی سند است و اگر این یک فرصت هدر برود، تا رفرشِ دستی هیچ‌چیز
   * دوباره تلاش نمی‌کند.
   */
  adoptToken: (value: string) => Promise<boolean>
  logout: () => void
  updateProfile: (patch: { displayName?: string; username?: string }) => Promise<void>
  setAvatar: (file: File) => Promise<void>
  clearAvatar: () => Promise<void>
  refresh: () => Promise<void>
}

export const useAuth = create<AuthState>((set, get) => ({
  user: null,
  providers: { google: false, googleReason: 'not_configured' },
  loading: Boolean(token()),
  offline: false,
  busy: false,

  async login(username, password) {
    set({ busy: true })
    try {
      const session = await api.authLogin({ username, password })
      adopt(session)
      set({ user: session.user, loading: false, offline: false })
      afterIdentityChange()
    } finally {
      set({ busy: false })
    }
  },

  async register(username, password, displayName) {
    set({ busy: true })
    try {
      const session = await api.authRegister({ username, password, displayName })
      adopt(session)
      set({ user: session.user, loading: false, offline: false })
      afterIdentityChange()
    } finally {
      set({ busy: false })
    }
  },

  async adoptToken(value) {
    adopt({ token: value })
    set({ loading: true, offline: false })
    /*
     * یک تلاشِ دوباره، صریح و همین‌جا.
     *
     * `refresh()` خطا را می‌بلعد و همان را برمی‌گرداند که «پروفایل نیامد»؛ ولی
     * بازگشتِ گوگل یک‌شات است: اگر همین یک درخواست با رقابتِ درخواست‌های
     * هم‌زمانِ بوت به ۵۰۳ِ اینترانت یا تایم‌اوت بخورد، کاربر با توکنِ سالم
     * «مهمان» می‌ماند تا خودش صفحه را رفرش کند. یک تلاشِ دومِ کوتاه همان
     * پنجره‌ی گذرا را می‌پوشاند، بدونِ اینکه به retry-loop تبدیل شود.
     */
    await get().refresh()
    if (get().user === null && token()) await get().refresh()
    afterIdentityChange()
    return get().user !== null
  },

  logout() {
    // سرور توکنِ خودبسنده را باطل نمی‌کند، پس این فراخوانی تشریفاتی است و
    // منتظرِ پاسخش نمی‌مانیم — خروج باید فوری باشد، حتی بدونِ شبکه.
    //
    // `?.` و `try` هر دو لازم‌اند: لایه‌ای که این متد را ندارد (مود دمو، سرورِ
    // قدیمی) نباید جلوی خروج را بگیرد. کاربری که دکمه‌ی خروج را زده باید بیرون
    // بیاید، حتی اگر پاک‌کردنِ سمتِ سرور ممکن نباشد.
    try {
      void api.authLogout?.()?.catch(() => null)
    } catch {
      // نبودِ متد یا خطای همگام — خروج سمتِ کلاینت کارِ خودش را می‌کند
    }
    drop()
    set({ user: null, loading: false, offline: false })
    afterIdentityChange()
  },

  async updateProfile(patch) {
    set({ busy: true })
    try {
      set({ user: await api.authUpdateProfile(patch) })
    } finally {
      set({ busy: false })
    }
  },

  async setAvatar(file) {
    set({ busy: true })
    try {
      set({ user: await api.authUploadAvatar(file) })
      toast(useI18n.getState().t.avatarSaved, 'success')
    } finally {
      set({ busy: false })
    }
  },

  async clearAvatar() {
    set({ busy: true })
    try {
      set({ user: await api.authRemoveAvatar() })
    } finally {
      set({ busy: false })
    }
  },

  async refresh() {
    if (!token()) {
      set({ user: null, loading: false, offline: false })
      return
    }
    try {
      set({ user: await api.authMe(), loading: false, offline: false })
    } catch {
      // توکنِ باطل خودش در `http.ts` پاک شده؛ این‌جا فقط وضعیت را هم‌راستا
      // می‌کنیم. خطای شبکه هم همین نتیجه را می‌دهد — پروفایلِ کهنه می‌ماند و
      // دفعه‌ی بعد که شبکه بود تازه می‌شود.
      //
      // `offline` فقط این را می‌گوید: «توکن داریم ولی پروفایلش نیامد». بدونِ
      // آن، UI توکنِ زنده را با مهمان اشتباه می‌گیرد و دکمه‌ی «ورود» نشان
      // می‌دهد — همان چیزی که کاربر فکر می‌کند ورودش نگرفت.
      if (!token()) set({ user: null, offline: false })
      else if (!get().user) set({ offline: true })
      set({ loading: false })
    }
  },
}))

// ---------------------------------------------------------------- کمکی


/** توکن را می‌نشاند. `expiresAt` فقط برای نمایش است، پس نبودش مهم نیست. */
function adopt(session: { token: string }): void {
  setToken(session.token)
}

function drop(): void {
  clearToken()
}

function toast(text: string, tone: 'info' | 'success' | 'error'): void {
  useToasts.getState().push(text, tone)
}

/**
 * هر چیزی که به هویتِ کاربر گره خورده باید دور ریخته شود.
 *
 * صفحه‌ی کش‌شده‌ی حسابِ قبلی اگر بماند، کاربر بعدِ ورود با حسابِ دوم هنوز
 * کتابخانه‌ی اولی را می‌بیند — که هم غلط است هم نشتِ اطلاعاتی.
 */
function afterIdentityChange(): void {
  pageCache.clearAll()
  // استورهای محلیِ باقی‌مانده (تاریخچه‌ی جستجو، «ادامه بده»، سنجاق‌های آفلاین،
  // صفِ دانلود) داده‌شان را در سطحِ ماژول خوانده‌اند؛ خودشان با این رویداد
  // دوباره از کلیدِ حسابِ تازه پر می‌شوند.
  emitIdentityChange()
}

/**
 * پل به لایه‌ی HTTP.
 *
 * `http.ts` نمی‌تواند استور را ایمپورت کند (استور خودش `api` را می‌خواهد)، پس
 * استور خودش را آن‌جا ثبت می‌کند. هر ۴۰۱ از هر جای اپ به این‌جا می‌رسد و
 * کاربر را از حساب بیرون می‌آورد، بدونِ اینکه هر کامپوننت جداگانه چک کند.
 */
setUnauthorizedHandler(() => {
  const state = useAuth.getState()
  if (state.user) {
    drop()
    useAuth.setState({ user: null, loading: false, offline: false })
    afterIdentityChange()
    toast(useI18n.getState().t.sessionExpired, 'info')
  }
})

/**
 * توکنِ مدیا برای آدرس‌های بدونِ هدر.
 *
 * تا وقتی معتبر است از حافظه‌ی محلی می‌آید؛ در غیر این صورت تازه گرفته
 * می‌شود. مهمان توکن نمی‌گیرد چون چیزی برای اثبات ندارد.
 *
 * **درخواستِ در جریان مشترک است.** پاسخِ همین درخواست هم از `readJson` می‌گذرد
 * و `attachMediaToken` را صدا می‌زند، یعنی دوباره همین‌جا؛ بدونِ این اشتراک، هر
 * پاسخ یک درخواستِ تازه می‌ساخت و تا ابد ادامه می‌داد — و در عمل `refresh`
 * هرگز تمام نمی‌شد و تاپ‌بار روی «ورود» می‌ماند.
 */
let mediaRequest: Promise<string | null> | null = null

export async function mediaToken(): Promise<string | null> {
  if (!token()) return null
  const cached = cachedMediaToken()
  if (cached) return cached
  if (mediaRequest) return mediaRequest
  // پرچم **پیش از** اولین `await` نشسته می‌شود؛ وگرنه پاسخِ همین درخواست که
  // دوباره به این‌جا می‌رسد هنوز آن را نمی‌بیند.
  mediaRequest = (async () => {
    try {
      const fresh = await api.authMediaToken()
      setMediaToken(fresh)
      return fresh.token
    } catch {
      // پخش نباید به‌خاطرِ این نشکند؛ آدرسِ بی‌توکن همان چیزی است که امروز هم
      // کار می‌کند
      return null
    }
  })()
  try {
    return await mediaRequest
  } finally {
    mediaRequest = null
  }
}

/** توکنِ فعلیِ مدیا، بدونِ رفت‌وبرگشتِ شبکه — برای مسیرهای همگام. */
export function currentMediaToken(): string | null {
  return cachedMediaToken()
}

/*
 * لایه‌ی HTTP هنگامِ پارس‌کردنِ هر پاسخ از این می‌پرسد تا آدرسِ فایل‌ها را با
 * توکنِ مدیا garnish کند. ثبت از استور (نه ایمپورتِ مستقیم) تا حلقه‌ی
 * وابستگی نسازد — همان قراردادِ `setUnauthorizedHandler`.
 */
setMediaResolver(async () => mediaToken())

/*
 * مهرِ تغییرِ ورود بین تب‌ها رد و بدل می‌شود.
 *
 * دو جهت دارد و هر دو لازم‌اند: خروج در یک تب باید تب‌های دیگر را هم ببرد، و
 * ورود در یک تب باید تب‌های دیگر را هم بیدار کند — وگرنه تبی که از قبل باز
 * بوده تا رفرشِ دستی «مهمان» می‌ماند، درحالی‌که توکنِ تازه همین حالا در
 * `localStorage` نشسته است.
 */
onStampChange(() => {
  const state = useAuth.getState()
  if (!token()) {
    if (state.user) {
      useAuth.setState({ user: null, loading: false, offline: false })
      afterIdentityChange()
    }
    return
  }
  if (!state.user && !state.loading) void state.refresh()
})
