import { api } from '../lib/api'
import {
  cleanArtist,
  digits,
  duration as fmtDuration,
  fileExt,
  formatLabel,
  percent as fmtPercent,
  safeFilename,
} from '../lib/format'
import { useI18n } from '../lib/i18n'
import type { Track } from '../lib/types'
import { isActive, useDownloads, useTrackJob } from '../store/downloads'
import { useFavorites } from '../store/favorites'
import { usePlayer } from '../store/player'
import { useSettings } from '../store/settings'
import { useToasts } from '../store/toasts'
import { toPlayItem } from '../lib/stream'
import { useRowSwipe } from '../lib/useRowSwipe'
import { canSaveToDevice, haptic, saveToDevice } from '../lib/native'
import LikeHeart from './LikeHeart'
import SendToTelegram from './SendToTelegram'
import {
  CheckIcon,
  DownloadIcon,
  EqualizerIcon,
  LyricsIcon,
  PauseIcon,
  PlayIcon,
  RetryIcon,
  Spinner,
  WarnIcon,
} from './icons'

interface Props {
  track: Track
  /** شماره‌ی ترک در آلبوم */
  index: number
  playingId: string | null
  onTogglePlay: (track: Track) => void
  /** کلیک روی نامِ آرتیستِ ردیف — صفحه‌ی آرتیستِ همان پلتفرم */
  onOpenArtist?: (ref: string) => void
  selectable?: boolean
  selected?: boolean
  onToggleSelect?: () => void
}

/*
 * ردیفِ ترکِ صفحه‌ی آلبوم — الگوی جدولیِ اسپاتیفای و اپل‌موزیک با چیدمان ستونی دسکتاپ:
 *
 * - روی دسکتاپ: ستون‌های اختصاصی برای شماره، عنوان، هنرمند، زمان و اکشن‌ها تا
 *   هیچ فضای مرده یا فاصله‌ی خالیِ ناهماهنگی بین متادیتا و دکمه‌ها نباشد.
 * - روی موبایل: چیدمان فشرده که هنرمند زیر عنوان قرار می‌گیرد.
 * - شماره‌ی ردیف با هاور به آیکون Play تبدیل می‌شود و با کلیک آهنگ پخش می‌شود.
 * - ترکِ در حال پخش آیکون اکولایزر متحرک و رنگ اکسنت دریافت می‌کند.
 * - دکمه‌های ثانویه (تلگرام، متن ترانه، لایک) در هاور نرم و تمیز ظاهر می‌شوند.
 */
