/*
 * HLS playback adapter برای Web (فاز ۱۵) — Strategy B فاز ۱۳.
 *
 *isolated: نه AudioEngine بازنویسی می‌شود نه Zustand؛ فقط یک fallback لایه‌ای
 * روی همان HTMLAudioElement موجود. Progressive همیشه native-first می‌ماند.
 *
 * Detection: native-first — HTMLAudioElement اگر بتواند (Safari / progressive)
 * خودش پخش می‌کند؛ فقط روی media error است که fallback به hls.js امتحان می‌شود
 * (فقط برای srcهای /api/stream خودِ سرور). hls.js به‌صورت lazy بارگذاری می‌شود.
 *
 * امنیت: client فقط URLهای داخلی Music Bazi را می‌بیند (manifest بازنویسی‌شده
 * فاز ۱۴)؛ هیچ signed upstream URL به این لایه نمی‌رسد.
 */
import type HlsType from 'hls.js'

// undefined = هنوز تلاش نشده، null = بارگذاری شکست خورده (offline/bundle)
let HlsCtor: typeof HlsType | null | undefined

const attached = new WeakMap<HTMLMediaElement, HlsType>()

/** فقط منبع‌های استریم خود سرور شایسته fallback هستند — نه هر src خطاداده‌ای. */
export function isOurStreamSource(src: string): boolean {
  try {
    return new URL(src, globalThis.location?.href ?? 'http://localhost').pathname.startsWith(
      '/api/stream',
    )
  } catch {
    return false
  }
}

export function hlsActive(el: HTMLMediaElement): boolean {
  return attached.has(el)
}

async function loadHls(): Promise<typeof HlsType | null> {
  if (HlsCtor !== undefined) return HlsCtor
  try {
    const mod = await import('hls.js')
    HlsCtor = mod.default
  } catch {
    HlsCtor = null
  }
  return HlsCtor
}

/** جداکردن hls.js از المنت (در load/stop/crossfade بعدی) — بدون destroy دوباره. */
export function detachHls(el: HTMLMediaElement): void {
  const hls = attached.get(el)
  if (hls) {
    attached.delete(el)
    hls.destroy()
  }
}

/**
 * تلاش برای پخش HLS با hls.js روی همین المنت (MSE).
 * true یعنی manifest پذیرفته شد و پخش ادامه دارد؛ false یعنی HLS ممکن نبود
 * (dependency نبود، MSE نبود، manifest نامعتبر) — caller مسیر خطای عادی می‌رود.
 */
export async function attachHls(
  el: HTMLMediaElement,
  url: string,
  onError: () => void,
): Promise<boolean> {
  if (attached.has(el)) return true
  const Hls = await loadHls()
  if (!Hls || !Hls.isSupported()) return false

  const hls = new Hls({ enableWorker: true, backBufferLength: 60 })
  attached.set(el, hls)
  hls.on(Hls.Events.ERROR, (_event, data) => {
    if (!data.fatal) return
    detachHls(el)
    onError()
  })
  hls.attachMedia(el)
  hls.loadSource(url)
  return true
}

/**
 * hook خطای audioEngine: روی media error برای srcهای خودِ سرور، یک‌بار fallback
 * به hls.js را امتحان می‌کند. اگر HLS فعال بود و باز خطا داد (fatal)، onError
 * اصلی صدا زده می‌شود — هیچ retry loop ای وجود ندارد.
 */
export async function maybeHlsFallback(
  el: HTMLMediaElement,
  onError: () => void,
): Promise<void> {
  if (attached.has(el)) {
    // خطا از خود hls.js آمده (fatal → detach شده) — خطای واقعی playback است
    onError()
    return
  }
  const src = el.currentSrc || el.src
  if (!src || !isOurStreamSource(src)) {
    onError()
    return
  }
  const url = src
  const ok = await attachHls(el, url, onError)
  if (!ok) {
    onError()
    return
  }
  // MSE متادیتا را تازه می‌آورد؛ پخش را ادامه می‌دهیم
  el.play().catch(() => {
    /* autoplay policy — کاربر play را دوباره می‌زند */
  })
}
