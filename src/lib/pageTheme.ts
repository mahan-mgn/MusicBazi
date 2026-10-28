/**
 * تمِ مشترکِ «بر پایه‌ی تصویر» برای صفحه‌های هنرمند، آلبوم و در حال پخش.
 *
 * این ماژول خالص است: نه DOM، نه React state، نه اثرِ جانبی. ورودی‌اش یک رنگِ
 * استخراج‌شده (یا `null`) به‌همراه یک سیدِ پایدار است، خروجی‌اش یک `PageTheme`
 * که همه‌ی سطح‌ها از همان یک منبع رنگ می‌گیرند.
 *
 * قراردادها:
 *
 * ۱. `tintAccent` برای اکسنت‌ها و کنترل‌هاست (توکنِ خروجیِ `--accent`) —
 *    روشنایی‌نرمال‌شده تا هم متنِ `ink` روی دکمه تضمینی باشد و هم خودش
 *    به‌عنوان متن روی پایهٔ صفحه خوانا بماند.
 * ۲. `wash` برای سطوحِ وسیعی است که متنِ تم رویشان می‌نشیند. رنگِ خامِ یک
 *    کاورِ روشن اگر بدونِ مهار روی هیرو برود، متن را ناخوانا می‌کند؛ پس
 *    روشنایی‌اش با `clampLuminance` سقف می‌خورد و hue دست‌نخورده می‌ماند.
 * ۳. `bg` پس‌زمینه‌ی عمیقِ شیتِ «در حال پخش» است (همان `tidalBgColor`).
 * ۴. `mesh` سه‌گانه‌ی هارمونیکِ اتمسفرِ نوری است و عمداً از رنگِ خام ساخته
 *    می‌شود تا هویتِ بصریِ موجودِ آن صفحه دست‌نخورده بماند.
 *
 * مقادیرِ رنگ به‌صورت متغیرهای CSS بیرون داده می‌شوند (`pageThemeVars`) و نه
 * به‌صورت رشته‌های رنگِ آماده. دلیلش `@property` است: سه‌گانه‌ی عددیِ ثبت‌شده
 * در CSS درون‌یابی می‌شود، در حالی که یک رشته‌ی `rgb(...)` گرادیان را در هر
 * فریم می‌پراند و ترنزیشنِ نرم نمی‌دهد.
 */

import type { CSSProperties } from 'react'
import {
  accentColor,
  clampLuminance,
  contrastRatio,
  deriveHarmonics,
  fallbackTint,
  hslToRgb,
  rgbToHsl,
  tidalBgColor,
  tintVars,
  type ColorPalette,
  type RGB,
} from './artColor'

/*
 * سقفِ روشناییِ رنگِ واشِ وسیع.
 *
 * این یک «سقف» است نه یک «هدف»: کاورهای معمولی دست‌نخورده می‌مانند و فقط
 * کاورهای سوخته (سفید یا زردِ خالص) کمی تاشده می‌شوند تا هیرو به یک تخته‌ی
 * سفیدِ تخت تبدیل نشود.
 *
 * اول ۰.۲۲ گذاشته شده بود، به‌خیالِ اینکه خواناییِ متن را تضمین می‌کند. غلط
 * بود و در عمل رنگ را کشت: روی زمینه‌ی تمِ تیره، واشِ کلیمپ‌شده آن‌قدر تیره
 * می‌شد که کاورِ روشن ۲۹٪ و کاورِ زرد ۴۵٪ از رنگش را از دست می‌داد. خوانایی
 * کارِ گاردِ متنی است، نه کارِ این عدد.
 */
export const WASH_MAX_LUM = 0.6

/** بیشترین آلفایی که واشِ هیرو در نقطه‌ی اوجش می‌رسد (رادیالِ بالای هیرو). */
export const WASH_MAX_ALPHA = 0.45

/**
 * آلفای گاردِ متنی در باندِ متن.
 *
 * گارد یک نوارِ هم‌رنگِ `--bg` روی پایینِ هیرو می‌کشد. عددش از قراردادِ
 * کنتراستِ همین ماژول بیرون آمده و حاشیه‌ی امن روی AA دارد.
 *
 * قبلاً ۰.۷ بود و تقریباً تمامِ ۶۰٪ پایینِ هیرو را مشکی می‌کرد — همان چیزی
 * که در تصویرِ واقعی رنگِ کاور را می‌خورد. کلاسش `.tint-text-guard` در
 * `index.css` است و مقدارش باید با آن یکی بماند.
 */
