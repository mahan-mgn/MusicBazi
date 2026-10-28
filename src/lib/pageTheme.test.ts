/*
 * `@types/node` در allowlistِ `types` توکنفیگ نیست، پس تایپِ `node:fs` پیدا
 * نمی‌شود؛ در زمانِ اجرا ویتست روی Node است و مشکلی ندارد. سرکوب عمدی و محدود
 * به همین یک خط است.
 */
// @ts-expect-error -- node types خارج از allowlistِ tsconfig
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { clampLuminance, contrastRatio, fallbackTint, relativeLuminance, rgbToHsl } from './artColor'
import type { RGB } from './artColor'
import {
  MESH_AURA_ALPHA,
  PAGE_BASE,
  PAGE_RAMP_ALPHA,
  TEXT_GUARD_ALPHA,
  WASH_MAX_ALPHA,
  WASH_MAX_LUM,
  compositedContrast,
  meshAuraAlphaAt,
  pageBase,
  pageRampAlphaAt,
  pageRampLayers,
  pageTheme,
  pageThemeVars,
  type ColorLayer,
  type PageTheme,
} from './pageTheme'

/*
 * آینه‌ی توکن‌های تم از `index.css`.
 *
 * عمداً در تست است و نه در ماژول: `index.css` تنها منبعِ حقیقتِ رنگ‌هاست و
 * تکرارِ آن در کدِ محصول یعنی دو جا برای واگرایی. اینجا فقط برای این است که
 * قراردادِ خوانایی عددی و اجراپذیر شود.
 *
 *   dark  → index.css:13-40   (--bg: #070707، --fg: #f2f2f2)
 *   light → index.css:42-61   (--bg: #f7f7f5، --fg: #131313)
 */
type Mode = 'dark' | 'light'

const THEME: Record<Mode, { bg: RGB; fg: RGB; muted: RGB; worstArtwork: RGB }> = {
  dark: { bg: [7, 7, 7], fg: [242, 242, 242], muted: [163, 163, 163], worstArtwork: [255, 255, 255] },
  light: { bg: [247, 247, 245], fg: [19, 19, 19], muted: [89, 89, 89], worstArtwork: [0, 0, 0] },
}

/**
 * زنجیره‌ی لایه‌های باندِ متنیِ هیرو، دقیقاً همان‌طور که در DOM سوار می‌شوند:
 * scrimهای `HeroBackdrop`، بعد واشِ هیرو، بعد گاردِ متنی. `worstArtwork` هم
 * بدترین کاورِ ممکن برای آن تم است.
 */
function heroLayers(theme: PageTheme, mode: Mode): ColorLayer[] {
  const { bg } = THEME[mode]
  return [
    // bg-bg/25 در HeroBackdrop (Artwork.tsx:115)
    { rgb: bg, alpha: 0.25 },
    // بدترین بخشِ scrimِ کناریِ HeroBackdrop (Artwork.tsx:125-131)
    { rgb: bg, alpha: 0.3 },
    // اوجِ واشِ هیرو
    { rgb: theme.wash, alpha: WASH_MAX_ALPHA },
    // گاردِ متنیِ پایینِ هیرو
    { rgb: bg, alpha: TEXT_GUARD_ALPHA },
  ]
}

/** بدترین کاورهای ممکن — همه در محدوده‌ی مجازِ فیلترِ `dominantColor`. */
const COVERS: RGB[] = [
  [255, 255, 0],
  [255, 235, 120],
  [255, 255, 255],
  [235, 235, 235],
  [255, 128, 0],
  [255, 0, 0],
  [0, 196, 0],
  [0, 0, 255],
  [0, 255, 255],
  [255, 0, 255],
  [12, 200, 60],
  [180, 20, 50],
  [128, 128, 128],
  [91, 75, 214],
  [20, 30, 90],
  [24, 24, 24],
  [7, 7, 7],
  [0, 0, 0],
]

const SEEDS = ['artist:sp:1', 'album:apple:2', 'track-3', 'x', 'آلبوم فارسی']

/*
 * همان کلیدهایی که `pageThemeVars` بیرون می‌دهد و CSS ثبت می‌کند.
 *
 * دو گروه‌اند و تفاوتشان مهم است: پانزده سه‌گانه‌ی *عددی* که `@property` با
 * `syntax: '<number>'` ثبتشان می‌کند تا انیمیت شوند، و سه رشته‌ی رنگِ آماده
 * (`--accent`، `--accent-dim`، `--accent-fg`) که عمداً ثبت نشده‌اند چون
 * درون‌یابیِ `<color>` گرادیان‌های ساخته‌شده از آن‌ها را نرم نمی‌کند.
 */
const KEYS = [
  '--tint-r',
  '--tint-g',
  '--tint-b',
  '--page-r',
  '--page-g',
  '--page-b',
  '--mesh1-r',
  '--mesh1-g',
  '--mesh1-b',
  '--mesh2-r',
  '--mesh2-g',
  '--mesh2-b',
  '--mesh3-r',
  '--mesh3-g',
  '--mesh3-b',
]

/** رشته‌های رنگِ آماده — در `Object.keys` هستند ولی سه‌گانه‌ی عددی نیستند. */
const COLOR_KEYS = ['--accent', '--accent-dim', '--accent-fg']

