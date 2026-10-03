/**
 * رنگِ غالبِ یک کاور — برای تینتِ پس‌زمینه‌ی پخش‌کننده.
 *
 * تصویر روی یک بومِ کوچک کشیده می‌شود و پیکسل‌ها با کوانتیزه‌کردنِ ۴ بیتی
 * سطل‌بندی می‌شوند؛ سطلی که بیشترین امتیازِ (تعداد × اشباع) را دارد، رنگِ
 * غالب است. اشباع در امتیاز وزن دارد تا یک کاورِ خاکستری، رنگِ بی‌روح ندهد.
 *
 * اگر بوم tainted شود (کاورِ بیرونی بدونِ هدرِ CORS) یا تصویر لود نشود،
 * `null` برمی‌گردد و پخش‌کننده همان رنگِ پیش‌فرضِ خودش را نگه می‌دارد.
 */

const cache = new Map<string, [number, number, number] | null>()

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    // کاورها معمولاٌ از `/api/art/…` هم‌مبدأ می‌آیند، ولی اگر آدرسِ CDN باشد
    // این اجازه می‌دهد بوم tainted نشود؛ نشد هم reject می‌خورد و null می‌دهیم
    img.crossOrigin = 'anonymous'
    img.onload = () => resolve(img)
    img.onerror = reject
    img.src = src
  })
}

export async function dominantColor(
  src: string | null,
): Promise<[number, number, number] | null> {
  if (!src) return null
  if (cache.has(src)) return cache.get(src)!

  let result: [number, number, number] | null = null
  try {
    const img = await loadImage(src)
    const size = 24
    const canvas = document.createElement('canvas')
    canvas.width = size
    canvas.height = size
    const ctx = canvas.getContext('2d', { willReadFrequently: true })
    if (ctx) {
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
      if (best) {
        result = [
          Math.round(best.r / best.n),
          Math.round(best.g / best.n),
          Math.round(best.b / best.n),
        ]
      }
    }
  } catch {
    result = null
  }

  // فقط نتایج موفق ذخیره شوند تا خطای موقت شبکه یا CORS کش دائمی نسازد
  if (result) {
    cache.set(src, result)
  }
  return result
}

const FALLBACK_PALETTES: [number, number, number][] = [
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
export function fallbackTint(seed: string): [number, number, number] {
  let h = 0
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0
  return FALLBACK_PALETTES[h % FALLBACK_PALETTES.length]
}

/**
 * رنگِ غالب → جفتِ CSSِ نوار پخش.
 *
 * - `rgb`: سه‌تاییِ خام که در `rgb(var(--pb-rgb) / α)` استفاده می‌شود.
 * - `strong`: همان رنگِ روشن‌شده تا luminance ≈ 0.55. چرا لازم است:
 *   color-mix با درصدِ ثابت روشنایی را هدف نمی‌گیرد، و یک کاورِ تیره اکسنتی
 *   می‌دهد که متنِ مشکیِ روی دکمه‌ی پخش خوانا نیست. فرمولِ سفیدِ افزودنیِ
 *   خطی، luminance را دقیقاً به هدف می‌رساند (و برای رنگِ روشن‌تر از هدف،
 *   w=0 یعنی دست‌نخورده).
 */
export function tintVars(
  rgb: [number, number, number],
): { rgb: string; strong: string } {
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
  dominant: [number, number, number]
  secondary: [number, number, number]
  accent: [number, number, number]
  muted: [number, number, number]
}

function rgbToHsl(r: number, g: number, b: number): [number, number, number] {
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

function hslToRgb(h: number, s: number, l: number): [number, number, number] {
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

/**
 * تولید پالت ۴ رنگی متوازن جهت ساخت اتمسفر نوری زنده (Living Mesh Aurora).
 */
export function deriveHarmonics(dominant: [number, number, number] | null): ColorPalette {
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
export function tidalBgColor(rgb: [number, number, number] | null): string {
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