export const TEXT_GUARD_ALPHA = 0.52

export type ThemeMode = 'dark' | 'light'

/*
 * پایه‌ی ماتِ عمیقِ صفحه — رنگی، ولی هرگز مشکیِ مطلق.
 *
 * این همان چیزی است که «ناحیه‌ی مشکیِ خالی» را از بین می‌برد: به‌جای اینکه
 * پس‌زمینه یک `color-mix`ِ ۱۴٪ روی `--bg`ِ مشکی باشد (یعنی در نهایت ۸۶٪
 * مشکی)، یک رنگِ ماتِ کامل با هیوی *خودِ تصویر* می‌نشیند و `--bg` فقط جایی
 * می‌ماند که تصویری نیست.
 *
 * سقفِ روشنایی (`maxLum`) عمداً محافظه‌کارانه است. روی پایه‌ی مات، `--muted`
 * حداکثر تا روشناییِ ۰٫۰۵۹ جا دارد (کاورِ آبیِ خالص بدترین حالت است)؛ ۰٫۰۱۶
 * انتخاب شد تا پشتش رمپِ واش هم جا داشته باشد. اگر کسی این عدد را بالا ببرد،
 * تستِ قراردادِ رمپ در `pageTheme.test.ts` سرخ می‌شود — که همان هدف است.
 *
 * `neutral` برای کاورِ بی‌رنگ است (`s < 0.08`): هیوی دروغین نمی‌سازیم، ولی
 * حتی همان هم از `#070707` روشن‌تر است تا صفحه مشکی نماند.
 */
export const PAGE_BASE: Record<
  ThemeMode,
  { l: number; sMin: number; sMax: number; maxLum: number | null; neutral: RGB }
> = {
  dark: { l: 0.1, sMin: 0.42, sMax: 0.68, maxLum: 0.016, neutral: [22, 22, 24] },
  light: { l: 0.955, sMin: 0.16, sMax: 0.4, maxLum: null, neutral: [244, 244, 240] },
}

/**
 * پایه‌ی ماتِ صفحه از رنگِ تصویر: هیو دست‌نخورده، اشباع در بازه‌ی زنده،
 * روشنایی مهارشده.
 *
 * در دارک `clampLuminance` هم می‌نشیند چون `hslToRgb` با L ثابت روی هیوهای
 * زرد-سبز روشن‌ترین رنگ را می‌سازد و همان است که `--muted` را می‌شکند.
 */
export function pageBase(source: RGB, mode: ThemeMode): RGB {
  const cfg = PAGE_BASE[mode]
  const [h, s] = rgbToHsl(source[0], source[1], source[2])
  if (s < 0.08) return [...cfg.neutral]
  const hinted = hslToRgb(h, Math.min(cfg.sMax, Math.max(cfg.sMin, s)), cfg.l)
  return cfg.maxLum === null ? hinted : clampLuminance(hinted, cfg.maxLum)
}

/*
 * رمپِ واشِ کلِ صفحه.
 *
 * قبلاً یک واشِ تخت بود به‌علاوه‌ی یک گلوِ رادیالِ ۲۶rem؛ گلو در صفحه‌های
 * بلند به «نوار» تبدیل می‌شد و پایینش هیچ رنگی نداشت. رمپِ عمودی هر ارتفاعی
 * که بگیرد پوشش می‌دهد و شکلِ اسکرین‌شات‌های مرجع را می‌سازد: پررنگ در بالا،
 * محو تا `end`، و از آن‌جا به بعد پایه‌ی ماتِ رنگی تنها می‌ماند.
 *
 * `end = 0.72` یعنی «۷۲٪ ارتفاعِ دید»، و واحدش `dvh` است نه پیکسل: روی گوشیِ
 * کوتاه و تبلتِ بلند شکلِ یکسانی می‌دهد.
 *
 * عددها به همان دلیلِ `MESH_AURA_ALPHA` این‌جا در TS هستند و نه فقط inline در
 * CSS: تستِ کنتراست باید بتواند برای بدترین کاور و بدترین نقطه‌ی رمپ عدد
 * بگیرد، و اگر عدد و هندسه در JSX دستی تکرار می‌شد تست فقط نسخه‌ی خودش را
 * می‌سنجید.
 */
export const PAGE_RAMP_ALPHA: Record<ThemeMode, { top: number; mid: number }> = {
  dark: { top: 0.12, mid: 0.06 },
  light: { top: 0.12, mid: 0.06 },
}

