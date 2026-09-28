import { useEffect, useMemo, useState } from 'react'
import { api, API_MODE } from '../lib/api'
import { useI18n, type Dict } from '../lib/i18n'
import { SOURCE_LABEL, type DailyMix, type LibraryItem, type Source } from '../lib/types'
import { splitVibeLabel, VIBE_KEYS, vibeCovers, vibeLabel } from '../lib/vibes'
import { useMoodChat } from '../store/moodChat'
import { usePlayer, type PlayItem } from '../store/player'
import { useRecent, type RecentEntry } from '../store/recent'
import Artwork from './Artwork'
import ShinyText from './ShinyText'
import SpotlightCard from './SpotlightCard'
import { SectionHead, Shelf, TrackTile } from './Shelf'
import {
  ArrowIcon,
  ExploreIcon,
  LibraryIcon,
  PauseIcon,
  PlayIcon,
  SparkleIcon,
} from './icons'
import SourceLogo from './logos'

/** منبع‌هایی که سرچ‌بار می‌شناسد — همان‌ها که در هیرو نشان داده می‌شوند */
const SOURCES: Source[] = ['spotify', 'deezer', 'apple', 'youtube', 'soundcloud']

/**
 * رنگ هر کاشی حس‌وحال.
 *
 * از پالت تیلویند نمی‌آید چون این‌ها «رنگ برند» نیستند، حالت‌اند: باید در تم
 * روشن و تیره یکسان بمانند تا کاشی‌ها با هم یک خانواده بمانند.
 */
const VIBE_GRADIENT: Record<string, [string, string]> = {
  sad: ['#2b4a7a', '#5b8fd6'],
  happy: ['#b8721a', '#ffd166'],
  energetic: ['#a32e1f', '#ff7a45'],
  calm: ['#1f6b60', '#6fd3bd'],
  romantic: ['#8c2350', '#ff8fb1'],
  angry: ['#6b1414', '#e0503c'],
  nostalgic: ['#5a4326', '#c9a06b'],
  focus: ['#2c3550', '#8f9dd6'],
  heartbreak: ['#4a2060', '#b07be0'],
}

/** «چه ساعتی از روز» — همان سلامِ ساده‌ای که هر صفحه‌ی خانه‌ی موزیک دارد */
function greeting(t: Dict): string {
  const h = new Date().getHours()
  if (h >= 5 && h < 12) return t.greetingMorning
  if (h >= 12 && h < 18) return t.greetingAfternoon
  return t.greetingEvening
}

const toPlayItem = (item: LibraryItem): PlayItem => ({
  id: item.jobId,
  track: item.track,
  streamUrl: item.streamUrl,
  lyricsUrl: item.lyricsUrl,
  gainDb: item.gainDb,
})

interface Props {
  onOpenRef: (kind: 'artist' | 'album', ref: string) => void
  onOpenLibrary: () => void
  onFocusSearch?: () => void
  onSearch: (query: string) => void
  onIdentify?: () => void
}

const STARTER_QUERIES = {
  fa: ['موسیقی بی‌کلام', 'همایون شجریان', 'lofi'],
  en: ['lofi', 'Daft Punk', 'jazz'],
} as const

