/**
 * رنگِ غالبِ یک کاور — برای تینتِ پس‌زمینه‌ی پخش‌کننده و تمِ صفحه‌ها.
 *
 * تصویر روی یک بومِ کوچک کشیده می‌شود و پیکسل‌ها با کوانتیزه‌کردنِ ۴ بیتی
 * سطل‌بندی می‌شوند؛ سطلی که بیشترین امتیازِ (تعداد × اشباع) را دارد، رنگِ
 * غالب است. اشباع در امتیاز وزن دارد تا یک کاورِ خاکستری، رنگِ بی‌روح ندهد.
 *
 * اگر بوم tainted شود (کاورِ بیرونی بدونِ هدرِ CORS) یا تصویر لود نشود،
 * `null` برمی‌گردد و مصرف‌کننده همان تمِ پیش‌فرضِ پایدارِ خودش را نگه می‌دارد.
 */

export type RGB = [number, number, number]

/** سقفِ ورودی‌های کش — جلوی رشدِ بی‌پایان روی گشتِ طولانی را می‌گیرد. */
const CACHE_MAX = 128

/*
 * عمرِ نتیجه‌های منفی.
 *
 * کاورِ ۴۰۴ِ امروز می‌تواند فردا در آینه‌ی محلی حاضر باشد، پس «رنگ ندارد»
 * نباید مثلِ «رنگ دارد» ابدی شود؛ ولی نباید هم هر بارِ ورود به صفحه یک
 * درخواستِ بی‌نتیجه‌ی تازه بزند.
 */
const NEGATIVE_TTL_MS = 60_000

interface CacheEntry {
  rgb: RGB | null
  /** مهرِ زمان — فقط برای نتیجه‌های منفی معنا دارد */
  at: number
}

/*
 * کلید = آدرسِ تصویر.
 *
 * آدرس‌های `/api/art/<sha>` محتوامحور و تغییرناپذیرند (`Cache-Control:
 * immutable` در سرور)، پس نتیجه‌ی موفق هرگز کهنه نمی‌شود و TTL لازم ندارد.
 * ترتیبِ درج، ترتیبِ LRU است: هر خواندن کلید را به ته می‌برد.
 */
const cache = new Map<string, CacheEntry>()

/** درخواست‌های در جریانِ یک آدرس — تا دو ویو هم‌زمان دو `Image` نسازند. */
const inflight = new Map<string, Promise<RGB | null>>()

function isFresh(entry: CacheEntry): boolean {
  return entry.rgb !== null || Date.now() - entry.at < NEGATIVE_TTL_MS
}

function remember(src: string, rgb: RGB | null): void {
  cache.delete(src)
  cache.set(src, { rgb, at: Date.now() })
  while (cache.size > CACHE_MAX) {
    const oldest = cache.keys().next().value
    if (oldest === undefined) break
    cache.delete(oldest)
  }
}

/**
 * رنگِ کش‌شده‌ی یک کاور، بی‌درنگ (سنکرون).
 *
 * مصرف‌کننده‌ها این را پیش از اولین رندر می‌خوانند تا وقتی رنگ از قبل
 * استخراج شده، صفحه حتی یک فریم هم رنگِ جایگزین نشان ندهد.
 */
export function peekArtworkColor(src: string | null): RGB | null {
  if (!src) return null
  const entry = cache.get(src)
  if (!entry || entry.rgb === null) return null
  // خواندن یعنی استفاده؛ برای LRU به ته صف می‌رود
  remember(src, entry.rgb)
  return entry.rgb
}

/** پاک‌کردنِ کاملِ کش — برای تست و هر مسیرِ «پاک‌سازی داده‌ی محلی». */
export function clearArtworkColorCache(): void {
  cache.clear()
  inflight.clear()
}

/** تعدادِ ورودی‌های کش — برای تست. */
export function artworkColorCacheSize(): number {
  return cache.size
}