/** موقعیتِ ایست‌های رمپ، به‌صورت کسری از ارتفاعِ دید. */
export const PAGE_RAMP_STOPS = { top: 0, mid: 0.4, end: 0.72 } as const

/** آلفای مؤثرِ رمپ در کسرِ `t` از ارتفاعِ دید (بیرونِ بازه → صفر). */
export function pageRampAlphaAt(mode: ThemeMode, t: number): number {
  const { top, mid } = PAGE_RAMP_ALPHA[mode]
  const { mid: at, end } = PAGE_RAMP_STOPS
  if (t <= 0) return top
  if (t >= end) return 0
  return t <= at ? top + (mid - top) * (t / at) : mid * (1 - (t - at) / (end - at))
}

/**
 * لایه‌های واشِ صفحه در نقطه‌ی `t` — روی پایه‌ی `theme.page`.
 *
 * همتای `compositedContrast` برای هیرو: وجودش برای این است که «متنِ پایینِ
 * صفحه خوانا می‌ماند» یک ادعای کامنتی نباشد و تست بتواند روی *همه‌ی* ارتفاعِ
 * رمپ عدد بگیرد — همان سوراخی که قراردادِ واشِ تختِ قبلی نداشت.
 */
export function pageRampLayers(theme: PageTheme, mode: ThemeMode, t: number): ColorLayer[] {
  const alpha = pageRampAlphaAt(mode, t)
  return alpha <= 0 ? [] : [{ rgb: theme.wash, alpha }]
}

/*
 * اکسنتِ تم — همان رنگِ فسفری/لیموییِ رابط، ولی از تصویر.
 *
 * دو مصرفِ متضاد دارد و همین عددها را تعیین می‌کند:
 *
 *  ۱. **پس‌زمینهٔ دکمه** با متنِ `ACCENT_INK`. متنِ روی دکمه باید با رنگِ
 *     همان دکمه کنتراست داشته باشد.
 *  ۲. **متنِ رنگی روی پس‌زمینهٔ صفحه** (بج‌ها، لینک‌ها). پس نباید به پایهٔ
 *     تیره نزدیک شود.
 *
 * هر دو شرط فقط تابعِ روشنایی‌اند (کنتراستِ WCAG تنها به luminaceِ نسبی
 * وابسته است)، پس یک بازهٔ باریکِ مجاز می‌سازند. برای تمِ تیره (`--fg`
 * روشن است) اکسنت باید در میانه قرار بگیرد تا هم متنِ تیره روی دکمه‌اش
 * خوانا باشد و هم خودش به‌عنوان متن روی پایهٔ #070707. برای تمِ روشن اکسنت
 * باید تیره بماند تا متنِ سفید روی دکمه‌اش خوانا باشد.
 *
 * عددها از اسکنِ بدترین کاورها آمده‌اند (تستِ کنتراست اجراپذیرش می‌کند):
 * در تیره هدفِ ۰٫۳۰ بدترین مشکی روی دکمه را ۶٫۰۱ و بدترین متن روی پایه را
 * ۶٫۷۱ می‌دهد — حاشیهٔ یک‌سوم بالای AA. هدفِ ۰٫۶۲ (عددِ قبلی) هم رد می‌شد
 * ولی دکمه را پاستلی می‌کرد: اکسنت تا روشناییِ ۰٫۶۲ که برود، اشباع
 * ادراکی‌اش را از دست می‌دهد و رنگِ کاور دیگر دیده نمی‌شود. در روشن سقفِ
 * ۰٫۱۴ بدترین سفید روی دکمه را ۵٫۵۳ و بدترین متن روی پایه را ۵٫۱۵ می‌دهد؛
 * ۰٫۱۸ سفید روی دکمه را به ۴٫۱۸ می‌آورد.
 */
export const ACCENT_LUM: Record<ThemeMode, { target?: number; cap?: number }> = {
  dark: { target: 0.3 },
  light: { cap: 0.14 },
}