export default function Home({
  onOpenRef,
  onOpenLibrary,
  onFocusSearch: _onFocusSearch,
  onSearch,
  onIdentify: _onIdentify,
}: Props) {
  const { t } = useI18n()
  const history = useRecent((s) => s.items)
  const { items: library, loaded: libraryLoaded } = useRecentLibrary()
  // ردیفِ «تازه گرفته‌ای» فقط یک نگاهِ کوتاه است؛ استخرِ کاورها کلِ کتابخانه
  const recent = library.slice(0, 12)
  // کل ردیف یک صف است: کلیک روی کاشی سوم یعنی «از سومی به بعد»
  const recentQueue = recent.map(toPlayItem)
  // یکتاسازی لازم است: چند ترک از یک آلبوم همه یک کاور دارند و موزاییکِ
  // چهارتاییِ تکراری خرابی به‌نظر می‌رسد، نه طرح
  const coverPool = useMemo(
    () => [...new Set(library.map((x) => x.track.artworkUrl).filter((url) => Boolean(url)))] as string[],
    [library],
  )

  const recentShelf = recent.length > 0 && (
    <section className="rise" style={{ animationDelay: '210ms' }}>
      <SectionHead
        title={t.recentlyDownloaded}
        hint={t.recentlyDownloadedHint}
        action={
          <button
            onClick={onOpenLibrary}
            className="inline-flex shrink-0 items-center gap-1 rounded-full border border-line bg-panel px-3 py-1.5 text-[11px] text-muted transition hover:text-fg"
          >
            <LibraryIcon className="size-3.5" />
            {t.seeAll}
          </button>
        }
      />
      <Shelf>
        {recent.map((item, i) => (
          <TrackTile key={item.jobId} item={item} queue={recentQueue} index={i} />
        ))}
      </Shelf>
    </section>
  )

  return (
    <div className="space-y-10 pb-4 pt-6 sm:pt-8">
      <Hero />

      {/* تأخیرِ پلکانی: ردیف‌ها یکی‌یکی بالا می‌آیند، نه همه با هم مثل یک پرش */}
      {history.length > 0 && (
        <section className="rise" style={{ animationDelay: '70ms' }}>
          <SectionHead title={t.jumpBackIn} hint={t.jumpBackInHint} />
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {history.slice(0, 6).map((entry) => (
              <QuickPick key={entry.key} entry={entry} onOpenRef={onOpenRef} />
            ))}
          </div>
        </section>
      )}

      {!history.length && libraryLoaded && recent.length === 0 && (
        <StarterSearch onSearch={onSearch} />
      )}

      {!history.length && recent.length > 0 && recentShelf}

      <DailyMixShelf />

      <section className="rise" style={{ animationDelay: '140ms' }}>
        <SectionHead
          title={t.madeForYou}
          hint={t.madeForYouHint}
          icon={<ExploreIcon className="size-4 text-accent" />}
        />
        <Shelf>
          {VIBE_KEYS.map((key) => (
            <VibeTile key={key} vibe={key} covers={vibeCovers(coverPool, key)} />
          ))}
        </Shelf>
      </section>

      {history.length > 0 && recentShelf}
    </div>
  )
}

function StarterSearch({ onSearch }: { onSearch: (query: string) => void }) {
  const { t, lang } = useI18n()
  const queries = STARTER_QUERIES[lang]

  return (
    <section className="rise rounded-2xl border border-line-soft bg-panel/50 p-4 sm:p-5">
      <SectionHead title={t.homeStartTitle} hint={t.homeStartHint} />
      <div className="flex flex-wrap gap-2">
        {queries.map((query) => (
          <button
            key={query}
            onClick={() => onSearch(query)}
            className="rounded-full border border-line bg-panel px-3.5 py-2 text-xs text-muted transition hover:border-accent/50 hover:text-fg"
          >
            {query}
          </button>
        ))}
      </div>
    </section>
  )
}

/**
 * چیزهایی که روی دیسک نشسته‌اند — هم ردیفِ «تازه گرفته‌ای» و هم استخرِ کاورِ
 * کاشی‌های حس‌وحال از این می‌آید، پس کاملش برمی‌گردد نه فقط چندتای اول.
 *
 * مود دمو اصلاً کتابخانه ندارد؛ آن‌جا ردیف کلاً رندر نمی‌شود به‌جای این‌که یک
 * جعبه‌ی خالیِ «در دسترس نیست» وسط خانه بگذارد.
 */
