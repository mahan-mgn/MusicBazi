/**
 * موتور پخش — دو «دک» صوتی زیر یک گرافِ Web Audio، رانده‌شده با state machine.
 *
 * این نسخه معماری اپ اندروید (`MusicBaziAudioEngine.kt` + `CrossfadeController.kt`)
 * را روی وب پیاده می‌کند:
 *
 *  ۱. **دو دکِ همتا** که همیشه زنده‌اند؛ دکِ غیرفعال از قبل ترکِ بعدی را
 *     بافر می‌کند (`setNext` — پربافرِ شبیه Spotify).
 *  ۲. **CrossfadeController** (پورت CrossfadeController.kt) با فازهای
 *     IDLE/ARMING/FADING/BAILING — به‌جای چکِ ادهاک روی timeupdate. تعویض
 *     نقش دک‌ها در *میانه* فید انجام می‌شود (t ≥ 0.5) نه در پایانش، تا آنچه
 *     UI نشان می‌دهد همان ترکی باشد که دارد بلند می‌شود.
 *  ۳. **هدررومِ ترکیب** حین فید (۱/√(out+in)) که بعداً به پردازندهٔ لودنس
 *     می‌رسد و جلوی کلیپِ جمع دو ترک را می‌گیرد.
 *  ۴. **وضعیت رسمی** (AudioState.kt) — یک منبع حقیقت برای IDLE/BUFFERING/
 *     READY/ENDED/ERROR به‌جای پرچم‌های پراکنده.
 *
 * زنجیرهٔ هر دک: `<audio>` → norm (هم‌ترازی) → fade (کراس‌فید) → EQ → مستر.
 * دو گِینِ جدا لازم است چون رمپِ کراس‌فید مقدارِ گِین را بازنویسی می‌کند و
 * اگر هم‌ترازی روی همان نود می‌نشست، هر فید تنظیمش را پاک می‌کرد.
 *
 * قراردادهای رفتاری که حفظ شده‌اند (هر کدام یک باگِ واقعی را بسته‌اند):
 *  - «هیچ‌چیز تا resolve شدنِ play() تثبیت نمی‌شود»: شکستِ play دکِ ورودی
 *    یعنی فید هرگز شروع نشده — ترک فعلی دست‌نخورده تا ENDED می‌رود.
 *  - اگر Web Audio نبود (یا مرورگر اجازه نداد)، همه‌چیز بی‌صدا به پخشِ سادهٔ
 *    همان `<audio>` برمی‌گردد: بدون هم‌ترازی، بدون EQ، بدون کراس‌فید — ولی
 *    صدا قطع نمی‌شود.
 */

export type EqPreset = 'off' | 'bass' | 'vocal' | 'treble' | 'loud'

import { detachHls, attachHls } from './hlsPlayback'
import { EngineStatePublisher } from './audio/AudioState'
import {
  CrossfadeController,
  MIN_CROSSFADE_SECONDS,
  TransitionLock,
  type CrossfadeActiveInfo,
  type CrossfadeHooks,
} from './audio/CrossfadeController'
import { combineCurves, flatCurve, manualCurve, toneCurve, EQ_SLOTS, type EqCurve } from './audio/dsp/EqCurve'
import { classifyMediaError, StreamRecovery, type StreamErrorKind } from './audio/StreamRecovery'
import type { AudioDiagnostics } from './native'
import {
  isSetSinkIdSupported,
  getSavedSinkId,
  saveSinkId,
  routeAudioElements,
  routeAudioContext,
} from './audio/AudioRouting'
import { planTransition, type TransitionPlan } from './audio/automix/TransitionPlanner'

/** فرکانس مرکزیِ باندها — پنج‌تایی استانداردِ اکولایزرهای مصرفی */
export const EQ_BANDS = [60, 230, 910, 3600, 14000]

/** تقویت/تضعیفِ هر باند به دسی‌بل، به همان ترتیبِ EQ_BANDS */
export const EQ_PRESETS: Record<EqPreset, number[]> = {
  off: [0, 0, 0, 0, 0],
  bass: [6, 3, 0, -1, -1],
  vocal: [-2, -1, 4, 3, 0],
  treble: [-2, -1, 0, 3, 6],
  loud: [5, 1, -2, 2, 5],
}

/** دسی‌بل → ضریبِ دامنه. هر ۶ دسی‌بل یعنی دو برابر. */
export function gainFromDb(db: number): number {
  return Math.pow(10, db / 20)
}

/** سقفِ تقویتِ سراسری (دسی‌بل) — بالاتر از این تقریباً همیشه کلیپ می‌شود */
export const MAX_BOOST_DB = 12

export interface EngineHandlers {
  onPlay: () => void
  onPlaying?: () => void
  onBuffering?: (buffering: boolean) => void
  onPause: () => void
  onTime: (seconds: number) => void
  onDuration: (seconds: number) => void
  onEnded: () => void
  onError: () => void
  /**
   * بازیابی جریان: آدرس تازه برای ترکِ جاری بخواهد — استور از
   * `streamUrlFor` + media token تازه می‌سازد. null یعنی «نمی‌توانم».
   */
  onRecoveryResolve?: () => Promise<string | null>
  /**
   * بازیابی ناکام ماند — استور شمارش خطاهای متوالی را نگه می‌دارد و بعد
   * از ۲ بار خودش به ترک بعدی می‌رود.
   */
  onRecoveryGiveUp?: () => void
  /**
   * کراس‌فید شروع شد و ترکِ بعدی روی دکِ دیگر افتاد.
   *
   * از این نسخه در *میانه* فید صدا زده می‌شود (handoff اندروید)، نه در شروعش.
   * صف باید همان‌جا جلو برود ولی *نباید* دوباره `load` صدا بزند — ترک از قبل
   * در حالِ پخش است. این تنها جایی است که موتور به صف دستور می‌دهد، نه برعکس.
   */
  onAdvance: () => void
}

interface DeckDsp {
  source: MediaElementAudioSourceNode
  /** زنجیرهٔ یکپارچهٔ DspChain معادل DspChain.kt اندروید */
  chain: AudioWorkletNode | null
  spatial: AudioWorkletNode | null
  eq: AudioWorkletNode | null
  loudness: AudioWorkletNode | null
}

interface Deck {
  el: HTMLAudioElement
  norm: GainNode | null
  fade: GainNode | null
  /** نودهای ورک‌لت/منبع این دک — بعد از بوتِ async گراف پر می‌شود */
  dsp: DeckDsp | null
  /**
   * گِینِ هم‌ترازیِ همین لحظه‌ی این دک — نه ترکِ بعدی. برای این است که اگر
   * تقویتِ سراسری وسطِ کراس‌فید عوض شد، دکی که دارد محو می‌شود هم همان‌قدر
   * تقویت را داشته باشد، نه فقط دکِ فعال.
   */
  gainDb: number
  /** شناسهٔ ترکِ روی این دک — کلیدِ گینِ هم‌ترازی در پردازندهٔ لودنس */
  mediaId: string | null
  /**
   * پرشِ معلق تا رسیدنِ متادیتا («ادامه از جایی که بودی»). نگه داشته می‌شود
   * تا بارگذاریِ بعدی بتواند لغوش کند — وگرنه اگر کاربر قبل از آمدنِ متادیتا
   * ترک را عوض کند، همان ثانیه روی ترکِ *تازه* می‌نشست و از وسط شروعش می‌کرد.
   */
  pendingSeek: (() => void) | null
}