/**
 * رنگِ متن/آیکونِ روی اکسنت — «ink».
 *
 * چرا لازم است و چرا از خودِ تم می‌آید: `--accent-fg`ِ ثابتِ تم برای تمِ
 * تیره و روشن هر دو `#0d1a00` (سبزِ تقریباً سیاه) است. آن مقدار برای
 * لیموییِ ثابتِ `#9fd117` درست است (کنتراست ۹٫۹۶)، ولی روی اکسنتِ تم‌دارِ
 * تمِ روشن فاجعه است: اکسنت آن‌جا روشناییِ ≤۰٫۱۴ دارد و مشکیِ رویش کنتراستِ
 * ۱٫۰ می‌دهد — یعنی متنِ دکمه‌ی «پخش» عملاً ناپدید می‌شد.
 *
 * تمِ روشن inkِ سفید می‌خواهد (بدترین حالت ۵٫۵۳ روی همهٔ رنگ‌های ممکن) و
 * تمِ تیره همان inkِ تیره را نگه می‌دارد (بدترین ۸٫۵۸). این توکن فقط روی
 * صفحه‌های تم‌دار بازنویسی می‌شود؛ صفحه‌های بی‌تم اکسنتِ ثابت را نگه
 * می‌دارند و باید همان inkِ ثابتِ تم را هم نگه دارند — روی `#9fd117`ِ تمِ
 * روشن، inkِ سفید کنتراستِ ۱٫۸۱ می‌داد.
 */
export const ACCENT_INK: Record<ThemeMode, RGB> = {
  dark: [13, 26, 0],
  light: [255, 255, 255],
}

/**
 * رنگِ اکسنت از رنگِ تصویر.
 *
 * از `source` (رنگِ خام) ساخته می‌شود نه `wash`: واش عمداً روشنایی‌مهارشده
 * است تا متنِ سفید رویش خوانا بماند و اگر اکسنت از آن بیاید در تمِ روشن
 * تقریباً سیاه می‌شود.
 */
export function pageAccent(source: RGB, mode: ThemeMode): RGB {
  if (mode === 'dark') return accentColor(source, ACCENT_LUM.dark.target as number)
  return clampLuminance(source, ACCENT_LUM.light.cap as number)
}

export interface PageTheme {
  /**
   * کلیدِ پایدارِ تم — پیوسته به سه‌گانه‌ی رنگِ مبنا، نه به شیء.
   *
   * مصرف‌کننده‌ها با همین کلید memo می‌کنند؛ بدونِ آن هر رندر یک شیءِ تازه
   * می‌سازد و `useMemo` هرگز hit نمی‌شود.
   */
  key: string
  /** رنگی که واقعاً از تصویر درآمد؛ `null` یعنی تم از سید آمده است. */
  extracted: RGB | null
  /** رنگِ مبنای محاسبات (استخراج‌شده یا جایگزینِ قطعیِ سید). */
  source: RGB
  /** واشِ امن برای سطوحِ وسیع — روشنایی‌مهارشده. */
  wash: RGB
  /** پایه‌ی ماتِ عمیقِ صفحه — رنگی ولی هرگز مشکیِ مطلق. */
  page: RGB
  /** اکسنتِ رابط از رنگِ تصویر — جای فسفری/لیموییِ تمِ ثابت. */
  tintAccent: RGB
  /** رنگِ متن/آیکونِ روی اکسنت — با تم عوض می‌شود، برخلافِ `--accent-fg`ِ ثابت. */
  ink: RGB
  /** سه‌گانه‌ی اتمسفرِ نوری. */
  mesh: ColorPalette
  /** رشته‌ی آماده‌ی `color-mix` برای اکسنتِ تم. */
  accent: string
  /** رشته‌ی آماده‌ی `background-color` شیتِ در حال پخش. */
  bg: string
}

/**
 * ساختِ تم از یک رنگِ استخراج‌شده.
 *
 * `extracted === null` یعنی استخراج نشد (کاور نبود، ۴۰۴ بود، یا بوم tainted
 * شد) → جایگزینِ قطعیِ `fallbackTint(seed)` می‌نشیند تا صفحه هرگز خاکستریِ
 * بی‌روح یا بی‌رنگ نماند.
 *
 * `mode` اجباری است و نه با پیش‌فرض: پایه‌ی صفحه در دو تم دو رنگِ کاملاً
 * متفاوت است و یک پیش‌فرضِ خاموش یعنی فراموشیِ پاس‌دادنش هیچ‌جا سرخ نمی‌شود.
 */
export function pageTheme(extracted: RGB | null, seed: string, mode: ThemeMode): PageTheme {
  const source = extracted ?? fallbackTint(seed)
  const triad = `${source[0]} ${source[1]} ${source[2]}`
  return {
    key: `${extracted ? 'art' : 'seed'}:${triad}:${mode}`,
    extracted,
    source,
    wash: clampLuminance(source, WASH_MAX_LUM),
    page: pageBase(source, mode),
    tintAccent: pageAccent(source, mode),
    ink: ACCENT_INK[mode],
    mesh: deriveHarmonics(source),
    accent: tintVars(source).strong,
    bg: tidalBgColor(source),
  }
}

