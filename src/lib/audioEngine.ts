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

import { detachHls, maybeHlsFallback } from './hlsPlayback'
import { EngineStatePublisher } from './audio/AudioState'
import {
  CrossfadeController,
  MIN_CROSSFADE_SECONDS,
  TransitionLock,
  type CrossfadeActiveInfo,
  type CrossfadeHooks,
} from './audio/CrossfadeController'

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
   * کراس‌فید شروع شد و ترکِ بعدی روی دکِ دیگر افتاد.
   *
   * از این نسخه در *میانه* فید صدا زده می‌شود (handoff اندروید)، نه در شروعش.
   * صف باید همان‌جا جلو برود ولی *نباید* دوباره `load` صدا بزند — ترک از قبل
   * در حالِ پخش است. این تنها جایی است که موتور به صف دستور می‌دهد، نه برعکس.
   */
  onAdvance: () => void
}

interface Deck {
  el: HTMLAudioElement
  norm: GainNode | null
  fade: GainNode | null
  /**
   * گِینِ هم‌ترازیِ همین لحظه‌ی این دک — نه ترکِ بعدی. برای این است که اگر
   * تقویتِ سراسری وسطِ کراس‌فید عوض شد، دکی که دارد محو می‌شود هم همان‌قدر
   * تقویت را داشته باشد، نه فقط دکِ فعال.
   */
  gainDb: number
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
  /** ثانیه‌ای که باید از آنجا شروع شود — «ادامه از جایی که بودی» */
  at?: number
  autoplay?: boolean
}

let handlers: EngineHandlers | null = null
let ctx: AudioContext | null = null
let eqNodes: BiquadFilterNode[] = []
let master: GainNode | null = null
let limiter: DynamicsCompressorNode | null = null
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
let eqPreset: EqPreset = 'off'
let eqEnabled = false
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
    rampEqualPower(outgoing.fade, 'out', seconds)
    rampEqualPower(incoming.fade, 'in', seconds)
  },

  onHandoff(_outgoing: string, incoming: string): void {
    // تعویض نقش در میانهٔ فید — همان لحظه UI باید ترک تازه را نشان دهد
    const deck = deckByRef(incoming)
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
  },

  onBlendHeadroom(headroom: number): void {
    blendHeadroomValue = headroom
  },

  onBail(outgoing: string | null, incoming: string | null): void {
    // پاک‌سازی دک‌هایی که *فعال نیستند*:
    //  - پایان موفق فید: دک خروجی idle شده → متوقف و آزاد
    //  - bail وسط فید: دک ورودی هنوز شروع‌نشده/نیمه‌کاره → متوقف و آزاد؛
    //    دک فعال (ترک جاری) دست‌نخورده می‌ماند
    for (const ref of [outgoing, incoming]) {
      if (ref === null) continue
      const deck = deckByRef(ref)
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

/**
 * گرافِ Web Audio. یک بار ساخته می‌شود و اگر مرورگر نداشته باشدش، null
 * می‌ماند و بقیه‌ی کد بدون آن کار می‌کند.
 */
function buildGraph(): void {
  if (ctx !== null || typeof window === 'undefined') return
  const Ctor = window.AudioContext ?? (window as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
  if (!Ctor) return

  try {
    ctx = new Ctor()
    master = ctx.createGain()
    eqNodes = EQ_BANDS.map((frequency) => {
      const filter = ctx!.createBiquadFilter()
      filter.type = 'peaking'
      filter.frequency.value = frequency
      filter.Q.value = 1
      filter.gain.value = 0
      return filter
    })
    // باندها پشت‌سرهم، بعد مستر، بعد لیمیتر، بعد بلندگو
    eqNodes.reduce((prev, node) => {
      prev.connect(node)
      return node
    })
    eqNodes[eqNodes.length - 1].connect(master)

    // لیمیتر شفاف با زانوی نرم (soft knee): جلوی دیستورشن دیجیتال را می‌گیرد
    // بدون آنکه بیس‌ها را دچار شکستگی موج (waveshaping) یا خش در هدفون بلوتوث کند
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

    analyser = ctx.createAnalyser()
    analyser.fftSize = 256
    analyser.smoothingTimeConstant = 0.82
    spectrum = new Uint8Array(analyser.frequencyBinCount)

    const outputNode: AudioNode = limiter ?? master
    // outputNode → analyser → destination: طیف را می‌خواند و سیگنال را رد می‌کند
    outputNode.connect(analyser)
    analyser.connect(ctx.destination)
  } catch {
    ctx = null
    master = null
    limiter = null
    eqNodes = []
    analyser = null
    spectrum = null
  }
}

function buildDeck(): Deck {
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

  const deck: Deck = { el, norm: null, fade: null, gainDb: 0, pendingSeek: null }

  if (ctx && eqNodes.length) {
    try {
      const source = ctx.createMediaElementSource(el)
      deck.norm = ctx.createGain()
      deck.fade = ctx.createGain()
      source.connect(deck.norm)
      deck.norm.connect(deck.fade)
      deck.fade.connect(eqNodes[0])
    } catch {
      // createMediaElementSource فقط یک بار به‌ازای هر المنت جواب می‌دهد؛
      // شکستش یعنی این دک بدون گراف کار می‌کند، نه اینکه پخش نشود
      deck.norm = null
      deck.fade = null
    }
  }
  return deck
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
      // فاز ۱۵: اگر منبع HLS باشد (native پخش نمی‌کند)، یک‌بار fallback به hls.js
      // امتحان می‌شود؛ ناموفق بودن آن خطای عادی playback را به بالا می‌دهد.
      // (فاز ۳: این hook جایش را به خط لولهٔ StreamRecovery می‌دهد)
      void maybeHlsFallback(el, () => handlers?.onError())
    }
  })
}

