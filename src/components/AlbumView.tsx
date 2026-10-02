import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../lib/api'
import { digits, safeFilename } from '../lib/format'
import { useI18n } from '../lib/i18n'
import { dominantColor } from '../lib/artColor'
import { findBestJob, toPlayItem } from '../lib/stream'
import { downloadFile } from '../lib/native'
import { SOURCE_LABEL, type Album, type AlbumDetail, type Track } from '../lib/types'
import { isActive, isDone, useDownloads } from '../store/downloads'
import { usePlayer } from '../store/player'
import { useSettings } from '../store/settings'
import { useToasts } from '../store/toasts'
import AlbumTrackRow from './AlbumTrackRow'
import Artwork, { HeroBackdrop } from './Artwork'
import ClickSpark from './ClickSpark'
import EmptyState from './EmptyState'
import SendToTelegram from './SendToTelegram'
import { Shelf, SectionHead } from './Shelf'
import { AlbumCard } from './cards'
import SplitPanel from './SplitPanel'
import SourceLogo from './logos'
import {
  AlbumIcon,
  ArrowIcon,
  CheckIcon,
  DownloadIcon,
  HeadphonesIcon,
  LinkIcon,
  PauseIcon,
  PlayIcon,
  ShuffleIcon,
  Spinner,
  ZipIcon,
} from './icons'

interface Props {
  album: AlbumDetail
  playingId: string | null
  onTogglePlay: (track: Track) => void
  /** کلیک روی نامِ آرتیست — به صفحه‌ی آرتیستِ همان پلتفرم می‌رود */
  onOpenArtist?: (ref: string) => void
  /** کلیک روی آلبوم دیگر از همین هنرمند */
  onOpenAlbum?: (album: Album) => void
  onBack: () => void
}

function longDuration(ms: number, t: ReturnType<typeof useI18n.getState>['t']): string {
  const minutes = Math.round(ms / 60000)
  if (minutes < 60) return t.minutes(minutes)
  return t.hoursMinutes(Math.floor(minutes / 60), minutes % 60)
}

/**
 * دیسک وینیل شیاردارِ تعاملی — با چرخش ملایم هنگام پخش و بیرون‌آمدنِ نرم
 */
function VinylDisc({
  artworkUrl,
  seed,
  isPlaying,
}: {
  artworkUrl: string | null
  seed: string
  isPlaying: boolean
}) {
  return (
    <div
      aria-hidden
      className={`pointer-events-none absolute inset-y-0 start-0 z-0 flex items-center transition-all duration-700 ease-out ${
        isPlaying
          ? 'translate-x-12 rtl:-translate-x-12 sm:translate-x-20 sm:rtl:-translate-x-20 md:translate-x-26 md:rtl:-translate-x-26'
          : 'translate-x-6 rtl:-translate-x-6 group-hover/cover:translate-x-10 group-hover/cover:rtl:-translate-x-10 sm:translate-x-9 sm:rtl:-translate-x-9 sm:group-hover/cover:translate-x-14 sm:group-hover/cover:rtl:-translate-x-14'
      }`}
    >
      <div
        className={`relative aspect-square size-36 sm:size-44 md:size-52 rounded-full p-1 shadow-2xl shadow-black/90 ring-1 ring-white/10 ${
          isPlaying ? 'animate-[spin_7s_linear_infinite]' : ''
        }`}
        style={{
          background:
            'radial-gradient(circle, #1c1c1f 0%, #0c0c0e 38%, #1f1f23 44%, #0c0c0e 52%, #1a1a1d 68%, #09090b 100%)',
        }}
      >
        {/* شیارهای صوتی براق وینیل */}
        <div
          className="absolute inset-0 rounded-full opacity-40"
          style={{
            background:
              'conic-gradient(from 0deg, transparent 0deg, rgba(255,255,255,0.2) 45deg, transparent 90deg, rgba(255,255,255,0.2) 135deg, transparent 180deg, rgba(255,255,255,0.2) 225deg, transparent 270deg, rgba(255,255,255,0.2) 315deg, transparent 360deg)',
          }}
        />

        {/* شیارهای مدور فیزیکی */}
        <div className="absolute inset-2.5 rounded-full border border-white/5" />
        <div className="absolute inset-5 rounded-full border border-white/5" />
        <div className="absolute inset-8 rounded-full border border-white/5" />
        <div className="absolute inset-11 rounded-full border border-white/5" />
        <div className="absolute inset-14 rounded-full border border-white/5" />

        {/* سنتر استیکر با تصویر مینیاتوری کاور */}
        <div className="absolute inset-0 m-auto size-12 sm:size-16 md:size-18 overflow-hidden rounded-full border-2 border-zinc-700 bg-zinc-900 shadow-inner">
          <Artwork
            src={artworkUrl}
            alt=""
            seed={seed}
            rounded="rounded-full"
            className="size-full object-cover"
          />
          {/* سوراخ مرکزی دیسک */}
          <div className="absolute inset-0 m-auto size-3 rounded-full border border-zinc-600 bg-black shadow-inner" />
        </div>
      </div>
    </div>
  )
}