interface LoadOptions {
  /** هم‌ترازیِ بلندی برای همین فایل (دسی‌بل) */
  gainDb?: number
  /** شناسهٔ ترک — کلیدِ گینِ لودنس؛ برای «ادامه از جایی که بودی» و کراس‌فید */
  trackId?: string
  /** ثانیه‌ای که باید از آنجا شروع شود — «ادامه از جایی که بودی» */
  at?: number
  autoplay?: boolean
}

let handlers: EngineHandlers | null = null
let ctx: AudioContext | null = null
/** فالبک Biquad — ۱۰ نود مطابق اسلات‌های چیدمان (شکل/frequency/Q هر اسلات) */
let eqSlotNodes: BiquadFilterNode[] = []
let master: GainNode | null = null
let limiter: DynamicsCompressorNode | null = null
/** فقط مسیر ورک‌لت: لیمیترِ لودنس جای DynamicsCompressor را می‌گیرد */
let workletPath = false
/**
 * تحلیلگرِ طیف — برای «هاله‌ی هم‌رhythm با صدا» در پخش‌کننده.
 *
 * روی گراف سِری می‌نشیند (master → analyser → destination) تا سیگنال را
 * دست‌نخورده رد کند و هم‌زمان انرژیِ فرکانس‌ها را ببیند؛ اگر موازی وصلش
 * می‌کردیم، صدا دو بار به مقصد می‌رسید.
 */
let analyser: AnalyserNode | null = null
let spectrum: Uint8Array<ArrayBuffer> | null = null
let decks: [Deck, Deck] | null = null
let activeIndex = 0
let statePublisher: EngineStatePublisher | null = null

let crossfadeSeconds = 0
let eqEnabled = false
/** تنظیمات اکولایزر ۷ بانده + پد تون + balance — API تازهٔ موتور */
let eqBands7: number[] = [0, 0, 0, 0, 0, 0, 0]
let eqTone: { x: number; y: number } = { x: 0, y: 0 }
let eqBalance = 0
let spatialOn = false
let normalizeOn = true
/**
 * تقویتِ سراسریِ گراف، به دسی‌بل.
 *
 * هم‌ترازیِ بلندی همه‌ی ترک‌ها را به یک هدف می‌برد، ولی «بلند شدن» نیست —
 * هدف منفی است و خیلی از مسترها از آن آرام‌ترند و تقویت نمی‌گیرند تا اوجشان
 * کلیپ نکند. این نود همان است که کاربر موقعِ «صدای این اپ کم است» می‌خواهد:
 * همه‌چیز را با هم بلند می‌کند، مستقل از گِینِ هر ترک.
 */
let boostDb = 0
let volume = 1
let muted = false

/** آدرس و هم‌ترازیِ ترکِ بعدی — بدون آن کراس‌فید چیزی برای رفتن ندارد */
let nextSource: { src: string; gainDb: number } | null = null

/**
 * هدررومِ جاریِ ترکیب (۱ بین ترنزیشن‌ها، کمی پایین‌تر حین فید).
 * پردازندهٔ لودنسِ فاز ۲ این را به‌عنوان trim هدف می‌گیرد.
 */
let blendHeadroomValue = 1

let currentSinkId = ''
let currentSinkLabel = ''
let currentTransitionPlan: TransitionPlan | null = null
let automixEnabled = true
let smartDjEnabled = true

/** ارسال یکپارچه پیام به زنجیره DSP (ورک‌لت واحد یا نودهای مجزا) */
function postDsp(deck: Deck | null, msg: unknown): void {
  if (!deck || !workletPath) return
  if (deck.dsp?.chain) {
    deck.dsp.chain.port.postMessage(msg)
    return
  }
  const m = msg as { type: string }
  if (m.type === 'eq') deck.dsp?.eq?.port.postMessage(msg)
  else if (m.type === 'spatial') deck.dsp?.spatial?.port.postMessage(msg)
  else if (['gain', 'track', 'normalize', 'trim', 'boundary', 'flush'].includes(m.type)) {
    deck.dsp?.loudness?.port.postMessage(msg)
  }
}

function active(): Deck | null {
  return decks ? decks[activeIndex] : null
}

function idle(): Deck | null {
  return decks ? decks[1 - activeIndex] : null
}

function deckByRef(ref: string): Deck | null {
  if (!decks) return null
  return ref === 'A' ? decks[0] : decks[1]
}

function refOfDeck(deck: Deck): string {
  return decks && deck === decks[0] ? 'A' : 'B'
}

/** مقایسهٔ منبع با نرمال‌سازی نسبی/مطلق — el.src همیشه مطلق است */
function sameSource(a: string | undefined | null, b: string | undefined | null): boolean {
  if (!a || !b) return false
  try {
    const base = globalThis.location?.href ?? 'http://localhost'
    return new URL(a, base).href === new URL(b, base).href
  } catch {
    return a === b
  }
}

/** آیا ترنزیشنی (ارم/فید) در جریان است — جایگزین پرچم `fading` قدیمی */
function isTransitioning(): boolean {
  return controller.getPhase() !== 'IDLE'
}

// ---------------------------------------------------------------------------
// کراس‌فید — قلاب‌های CrossfadeController
// ---------------------------------------------------------------------------

