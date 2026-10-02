import { api } from '../lib/api'
import {
  duration as fmtDuration,
  percent as fmtPercent,
  digits,
  fileExt,
  formatLabel,
  safeFilename,
} from '../lib/format'
import { useI18n } from '../lib/i18n'
import type { Track } from '../lib/types'
import { isActive, useDownloads, useTrackJob } from '../store/downloads'
import { usePlayer } from '../store/player'
import { useSettings } from '../store/settings'
import { useToasts } from '../store/toasts'
import { toPlayItem } from '../lib/stream'
import { useRowSwipe } from '../lib/useRowSwipe'
import { canSaveToDevice, haptic, saveToDevice } from '../lib/native'
import Artwork from './Artwork'
import SendToTelegram from './SendToTelegram'
import SourceBadge from './SourceBadge'
import {
  CheckIcon,
  DownloadIcon,
  LyricsIcon,
  PauseIcon,
  PlayIcon,
  RetryIcon,
  Spinner,
  WarnIcon,
} from './icons'

interface Props {
  track: Track
  /** شماره‌ی ترک در آلبوم؛ در نتایج جستجو معنا ندارد */
  index?: number
  selectable?: boolean
  selected?: boolean
  onToggleSelect?: () => void
  playingId: string | null
  onTogglePlay: (track: Track) => void
  showSource?: boolean
}

export default function TrackRow({
  track,
  index,
  selectable = false,
  selected = false,
  onToggleSelect,
  playingId,
  onTogglePlay,
  showSource = false,
}: Props) {
  const quality = useSettings((s) => s.quality)
  // با همان کیفیتی که دکمه‌ی این ردیف دانلود را ثبت می‌کند — وگرنه ردیف
  // وضعیتِ یک دانلودِ دیگر (کیفیتِ دیگر) را نشان می‌دهد
  const job = useTrackJob(track.id, quality)
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
      className={`group relative flex items-center gap-2 overflow-hidden rounded-lg px-1.5 py-2 transition sm:gap-3 sm:px-2 ${
        selected
          ? 'bg-accent-dim'
          : isCurrent
            ? 'bg-accent/8 border border-accent/20'
            : 'border border-transparent hover:bg-panel-2'
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
          className={`relative grid size-5 shrink-0 place-items-center rounded border transition sm:size-4 ${
            selected ? 'border-accent bg-accent text-accent-fg' : 'border-muted-2 hover:border-fg'
          }`}
        >
          {selected && <CheckIcon className="size-2.5" />}
        </button>
      )}

      {index !== undefined && (
        <span className="relative w-4 shrink-0 text-center text-[11px] tabular-nums text-muted-2">
          {digits(index, lang)}
        </span>
      )}

      <button
        type="button"
        onClick={() => onTogglePlay(track)}
        aria-label={playing ? t.pause : t.playTrack(track.title)}
        className="group/art relative size-10 shrink-0 overflow-hidden rounded-lg shadow-sm border border-white/10 text-start"
      >
        <Artwork
          src={track.artworkUrl}
          alt={track.album ?? track.title}
          seed={track.albumId ?? track.id}
          className="size-full object-cover transition duration-200 group-hover/art:scale-105"
        />
        <span
          className={`absolute inset-0 grid place-items-center bg-black/45 transition-opacity ${
            isCurrent ? 'opacity-100' : 'opacity-0 group-hover/art:opacity-100'
          }`}
        >
          {playing ? (
            <PauseIcon className="size-4 text-white" />
          ) : (
            <PlayIcon className="size-4 text-white ms-0.5" />
          )}
        </span>
      </button>

      <div className="relative min-w-0 flex-1">
        <div className="flex items-center gap-2">
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
          {showSource && <SourceBadge source={track.source} />}
        </div>
        <p className="bidi truncate text-xs text-muted">{track.artist}</p>
      </div>

      <div className="relative flex shrink-0 items-center gap-0.5 sm:gap-1">
        {/* روی موبایل، پیشرفت را همان پرشدنِ پس‌زمینه‌ی ردیف می‌گوید — متنِ
            وضعیت فقط عرضی می‌خورد که عنوان آهنگ لازمش دارد */}
        {statusText && <span className="me-1 hidden text-[11px] text-muted sm:inline">{statusText}</span>}

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

        <button
          onClick={() => onTogglePlay(track)}
          aria-label={playing ? t.pause : t.play}
          title={playing ? t.pause : t.play}
          className={`grid size-8 place-items-center rounded-md transition hover:bg-panel-2 sm:size-7 ${
            isCurrent ? 'text-accent' : 'text-muted hover:text-fg'
          }`}
        >
          {playing ? <PauseIcon className="size-4" /> : <PlayIcon className="size-4" />}
        </button>

        <span className="hidden w-9 text-center text-[11px] tabular-nums text-muted-2 sm:inline">
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

        <SendToTelegram target={{ kind: 'track', track }} />

        {job?.lyricsUrl && (
          <a
            href={job.lyricsUrl}
            download
            title={t.lyrics}
            aria-label={t.lyrics}
            className="grid size-7 place-items-center rounded-md text-muted transition hover:bg-panel-2 hover:text-fg"
          >
            <LyricsIcon className="size-4" />
          </a>
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
            onClick={() =>
              enqueue(track, quality, { title: track.album ?? track.title })
            }
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