/**
 * متغیرهای CSS تم برای گذاشتن روی ریشه‌ی هر ویو.
 *
 * پانزده سه‌گانه‌ی عددی لازم است، و هر سه‌گانه‌اش دلیلی دارد: واشِ صفحه باید
 * مهارشده باشد، پایه‌ی عمیقِ صفحه باید مات و در عینِ حال رنگی باشد (نه
 * `--bg`ِ مشکی)، و اتمسفرِ نوریِ «در حال پخش» باید رنگِ خامِ خودش را نگه دارد
 * — اگر یکی شوند، یا خواناییِ هیرو یا هویتِ بصریِ شیت قربانی می‌شود.
 *
 * به‌علاوه سه رشته‌ی آماده: `--accent` و `--accent-dim` و `--accent-fg`.
 * این‌ها در CSS به‌صورت `<number>` ثبت نشده‌اند و ترنزیشن نمی‌گیرند؛ فقط
 * سه‌گانه‌ها انیمیت می‌شوند.
 */
export function pageThemeVars(theme: PageTheme): CSSProperties {
  const { wash, mesh, page, tintAccent, ink } = theme
  return {
    /* اکسنت به‌صورت رشته‌ی آماده: `--accent` خودش یک توکنِ نهایی است، نه
       سه‌گانه‌ای که کسی در CSS باز ترکیبش کند. */
    '--accent': `rgb(${tintAccent[0]} ${tintAccent[1]} ${tintAccent[2]})`,
    '--accent-dim': `rgb(${tintAccent[0]} ${tintAccent[1]} ${tintAccent[2]} / 0.16)`,
    /*
     * inkِ روی اکسنت باید هم‌تم عوض شود، وگرنه در تمِ روشن متنِ دکمه‌ها
     * ناخوانا می‌شود (توضیح در `ACCENT_INK`). فقط روی همین عنصرِ تم‌دار
     * نوشته می‌شود، پس صفحه‌های بی‌تم همان `--accent-fg`ِ ثابتِ تم را
     * نگه می‌دارند که روی لیموییِ ثابت درست است.
     */
    '--accent-fg': `rgb(${ink[0]} ${ink[1]} ${ink[2]})`,
    '--tint-r': String(wash[0]),
    '--tint-g': String(wash[1]),
    '--tint-b': String(wash[2]),
    '--page-r': String(page[0]),
    '--page-g': String(page[1]),
    '--page-b': String(page[2]),
    '--mesh1-r': String(mesh.dominant[0]),
    '--mesh1-g': String(mesh.dominant[1]),
    '--mesh1-b': String(mesh.dominant[2]),
    '--mesh2-r': String(mesh.secondary[0]),
    '--mesh2-g': String(mesh.secondary[1]),
    '--mesh2-b': String(mesh.secondary[2]),
    '--mesh3-r': String(mesh.accent[0]),
    '--mesh3-g': String(mesh.accent[1]),
    '--mesh3-b': String(mesh.accent[2]),
  } as CSSProperties
}

/** یک لایه‌ی نیمه‌شفاف روی زمینه. */
export interface ColorLayer {
  rgb: RGB
  alpha: number
}

/** ترکیبِ alpha-over روی یک زمینه‌ی مات، به ترتیبِ لایه‌ها. */
export function composite(base: RGB, layers: readonly ColorLayer[]): RGB {
  const out: RGB = [base[0], base[1], base[2]]
  for (const layer of layers) {
    for (let i = 0; i < 3; i++) {
      out[i] = Math.round(out[i] * (1 - layer.alpha) + layer.rgb[i] * layer.alpha)
    }
  }
  return out
}

/**
 * نسبتِ کنتراستِ متنِ تم روی باندِ متنی، پس از سوارکردنِ همه‌ی لایه‌ها.
 *
 * وجودش برای این است که قراردادِ خوانایی *اجراپذیر* شود: به‌جای این‌که در
 * کامنت بنویسیم «متن خوانا می‌ماند»، تست می‌تواند برای بدترین کاورِ ممکن
 * عدد را بگیرد و بیفتد.
 */
export function compositedContrast(
  fg: RGB,
  base: RGB,
  layers: readonly ColorLayer[],
): number {
  return contrastRatio(fg, composite(base, layers))
}