describe('pageTheme', () => {
  it('keeps the extracted colour and reports where it came from', () => {
    const theme = pageTheme([12, 200, 60], 'seed', 'dark')
    expect(theme.extracted).toEqual([12, 200, 60])
    expect(theme.source).toEqual([12, 200, 60])
    // مود جزءِ کلید است: پایه‌ی صفحه در دو تم فرق می‌کند، پس هویتِ تم هم باید
    expect(theme.key).toBe('art:12 200 60:dark')
  })

  it('falls back to the deterministic seeded palette when extraction failed', () => {
    const theme = pageTheme(null, 'album:9', 'dark')
    expect(theme.extracted).toBeNull()
    expect(theme.source).toEqual(fallbackTint('album:9'))
    expect(theme.key).toBe(`seed:${fallbackTint('album:9').join(' ')}:dark`)
  })

  it('is stable for the same input and differs for a different cover', () => {
    expect(pageTheme([1, 2, 3], 's', 'dark')).toEqual(pageTheme([1, 2, 3], 's', 'dark'))
    expect(pageTheme([1, 2, 3], 's', 'dark').key).not.toBe(pageTheme([4, 5, 6], 's', 'dark').key)
  })

  it('keeps the seeded fallback stable for the same seed', () => {
    expect(pageTheme(null, 'same', 'dark')).toEqual(pageTheme(null, 'same', 'dark'))
  })

  it('derives the sheet background and the mesh from the raw source', () => {
    const theme = pageTheme([12, 200, 60], 'seed', 'dark')
    expect(theme.bg).toMatch(/^rgb\(\d+, \d+, \d+\)$/)
    // مشِ اتمسفر عمداً رنگِ خام است تا هویتِ بصریِ شیت دست‌نخورده بماند
    expect(theme.mesh.dominant).toEqual(theme.source)
  })

  it('produces a usable theme for every seeded palette', () => {
    for (const seed of SEEDS) {
      const theme = pageTheme(null, seed, 'dark')
      const [r, g, b] = theme.source
      expect([r, g, b].every((c) => Number.isInteger(c) && c >= 0 && c <= 255)).toBe(true)
      expect(theme.wash.every((c) => Number.isInteger(c) && c >= 0 && c <= 255)).toBe(true)
      expect(theme.bg).not.toBe('')
      expect(theme.accent).toContain('color-mix')
    }
  })
})

describe('pageTheme wash ceiling', () => {
  it('never lets a wide wash get brighter than the ceiling', () => {
    for (const cover of COVERS) {
      expect(relativeLuminance(pageTheme(cover, 's', 'dark').wash)).toBeLessThanOrEqual(
        WASH_MAX_LUM
      )
    }
  })

  it('leaves a cover that is already dark enough untouched', () => {
    for (const cover of [
      [0, 0, 0],
      [7, 7, 7],
      [24, 24, 24],
      [20, 30, 90],
      [128, 128, 128],
    ] as RGB[]) {
      expect(pageTheme(cover, 's', 'dark').wash).toEqual(cover)
    }
  })

  it('actually dims a saturated bright cover', () => {
    const bright = pageTheme([255, 255, 0], 's', 'dark')
    expect(bright.wash).not.toEqual(bright.source)
    expect(relativeLuminance(bright.wash)).toBeLessThan(relativeLuminance(bright.source))
  })

  it('agrees with clampLuminance', () => {
    for (const cover of COVERS) {
      expect(pageTheme(cover, 's', 'dark').wash).toEqual(clampLuminance(cover, WASH_MAX_LUM))
    }
  })
})

/*
 * قراردادِ خوانایی.
 *
 * گاردِ متنیِ تخت، تضمینِ اصلی است و مهارِ روشناییِ واش لایه‌ی دوم. این تست‌ها
 * هر دو تم و بدترین کاورِ ممکنِ هر تم را می‌سنجند، پس اگر روزی کسی آلفای گارد
 * یا سقفِ روشنایی را کم کند، اینجا سرخ می‌شود.
 */
describe('hero text contrast contract', () => {
  const modes: Mode[] = ['dark', 'light']

  it('clears WCAG AA for every cover in both themes', () => {
    for (const mode of modes) {
      const { fg, worstArtwork } = THEME[mode]
      for (const cover of COVERS) {
        const theme = pageTheme(cover, 's', 'dark')
        const ratio = compositedContrast(fg, worstArtwork, heroLayers(theme, mode))
        // برچسبِ گویا تا شکست بگوید کدام تم و کدام کاور مقصر بوده
        expect({ mode, cover, ok: ratio >= 4.5 }).toEqual({ mode, cover, ok: true })
      }
    }
  })

  it('clears WCAG AA for every seeded fallback in both themes', () => {
    for (const mode of modes) {
      const { fg, worstArtwork } = THEME[mode]
      for (const seed of SEEDS) {
        const theme = pageTheme(null, seed, 'dark')
        expect(
          compositedContrast(fg, worstArtwork, heroLayers(theme, mode))
        ).toBeGreaterThanOrEqual(4.5)
      }
    }
  })

  it('is measured against the real theme foregrounds', () => {
    // اگر توکن‌های تم عوض شوند، این عددها هم باید بازبینی شوند
    expect(THEME.dark.fg).toEqual([242, 242, 242])
    expect(THEME.light.fg).toEqual([19, 19, 19])
  })
})

