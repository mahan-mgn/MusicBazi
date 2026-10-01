import { useEffect, useState } from 'react'
import { useDialog } from '../lib/useDialog'
import { useI18n, type Dict } from '../lib/i18n'
import { usePlayer } from '../store/player'
import { CloseIcon, KeyboardIcon } from './icons'

/**
 * میان‌برهای کیبورد.
 *
 * تا امروز تنها میان‌برهای اپ «فاصله» (داخلِ نوار پخش) و «/» (داخلِ سرچ‌بار)
 * بودند، هرکدام با شنونده‌ی خودشان و بی‌خبر از هم. حالا همه‌ی میان‌برهای
 * سراسری یک‌جا هستند و یک فهرستِ واحد هم دارند که خودش را نشان می‌دهد — چون
 * میان‌بری که هیچ‌جا نوشته نشده، برای کاربر وجود ندارد.
 *
 * سه قاعده‌ی مشترکِ همه‌شان:
 *
 *  ۱. **داخلِ ورودی هیچ‌کدام کار نمی‌کنند.** تایپِ «m» در نامِ پلی‌لیست نباید
 *     صدا را قطع کند.
 *  ۲. **با Ctrl/Alt/Cmd کار نمی‌کنند.** آن ترکیب‌ها مالِ مرورگر و سیستم‌اند.
 *  ۳. **میان‌برهای پخش وقتی چیزی پخش نمی‌شود، بی‌اثرند** — نه اینکه خطا بدهند.
 *
 * `Escape` عمداً اینجا نیست: بستنِ لایه‌ها کارِ پشته‌ی `back.ts` است تا با
 * دکمه‌ی برگشتِ اندروید یکی بماند.
 */

/** میان‌بری که خودش پنجره‌ای باز می‌کند، از قلمروِ این شنونده بیرون است */
function inEditable(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  if (!el) return false
  return (
    el.tagName === 'INPUT' ||
    el.tagName === 'TEXTAREA' ||
    el.tagName === 'SELECT' ||
    el.isContentEditable
  )
}

/** یک ردیف از جدولِ راهنما */
function Row({ keys, label }: { keys: string[]; label: string }) {
  return (
    <div className="flex items-center justify-between gap-3 py-1.5">
      <span className="text-xs text-muted">{label}</span>
      <span className="flex shrink-0 items-center gap-1" dir="ltr">
        {keys.map((key) => (
          <kbd
            key={key}
            className="min-w-6 rounded-md border border-line bg-panel-2 px-1.5 py-0.5 text-center text-[11px] font-semibold text-fg"
          >
            {key}
          </kbd>
        ))}
      </span>
    </div>
  )
}

const GROUPS = (t: Dict): { title: string; rows: { keys: string[]; label: string }[] }[] => [
  {
    title: t.nowPlayingView,
    rows: [
      { keys: ['Space', 'K'], label: t.shortcutPlayPause },
      { keys: ['←', '→'], label: t.shortcutSeek },
      { keys: ['N'], label: t.shortcutNext },
      { keys: ['B'], label: t.shortcutPrev },
      { keys: ['M'], label: t.shortcutMute },
      { keys: ['S'], label: t.shortcutShuffle },
      { keys: ['R'], label: t.shortcutRepeat },
      { keys: ['F'], label: t.shortcutFull },
    ],
  },
  {
    title: t.brand,
    rows: [
      { keys: ['/'], label: t.shortcutSearch },
      { keys: ['?'], label: t.shortcutHelp },
      { keys: ['Esc'], label: t.shortcutClose },
    ],
  },
]

export default function Shortcuts() {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const dialog = useDialog<HTMLDivElement>(open, () => setOpen(false))

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || inEditable(e.target)) return

      if (e.key === '?') {
        e.preventDefault()
        setOpen((v) => !v)
        return
      }

      // بقیه‌ی میان‌برها روی پخش‌کننده‌اند و بدونِ صف معنایی ندارند
      const player = usePlayer.getState()
      if (!player.queue.length) return

      /*
       * جهتِ فلش‌ها به راست‌به‌چپ بودنِ رابط گره نمی‌خورد — دقیقاً به همان
       * دلیلی که `.seek` قفلِ ltr است: «→ یعنی جلو» قراردادِ جهانیِ
       * پخش‌کننده‌هاست، حتی وقتی بقیه‌ی صفحه از راست خوانده می‌شود.
       */
      switch (e.key) {
        case ' ':
        case 'k':
        case 'K':
          e.preventDefault()
          player.toggle()
          break
        case 'ArrowRight':
          e.preventDefault()
          player.seek(Math.min(player.duration || Infinity, player.position + 5))
          break
        case 'ArrowLeft':
          e.preventDefault()
          player.seek(Math.max(0, player.position - 5))
          break
        case 'n':
        case 'N':
          player.next()
          break
        case 'b':
        case 'B':
          player.prev()
          break
        case 'm':
        case 'M':
          player.toggleMute()
          break
        case 's':
        case 'S':
          player.toggleShuffle()
          break
        case 'r':
        case 'R':
          player.cycleRepeat()
          break
        case 'f':
        case 'F':
          // نمای کامل مالِ نوار پخش است؛ همان‌جا گوش می‌دهد
          window.dispatchEvent(new CustomEvent('musicbazi:expand-player'))
          break
      }
    }

    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  if (!open) return null

  return (
    <div
      className="scroll-pane fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-3 pb-[calc(1rem+var(--safe-b))] pt-[calc(1rem+var(--safe-t))] backdrop-blur-sm sm:p-4"
      onClick={(e) => e.target === e.currentTarget && setOpen(false)}
    >
      <div
        ref={dialog}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={t.shortcuts}
        className="glass rise w-full max-w-md overflow-hidden rounded-2xl shadow-2xl sm:mt-20"
      >
        <div className="flex items-center justify-between border-b border-line-soft px-4 py-3">
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <KeyboardIcon className="size-4 text-accent" />
            {t.shortcuts}
          </h2>
          <button
            onClick={() => setOpen(false)}
            aria-label={t.close}
            className="grid size-9 place-items-center rounded-md text-muted-2 transition hover:bg-panel-2 hover:text-fg sm:size-7"
          >
            <CloseIcon className="size-3.5" />
          </button>
        </div>

        <div className="space-y-4 p-4">
          {GROUPS(t).map((group) => (
            <div key={group.title}>
              <p className="mb-1 text-[10px] uppercase tracking-wide text-muted-2">{group.title}</p>
              <div className="divide-y divide-line-soft">
                {group.rows.map((row) => (
                  <Row key={row.label} keys={row.keys} label={row.label} />
                ))}
              </div>
            </div>
          ))}
          <p className="text-[11px] leading-5 text-muted-2">{t.shortcutsPlayerHint}</p>
        </div>
      </div>
    </div>
  )
}
