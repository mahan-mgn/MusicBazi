import { digits, formatArtistSubtitle } from '../lib/format'
import { useI18n } from '../lib/i18n'
import { SOURCE_LABEL, type Album, type Artist, type Playlist } from '../lib/types'
import Artwork, { ArtBackdrop } from './Artwork'
import SendToTelegram from './SendToTelegram'
import SourceBadge from './SourceBadge'
import { PauseIcon, PlayIcon, Spinner } from './icons'
import SourceLogo, { SOURCE_COLOR } from './logos'

/**
 * کارت‌های مشترکِ نتایج جستجو و صفحه‌ی هنرمند.
 * جدا شدند چون هر دو صفحه دقیقاً همین کارت‌ها را می‌خواهند.
 */

export function ArtistCard({ artist, onOpen }: { artist: Artist; onOpen: () => void }) {
  const { lang } = useI18n()
  return (
    <button
      onClick={onOpen}
      className="group flex w-full flex-col items-center gap-2 rounded-xl p-2 text-center transition hover:bg-panel-2"
    >
      <div className="relative w-full">
        <span
          aria-hidden
          className="src-glow pointer-events-none absolute -inset-2 -z-10 rounded-full blur-xl"
          style={{ '--src': SOURCE_COLOR[artist.source] } as React.CSSProperties}
        />
        <Artwork
          src={artist.artworkUrl}
          alt={artist.name}
          seed={artist.id}
          rounded="rounded-full"
          className="aspect-square w-full shadow-lg shadow-black/25 transition group-hover:scale-[1.03]"
        />
        {/*
          یک هنرمند از چهار کاتالوگ چهار کارت دارد و هر کارت به صفحه‌ی همان
          پلتفرم می‌رود. بدون این نشان، چهار دایره‌ی هم‌نام شبیه باگ به نظر
          می‌رسند — نه شبیه انتخاب.
        */}
        <span
          title={SOURCE_LABEL[artist.source]}
          className="absolute bottom-0 end-0 grid size-6 place-items-center rounded-full border border-line bg-panel shadow-sm"
        >
          <SourceLogo source={artist.source} className="size-3.5" />
        </span>
      </div>
      <div className="w-full">
        <p className="bidi-center truncate text-xs">{artist.name}</p>
        {/* زیرنویسِ سرور («76 آلبوم»، «11,365 دنبال‌کننده») ارقامِ لاتین دارد —
            در حالتِ فارسی باید فارسی شوند؛ کشِ کاتالوگ هم قدیمی را نگه می‌دارد
            پس تبدیل همین‌جا انجام می‌شود نه سمت سرور */}
        <p className="truncate text-[10px] text-muted-2">{formatArtistSubtitle(artist.subtitle, lang)}</p>
      </div>
    </button>
  )
}

