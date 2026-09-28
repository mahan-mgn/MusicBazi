import { memo, useRef, type ReactNode } from 'react'
import { useI18n } from '../lib/i18n'
import { SOURCE_LABEL, type LibraryItem } from '../lib/types'
import { usePlayer, type PlayItem } from '../store/player'
import Artwork, { ArtBackdrop } from './Artwork'
import { ChevronIcon, PauseIcon, PlayIcon } from './icons'
import SourceLogo from './logos'

/**
 * سرصفحه‌ی یک سکشن و ردیفِ افقیِ قابل‌اسکرول — از خانه بیرون آمد چون
 * کتابخانه هم دقیقاً همان دو چیز را لازم دارد. یک نسخه، دو جا.
 */

export function SectionHead({
  title,
  hint,
  action,
  icon,
}: {
  title: string
  hint?: string
  action?: ReactNode
  icon?: ReactNode
}) {
  return (
    <div className="mb-3 flex items-end justify-between gap-3">
      <div className="min-w-0">
        <h2 className="flex items-center gap-2 text-base font-bold sm:text-lg">
          {icon ?? <span aria-hidden className="h-4 w-1 shrink-0 rounded-full bg-accent" />}
          {title}
        </h2>
        {hint && <p className="mt-1 ps-3 text-[11px] text-muted-2">{hint}</p>}
      </div>
      {action}
    </div>
  )
}

/**
 * ردیف افقی کاشی‌ها.
 *
 * دکمه‌های پیمایش فقط از sm به بالا هستند: روی موبایل انگشت کار را می‌کند و دو
 * دکمه‌ی شناور فقط جلوی کاشی‌ها را می‌گیرند.
 */
export function Shelf({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  const { t, lang } = useI18n()

  const scroll = (dir: 1 | -1) => {
    const el = ref.current
    if (!el) return
    // در RTL محورِ اسکرول برعکس است؛ «جلو» یعنی scrollLeft منفی‌تر
    const sign = lang === 'fa' ? -1 : 1
    el.scrollBy({ left: sign * dir * el.clientWidth * 0.8, behavior: 'smooth' })
  }

  return (
    <div className="group/shelf relative">
      <div
        ref={ref}
        className="no-scrollbar -mx-1 flex snap-x snap-proximity gap-3 overflow-x-auto px-1 pb-1"
      >
        {children}
      </div>

      {([-1, 1] as const).map((dir) => {
        // شورون همیشه به چپ رسم می‌شود (flip خاموش)؛ کدام دکمه به چپ اشاره کند
        // به جهت صفحه بستگی دارد، نه به «قبلی/بعدی»
        const pointsLeft = (dir === -1) !== (lang === 'fa')
        return (
          <button
            key={dir}
            onClick={() => scroll(dir)}
            aria-label={dir === -1 ? t.shelfPrev : t.shelfNext}
            className={`glass-chip absolute top-1/2 hidden size-8 -translate-y-1/2 place-items-center rounded-full text-muted opacity-0 shadow-lg shadow-black/30 transition hover:text-fg focus-visible:opacity-100 group-hover/shelf:opacity-100 sm:grid ${
              dir === -1 ? 'start-[-0.75rem]' : 'end-[-0.75rem]'
            }`}
          >
            <ChevronIcon flip={false} className={`size-4 ${pointsLeft ? '' : 'rotate-180'}`} />
          </button>
        )
      })}
    </div>
  )
}

/** یک فایلِ آماده روی دیسک — کلیک یعنی «از همین‌جا تا آخرِ ردیف را پخش کن» */
export const TrackTile = memo(function TrackTile({
  item,
  queue,
  index,
  // قفسه‌ها عرضِ ثابت و snap می‌دهند؛ نمای شبکه‌ایِ کتابخانه `w-full` می‌فرستد
  className = 'w-32 shrink-0 snap-start sm:w-36',
}: {
  item: LibraryItem
  queue: PlayItem[]
  index: number
  className?: string
}) {
  const { t } = useI18n()
  const play = usePlayer((s) => s.play)
  const toggle = usePlayer((s) => s.toggle)
  /*
   * سلکتورِ primitive (مثل LibraryRow): با `playing` عمومی، هر play/pause
   * کلِ قفسه و شبکه را از نو می‌راند؛ این‌طور فقط کاشتی که وضعیتش عوض شده
   * رندر می‌کند.
   */
  const jobId = item.jobId
  const isCurrent = usePlayer((s) => s.queue[s.index]?.id === jobId)
  const isPlaying = usePlayer((s) => s.playing && s.queue[s.index]?.id === jobId)
  const { track } = item

  return (
    <button
      onClick={() => (isCurrent ? toggle() : play(queue, index))}
      aria-label={isPlaying ? t.pause : t.playTrack(track.title)}
      className={`group relative overflow-hidden rounded-xl p-2 text-start transition hover:bg-panel-2 ${className}`}
    >
      <ArtBackdrop src={track.artworkUrl} seed={track.albumId ?? track.id} />
      <div className="relative">
        <Artwork
          src={track.artworkUrl}
          alt={track.album ?? track.title}
          seed={track.albumId ?? track.id}
          className="aspect-square w-full shadow-lg shadow-black/25"
        />
        <span
          className={`absolute bottom-2 end-2 grid size-9 place-items-center rounded-full bg-accent text-accent-fg shadow-lg shadow-black/40 transition ${
            isCurrent
              ? 'opacity-100'
              : 'hover-reveal translate-y-1.5 opacity-0 group-hover:translate-y-0 group-hover:opacity-100'
          }`}
        >
          {isPlaying ? <PauseIcon className="size-4" /> : <PlayIcon className="size-4" />}
        </span>
        {/* پلتفرمِ منبع — گوشه‌ی پایینِ کاور، با پس‌زمینه تا روی هر کادری خوانا بماند */}
        <span
          title={SOURCE_LABEL[track.source]}
          className="glass-chip absolute bottom-1.5 start-1.5 grid size-6 place-items-center rounded-full"
        >
          <SourceLogo source={track.source} className="size-3.5" />
          <span className="sr-only">{SOURCE_LABEL[track.source]}</span>
        </span>
      </div>
      <p className={`bidi mt-2 truncate text-xs ${isCurrent ? 'text-accent' : ''}`}>
        {track.title}
      </p>
      <p className="bidi truncate text-[10px] text-muted-2">{track.artist}</p>
    </button>
  )
})