const crossfadeHooks: CrossfadeHooks<string> = {
  active(): CrossfadeActiveInfo<string> | null {
    const deck = active()
    if (!deck || !deck.el.src) return null
    const duration = deck.el.duration
    return {
      ref: refOfDeck(deck),
      positionMs: deck.el.currentTime * 1000,
      durationMs: Number.isFinite(duration) ? duration * 1000 : 0,
      isPlaying: !deck.el.paused,
    }
  },

  standby(): string | null {
    // بدونِ ترکِ بعدیِ نشسته روی دکِ ذخیره، فید چیزی برای بالا آوردن ندارد
    return nextSource !== null ? (decks ? (activeIndex === 0 ? 'B' : 'A') : null) : null
  },

  crossfadeSeconds(): number {
    return crossfadeSeconds
  },

  async startIncoming(incoming: string): Promise<void> {
    const deck = deckByRef(incoming)
    if (!deck || !nextSource) throw new Error('crossfade target vanished')
    const { src, gainDb } = nextSource
    nextSource = null

    cancelPendingSeek(deck)
    detachHls(deck.el)
    if (!sameSource(deck.el.src, src)) {
      // پربافرِ setNext معمولاً همین‌جا از قبل نشسته؛ فقط وقتی منبع فرق دارد می‌نشینیم
      deck.el.src = src
    }
    applyNormalize(deck, gainDb)
    if (deck.fade) deck.fade.gain.value = 0

    /*
     * هیچ‌چیز تا وقتی دکِ تازه واقعاً صدا ندهد تثبیت نمی‌شود. reject این
     * promise (autoplay policy، فایل رفته) یعنی هیچ اتفاقی نیفتاده: کنترلر
     * bail می‌کند، ترکِ فعلی دست‌نخورده تا آخر می‌رود و مسیرِ همیشگیِ `ended`
     * ترک بعدی را بالا می‌آورد — بدون کراس‌فید، ولی بدون سکوت.
     */
    await deck.el.play()
  },

  beginFadeCurve(seconds: number): void {
    const outgoing = active()
    const incoming = idle()
    if (!outgoing || !incoming) return

    const outMeta = outgoing.mediaId
      ? { id: outgoing.mediaId, durationMs: (outgoing.el.duration || 0) * 1000 }
      : null
    const inMeta = incoming.mediaId
      ? { id: incoming.mediaId, durationMs: (incoming.el.duration || 0) * 1000 }
      : null

    const plan = planTransition(outMeta, inMeta, seconds, {
      automix: automixEnabled,
      smartDj: smartDjEnabled,
    })
    currentTransitionPlan = plan

    if (plan.transitionStyle === 'DJ_BLEND' && plan.bassSwap) {
      // تعویض فرکانس بیس: در ابتدای ترنزیشن، بیس ترک ورودی بریده می‌شود تا با بیس ترک خروجی تداخل نکند
      postDsp(incoming, { type: 'transition_filter', lowPassHz: 20000, highPassHz: 180 })
      postDsp(outgoing, { type: 'transition_filter', lowPassHz: 20000, highPassHz: 20 })
    } else if (plan.transitionStyle === 'DJ_FILTER') {
      // فیلتر دی‌جی: بستن تدریجی فرکانس‌های بالا روی ترک خروجی
      postDsp(outgoing, { type: 'transition_filter', lowPassHz: 250, highPassHz: 20 })
      postDsp(incoming, { type: 'transition_filter', lowPassHz: 20000, highPassHz: 20 })
      if (plan.filterVariant === 'ECHO_RIDE') {
        postDsp(outgoing, { type: 'transition_echo', delaySeconds: 0.25, send: 0.5, dry: 0.5 })
      }
    }

    rampEqualPower(outgoing.fade, 'out', seconds)
    rampEqualPower(incoming.fade, 'in', seconds)
  },

  onHandoff(_outgoing: string, incomingRef: string): void {
    // تعویض نقش در میانهٔ فید — همان لحظه UI باید ترک تازه را نشان دهد
    const deck = deckByRef(incomingRef)
    activeIndex = 1 - activeIndex
    handlers?.onAdvance()
    if (deck && Number.isFinite(deck.el.duration)) handlers?.onDuration(deck.el.duration)
    statePublisher?.patch({
      currentTrackId: null,
      positionMs: 0,
      status: 'READY',
      isPlaying: true,
      isBuffering: false,
    })

    if (currentTransitionPlan?.transitionStyle === 'DJ_BLEND' && currentTransitionPlan.bassSwap) {
      // نقطه میانی فید: حالا بیس به ترک ورودی واگذار می‌شود و بیس خروجی قطع می‌شود
      const inDeck = active()
      const outDeck = idle()
      postDsp(inDeck, { type: 'transition_filter', lowPassHz: 20000, highPassHz: 20 })
      postDsp(outDeck, { type: 'transition_filter', lowPassHz: 20000, highPassHz: 180 })
    }
  },

  onBlendHeadroom(headroom: number): void {
    blendHeadroomValue = headroom
    // هدرروم به‌صورت trim به پردازندهٔ لودنسِ هر دو دک می‌رسد (گِلاید ۴۰ms
    // سمت پردازنده است — نوشتن هر ۳۰ms اینجا فقط target را عوض می‌کند)
    if (workletPath) {
      for (const deck of decks ?? []) {
        postDsp(deck, { type: 'trim', value: headroom })
      }
    }
  },

  onBail(outgoing: string | null, incoming: string | null): void {
    // پاک‌سازی دک‌هایی که *فعال نیستند*:
    //  - پایان موفق فید: دک خروجی idle شده → متوقف و آزاد
    //  - bail وسط فید: دک ورودی هنوز شروع‌نشده/نیمه‌کاره → متوقف و آزاد؛
    //    دک فعال (ترک جاری) دست‌نخورده می‌ماند
    currentTransitionPlan = null
    for (const ref of [outgoing, incoming]) {
      if (ref === null) continue
      const deck = deckByRef(ref)
      if (deck) {
        postDsp(deck, { type: 'transition_filter', lowPassHz: 20000, highPassHz: 20 })
        postDsp(deck, { type: 'transition_park_echo' })
      }
      if (!deck || deck === active()) continue
      deck.el.pause()
      detachHls(deck.el)
      deck.el.removeAttribute('src')
      deck.el.preload = 'metadata'
      if (deck.fade) deck.fade.gain.value = 1
      deck.el.volume = volume
      deck.el.muted = muted
    }
  },
}

const controller = new CrossfadeController(crossfadeHooks)

// ---------------------------------------------------------------------------
// بازیابی جریان (Stream Recovery) — تصمیم با StreamRecovery، اجرا این‌جا
// ---------------------------------------------------------------------------

const streamRecovery = new StreamRecovery()
let recoveryBusy = false

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

/** از `loadedmetadata` رد شدن و برگشتن به جایگاه — برای ادامهٔ پس از ریکاوری */
function resumeAt(el: HTMLAudioElement, seconds: number): void {
  if (!Number.isFinite(seconds) || seconds <= 0.5) return
  const seek = () => {
    try {
      el.currentTime = seconds
    } catch {
      // متادیتا هنوز آماده نیست یا seek نامعتبر — از ابتدا می‌شروع می‌شود
    }
  }
  if (el.readyState >= 1) seek()
  else el.addEventListener('loadedmetadata', seek, { once: true })
}

async function giveUp(): Promise<void> {
  handlers?.onError()
  handlers?.onRecoveryGiveUp?.()
}

/**
 * اجرای اقدامِ تصمیم‌گرفته‌شدهٔ بازیابی. همیشه روی دکِ *فعالِ لحظه* کار می‌کند
 * — اگر بین تصمیم و اجرا ترک عوض شود، کار رها می‌شود (خطای ترکِ قبلی به
 * ترکِ تازه نمی‌چسبد).
 */
async function runRecovery(kind: StreamErrorKind, el: HTMLAudioElement): Promise<void> {
  const src = el.currentSrc || el.src
  if (!src) return
  // خطای ناشناخته (غالباً abort ناشی از load تازه) و decode خراب را تلاش
  // دوباره نمی‌کنیم — هر دو یا بی‌ضررند یا بی‌فایده
  const action =
    kind === 'UNKNOWN' || kind === 'FATAL_DECODE'
      ? ({ kind: 'give-up' } as const)
      : streamRecovery.nextAction(kind, src)

  if (recoveryBusy) return
  recoveryBusy = true
  try {
    switch (action.kind) {
      case 'retry-same': {
        await delay(action.delayMs)
        if (el !== active()?.el) return
        const position = el.currentTime
        // ستِ مجددِ src، بارگذاری از نو را تضمین می‌کند (ست همان مقدار همیشه
        // reload نمی‌کند)
        el.removeAttribute('src')
        el.load()
        el.src = src
        resumeAt(el, position)
        await el.play().catch(() => {})
        return
      }
      case 'resolve-fresh': {
        const fresh = (await handlers?.onRecoveryResolve?.()) ?? null
        if (el !== active()?.el) return
        if (!fresh) {
          await giveUp()
          return
        }
        const position = el.currentTime
        detachHls(el)
        el.removeAttribute('src')
        el.load()
        el.src = fresh
        resumeAt(el, position)
        await el.play().catch(() => {})
        return
      }
      case 'hls-fallback': {
        if (el !== active()?.el) return
        const position = el.currentTime
        const ok = await attachHls(el, src, () => {
          // خطای fatal خودِ hls — دیگر تلاشی نمانده
          void giveUp()
        })
        if (!ok) {
          await giveUp()
          return
        }
        resumeAt(el, position)
        await el.play().catch(() => {})
        return
      }
      case 'give-up':
        await giveUp()
        return
    }
  } finally {
    recoveryBusy = false
  }
}