export function AlbumCard({
  album,
  onOpen,
  onPlay,
  isPlaying = false,
  isLoading = false,
}: {
  album: Album
  onOpen: () => void
  onPlay?: () => void
  isPlaying?: boolean
  isLoading?: boolean
}) {
  const { lang, t } = useI18n()
  const playLabel = isPlaying ? t.pause : album.trackCount === 1 ? t.playTrack(album.title) : t.playAll
  return (
    // دکمه‌ی تلگرام بیرونِ دکمه‌ی کارت می‌نشیند نه تویش: دکمه در دکمه HTML
    // نامعتبر است و کلیکش هم به کارت نشت می‌کرد (یعنی آلبوم باز می‌شد)
    <div className="group relative">
      <SendToTelegram
        target={{ kind: 'album', ref: album.sourceUrl || album.id, title: album.title }}
        hoverOnly
        // روی کاور می‌نشیند نه روی پنل، پس سفید می‌ماند — و `!` لازم است چون
        // خاکستریِ پیش‌فرضِ خودِ دکمه هم‌وزنِ این کلاس است و ترتیبشان تضمینی نیست
        className="absolute start-3.5 top-3.5 z-10 bg-black/55 text-white! backdrop-blur-sm hover:bg-black/75"
      />
      <div className="relative">
        <ArtBackdrop src={album.artworkUrl} seed={album.id} />
        <div className="relative p-2">
          <button
            onClick={onOpen}
            aria-label={album.title}
            className="group/art relative block w-full overflow-hidden rounded-lg"
          >
            <span
              aria-hidden
              className="src-glow pointer-events-none absolute -inset-2 -z-10 rounded-xl blur-xl"
              style={{ '--src': SOURCE_COLOR[album.source] } as React.CSSProperties}
            />
            <Artwork
              src={album.artworkUrl}
              alt={album.title}
              seed={album.id}
              className="aspect-square w-full shadow-lg shadow-black/25"
            />
            <span className="pointer-events-none absolute inset-0 grid place-items-center rounded-lg bg-black/45 opacity-0 transition group-hover/art:opacity-100">
              {!onPlay && (
                <span className="grid size-9 place-items-center rounded-full bg-accent text-accent-fg">
                  <PlayIcon className="size-4" />
                </span>
              )}
            </span>
            <span className="pointer-events-none absolute end-1.5 top-1.5 opacity-0 transition group-hover/art:opacity-100">
              <SourceBadge source={album.source} />
            </span>
          </button>
          {onPlay && (
            <button
              onClick={onPlay}
              disabled={isLoading}
              aria-label={playLabel}
              title={playLabel}
              className={`absolute start-1/2 top-1/2 z-10 grid size-9 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full bg-accent text-accent-fg shadow-lg transition enabled:hover:scale-110 disabled:cursor-wait ${
                isPlaying || isLoading ? 'opacity-100' : 'opacity-0 group-hover:opacity-100 focus-visible:opacity-100'
              }`}
            >
              {isLoading ? (
                <Spinner className="size-4" />
              ) : isPlaying ? (
                <PauseIcon className="size-4" />
              ) : (
                <PlayIcon className="size-4 ms-0.5" />
              )}
            </button>
          )}
        </div>
        <button onClick={onOpen} className="block w-full px-2 pb-2 text-start">
          <p className="bidi mt-0 truncate text-xs">{album.title}</p>
          <p className="truncate text-[10px] text-muted-2">
            <bdi>{album.artist}</bdi>
            {album.year ? ` · ${digits(album.year, lang)}` : ''}
          </p>
        </button>
      </div>
    </div>
  )
}

/**
 * ردیفِ پلی‌لیست — در نتایج جستجو و در صفحه‌ی کاربر/هنرمند.
 *
 * تعداد ترک وقتی صفر است اصلاً نوشته نمی‌شود، چون صفر اینجا یعنی «نمی‌دانیم»
 * نه «خالی»: صفحه‌ی پروفایلِ اسپاتیفای و تبِ پلی‌لیست‌های یوتیوب تعداد را
 * نمی‌دهند و «۰ آهنگ» زیرِ پلی‌لیستِ صدتایی، دروغِ صریح بود.
 */
export function PlaylistRow({ playlist, onOpen }: { playlist: Playlist; onOpen: () => void }) {
  const { t } = useI18n()
  return (
    <button
      onClick={onOpen}
      className="flex w-full items-center gap-3 rounded-lg px-2 py-2 text-start transition hover:bg-panel-2"
    >
      <Artwork
        src={playlist.artworkUrl}
        alt={playlist.title}
        seed={playlist.id}
        className="size-10 shrink-0"
      />
      <div className="min-w-0 flex-1">
        <p className="bidi truncate text-sm">{playlist.title}</p>
        <p className="truncate text-xs text-muted">
          {playlist.trackCount > 0 && `${t.trackCount(playlist.trackCount)} · `}
          <bdi>{playlist.owner}</bdi>
        </p>
      </div>
      <SourceBadge source={playlist.source} />
    </button>
  )
}
