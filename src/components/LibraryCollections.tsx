import { memo, useEffect, useState } from 'react'
import { bytes as fmtBytes } from '../lib/format'
import { dominantColor } from '../lib/artColor'
import { useI18n } from '../lib/i18n'
import type { LibraryGroup } from '../lib/library'
import { SOURCE_LABEL } from '../lib/types'
import { useOnline } from '../store/net'
import { usePlayer } from '../store/player'
import Artwork, { ArtBackdrop } from './Artwork'
import { toPlayItem } from './LibraryRow'
import SourceLogo from './logos'
import { AlbumIcon, ArtistIcon, ArrowIcon, PlayIcon, ShuffleIcon } from './icons'

/**
 * آلبوم‌ها و هنرمندانِ کتابخانه.
 *
 * هیچ‌کدام موجودیتِ سرور نیستند — از روی همان ردیف‌های دانلودشده ساخته
 * می‌شوند (`lib/library.ts`)، پس کارت و صفحه‌شان هم اینجا کنارِ هم ماند.
 */

/** ۲×۲ کاور برای گروهی که چند کاورِ متفاوت دارد، وگرنه همان یکی */
export function Mosaic({
  urls,
  seed,
  alt = '',
  className = 'size-16',
  rounded = 'rounded-lg',
}: {
  urls: string[]
  seed: string
  alt?: string
  className?: string
  rounded?: string
}) {
  if (urls.length < 4) {
    return (
      <Artwork src={urls[0] ?? null} alt={alt} seed={seed} className={className} rounded={rounded} />
    )
  }
  return (
    <div className={`${className} ${rounded} grid shrink-0 grid-cols-2 grid-rows-2 overflow-hidden`}>
      {urls.slice(0, 4).map((url, i) => (
        <img key={`${url}-${i}`} src={url} alt="" loading="lazy" className="size-full object-cover" />
      ))}
    </div>
  )
}

export function longDuration(ms: number, t: ReturnType<typeof useI18n.getState>['t']): string {
  const minutes = Math.round(ms / 60000)
  return minutes < 60 ? t.minutes(minutes) : t.hoursMinutes(Math.floor(minutes / 60), minutes % 60)
}

/** لوگوهای پلتفرم‌های حاضر در گروه — یک گروه می‌تواند ترک از چند منبع داشته باشد */
function GroupSources({ group, size = 'size-3.5' }: { group: LibraryGroup; size?: string }) {
  const sources = [...new Set(group.items.map((x) => x.track.source))]
  return (
    <span className="inline-flex items-center -space-x-0.5 rtl:space-x-reverse">
      {sources.map((source) => (
        <span
          key={source}
          title={SOURCE_LABEL[source]}
          className={`grid ${size === 'size-3.5' ? 'size-4' : 'size-5'} place-items-center rounded-full bg-bg/80 ring-1 ring-bg`}
        >
          <SourceLogo source={source} className={size} />
          <span className="sr-only">{SOURCE_LABEL[source]}</span>
        </span>
      ))}
    </span>
  )
}

/** کاشیِ یک آلبوم یا هنرمند — گرد بودنِ کاور تنها فرقشان است، مثل اسپاتیفای */
export const GroupCard = memo(function GroupCard({
  group,
  round,
  // شناسه می‌گیرد نه کلوزرِ آماده — مثل LibraryRow تا memo معنا داشته باشد
  onOpen,
}: {
  group: LibraryGroup
  round: boolean
  onOpen: (key: string) => void
}) {
  const { t } = useI18n()

  return (
    <button
      onClick={() => onOpen(group.key)}
      aria-label={t.libraryOpenGroup(group.title)}
      className="group relative w-full overflow-hidden rounded-xl p-2 text-start transition hover:bg-panel-2 motion-safe:hover:-translate-y-0.5 motion-safe:active:scale-[0.98]"
    >
      <ArtBackdrop src={group.artworkUrls[0] ?? null} seed={group.seed} />
      <div className="relative">
        <Mosaic
          urls={group.artworkUrls}
          seed={group.seed}
          alt={group.title}
          className="aspect-square w-full shadow-lg shadow-black/25"
          rounded={round ? 'rounded-full' : 'rounded-lg'}
        />
        {/* دکمه‌ی پخشِ شناور، گوشه‌ی پایین — با هاور از پایین بالا می‌آید.
            نشانه‌ی «باز شو» است نه یک دکمه‌ی دیگر: دکمه داخلِ دکمه نه معتبر
            است نه قابل‌پیش‌بینی. خودِ پخش یک کلیک آن‌طرف‌تر، در سرصفحه است */}
        <span
          aria-hidden
          className={`absolute end-2 bottom-2 grid size-10 translate-y-2 place-items-center bg-accent text-accent-fg opacity-0 shadow-lg shadow-black/40 transition duration-200 group-hover:translate-y-0 group-hover:opacity-100 ${
            round ? 'rounded-full' : 'rounded-xl'
          }`}
        >
          <PlayIcon className="size-4" />
        </span>
      </div>
      <p className={`mt-2 flex items-center gap-1.5 truncate text-xs ${round ? 'bidi-center justify-center' : 'bidi'}`}>
        <GroupSources group={group} />
        <span className="truncate">{group.title}</span>
      </p>
      <p className={`truncate text-[10px] text-muted-2 ${round ? 'bidi-center' : 'bidi'}`}>
        {round ? (
          t.albumCount(group.albumCount)
        ) : (
          <>
            <bdi>{group.artist}</bdi>
            {` · ${t.trackCount(group.items.length)}`}
          </>
        )}
      </p>
    </button>
  )
})