/**
 * آیا آدرس هم‌مبدأ است؟
 *
 * برای تصویرِ هم‌مبدأ نیازی به `crossOrigin` نیست و گذاشتنش باعث می‌شود
 * مرورگر یک ورودیِ کشِ HTTP جداگانه (CORS-keyed) بسازد و همان کاور دو بار
 * دانلود/کش شود. تصویرِ هم‌مبدأ هرگز بوم را taint نمی‌کند.
 */
function isSameOrigin(src: string): boolean {
  try {
    return new URL(src, location.href).origin === location.origin
  } catch {
    return false
  }
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    // کاورِ CDN بدونِ این هدر بوم را taint می‌کند؛ اگر CORS ندهد هم reject
    // می‌خورد و `null` می‌گیریم — یعنی همان جایگزینِ پایدار.
    if (!isSameOrigin(src)) img.crossOrigin = 'anonymous'
    img.onload = () => resolve(img)
    img.onerror = reject
    img.src = src
  })
}

/**
 * استخراجِ خام. هیچ‌وقت reject نمی‌کند: هر خطایی (شبکه، CORS، بومِ tainted،
 * نبودِ `Image` یا `getContext`) به `null` تبدیل می‌شود تا مصرف‌کننده مجبور
 * نباشد مسیرِ خطا داشته باشد.
 */
async function extract(src: string): Promise<RGB | null> {
  try {
    const img = await loadImage(src)
    const size = 24
    const canvas = document.createElement('canvas')
    canvas.width = size
    canvas.height = size
    const ctx = canvas.getContext('2d', { willReadFrequently: true })
    if (!ctx) return null

    ctx.drawImage(img, 0, 0, size, size)
    const { data } = ctx.getImageData(0, 0, size, size)

    const buckets = new Map<
      number,
      { r: number; g: number; b: number; n: number; sat: number }
    >()
    for (let i = 0; i < data.length; i += 4) {
      if (data[i + 3] < 128) continue
      const r = data[i]
      const g = data[i + 1]
      const b = data[i + 2]
      const max = Math.max(r, g, b)
      const min = Math.min(r, g, b)
      // سیاهِ مطلق و سفیدِ مطلق رنگِ غالبِ معناداری نیستند
      if (max < 24 || min > 235) continue
      const key = ((r >> 4) << 8) | ((g >> 4) << 4) | (b >> 4)
      const bucket = buckets.get(key)
      if (bucket) {
        bucket.r += r
        bucket.g += g
        bucket.b += b
        bucket.n++
        bucket.sat += max - min
      } else {
        buckets.set(key, { r, g, b, n: 1, sat: max - min })
      }
    }

    let best: { r: number; g: number; b: number; n: number; sat: number } | null = null
    let bestScore = -1
    for (const bucket of buckets.values()) {
      const score = bucket.n * (1 + bucket.sat / bucket.n / 255)
      if (score > bestScore) {
        bestScore = score
        best = bucket
      }
    }
    if (!best) return null
    return [
      Math.round(best.r / best.n),
      Math.round(best.g / best.n),
      Math.round(best.b / best.n),
    ]
  } catch {
    return null
  }
}

export async function dominantColor(src: string | null): Promise<RGB | null> {
  if (!src) return null

  const cached = cache.get(src)
  if (cached && isFresh(cached)) {
    remember(src, cached.rgb)
    return cached.rgb
  }
  // نتیجه‌ی منفیِ کهنه ⇒ یک تلاشِ دوباره
  if (cached) cache.delete(src)

  const running = inflight.get(src)
  if (running) return running

  const job = extract(src)
    .then((rgb) => {
      // موفق و ناموفق هر دو ثبت می‌شوند؛ تفاوتشان TTL است نه ذخیره‌شدن
      remember(src, rgb)
      return rgb
    })
    .finally(() => {
      inflight.delete(src)
    })
  inflight.set(src, job)
  return job
}