function useRecentLibrary(): { items: LibraryItem[]; loaded: boolean } {
  const [items, setItems] = useState<LibraryItem[]>([])
  const [loaded, setLoaded] = useState(API_MODE !== 'http')

  useEffect(() => {
    if (API_MODE !== 'http') return
    const ctrl = new AbortController()
    api
      .library('', ctrl.signal)
      .then((page) => {
        if (!ctrl.signal.aborted) {
          setItems(page?.items ?? [])
          setLoaded(true)
        }
      })
      // خانه بدون این ردیف هم کامل است — خطای کتابخانه ارزش توست ندارد
      .catch(() => {
        if (!ctrl.signal.aborted) setLoaded(true)
      })
    return () => ctrl.abort()
  }, [])

  return { items, loaded }
}

function Hero() {
  const { t, lang } = useI18n()

  return (
    <section className="rise relative isolate overflow-hidden rounded-2xl border border-line-soft bg-panel/40 px-5 py-5 sm:rounded-3xl sm:px-8 sm:py-6">
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10">
        <div className="absolute -top-20 start-[-2rem] size-48 rounded-full bg-accent/20 blur-[60px]" />
        <div className="absolute -bottom-20 end-[-1.5rem] size-52 rounded-full bg-accent-2/15 blur-[70px]" />
      </div>

      <p
        className={`flex items-center gap-1.5 text-[11px] font-semibold text-muted-2 ${
          lang === 'en' ? 'uppercase tracking-[0.18em]' : ''
        }`}
      >
        <SparkleIcon className="size-3.5 text-accent" />
        {greeting(t)}
      </p>

      <h1 className="mt-2 text-2xl font-black leading-tight sm:text-4xl sm:leading-tight">
        {t.heroLine1}
        <br />
        <ShinyText>{t.heroLine2}</ShinyText>
      </h1>

      <p className="mt-2.5 max-w-xl text-xs leading-5 text-muted sm:text-sm sm:leading-6">
        {t.heroBody}
      </p>

      <div className="mt-4 flex items-center gap-2.5">
        <span className="shrink-0 text-[11px] text-muted-2">{t.worksWith}</span>
        <ul className="flex items-center gap-1.5" aria-label={t.worksWith}>
          {SOURCES.map((source) => (
            <li
              key={source}
              title={SOURCE_LABEL[source]}
              className="inline-grid size-6 shrink-0 place-items-center rounded-full border border-line bg-panel/70"
            >
              <SourceLogo source={source} className="size-3.5" />
              <span className="sr-only">{SOURCE_LABEL[source]}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}

/**
 * یک چیزِ اخیر: ترکی که پخش شده، یا صفحه‌ی هنرمند/آلبومی که باز شده.
 *
 * ترک همان‌جا پخش می‌شود و بقیه صفحه‌شان باز می‌شود؛ برای همین آیکونِ گوشه هم
 * فرق می‌کند — دایره‌ی پخش در برابر فلشِ رفتن.
 */
function QuickPick({
  entry,
  onOpenRef,
}: {
  entry: RecentEntry
  onOpenRef: (kind: 'artist' | 'album', ref: string) => void
}) {
  const { t } = useI18n()
  const play = usePlayer((s) => s.play)
  const toggle = usePlayer((s) => s.toggle)
  const currentId = usePlayer((s) => s.queue[s.index]?.id ?? null)
  const playing = usePlayer((s) => s.playing)

  const isTrack = entry.kind === 'track'
  const isCurrent = isTrack && currentId === entry.item.id
  const isPlaying = isCurrent && playing
  const subtitle = entry.kind === 'artist' ? t.typeArtist : entry.subtitle

  const open = () => {
    if (entry.kind !== 'track') return onOpenRef(entry.kind, entry.ref)
    if (isCurrent) return toggle()
    play([entry.item], 0)
  }

  return (
    <SpotlightCard
      as="button"
      onClick={open}
      aria-label={isTrack ? (isPlaying ? t.pause : t.playTrack(entry.title)) : t.openTitle(entry.title)}
      className="group flex items-center gap-3 overflow-hidden rounded-xl border border-line-soft bg-panel-2/60 pe-3 text-start transition hover:border-line hover:bg-panel-2"
    >
      {/* هنرمند دایره‌ای است و آلبوم/ترک مربعِ لبه‌به‌لبه — همان قراردادی که در
          کارت‌های نتایج جستجو هم هست، تا نوعِ هر ردیف از دور معلوم باشد */}
      {entry.kind === 'artist' ? (
        <span className="grid size-14 shrink-0 place-items-center">
          <Artwork
            src={entry.artworkUrl}
            alt={entry.title}
            seed={entry.seed}
            rounded="rounded-full"
            className="size-11"
          />
        </span>
      ) : (
        <Artwork
          src={entry.artworkUrl}
          alt={entry.title}
          seed={entry.seed}
          rounded="rounded-none"
          className="size-14 shrink-0"
        />
      )}

      <span className="min-w-0 flex-1">
        <span
          className={`bidi block truncate text-sm font-medium ${isCurrent ? 'text-accent' : ''}`}
        >
          {entry.title}
        </span>
        {subtitle && <span className="bidi block truncate text-[11px] text-muted-2">{subtitle}</span>}
      </span>

      <span
        className={`grid size-7 shrink-0 place-items-center rounded-full bg-accent text-accent-fg transition ${
          isCurrent ? 'opacity-100' : 'hover-reveal opacity-0 group-hover:opacity-100'
        }`}
      >
        {isTrack ? (
          isPlaying ? (
            <PauseIcon className="size-3.5" />
          ) : (
            <PlayIcon className="size-3.5" />
          )
        ) : (
          <ArrowIcon className="size-3.5" />
        )}
      </span>
    </SpotlightCard>
  )
}

/**
 * کاشیِ حس‌وحال با موزاییکِ کاورهای واقعیِ کتابخانه.
 *
 * تا وقتی چهار کاورِ یکتا نداریم (کتابخانه‌ی خالی یا مود دمو)، همان گرادیانِ
 * رنگیِ حس می‌ماند — نه کاورِ تکراری، نه جای خالیِ خاکستری.
 */
function VibeTile({ vibe, covers }: { vibe: string; covers: string[] }) {
  const { t } = useI18n()
  const ask = useMoodChat((s) => s.ask)
  const { text } = splitVibeLabel(vibeLabel(t, vibe))
  const [from, to] = VIBE_GRADIENT[vibe] ?? ['#3a3a3a', '#8a8a8a']
  const mosaic = covers.length === 4

  return (
    <button
      onClick={() => ask(vibe)}
      aria-label={t.vibePlaylistFor(text)}
      className="group relative aspect-square w-32 shrink-0 snap-start overflow-hidden rounded-2xl text-start shadow-lg shadow-black/30 transition hover:-translate-y-0.5 sm:w-36"
      style={mosaic ? undefined : { background: `linear-gradient(150deg, ${from}, ${to})` }}
    >
      {/* grid-rows-2 صریح است: با ردیف‌های ضمنی، ارتفاعِ h-full به ردیفی وابسته
          می‌شود که خودش از محتوا اندازه می‌گیرد و در بعضی موتورها (سافاری)
          موزاییک جمع می‌شود */}
      {mosaic ? (
        <span
          aria-hidden
          className="absolute inset-0 grid grid-cols-2 grid-rows-2 transition duration-500 group-hover:scale-[1.06]"
        >
          {covers.map((url) => (
            <img key={url} src={url} alt="" loading="lazy" className="size-full object-cover" />
          ))}
        </span>
      ) : (
        <span
          aria-hidden
          className="pointer-events-none absolute -end-6 -top-8 size-24 rounded-full bg-white/20 blur-xl transition group-hover:bg-white/30"
        />
      )}

      {/*
        سه لایه روی موزاییک:
        soft-light رنگِ حس را روی کلِ عکس‌ها می‌نشاند بدون این‌که مثل فیلترِ تخت
        رویشان بیفتد؛ نوارِ رنگیِ پایین همان حس را جایی که اسم می‌نشیند غلیظ
        می‌کند (وگرنه چهار کاورِ شلوغ، تفاوتِ کاشی‌ها را می‌بلعند)؛ و لایه‌ی
        سیاه فقط بیمه‌ی خوانایی است، چون رنگِ بعضی حس‌ها روشن است.
      */}
      {mosaic && (
        <>
          <span
            aria-hidden
            className="absolute inset-0"
            style={{
              background: `linear-gradient(155deg, ${from}, ${to})`,
              opacity: 0.55,
              mixBlendMode: 'soft-light',
            }}
          />
          <span
            aria-hidden
            className="absolute inset-0"
            style={{ background: `linear-gradient(to top, ${from} 4%, transparent 70%)`, opacity: 0.95 }}
          />
          <span
            aria-hidden
            className="absolute inset-0 bg-gradient-to-t from-black/55 via-transparent to-transparent"
          />
        </>
      )}

      <span className="absolute inset-x-3 bottom-3">
        <span className="block text-[10px] uppercase tracking-wide text-white/65">
          {t.vibePlaylist}
        </span>
        <span className="bidi block truncate text-sm font-bold text-white drop-shadow">{text}</span>
        <span className="bidi mt-0.5 block truncate text-[10px] text-white/80 drop-shadow">
          {t[`vibe${vibe[0].toUpperCase()}${vibe.slice(1)}Hint` as keyof Dict] as string}
        </span>
      </span>

      <span className="hover-reveal absolute end-2 top-2 grid size-7 place-items-center rounded-full bg-accent text-accent-fg opacity-0 shadow-lg shadow-black/40 transition group-hover:opacity-100">
        <SparkleIcon className="size-3.5" />
      </span>
    </button>
  )
}

/**
 * میکسِ روزانه — پیشنهادِ سرور از کتابخانه بر اساسِ سلیقه‌ی خودِ کاربر.
 *
 * تنها سکشنی است که سرور می‌چیندش (نه خودِ کاربر). وقتی نه لایکی هست نه پخشی
 * (`source === 'none'`) یا مود دمو، کلاً رندر نمی‌شود — پیشنهادی که پشتش
 * سیگنالی نیست، یک ردیفِ تصادفی است و از نداشتنش بدتر است.
 */
function DailyMixShelf() {
  const { t } = useI18n()
  const [mix, setMix] = useState<DailyMix | null>(null)

  useEffect(() => {
    if (API_MODE !== 'http') return
    const ctrl = new AbortController()
    api
      .dailyMix(ctrl.signal)
      .then((m) => {
        if (!ctrl.signal.aborted) setMix(m)
      })
      // خانه بدون میکس هم کامل است — خطایش ارزش توست ندارد
      .catch(() => {})
    return () => ctrl.abort()
  }, [])

  const items = mix?.items ?? []
  const play = usePlayer((s) => s.play)
  if (!mix || mix.source === 'none' || items.length === 0) return null

  const queue = items.map(toPlayItem)
  const hint = mix.source === 'favorites' ? t.dailyMixFromFavorites : t.dailyMixFromRecent

  return (
    <section className="rise" style={{ animationDelay: '105ms' }}>
      <SectionHead
        title={t.dailyMix}
        hint={`${t.dailyMixHint} — ${hint}`}
        action={
          <button
            onClick={() => play(queue, 0)}
            className="inline-flex shrink-0 items-center gap-1 rounded-full border border-line bg-panel px-3 py-1.5 text-[11px] text-muted transition hover:text-fg"
          >
            <PlayIcon className="size-3.5" />
            {t.playAll}
          </button>
        }
      />
      <Shelf>
        {items.map((item, i) => (
          <TrackTile key={item.jobId} item={item} queue={queue} index={i} />
        ))}
      </Shelf>
    </section>
  )
}