function ensure(): Deck {
  if (!decks) {
    buildGraph()
    decks = [buildDeck(), buildDeck()]
    decks.forEach(attach)
    applyEq()
    statePublisher = new EngineStatePublisher(
      () => Math.round((active()?.el.currentTime ?? 0) * 1000),
      () => {
        const value = active()?.el.duration ?? 0
        return Number.isFinite(value) ? Math.round(value * 1000) : 0
      },
    )
    controller.start()

    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible' && ctx?.state === 'suspended') {
          const d = active()
          if (d && !d.el.paused) void ctx.resume().catch(() => {})
        }
      })
    }
  }
  return decks[activeIndex]
}

function applyEq(): void {
  const values = eqEnabled ? (EQ_PRESETS[eqPreset] ?? EQ_PRESETS.off) : EQ_PRESETS.off
  eqNodes.forEach((node, i) => {
    node.gain.value = values[i] ?? 0
  })
}

function applyNormalize(deck: Deck | null, gainDb: number, smooth = true): void {
  if (!deck?.norm) {
    if (deck) deck.gainDb = gainDb
    return
  }
  deck.gainDb = gainDb
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

  load(src: string, { gainDb = 0, at = 0, autoplay = true }: LoadOptions = {}): void {
    const deck = ensure()

    // یک بارگذاریِ صریح، هر ترنزیشن در جریان را bail می‌کند؛ onBail دک‌های
    // غیرفعال را تمیز می‌کند و دک فعال (همین که می‌خواهیم لود کنیم) دست‌نخورده می‌ماند
    controller.notifyInterruption()
    if (deck.fade) deck.fade.gain.value = 1

    // اگر دکِ غیرفعال قبلاً با همین منبع پرلود شده بود، پاک شود تا تکرار/اکو نشود
    const other = idle()
    if (other && (sameSource(other.el.src, src) || !sameSource(nextSource?.src, other.el.src))) {
      other.el.pause()
      detachHls(other.el)
      other.el.removeAttribute('src')
      other.el.preload = 'metadata'
    }

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
  setNext(src: string | null, gainDb = 0): void {
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
      applyNormalize(other, gainDb)
      if (other.fade) other.fade.gain.value = 1
    }
  },

  setCrossfade(seconds: number): void {
    crossfadeSeconds = Math.max(0, seconds)
    // کوتاه‌شدنِ فید زیر حداقل، ترنزیشن منتظری را بی‌معنا می‌کند
    if (crossfadeSeconds < MIN_CROSSFADE_SECONDS) controller.notifyInterruption()
  },

  setEq(preset: EqPreset): void {
    eqPreset = preset
    applyEq()
  },

  setEqEnabled(on: boolean): void {
    eqEnabled = on
    applyEq()
  },

  setNormalize(on: boolean): void {
    normalizeOn = on
    decks?.forEach((deck) => applyNormalize(deck, deck.gainDb))
  },

  /**
   * تقویتِ سراسریِ گراف به دسی‌بل. وسطِ پخش هم اثر می‌کند: هر دک گِینِ خودش
   * را از نو از همین تابع می‌گیرد — دکِ فعال و دکی که وسطِ کراس‌فید دارد
   * محو می‌شود، هر دو.
   */
  setBoost(db: number): void {
    boostDb = Math.max(0, Math.min(MAX_BOOST_DB, db))
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
      if (deck.fade) deck.fade.gain.value = 1
    })
    statePublisher?.patch({ status: 'IDLE', isPlaying: false, isBuffering: false, errorMessage: null })
  },
}