/** سرصفحه‌ی یک آلبوم/هنرمندِ باز شده — همان زبانِ هیروی صفحه‌ی آلبوم */
export function GroupHero({
  group,
  round,
  onBack,
}: {
  group: LibraryGroup
  round: boolean
  onBack: () => void
}) {
  const { t, lang } = useI18n()
  const online = useOnline()
  const queue = group.items.map(toPlayItem)

  // رنگِ غالبِ کاورِ اول — همان لایه‌ای که پخش‌کننده و صفحه‌ی آلبوم استفاده
  // می‌کنند، پس کشِ مشترک است و هاله‌ی کتابخانه با هیروی آلبوم هم‌خوان می‌ماند
  const [tint, setTint] = useState<[number, number, number] | null>(null)
  const cover0 = group.artworkUrls[0] ?? null
  useEffect(() => {
    let cancelled = false
    // عمداً بی‌درنگ به null برنمی‌گردد: یک فریمِ تهی یعنی پرشِ هاله به خاکستری
    // تا رنگِ تازه برسد. رنگِ کهنه می‌ماند و با رسیدنِ تازه (که بیشترِ وقت‌ها
    // از کشِ dominantColor در یک microtask درمی‌آید) جایگزین می‌شود.
    void dominantColor(cover0).then((c) => {
      if (!cancelled && c) setTint(c)
    })
    return () => {
      cancelled = true
    }
  }, [cover0])
  const anyTint = tint ? tint.join(',') : '107,107,107'

  const shufflePlay = () => {
    const player = usePlayer.getState()
    if (!player.shuffle) player.toggleShuffle()
    player.play(queue, Math.floor(Math.random() * queue.length))
  }

  return (
    <div
      className="rounded-t-2xl px-4 pb-5 pt-4 sm:px-6"
      style={{
        background: `radial-gradient(120% 110% at 85% 0%, rgb(${anyTint} / 0.24), transparent 60%)`,
      }}
    >
      <button
        onClick={onBack}
        className="inline-flex items-center gap-1.5 text-xs text-muted transition hover:text-fg"
      >
        <ArrowIcon className="size-3.5 -scale-x-100 rtl:scale-x-100" />
        {t.libraryBack}
      </button>

      <div className="mt-4 flex flex-col gap-4 sm:flex-row sm:items-end sm:gap-6">
        {/* هاله‌ی نرمِ پشتِ کاور — همان رنگ، عمقِ بیشتر */}
        <div className="relative shrink-0">
          <div
            aria-hidden
            className={`pointer-events-none absolute inset-2 scale-125 opacity-45 blur-2xl ${
              round ? 'rounded-full' : 'rounded-3xl'
            }`}
            style={{ background: `rgb(${anyTint} / 0.5)` }}
          />
          <Mosaic
            urls={group.artworkUrls}
            seed={group.seed}
            alt={group.title}
            className="relative size-40 shadow-2xl shadow-black/50 sm:size-48 md:size-52"
            rounded={round ? 'rounded-full' : 'rounded-2xl'}
          />
        </div>

        <div className="min-w-0 flex-1">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-widest text-muted-2">
            {round ? t.artists : t.typeAlbum}
          </p>
          <h2 className={`text-3xl font-black leading-[1.15] [word-break:break-word] sm:text-4xl md:text-5xl ${round ? 'bidi-center' : 'bidi'}`}>
            {group.title}
          </h2>
          <p className="bidi mt-2 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-sm text-muted">
            {group.artist && (
              <>
                <bdi className="font-semibold text-fg/90">{group.artist}</bdi>
                <span aria-hidden>·</span>
              </>
            )}
            <GroupSources group={group} />
            <span aria-hidden>·</span>
            {t.trackCount(group.items.length)}
            <span aria-hidden>·</span>
            {longDuration(group.durationMs, t)}
            <span aria-hidden>·</span>
            {fmtBytes(group.bytes, lang)}
          </p>

          {/* ردیفِ کنش: پخشِ گردِ بزرگ + شافلِ دایره‌ای — هم‌ترازِ صفحه‌ی آلبوم */}
          <div className="mt-5 flex flex-wrap items-center gap-3">
            <button
              onClick={() => usePlayer.getState().play(queue, 0)}
              disabled={!queue.length}
              aria-label={t.playAll}
              title={t.playAll}
              className="grid size-14 place-items-center rounded-full bg-accent text-accent-fg shadow-lg shadow-accent/25 transition enabled:hover:scale-105 enabled:active:scale-95 disabled:opacity-40"
            >
              <PlayIcon className="size-6" />
            </button>
            <button
              onClick={shufflePlay}
              disabled={!queue.length}
              aria-label={t.shuffle}
              title={t.shuffle}
              className="grid size-11 place-items-center rounded-full border border-line text-muted transition enabled:hover:scale-105 enabled:hover:text-fg disabled:opacity-40"
            >
              <ShuffleIcon className="size-5" />
            </button>

            {online && (
              <button
                type="button"
                onClick={() => {
                  if (round) {
                    const ref = group.items.find((x) => x.track.artistId)?.track.artistId || group.title
                    window.dispatchEvent(new CustomEvent('musicbazi:open-artist', { detail: { ref } }))
                  } else {
                    const ref = group.items.find((x) => x.track.albumId)?.track.albumId || group.title
                    window.dispatchEvent(new CustomEvent('musicbazi:open-album', { detail: { ref } }))
                  }
                }}
                title={round ? t.viewOnlineArtist : t.viewOnlineAlbum}
                className="inline-flex h-11 items-center gap-2 rounded-full border border-line bg-panel-2/60 px-4 text-xs font-medium text-muted transition hover:border-accent/40 hover:bg-accent-dim hover:text-accent"
              >
                {round ? <ArtistIcon className="size-4" /> : <AlbumIcon className="size-4" />}
                <span>{round ? t.viewOnlineArtist : t.viewOnlineAlbum}</span>
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