/*
 * پایه‌ی عمیقِ صفحه.
 *
 * این تست سه چیز را قفل می‌کند که «ناحیه‌ی مشکیِ خالی دیگر وجود ندارد» را از
 * یک ادعای کامنتی به یک قرارداد اجراپذیر تبدیل می‌کند:
 *
 *  ۱. کفِ روشنایی: پایه هرگز به مشکیِ مطلق نمی‌رسد.
 *  ۲. هیو: رنگِ پایه هم‌خانواده‌ی تصویر است، نه یک خاکستریِ بی‌رنگ.
 *  ۳. خوانایی: خودِ پایه، با متنِ تم، از AA رد می‌شود — و رمپ رویش جا دارد.
 */
describe('page base', () => {
  const modes: Mode[] = ['dark', 'light']

  it('never bottoms out at absolute black', () => {
    for (const mode of modes) {
      for (const cover of [...COVERS, [1, 1, 1]] as RGB[]) {
        const base = pageBase(cover, mode)
        const maxCh = Math.max(base[0], base[1], base[2])
        const minCh = Math.min(base[0], base[1], base[2])
        if (mode === 'dark') {
          // روشن‌ترین کانال باید به‌طور محسوس بالای مشکیِ --bg (#070707) باشد
          expect({ cover, ok: maxCh > 7 }).toEqual({ cover, ok: true })
        }
        // هیچ‌کدام از دو تم نمی‌تواند به یک رنگِ کاملاً تخت برسد
        expect(maxCh - minCh).toBeGreaterThan(0)
      }
    }
  })

  it('keeps the hue of the artwork instead of going grey', () => {
    for (const mode of modes) {
      for (const cover of COVERS) {
        // رنگ‌های نزدیک به خاکستری عمداً به پایه‌ی خنثی می‌روند
        const [h, s] = rgbToHsl(cover[0], cover[1], cover[2])
        if (s < 0.08) continue
        const [bh, bs] = rgbToHsl(...(pageBase(cover, mode) as [number, number, number]))
        // هیوی درست و اشباعِ واقعی (نه یک ته‌رنگِ تصادفی)
        expect({ cover, ok: bs > 0.08 }).toEqual({ cover, ok: true })
        const delta = Math.abs(((bh - h + 540) % 360) - 180)
        expect({ cover, delta, ok: delta < 4 }).toEqual({ cover, delta, ok: true })
      }
    }
  })

  it('uses a neutral floor for colourless artwork rather than inventing a hue', () => {
    for (const mode of modes) {
      expect(pageBase([128, 128, 128], mode)).toEqual([...PAGE_BASE[mode].neutral])
      expect(pageBase([7, 7, 7], mode)).toEqual([...PAGE_BASE[mode].neutral])
    }
  })

  it('honours the luminance ceiling in the dark theme', () => {
    for (const cover of COVERS) {
      expect(relativeLuminance(pageBase(cover, 'dark'))).toBeLessThanOrEqual(
        PAGE_BASE.dark.maxLum as number
      )
    }
  })

  it('stays lighter than the flat --bg it replaces', () => {
    /*
     * کلِ هدفِ این کار همین است: رنگِ ترسیم‌شده در هیچ نقطه‌ای همان `--bg`
     * نباشد. اگر کسی `PAGE_BASE` را محافظه‌کارانه‌تر کند، این‌جا سرخ می‌شود.
     */
    for (const mode of modes) {
      for (const cover of COVERS) {
        expect(pageBase(cover, mode)).not.toEqual(THEME[mode].bg)
      }
    }
  })
})

/*
 * قراردادِ خواناییِ رمپِ صفحه.
 *
 * جدا از قراردادِ هیرو است چون سطحش فرق می‌کند: هیرو سه لایه روی هم می‌سوار
 * می‌کند و در نهایت گاردِ متنیِ تخت دارد، ولی متن‌های پایینِ صفحه (تیترِ
 * بخش‌ها، حالتِ خالی) روی خودِ پس‌زمینه می‌نشینند و هیچ گاردی ندارند.
 *
 * این تست روی *کلِ* ارتفاعِ رمپ عدد می‌گیرد و نه فقط روی یک نقطه. قراردادِ
 * قبلی (واشِ تخت) همین‌جا یک سوراخ داشت: اوجِ گلو هرگز برای `--muted` سنجیده
 * نمی‌شد و در عمل باندِ بالای صفحه زیرِ AA می‌رفت. اسکنِ نقطه‌به‌نقطه همان را
 * می‌گیرد.
 */