/*
 * نمای آلبوم/تک‌آهنگ/پلی‌لیست بازطراحی‌شده با استانداردهای مدرن:
 *
 * - هدر هیرو با گرادیان تمام‌عرض و محوِ نرم بدون کادرهای بریده‌شده.
 * - دیسک وینیل با انیمیشن چرخش و بیرون‌آمدن تعاملی هنگام پخش آلبوم.
 * - بج‌های شیشه‌ای نوع اثر، پلتفرم منبع و کیفیت صوتی.
 * - نوار اکشن منسجم در یک ردیف (پخش، شافل، دانلود، تلگرام، کپی لینک، زیپ).
 * - نوار چسبان با مینی‌پلیر هنگام اسکرول به پایین.
 * - جدول قطعات با هدر ستون‌های دسکتاپ و لایک اختصاصی هر ترک.
 * - شلف «آثار دیگر از این هنرمند» در انتهای صفحه برای ادامه‌ی کاوش.
 */
export default function AlbumView({
  album,
  playingId,
  onTogglePlay,
  onOpenArtist,
  onOpenAlbum,
  onBack,
}: Props) {
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [selectionMode, setSelectionMode] = useState(false)
  const [zipping, setZipping] = useState(false)
  const [tint, setTint] = useState<[number, number, number] | null>(null)
  const [moreAlbums, setMoreAlbums] = useState<Album[]>([])
  const [isScrolledPast, setIsScrolledPast] = useState(false)
  const heroRef = useRef<HTMLDivElement>(null)

  const quality = useSettings((s) => s.quality)
  const { enqueueMany, jobs } = useDownloads()
  const { t, lang } = useI18n()
  const pushToast = useToasts((s) => s.push)
  const play = usePlayer((s) => s.play)

  const albumTrackIds = useMemo(() => new Set(album.tracks.map((x) => x.id)), [album])
  const own = jobs.filter((j) => albumTrackIds.has(j.track.id))
  const activeCount = own.filter((j) => isActive(j.status)).length
  const readyJobs = own.filter((j) => isDone(j.status))

  const allSelected = selected.size === album.tracks.length && album.tracks.length > 0
  const targets = selected.size ? album.tracks.filter((x) => selected.has(x.id)) : album.tracks

  const toggleAll = () =>
    setSelected(allSelected ? new Set() : new Set(album.tracks.map((x) => x.id)))

  const toggleOne = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })

  // رنگِ غالبِ کاور
  useEffect(() => {
    let cancelled = false
    void dominantColor(album.artworkUrl).then((c) => {
      if (!cancelled) setTint(c)
    })
    return () => {
      cancelled = true
    }
  }, [album.artworkUrl])

  const anyTint = tint ? tint.join(',') : '107,107,107'

  // واکشی سایر آثار هنرمند به صورت پس‌زمینه
  useEffect(() => {
    if (!album.artistId) return
    let cancelled = false
    api.getArtist(album.artistId)
      .then((detail) => {
        if (cancelled) return
        const others = detail.albums.filter((a) => a.id !== album.id && a.title !== album.title)
        setMoreAlbums(others)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [album.artistId, album.id, album.title])

  // رصد اسکرول برای فعال‌سازی مینی‌پلیر در نوار چسبان
  useEffect(() => {
    const el = heroRef.current
    if (!el) return
    const observer = new IntersectionObserver(
      ([entry]) => {
        setIsScrolledPast(!entry.isIntersecting)
      },
      { threshold: 0.1 },
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  // پلی‌لیست و تک‌آهنگ هم در همین قالب می‌آیند
  const typeLabel =
    album.id.includes(':playlist:') ? t.typePlaylist : album.tracks.length === 1 ? t.typeSong : t.typeAlbum

  /** تمام ترک‌های آلبوم با متادیتای غنی‌شده (کاور و عنوان والد) قابل پخش‌اند */
  const playableItems = useMemo(
    () =>
      album.tracks.map((track) => {
        const enriched: Track = {
          ...track,
          album: track.album || album.title,
          albumId: track.albumId || album.id,
          artworkUrl: track.artworkUrl || album.artworkUrl,
          artistId: track.artistId || (track.artist === album.artist ? album.artistId : undefined),
          artistArtworkUrl: track.artistArtworkUrl || (track.artist === album.artist ? album.artistArtworkUrl : undefined),
        }
        const job = findBestJob(readyJobs, track.id, quality)
        return toPlayItem(enriched, job, quality)
      }),
    [album.artist, album.artistId, album.artistArtworkUrl, album.artworkUrl, album.id, album.title, album.tracks, readyJobs, quality],
  )

  const currentTrackId = usePlayer((s) => s.queue[s.index]?.track?.id)
  const isPlaying = usePlayer((s) => s.playing)
  const queue = usePlayer((s) => s.queue)
  const activePlayingId = playingId ?? (isPlaying ? currentTrackId ?? null : null)

  const isCurrentAlbumQueue = useMemo(() => {
    if (queue.length === 0 || album.tracks.length === 0) return false
    if (queue.length !== album.tracks.length) return false
    return album.tracks.every((t, i) => queue[i]?.track?.id === t.id)
  }, [queue, album.tracks])

  const isTrackFromAlbumActive = Boolean(currentTrackId && albumTrackIds.has(currentTrackId))
  const isThisAlbumPlaying = (isCurrentAlbumQueue || isTrackFromAlbumActive) && isPlaying

  // پیش‌گرم‌سازی ۳ ترک اول آلبوم در پس‌زمینه
  useEffect(() => {
    const tracksToWarm = album.tracks.slice(0, 3)
    if (!tracksToWarm.length) return

    const timers: ReturnType<typeof setTimeout>[] = []
    tracksToWarm.forEach((track, i) => {
      const alreadyDownloaded = jobs.some((j) => j.track.id === track.id && isDone(j.status))
      if (alreadyDownloaded) return

      const timer = setTimeout(() => {
        void api.prefetchStream?.(track)
      }, i * 600)
      timers.push(timer)
    })

    return () => {
      timers.forEach((t) => clearTimeout(t))
    }
  }, [album.id, album.tracks, jobs])

  const handleTrackToggle = useCallback(
    (track: Track) => {
      const enriched: Track = {
        ...track,
        album: track.album || album.title,
        albumId: track.albumId || album.id,
        artworkUrl: track.artworkUrl || album.artworkUrl,
        artistId: track.artistId || (track.artist === album.artist ? album.artistId : undefined),
        artistArtworkUrl: track.artistArtworkUrl || (track.artist === album.artist ? album.artistArtworkUrl : undefined),
      }
      if (currentTrackId === track.id) {
        usePlayer.getState().toggle()
      } else if (onTogglePlay) {
        onTogglePlay(enriched)
      } else {
        const idx = album.tracks.findIndex((t) => t.id === track.id)
        play(playableItems, Math.max(0, idx))
      }
    },
    [album.artist, album.artistId, album.artistArtworkUrl, album.artworkUrl, album.id, album.title, album.tracks, currentTrackId, onTogglePlay, play, playableItems],
  )

  const togglePlayAll = useCallback(() => {
    if (!playableItems.length) return
    if (isThisAlbumPlaying) {
      usePlayer.getState().pause()
    } else if (isCurrentAlbumQueue) {
      usePlayer.getState().toggle()
    } else {
      usePlayer.getState().setShuffle(false)
      play(playableItems, 0)
    }
  }, [isThisAlbumPlaying, isCurrentAlbumQueue, play, playableItems])

  const handleShufflePlay = useCallback(() => {
    if (!playableItems.length) return
    const randomIdx = Math.floor(Math.random() * playableItems.length)
    usePlayer.getState().setShuffle(true)
    play(playableItems, randomIdx)
  }, [play, playableItems])

  const copyAlbumLink = async () => {
    const url = album.sourceUrl || window.location.href
    try {
      await navigator.clipboard.writeText(url)
      pushToast(t.linkCopied, 'info')
    } catch {
      // fallback
    }
  }

  async function downloadZip() {
    setZipping(true)
    try {
      const url = await api.zip(
        readyJobs.map((j) => ({ trackId: j.track.id, quality: j.quality })),
        safeFilename(`${album.artist} - ${album.title}`),
      )
      if (!url) {
        pushToast(t.mockNoFile, 'info')
        return
      }
      await downloadFile(url)
    } catch {
      pushToast(t.toastZipFailed, 'error')
    } finally {
      setZipping(false)
    }
  }

  return (
    <div className="rise pb-6">
      {/* دکمه‌ی بازگشت */}
      <div className="mb-2 px-1 pt-1 sm:px-2">
        <button
          onClick={onBack}
          className="inline-flex items-center gap-1.5 py-1 text-xs text-muted transition hover:text-fg"
        >
          <ArrowIcon className="size-3.5 -scale-x-100 rtl:scale-x-100" />
          <span>{t.backToResults}</span>
        </button>
      </div>

      {/* ─── هیرو: بک‌دراپ محیطی تمام‌عرض با فِید نرم به پس‌زمینه ─── */}
      <div
        ref={heroRef}
        className="relative -mx-2 -mt-2 mb-6 overflow-hidden rounded-3xl p-5 sm:-mx-4 sm:p-7 md:p-8"
        style={{
          background: `
            radial-gradient(ellipse 90% 70% at 50% -10%, rgb(${anyTint} / 0.42), transparent 75%),
            linear-gradient(to bottom, rgb(${anyTint} / 0.16) 0%, transparent 100%)
          `,
        }}
      >
        {/* لایه‌ی محوِ تصویر کاور در پس‌زمینه با ماسک نرم */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 -z-10 opacity-60 blur-3xl"
          style={{
            maskImage: 'linear-gradient(to bottom, black 30%, transparent 100%)',
            WebkitMaskImage: 'linear-gradient(to bottom, black 30%, transparent 100%)',
          }}
        >
          <HeroBackdrop src={album.artworkUrl} seed={album.id} />
        </div>

        <div className="relative flex flex-col gap-6 sm:flex-row sm:items-end sm:gap-8">
          {/* بخش کاور با دیسک وینیل */}
          <div className="group/cover relative shrink-0 self-center sm:self-auto">
            <VinylDisc
              artworkUrl={album.artworkUrl}
              seed={album.id}
              isPlaying={isThisAlbumPlaying}
            />

            {/* هاله‌ی درخشان رنگ کاور */}
            <div
              aria-hidden
              className="pointer-events-none absolute inset-0 rounded-2xl opacity-60 blur-2xl transition-opacity duration-500 group-hover/cover:opacity-85"
              style={{ background: `rgb(${anyTint} / 0.7)` }}
            />

            {/* جلد آلبوم */}
            <div className="relative z-10 overflow-hidden rounded-2xl border border-white/15 bg-panel shadow-2xl shadow-black/80 transition-transform duration-300 group-hover/cover:scale-[1.02]">
              <Artwork
                src={album.artworkUrl}
                alt={album.title}
                seed={album.id}
                className="size-44 object-cover sm:size-48 md:size-56"
                rounded="rounded-2xl"
              />
              {/* برق شیشه‌ای روی کاور */}
              <div className="pointer-events-none absolute inset-0 bg-gradient-to-tr from-white/10 via-transparent to-white/5 opacity-70" />
            </div>
          </div>

          {/*
            متادیتا کنار کاور است و دیسک با position مطلق از جعبهٔ کاور بیرون
            می‌زند — پس روی عنوان می‌افتد. کلاس album-hero-meta همان سفرِ
            اضافهٔ وینیل را padding-inline-start می‌کند تا متن و دیسک با هم
            حرکت کنند. فقط از sm به بالا: زیر sm هیرو ستونی است.
          */}
          <div
            data-album-hero-meta
            data-playing={isThisAlbumPlaying ? '' : undefined}
            className="album-hero-meta min-w-0 flex-1 text-center sm:text-start"
          >
            {/* ردیف بج‌های شیشه‌ای */}
            <div className="mb-2.5 flex flex-wrap items-center justify-center gap-2 sm:justify-start">
              <span className="glass-chip inline-flex items-center gap-1.5 rounded-full border border-white/15 px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-white shadow-sm">
                <AlbumIcon className="size-3 text-accent" />
                <span>{typeLabel}</span>
              </span>

              {album.source && (
                <span className="glass-chip inline-flex items-center gap-1.5 rounded-full border border-white/15 px-2.5 py-0.5 text-[10px] font-medium text-white/90 shadow-sm">
                  <SourceLogo source={album.source} className="size-3" />
                  <span>{SOURCE_LABEL[album.source]}</span>
                </span>
              )}

              <span className="glass-chip inline-flex items-center gap-1 rounded-full border border-white/15 px-2 py-0.5 text-[10px] font-semibold text-accent/95 shadow-sm">
                <HeadphonesIcon className="size-3" />
                <span>{quality.toUpperCase()}</span>
              </span>
            </div>

            {/* عنوان اصلی */}
            <h1 className="bidi-hero relative z-10 w-full text-2xl font-black leading-[1.18] [word-break:break-word] [text-wrap:balance] drop-shadow-[0_2px_12px_rgb(0_0_0/0.6)] text-center sm:text-start sm:text-4xl md:text-5xl">
              {album.title}
            </h1>

            {/* خط جزئیات: هنرمند، تعداد ترک، مدت، سال */}
            <div className="relative z-10 mt-3 flex flex-wrap items-center justify-center gap-x-2 gap-y-1 text-sm text-muted drop-shadow-[0_1px_6px_rgb(0_0_0/0.6)] sm:justify-start">
              {onOpenArtist && album.artistId ? (
                <button
                  onClick={() => onOpenArtist(album.artistId!)}
                  className="group/artist inline-flex items-center gap-1.5 rounded-full bg-white/5 px-2.5 py-1 font-semibold text-fg backdrop-blur-md ring-1 ring-white/15 transition hover:bg-white/10 hover:text-accent hover:ring-accent/40"
                  title={album.artist}
                >
                  <Artwork
                    src={album.artistArtworkUrl ?? null}
                    alt=""
                    seed={album.artistId}
                    rounded="rounded-full"
                    className="size-5 ring-1 ring-white/20"
                  />
                  <bdi className="underline-offset-2 group-hover/artist:underline">
                    {album.artist}
                  </bdi>
                </button>
              ) : (
                <span className="inline-flex items-center gap-1.5 font-semibold text-fg">
                  <bdi>{album.artist}</bdi>
                </span>
              )}

              <span aria-hidden className="text-muted-2">·</span>
              <span>{t.trackCount(album.trackCount)}</span>
              <span aria-hidden className="text-muted-2">·</span>
              <span>{longDuration(album.durationMs, t)}</span>
              {album.year ? (
                <>
                  <span aria-hidden className="text-muted-2">·</span>
                  <span>{digits(album.year, lang)}</span>
                </>
              ) : null}
            </div>

            {/* اکشن‌بار منسجم */}
            <div className="mt-6 flex flex-wrap items-center justify-center gap-3 sm:justify-start">
              {album.tracks.length > 0 && (
                <ClickSpark>
                  <button
                    onClick={togglePlayAll}
                    aria-label={isThisAlbumPlaying ? t.pause : t.playAll}
                    title={isThisAlbumPlaying ? t.pause : t.playAll}
                    className="grid size-14 place-items-center rounded-full bg-accent text-accent-fg shadow-xl shadow-accent/25 transition enabled:hover:scale-105 enabled:active:scale-95"
                  >
                    {isThisAlbumPlaying ? <PauseIcon className="size-6" /> : <PlayIcon className="size-6 ms-0.5" />}
                  </button>
                </ClickSpark>
              )}

              {/* دکمه شافل */}
              {album.tracks.length > 1 && (
                <button
                  onClick={handleShufflePlay}
                  aria-label={t.shufflePlay}
                  title={t.shufflePlay}
                  className="grid size-11 place-items-center rounded-full border border-white/15 bg-white/5 text-fg backdrop-blur-md transition hover:border-accent/40 hover:bg-white/10 hover:text-accent active:scale-95"
                >
                  <ShuffleIcon className="size-5" />
                </button>
              )}

              {/* دکمه دانلود همه */}
              {(activeCount > 0 || readyJobs.length < album.tracks.length) && (
                <ClickSpark className="flex-1 sm:flex-none">
                  <button
                    onClick={() =>
                      enqueueMany(targets, quality, {
                        title: album.title,
                        artworkUrl: album.artworkUrl,
                      })
                    }
                    disabled={targets.length === 0 || activeCount > 0}
                    className="inline-flex w-full items-center justify-center gap-2 rounded-full bg-accent px-5 py-3 text-sm font-bold text-accent-fg shadow-lg shadow-accent/20 transition enabled:hover:brightness-110 disabled:opacity-60 active:scale-95 sm:w-auto"
                  >
                    {activeCount > 0 ? (
                      <>
                        <Spinner className="size-4" />
                        <span>{t.ofTotal(readyJobs.length, readyJobs.length + activeCount)}</span>
                      </>
                    ) : (
                      <>
                        <DownloadIcon className="size-4" />
                        <span>{selected.size ? t.downloadN(selected.size) : t.downloadAll}</span>
                      </>
                    )}
                  </button>
                </ClickSpark>
              )}

              {/* تلگرام */}
              <SendToTelegram
                target={{ kind: 'album', ref: album.sourceUrl || album.id, title: album.title }}
                className="grid size-11 place-items-center rounded-full border border-white/15 bg-white/5 backdrop-blur-md transition hover:border-white/30 hover:bg-white/10"
              />

              {/* کپی لینک */}
              {album.sourceUrl && (
                <button
                  onClick={copyAlbumLink}
                  title={t.copyLink}
                  aria-label={t.copyLink}
                  className="grid size-11 place-items-center rounded-full border border-white/15 bg-white/5 text-muted backdrop-blur-md transition hover:border-white/30 hover:bg-white/10 hover:text-fg active:scale-95"
                >
                  <LinkIcon className="size-4" />
                </button>
              )}

              {/* فایل ZIP */}
              {readyJobs.length > 0 && (
                <button
                  onClick={downloadZip}
                  disabled={zipping}
                  title={t.zipTitle}
                  className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/5 px-4 py-2.5 text-sm font-medium text-fg backdrop-blur-md transition hover:border-white/30 hover:bg-white/10 disabled:opacity-45"
                >
                  {zipping ? <Spinner className="size-4" /> : <ZipIcon className="size-4" />}
                  <span>{t.zip(readyJobs.length)}</span>
                </button>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* یک لینکِ یوتیوب که فقط «یک ترک» است اگر چپتر داشته باشد، تکه‌اش می‌کند */}
      {album.tracks.length === 1 && album.source === 'youtube' && album.sourceUrl && (
        <div className="mb-4 border-b border-line-soft py-3">
          <SplitPanel url={album.sourceUrl} />
        </div>
      )}

      {/* نوار چسبان: نمایش کنترل‌ها و مینی‌پلیر هنگام اسکرول */}
      <div className="glass-bar sticky top-[calc(3.5rem+env(safe-area-inset-top,0px))] z-20 mb-3 flex flex-wrap items-center justify-between gap-3 rounded-2xl border-b border-line-soft px-3 py-2.5 sm:px-4">
        {/* در حالت اسکرول: مینی پلیر آلبوم ظاهر می‌شود */}
        {isScrolledPast ? (
          <div className="flex min-w-0 items-center gap-3">
            <Artwork
              src={album.artworkUrl}
              alt=""
              seed={album.id}
              className="size-8 shrink-0 shadow-sm"
              rounded="rounded-lg"
            />
            <div className="min-w-0">
              <p className="bidi truncate text-xs font-bold text-fg">{album.title}</p>
              <p className="bidi truncate text-[10px] text-muted">{album.artist}</p>
            </div>
            <button
              onClick={togglePlayAll}
              aria-label={isThisAlbumPlaying ? t.pause : t.playAll}
              className="grid size-8 shrink-0 place-items-center rounded-full bg-accent text-accent-fg shadow-sm transition hover:scale-105 active:scale-95"
            >
              {isThisAlbumPlaying ? <PauseIcon className="size-4" /> : <PlayIcon className="size-4 ms-0.5" />}
            </button>
          </div>
        ) : (
          /* در بالای صفحه: دکمه انتخاب چندتایی و راهنما */
          <div className="flex items-center gap-2">
            <button
              onClick={() => {
                if (!selectionMode) {
                  setSelectionMode(true)
                } else {
                  toggleAll()
                }
              }}
              className="inline-flex items-center gap-1.5 rounded-lg border border-line px-2.5 py-1 text-xs font-medium text-fg transition hover:border-muted-2 hover:bg-panel-2"
            >
              <span
                className={`grid size-4 place-items-center rounded border transition ${
                  allSelected ? 'border-accent bg-accent text-accent-fg' : 'border-muted-2'
                }`}
              >
                {allSelected && <CheckIcon className="size-2.5" />}
              </span>
              <span>
                {allSelected ? t.clearSelection : selectionMode ? t.selectAll : t.selectMultiple}
              </span>
            </button>

            {selectionMode && (
              <span className="text-[11px] text-muted-2">
                {selected.size ? t.downloadN(selected.size) : t.tickHint(album.trackCount)}
              </span>
            )}
          </div>
        )}

        {/* سمت دیگر نوار چسبان: اکشن‌های انتخابی */}
        <div className="ms-auto flex items-center gap-2">
          {selectionMode && selected.size > 0 && (
            <button
              onClick={() =>
                enqueueMany(targets, quality, {
                  title: album.title,
                  artworkUrl: album.artworkUrl,
                })
              }
              className="inline-flex items-center gap-1.5 rounded-full bg-accent px-3 py-1 text-xs font-semibold text-accent-fg transition hover:brightness-110"
            >
              <DownloadIcon className="size-3" />
              <span>{t.downloadN(selected.size)}</span>
            </button>
          )}
          {selectionMode && (
            <button
              onClick={() => {
                setSelectionMode(false)
                setSelected(new Set())
              }}
              className="text-xs text-muted transition hover:text-fg"
            >
              {t.close}
            </button>
          )}
        </div>
      </div>

      {album.tracks.length === 0 ? (
        <div className="my-8">
          <EmptyState
            icon={<AlbumIcon className="size-6 text-muted-2" />}
            text={t.noResults(album.title)}
          />
        </div>
      ) : (
        <>
          {/* هدر ستون‌های جدول روی دسکتاپ */}
          <div className="hidden border-b border-line-soft px-3 pb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-2 md:flex md:items-center md:gap-3">
            <span className="w-7 text-center">{t.tableHeaderNumber}</span>
            <span className="w-[46%] lg:w-[48%]">{t.tableHeaderTitle}</span>
            <span className="w-[26%] lg:w-[28%]">{t.tableHeaderArtist}</span>
            <span className="w-12 text-center">{t.tableHeaderDuration}</span>
            <span className="ms-auto pe-2 text-end">{t.tableHeaderActions}</span>
          </div>

          {/* فهرست ترک‌ها */}
          <div className="space-y-0.5 px-1 sm:px-2">
            {album.tracks.map((track, i) => (
              <AlbumTrackRow
                key={track.id}
                track={{
                  ...track,
                  album: track.album || album.title,
                  albumId: track.albumId || album.id,
                  artworkUrl: track.artworkUrl || album.artworkUrl,
                  artistId: track.artistId || (track.artist === album.artist ? album.artistId : undefined),
                  artistArtworkUrl: track.artistArtworkUrl || (track.artist === album.artist ? album.artistArtworkUrl : undefined),
                }}
                index={i + 1}
                selectable={selectionMode}
                selected={selected.has(track.id)}
                onToggleSelect={() => toggleOne(track.id)}
                playingId={activePlayingId}
                onTogglePlay={handleTrackToggle}
                onOpenArtist={onOpenArtist}
              />
            ))}
          </div>
        </>
      )}

      {/* شناسنامه و کپی‌رایت انتهای آلبوم */}
      <footer className="mt-8 border-t border-line-soft/60 px-3 pt-6 text-xs text-muted-2">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="bidi font-medium">
            {album.year ? `℗ ${digits(album.year, lang)} ${album.artist}` : `℗ ${album.artist}`}
          </p>
          <p className="tabular-nums">
            {t.trackCount(album.tracks.length)} · {longDuration(album.durationMs, t)}
          </p>
        </div>
      </footer>

      {/* شلف آثار دیگر از همین هنرمند */}
      {moreAlbums.length > 0 && (
        <section className="mt-12 border-t border-line-soft pt-8">
          <SectionHead
            title={t.moreByArtist(album.artist)}
            hint={album.artist}
            action={
              onOpenArtist && album.artistId ? (
                <button
                  onClick={() => onOpenArtist(album.artistId!)}
                  className="text-xs font-semibold text-accent transition hover:underline"
                >
                  {t.seeAll}
                </button>
              ) : null
            }
          />
          <Shelf>
            {moreAlbums.map((otherAlbum) => (
              <div key={otherAlbum.id} className="w-36 shrink-0 sm:w-44">
                <AlbumCard
                  album={otherAlbum}
                  onOpen={() => onOpenAlbum?.(otherAlbum)}
                />
              </div>
            ))}
          </Shelf>
        </section>
      )}
    </div>
  )
}
