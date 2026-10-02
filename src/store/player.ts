import { create } from 'zustand'
import { api } from '../lib/api'
import { claimAudio, registerAudio } from '../lib/audioFocus'
import { engine } from '../lib/audioEngine'
import {
  ensureNotificationPermission,
  onTransport,
  setNativeSleepTimer,
  stopPlaybackNotification,
  syncPlayback,
} from '../lib/native'
import { useI18n } from '../lib/i18n'
import { downloadRadioTrack, findRadioTrack, radioKey } from '../lib/radio'
import { pickShuffleIndex } from '../lib/shuffle'
import { readStored, readStoredNumber, removeStored, writeStored } from '../lib/storage'
import type { Track } from '../lib/types'
import { useRecent } from './recent'
import { useSettings } from './settings'
import { useToasts } from './toasts'

/** یک ترکِ آماده روی دیسک سرور، از زاویه‌ی پخش */
export interface PlayItem {
  /** کلید یکتا در صف — برای موارد کتابخانه همان jobId است */
  id: string
  track: Track
  streamUrl: string
  /** فایل .lrc اگر متن هم‌زمان‌شده پیدا شده باشد */
  lyricsUrl?: string
  /**
   * هم‌ترازیِ بلندی (دسی‌بل) که سرور با EBU R128 اندازه گرفته. بدون آن، هر
   * چند ترک یک‌بار باید دستی صدا را کم و زیاد کرد.
   */
  gainDb?: number
}

/**
 * jobId واقعیِ سرور برای ثبتِ پخش. ردیف‌های کتابخانه خودشان jobId هستند؛
 * ترک‌های رادیو شناسه‌ی `radio-…` دارند و jobId از streamUrl استخراج می‌شود؛
 * ترک‌های استریم آنلاین شناسه‌ی `stream:…` دارند و هرگز جاب دیتابیسی ندارند.
 */
export function jobIdOf(item: PlayItem): string | null {
  if (item.id.startsWith('stream:')) return null
  if (!item.id.startsWith('radio-')) return item.id
  const m = item.streamUrl.match(/\/downloads\/([^/]+)\/stream/)
  return m?.[1] ?? null
}

export type Repeat = 'off' | 'all' | 'one'

const VOLUME_KEY = 'player:volume'
const RESUME_KEY = 'player:resume'

/**
 * چیزی که بین دو بازدید زنده می‌ماند.
 *
 * کل صف ذخیره نمی‌شود: یک کتابخانه‌ی چندصدتایی چند صد کیلوبایت JSON است و
 * localStorage جای درستی برایش نیست. فقط همان ترکی که وسطش بودی برمی‌گردد —
 * بقیه‌ی صف یک کلیک فاصله دارد.
 */
interface Resume {
  item: PlayItem
  position: number
}