describe('page ramp contrast contract', () => {
  const modes: Mode[] = ['dark', 'light']

  /** همه‌ی ارتفاع‌های رمپ، به‌صورت کسری از ارتفاعِ دید. */
  const heights = Array.from({ length: 41 }, (_, i) => i / 40)

  it('clears WCAG AA for foreground text anywhere on the ramp, both themes', () => {
    for (const mode of modes) {
      const { fg } = THEME[mode]
      for (const cover of COVERS) {
        const theme = pageTheme(cover, 's', mode)
        for (const t of heights) {
          const ratio = compositedContrast(fg, theme.page, pageRampLayers(theme, mode, t))
          expect({ mode, cover, t, ok: ratio >= 4.5 }).toEqual({ mode, cover, t, ok: true })
        }
      }
    }
  })

  /*
   * متنِ کم‌رنگ (`--muted`) تنگ‌ترین حالت است: تیترها `--fg` می‌گیرند و راحت
   * رد می‌شوند، ولی متادیتا و زیرنویس‌ها `--muted`‌اند. همین عدد است که سقفِ
   * PAGE_RAMP_ALPHA و کفِ PAGE_BASE.maxLum را تعیین می‌کند، نه سلیقه.
   */
  it('clears WCAG AA for muted text anywhere on the ramp, both themes', () => {
    for (const mode of modes) {
      const { muted } = THEME[mode]
      for (const cover of COVERS) {
        const theme = pageTheme(cover, 's', mode)
        for (const t of heights) {
          const ratio = compositedContrast(muted, theme.page, pageRampLayers(theme, mode, t))
          expect({ mode, cover, t, ok: ratio >= 4.5 }).toEqual({ mode, cover, t, ok: true })
        }
      }
    }
  })

  it('clears WCAG AA for seeded fallbacks too', () => {
    for (const mode of modes) {
      const { muted, fg } = THEME[mode]
      for (const seed of SEEDS) {
        const theme = pageTheme(null, seed, mode)
        for (const t of heights) {
          const layers = pageRampLayers(theme, mode, t)
          expect(
            compositedContrast(muted, theme.page, layers),
            `muted @ ${seed}/${mode}/${t}`
          ).toBeGreaterThanOrEqual(4.5)
          expect(compositedContrast(fg, theme.page, layers)).toBeGreaterThanOrEqual(4.5)
        }
      }
    }
  })

  it('starts strong enough to be seen and fades out before the page ends', () => {
    for (const mode of modes) {
      // بالا باید واقعاً رنگ داشته باشد…
      expect(pageRampAlphaAt(mode, 0)).toBeGreaterThan(0)
      // …و ته صفحه به پایه‌ی مات برسد، نه به یک واشِ باقی‌مانده
      expect(pageRampAlphaAt(mode, 0.72)).toBe(0)
      expect(pageRampAlphaAt(mode, 1)).toBe(0)
      // پیوسته و نزولی نیست ولی هرگز منفی/بیش‌از‌حد نیست
      for (const t of heights) {
        const a = pageRampAlphaAt(mode, t)
        expect(a).toBeGreaterThanOrEqual(0)
        expect(a).toBeLessThanOrEqual(Math.max(...Object.values(PAGE_RAMP_ALPHA[mode])))
      }
    }
  })

  it('keeps the ramp peaks at or below the measured ceiling', () => {
    /*
     * سقفِ ۰٫۱۲ از اسکنِ همان تستِ بالا آمده، با حاشیه‌ی امن و نه روی مرز:
     * روی بدترین کاور (`#ffff00` در تمِ تیره) متنِ `--muted` روی اوجِ رمپ به
     * ۴٫۷۹ می‌رسد. اگر کسی α را بالا ببرد این‌جا سرخ می‌شود.
     */
    for (const mode of modes) {
      expect(Math.max(PAGE_RAMP_ALPHA[mode].top, PAGE_RAMP_ALPHA[mode].mid)).toBeLessThanOrEqual(
        0.12
      )
    }
  })

  it('returns no layer where the ramp has fully faded', () => {
    const theme = pageTheme([12, 200, 60], 's', 'dark')
    expect(pageRampLayers(theme, 'dark', 0.9)).toEqual([])
  })
})

/*
 * قراردادِ خواناییِ شیتِ «در حال پخش».
 *
 * این یکی جایگزینِ قراردادِ کنتراستی نشده که «مارک‌آپ» در NowPlaying.dom.test.tsx
 * ساخت (حذف بلور و scrimها)، بلکه تکمیلش است: آن تست می‌گوید لایهٔ تاریک‌کننده
 * *نیست*، این تست می‌گوید بدونِ آن هم متنِ سفید خوانا *می‌ماند*.
 *
 * چرا روی *هندسه* عدد می‌گیریم و نه با فرضِ روی‌هم‌افتادنِ کامل: سه گرادیان
 * مرکزهای دوری دارند (۵۰٪/۱۵٪، ۸۵٪/۸۵٪، ۱۵٪/۷۵٪). اگر همه را در یک نقطه
 * روی هم فرض کنیم، تست به حذفِ رنگی می‌رسد که در واقعیت هیچ‌وقت رخ نمی‌دهد و
 * اتمسفر را بی‌دلیل ملایم می‌کند. پس بدترین نقطه‌ی واقعیِ صفحه جست‌وجو می‌شود.
 */
