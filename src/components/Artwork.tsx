import { useState, type CSSProperties } from 'react'

interface Props {
  src: string | null
  alt: string
  /** برای تولید رنگ پایدار وقتی کاور واقعی نداریم */
  seed: string
  className?: string
  rounded?: string
  /** استایل اضافه — بک‌دراپ با opacity کمتر از خودش استفاده می‌کند */
  style?: CSSProperties
  /**
   * نامِ عنصرِ مشترکِ View Transitions. فقط پخش‌کننده استفاده‌اش می‌کند تا
   * کاورِ مینی‌پلیر به کاورِ نمای کامل تبدیل شود — و در هر لحظه باید دقیقاً
   * *یک* عنصر روی صفحه این نام را داشته باشد، وگرنه مرورگر کلِ گذار را
   * کنار می‌گذارد.
   */
  transitionName?: string
}

const PALETTES = [
  ['#5b4bd6', '#8f7bff'],
  ['#2f6f4e', '#7ec98f'],
  ['#8a3b2e', '#e0836b'],
  ['#2b5d7a', '#7fc0e0'],
  ['#6b4226', '#c99a6b'],
  ['#4a4a4a', '#9a9a9a'],
  ['#7a2f5d', '#d97bb0'],
  ['#3d5a2b', '#a3c96b'],
]

function hash(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0
  return h
}

/**
 * آدرسِ نسخه‌ی بلورشده‌ی سمتِ سرورِ یک کاور (`/api/art-blur/<sha>`).
 *
 * بلورِ زنده‌ی CSS روی لایه‌ای به بزرگیِ ویوپورت هر فریم گران است و بین
 * موتورهای رندر هم یک‌دست درنمی‌آید؛ سرور یک‌بار با ffmpeg می‌سازد و کش
 * می‌کند. برای کاورِ غیرمحلی (CDN) یا نبودِ آدرس، `null` — یعنی مصرف‌کننده
 * باید به CSS blur برگردد.
 */
export function artBlurUrl(src: string | null): string | null {
  if (!src) return null
  return src.includes('/api/art/') ? src.replace('/api/art/', '/api/art-blur/') : null
}

/** حرف اول عنوان — برای فارسی هم درست کار می‌کند */
function initial(text: string): string {
  const clean = text.trim().replace(/^[^\p{L}\p{N}]+/u, '')
  return clean.slice(0, 1).toUpperCase() || '♪'
}

/**
 * پس‌زمینهٔ بلورشدهٔ همان artwork پشتِ کارت — نسخهٔ بزرگ و محوِ تصویر که کلِ
 * کارت را رنگ می‌گیرد. از خودِ `Artwork` استفاده می‌کند تا فالبکِ گرادیانی و
 * کاورِ شکسته هم همین‌جا درست behave کنند.
 */
export function ArtBackdrop({ src, seed, className = 'rounded-xl' }: {
  src: string | null
  seed: string
  /** هیروهای تمام‌صفحه «rounded-none» می‌دهند؛ لبه‌ها با خودِ ظرفِ overflow-hidden بریده می‌شوند */
  className?: string
}) {
  return (
    <span
      aria-hidden
      className={`pointer-events-none absolute inset-0 overflow-hidden ${className}`}
    >
      <Artwork
        src={src}
        alt=""
        seed={seed}
        rounded=""
        className="size-full scale-125 object-cover opacity-50 brightness-90 blur-2xl"
      />
    </span>
  )
}

/**
 * پس‌زمینهٔ هیرو: همان artwork بلورشده، ولی با سه لایهٔ کنترل‌شده رویش تا هم
 * شیک بماند هم متن همیشه خوانا باشد:
 *
 *  ۱. خودِ blur — یک‌بار سمتِ سرور با ffmpeg ساخته می‌شود (`/api/art-blur/<sha>`)
 *     تا همه‌ی مرورگرها پیکسل‌به‌پیکسل یک blur ببینند؛ آدرسِ CDN یا ۴۰۴ِ سرور
 *     به فالبکِ گرادیانیِ Artwork برمی‌گردد.
 *  ۲. scrimِ تیرهٔ یکنواخت — روشناییِ کاورِ روشن را مهار می‌کند (کنتراستِ متن)
 *  ۳. محو به رنگِ صفحه در پایین — لبهٔ تیزِ «پاسته‌شده» حذف می‌شود؛ هیرو داخلِ
 *     خودِ صفحه حل می‌شود نه اینکه یک مستطیلِ بریده تمام شود.
 *
 * لبه‌های بالا/چپ/راست هم به‌جای قطعِ ناگهانی، با همین scrim نرم می‌شوند.
 */
