import { useEffect, useRef, useState } from 'react'
import { usePopover } from '../lib/usePopover'
import { isUrl } from '../lib/format'
import { useI18n } from '../lib/i18n'
import { useSearchHistory } from '../store/searchHistory'
import { ArrowIcon, CloseIcon, SearchIcon, Spinner } from './icons'

interface Props {
  value: string
  loading: boolean
  /** live=true یعنی حین تایپ (debounce شده) — نباید تاریخچه ثبت کند و نباید تاریخچه‌ی مرورگر را انباشته کند */
  onSearch: (value: string, opts: { live: boolean }) => void
}

/** فاصله‌ی سکوتِ تایپ قبل از شلیک جستجوی زنده — مثل نوار جستجوی اسپاتیفای */
const LIVE_DELAY = 400

export default function SearchBar({ value, loading, onSearch }: Props) {
  const [draft, setDraft] = useState(value)
  const [open, setOpen] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const box = usePopover<HTMLDivElement>(open, () => setOpen(false))
  const { t } = useI18n()
  const { items: history, remove, clear } = useSearchHistory()

  useEffect(() => setDraft(value), [value])

  const linkMode = isUrl(draft)

  // جستجوی زنده حین تایپ — فقط وقتی draft از value بیرونی جلوتر رفته، وگرنه
  // همگام‌سازیِ برگشتی از App (بعد از ناوبری) دوباره همان جستجو را شلیک می‌کند
  useEffect(() => {
    const v = draft.trim()
    if (!v || v === value.trim() || linkMode) return
    const id = window.setTimeout(() => onSearch(draft, { live: true }), LIVE_DELAY)
    return () => window.clearTimeout(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft])

  /*
   * میان‌بر «/» برای فوکوس روی سرچ.
   *
   * شرطِ قبلی فقط خودِ همین ورودی را استثنا می‌کرد، پس تایپِ «/» در نامِ
   * پلی‌لیست یا جعبه‌ی گفتگو فوکوس را از زیر دستِ کاربر می‌دزدید. حالا هر
   * ورودیِ فعالی مصون است — و کلیدهای ترکیبی هم دستِ مرورگر می‌مانند.
   */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== '/' || e.ctrlKey || e.metaKey || e.altKey) return
      const target = e.target as HTMLElement | null
      if (
        target?.tagName === 'INPUT' ||
        target?.tagName === 'TEXTAREA' ||
        target?.isContentEditable
      ) {
        return
      }
      e.preventDefault()
      input.current?.focus()
    }
    window.addEventListener('keydown', onKey)

    /* میان‌بُرِ لانچری «جستجو» — اپ را باز می‌کند و کاربر از همان‌جا تایپ
       می‌کند. بدونِ این، میان‌بُر فقط صفحه را باز می‌کرد و هیچ کادری فعال
       نمی‌شد؛ یعنی یک ضربه‌ی هدررفته. */
    const onFocus = () => input.current?.focus()
    window.addEventListener('musicbazi:focus-search', onFocus)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('musicbazi:focus-search', onFocus)
    }
  }, [])

  const submit = (raw: string) => {
    const v = raw.trim()
    if (!v) return
    setOpen(false)
    onSearch(v, { live: false })
  }

  const clearDraft = () => {
    setDraft('')
    input.current?.focus()
  }

  // با کلیک روی سرچ‌باکس باز می‌شود — چه خالی باشد چه از قبل چیزی توش باشد
  const showHistory = open && history.length > 0

  return (
    <div ref={box} className="relative w-full">
      <form
        onSubmit={(e) => {
          e.preventDefault()
          submit(draft)
        }}
        className="w-full"
      >
        <div className="flex items-center gap-2 rounded-full border border-line bg-panel-2 py-2 ps-3.5 pe-2 transition focus-within:border-accent/70 focus-within:shadow-[0_0_0_4px_var(--color-accent-dim)]">
          {loading ? (
            <Spinner className="size-4 shrink-0 text-muted-2" />
          ) : (
            <SearchIcon className="size-4 shrink-0 text-muted-2" />
          )}

          <input
            ref={input}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onFocus={() => setOpen(true)}
            // فوکوس تنها موقع گذار از بیرون به داخل شلیک می‌شود؛ بین دو صفحه
            // (خانه→نتایج) همین ورودی فوکوس‌اش را نگه می‌دارد، پس کلیک دوباره
            // هیچ رویداد focus جدیدی نمی‌دهد — باید خودِ کلیک را هم بشنویم
            onClick={() => setOpen(true)}
            autoComplete="off"
            // تبِ «جستجو»ی نوارِ پایین از روی همین نشانه پیدایش می‌کند —
            // بدونش تب‌بار باید یک ref از دلِ سه کامپوننت بالا می‌کشید
            data-search-input
            className="bidi-auto min-w-0 flex-1 bg-transparent px-0.5 text-sm outline-none placeholder:text-muted-2"
            placeholder={t.searchPlaceholder}
          />

          {linkMode ? (
            <button
              type="submit"
              className="flex shrink-0 items-center gap-1 rounded-full bg-accent px-3 py-1.5 text-xs font-semibold text-accent-fg transition hover:brightness-110"
            >
              {t.open}
              <ArrowIcon className="size-3" />
            </button>
          ) : (
            draft.length > 0 && (
              <button
                type="button"
                onClick={clearDraft}
                aria-label={t.clearSearch}
                className="grid size-6 shrink-0 place-items-center rounded-full text-muted-2 transition hover:bg-panel hover:text-fg"
              >
                <CloseIcon className="size-3" />
              </button>
            )
          )}
        </div>
      </form>

      {showHistory && (
        <div className="toast-in absolute inset-x-0 top-[calc(100%+0.5rem)] z-30 overflow-hidden rounded-2xl border border-line bg-panel shadow-xl">
          <div className="flex items-center justify-between px-3 py-2">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-2">
              {t.recentSearches}
            </span>
            <button
              type="button"
              onClick={clear}
              className="rounded-md px-1.5 py-1 text-[11px] text-muted-2 transition hover:text-fg"
            >
              {t.clearHistory}
            </button>
          </div>
          <ul className="max-h-64 overflow-y-auto pb-1">
            {history.map((q) => (
              <li key={q} className="group flex items-center">
                <button
                  type="button"
                  onClick={() => submit(q)}
                  className="bidi-auto flex min-w-0 flex-1 items-center gap-2.5 px-3 py-2 text-start text-sm transition hover:bg-panel-2"
                >
                  <SearchIcon className="size-3.5 shrink-0 text-muted-2" />
                  <span className="truncate">{q}</span>
                </button>
                <button
                  type="button"
                  onClick={() => remove(q)}
                  aria-label={t.removeSearch(q)}
                  title={t.removeSearch(q)}
                  className="hover-reveal me-2 grid size-8 shrink-0 place-items-center rounded-md text-muted-2 opacity-0 transition hover:bg-panel-2 hover:text-fg group-hover:opacity-100 sm:size-6"
                >
                  <CloseIcon className="size-3" />
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