// ---------------------------------------------------------------------------
// Watchdog گیرِ بی‌خطا — پخش «زنده» است ولی currentTime جلو نمی‌رود
// ---------------------------------------------------------------------------

const WATCHDOG_STEP_MS = 1000
/** ۴ ثانیه بدون پیشرفت → BUFFERING (چرخان UI) */
const STALL_REPORT_MS = 4000
/** ۱۰ ثانیه بدون پیشرفت → خط لولهٔ بازیابی با فرضِ مشکل شبکه */
const STALL_RECOVER_MS = 10_000

let watchdogTimer: ReturnType<typeof setInterval> | null = null
let lastWatchPosition = -1
let stallSince: number | null = null

function startWatchdog(): void {
  if (watchdogTimer !== null || typeof window === 'undefined') return
  watchdogTimer = setInterval(() => {
    const deck = active()
    if (!deck || !deck.el.src || deck.el.paused || isTransitioning()) {
      stallSince = null
      return
    }
    const position = deck.el.currentTime
    if (position !== lastWatchPosition) {
      lastWatchPosition = position
      stallSince = null
      return
    }
    if (stallSince === null) {
      stallSince = Date.now()
      return
    }
    const stalledFor = Date.now() - stallSince
    if (stalledFor > STALL_RECOVER_MS && !recoveryBusy) {
      stallSince = null
      console.warn(`[audioEngine] stalled ${Math.round(STALL_RECOVER_MS / 1000)}s on active deck — recovery`)
      statePublisher?.patch({ status: 'BUFFERING', isBuffering: true })
      void runRecovery('NETWORK', deck.el)
    } else if (stalledFor > STALL_REPORT_MS) {
      statePublisher?.patch({ status: 'BUFFERING', isBuffering: true })
    }
  }, WATCHDOG_STEP_MS)
}

/**
 * گرافِ Web Audio. یک بار ساخته می‌شود و اگر مرورگر نداشته باشدش، null
 * می‌ماند و بقیه‌ی کد بدون آن کار می‌کند.
 */
let bootStarted = false
let workletModuleReady: Promise<boolean> | null = null

/**
 * بارگذاری ماژول ورک‌لت — یک‌بار، و نتیجه‌اش برای همیشه کش می‌شود.
 * شکستش (مرورگر قدیمی، CSP، offline) یعنی فالبک Biquad؛ صدا قطع نمی‌شود.
 */
function loadWorkletModule(context: AudioContext): Promise<boolean> {
  if (!workletModuleReady) {
    if (!context.audioWorklet) {
      workletModuleReady = Promise.resolve(false)
    } else {
      const url = new URL('./audio/dsp/worklets/dsp-worklet.js', import.meta.url)
      workletModuleReady = context.audioWorklet
        .addModule(url)
        .then(() => true)
        .catch((err: unknown) => {
          console.warn('[audioEngine] AudioWorklet unavailable — Biquad fallback:', err)
          return false
        })
    }
  }
  return workletModuleReady
}

/** دک بدون گراف — فقط المنت؛ گراف بعداً به آن سیم‌کشی می‌شود */
function makeDeck(): Deck {
  const el = new Audio()
  /*
   * لازمه‌ی گرافِ Web Audio وقتی صدا از مبدأ دیگری می‌آید (اپ اندروید، که
   * صفحه‌اش localhost است و سرور جای دیگر).
   *
   * `createMediaElementSource` روی یک المنتِ cross-origin بدونِ این، منبع را
   * «آلوده» می‌کند و خروجیِ گراف سکوتِ محض می‌شود — پخش ظاهراً جلو می‌رود ولی
   * هیچ صدایی نمی‌آید. در مرورگر که همه‌چیز هم‌مبدأ است، این خط بی‌اثر است.
   */
  el.crossOrigin = 'anonymous'
  el.preload = 'metadata'
  el.volume = volume
  el.muted = muted

  if (currentSinkId && 'setSinkId' in el && typeof (el as any).setSinkId === 'function') {
    void (el as any).setSinkId(currentSinkId).catch(() => {})
  }

  return { el, norm: null, fade: null, dsp: null, gainDb: 0, mediaId: null, pendingSeek: null }
}

/**
 * بوتِ گراف — async چون ابتدا باید معلوم شود AudioWorklet هست یا نه.
 *
 * تا وقتی بوت تمام نشده، دک‌ها مستقیم از `<audio>` صدا می‌دهند (بدون EQ و
 * هم‌ترازی) و همهٔ تنظیماتی که تا این لحظه ست شده‌اند، بعد از اتصال دوباره
 * اعمال می‌شوند. `createMediaElementSource` یک‌بار به‌ازای هر المنت جواب
 * می‌دهد، پس تصمیمِ مسیر (ورک‌لت/فالبک) باید قبل از اتصال گرفته شود —
 * برای همین بوت یک‌باره است و هرگز عقب‌گرد ندارد.
 */
