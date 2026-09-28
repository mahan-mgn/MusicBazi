import { memo, useEffect, useState } from 'react'
import { useLongPress } from '../lib/useLongPress'
import { useRowSwipe } from '../lib/useRowSwipe'
import { usePopover } from '../lib/usePopover'
import {
  bytes as fmtBytes,
  duration as fmtDuration,
  fileExt,
  formatLabel,
  safeFilename,
  shortDate,
  digits,
} from '../lib/format'
import { useI18n } from '../lib/i18n'
import { canSaveToDevice, haptic, saveToDevice } from '../lib/native'
import { supported as offlineSupported } from '../lib/offline'
import { SOURCE_LABEL, type LibraryItem } from '../lib/types'
import { useFavorites } from '../store/favorites'
import { useOffline } from '../store/offline'
import { usePlayer, type PlayItem } from '../store/player'
import { useSettings } from '../store/settings'
import { trackKey, usable, useTelegram } from '../store/telegram'
import { useToasts } from '../store/toasts'
import { PlaylistPicker } from './AddToPlaylist'
import Artwork from './Artwork'
import LikeHeart from './LikeHeart'
import SourcePicker from './SourcePicker'
import SourceLogo from './logos'
import {
  AlbumIcon,
  ArtistIcon,
  ArrowIcon,
  CheckIcon,
  DotsIcon,
  DownloadIcon,
  EqualizerIcon,
  HeartIcon,
  LyricsIcon,
  NextIcon,
  OfflineIcon,
  PauseIcon,
  PlayIcon,
  PlaylistIcon,
  QueueIcon,
  Spinner,
  SwapIcon,
  TelegramIcon,
  TrashIcon,
  WarnIcon,
} from './icons'

/**
 * قالبِ ستون‌های ردیف — یک رشته و یک جا، چون سرستون‌ها هم دقیقاً همین را
 * می‌گیرند. با flex هر ستون به عرضِ محتوای خودش می‌رفت و ستونِ «آلبوم» ردیف
 * به ردیف جابه‌جا می‌شد؛ چیزی که چشم به‌عنوان «شلوغی» می‌خواند.
 */
export const ROW_GRID =
  'grid items-center gap-2 sm:gap-3 grid-cols-[1.75rem_minmax(0,1fr)_auto] md:grid-cols-[1.75rem_minmax(0,1fr)_minmax(0,12rem)_11.5rem] xl:grid-cols-[1.75rem_minmax(0,1fr)_minmax(0,12rem)_6rem_11.5rem]'

export const toPlayItem = (item: LibraryItem): PlayItem => ({
  id: item.jobId,
  track: item.track,
  streamUrl: item.streamUrl,
  lyricsUrl: item.lyricsUrl,
  gainDb: item.gainDb,
})

/** سنجاقِ آفلاین — منطقش بین ردیف و منو مشترک است */
function useOfflinePin(item: LibraryItem) {
  const { t } = useI18n()
  const pushToast = useToasts((s) => s.push)
  const pinned = useOffline((s) => Boolean(s.items[item.jobId]))
  const saving = useOffline((s) => s.busy.includes(item.jobId))

  async function toggle() {
    const store = useOffline.getState()
    if (pinned) {
      await store.unpin(item)
      pushToast(t.offlineRemoved(item.track.title), 'info')
      return
    }
    if (!offlineSupported()) {
      pushToast(t.offlineUnsupported, 'error')
      return
    }
    const ok = await store.pin(item)
    pushToast(ok ? t.offlinePinned(item.track.title) : t.offlineFailed, ok ? 'success' : 'error')
  }

  return { pinned, saving, toggle }
}

const menuItem =
  'flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-start text-xs text-muted transition hover:bg-panel-2 hover:text-fg'

/**
 * «بفرست به تلگرام» در منوی ردیف.
 *
 * برخلافِ نتایج جستجو اینجا دکمه‌ی مستقل نمی‌گیرد: ردیفِ کتابخانه از قبل
 * چهار کنترل دارد و پنجمی فقط شلوغش می‌کرد. منو بسته نمی‌شود تا کاربر
 * اسپینر و بعد تیک را ببیند — بات ممکن است چند ده ثانیه طول بدهد.
 */