const FALLBACK_PALETTES: RGB[] = [
  [91, 75, 214],
  [47, 111, 78],
  [138, 59, 46],
  [43, 93, 122],
  [107, 66, 38],
  [122, 47, 93],
  [61, 90, 43],
]

/**
 * رنگ تینت جایگزینِ پایدار از روی شناسه یا سید — وقتی استخراج بوم به دلیل CORS
 * یا خطای شبکه شکست می‌خورد تا پس‌زمینه هرگز خاکستری بی‌روح نماند.
 */
export function fallbackTint(seed: string): RGB {
  let h = 0
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0
  return FALLBACK_PALETTES[h % FALLBACK_PALETTES.length]
}

/**
 * رنگِ غالب → جفتِ CSSِ نوار پخش.
 *
 * - `rgb`: سه‌تاییِ خام که CSS آن را با `rgb(var(--pb-rgb) / α)` مصرف می‌کند.
 * - `strong`: همان رنگِ روشن‌شده تا luminance ≈ 0.55. چرا لازم است:
 *   color-mix با درصدِ ثابت روشنایی را هدف نمی‌گیرد، و یک کاورِ تیره اکسنتِ
 *   تیره‌ای می‌دهد که متنِ مشکیِ روی دکمه‌ی پخش خوانا نیست. فرمولِ سفیدِ
 *   افزودنیِ خطی، luminance را دقیقاً به هدف می‌رساند (و برای رنگِ روشن‌تر از
 *   هدف، w=0 یعنی دست‌نخورده).
 */
/**
 * اکسنتِ تم‌دار — رنگِ تصویر با روشناییِ *هدف*، با حفظِ hue و اشباع.
 *
 * دو دامِ این‌جا بود و هر دو یک ریشه داشتند:
 *
 *  ۱. **رنگ شسته می‌شد.** نسخه‌ی قبلی رنگ را به سمت *سفید* می‌برد
 *     (`c·(1-t) + 255·t`)، که اشباع را می‌کُشد: قرمزِ عمیقِ `[139,0,0]` به
 *     `[205,145,145]` می‌رسید — یعنی صورتیِ پریده. روی کاورِ سرمه‌ای،
 *     دکمه‌ی پخش خاکستری‌آبی می‌شد و رنگِ کاور اصلاً دیده نمی‌شد.
 *  ۲. **هدف هرگز گرفته نمی‌شد.** روشنایی با پروکسیِ خطیِ `tintVars`
 *     (`(0.2126r + 0.7152g + 0.0722b)/255`) حساب می‌شد، نه با فرمولِ رسمیِ
 *     WCAG. آن پروکسی روی رنگ‌های اشباع بسیار بزرگ‌تر از روشناییِ واقعی
 *     درمی‌آید (برای `[139,0,0]` عددِ ۰٫۱۲ می‌دهد در برابر ۰٫۰۳)، پس شرطِ
 *     «به هدف رسیدم؟» زودتر از موعد درست می‌شد و نتیجه روی روشناییِ واقعیِ
 *     ~۰٫۳۵ می‌نشست، نه ۰٫۶۲.
 *
 * حالا روی lightnessِ HSL جست‌وجوی دودویی می‌شود و سنجش با
 * `relativeLuminance`ِ رسمی است. hue و اشباع دقیقاً دست‌نخورده می‌مانند، پس
 * اکسنت همان رنگِ کاور است، فقط در روشناییِ خوانا.
 *
 * فقط روشن می‌کند و هرگز تیره نمی‌کند (`w = 0` برای رنگِ روشن‌تر از هدف) —
 * قراردادِ `tintVars` و نوارِ پخش همین است.
 */
