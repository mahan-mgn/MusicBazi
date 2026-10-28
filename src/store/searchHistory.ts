import { create } from 'zustand'

import { onIdentityChange } from '../lib/identity'
import { scopedKey } from '../lib/storage'

const KEY = 'search:history'
const MAX = 8

/** حساب‌محور — عبارت‌هایی که یک نفر جستجو کرده نباید به حسابِ بعدی نشان داده شود */
const key = () => scopedKey(KEY)

function read(): string[] {
  try {
    const raw = localStorage.getItem(key())
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === 'string') : []
  } catch {
    return []
  }
}

function write(items: string[]) {
  try {
    localStorage.setItem(key(), JSON.stringify(items))
  } catch {
    // سهمیه‌ی localStorage پر است — تاریخچه صرفاً یک راحتی است، نه چیز حیاتی
  }
}

interface SearchHistoryState {
  items: string[]
  /** جلو می‌آورد اگر از قبل بود، وگرنه اول لیست اضافه می‌کند — تا MAX تا */
  add: (query: string) => void
  remove: (query: string) => void
  clear: () => void
}

export const useSearchHistory = create<SearchHistoryState>((set, get) => ({
  items: read(),
  add: (query) => {
    const q = query.trim()
    if (!q) return
    const next = [q, ...get().items.filter((x) => x !== q)].slice(0, MAX)
    write(next)
    set({ items: next })
  },
  remove: (query) => {
    const next = get().items.filter((x) => x !== query)
    write(next)
    set({ items: next })
  },
  clear: () => {
    write([])
    set({ items: [] })
  },
}))

// ورود/خروج بدونِ رفرش: فهرستِ حسابِ قبلی نباید در حسابِ تازه بماند
onIdentityChange(() => useSearchHistory.setState({ items: read() }))