describe('now playing sheet contrast contract', () => {
  const WHITE: RGB = [255, 255, 255]

  /*
   * بدترین زمینه‌ی ممکن برای متنِ سفید: روشن‌ترین `tidalBgColor` مجاز.
   *
   * این عدد حدس نیست — جست‌وجوی کلِ بازه‌ی مجازِ `tidalBgColor` (روشنایی
   * [۰٫۱۲, ۰٫۲۰]، اشباع [۰٫۴۵, ۰٫۸۵]، همه‌ی هیوها) می‌دهد روشن‌ترین حالت
   * `[94, 94, 8]` است: اشباعِ اوج با روشناییِ اوج، روی هیوی زرد-سبز.
   *
   * همین تست در نسخه‌ی اولش با `[74, 74, 28]` نوشته شده بود و *سبز* بود،
   * در حالی که αهای آن‌موقع شیت روی همین `[94, 94, 8]` واقعی متنِ سفید را به
   * ۴٫۳۲ می‌رساندند — زیرِ AA. یعنی حدسِ خوش‌بینانه قرارداد را بی‌اعتبار کرده
   * بود بی‌آنکه چیزی سرخ شود. هر تغییری در این ثابت باید از همان جست‌وجو بیاید،
   * نه از یک سه‌گانه‌ی «تیره‌ی محتمل».
   */
  const worstSheetBg: RGB = [94, 94, 8]

  /*
   * کلیشه‌ی روشن‌ترین کاورِ ممکن. مشِ خام است (نه واشِ مهارشده)، پس یک کاورِ
   * تقریباً سفید روشن‌ترین حالت را می‌سازد. `dominantColor` پیکسل‌های بالای
   * ۲۳۵ را دور می‌ریزد، پس ۲۳۵ سقفِ واقعی است.
   */
  const brightestMesh: RGB = [235, 235, 235]

  it('keeps white text at AA anywhere on the sheet, with no scrim', () => {
    let worst = Infinity
    let where = ''
    for (let yi = 0; yi <= 40; yi++) {
      for (let xi = 0; xi <= 40; xi++) {
        const x = xi / 40
        const y = yi / 40
        const layers: ColorLayer[] = meshAuraAlphaAt(x, y)
          .map((alpha) => ({ rgb: brightestMesh, alpha }))
          .filter((l) => l.alpha > 0.001)
        const ratio = compositedContrast(WHITE, worstSheetBg, layers)
        if (ratio < worst) {
          worst = ratio
          where = `x=${x.toFixed(2)} y=${y.toFixed(2)}`
        }
      }
    }
    // برچسبِ گویا تا شکست بگوید کدام نقطه مقصر بوده
    expect({ where, ok: worst >= 4.5 }).toEqual({ where, ok: true })
  })

  it('keeps the aura peaks at or below the measured ceiling', () => {
    /*
     * سقفِ ۰٫۱۸ از همان جست‌وجوی بالا آمده، با حاشیه‌ی امن و نه روی مرز:
     * روی روشن‌ترین `tidalBgColor`، α=۰٫۲۰ متنِ سفید را دقیقاً روی ۴٫۵۰
     * می‌نشاند (پاس‌شدن با مویِ سر) و ۰٫۲۲ به ۴٫۳۲ می‌رساند. این پروژه
     * «دقیقاً روی AA» را قبول نمی‌کند — همان‌طور که `TEXT_GUARD_ALPHA` هم
     * «حاشیه‌ی امن روی AA» دارد — پس ۰٫۱۸ انتخاب شد که ۴٫۷۰ می‌دهد.
     */
    expect(Math.max(...Object.values(MESH_AURA_ALPHA))).toBeLessThanOrEqual(0.18)
  })
})

describe('accent contrast contract', () => {
  it('keeps the accent readable under --accent-fg for every cover', () => {
    // --accent-fg روی داکِ تینت‌شده #0b0b0b است (index.css:823)
    const accentFg: RGB = [11, 11, 11]
    for (const cover of COVERS) {
      const accent = pageTheme(cover, 's', 'dark').accent
      const m = accent.match(/rgb\((\d+) (\d+) (\d+)\) (\d+)%/)
      if (!m) throw new Error(`unexpected accent: ${accent}`)
      const [, r, g, b, pct] = m
      const w = (100 - Number(pct)) / 100
      const mixed: RGB = [
        Math.round(+r + (255 - +r) * w),
        Math.round(+g + (255 - +g) * w),
        Math.round(+b + (255 - +b) * w),
      ]
      expect(contrastRatio(mixed, accentFg)).toBeGreaterThanOrEqual(4.5)
    }
  })

  /*
   * قراردادِ اصلیِ صفحه‌های تم‌دار — تستی که باگِ تمِ روشن را می‌گیرد.
   *
   * قبلاً هیچ‌جا سنجیده نمی‌شد: تستِ بالا فقط `theme.accent` (مسیرِ نوار
   * پخش) را با inkِ مشکی می‌سنجید، در حالی که `tintAccent` مسیرِ صفحه‌های
   * هنرمند/آلبوم است و inkش باید هم‌تم عوض شود. نتیجه‌اش این بود که در تمِ
   * روشن متنِ دکمهٔ «پخش» کنتراستِ ۱٫۰ می‌گرفت (مشکیِ `#0d1a00` روی اکسنتِ
   * روشناییِ ≤۰٫۱۴) و کسی نمی‌فهمید.
   */
  it.each(['dark', 'light'] as const)(
    'keeps the page accent readable under its own ink in %s',
    (mode) => {
      for (const cover of COVERS) {
        const { tintAccent, ink } = pageTheme(cover, 's', mode)
        expect(contrastRatio(tintAccent, ink)).toBeGreaterThanOrEqual(4.5)
      }
    },
  )

  /*
   * اکسنت هم‌زمان *متن* هم هست (بج‌ها، لینک‌ها، آیکون‌ها) و آن‌ها روی پایهٔ
   * صفحه می‌نشینند. پس یک عدد باید هر دو نقش را هم‌زمان ارضا کند — و همین
   * است که بازهٔ مجاز را باریک می‌کند.
   */
  it.each(['dark', 'light'] as const)(
    'keeps the page accent readable as text on the page base in %s',
    (mode) => {
      for (const cover of COVERS) {
        const theme = pageTheme(cover, 's', mode)
        // متنِ رنگی روی پایه‌ی خودِ صفحه می‌نشیند (`--page-*`)، نه روی `--bg`
        expect(contrastRatio(theme.tintAccent, theme.page)).toBeGreaterThanOrEqual(4.5)
      }
    },
  )
})