export function accentColor(rgb: RGB, targetLum: number): RGB {
  if (relativeLuminance(rgb) >= targetLum) return [rgb[0], rgb[1], rgb[2]]
  const [h, s] = rgbToHsl(rgb[0], rgb[1], rgb[2])
  /*
   * چون روشنایی نسبت به lightnessِ HSL یکنواست، دودویی روی همان کار می‌کند و
   * برخلافِ مخلوط‌کردن با سفید، اشباع را در تمام مسیر حفظ می‌کند. ۳۰ گام
   * یعنی دقتِ زیرِ یک در ۲^۳۰ — خیلی بیشتر از ۲۵۵ پله‌ی کانال.
   */
  let lo = 0
  let hi = 1
  let best = hslToRgb(h, s, 1)
  for (let i = 0; i < 30; i++) {
    const mid = (lo + hi) / 2
    const candidate = hslToRgb(h, s, mid)
    if (relativeLuminance(candidate) >= targetLum) {
      hi = mid
      best = candidate
    } else {
      lo = mid
    }
  }
  return best
}

export function tintVars(rgb: RGB): { rgb: string; strong: string } {
  const [r, g, b] = rgb
  const lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
  const w = Math.round(Math.min(1, Math.max(0, (0.55 - lum) / (1 - lum))) * 100)
  const triad = `${r} ${g} ${b}`
  return {
    rgb: triad,
    strong: `color-mix(in srgb, rgb(${triad}) ${100 - w}%, white)`,
  }
}

export interface ColorPalette {
  dominant: RGB
  secondary: RGB
  accent: RGB
  muted: RGB
}

/**
 * RGB → HSL. صادر شده چون `pageTheme` برای ساختنِ پایهٔ رنگیِ صفحه لازمش دارد و
 * تکرارِ این ریاضی در دو ماژول یعنی دو جا برای واگرایی.
 */
export function rgbToHsl(r: number, g: number, b: number): [number, number, number] {
  r /= 255
  g /= 255
  b /= 255
  const max = Math.max(r, g, b)
  const min = Math.min(r, g, b)
  let h = 0
  let s = 0
  const l = (max + min) / 2

  if (max !== min) {
    const d = max - min
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min)
    switch (max) {
      case r:
        h = (g - b) / d + (g < b ? 6 : 0)
        break
      case g:
        h = (b - r) / d + 2
        break
      case b:
        h = (r - g) / d + 4
        break
    }
    h /= 6
  }
  return [h * 360, s, l]
}

/** HSL → RGB. صادر شده به همان دلیلی که `rgbToHsl` صادر شد. */
export function hslToRgb(h: number, s: number, l: number): RGB {
  h = (h % 360 + 360) % 360
  const c = (1 - Math.abs(2 * l - 1)) * s
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1))
  const m = l - c / 2
  let r = 0
  let g = 0
  let b = 0

  if (0 <= h && h < 60) {
    r = c; g = x; b = 0
  } else if (60 <= h && h < 120) {
    r = x; g = c; b = 0
  } else if (120 <= h && h < 180) {
    r = 0; g = c; b = x
  } else if (180 <= h && h < 240) {
    r = 0; g = x; b = c
  } else if (240 <= h && h < 300) {
    r = x; g = 0; b = c
  } else if (300 <= h && h < 360) {
    r = c; g = 0; b = x
  }

  return [
    Math.round((r + m) * 255),
    Math.round((g + m) * 255),
    Math.round((b + m) * 255),
  ]
}

/** خطی‌سازیِ یک کانالِ sRGB (صفر تا ۲۵۵) به نورِ خطی. */
function toLinear(c: number): number {
  const s = c / 255
  return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
}

/**
 * بازگشتِ نورِ خطی به کانالِ کدشده‌ی sRGB (صفر تا ۲۵۵).
 *
 * `floor` است نه `round`: خروجیِ این تابع سقفِ روشنایی می‌سازد و گِردکردنِ
 * رو به بالا می‌تواند چند هزارم از سقف رد شود — همان مقداری که تستِ کنتراست
 * را می‌شکند. کم‌کردنِ امن بهتر از رد شدن از سقف است.
 */