export function HeroBackdrop({ src, seed, rounded = '' }: { src: string | null; seed: string; /** کارتِ گردِ آرتیست «rounded-2xl» می‌دهد؛ هیروی آلبوم با محوِ صفحه، بدون گوشه */ rounded?: string }) {
  // بلورِ سمتِ سرور: همان کاور یک‌بار در سرور بلور می‌شود و همه‌ی مرورگرها
  // همان فایل را می‌بینند — CSS blur بین موتورها کمی متفاوت رندر می‌شود.
  // آدرسِ غیرمحلی (CDN در حالتِ بی‌آینه) به CSS blur برمی‌گردد.
  const blurred = artBlurUrl(src)
  return (
    <span
      aria-hidden
      className={`pointer-events-none absolute inset-0 overflow-hidden ${rounded}`}
    >
      <Artwork
        src={blurred ?? src}
        alt=""
        seed={seed}
        rounded=""
        className="size-full scale-150 object-cover"
      />
      {/* مهارِ روشنایی + یکدست‌کردنِ لکه‌های ناهموار کاورهای پرکنتراست */}
      <span className="absolute inset-0 bg-bg/25" />
      {/* از بالا فقط تینتِ ملایمِ صفحه برای نرمی — تهِ باند باید کاملاً خودِ artwork بماند */}
      <span
        className="absolute inset-0"
        style={{
          background:
            'linear-gradient(to bottom, color-mix(in srgb, var(--bg) 45%, transparent) 0%, transparent 25%, transparent 100%)',
        }}
      />
      {/* پشتِ متن همیشه تیره‌تر از خودِ blur — خوانایی مستقل از روشناییِ کاور */}
      <span
        className="absolute inset-0"
        style={{
          background:
            'linear-gradient(to left, transparent 45%, color-mix(in srgb, var(--bg) 30%, transparent) 80%)',
        }}
      />
    </span>
  )
}

export default function Artwork({
  src,
  alt,
  seed,
  className = '',
  rounded = 'rounded-lg',
  transitionName,
  style: extraStyle,
}: Props) {
  /*
   * کاوری که آدرس دارد ولی لود نمی‌شود.
   *
   * تا الان فالبکِ گرادیانیِ زیر فقط وقتی می‌آمد که آدرسی *نباشد*. ولی
   * کاورها از پنج منبعِ مختلف می‌آیند و لینکِ منقضی، ۴۰۳ و دامنه‌ی
   * فیلترشده بینشان عادی است — و نتیجه‌اش آیکونِ شکسته‌ی خودِ مرورگر بود،
   * که از یک کاورِ نداشته هم بدتر به‌نظر می‌رسد.
   *
   * خودِ آدرس ذخیره می‌شود نه یک پرچمِ بولی: با عوض‌شدنِ ترک، `src` جدید
   * دوباره شانسِ خودش را دارد، بدون افکت و بدون ریست‌کردنِ دستی.
   */
  const [brokenSrc, setBrokenSrc] = useState<string | null>(null)
  const style = extraStyle
    ? { ...(transitionName ? { viewTransitionName: transitionName } : {}), ...extraStyle }
    : transitionName
      ? { viewTransitionName: transitionName }
      : undefined

  if (src && src !== brokenSrc) {
    return (
      <img
        src={src}
        alt={alt}
        loading="lazy"
        // رمزگشاییِ تصویر روی نخِ اصلی، اسکرولِ لیستی که ده‌ها کاور دارد را
        // تکه‌تکه می‌کند
        decoding="async"
        onError={() => setBrokenSrc(src)}
        style={style}
        // img به‌صورت پیش‌فرض inline است؛ بدون block، اندازه‌ی واقعی‌اش گاهی
        // با اندازه‌ی جعبه‌ی تعیین‌شده توسط کلاس‌ها (مخصوصاً کنار aspect-square)
        // یکی نمی‌شود — مخصوصاً وقتی بارگذاری تصویر ناموفق است
        className={`${className} ${rounded} block object-cover bg-panel-2`}
      />
    )
  }

  const [from, to] = PALETTES[hash(seed) % PALETTES.length]
  return (
    <div
      role="img"
      aria-label={alt}
      className={`${className} ${rounded} grid place-items-center select-none overflow-hidden`}
      style={{
        ...style,
        background: `linear-gradient(140deg, ${from}, ${to})`,
        containerType: 'inline-size',
      }}
    >
      <span
        className="font-black text-white/80"
        // cqw تا حرف همیشه نسبت به اندازه‌ی خودِ کاور مقیاس بخورد، نه فونت والد
        style={{ fontSize: '44cqw', lineHeight: 1 }}
      >
        {initial(alt)}
      </span>
    </div>
  )
}