describe('composite / compositedContrast', () => {
  it('is a no-op without layers', () => {
    expect(compositedContrast([0, 0, 0], [128, 128, 128], [])).toBeCloseTo(
      contrastRatio([0, 0, 0], [128, 128, 128]),
      10
    )
    expect(compositedContrast([128, 128, 128], [128, 128, 128], [])).toBe(1)
  })

  it('walks alpha-over in order', () => {
    const white = compositedContrast([0, 0, 0], [0, 0, 0], [{ rgb: [255, 255, 255], alpha: 1 }])
    expect(white).toBeCloseTo(21, 0)
  })
})

describe('pageThemeVars', () => {
  it('emits the registered triads plus the ready-made colour strings', () => {
    const vars = pageThemeVars(pageTheme([12, 200, 60], 's', 'dark')) as Record<string, string>
    expect(Object.keys(vars).sort()).toEqual([...KEYS, ...COLOR_KEYS].sort())
  })

  it('emits --accent-fg so tinted pages can re-ink their accent buttons', () => {
    /*
     * بدونِ این توکن، صفحهٔ تم‌دارِ روشن همان inkِ ثابتِ تم را می‌گرفت و متنِ
     * دکمهٔ پخش روی اکسنتِ تیره ناخوانا می‌شد — باگی که کلِ این قرارداد برای
     * گرفتنش نوشته شده است.
     */
    const dark = pageThemeVars(pageTheme([12, 200, 60], 's', 'dark')) as Record<string, string>
    const light = pageThemeVars(pageTheme([12, 200, 60], 's', 'light')) as Record<string, string>
    expect(dark['--accent-fg']).toBe('rgb(13 26 0)')
    expect(light['--accent-fg']).toBe('rgb(255 255 255)')
  })

  it('emits plain integers so rgb(var(--tint-r) ...) stays valid', () => {
    const vars = pageThemeVars(pageTheme([12, 200, 60], 's', 'dark')) as Record<string, string>
    for (const key of KEYS) {
      expect(vars[key]).toMatch(/^\d{1,3}$/)
      const n = Number(vars[key])
      expect(n).toBeGreaterThanOrEqual(0)
      expect(n).toBeLessThanOrEqual(255)
    }
  })

  it('separates the clamped wash from the raw mesh dominant', () => {
    const raw: RGB = [255, 255, 0]
    const vars = pageThemeVars(pageTheme(raw, 's', 'dark')) as Record<string, string>
    const wash: RGB = [
      Number(vars['--tint-r']),
      Number(vars['--tint-g']),
      Number(vars['--tint-b']),
    ]

    // مشِ خام دست‌نخورده می‌ماند — هویتِ اتمسفرِ «در حال پخش» همین است
    expect([vars['--mesh1-r'], vars['--mesh1-g'], vars['--mesh1-b']]).toEqual([
      '255',
      '255',
      '0',
    ])

    /*
     * واش مهار شده، ولی با *مقیاس‌کردن* و نه با خاکستری‌کردن: نسبتِ کانال‌ها
     * باید حفظ شود. عددِ ثابت این‌جا نمی‌آید — سقف یک پارامترِ تنظیمی است و
     * تست باید خاصیت را بسنجد، نه یک مقدارِ جادویی را.
     */
    expect(wash[0]).toBe(wash[1])
    expect(wash[2]).toBe(0)
    expect(wash[0]).toBeLessThan(raw[0])
    expect(relativeLuminance(wash)).toBeLessThanOrEqual(WASH_MAX_LUM)
  })

  it('gives a stable, memo-friendly object for the same theme', () => {
    const a = pageTheme([1, 2, 3], 's', 'dark')
    const b = pageTheme([1, 2, 3], 's', 'dark')
    expect(a.key).toBe(b.key)
    expect(pageThemeVars(a)).toEqual(pageThemeVars(b))
  })
})

/*
 * قراردادِ استایل‌شیت.
 *
 * دو عدد و یک نامِ متغیر بین این ماژول و `index.css` مشترک‌اند و هیچ‌کدام از
 * سمتِ کامپایلر چک نمی‌شوند: `TEXT_GUARD_ALPHA` فقط در تست مصرف می‌شود و آلفای
 * واقعی در CSS است. بدونِ این تست، عوض‌کردنِ آلفا در CSS می‌توانست بی‌صدا
 * قراردادِ کنتراستی که بالا سنجیده می‌شود را بی‌اعتبار کند.
 */