function toEncoded(lin: number): number {
  const s = lin <= 0.0031308 ? lin * 12.92 : 1.055 * lin ** (1 / 2.4) - 0.055
  return Math.floor(Math.min(255, Math.max(0, s * 255)))
}

/**
 * روشناییِ نسبیِ WCAG — کانال‌ها اول خطی می‌شوند.
 *
 * توجه: `tintVars` عمداً از یک پروکسیِ خطیِ سریع استفاده می‌کند
 * (`0.2126r + 0.7152g + 0.0722b`) چون هدفش نرمال‌کردنِ رنگ است، نه گزارشِ
 * کنتراست. اینجا فرمولِ رسمی است تا کنتراست واقعاً اندازه‌گیری‌شدنی باشد.
 */
export function relativeLuminance(rgb: RGB): number {
  return 0.2126 * toLinear(rgb[0]) + 0.7152 * toLinear(rgb[1]) + 0.0722 * toLinear(rgb[2])
}

/** نسبتِ کنتراستِ WCAG (۱ تا ۲۱). */
export function contrastRatio(a: RGB, b: RGB): number {
  const la = relativeLuminance(a)
  const lb = relativeLuminance(b)
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05)
}

/**
 * مهارِ روشنایی با مقیاس‌کردنِ نورِ خطی.
 *
 * hue و نسبتِ اشباع دست‌نخورده می‌ماند، فقط «نور» کم می‌شود. برای واش‌های
 * وسیعی که متنِ تم رویشان می‌نشیند لازم است: رنگِ خامِ یک کاورِ زردِ اشباع،
 * اگر بدونِ مهار روی هیرو برود، متنِ روشن را ناخوانا می‌کند.
 */
export function clampLuminance(rgb: RGB, maxLum: number): RGB {
  const lum = relativeLuminance(rgb)
  if (lum <= maxLum || lum <= 0) return rgb
  const k = maxLum / lum
  const out: RGB = [0, 0, 0]
  for (let i = 0; i < 3; i++) out[i] = toEncoded(toLinear(rgb[i]) * k)
  return out
}

/**
 * تولید پالت ۴ رنگی متوازن جهت ساخت اتمسفر نوری زنده (Living Mesh Aurora).
 */
export function deriveHarmonics(dominant: RGB | null): ColorPalette {
  if (!dominant) {
    return {
      dominant: [99, 102, 241],   // indigo
      secondary: [168, 85, 247],  // purple
      accent: [236, 72, 153],     // pink
      muted: [30, 27, 75],        // dark slate
    }
  }

  const [h, s, l] = rgbToHsl(...dominant)
  const clampedS = Math.max(0.4, Math.min(0.85, s))
  const clampedL = Math.max(0.35, Math.min(0.65, l))

  const secondary = hslToRgb((h + 38) % 360, clampedS, Math.min(0.7, clampedL + 0.05))
  const accent = hslToRgb((h + 165) % 360, Math.min(0.9, clampedS + 0.15), Math.max(0.45, clampedL))
  const muted = hslToRgb(h, clampedS * 0.7, Math.max(0.12, clampedL * 0.35))

  return {
    dominant,
    secondary,
    accent,
    muted,
  }
}

/**
 * رنگ پس‌زمینه عمیق و غنی به سبک پلتفرم TIDAL.
 * از رنگ غالب کاور استخراج می‌شود و اشباع را زنده نگه می‌دارد، اما روشنایی
 * را کنترل می‌کند تا متون و کنترل‌های سفید کنتراست کامل داشته باشند.
 */
export function tidalBgColor(rgb: RGB | null): string {
  if (!rgb) return '#121214'
  const [h, s, l] = rgbToHsl(...rgb)
  if (s < 0.08) {
    return '#141416'
  }
  const targetS = Math.max(0.45, Math.min(0.85, s))
  const targetL = Math.max(0.12, Math.min(0.20, l * 0.42))
  const [r, g, b] = hslToRgb(h, targetS, targetL)
  return `rgb(${r}, ${g}, ${b})`
}