function readResume(): Resume | null {
  try {
    const raw = readStored(RESUME_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Resume
    return parsed?.item?.streamUrl ? parsed : null
  } catch {
    return null
  }
}

function readVolume(): number {
  return readStoredNumber(VOLUME_KEY, 1, { min: 0, max: 1 })
}

/**
 * وضعیتِ بعدیِ دکمه‌ی بی‌صدا.
 *
 * دو چیزِ متفاوت اینجا به هم می‌رسند و قبلاً قاطی شده بودند: پرچمِ `muted`ِ
 * المنت، و بلندیِ صفر. کشیدنِ نوارِ بلندی تا ته، `muted` را در state روشن
 * می‌کرد ولی هیچ‌وقت `engine.setMuted` را صدا نمی‌زد — پس دکمه‌ی بی‌صدا
 * پرچمی را برمی‌داشت که اصلاً بالا نرفته بود و بلندی صفر می‌ماند: آیکون
 * می‌گفت صدا وصل است و کاربر هیچ نمی‌شنید، بدون هیچ راهی جز دستکاریِ دوباره‌ی
 * نوار.
 *
 * حالا برگشت از بی‌صدا تضمین می‌کند صدا واقعاً برمی‌گردد: بلندیِ پیش از
 * بی‌صدا، وگرنه تهِ نوار.
 */
export function nextMuteState(
  volume: number,
  muted: boolean,
  remembered: number,
): { muted: boolean; volume: number } {
  if (!muted) return { muted: true, volume }
  if (volume > 0) return { muted: false, volume }
  return { muted: false, volume: remembered > 0 ? remembered : 1 }
}

interface PlayerState {
  queue: PlayItem[]
  index: number
  playing: boolean
  /** ثانیه */
  position: number
  duration: number
  volume: number
  muted: boolean
  repeat: Repeat
  shuffle: boolean
  /** فقط وقتی shuffle روشن است اثر دارد — ترکِ بعدی را به‌جای تصادفِ محض، با وزنِ نزدیکیِ حس‌وحال انتخاب می‌کند */
  smartShuffle: boolean
  /** فایل قابل پخش نبود — ردیف باید خطا را نشان بدهد، نه سکوت */
  failed: boolean
  /** وقتی صف تمام شود، به‌جای توقف از همان هنرمند ادامه بده */
  radio: boolean
  /** رادیو در حال جستجو/دانلودِ ترکِ بعدی است */
  radioLoading: boolean
  /** زمانِ خاموش‌شدنِ خودکار (اپاکِ میلی‌ثانیه یا 'track_end')، یا null یعنی تایمری در کار نیست */
  sleepAt: number | 'track_end' | null

  play: (items: PlayItem[], startIndex?: number) => void
  /** به عنوان ترک‌های بعدی صف درج می‌کند تا بلافاصله پس از ترک جاری پخش شوند */
  playNext: (items: PlayItem[]) => void
  /** به صفِ فعلی اضافه می‌کند بدون قطعِ پخش — برای پرشدنِ تدریجیِ پلی‌لیستِ چت‌بات وایب */
  enqueue: (items: PlayItem[]) => void
  toggle: () => void
  pause: () => void
  next: () => void
  prev: () => void
  seek: (seconds: number) => void
  setVolume: (v: number) => void
  toggleMute: () => void
  cycleRepeat: () => void
  toggleShuffle: () => void
  setShuffle: (shuffle: boolean) => void
  toggleSmartShuffle: () => void
  toggleRadio: () => void
  /** خاموشیِ خودکار بعد از این تعداد دقیقه یا در پایان همین ترک؛ null یعنی لغو */
  setSleepTimer: (choice: number | 'track_end' | null) => void
  /** یک مورد از صف بیرون می‌رود (مثلاً از کتابخانه پاک شده) */
  drop: (id: string) => void
  close: () => void
}

export const usePlayer = create<PlayerState>((set, get) => {
  let lastSaved = 0
  let ready = false
  let sleepTimer: ReturnType<typeof setTimeout> | undefined

  // بلندیِ پیش از بی‌صدا شدن — تا برگشت از بی‌صدا همان‌جایی برگردد که بود،
  // نه تهِ نوار
  let beforeMute = readVolume() || 1

  // نتیجه‌ی یک fetch رادیوی قدیمی (کاربر رادیو را خاموش کرده یا ترک دیگری زده)
  // باید بی‌صدا دور ریخته شود؛ هر play/close/extendRadio تازه یکی به این
  // شمارنده اضافه می‌کند و نتیجه فقط اگر توکنش هنوز جاری باشد اعمال می‌شود.
  let radioToken = 0
  // کلیدهای (عنوان، هنرمند) که این جلسه‌ی رادیو قبلاً پیشنهاد داده — جلوی
  // تکرار زودهنگام همان چند ترک محبوب هنرمند را می‌گیرد.
  let radioSeen = new Set<string>()

  // ایندکسی که کراس‌فید به آن خواهد رفت. موتور فقط آدرسِ بعدی را می‌داند؛
  // اینکه آن آدرس کدام ردیفِ صف بود را همین‌جا نگه می‌داریم، وگرنه بعد از
  // شروعِ فید معلوم نبود شمارنده‌ی صف کجا برود (به‌خصوص با شافل).
  let pendingNext: number | null = null

  // تاریخچه‌ی ایندکس‌های پخش‌شده برای بازگشتِ درستِ دکمه‌ی «قبلی» در حالتِ شافل
  let historyStack: number[] = []

  /*
   * آخرین باری که وضعیت به نوتیفیکیشنِ اندروید رفت.
   *
   * موقعیتِ پخش هر ثانیه تیک می‌زند ولی هر ثانیه ساختنِ دوباره‌ی نوتیفیکیشن
   * اسراف است — اندروید خودش از روی `playbackSpeed` موقعیت را جلو می‌برد. پس
   * فقط رویدادهای واقعی (ترک، پخش/مکث، جابه‌جایی) فوری می‌روند و موقعیت هر
   * چند ثانیه یک‌بار برای جبرانِ رانش.
   */
  let lastNativeSync = 0
  let notifyAsked = false

  const current = () => get().queue[get().index] as PlayItem | undefined

  function save(force = false) {
    const item = current()
    if (!item) return
    const now = Date.now()
    if (!force && now - lastSaved < 5000) return
    lastSaved = now
    // نشدنش مهم نیست: ادامه‌ی پخش مهم‌تر از یادآوریِ جایگاه است
    writeStored(RESUME_KEY, JSON.stringify({ item, position: get().position } satisfies Resume))
  }

  /**
   * اتصالِ یک‌باره به موتور صوتی.
   *
   * موتور بیرون از React زندگی می‌کند (وگرنه هر ناوبری بین صفحه‌ها پخش را از
   * صفر شروع می‌کرد) و ساختش تنبل است تا ایمپورت این ماژول در محیط بدون DOM
   * (تست‌ها) نشکند.
   */
  function setup() {
    if (ready) return
    ready = true

    engine.init({
      onPlay: () => {
        set({ playing: true, failed: false })
        syncNative(true)
      },
      onPause: () => {
        set({ playing: false })
        save(true)
        syncNative(true)
      },
      onTime: (seconds) => {
        set({ position: seconds })
        save()
        updatePositionState()
        syncNative()
      },
      onDuration: (seconds) => {
        set({ duration: seconds })
        updatePositionState()
      },
      onEnded: () => {
        if (get().sleepAt === 'track_end') {
          get().pause()
          set({ sleepAt: null })
          return
        }
        if (get().repeat === 'one') {
          engine.seek(0)
          engine.play()
          return
        }
        get().next()
      },
      // فایل ممکن است بین پخش و کلیک پاک شده باشد (پاک‌سازی دیسک یا حذف دستی)
      onError: () => set({ playing: false, failed: true }),
      onAdvance: () => advanceFromCrossfade(),
    })

    const settings = useSettings.getState()
    engine.setCrossfade(settings.crossfade)
    engine.setEq(settings.eq)
    engine.setNormalize(settings.normalize)
    engine.setBoost(settings.boost)
    engine.setVolume(get().volume)

    registerAudio('player', () => engine.pause())

    /*
     * دکمه‌های نوتیفیکیشن، صفحه‌ی قفل و هدفون همگی به همین اکشن‌ها می‌رسند —
     * نه به یک مسیرِ موازی. هر منطقِ جداگانه‌ای اینجا یعنی «بعدی»ِ نوتیفیکیشن
     * دیر یا زود با «بعدی»ِ داخلِ اپ فرق می‌کند (شافل، تکرار، رادیو).
     */
    onTransport((action, value) => {
      const state = get()
      if (action === 'play') {
        if (!state.playing) state.toggle()
      } else if (action === 'pause') {
        state.pause()
      } else if (action === 'next') state.next()
      else if (action === 'prev') state.prev()
      else if (action === 'stop') state.close()
      else if (action === 'seek') state.seek(value)
      // زنگِ تایمرِ خوابِ نیتیو. `pause()` نه `toggle()`: اگر JS هم‌زمان خودش
      // تایمر را زده باشد، این یکی بی‌اثر است و دوتایی پخش را روشن نمی‌کند.
      else if (action === 'sleep') state.pause()
    })
  }

  /**
   * ترکی که کراس‌فید باید سراغش برود.
   *
   * با تکرارِ تک‌ترک عمداً خالی می‌ماند: آنجا «بعدی» خودِ همین ترک است و
   * محوکردنش روی خودش فقط یک پژواکِ عجیب می‌سازد.
   */
  function scheduleNext() {
    if (get().sleepAt === 'track_end') {
      pendingNext = null
      engine.setNext(null)
      return
    }
    const next = get().repeat === 'one' ? null : nextIndex()
    // «بعدی» که خودِ ترکِ فعلی است هم همان حالت است: صفِ یک‌تایی با تکرارِ
    // همه، `nextIndex` را به ایندکسِ خودش می‌رساند و کراس‌فید ترک را روی
    // خودش محو می‌کرد — همان پژواکی که تکرارِ تک‌ترک از آن پرهیز می‌کند.
    const target = next === get().index ? null : next
    pendingNext = target
    const item = target === null ? undefined : get().queue[target]
    engine.setNext(item?.streamUrl ?? null, item?.gainDb ?? 0)
    if (item?.id.startsWith('stream:') && item?.track) {
      void api.prefetchStream?.(item.track).catch(() => {})
    }
  }

  /**
   * موتور خودش ترکِ بعدی را بالا آورده؛ اینجا فقط شمارنده و متادیتا جلو
   * می‌روند. صدا زدنِ `load` اینجا یعنی قطع کردنِ همان فیدی که تازه شروع شده.
   */
  function advanceFromCrossfade() {
    if (pendingNext === null) return
    const target = pendingNext
    const item = get().queue[target]
    if (!item) return

    const prevIdx = get().index
    if (prevIdx !== target) {
      historyStack.push(prevIdx)
      if (historyStack.length > 50) historyStack.shift()
    }

    set({ index: target, position: 0, failed: false })
    mediaSession(item)
    syncNative(true)
    remember(item)
    recordPlay(item)
    scheduleNext()
  }

  /** «ادامه بده»ی صفحه‌ی خانه از همین‌جا پر می‌شود */
  function remember(item: PlayItem) {
    useRecent.getState().push({
      kind: 'track',
      key: `track:${item.track.id}`,
      title: item.track.title,
      subtitle: item.track.artist,
      artworkUrl: item.track.artworkUrl,
      seed: item.track.albumId ?? item.track.id,
      item,
    })
  }

  /**
   * ثبتِ یک رویدادِ پخش سمتِ سرور — برای آمار و تاریخچه.
   *
   * fire-and-forget است: شکستش نباید پخش را خراب کند. `seconds` فعلاً فرستاده
   * نمی‌شود و سرور کلِ مدتِ ترک را حساب می‌کند؛ دقیق‌تر کردنش (فرستادنِ ثانیه‌ی
   * واقعی موقع رد شدن) یک بهینه‌سازی آینده است.
   */
  function recordPlay(item: PlayItem) {
    const jobId = jobIdOf(item)
    if (jobId) void api.recordPlay(jobId)
  }

  /** ترک فعلی را روی موتور می‌نشاند. `at` برای «ادامه از جایی که بودی» است. */
  function load(item: PlayItem, { autoplay = true, at = 0 } = {}) {
    setup()

    // بدون این، آدرسِ نبوده به رشته‌ی «undefined» تبدیل می‌شود، مرورگر آن را
    // یک مسیر نسبی می‌فهمد و ۴۰۴ می‌گیرد — و خطا شبیه «فایل پاک شده» درمی‌آید
    // درحالی‌که فایل سر جایش است و فقط بک‌اند این فیلد را نفرستاده.
    if (!item.streamUrl) {
      set({ playing: false, failed: true })
      return
    }

    set({ position: at, duration: item.track.durationMs / 1000, failed: false })
    mediaSession(item)

    // autoplay خاموش یعنی ترک فقط جایگزینِ ردیفِ حذف‌شده شده و کسی پخشش
    // نکرده، پس شنیده‌شده حساب نمی‌شود
    if (autoplay) {
      claimAudio('player')
      remember(item)
      recordPlay(item)
      /*
       * اجازه‌ی نوتیفیکیشن دقیقاً همین‌جا پرسیده می‌شود: اولین باری که کاربر
       * چیزی پخش می‌کند. زودتر از این (موقعِ باز شدنِ اپ) هنوز معلوم نیست
       * چرا لازم است و جوابش «نه» می‌شود؛ دیرتر از این، پخشِ پس‌زمینه یک‌بار
       * بی‌سروصدا شکست خورده است.
       */
      if (!notifyAsked) {
        notifyAsked = true
        void ensureNotificationPermission().then((granted) => {
          if (granted) syncNative(true)
        })
      }
    }

    syncNative(true)

    engine.load(item.streamUrl, { gainDb: item.gainDb ?? 0, at, autoplay })
    scheduleNext()
  }

  /** کلیدهای رسانه‌ای سیستم‌عامل و کنترل روی صفحه‌ی قفل */
  function mediaSession(item: PlayItem) {
    if (!('mediaSession' in navigator)) return
    const { track } = item
    navigator.mediaSession.metadata = new MediaMetadata({
      title: track.title,
      artist: track.artist,
      album: track.album ?? '',
      artwork: track.artworkUrl ? [{ src: track.artworkUrl, sizes: '512x512' }] : [],
    })
    navigator.mediaSession.setActionHandler('play', () => get().toggle())
    navigator.mediaSession.setActionHandler('pause', () => get().pause())
    navigator.mediaSession.setActionHandler('previoustrack', () => get().prev())
    navigator.mediaSession.setActionHandler('nexttrack', () => get().next())
    // بدون این دو، دکمه‌ی جابه‌جایی روی صفحه‌ی قفل موبایل کاری نمی‌کند
    navigator.mediaSession.setActionHandler('seekto', (details) => {
      if (details.seekTime != null) get().seek(details.seekTime)
    })
    navigator.mediaSession.setActionHandler('stop', () => get().close())
  }

  /**
   * همان متادیتا، این‌بار برای نوتیفیکیشنِ نیتیوِ اندروید.
   *
   * `mediaSession` وب داخل WebView به هیچ نوتیفیکیشنی وصل نیست، پس این دومی
   * تکرار نیست — تنها راهِ دیده‌شدنِ پخش بیرون از خودِ اپ است.
   */
  function syncNative(force = false) {
    const item = current()
    if (!item) return
    const now = Date.now()
    if (!force && now - lastNativeSync < 5000) return
    lastNativeSync = now

    const { track } = item
    syncPlayback({
      title: track.title,
      artist: track.artist,
      album: track.album ?? '',
      artworkUrl: track.artworkUrl ?? '',
      playing: get().playing,
      position: get().position,
      duration: get().duration || track.durationMs / 1000,
    })
  }

  /** نوار پیشرفتِ صفحه‌ی قفل — بدونش همیشه صفر می‌ماند و seekto بی‌معنی است */
  function updatePositionState() {
    if (!('mediaSession' in navigator) || !('setPositionState' in navigator.mediaSession)) return
    const duration = get().duration
    if (!Number.isFinite(duration) || duration <= 0) return
    navigator.mediaSession.setPositionState({
      duration,
      position: Math.min(get().position, duration),
      playbackRate: 1,
    })
  }

  /** ایندکس بعدی با درنظرگرفتن شافل و تکرار، یا null اگر صف تمام شده */
  function nextIndex(): number | null {
    const { queue, index, shuffle, smartShuffle, repeat } = get()
    if (queue.length <= 1) return repeat === 'all' ? index : null
    if (shuffle) {
      if (smartShuffle) return pickShuffleIndex(queue, index)
      const offset = 1 + Math.floor(Math.random() * (queue.length - 1))
      return (index + offset) % queue.length
    }
    if (index + 1 < queue.length) return index + 1
    return repeat === 'all' ? 0 : null
  }

  /** رفتار پایانِ صفِ معمولی — همان چیزی که قبل از رادیو در انتهای صف اتفاق می‌افتاد */
  function stopAtEnd() {
    engine.pause()
    engine.seek(0)
    set({ position: 0, radioLoading: false })
  }

  /**
   * صف تمام شده و رادیو روشن است: یک ترکِ دیگر از همان هنرمند پیدا، دانلود و
   * پخش می‌شود. اگر چیزی پیدا نشود یا دانلود شکست بخورد، درست مثل پایانِ صفِ
   * معمولی متوقف می‌شود — رادیو زنجیره‌ی هنرمندهای مرتبط نمی‌سازد.
   */
  async function extendRadio() {
    const seed = current()
    if (!seed) return
    const token = ++radioToken
    set({ radioLoading: true })

    const exclude = new Set([...get().queue.map((i) => radioKey(i.track)), ...radioSeen])
    const track = await findRadioTrack(seed.track, exclude)
    if (token !== radioToken) return

    if (!track) {
      stopAtEnd()
      useToasts.getState().push(useI18n.getState().t.radioEmpty, 'info')
      return
    }

    const result = await downloadRadioTrack(track, useSettings.getState().quality)
    if (token !== radioToken) return

    if (!result) {
      stopAtEnd()
      useToasts.getState().push(useI18n.getState().t.radioEmpty, 'info')
      return
    }

    radioSeen.add(radioKey(track))
    const item: PlayItem = {
      id: `radio-${track.id}-${Date.now()}`,
      track,
      streamUrl: result.streamUrl,
      lyricsUrl: result.lyricsUrl,
      gainDb: result.gainDb,
    }
    const queue = [...get().queue, item]
    set({ queue, index: queue.length - 1, radioLoading: false })
    load(item)
  }

  const resumed = readResume()

  return {
    queue: resumed ? [resumed.item] : [],
    index: 0,
    playing: false,
    position: resumed?.position ?? 0,
    duration: resumed ? resumed.item.track.durationMs / 1000 : 0,
    volume: readVolume(),
    muted: false,
    repeat: 'off',
    shuffle: false,
    smartShuffle: false,
    failed: false,
    radio: false,
    radioLoading: false,
    sleepAt: null,

    play: (items, startIndex = 0) => {
      if (!items.length) return
      const index = Math.max(0, Math.min(startIndex, items.length - 1))
      const item = items[index]
      const same = current()?.id === item.id

      // صفِ تازه یعنی جلسه‌ی رادیوی قبلی و تاریخچه‌ی پخش هم تازه شوند
      historyStack = []
      radioToken++
      radioSeen = new Set(items.map((i) => radioKey(i.track)))
      set({ queue: items, index, radioLoading: false })
      // کلیک دوباره روی همان ترکی که در حال پخش است یعنی «مکث»، نه «از اول»
      if (same && get().playing) {
        engine.pause()
        scheduleNext()
        return
      }
      // بعد از رفرش، همان ترک از همان‌جا ادامه می‌دهد
      load(item, { at: same ? get().position : 0 })
    },

    playNext: (items) => {
      if (!items.length) return
      const { queue, index } = get()
      if (!queue.length) {
        get().play(items, 0)
        return
      }
      const insertIndex = Math.min(index + 1, queue.length)
      const nextQueue = [
        ...queue.slice(0, insertIndex),
        ...items,
        ...queue.slice(insertIndex),
      ]
      set({ queue: nextQueue })
      scheduleNext()
    },

    enqueue: (items) => {
      if (!items.length) return
      set({ queue: [...get().queue, ...items] })
      // صفِ بلندتر یعنی «بعدی»ِ تازه — بدون این، کراس‌فیدِ انتهای ترکِ فعلی
      // هنوز فکر می‌کند چیزی بعدش نیست
      scheduleNext()
    },

    toggle: () => {
      const item = current()
      if (!item) return
      setup()
      if (!engine.hasSource()) {
        load(item, { at: get().position })
        return
      }
      if (engine.paused()) {
        claimAudio('player')
        engine.play()
      } else {
        engine.pause()
      }
    },

    pause: () => engine.pause(),

    next: () => {
      const target = nextIndex()
      if (target === null) {
        if (get().radio) {
          void extendRadio()
          return
        }
        stopAtEnd()
        return
      }
      const currentIdx = get().index
      if (currentIdx !== target) {
        historyStack.push(currentIdx)
        if (historyStack.length > 50) historyStack.shift()
      }
      set({ index: target })
      load(get().queue[target])
    },

    prev: () => {
      // مثل هر پلیر دیگری: وسط ترک یعنی «از اول همین»، اول ترک یعنی «قبلی»
      if (get().position > 3) {
        engine.seek(0)
        return
      }
      const { index, queue, repeat } = get()
      // در حالت شافل یا در صورت وجود تاریخچه، اولویت با آهنگی است که کاربر قبل از این واقعاً شنیده
      while (historyStack.length > 0) {
        const candidate = historyStack.pop()!
        if (candidate >= 0 && candidate < queue.length && candidate !== index) {
          set({ index: candidate })
          load(queue[candidate])
          return
        }
      }
      if (index === 0 && repeat !== 'all') {
        engine.seek(0)
        return
      }
      const target = index > 0 ? index - 1 : queue.length - 1
      if (target === index) {
        engine.seek(0)
        return
      }
      set({ index: target })
      load(queue[target])
    },

    seek: (seconds) => {
      setup()
      const max = get().duration || engine.duration() || 0
      const value = Math.max(0, Math.min(seconds, max))
      engine.seek(value)
      set({ position: value })
      syncNative(true)
    },

    setVolume: (v) => {
      const value = Math.max(0, Math.min(1, v))
      if (value > 0) beforeMute = value
      engine.setVolume(value)
      // بالا بردنِ نوارِ بلندی خودش یعنی «دیگر بی‌صدا نباش» — وگرنه اگر قبلش
      // دکمه‌ی بی‌صدا زده شده بود، نوار حرکت می‌کرد و هیچ صدایی نمی‌آمد
      if (value > 0 && get().muted) engine.setMuted(false)
      writeStored(VOLUME_KEY, String(value))
      set({ volume: value, muted: value === 0 })
    },

    toggleMute: () => {
      const { volume, muted } = get()
      if (!muted && volume > 0) beforeMute = volume
      const next = nextMuteState(volume, muted, beforeMute)
      engine.setMuted(next.muted)
      if (next.volume !== volume) {
        engine.setVolume(next.volume)
        writeStored(VOLUME_KEY, String(next.volume))
      }
      set(next)
    },

    cycleRepeat: () => {
      set({ repeat: get().repeat === 'off' ? 'all' : get().repeat === 'all' ? 'one' : 'off' })
      scheduleNext()
    },

    toggleShuffle: () => {
      set({ shuffle: !get().shuffle })
      scheduleNext()
    },

    setShuffle: (shuffle: boolean) => {
      if (get().shuffle === shuffle) return
      set({ shuffle })
      scheduleNext()
    },

    toggleSmartShuffle: () => {
      set({ smartShuffle: !get().smartShuffle })
      scheduleNext()
    },

    toggleRadio: () => set({ radio: !get().radio }),

    setSleepTimer: (choice) => {
      clearTimeout(sleepTimer)
      if (choice === 'track_end') {
        setNativeSleepTimer(0)
        set({ sleepAt: 'track_end' })
        scheduleNext()
        return
      }
      // تایمرِ سیستم همیشه با همان عدد ست/لغو می‌شود تا دو ساعت از هم
      // واگرا نمانند (مثلاً کاربر تایمر را عوض کند وقتی صفحه پس‌زمینه است)
      setNativeSleepTimer(choice ?? 0)
      if (choice === null) {
        set({ sleepAt: null })
        scheduleNext()
        return
      }
      const at = Date.now() + choice * 60_000
      set({ sleepAt: at })
      scheduleNext()
      sleepTimer = setTimeout(() => {
        engine.pause()
        set({ sleepAt: null })
      }, choice * 60_000)
    },

    drop: (id) => {
      const { queue, index } = get()
      const at = queue.findIndex((i) => i.id === id)
      if (at < 0) return
      const rest = queue.filter((i) => i.id !== id)
      if (!rest.length) {
        get().close()
        return
      }
      if (at === index) {
        const target = Math.min(index, rest.length - 1)
        set({ queue: rest, index: target })
        load(rest[target], { autoplay: get().playing })
        return
      }
      set({ queue: rest, index: at < index ? index - 1 : index })
      scheduleNext()
    },

    close: () => {
      engine.stop()
      stopPlaybackNotification()
      removeStored(RESUME_KEY)
      clearTimeout(sleepTimer)
      // ساعتِ سیستم هم باید با ما بخوابد، وگرنه بعد از بستنِ پخش‌کننده یک
      // «sleep» بی‌صاحب می‌آید و روی صفِ خالی `pause()` می‌زند
      setNativeSleepTimer(0)
      // رادیوِ در حالِ fetch نباید بعد از بستنِ پخش‌کننده چیزی به صفِ خالی اضافه کند
      radioToken++
      pendingNext = null
      set({
        queue: [],
        index: 0,
        playing: false,
        position: 0,
        duration: 0,
        failed: false,
        radioLoading: false,
        sleepAt: null,
      })
    },
  }
})

/** آیا همین ترک الان روی پخش‌کننده است (و در حال پخش؟) */
export function usePlayingId(): string | null {
  return usePlayer((s) => s.queue[s.index]?.track.id ?? null)
}

/** آیتم جاری در صف پخش */
export function useCurrentItem(): PlayItem | null {
  return usePlayer((s) => s.queue[s.index] ?? null)
}