function bootGraph(): void {
  if (bootStarted || typeof window === 'undefined') return
  bootStarted = true

  const Ctor = window.AudioContext ?? (window as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
  if (!Ctor) return

  const savedSink = getSavedSinkId()
  if (savedSink) currentSinkId = savedSink

  void (async () => {
    try {
      ctx = new Ctor({ latencyHint: 'playback' } as AudioContextOptions)
    } catch {
      try {
        ctx = new Ctor()
      } catch {
        ctx = null
        return
      }
    }

    if (currentSinkId && ctx) {
      void routeAudioContext(ctx, currentSinkId)
    }

    try {
      const useWorklet = await loadWorkletModule(ctx)
      workletPath = useWorklet

      master = ctx.createGain()
      // تقویت سراسری (boost) روی نود مستر — مشترک بین دو دک، مثل اپ اندروید
      master.gain.value = gainFromDb(boostDb)

      if (!useWorklet) {
        // فالبک: ۱۰ نود Biquad با همان چیدمان اسلات‌ها (شکل/فرکانس/Q) —
        // پاسخ بزرگی نزدیک به SVF، بدون هیچ ورک‌لتی
        eqSlotNodes = EQ_SLOTS.map((slot) => {
          const filter = ctx!.createBiquadFilter()
          filter.type =
            slot.kind === 'BELL' ? 'peaking' : slot.kind === 'LOW_SHELF' ? 'lowshelf' : 'highshelf'
          filter.frequency.value = slot.frequencyHz
          filter.Q.value = 0.707
          filter.gain.value = 0
          return filter
        })
        eqSlotNodes.reduce((prev, node) => {
          prev.connect(node)
          return node
        })
        eqSlotNodes[eqSlotNodes.length - 1].connect(master)
        // لیمیتر شفاف با زانوی نرم فقط در فالبک — در مسیر ورک‌لت، لیمیترِ
        // پردازندهٔ لودنس (سقف ۰٫۹۸۵) همین نقش را با دقت بیشتر انجام می‌دهد
        try {
          limiter = ctx.createDynamicsCompressor()
          limiter.threshold.value = -0.5
          limiter.knee.value = 12
          limiter.ratio.value = 3
          limiter.attack.value = 0.01
          limiter.release.value = 0.25
          master.connect(limiter)
        } catch {
          limiter = null
        }
      }

      analyser = ctx.createAnalyser()
      analyser.fftSize = 256
      analyser.smoothingTimeConstant = 0.82
      spectrum = new Uint8Array(analyser.frequencyBinCount)

      const outputNode: AudioNode = limiter ?? master
      // outputNode → analyser → destination: طیف را می‌خواند و سیگنال را رد می‌کند
      outputNode.connect(analyser)
      analyser.connect(ctx.destination)

      for (const deck of decks ?? []) connectDeck(deck, useWorklet)

      // تنظیماتی که قبل از بوت ست شده‌اند — الان به نودها می‌رسند
      applyEq()
      decks?.forEach((deck) => applyNormalize(deck, deck.gainDb))
    } catch (err) {
      console.warn('[audioEngine] graph boot failed — plain <audio> playback:', err)
      ctx = null
      master = null
      limiter = null
      eqSlotNodes = []
      analyser = null
      spectrum = null
    }
  })()
}

function connectDeck(deck: Deck, useWorklet: boolean): void {
  if (!ctx || !master) return
  let source: MediaElementAudioSourceNode
  try {
    source = ctx.createMediaElementSource(deck.el)
  } catch {
    // createMediaElementSource فقط یک بار به‌ازای هر المنت جواب می‌دهد؛
    // شکستش یعنی این دک بدون گراف کار می‌کند، نه اینکه پخش نشود
    deck.norm = null
    deck.fade = null
    deck.dsp = null
    return
  }

  const norm = ctx.createGain()
  const fade = ctx.createGain()
  deck.norm = norm
  deck.fade = fade

  if (!useWorklet) {
    deck.dsp = { source, chain: null, spatial: null, eq: null, loudness: null }
    source.connect(norm)
    norm.connect(fade)
    fade.connect(eqSlotNodes[0])
    return
  }

  // مسیر ورک‌لت — زنجیره واحد mb-dsp-chain مطابق DspChain.kt اندروید:
  //   Spatial → EQ → TransitionFilter → Loudness → fade → master
  const workletOptions: AudioWorkletNodeOptions = {
    numberOfInputs: 1,
    numberOfOutputs: 1,
    outputChannelCount: [2],
    channelCount: 2,
    channelCountMode: 'explicit',
    channelInterpretation: 'speakers',
  }

  let chain: AudioWorkletNode | null = null
  try {
    chain = new AudioWorkletNode(ctx, 'mb-dsp-chain', workletOptions)
  } catch {
    chain = null
  }

  if (chain) {
    deck.dsp = { source, chain, spatial: null, eq: null, loudness: null }
    source.connect(norm)
    norm.connect(chain)
    chain.connect(fade)
    fade.connect(master)
    return
  }

  // فالبک به نودهای سه‌گانه در صورت در دسترس نبودن زنجیرهٔ واحد
  let spatial: AudioWorkletNode | null = null
  let eq: AudioWorkletNode | null = null
  let loudness: AudioWorkletNode | null = null
  try {
    spatial = new AudioWorkletNode(ctx, 'mb-spatial', workletOptions)
  } catch {
    spatial = null
  }
  try {
    eq = new AudioWorkletNode(ctx, 'mb-equalizer', workletOptions)
  } catch {
    eq = null
  }
  try {
    loudness = new AudioWorkletNode(ctx, 'mb-loudness', workletOptions)
  } catch {
    loudness = null
  }

  if (spatial && eq && loudness) {
    deck.dsp = { source, chain: null, spatial, eq, loudness }
    source.connect(norm)
    norm.connect(spatial)
    spatial.connect(eq)
    eq.connect(fade)
    fade.connect(loudness)
    loudness.connect(master)
  } else {
    // ورک‌لت ناقص ساخت — گراف ساده ولی زنده؛ صدا هرگز قطع نمی‌شود
    deck.dsp = { source, chain: null, spatial: null, eq: null, loudness: null }
    source.connect(norm)
    norm.connect(fade)
    fade.connect(master)
  }
}

function attach(deck: Deck): void {
  const { el } = deck
  el.addEventListener('play', () => {
    if (el === active()?.el) {
      statePublisher?.patch({ status: 'READY', isPlaying: true })
      handlers?.onPlay()
    }
  })
  el.addEventListener('playing', () => {
    if (el === active()?.el) {
      // پخش واقعاً وصل شد — بودجه‌های بازیابی از نو
      streamRecovery.markRecovered()
      statePublisher?.patch({ status: 'READY', isPlaying: true, isBuffering: false })
      handlers?.onBuffering?.(false)
      handlers?.onPlaying?.()
    }
  })
  el.addEventListener('waiting', () => {
    if (el === active()?.el) {
      statePublisher?.patch({ status: 'BUFFERING', isBuffering: true })
      handlers?.onBuffering?.(true)
    }
  })
  el.addEventListener('stalled', () => {
    if (el === active()?.el) {
      statePublisher?.patch({ status: 'BUFFERING', isBuffering: true })
      handlers?.onBuffering?.(true)
    }
  })
  el.addEventListener('canplay', () => {
    if (el === active()?.el) {
      statePublisher?.patch({ isBuffering: false, status: 'READY' })
      handlers?.onBuffering?.(false)
    }
  })
  el.addEventListener('pause', () => {
    // مکثِ دکِ در حالِ محو شدن، «مکث» نیست — کاربر چیزی را متوقف نکرده
    if (el === active()?.el && !isTransitioning()) {
      statePublisher?.patch({ isPlaying: false })
      handlers?.onBuffering?.(false)
      handlers?.onPause()
    }
  })
  el.addEventListener('timeupdate', () => {
    if (el !== active()?.el) return
    handlers?.onTime(el.currentTime)
    // ارم می‌تواند از همین رویداد هم جلو بیفتد، نه فقط تیک ۲۵۰ms کنترلر
    controller.poll()
  })
  el.addEventListener('durationchange', () => {
    if (el === active()?.el && Number.isFinite(el.duration)) handlers?.onDuration(el.duration)
  })
  el.addEventListener('ended', () => {
    // پایانِ دکی که کراس‌فید جایش را گرفته بی‌معنی است — صف از قبل جلو رفته
    if (el !== active()?.el) return

    statePublisher?.patch({ status: 'ENDED', isPlaying: false })

    // اگر کراس‌فید فعال نیست و دکِ غیرفعال از قبل با منبع بعدی پرلود شده است، سوییچ بدون‌وقفه انجام می‌دهیم
    if (
      controller.getPhase() === 'IDLE' &&
      crossfadeSeconds < MIN_CROSSFADE_SECONDS &&
      nextSource
    ) {
      const incoming = idle()
      if (incoming && sameSource(incoming.el.src, nextSource.src)) {
        const outgoing = active()
        nextSource = null

        void incoming.el
          .play()
          .then(() => {
            activeIndex = 1 - activeIndex
            if (outgoing) {
              outgoing.el.pause()
              detachHls(outgoing.el)
              outgoing.el.removeAttribute('src')
              outgoing.el.preload = 'metadata'
              if (outgoing.fade) outgoing.fade.gain.value = 1
            }
            handlers?.onAdvance()
            statePublisher?.patch({ status: 'READY', isPlaying: true, positionMs: 0 })
            if (Number.isFinite(incoming.el.duration)) handlers?.onDuration(incoming.el.duration)
          })
          .catch((err) => {
            console.warn('[audioEngine] gapless swap play rejected, falling back to onEnded:', err)
            incoming.el.pause()
            detachHls(incoming.el)
            incoming.el.removeAttribute('src')
            incoming.el.preload = 'metadata'
            handlers?.onEnded()
          })
        return
      }
    }

    handlers?.onEnded()
  })
  el.addEventListener('error', () => {
    if (el === active()?.el) {
      const err = el.error
      console.warn(`[audioEngine] playback error (code: ${err?.code}, msg: ${err?.message}) for src: ${el.src}`)
      statePublisher?.patch({
        status: 'ERROR',
        isPlaying: false,
        errorMessage: err?.message ?? 'media error',
      })
      // خط لولهٔ بازیابی: retry → resolve تازه از استور → hls.js → تسلیم.
      // hls.js دیگر hook جداگانه نیست؛ یکی از پله‌های همین خط لوله است.
      void runRecovery(classifyMediaError(err), el)
    }
  })
}

function ensure(): Deck {
  if (!decks) {
    decks = [makeDeck(), makeDeck()]
    decks.forEach(attach)
    statePublisher = new EngineStatePublisher(
      () => Math.round((active()?.el.currentTime ?? 0) * 1000),
      () => {
        const value = active()?.el.duration ?? 0
        return Number.isFinite(value) ? Math.round(value * 1000) : 0
      },
    )
    controller.start()
    startWatchdog()

    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible' && ctx?.state === 'suspended') {
          const d = active()
          if (d && !d.el.paused) void ctx.resume().catch(() => {})
        }
      })
    }
  }
  bootGraph()
  return decks[activeIndex]
}

