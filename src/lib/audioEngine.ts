/**
 * موتور پخش — دو «دک» صوتی زیر یک گرافِ Web Audio.
 *
 * قبلاً یک `<audio>` تنها بود و سه چیز از آن درنمی‌آمد:
 *
 *  ۱. **هم‌ترازیِ بلندی.** هر ترک با بلندیِ متفاوتی مسترینگ شده و منابعِ ما هم
 *     یکسان نیستند؛ بدون یک GainNode که سرور عددش را داده، هر چند ترک یک‌بار
 *     باید دستی صدا را کم و زیاد کرد.
 *  ۲. **اکولایزر.** فیلترهای Biquad فقط روی گرافِ Web Audio معنی دارند.
 *  ۳. **کراس‌فید.** با یک المنت اصلاً ممکن نیست — دو ترک باید هم‌زمان صدا
 *     بدهند، پس دو المنت لازم است.
 *
 * زنجیره‌ی هر دک: `<audio>` → norm (هم‌ترازی) → fade (کراس‌فید) → EQ → مستر.
 * دو گِینِ جدا لازم است چون رمپِ کراس‌فید مقدارِ گِین را بازنویسی می‌کند و
 * اگر هم‌ترازی روی همان نود می‌نشست، هر فید تنظیمش را پاک می‌کرد.
 *
 * اگر Web Audio نبود (یا مرورگر اجازه نداد)، همه‌چیز بی‌صدا به پخشِ ساده‌ی
 * همان `<audio>` برمی‌گردد: بدون هم‌ترازی، بدون EQ، بدون کراس‌فید — ولی صدا
 * قطع نمی‌شود.
 */

export type EqPreset = 'off' | 'bass' | 'vocal' | 'treble' | 'loud'

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
  onPause: () => void
  onTime: (seconds: number) => void
  onDuration: (seconds: number) => void
  onEnded: () => void
  onError: () => void
  /**
   * کراس‌فید شروع شد و ترکِ بعدی روی دکِ دیگر افتاد.
   *
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

// زیر این مقدار کراس‌فید عملاً شنیده نمی‌شود و فقط ریسکِ پرش دارد
const MIN_CROSSFADE = 0.5

let handlers: EngineHandlers | null = null
let ctx: AudioContext | null = null
let eqNodes: BiquadFilterNode[] = []
let master: GainNode | null = null
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

let crossfadeSeconds = 0
let eqPreset: EqPreset = 'off'
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
/** هم‌ترازیِ دکِ فعال، تا روشن/خاموش کردن نرمال‌سازی وسطِ ترک هم اثر کند */
let activeGainDb = 0
let fading = false

function active(): Deck | null {
  return decks ? decks[activeIndex] : null
}

function idle(): Deck | null {
  return decks ? decks[1 - activeIndex] : null
}

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
    // باندها پشت‌سرهم، بعد مستر، بعد بلندگو
    eqNodes.reduce((prev, node) => {
      prev.connect(node)
      return node
    })
    eqNodes[eqNodes.length - 1].connect(master)
    analyser = ctx.createAnalyser()
    analyser.fftSize = 256
    analyser.smoothingTimeConstant = 0.82
    spectrum = new Uint8Array(analyser.frequencyBinCount)
    // master → analyser → destination: طیف را می‌خواند و سیگنال را رد می‌کند
    master.connect(analyser)
    analyser.connect(ctx.destination)
  } catch {
    ctx = null
    master = null
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
    if (el === active()?.el) handlers?.onPlay()
  })
  el.addEventListener('pause', () => {
    // مکثِ دکِ در حالِ محو شدن، «مکث» نیست — کاربر چیزی را متوقف نکرده
    if (el === active()?.el && !fading) handlers?.onPause()
  })
  el.addEventListener('timeupdate', () => {
    if (el !== active()?.el) return
    handlers?.onTime(el.currentTime)
    maybeCrossfade()
  })
  el.addEventListener('durationchange', () => {
    if (el === active()?.el && Number.isFinite(el.duration)) handlers?.onDuration(el.duration)
  })
  el.addEventListener('ended', () => {
    // پایانِ دکی که کراس‌فید جایش را گرفته بی‌معنی است — صف از قبل جلو رفته
    if (el === active()?.el) handlers?.onEnded()
  })
  el.addEventListener('error', () => {
    if (el === active()?.el) handlers?.onError()
  })
}