function TelegramItem({ item, onDone }: { item: LibraryItem; onDone: () => void }) {
  const { t } = useI18n()
  const ready = useTelegram(usable)
  const state = useTelegram((s) => s.sends[trackKey(item.track.id)])
  const quality = useSettings((s) => s.quality)

  if (!ready) return null

  const busy = state === 'pending' || state === 'sending'

  async function send() {
    const queued = await useTelegram.getState().send({ kind: 'track', track: item.track, quality })
    // نرفت یعنی پنجره‌ی وصل‌شدن باز شده یا خطا خورده — منو باید کنار برود تا دیده شود
    if (!queued) onDone()
  }

  return (
    <button role="menuitem" onClick={() => void send()} disabled={busy} className={menuItem}>
      {busy ? (
        <Spinner className="size-3.5 shrink-0" />
      ) : state === 'done' ? (
        <CheckIcon className="size-3.5 shrink-0 text-accent" />
      ) : state === 'error' ? (
        <WarnIcon className="size-3.5 shrink-0 text-danger" />
      ) : (
        <TelegramIcon className="size-3.5 shrink-0" />
      )}
      {t.telegramSendTrack(item.track.title)}
    </button>
  )
}

/**
 * «ذخیره در گوشی» — فقط داخل اپ اندروید.
 *
 * تفاوتش با «سنجاقِ آفلاین» که بغلش نشسته، همان تفاوتی است که کاربر هم
 * می‌فهمد: سنجاق فایل را در حافظه‌ی خودِ اپ نگه می‌دارد تا *اینجا* بدون
 * اینترنت پخش شود؛ این یکی فایل را در کتابخانه‌ی موسیقیِ گوشی می‌گذارد تا
 * *هر اپِ دیگری* هم ببیندش و با پاک‌کردنِ آنستریم نرود.
 *
 * روی وب اصلاً نشان داده نمی‌شود: آنجا همان دکمه‌ی دانلودِ مرورگر کار را
 * می‌کند و یک آیتمِ منوی اضافه که فقط روی یک پلتفرم کار می‌کند، گیج‌کننده است.
 */