/** منحنی ترکیبی: ۷ باند دستی + پد تون، با preamp محاسبه‌شده */
function combinedEqCurve(): EqCurve {
  return combineCurves(manualCurve(eqBands7), toneCurve(eqTone.x, eqTone.y, false))
}

function applyEq(): void {
  const curve = eqEnabled ? combinedEqCurve() : flatCurve()
  if (workletPath) {
    for (const deck of decks ?? []) {
      postDsp(deck, {
        type: 'eq',
        curve: { gainsDb: Array.from(curve.gainsDb), qs: Array.from(curve.qs), preampDb: curve.preampDb },
        balance: eqBalance,
      })
    }
    return
  }
  // فالبک Biquad — همان منحنی روی نودهای هم‌اسلات
  eqSlotNodes.forEach((node, i) => {
    node.gain.value = curve.gainsDb[i] ?? 0
    node.Q.value = curve.qs[i] ?? 0.707
  })
}

/**
 * نگاشتِ گذرا: پری‌ست قدیمی ۵ بانده (۶۰/۲۳۰/۹۱۰/۳۶۰۰/۱۴۰۰۰) به نزدیک‌ترین
 * باندهای چیدمان ۷تایی (۶۰/۱۵۰/۴۰۰/۱۰۰۰/۲۵۰۰/۶۰۰۰/۱۴۰۰۰). فاز ۴ این را
 * حذف می‌کند وقتی استور مستقیم باندهای ۷تایی می‌فرستد.
 */
const LEGACY_BAND_TO_MANUAL = [0, 1, 3, 4, 6]
function legacyPresetToBands7(values: readonly number[]): number[] {
  const bands = [0, 0, 0, 0, 0, 0, 0]
  values.forEach((value, i) => {
    const idx = LEGACY_BAND_TO_MANUAL[i]
    if (idx !== undefined) bands[idx] = value
  })
  return bands
}

/** پیام ترک جاری + گینش به پردازندهٔ لودنسِ یک دک */
function pushTrackMessage(deck: Deck): void {
  if (!workletPath || deck.mediaId === null) return
  const gain = normalizeOn ? gainFromDb(deck.gainDb) : 1
  postDsp(deck, { type: 'gain', mediaId: deck.mediaId, gain })
  postDsp(deck, { type: 'track', mediaId: deck.mediaId })
}

function pushNormalize(): void {
  if (!workletPath) return
  for (const deck of decks ?? []) {
    postDsp(deck, { type: 'normalize', on: normalizeOn })
  }
}

function pushSpatial(): void {
  if (!workletPath) return
  for (const deck of decks ?? []) {
    postDsp(deck, { type: 'spatial', enabled: spatialOn })
  }
}

function applyNormalize(deck: Deck | null, gainDb: number, smooth = true): void {
  if (!deck) return
  deck.gainDb = gainDb

  // مسیر ورک‌لت: گین per-track به پردازندهٔ لودنس می‌رود و نودِ norm فقط
  // شنوندهٔ گراف است (boost هم روی مستر است) — دو جای اعمال یعنی دو برابرِ گین
  if (workletPath) {
    pushTrackMessage(deck)
    return
  }

  if (!deck.norm) return
  const norm = normalizeOn ? gainFromDb(gainDb) : 1
  const target = norm * gainFromDb(boostDb)

  if (smooth && ctx && ctx.state === 'running') {
    // رمپ نرم ۴۰ میلی‌ثانیه‌ای برای جلوگیری از صدای تقه (click/pop) حین تغییر گِین
    try {
      const now = ctx.currentTime
      deck.norm.gain.cancelScheduledValues(now)
      deck.norm.gain.setValueAtTime(deck.norm.gain.value, now)
      deck.norm.gain.linearRampToValueAtTime(target, now + 0.04)
      return
    } catch {
      // فالبک در صورت عدم پشتیبانی مرورگر
    }
  }
  deck.norm.gain.value = target
}

/** پرشِ معلقِ یک دک را باطل می‌کند — قبل از هر بارگذاریِ تازه روی همان دک */
function cancelPendingSeek(deck: Deck): void {
  if (!deck.pendingSeek) return
  deck.el.removeEventListener('loadedmetadata', deck.pendingSeek)
  deck.pendingSeek = null
}

const EQUAL_POWER_STEPS = 64

/**
 * منحنی تضعیف لگاریتمی توان-برابر (Equal-Power Fade Out).
 * رابطه: cos(pi/2 * t)
 */
export function makeEqualPowerFadeOutCurve(steps = EQUAL_POWER_STEPS): Float32Array {
  const curve = new Float32Array(steps)
  for (let i = 0; i < steps; i++) {
    const t = i / (steps - 1)
    curve[i] = Math.cos(t * 0.5 * Math.PI)
  }
  return curve
}

/**
 * منحنی تقویت لگاریتمی توان-برابر (Equal-Power Fade In).
 * رابطه: sin(pi/2 * t)
 */
export function makeEqualPowerFadeInCurve(steps = EQUAL_POWER_STEPS): Float32Array {
  const curve = new Float32Array(steps)
  for (let i = 0; i < steps; i++) {
    const t = i / (steps - 1)
    curve[i] = Math.sin(t * 0.5 * Math.PI)
  }
  return curve
}

const EQUAL_POWER_FADE_OUT = makeEqualPowerFadeOutCurve()
const EQUAL_POWER_FADE_IN = makeEqualPowerFadeInCurve()

/** رمپِ توان-برابر برای کراس‌فید بدون افت بلندی در نقطه تقاطع */
function rampEqualPower(node: GainNode | null, type: 'in' | 'out', seconds: number): void {
  if (!node || !ctx) return
  const now = ctx.currentTime
  const curve = type === 'out' ? EQUAL_POWER_FADE_OUT : EQUAL_POWER_FADE_IN
  try {
    node.gain.cancelScheduledValues(now)
    node.gain.setValueCurveAtTime(curve, now, seconds)
  } catch {
    // فالبک به رمپ خطی در صورت عدم پشتیبانی کامل
    node.gain.cancelScheduledValues(now)
    node.gain.setValueAtTime(node.gain.value, now)
    node.gain.linearRampToValueAtTime(type === 'out' ? 0 : 1, now + seconds)
  }
}