function ensure(): Deck {
  if (!decks) {
    buildGraph()
    decks = [buildDeck(), buildDeck()]
    decks.forEach(attach)
    applyEq()

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
  const values = EQ_PRESETS[eqPreset] ?? EQ_PRESETS.off
  eqNodes.forEach((node, i) => {
    node.gain.value = values[i] ?? 0
  })
}

function applyNormalize(deck: Deck | null, gainDb: number): void {
  if (!deck?.norm) {
    if (deck) deck.gainDb = gainDb
    return
  }
  deck.gainDb = gainDb
  const norm = normalizeOn ? gainFromDb(gainDb) : 1
  // تقویت روی همان نود می‌نشیند: هر دو اثرِ دسی‌بلی‌اند و حاصل‌ضربشان همان
  // چیزی است که گوش می‌شنود. اوجی که از ۰ دسی‌بل بالاتر برود در مقصد کلیپ
  // می‌شود — دقیقاً مثلِ پریستِ «پرحجم»ِ اکولایزر، که این تقویت هم همان
  // معامله را با کاربر می‌کند: بلندتر، در ازای ریسکِ کلیپ روی مسترهای داغ.
  deck.norm.gain.value = norm * gainFromDb(boostDb)
}

/** پرشِ معلقِ یک دک را باطل می‌کند — قبل از هر بارگذاریِ تازه روی همان دک */
function cancelPendingSeek(deck: Deck): void {
  if (!deck.pendingSeek) return
  deck.el.removeEventListener('loadedmetadata', deck.pendingSeek)
  deck.pendingSeek = null
}

/** رمپِ خطی روی یک گِین — با فالبک برای مرورگری که setValueAtTime ندارد */
function ramp(node: GainNode | null, to: number, seconds: number): void {
  if (!node || !ctx) return
  const now = ctx.currentTime
  node.gain.cancelScheduledValues(now)
  node.gain.setValueAtTime(node.gain.value, now)
  node.gain.linearRampToValueAtTime(to, now + seconds)
}

/**
 * نزدیکِ پایانِ ترک، ترکِ بعدی را زیرش بالا می‌آورد.
 *
 * دکِ فعال بلافاصله عوض می‌شود (نه در پایانِ رمپ) تا زمان و عنوانی که UI
 * نشان می‌دهد همان ترکی باشد که دارد بلند می‌شود؛ دکِ قبلی فقط صدایش را
 * پایین می‌آورد و بعد متوقف می‌شود.
 */
function maybeCrossfade(): void {
  if (fading || crossfadeSeconds < MIN_CROSSFADE || !nextSource) return
  const current = active()
  if (!current || !current.fade) return

  const remaining = current.el.duration - current.el.currentTime
  if (!Number.isFinite(remaining) || remaining > crossfadeSeconds) return

  const incoming = idle()
  if (!incoming) return

  const seconds = Math.min(crossfadeSeconds, Math.max(remaining, MIN_CROSSFADE))
  fading = true

  const outgoing = current
  const pendingGainDb = nextSource.gainDb
  cancelPendingSeek(incoming)
  incoming.el.src = nextSource.src
  applyNormalize(incoming, pendingGainDb)
  if (incoming.fade) incoming.fade.gain.value = 0
  nextSource = null

  /*
   * هیچ‌چیز تا وقتی دکِ تازه واقعاً صدا ندهد تثبیت نمی‌شود.
   *
   * قبلاً برعکس بود: دکِ فعال بلافاصله عوض می‌شد، `onAdvance` صف را جلو می‌برد
   * و تایمر دکِ قدیمی را متوقف می‌کرد — و اگر `play()` رد می‌شد (فایل رفته،
   * منعِ خودکارپخشِ مرورگر) فقط `fading` پایین می‌آمد. نتیجه: هر دو دک ساکت،
   * صف یک ردیف جلوتر، بدون هیچ خطایی. پخش بی‌صدا می‌مُرد.
   *
   * حالا شکستِ `play()` یعنی هیچ اتفاقی نیفتاده: ترکِ فعلی دست‌نخورده تا آخر
   * می‌رود و مسیرِ همیشگیِ `ended` ترکِ بعدی را بالا می‌آورد — بدون کراس‌فید،
   * ولی بدون سکوت.
   */
  void incoming.el
    .play()
    .then(() => {
      activeGainDb = pendingGainDb
      ramp(outgoing.fade, 0, seconds)
      ramp(incoming.fade, 1, seconds)
      activeIndex = 1 - activeIndex

      window.setTimeout(() => {
        outgoing.el.pause()
        outgoing.el.removeAttribute('src')
        if (outgoing.fade) outgoing.fade.gain.value = 1
        fading = false
      }, seconds * 1000)

      handlers?.onAdvance()
      if (Number.isFinite(incoming.el.duration)) handlers?.onDuration(incoming.el.duration)
    })
    .catch(() => {
      incoming.el.pause()
      incoming.el.removeAttribute('src')
      if (incoming.fade) incoming.fade.gain.value = 1
      fading = false
    })
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

  load(src: string, { gainDb = 0, at = 0, autoplay = true }: LoadOptions = {}): void {
    const deck = ensure()

    // یک بارگذاریِ صریح، هر کراس‌فیدِ در جریان را باطل می‌کند
    if (fading) {
      const other = idle()
      other?.el.pause()
      if (other?.fade) other.fade.gain.value = 1
      fading = false
    }
    if (deck.fade) deck.fade.gain.value = 1

    activeGainDb = gainDb
    applyNormalize(deck, gainDb)
    cancelPendingSeek(deck)
    deck.el.src = src
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
      handlers?.onError()
    })
  },

  pause(): void {
    decks?.forEach((deck) => deck.el.pause())
  },

  seek(seconds: number): void {
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

  /** ترکی که کراس‌فید باید به آن برود؛ null یعنی کراس‌فیدی در کار نیست */
  setNext(src: string | null, gainDb = 0): void {
    nextSource = src ? { src, gainDb } : null
  },

  setCrossfade(seconds: number): void {
    crossfadeSeconds = Math.max(0, seconds)
  },

  setEq(preset: EqPreset): void {
    eqPreset = preset
    applyEq()
  },

  setNormalize(on: boolean): void {
    normalizeOn = on
    applyNormalize(active(), activeGainDb)
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
    fading = false
    nextSource = null
    decks?.forEach((deck) => {
      cancelPendingSeek(deck)
      deck.el.pause()
      deck.el.removeAttribute('src')
      if (deck.fade) deck.fade.gain.value = 1
    })
  },
}