function SaveToPhoneItem({ item, onDone }: { item: LibraryItem; onDone: () => void }) {
  const { t } = useI18n()
  const push = useToasts((s) => s.push)
  const [busy, setBusy] = useState(false)

  if (!canSaveToDevice()) return null

  const run = async () => {
    setBusy(true)
    try {
      await saveToDevice({
        // `fileUrl` نه `streamUrl`: دومی برای پخشِ تکه‌تکه است، اولی خودِ فایل
        url: item.fileUrl,
        title: item.track.title,
        artist: item.track.artist,
        album: item.track.album ?? '',
        // `fileExt` خودِ فرمت را می‌گیرد («mp3 320» → «mp3»)، نه آدرس را
        ext: fileExt(item.format),
      })
      haptic.success()
      push(t.saveToPhoneDone, 'success')
      onDone()
    } catch (error) {
      haptic.warn()
      push(error instanceof Error ? error.message : t.saveToPhoneFailed, 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <button role="menuitem" onClick={() => void run()} disabled={busy} className={menuItem}>
      {busy ? (
        <Spinner className="size-3.5 shrink-0" />
      ) : (
        <DownloadIcon className="size-3.5 shrink-0" />
      )}
      {t.saveToPhone}
    </button>
  )
}

/**
 * منویِ «⋯» ردیف.
 *
 * قبلاً هر ردیف شش دکمه‌ی همیشه‌حاضر داشت؛ آن‌ها اینجا جمع شدند و بیرون فقط
 * چیزهایی ماندند که یا *وضعیت*‌اند (سنجاقِ آفلاین) یا کارِ اصلیِ همین اپ
 * (گرفتنِ فایل).
 */
function RowMenu({
  item,
  onRemove,
  onPickSource,
  open,
  setOpen,
}: {
  item: LibraryItem
  onRemove: () => void
  onPickSource: () => void
  /*
   * حالتِ باز/بسته بالای این کامپوننت زندگی می‌کند، چون دو نفرِ دیگر هم به
   * آن کار دارند: نگه‌داشتنِ طولانی روی خودِ ردیف که بازش می‌کند، و کلاسِ
   * `row-cv` که ردیفِ منو-باز نباید بگیرد (وگرنه منو بریده می‌شود).
   */
  open: boolean
  setOpen: (open: boolean) => void
}) {
  const { t } = useI18n()
  const [page, setPage] = useState<'root' | 'playlist'>('root')
  const box = usePopover<HTMLDivElement>(open, () => setOpen(false))
  const { pinned, saving, toggle } = useOfflinePin(item)
  const favorite = useFavorites((s) => Boolean(s.items[item.jobId]))
  const toggleFavorite = useFavorites((s) => s.toggle)

  // منو که بسته می‌شود باید دفعه‌ی بعد از صفحه‌ی اول باز شود
  useEffect(() => {
    if (!open) setPage('root')
  }, [open])

  return (
    <div ref={box} className="relative">
      <button
        onClick={() => setOpen(!open)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t.trackActions(item.track.title)}
        title={t.trackActions(item.track.title)}
        className={`grid size-8 place-items-center rounded-full text-muted-2 transition hover:bg-panel-2 hover:text-fg sm:size-7 ${
          open ? 'bg-panel-2 text-fg' : 'hover-reveal opacity-0 focus-visible:opacity-100 group-hover:opacity-100'
        }`}
      >
        <DotsIcon className="size-4" />
      </button>

      {open && (
        <div
          role="menu"
          className="sheet-in absolute end-0 z-40 mt-1 w-56 rounded-xl border border-line bg-panel p-1.5 shadow-xl"
        >
          {page === 'playlist' ? (
            <>
              <button onClick={() => setPage('root')} className={`${menuItem} text-muted-2`}>
                <ArrowIcon className="size-3.5 -scale-x-100 rtl:scale-x-100" />
                {t.playlistAdd}
              </button>
              <div className="my-1 border-t border-line-soft" />
              <PlaylistPicker jobIds={[item.jobId]} onDone={() => setOpen(false)} />
            </>
          ) : (
            <>
              <button
                role="menuitem"
                onClick={() => {
                  usePlayer.getState().playNext([toPlayItem(item)])
                  useToasts.getState().push(t.playNextAdded(item.track.title), 'info')
                  setOpen(false)
                }}
                className={menuItem}
              >
                <NextIcon className="size-3.5 shrink-0" />
                {t.playNext}
              </button>

              <button
                role="menuitem"
                onClick={() => {
                  usePlayer.getState().enqueue([toPlayItem(item)])
                  useToasts.getState().push(t.queueAdded(item.track.title), 'info')
                  setOpen(false)
                }}
                className={menuItem}
              >
                <QueueIcon className="size-3.5 shrink-0" />
                {t.addToQueue}
              </button>

              <button
                role="menuitem"
                onClick={() => void toggleFavorite(item.jobId)}
                className={menuItem}
              >
                <HeartIcon
                  className={`size-3.5 shrink-0 ${favorite ? 'text-like' : ''}`}
                  filled={favorite}
                />
                {favorite ? t.favoriteRemove : t.favoriteAdd}
              </button>

              <button role="menuitem" onClick={() => void toggle()} disabled={saving} className={menuItem}>
                {saving ? (
                  <Spinner className="size-3.5 shrink-0" />
                ) : (
                  <OfflineIcon className={`size-3.5 shrink-0 ${pinned ? 'text-accent' : ''}`} filled={pinned} />
                )}
                {pinned ? t.offlineUnpin : t.offlinePin}
              </button>

              <button role="menuitem" onClick={() => setPage('playlist')} className={menuItem}>
                <PlaylistIcon className="size-3.5 shrink-0" />
                <span className="flex-1">{t.playlistAdd}</span>
                <ArrowIcon className="size-3 shrink-0 text-muted-2 rtl:-scale-x-100" />
              </button>

              <button
                role="menuitem"
                onClick={() => {
                  setOpen(false)
                  const ref = item.track.artistId || item.track.artist
                  if (ref) {
                    window.dispatchEvent(new CustomEvent('unstream:open-artist', { detail: { ref } }))
                  }
                }}
                className={menuItem}
              >
                <ArtistIcon className="size-3.5 shrink-0" />
                {t.goToArtist(item.track.artist)}
              </button>

              {item.track.album && (
                <button
                  role="menuitem"
                  onClick={() => {
                    setOpen(false)
                    const ref = item.track.albumId || item.track.album
                    if (ref) {
                      window.dispatchEvent(new CustomEvent('unstream:open-album', { detail: { ref } }))
                    }
                  }}
                  className={menuItem}
                >
                  <AlbumIcon className="size-3.5 shrink-0" />
                  {t.goToAlbum(item.track.album)}
                </button>
              )}

              <SaveToPhoneItem item={item} onDone={() => setOpen(false)} />

              <TelegramItem item={item} onDone={() => setOpen(false)} />

              {item.lyricsUrl && (
                <a role="menuitem" href={item.lyricsUrl} download className={menuItem}>
                  <LyricsIcon className="size-3.5 shrink-0" />
                  {t.lyrics}
                </a>
              )}

              <button
                role="menuitem"
                onClick={() => {
                  setOpen(false)
                  onPickSource()
                }}
                className={menuItem}
              >
                <SwapIcon className="size-3.5 shrink-0" />
                {t.pickSource}
              </button>

              <div className="my-1 border-t border-line-soft" />

              <button
                role="menuitem"
                onClick={() => {
                  setOpen(false)
                  onRemove()
                }}
                className={`${menuItem} text-danger hover:text-danger`}
              >
                <TrashIcon className="size-3.5 shrink-0" />
                {t.libraryRemove}
              </button>
            </>
          )}
        </div>
      )}
    </div>
  )
}

interface RowProps {
  item: LibraryItem
  queue: PlayItem[]
  index: number
  /** شماره‌ای که در ستونِ اول دیده می‌شود — معمولاً همان index + 1 */
  number: number
  /**
   * آبجکت/شناسه می‌گیرد نه کلوزرِ آماده: با `memo`، کلوزری که هر رندر
   * تازه ساخته می‌شود کل ردیف را بی‌معنی از نو رندر می‌کرد.
   */
  onRemove: (item: LibraryItem) => void
  selectable: boolean
  selected: boolean
  onToggleSelect: (jobId: string) => void
}

export const LibraryRow = memo(function LibraryRow({
  item,
  queue,
  index,
  number,
  onRemove,
  selectable,
  selected,
  onToggleSelect,
}: RowProps) {
  const { t, lang } = useI18n()
  const [picking, setPicking] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const { pinned, saving, toggle } = useOfflinePin(item)
  const favorite = useFavorites((s) => Boolean(s.items[item.jobId]))
  const toggleFavorite = useFavorites((s) => s.toggle)
  /*
   * دو سلکتورِ primitive به‌جای `playing` عمومی.
   *
   * `usePlayer((s) => s.playing)` یعنی هر play/pause روی هر ۴۸ ردیف یک
   * رندر می‌ریزد (اشتراک zustand از memo ردیف رد می‌شود). این‌طور فقط ردیفی
   * که وضعیتش *واقعاً* عوض شده رندر می‌کند — و تیک‌های جایگاهِ پخش که هر
   * ربع‌ثانیه state می‌سازند هیچ ردیفی را بیدار نمی‌کنند.
   */
  const jobId = item.jobId
  const isCurrent = usePlayer((s) => s.queue[s.index]?.id === jobId)
  const isPlaying = usePlayer((s) => s.playing && s.queue[s.index]?.id === jobId)

  /*
   * نگه‌داشتنِ انگشت روی ردیف (و راست‌کلیک روی دسکتاپ) همان منویِ «⋯» را
   * باز می‌کند. روی گوشی، «⋯» یک هدفِ ریزِ ته ردیف است که کنارِ دکمه‌ی
   * دانلود نشسته؛ کلِ ردیف هدفِ به‌مراتب راحت‌تری است.
   *
   * وقتی ردیف در حالتِ انتخاب است غیرفعال می‌شود: آن‌جا نگه‌داشتن یعنی
   * انتخابِ چندتایی، نه منو.
   */
  const holdRef = useLongPress<HTMLDivElement>(() => setMenuOpen(true), !selectable)

  useRowSwipe<HTMLDivElement>({
    ref: holdRef,
    onStartToEnd: () => {
      usePlayer.getState().enqueue([toPlayItem(item)])
      useToasts.getState().push(t.queueAdded(item.track.title), 'info')
    },
    onEndToStart: () => {
      const isFav = Boolean(useFavorites.getState().items[item.jobId])
      void toggleFavorite(item.jobId)
      useToasts.getState().push(isFav ? t.favoriteRemove : t.favoriteAdd, 'info')
    },
    enabled: !selectable,
  })

  const { track } = item
  const filename = `${safeFilename(`${track.artist} - ${track.title}`)}.${fileExt(item.format)}`

  /*
   * `row-cv` (یعنی `content-visibility: auto`) فقط روی ردیفِ آرام.
   *
   * آن خاصیت `contain: paint` هم می‌آورد: منویِ باز از قابِ ردیف بیرون
   * می‌زند و بریده می‌شود، و `SourcePicker` که `position: fixed` است نسبت
   * به همین ردیف جا می‌گیرد نه صفحه. پس ردیفی که چیزی رویش باز است از این
   * بهینه‌سازی کنار می‌کشد — یک ردیف از پانصدتا، بی‌اثر بر روانیِ اسکرول.
   */
  const quiet = !menuOpen && !picking

  return (
    <div
      ref={holdRef}
      className={`group hold-menu relative touch-pan-y rounded-lg px-1.5 py-1.5 transition sm:px-2 ${ROW_GRID} ${
        quiet ? 'row-cv ' : ''
      }${selected ? 'bg-accent-dim' : 'hover:bg-panel-2'}`}
    >
      {/* ستونِ اول سه چیز است در یک جا: شماره، تیکِ انتخاب، و دکمه‌ی پخش —
          هیچ‌کدام جای دیگری نمی‌رفتند بدون این‌که ردیف بلندتر یا شلوغ‌تر شود */}
      <div className="relative grid size-7 place-items-center">
        {selectable ? (
          <button
            onClick={() => onToggleSelect(jobId)}
            role="checkbox"
            aria-checked={selected}
            aria-label={t.selectionRow(track.title)}
            className={`grid size-4 place-items-center rounded border transition ${
              selected ? 'border-accent bg-accent text-accent-fg' : 'border-line text-transparent hover:border-muted'
            }`}
          >
            <CheckIcon className="size-3" />
          </button>
        ) : (
          <>
            <span
              className={`hover-hide text-[11px] tabular-nums transition group-hover:opacity-0 ${
                isCurrent ? 'opacity-0' : 'text-muted-2'
              }`}
            >
              {digits(number, lang)}
            </span>
            {isCurrent && (
              <span
                title={t.nowPlayingRow}
                className="hover-hide absolute inset-0 grid place-items-center text-accent transition group-hover:opacity-0"
              >
                <EqualizerIcon className="size-3.5" animate={isPlaying} />
              </span>
            )}
            <button
              onClick={() => usePlayer.getState().play(queue, index)}
              aria-label={isPlaying ? t.pause : t.playTrack(track.title)}
              title={isPlaying ? t.pause : t.playTrack(track.title)}
              className="hover-reveal absolute inset-0 grid place-items-center rounded-full text-fg opacity-0 transition focus-visible:opacity-100 group-hover:opacity-100"
            >
              {isPlaying ? <PauseIcon className="size-3.5" /> : <PlayIcon className="size-3.5" />}
            </button>
          </>
        )}
      </div>

      <div className="flex min-w-0 items-center gap-2.5 sm:gap-3">
        <Artwork
          src={track.artworkUrl}
          alt={track.album ?? track.title}
          seed={track.albumId ?? track.id}
          className="size-10 shrink-0"
        />
        <div className="min-w-0">
          <p className={`bidi flex items-center gap-1.5 truncate text-sm ${isCurrent ? 'font-medium text-accent' : ''}`}>
            <span className="truncate">{track.title}</span>
            <SourceLogo
              source={track.source}
              className="size-3.5 shrink-0 opacity-80"
            />
            <span className="sr-only">{SOURCE_LABEL[track.source]}</span>
          </p>
          <p className="bidi truncate text-xs text-muted">
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                const ref = track.artistId || track.artist
                if (ref) {
                  window.dispatchEvent(new CustomEvent('unstream:open-artist', { detail: { ref } }))
                }
              }}
              title={t.goToArtist(track.artist)}
              className="truncate text-start transition hover:text-accent hover:underline decoration-accent/40 underline-offset-2"
            >
              <bdi>{track.artist}</bdi>
            </button>
          </p>
        </div>
      </div>

      {/* آلبوم و تاریخ فقط روی صفحه‌ی بزرگ — روی موبایل همان دو خطِ بالا کافی است */}
      {track.album ? (
        <p className="bidi hidden truncate text-xs text-muted-2 md:block">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              const ref = track.albumId || track.album
              if (ref) {
                window.dispatchEvent(new CustomEvent('unstream:open-album', { detail: { ref } }))
              }
            }}
            title={t.goToAlbum(track.album)}
            className="truncate text-start transition hover:text-fg hover:underline decoration-muted-2/40 underline-offset-2"
          >
            {track.album}
          </button>
        </p>
      ) : (
        <p className="bidi hidden truncate text-xs text-muted-2 md:block">—</p>
      )}
      <p className="hidden truncate text-[11px] text-muted-2 xl:block">
        {shortDate(item.createdAt, lang)}
      </p>

      <div className="flex shrink-0 items-center justify-end gap-1 sm:gap-1.5">
        {/* قلبِ لایک: همیشه دیده می‌شود و دوطرفه است — مستقیم از ردیف لایک/برداشت
            می‌شود، با همان pop و پاششِ نمای کامل. (آیتمِ «علاقه‌مندی» در منو هم
            هست برای دسترسیِ کیبورد/صفحه‌خوان.) */}
        <LikeHeart
          liked={favorite}
          onToggle={() => void toggleFavorite(item.jobId)}
          ariaLabel={favorite ? t.favoriteRemove : t.favoriteAdd}
          title={favorite ? t.favoriteRemove : t.favoriteAdd}
          className="size-6 rounded-full transition hover:bg-panel"
          iconClassName="size-3.5"
        />

        {/* سنجاق فقط وقتی *روشن* است بیرون می‌ماند؛ روشن کردنش کاری است که
            جایش داخل منوست، ولی خودِ وضعیت باید همیشه دیده شود */}
        {(pinned || saving) && (
          <button
            onClick={() => void toggle()}
            disabled={saving}
            aria-pressed={pinned}
            aria-label={t.offlineUnpin}
            title={t.offlineUnpin}
            className="grid size-6 place-items-center rounded-full text-accent transition hover:bg-panel disabled:opacity-50"
          >
            {saving ? <Spinner className="size-3.5" /> : <OfflineIcon className="size-3.5" filled />}
          </button>
        )}

        <span className="hidden w-8 text-end text-[11px] tabular-nums text-muted-2 sm:inline">
          {fmtDuration(track.durationMs, lang)}
        </span>

        <a
          href={item.fileUrl}
          download={filename}
          title={`${t.save} — ${fmtBytes(item.bytes, lang)}`}
          className="inline-flex items-center gap-1 rounded-full border border-line bg-panel-2 px-2 py-1 text-[10px] font-semibold text-muted transition group-hover:border-accent/40 group-hover:bg-accent-dim group-hover:text-accent"
        >
          {formatLabel(item.format, lang)}
          <DownloadIcon className="size-3" />
        </a>

        <RowMenu
          item={item}
          onRemove={() => onRemove(item)}
          onPickSource={() => setPicking(true)}
          open={menuOpen}
          setOpen={setMenuOpen}
        />
      </div>

      {picking && (
        <SourcePicker track={track} quality={item.quality} onClose={() => setPicking(false)} />
      )}
    </div>
  )
})

/**
 * سرستون‌ها — همان قالبِ ردیف، تا ستون‌ها زیرِ هم بنشینند.
 *
 * چسبان نیست: نوارِ تب/ابزار بالای صفحه خودش چسبان است و دو نوارِ چسبانِ
 * روی‌هم‌افتاده بدتر از نداشتنِ سرستونِ چسبان است.
 */
export function RowHeader() {
  const { t } = useI18n()
  return (
    <div
      className={`${ROW_GRID} mb-1 border-b border-line-soft px-2 pb-1.5 text-[10px] uppercase tracking-wide text-muted-2`}
    >
      <span className="text-center">#</span>
      <span>{t.colTitle}</span>
      <span className="hidden md:block">{t.colAlbum}</span>
      <span className="hidden xl:block">{t.colAdded}</span>
      {/*
        ستونِ آخر مثل ردیف‌ها عرضِ ثابت می‌گیرد (۱۱.۵rem)، وگرنه چون هر ردیف
        grid جداگانه‌ای است، نقطه‌ی شروعِ «آلبوم» و «افزوده‌شده» به‌اندازه‌ی
        اختلافِ این ستون از زیرِ سرستون‌شان بیرون می‌لغزد
      */}
      <span aria-hidden />
    </div>
  )
}
