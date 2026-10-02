import { useMemo } from 'react'
import { api } from '../lib/api'
import {
  digits,
  duration as fmtDuration,
  fileExt,
  formatLabel,
  percent as fmtPercent,
  safeFilename,
} from '../lib/format'
import { useI18n } from '../lib/i18n'
import type { Album, Track } from '../lib/types'
import { isActive, useDownloads, useTrackJob } from '../store/downloads'
import { useFavorites } from '../store/favorites'
import { usePlayer } from '../store/player'
import { useSettings } from '../store/settings'
import { useToasts } from '../store/toasts'
import { canSaveToDevice, haptic, saveToDevice } from '../lib/native'
import Artwork from './Artwork'
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
  /** شماره‌ی رتبه‌ی ترک در لیست برترین‌ها (۱، ۲، ...) */
  index: number
  playingId: string | null
  onTogglePlay: (track: Track) => void
  onOpenAlbum?: (album: Album) => void
  artistAlbums?: Album[]
}

/**
 * ردیف ترک در بخش آهنگ‌های برتر صفحه‌ی هنرمند:
 *
 * - ستون شماره‌ی رتبه با هاور به دکمه‌ی Play و هنگام پخش به Equalizer متحرک تبدیل می‌شود.
 * - تصویر مینیاتوری کاور آلبوم/تک‌آهنگ مربوط به همان قطعه.
 * - ستون عنوان و نشان Explicit.
 * - ستون نام آلبوم با امکان ناوبری سریع در صورت وجود در دیسکوگرافی.
 * - ستون مدت‌زمان و اکشن‌های سریع (دانلود، تلگرام، متن، لایک).
 */
export default function ArtistTrackRow({
  track,
  index,
  playingId,
  onTogglePlay,
  onOpenAlbum,
  artistAlbums,
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

  const matchedAlbum = useMemo(() => {
    if (!track.album) return null
    if (artistAlbums?.length) {
      const lower = track.album.toLowerCase().trim()
      const found = artistAlbums.find(
        (a) => (track.albumId && a.id === track.albumId) || a.title.toLowerCase().trim() === lower,
      )
      if (found) return found
    }
    // اگر آلبوم در فهرست دیسکوگرافی اولیه نبود ولی شناسه دارد،
    // موجودیت مناسبی می‌سازیم تا کلیک روی نام آلبوم همیشه کار کند
    if (track.albumId) {
      return {
        id: track.albumId,
        title: track.album,
        artist: track.artist,
        year: track.year ?? 0,
        artworkUrl: track.artworkUrl,
        trackCount: 0,
        source: track.source,
        sourceUrl: '',
      } as Album
    }
    return null
  }, [artistAlbums, track.album, track.albumId, track.artist, track.artworkUrl, track.source, track.year])

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

  return (
    <div
      onMouseEnter={() => {
        if (!job) void api.prefetchStream?.(track)
      }}
      className={`group relative flex items-center gap-2 overflow-hidden rounded-xl px-2.5 py-2 transition sm:gap-3 ${
        isCurrent
          ? 'bg-accent/10 border border-accent/25'
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

      {/* ستون شماره رتبه / دکمه پخش / اکولایزر */}
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

      {/* کاور کوچک قطعه با قابلیت کلیک برای پخش */}
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
          rounded="rounded-lg"
          className="size-full object-cover transition duration-200 group-hover/art:scale-105"
        />
        <span
          className={`absolute inset-0 grid place-items-center bg-black/45 transition-opacity ${
            isCurrent ? 'opacity-100' : 'opacity-0 group-hover/art:opacity-100'
          }`}
        >
          {isCurrent ? (
            playing ? (
              <>
                <EqualizerIcon className="size-4 text-accent transition-opacity group-hover/art:opacity-0" animate={true} />
                <PauseIcon className="absolute size-4 text-white opacity-0 transition-opacity group-hover/art:opacity-100" />
              </>
            ) : (
              <>
                <EqualizerIcon className="size-4 text-accent transition-opacity group-hover/art:opacity-0" animate={false} />
                <PlayIcon className="absolute size-3.5 text-white ms-0.5 opacity-0 transition-opacity group-hover/art:opacity-100" />
              </>
            )
          ) : (
            <PlayIcon className="size-3.5 text-white ms-0.5" />
          )}
        </span>
      </button>

      {/* ستون عنوان ترک + نشان Explicit */}
      <div className="relative min-w-0 flex-1 md:flex-initial md:w-[38%] lg:w-[42%]">
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

        {/* روی موبایل: نام آلبوم یا هنرمند زیر عنوان قرار می‌گیرد */}
        {(track.album || track.artist) && (
          <div className="mt-0.5 md:hidden">
            {track.album && matchedAlbum && onOpenAlbum ? (
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  onOpenAlbum(matchedAlbum)
                }}
                className="bidi block max-w-full truncate text-xs text-muted transition hover:text-accent hover:underline text-start"
              >
                {track.album}
              </button>
            ) : (
              <p className="bidi truncate text-xs text-muted">{track.album ?? track.artist}</p>
            )}
          </div>
        )}
      </div>

      {/* ستون آلبوم روی دسکتاپ — با امکان کلیک برای رفتن به آلبوم */}
      <div className="hidden min-w-0 md:block md:w-[26%] lg:w-[28%]">
        {track.album ? (
          matchedAlbum && onOpenAlbum ? (
            <button
              onClick={(e) => {
                e.stopPropagation()
                onOpenAlbum(matchedAlbum)
              }}
              className="bidi block max-w-full truncate text-xs text-muted transition hover:text-accent hover:underline text-start"
              title={track.album}
            >
              {track.album}
            </button>
          ) : (
            <p className="bidi truncate text-xs text-muted" title={track.album}>
              {track.album}
            </p>
          )
        ) : (
          <span className="text-xs text-muted-2">—</span>
        )}
      </div>

      {/* زمان قطعه روی دسکتاپ */}
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

        <div className="transition-opacity sm:opacity-80 sm:group-hover:opacity-100">
          <SendToTelegram target={{ kind: 'track', track }} />
        </div>

        {job?.lyricsUrl && (
          <a
            href={job.lyricsUrl}
            download
            title={t.lyrics}
            aria-label={t.lyrics}
            className="grid size-7 place-items-center rounded-md text-muted opacity-80 transition hover:bg-panel-2 hover:text-fg group-hover:opacity-100"
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
