import { create } from 'zustand'

import { onIdentityChange } from '../lib/identity'
import { scopedKey } from '../lib/storage'
import type { PlayItem } from './player'

/**
 * «ادامه بده» — آخرین چیزهایی که کاربر واقعاً باهاشان کار کرده: ترک‌هایی که پخش
 * شده‌اند و صفحه‌های هنرمند/آلبومی که باز شده‌اند.
 *
 * عمداً از تاریخچه‌ی جستجو جداست: جستجو یعنی «دنبال چیزی می‌گشتم»، این یعنی
 * «چیزی را پیدا کردم و رفتم سراغش» — و همان دومی است که ارزش برگشتن دارد.
 */

const KEY = 'recent:played'
const MAX = 8

interface Base {
  /** کلید یکتا برای جلوگیری از تکرار در لیست */
  key: string
  title: string
  /** نام هنرمند برای ترک و آلبوم؛ برای خودِ هنرمند خالی است و از i18n پر می‌شود */
  subtitle: string
  artworkUrl: string | null
  /** seed کاورِ حرف‌اولی، وقتی artworkUrl نداریم */
  seed: string
  /** میلی‌ثانیه‌ی یونیکس */
  at: number
}

export type RecentEntry =
  | (Base & {
      kind: 'track'
      /**
       * کلِ PlayItem ذخیره می‌شود تا کلیک بتواند مستقیم پخش کند.
       * اگر فایل بعداً از دیسک پاک شده باشد، پخش همان خطای همیشگی را می‌دهد —
       * دقیقاً مثل «ادامه از جایی که بودی» که آن هم آدرس را ذخیره می‌کند.
       */
      item: PlayItem
    })
  | (Base & {
      kind: 'artist' | 'album'
      /** همان چیزی که ناوبری با آن باز می‌شود (id داخلی یا لینک منبع) */
      ref: string
    })

/** Omit روی یونیون خودش توزیع نمی‌شود و شاخه‌ها را قاطی می‌کند؛ این می‌کند */
type WithoutAt<T> = T extends unknown ? Omit<T, 'at'> : never

/**
 * کلیدِ حساب‌محور. «ادامه بده» شاملِ خودِ ترک و آدرسش است — تاریخِ گوش‌دادنِ
 * حسابِ اول نباید در حسابِ دوم دیده شود. مهمان همان کلیدِ قدیمی را نگه
 * می‌دارد تا داده‌ی نسخه‌ی تک‌کاربره از دست نرود.
 */
const key = () => scopedKey(KEY)

function read(): RecentEntry[] {
  try {
    const raw = localStorage.getItem(key())
    const parsed: unknown = raw ? JSON.parse(raw) : []
    if (!Array.isArray(parsed)) return []
    // نسخه‌های قدیمی‌ترِ ساختار نباید کلِ ردیف را بترکانند
    return (parsed as RecentEntry[]).filter(
      (x) => typeof x?.key === 'string' && typeof x?.title === 'string' && Boolean(x?.kind),
    )
  } catch {
    return []
  }
}

function write(items: RecentEntry[]) {
  try {
    localStorage.setItem(key(), JSON.stringify(items))
  } catch {
    // سهمیه‌ی localStorage پر است — این لیست یک راحتی است، نه چیز حیاتی
  }
}

interface RecentState {
  items: RecentEntry[]
  /** جلو می‌آورد اگر از قبل بود، وگرنه اول لیست اضافه می‌کند — تا MAX تا */
  push: (entry: WithoutAt<RecentEntry>) => void
  clear: () => void
}

export const useRecent = create<RecentState>((set, get) => ({
  items: read(),
  push: (entry) => {
    const current = get().items
    // پخشِ دوباره‌ی همان ترکی که همین حالا صدرِ لیست است، نه ترتیب را عوض
    // می‌کند نه چیزی به localStorage اضافه دارد — پس اصلاً set نکن
    if (current[0]?.key === entry.key) return
    const next = [
      { ...entry, at: Date.now() } as RecentEntry,
      ...current.filter((x) => x.key !== entry.key),
    ].slice(0, MAX)
    write(next)
    set({ items: next })
  },
  clear: () => {
    write([])
    set({ items: [] })
  },
}))

// ورود/خروج بدونِ رفرش: «ادامه بده»‌ی حسابِ قبلی نباید در حسابِ تازه بماند
onIdentityChange(() => useRecent.setState({ items: read() }))
