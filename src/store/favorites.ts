import { create } from 'zustand'
import { api } from '../lib/api'
import { onIdentityChange } from '../lib/identity'

/**
 * لایک‌های کاربر — مجموعه‌ی jobIdهایی که قلب خورده‌اند.
 *
 * منبع حقیقت سمت سرور است (ستون favorite جدول jobs)؛ اینجا فقط یک کپیِ
 * خوش‌بینانه در حافظه نگه می‌داریم تا قلب بلافاصله پر/خالی شود و منتظرِ
 * round-trip نماند. اگر درخواست شکست خورد، همان مقدار قبلی برمی‌گردد.
 */
interface FavoritesState {
  /** jobId → لایک‌شده؟ */
  items: Record<string, boolean>
  /**
   * با هر «تغییرِ واقعی» (لایک/برداشتن) یکی بالا می‌رود ولی با `hydrate` نه —
   * تا فهرستِ «فقط لایک‌شده‌ها» بداند کی باید دوباره واکشی کند، بدونِ اینکه
   * هر بارِ لود شدنِ کتابخانه یک واکشیِ اضافه بزند.
   */
  version: number
  /** مقدار اولیه را از ردیف‌های کتابخانه می‌گیرد */
  hydrate: (jobIds: string[], favorites: boolean[]) => void
  /** لایک/برداشتن با به‌روزرسانی خوش‌بینانه */
  toggle: (jobId: string) => Promise<void>
}

export const useFavorites = create<FavoritesState>((set, get) => ({
  items: {},
  version: 0,

  hydrate: (jobIds, favorites) => {
    const items = { ...get().items }
    jobIds.forEach((id, i) => {
      if (favorites[i]) items[id] = true
    })
    set({ items })
  },

  toggle: async (jobId) => {
    const current = Boolean(get().items[jobId])
    const next = !current
    // خوش‌بینانه: قلب همین حالا عوض شود؛ نسخه هم همان‌جا که تغییر واقعی است
    set({ items: { ...get().items, [jobId]: next }, version: get().version + 1 })
    try {
      await api.toggleFavorite(jobId, next)
    } catch {
      // شکست: برگردان به مقدار قبلی — این هم یک تغییر است
      set({ items: { ...get().items, [jobId]: current }, version: get().version + 1 })
    }
  },
}))

/*
 * ورود/خروج بدونِ رفرش: قلب‌های حسابِ قبلی نباید در حسابِ تازه روشن بمانند —
 * شناسه‌ی جاب‌ها هم مالِ اوست. `version` هم بالا می‌رود تا فهرستِ «لایک‌شده‌ها»
 * که به آن وابسته است دوباره واکشی کند.
 */
onIdentityChange(() => {
  useFavorites.setState((s) => ({ items: {}, version: s.version + 1 }))
})