export default function AlbumTrackRow({
  track,
  index,
  playingId,
  onTogglePlay,
  onOpenArtist,
  selectable = false,
  selected = false,
  onToggleSelect,
}: Props) {
  const quality = useSettings((s) => s.quality)
  const job = useTrackJob(track.id, quality)
  const isFavorite = useFavorites((s) => (job ? Boolean(s.items[job.id]) : false))
  const toggleFavorite = useFavorites((s) => s.toggle)
  const { enqueue, cancel, retry } = useDownloads()
  const { t, lang } = useI18n()

  const currentTrackId = usePlayer((s) => s.queue[s.index]?.track?.id)
  const isPlayerPlaying = usePlayer((s) => s.playing)
  const isCurrent = Boolean(
    (playingId && playingId === track.id) || (currentTrackId && currentTrackId === track.id),
  )
  const playing = isCurrent && isPlayerPlaying

  const busy = job ? isActive(job.status) : false
  const fill = job?.status === 'downloading' ? job.percent : 0

  const statusText = (() => {
    if (!job) return null
    switch (job.status) {
      case 'queued':
        return t.stQueued
      case 'searching':
        return t.stSearching
      case 'downloading':
        return t.stDownloading(fmtPercent(job.percent, lang))
      case 'tagging':
        return t.stTagging
      default:
        return null
    }
  })()

  const filename = `${safeFilename(`${track.artist} - ${track.title}`)}.${fileExt(job?.format)}`

  const handleSwipeToQueue = () => {
    const playItem = toPlayItem(track, job, quality)
    usePlayer.getState().enqueue([playItem])
    useToasts.getState().push(t.queueAdded(track.title), 'info')
  }

  const rowRef = useRowSwipe<HTMLDivElement>({
    onStartToEnd: handleSwipeToQueue,
    onEndToStart: handleSwipeToQueue,
    enabled: !selectable,
  })

  return (
    <div
      ref={rowRef}
      onMouseEnter={() => {
        if (!job) void api.prefetchStream?.(track)
      }}
      className={`group relative flex items-center gap-2 overflow-hidden rounded-xl px-2.5 py-2.5 transition sm:gap-3 ${
        selected
          ? 'bg-accent-dim'
          : isCurrent
            ? 'bg-accent/8 border border-accent/20'
            : 'border border-transparent hover:bg-panel-2/80'
      }`}
    >
      {/* پروگرس به‌صورت پُرشدنِ پس‌زمینه‌ی خودِ ردیف */}
      {busy && (
        <>
          <div
            className="pointer-events-none absolute inset-0 origin-left rtl:origin-right bg-accent/8 transition-transform duration-200 ease-linear"
            style={{ transform: `scaleX(${fill / 100})` }}
          />
          <div
            className="pointer-events-none absolute bottom-0 inset-x-0 h-[2px] origin-left rtl:origin-right bg-accent transition-transform duration-200 ease-linear"
            style={{ transform: `scaleX(${fill / 100})` }}
          />
        </>
      )}

      {selectable && (
        <button
          onClick={onToggleSelect}
          role="checkbox"
          aria-checked={selected}
          aria-label={t.selectTrack(track.title)}
          className={`relative grid size-5 shrink-0 place-items-center rounded border transition ${
            selected ? 'border-accent bg-accent text-accent-fg' : 'border-muted-2 hover:border-fg'
          }`}
        >
          {selected && <CheckIcon className="size-2.5" />}
        </button>
      )}

      {/* ستون شماره / دکمه پخش */}
      <button
        onClick={() => onTogglePlay(track)}
        aria-label={playing ? t.pause : t.play}
        title={playing ? t.pause : t.play}
        className="relative grid size-7 shrink-0 place-items-center rounded-lg text-muted-2 transition hover:bg-white/5 hover:text-fg"
      >
        {isCurrent ? (
          <>
            <EqualizerIcon
              className="size-4 text-accent transition-opacity group-hover:opacity-0"
              animate={playing}
            />
            {playing ? (
              <PauseIcon className="absolute size-4 text-accent opacity-0 transition-opacity group-hover:opacity-100" />
            ) : (
              <PlayIcon className="absolute size-4 text-accent opacity-0 transition-opacity group-hover:opacity-100" />
            )}
          </>
        ) : (
          <>
            <span className="text-[13px] font-medium tabular-nums transition-opacity group-hover:opacity-0">
              {digits(index, lang)}
            </span>
            <PlayIcon className="absolute size-4 text-fg opacity-0 transition-opacity group-hover:opacity-100" />
          </>
        )}
      </button>

      {/* ستون عنوان ترک + نشان Explicit */}
      <div className="relative min-w-0 flex-1 md:flex-initial md:w-[46%] lg:w-[48%]">
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => onTogglePlay(track)}
            className="bidi truncate text-start text-sm font-medium transition-colors hover:text-accent"
          >
            <span
              className={`truncate ${
                isCurrent ? 'font-bold text-accent' : 'text-fg/95 group-hover:text-fg'
              }`}
            >
              {track.title}
            </span>
          </button>
          {track.explicit && (
            <span
              title="Explicit"
              className="inline-grid h-3.5 min-w-3.5 place-items-center rounded bg-white/10 px-1 text-[9px] font-bold uppercase text-muted"
            >
              E
            </span>
          )}
        </div>

        {/* روی موبایل نام هنرمند زیر عنوان می‌آید */}
        <div className="mt-0.5 md:hidden">
          {onOpenArtist && track.artistId ? (
            <button
              onClick={(e) => {
                e.stopPropagation()
                onOpenArtist(track.artistId!)
              }}
              className="bidi block max-w-full truncate text-xs text-muted transition hover:text-accent hover:underline"
            >
              {cleanArtist(track.artist)}
            </button>
          ) : (
            <p className="bidi truncate text-xs text-muted">{cleanArtist(track.artist)}</p>
          )}
        </div>
      </div>

      {/* ستون اختصاصی هنرمند روی دسکتاپ — جلوگیری از فضای خالی بزرگ */}
      <div className="hidden min-w-0 md:block md:w-[26%] lg:w-[28%]">
        {onOpenArtist && track.artistId ? (
          <button
            onClick={(e) => {
              e.stopPropagation()
              onOpenArtist(track.artistId!)
            }}
            className="bidi block max-w-full truncate text-xs text-muted transition hover:text-accent hover:underline"
          >
            {cleanArtist(track.artist)}
          </button>
        ) : (
          <p className="bidi truncate text-xs text-muted">{cleanArtist(track.artist)}</p>
        )}
      </div>

      {/* زمان روی دسکتاپ */}
      <span className="hidden w-12 shrink-0 text-center text-xs tabular-nums text-muted-2 md:inline">
        {fmtDuration(track.durationMs, lang)}
      </span>

      {/* ستون عملیات */}
      <div className="relative ms-auto flex shrink-0 items-center gap-0.5 sm:gap-1">
        {/* وضعیت دانلود روی موبایل */}
        {statusText && (
          <span className="me-1 hidden text-[11px] text-muted sm:inline">{statusText}</span>
        )}

        {job?.status === 'error' && (
          <button
            onClick={() => retry(job.id)}
            title={job.error}
            className="me-1 inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-[11px] text-danger hover:bg-panel-2"
          >
            <RetryIcon className="size-3" />
            {t.retry}
          </button>
        )}

        {/* لایک / قلب برای قطعات دانلودشده */}
        {job?.status === 'ready' && (
          <LikeHeart
            liked={isFavorite}
            onToggle={() => toggleFavorite(job.id)}
            ariaLabel={isFavorite ? t.favoriteRemove : t.favoriteAdd}
            className={`grid size-7 place-items-center rounded-md transition hover:bg-panel-2 ${
              isFavorite ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'
            }`}
            iconClassName="size-4"
          />
        )}

        <div className="hidden sm:block transition-opacity sm:opacity-80 sm:group-hover:opacity-100">
          <SendToTelegram target={{ kind: 'track', track }} />
        </div>

        {job?.lyricsUrl && (
          <a
            href={job.lyricsUrl}
            download
            title={t.lyrics}
            aria-label={t.lyrics}
            className="hidden sm:grid size-7 place-items-center rounded-md text-muted opacity-80 transition hover:bg-panel-2 hover:text-fg group-hover:opacity-100"
          >
            <LyricsIcon className="size-4" />
          </a>
        )}

        {/* زمان روی موبایل */}
        <span className="inline w-9 text-center text-[11px] tabular-nums text-muted-2 md:hidden">
          {fmtDuration(track.durationMs, lang)}
        </span>

        {job?.warning && (
          <span
            title={job.warning}
            aria-label={job.warning}
            className="grid size-7 place-items-center text-warn"
          >
            <WarnIcon className="size-4" />
          </span>
        )}

        {job?.status === 'ready' ? (
          <a
            href={job.fileUrl ?? '#'}
            download={job.fileUrl ? filename : undefined}
            onClick={async (e) => {
              if (!job.fileUrl) {
                e.preventDefault()
                return
              }
              if (canSaveToDevice()) {
                e.preventDefault()
                try {
                  await saveToDevice({
                    url: job.fileUrl,
                    title: track.title,
                    artist: track.artist,
                    album: track.album ?? '',
                    ext: fileExt(job.format),
                  })
                  haptic.success()
                  useToasts.getState().push(t.saveToPhoneDone, 'success')
                } catch (err) {
                  haptic.warn()
                  useToasts.getState().push(err instanceof Error ? err.message : t.saveToPhoneFailed, 'error')
                }
              }
            }}
            title={job.fileUrl ? (canSaveToDevice() ? t.saveToPhone : t.save) : t.mockNoFile}
            className="inline-flex items-center gap-1 rounded-md border border-accent/40 bg-accent-dim px-2 py-1 text-[11px] font-semibold text-accent cursor-pointer"
          >
            <CheckIcon className="size-3" />
            {formatLabel(job.format, lang)}
            <DownloadIcon className="size-3" />
          </a>
        ) : busy ? (
          <button
            onClick={() => cancel(job!.id)}
            aria-label={t.cancelDownload}
            className="grid size-8 place-items-center rounded-md text-accent transition hover:bg-panel-2 sm:size-7"
          >
            <Spinner className="size-4" />
          </button>
        ) : (
          <button
            onClick={() => enqueue(track, quality, { title: track.album ?? track.title })}
            aria-label={t.downloadTrack(track.title)}
            className="grid size-8 place-items-center rounded-md text-muted transition hover:bg-panel-2 hover:text-fg sm:size-7"
          >
            <DownloadIcon className="size-4" />
          </button>
        )}
      </div>
    </div>
  )
}