export const engine = {
  init(next: EngineHandlers): void {
    handlers = next
  },

  /**
   * آماده‌سازی پیش‌دستانه‌ی گراف صوتی و دیکد ورک‌لت پیش از اولین کلیک پلی.
   */
  prewarm(): void {
    if (typeof window === 'undefined') return
    ensure()
    if (ctx && ctx.state === 'suspended') {
      void ctx.resume().catch(() => {})
    }
  },

  /** المنتِ دکِ فعال — برای ثبت در audioFocus و تست */
  element(): HTMLAudioElement {
    return ensure().el
  },

  hasSource(): boolean {
    return Boolean(active()?.el.src)
  },

  currentTime(): number {
    return active()?.el.currentTime ?? 0
  },

  duration(): number {
    const value = active()?.el.duration ?? 0
    return Number.isFinite(value) ? value : 0
  },

  paused(): boolean {
    return active()?.el.paused ?? true
  },

  /** اسنپ‌شات رسمی وضعیت موتور — پورت AudioState.kt */
  audioState(): ReturnType<EngineStatePublisher['snapshot']> | null {
    return statePublisher?.snapshot() ?? null
  },

  /**
   * هدررومِ جاریِ ترکیب — ۱ بین ترنزیشن‌ها، کمتر حین فید.
   * پردازندهٔ لودنس (فاز ۲) این را به‌عنوان trim هدف می‌گیرد.
   */
  blendHeadroom(): number {
    return blendHeadroomValue
  },

  load(src: string, { gainDb = 0, trackId, at = 0, autoplay = true }: LoadOptions = {}): void {
    const deck = ensure()

    // یک بارگذاریِ صریح، هر ترنزیشن در جریان را bail می‌کند؛ onBail دک‌های
    // غیرفعال را تمیز می‌کند و دک فعال (همین که می‌خواهیم لود کنیم) دست‌نخورده می‌ماند
    controller.notifyInterruption()
    streamRecovery.reset()
    if (deck.fade) deck.fade.gain.value = 1

    const other = idle()
    // سوئیچ سریع بدون‌وقفه (Fast Gapless Swap): اگر دک آماده از قبل همین منبع را بافر کرده است
    if (other && sameSource(other.el.src, src) && at === 0) {
      const outgoing = deck
      activeIndex = 1 - activeIndex
      const incoming = other
      incoming.mediaId = trackId ?? null
      applyNormalize(incoming, gainDb)
      cancelPendingSeek(incoming)
      if (incoming.fade) incoming.fade.gain.value = 1

      // توقف و آزادسازی دک خروجی تا برای ترک بعدیِ صف آماده باشد
      if (outgoing) {
        outgoing.el.pause()
        detachHls(outgoing.el)
        outgoing.el.removeAttribute('src')
        outgoing.el.preload = 'metadata'
        outgoing.mediaId = null
        if (outgoing.fade) outgoing.fade.gain.value = 1
      }

      statePublisher?.patch({
        status: incoming.el.readyState >= 2 ? 'READY' : 'BUFFERING',
        isBuffering: incoming.el.readyState < 2 && autoplay,
        isPlaying: false,
        errorMessage: null,
      })

      if (autoplay) this.play()
      handlers?.onAdvance?.()
      return
    }

    // اگر دکِ غیرفعال قبلاً با همین منبع پرلود شده بود، پاک شود تا تکرار/اکو نشود
    if (other && (sameSource(other.el.src, src) || !sameSource(nextSource?.src, other.el.src))) {
      other.el.pause()
      detachHls(other.el)
      other.el.removeAttribute('src')
      other.el.preload = 'metadata'
      other.mediaId = null
    }

    deck.mediaId = trackId ?? null
    applyNormalize(deck, gainDb)
    cancelPendingSeek(deck)
    detachHls(deck.el) // منبع تازه native-first شروع می‌شود (فاز ۱۵)
    deck.el.src = src
    statePublisher?.patch({
      status: 'BUFFERING',
      isBuffering: autoplay,
      isPlaying: false,
      errorMessage: null,
    })
    if (at > 0) {
      // قبل از رسیدن متادیتا، currentTime بی‌اثر است
      const seek = () => {
        deck.pendingSeek = null
        deck.el.currentTime = at
      }
      deck.pendingSeek = seek
      deck.el.addEventListener('loadedmetadata', seek, { once: true })
    }
    if (autoplay) this.play()
  },

  play(): void {
    const deck = ensure()
    // مرورگر تا اولین تعاملِ کاربر گراف را معلق نگه می‌دارد؛ بدون این،
    // صدا اصلاً از گراف بیرون نمی‌آید
    if (ctx?.state === 'suspended') void ctx.resume()
    void deck.el.play().catch((err: unknown) => {
      // پرشِ سریع به ترکِ بعدی، `play()`ِ قبلی را با AbortError رد می‌کند —
      // این شکست نیست، پخشِ تازه دارد شروع می‌شود
      if (err instanceof DOMException && err.name === 'AbortError') return
      console.warn('[audioEngine] deck.el.play() rejected:', err)
      handlers?.onError()
    })
  },

  pause(): void {
    decks?.forEach((deck) => deck.el.pause())
  },

  seek(seconds: number): void {
    // seek هر ترنزیشن در جریان را bail می‌کند — همان DISCONTINUITY_REASON_SEEK اندروید
    controller.notifyInterruption()
    const deck = active()
    if (deck?.el.src) deck.el.currentTime = seconds
  },

  setVolume(value: number): void {
    volume = value
    decks?.forEach((deck) => (deck.el.volume = value))
  },

  setMuted(value: boolean): void {
    muted = value
    decks?.forEach((deck) => (deck.el.muted = value))
  },

  /** ترکی که کراس‌فید یا سوییچ بدون‌وقفه باید به آن برود؛ null یعنی ترکی نیست */
  setNext(src: string | null, gainDb = 0, trackId?: string): void {
    nextSource = src ? { src, gainDb } : null
    if (!decks) return
    if (!src) {
      // صف عوض شده: هر ارم/فید منتظری دیگر مقصد ندارد
      controller.notifyInterruption()
      const other = idle()
      if (other) {
        other.el.pause()
        detachHls(other.el)
        other.el.removeAttribute('src')
        other.el.preload = 'metadata'
        other.mediaId = null
      }
      return
    }
    if (isTransitioning()) return

    const other = idle()
    if (!other) return

    // اگر منبع با دکِ فعال و دکِ غیرفعال متفاوت است، دکِ آماده را از قبل بافر می‌کنیم (Spotify-like pre-buffering)
    if (!sameSource(other.el.src, src) && !sameSource(active()?.el.src, src)) {
      cancelPendingSeek(other)
      detachHls(other.el)
      other.el.preload = 'auto'
      other.el.src = src
      other.mediaId = trackId ?? null
      applyNormalize(other, gainDb)
      if (other.fade) other.fade.gain.value = 1
    }
  },

  setCrossfade(seconds: number): void {
    crossfadeSeconds = Math.max(0, seconds)
    // کوتاه‌شدنِ فید زیر حداقل، ترنزیشن منتظری را بی‌معنا می‌کند
    if (crossfadeSeconds < MIN_CROSSFADE_SECONDS) controller.notifyInterruption()
  },

  /** فعال/غیرفعال کردن میکس خودکار زمان‌بندی (Automix) */
  setAutomix(on: boolean): void {
    automixEnabled = on
  },

  /** فعال/غیرفعال کردن ترنزیشن‌های دی‌جی (سوئیپ فیلتر LPF و تعویض ساب‌بیس) */
  setSmartDj(on: boolean): void {
    smartDjEnabled = on
  },

  /**
   * API قدیمی پری‌ست ۵ بانده — تا مهاجرتِ استور تنظیمات (فاز ۴) حفظ شده.
   * باندهای قدیمی (۶۰/۲۳۰/۹۱۰/۳۶۰۰/۱۴۰۰۰) به نزدیک‌ترین باندهای چیدمان
   * ۷تایی تخت می‌شوند؛ بعد از فاز ۴ همه‌چیز مستقیم باندهای ۷تایی می‌فرستد.
   */
  setEq(preset: EqPreset): void {
    eqBands7 = legacyPresetToBands7(EQ_PRESETS[preset] ?? EQ_PRESETS.off)
    applyEq()
  },

  setEqEnabled(on: boolean): void {
    eqEnabled = on
    applyEq()
  },

  /**
   * API تازه — اکولایزر دقیق اندروید: ۷ باند دستی + پد تون + balance.
   * روی مسیر ورک‌لت همان SVF ده‌اسلاتی می‌شود؛ روی فالبک Biquad هم‌اسلات.
   */
  setEq7(params: { bandsDb: number[]; tone?: { x: number; y: number }; balance?: number }, enabled: boolean): void {
    eqBands7 = params.bandsDb.slice(0, 7)
    if (params.tone) eqTone = { ...params.tone }
    if (params.balance !== undefined) eqBalance = Math.max(-1, Math.min(1, params.balance))
    eqEnabled = enabled
    applyEq()
  },

  /** فضاسازی روی وب — پورت SpatialAudioProcessor (تا حالا فقط به نیتیو می‌رفت) */
  setSpatialAudio(on: boolean): void {
    spatialOn = on
    pushSpatial()
  },

  setNormalize(on: boolean): void {
    normalizeOn = on
    pushNormalize()
    decks?.forEach((deck) => applyNormalize(deck, deck.gainDb))
  },

  /**
   * تقویتِ سراسریِ گراف به دسی‌بل. وسطِ پخش هم اثر می‌کند: در مسیر ورک‌لت روی
   * نود مستر (مشترک بین دو دک) و در فالبک روی نودِ هم‌ترازیِ هر دک.
   */
  setBoost(db: number): void {
    boostDb = Math.max(0, Math.min(MAX_BOOST_DB, db))
    if (workletPath && ctx && master) {
      try {
        const now = ctx.currentTime
        master.gain.cancelScheduledValues(now)
        master.gain.setValueAtTime(master.gain.value, now)
        master.gain.linearRampToValueAtTime(gainFromDb(boostDb), now + 0.04)
        return
      } catch {
        // فالبک
      }
      master.gain.value = gainFromDb(boostDb)
      return
    }
    decks?.forEach((deck) => applyNormalize(deck, deck.gainDb))
  },

  /** آیا گرافِ صوتی واقعاً بالا آمد — بدونش هم‌ترازی و EQ کاری نمی‌کنند */
  graphReady(): boolean {
    return Boolean(active()?.norm)
  },

  /**
   * انرژیِ بمِ لحظه در بازه‌ی [۰،۱] — برای رقصاندنِ هاله‌ی پشتِ کاور با بیت.
   *
   * فقط چند باندِ اولِ طیف را می‌گیرد (بم و کیک) چون همان‌ها ضرب را می‌سازند؛
   * کلِ طیف میانگین می‌شود و به «بلندی» تبدیل می‌شد نه «ریتم». بدونِ گراف
   * (مرورگرِ قدیمی، یا شکستِ Web Audio) صفر برمی‌گرداند و مصرف‌کننده هاله را
   * ساکن می‌گذارد — نه پرش، نه خطا.
   */
  bassLevel(): number {
    if (!analyser || !spectrum) return 0
    analyser.getByteFrequencyData(spectrum)
    // ~۸ باندِ اول روی ۴۴.۱kHz با fftSize=256 یعنی تا حدود ۶۵۰Hz — بمِ خالص
    const bins = 8
    let sum = 0
    for (let i = 0; i < bins; i++) sum += spectrum[i]
    return sum / (bins * 255)
  },

  /**
   * داده‌های خام طیف فرکانسی برای ویژوالایزر زنده.
   */
  getFrequencyData(out?: Uint8Array): Uint8Array | null {
    if (!analyser || !spectrum) return null
    analyser.getByteFrequencyData(spectrum)
    if (out) {
      out.set(spectrum.subarray(0, Math.min(out.length, spectrum.length)))
      return out
    }
    return spectrum
  },

  stop(): void {
    controller.notifyInterruption()
    nextSource = null
    blendHeadroomValue = 1
    TransitionLock.isCrossfadeActive = false
    decks?.forEach((deck) => {
      cancelPendingSeek(deck)
      deck.el.pause()
      detachHls(deck.el)
      deck.el.removeAttribute('src')
      deck.mediaId = null
      postDsp(deck, { type: 'flush' })
      if (deck.fade) deck.fade.gain.value = 1
    })
    statePublisher?.patch({ status: 'IDLE', isPlaying: false, isBuffering: false, errorMessage: null })
  },

  /** گزارش جامع وضعیت خط پردازش صوتی وب برای AudioPipelineModal */
  getDiagnostics(): AudioDiagnostics {
    const isBitPerfect = !eqEnabled && !spatialOn && !normalizeOn && boostDb === 0
    const devLabel = currentSinkLabel || 'بلندگو / خروجی پیش‌فرض مرورگر'
    const isUsb = /usb|dac|fiio|schiit|topping|audioengine|chord|dragonfly/i.test(devLabel)

    return {
      sink: currentSinkId ? `Direct Hardware Sink (${currentSinkId.slice(0, 8)}...)` : 'WebAudio Destination',
      deviceName: devLabel,
      routeKind: isUsb ? 'USB_DAC' : currentSinkId ? 'EXTERNAL_SINK' : 'SYSTEM_DEFAULT',
      actualEncoding: 32,
      actualSampleRateHz: ctx?.sampleRate ?? 44100,
      systemMixerRateHz: ctx?.sampleRate ?? 44100,
      decoderName: 'HTML5 MediaElement + WebAudio',
      decoderOutputEncoding: 'Float32 PCM',
      dspFormat: workletPath ? 'AudioWorklet (Float32 Single-Pass DspChain)' : 'Web Audio Biquad Fallback',
      dspAvailable: workletPath,
      directPlaybackSupported: isSetSinkIdSupported(),
      directPlaybackActual: Boolean(currentSinkId),
      outputExact: isBitPerfect,
      outputExactDetail: isBitPerfect
        ? 'Bit-Perfect Direct Float32'
        : workletPath
          ? 'DSP Chain Active (Float32)'
          : 'Biquad Fallback Active',
      loudnessGainDb: active()?.gainDb ?? 0,
      loudnessLufs: -14.0,
      usbProductName: isUsb ? devLabel : null,
    }
  },

  /** تغییر سخت‌افزار یا دستگاه خروجی صدا (مانند DAC یواس‌بی) */
  async setOutputDevice(deviceId: string, label?: string): Promise<boolean> {
    currentSinkId = deviceId
    currentSinkLabel = label ?? ''
    saveSinkId(deviceId)
    const elements = decks ? [decks[0].el, decks[1].el] : []
    const elSuccess = await routeAudioElements(elements, deviceId)
    const ctxSuccess = await routeAudioContext(ctx, deviceId)
    return elSuccess || ctxSuccess
  },

  getCurrentOutputDevice(): { deviceId: string; label: string } {
    return { deviceId: currentSinkId, label: currentSinkLabel }
  },

  getAudioContext(): AudioContext | null {
    return ctx
  },
}