/*
 * اوجِ آلفای سه گرادیانِ اتمسفرِ شیتِ «در حال پخش» (`--mesh1/2/3`).
 *
 * اینجا در TS است و نه فقط inline در JSX، چون شیت از وقتی که scrimهای تیره
 * برداشته شد **هیچ لایه‌ی تاریک‌کننده‌ای ندارد**: خواناییِ متنِ سفید کاملاً به
 * `tidalBgColor` (روشنایی ۰٫۱۲–۰٫۲۰) به‌علاوه‌ی همین سه عدد تکیه دارد.
 * عددِ جادوییِ inline یعنی هیچ‌چیز جلوی بالا بردنش را نمی‌گیرد؛ اینجا تستِ
 * کنتراست در `NowPlaying.dom.test.tsx` رویشان عدد می‌گیرد.
 *
 * موقعیت و شعاعِ گرادیان‌ها عمداً اینجا نیست — آنها بخشی از چیدمان‌اند و در
 * JSX می‌مانند؛ تست هندسه‌شان را آینه می‌کند، همان کاری که با توکن‌های تم در
 * `pageTheme.test.ts` می‌شود.
 */
export const MESH_AURA_ALPHA = { dominant: 0.18, secondary: 0.14, accent: 0.1 } as const

/*
 * هندسه‌ی همان سه گرادیان، به‌صورت نسبی (۰ تا ۱ نسبت به کادرِ شیت).
 *
 * از JSX اینجا آورده شد تا تستِ کنتراست بتواند «بدترین نقطه‌ی روی صفحه» را
 * واقعاً پیدا کند، نه اینکه همه‌ی گرادیان‌ها را روی هم در یک نقطه فرض کند.
 * آن فرضِ محافظه‌کارانه تست را به سمتِ نتیجه‌ی غلط می‌برد: چون سه مرکز
 * (۵۰٪/۱۵٪، ۸۵٪/۸۵٪، ۱۵٪/۷۵٪) از هم دورند، عملاً هیچ‌جا هر سه با اوجِ
 * خودشان روی هم نمی‌افتند.
 *
 *   cx, cy: مرکز · rx, ry: شعاع · stop: کسری از شعاع که گرادیان به شفاف می‌رسد
 */
export const MESH_AURA_GEOMETRY = [
  { cx: 0.5, cy: 0.15, rx: 0.85, ry: 0.65, stop: 0.75 },
  { cx: 0.85, cy: 0.85, rx: 0.7, ry: 0.55, stop: 0.65 },
  { cx: 0.15, cy: 0.75, rx: 0.6, ry: 0.5, stop: 0.6 },
] as const

/** آلفای مؤثرِ اتمسفر در نقطه‌ی (x, y) — نسبتِ نسبیِ کادرِ شیت. */
export function meshAuraAlphaAt(x: number, y: number): number[] {
  const peaks = [
    MESH_AURA_ALPHA.dominant,
    MESH_AURA_ALPHA.secondary,
    MESH_AURA_ALPHA.accent,
  ]
  return MESH_AURA_GEOMETRY.map((g, i) => {
    const t = Math.hypot((x - g.cx) / g.rx, (y - g.cy) / g.ry)
    return t >= g.stop ? 0 : peaks[i] * (1 - t / g.stop)
  })
}

/**
 * رشته‌ی `background` اتمسفرِ نوری.
 *
 * از همان ثابت‌های بالاست تا CSS و تست نتوانند از هم واگرا شوند — اگر عدد و
 * هندسه در JSX دستی تکرار می‌شد، تست فقط نسخه‌ی خودش را می‌سنجید و تغییرِ
 * واقعیِ صفحه بی‌آنکه کسی بفهمد از قرارداد رد می‌شد.
 */
export function meshAuraBackground(): string {
  const peaks = [
    MESH_AURA_ALPHA.dominant,
    MESH_AURA_ALPHA.secondary,
    MESH_AURA_ALPHA.accent,
  ]
  return MESH_AURA_GEOMETRY.map(
    (g, i) =>
      `radial-gradient(ellipse ${g.rx * 100}% ${g.ry * 100}% at ${g.cx * 100}% ${g.cy * 100}%, ` +
      `rgb(var(--mesh${i + 1}-r) var(--mesh${i + 1}-g) var(--mesh${i + 1}-b) / ${peaks[i]}), transparent ${g.stop * 100}%)`,
  ).join(', ')
}
