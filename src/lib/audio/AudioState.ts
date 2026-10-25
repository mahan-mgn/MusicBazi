/**
 * وضعیت رسمی موتور صوتی — پورت `core/AudioState.kt` اندروید.
 *
 * اندروید یک `StateFlow<AudioState>` دارد: اسنپ‌شاتِ تغییرناپذیری که همیشه
 * می‌گوید موتور کجاست. وب این را نداشت؛ UI از رویدادهای پراکنده (`buffering`
 * بولی، `failed` بولی) این‌ور و آن‌ور می‌پرید و هیچ منبع واحدِ حقیقت نبود.
 *
 * وضعیت‌ها یک‌به‌یک همان enum اندرویدند:
 *   IDLE → هنوز هیچ چیزی لود نشده
 *   BUFFERING → در حال آوردن داده (چرخان UI همین‌جاست)
 *   READY → آماده یا در حال پخش
 *   ENDED → ترک به انتها رسید (بدون ترک بعدیِ از پیش نشسته)
 *   ERROR → پخش شکست خورد
 *
 * این ماژول عمداً وابسته به Web Audio و DOM نیست — فقط تیکرش برای اینکه
 * موقعیت جلو برود به `document.visibilityState` نگاه می‌کند و در تب مخفی
 * کم‌بسامد می‌شود.
 */

/** وضعیت کلان موتور — همان ترتیب و معنای `Status` اندروید */
export type AudioStatus = 'IDLE' | 'BUFFERING' | 'READY' | 'ENDED' | 'ERROR'

/** اسنپ‌شات تغییرناپذیر وضعیت — معادل data class اندروید */
export interface AudioStateSnapshot {
  status: AudioStatus
  isPlaying: boolean
  currentTrackId: string | null
  positionMs: number
  durationMs: number
  volume: number
  isBuffering: boolean
  errorMessage: string | null
}

/** کلیدهای وضعیت که صاحبِ موتور (audioEngine) روی آن‌ها می‌نویسد */
export interface AudioStatePatch {
  status?: AudioStatus
  isPlaying?: boolean
  currentTrackId?: string | null
  positionMs?: number
  durationMs?: number
  volume?: number
  isBuffering?: boolean
  errorMessage?: string | null
}

export type AudioStateListener = (state: AudioStateSnapshot) => void

/**
 * پیشرفتِ موقعیت به‌صورت ms منتشر می‌شود؛ UI به ثانیه خو گرفته و موتورِ
 * اندروید هم ms می‌دهد. سقفِ دقتِ نوار پیشرفت همین ۲۵۰ms است نه کمتر.
 */
export const PROGRESS_INTERVAL_MS = 250
/** در تب مخفی تایمرها throttle می‌شوند؛ خودمان هم کم‌کار می‌کنیم */
export const HIDDEN_PROGRESS_INTERVAL_MS = 1000

/**
 * نگه‌دارنده و پخش‌کننده وضعیت موتور.
 *
 * عمداً ساده نگه داشته شده: یک مقدار + لیست شنونده. Zustand اینجا نمی‌نشیند
 * چون موتور بیرون از React ساخته می‌شود و چرخه‌های رندر نباید به زمان‌بندی
 * صدا گره بخورند.
 */
export class EngineStatePublisher {
  private state: AudioStateSnapshot = {
    status: 'IDLE',
    isPlaying: false,
    currentTrackId: null,
    positionMs: 0,
    durationMs: 0,
    volume: 1,
    isBuffering: false,
    errorMessage: null,
  }

  private listeners = new Set<AudioStateListener>()
  private ticker: ReturnType<typeof setInterval> | null = null
  private tickerIntervalMs = 0

  /** تیکر، با read/advance موقعیت — صاحبِ واقعیِ زمان دکِ فعال موتور است */
  constructor(
    private readonly readPositionMs: () => number,
    private readonly readDurationMs: () => number,
  ) {}

  snapshot(): AudioStateSnapshot {
    return this.state
  }

  subscribe(listener: AudioStateListener): () => void {
    this.listeners.add(listener)
    listener(this.state)
    return () => {
      this.listeners.delete(listener)
    }
  }

  patch(next: AudioStatePatch): void {
    const merged: AudioStateSnapshot = {
      status: next.status ?? this.state.status,
      isPlaying: next.isPlaying ?? this.state.isPlaying,
      currentTrackId: next.currentTrackId !== undefined ? next.currentTrackId : this.state.currentTrackId,
      positionMs: next.positionMs ?? this.state.positionMs,
      durationMs: next.durationMs ?? this.state.durationMs,
      volume: next.volume ?? this.state.volume,
      isBuffering: next.isBuffering ?? this.state.isBuffering,
      errorMessage: next.errorMessage !== undefined ? next.errorMessage : this.state.errorMessage,
    }
    // تساوی سطحی: بدون آن هر تیکِ position هم شنونده‌های UI را بیدار می‌کند
    if (sameState(merged, this.state)) return
    this.state = merged
    this.emit()
  }

  /**
   * تیکر پیشرفت — معادل حلقه coroutine اندروید.
   *
   * فقط وقتی موتور واقعاً کاری دارد تیک می‌خورد (READY/BUFFERING)؛ در IDLE و
   * ENDED و ERROR ساکت می‌شود تا موقعیت مرده دوباره‌نویسی نشود.
   */
  syncTicker(): void {
    const active = this.state.status === 'READY' || this.state.status === 'BUFFERING'
    const wanted = active ? this.currentInterval() : 0
    // هم روی ورود/خروج از وضعیت فعال و هم روی تغییرِ مخفی/آشکار، تیکر از نو
    // ساخته می‌شود — setInterval خودش بسامد عوض نمی‌کند
    if (this.ticker !== null && (wanted === 0 || wanted !== this.tickerIntervalMs)) {
      clearInterval(this.ticker)
      this.ticker = null
    }
    if (wanted !== 0 && this.ticker === null) {
      this.tickerIntervalMs = wanted
      this.ticker = setInterval(() => this.tick(), wanted)
    }
  }

  dispose(): void {
    if (this.ticker !== null) clearInterval(this.ticker)
    this.ticker = null
    this.listeners.clear()
  }

  private currentInterval(): number {
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') {
      return HIDDEN_PROGRESS_INTERVAL_MS
    }
    return PROGRESS_INTERVAL_MS
  }

  private tick(): void {
    // تغییرِ مخفی/آشکارِ تب بی‌هیچ patchی رخ می‌دهد؛ اینجا بسامد را تطبیق می‌دهیم
    if (this.ticker !== null && this.tickerIntervalMs !== this.currentInterval()) {
      this.syncTicker()
    }
    this.patch({ positionMs: this.readPositionMs(), durationMs: this.readDurationMs() })
  }

  private emit(): void {
    for (const listener of this.listeners) listener(this.state)
    this.syncTicker()
  }
}

function sameState(a: AudioStateSnapshot, b: AudioStateSnapshot): boolean {
  return (
    a.status === b.status &&
    a.isPlaying === b.isPlaying &&
    a.currentTrackId === b.currentTrackId &&
    a.positionMs === b.positionMs &&
    a.durationMs === b.durationMs &&
    a.volume === b.volume &&
    a.isBuffering === b.isBuffering &&
    a.errorMessage === b.errorMessage
  )
}