describe('stylesheet contract', () => {
  // متنِ *نوشته‌شده‌ی* استایل‌شیت، نه خروجیِ بیلد — چون قرارداد همان‌جاست
  const css = readFileSync(new URL('../index.css', import.meta.url), 'utf8')

  /*
   * همه‌ی قواعدِ یک سلکتور را برمی‌گرداند.
   *
   * `String.match` فقط *اولی* را می‌دهد و این فایل چند بار یک سلکتور را در
   * بلوک‌های شرطی تکرار می‌کند (`prefers-reduced-motion`). انتخابِ اولی یعنی
   * تست بی‌سروصدا قاعده‌ی اشتباه را می‌سنجد — همان اشتباهی که اولش رخ داد.
   */
  const rulesFor = (selector: string): string[] =>
    css.match(new RegExp(`${selector}\\s*\\{[^}]*\\}`, 'g')) ?? []

  /** قاعده‌ای که باید حاویِ `marker` باشد — تا تست هرگز قاعده‌ی اشتباه نگیرد. */
  const ruleWith = (selector: string, marker: string): string => {
    const found = rulesFor(selector).find((r) => r.includes(marker))
    expect(found, `no ${selector} rule containing "${marker}"`).toBeDefined()
    return found as string
  }

  it('registers every emitted token as an animatable <number>', () => {
    for (const token of KEYS) {
      const declaration = css.match(new RegExp(`@property\\s+${token}\\s*\\{[^}]*\\}`))?.[0]
      expect(declaration).toBeDefined()
      expect(declaration).toMatch(/syntax:\s*'<number>'/)
      expect(declaration).toMatch(/inherits:\s*true/)
    }
  })

  it('keeps the text guard alpha in step with TEXT_GUARD_ALPHA', () => {
    const rule = css.match(/\.tint-text-guard\s*\{[^}]*\}/)?.[0] ?? ''
    expect(rule).toContain(
      `rgb(var(--page-r) var(--page-g) var(--page-b) / ${TEXT_GUARD_ALPHA})`
    )
  })

  it('defines --bg-rgb for both themes', () => {
    expect(css).toMatch(/--bg-rgb:\s*7 7 7;/)
    expect(css).toMatch(/--bg-rgb:\s*247 247 245;/)
  })

  it('lists the tokens literally on both tint scopes', () => {
    for (const selector of ['.tint-scope', '.tint-scope-sheet']) {
      const rule = css.match(new RegExp(`\\${selector}\\s*\\{[^}]*\\}`))?.[0] ?? ''
      expect(rule).not.toBe('')
      for (const token of KEYS) expect(rule).toContain(token)
    }
  })

  it('never routes a transition list through var()', () => {
    /*
     * رگرسیونِ واقعی: فهرست یک‌بار در `--tint-ease` بود و
     * `transition: var(--tint-ease)`. Lightning CSS سرِ بیلد اعلانِ متغیر را از
     * `.tint-scope` حذف کرد ولی `transition` را دست‌نخورده گذاشت، پس گذارِ
     * هیروها نامعتبر و بی‌اثر می‌شد. تستِ منبع نمی‌تواند خودِ ترنسفورم را
     * ببیند، ولی می‌تواند جلوی برگشتنِ آن الگو را بگیرد.
     */
    for (const selector of ['.tint-scope', '.tint-scope-sheet']) {
      const rule = css.match(new RegExp(`\\${selector}\\s*\\{[^}]*\\}`))?.[0] ?? ''
      expect(rule).not.toMatch(/transition:\s*var\(/)
    }
  })

  /*
   * لایه‌ی پس‌زمینه‌ی تمام‌صفحه.
   *
   * چند چیز اینجا قفل می‌شود که هیچ تستِ DOM‌ای نمی‌تواند ببیند:
   *
   *  ۱. هندسه‌ی `fixed inset-0`: اگر کسی `position: static` کند، لایه فقط
   *     ارتفاعِ محتوا را می‌گیرد و دوباره «ناحیه‌ی مشکی» برمی‌گردد.
   *  ۲. `z-index: -1` به‌همراهِ `isolation` روی شل: زنجیره باید *داخلِ* شل
   *     مهار شود وگرنه لایه زیرِ `background`ِ `body` گم می‌شود. jsdom ترتیبِ
   *     نقاشی را نمی‌بیند، پس تنها راهِ گرفتنِ این رگرسیون خواندنِ متنِ CSS است.
   *  ۳. آلفاها آینه‌ی PAGE_RAMP_ALPHA بمانند — همان الگویی که
   *     TEXT_GUARD_ALPHA ↔ `.tint-text-guard` دارد.
   */
  describe('.page-tint', () => {
    // قاعده‌ی اصلی با نشانه‌ی هندسه‌اش از بلوکِ reduced-motion جدا می‌شود
    const rule = ruleWith('\\.page-tint', 'position: fixed')
    const active = ruleWith('\\.app-shell\\[data-page-tint\\]\\s*\\.page-tint', 'opacity: 1')
    const shell = ruleWith('\\.app-shell', 'isolation: isolate')

    it('exists and paints the registered page base', () => {
      expect(rule).toContain('rgb(var(--page-r) var(--page-g) var(--page-b))')
    })

    it('covers the whole viewport, not just the content column', () => {
      expect(rule).toContain('position: fixed')
      expect(rule).toContain('inset: 0')
      expect(rule).toContain('z-index: -1')
      // بدونِ این، لایه روی متن و کاورها می‌افتد
      expect(rule).toContain('pointer-events: none')
    })

    it('is inert until a themed page asks for it', () => {
      expect(rule).toContain('opacity: 0')
      expect(active).toContain('opacity: 1')
    })

    it('mirrors PAGE_RAMP_ALPHA', () => {
      /*
       * ایست‌های گرادیان باید آینه‌ی ثابت‌های TS بمانند. اگر کسی یکی را تنها
       * در CSS عوض کند، قراردادِ کنتراستی که بالا سنجیده می‌شود بی‌اعتبار
       * می‌شد بی‌آنکه تستی سرخ شود.
       */
      const { top, mid } = PAGE_RAMP_ALPHA.dark
      expect(rule).toContain(`/ ${top})`)
      expect(rule).toContain(`/ ${mid})`)
      // هر دو تمِ فعلی یک عدد دارند؛ اگر روزی جدا شدند، باید هر دو تست شوند
      expect(PAGE_RAMP_ALPHA.light).toEqual(PAGE_RAMP_ALPHA.dark)
    })

    it('keeps the shell isolated so the -1 layer cannot escape', () => {
      expect(shell).toContain('isolation: isolate')
    })

    it('disables its own fade when motion is reduced', () => {
      const reduced = ruleWith('\\.page-tint', 'transition: none')
      expect(reduced).toContain('transition: none')
    })
  })

  /*
   * «هیچ ناحیه‌ی مشکیِ خالی نمی‌ماند» به‌صورت اجراپذیر.
   *
   * سه لایه‌ی سطحِ صفحه (کفِ صفحه، گاردِ متنی، و خودِ پس‌زمینه) قبلاً به
   * `--bg` محو می‌شدند و همین‌ها بودند که پایینِ صفحه‌ها را مشکی می‌کردند.
   * حالا همه باید به پایه‌ی رنگی بروند. تست روی *متنِ* CSS کار می‌کند چون
   * jsdom نه رنگِ محاسبه‌شده را می‌دهد نه ترتیبِ نقاشی را.
   */
  describe('no page-level scrim falls back to the flat --bg', () => {
    it('fades the bottom scrim to the page base', () => {
      const src = readFileSync(new URL('../components/BottomFadeScrim.tsx', import.meta.url), 'utf8')
      expect(src).toContain('rgb(var(--page-r) var(--page-g) var(--page-b))')
      expect(src).not.toMatch(/color-mix\(in srgb, var\(--bg\)/)
    })

    it('fades the hero text guard to the page base', () => {
      const guard = css.match(/\.tint-text-guard\s*\{[^}]*\}/)?.[0] ?? ''
      expect(guard).not.toBe('')
      expect(guard).toContain('rgb(var(--page-r) var(--page-g) var(--page-b)')
      expect(guard).not.toContain('var(--bg-rgb)')
    })

    it('gives both themes their own page base, so unthemed pages stay in-theme', () => {
      /*
       * باگِ واقعی: `@property --page-*` مقدارِ اولیه‌ی ثابتِ ۷ داشت. مقدارِ
       * اولیه در زمانِ ثبت تجزیه می‌شود و نمی‌تواند `var()` باشد، پس در تمِ
       * روشن صفحه‌های بی‌تم (خانه، کتابخانه) گاردِ متنی و کفِ صفحه را به مشکی
       * محو می‌کردند — یک باگِ دیداری که هیچ تستِ رنگِ محاسبه‌شده نمی‌گرفت.
       * حالا هر بلوکِ تم توکنِ خودش را دارد.
       */
      const darkBlock = css.match(/:root,\s*\[data-theme='dark'\]\s*\{[^}]*\}/)?.[0] ?? ''
      const lightBlock = css.match(/\[data-theme='light'\]\s*\{[^}]*\}/)?.[0] ?? ''

      expect(darkBlock).toContain('--page-rgb: 7 7 7;')
      expect(darkBlock).toMatch(/--page-r:\s*7;/)
      expect(darkBlock).toMatch(/--page-g:\s*7;/)
      expect(darkBlock).toMatch(/--page-b:\s*7;/)

      expect(lightBlock).toContain('--page-rgb: 247 247 245;')
      expect(lightBlock).toMatch(/--page-r:\s*247;/)
      expect(lightBlock).toMatch(/--page-g:\s*247;/)
      expect(lightBlock).toMatch(/--page-b:\s*245;/)
    })

    it('never paints an opaque --bg behind the page tint', () => {
      /*
       * `--bg` باید فقط به‌عنوانِ بومِ سند و مقدارِ اولیه‌ی توکن‌ها بماند، نه
       * به‌عنوانِ پس‌زمینه‌ی یک لایه‌ی تمام‌صفحه.
       */
      const tint = css.match(/\.page-tint\s*\{[^}]*\}/)?.[0] ?? ''
      expect(tint).not.toContain('var(--bg)')
    })
  })
})
