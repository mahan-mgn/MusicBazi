const FA_DIGITS = ['۰', '۱', '۲', '۳', '۴', '۵', '۶', '۷', '۸', '۹']

/** تبدیل ارقام لاتین به فارسی */
export function fa(input: string | number): string {
  return String(input).replace(/\d/g, (d) => FA_DIGITS[Number(d)])
}

/** ارقام را فقط وقتی فارسی کن که زبان فارسی باشد */
export function digits(input: string | number, lang: string): string {
  return lang === 'fa' ? fa(input) : String(input)
}

/** ۳:۴۵ — و برای چیزی که از یک ساعت رد می‌شود، ۱:۱۲:۳۰ */
export function duration(ms: number, lang = 'fa'): string {
  // مدت‌زمانِ نامعلوم (NaN از `<audio>`ِ هنوز بارنشده) یا منفی نباید به شکل
  // «NaN:NaN» روی نوار پخش بنشیند
  const total = Number.isFinite(ms) ? Math.max(0, Math.round(ms / 1000)) : 0
  const h = Math.floor(total / 3600)
  const m = Math.floor(total / 60) % 60
  const s = total % 60
  // بخشِ ساعت فقط وقتی می‌آید که واقعاً باشد: «۰:۰۳:۴۵» برای یک آهنگ نویز
  // است، ولی بدونش میکسِ دوساعته «۱۲۰:۰۰» نشان داده می‌شد — که نه ساعت است
  // نه دقیقه، و روی نوار پخشِ همان میکس هم دیده می‌شود نه فقط در تکه‌کردن.
  const text = h
    ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
    : `${m}:${String(s).padStart(2, '0')}`
  return digits(text, lang)
}

export function percent(n: number, lang = 'fa'): string {
  return lang === 'fa' ? `${fa(Math.round(n))}٪` : `${Math.round(n)}%`
}

/** تشخیص اینکه ورودی کاربر لینک است یا عبارت جستجو */
export function isUrl(value: string): boolean {
  return /^https?:\/\//i.test(value.trim())
}

/**
 * لینکِ صفحه‌ی هنرمند یا کاربر — هر چیزی که به `/api/artist` می‌رود، نه
 * `/api/album`.
 *
 * بدونش هر لینکِ پیست‌شده به `/api/album` می‌رفت، حتی لینک هنرمند — که آنجا
 * شناخته نمی‌شود و ۴۰۴ می‌گیرد.
 *
 * «کاربر» هم همان‌جا می‌رود: صفحه‌ی کسی که هنرمند نیست و فقط پلی‌لیستِ عمومی
 * دارد (اسپاتیفای `user/`، دیزر `profile/`) همان قالبِ صفحه‌ی هنرمند را دارد.
 *
 * ساندکلاد و یوتیوب بخشِ ثابتی برای «هنرمند» ندارند و از روی شکلِ کلِ آدرس
 * تشخیص داده می‌شوند: پروفایلِ ساندکلاد دقیقاً یک بخش دارد (ترک و ست بیشتر
 * دارند) و کانالِ یوتیوب با `@`/`channel`/`c`/`user` شروع می‌شود و نه با
 * `watch` یا `playlist`.
 */
export function isArtistUrl(value: string): boolean {
  const url = value.trim()
  return (
    /music\.apple\.com\/[a-z]{2}\/artist\//i.test(url) ||
    /deezer\.com\/(?:[a-z]{2}\/)?(?:artist|profile)\//i.test(url) ||
    /open\.spotify\.com\/(?:intl-[a-z]{2}\/)?(?:artist|user)\//i.test(url) ||
    /^https?:\/\/(?:www\.|m\.)?soundcloud\.com\/[\w.-]+\/?(?:[?#].*)?$/i.test(url) ||
    /^https?:\/\/(?:www\.|m\.)?youtube\.com\/(?:@[\w.-]+|channel\/[\w-]+|c\/[\w.-]+|user\/[\w.-]+)(?:\/[a-z]+)?\/?(?:[?#].*)?$/i.test(
      url,
    )
  )
}

/** نام فایل امن برای ذخیره‌سازی */
export function safeFilename(name: string): string {
  return name.replace(/[\\/:*?"<>|]/g, '-').trim()
}

/**
 * سرور فرمت را به شکل «mp3 128» می‌دهد (فرمت واقعی، نه کیفیت درخواستی).
 * برای پسوند فایل فقط بخش اول لازم است.
 */
export function fileExt(format: string | undefined): string {
  return (format ?? 'mp3').split(' ')[0]
}

/**
 * برچسب فرمت با ارقام زبانِ فعلی، مثل «mp3 ۱۲۸».
 *
 * فقط بخش عددی فارسی می‌شود: «mp3» یک نامِ لاتین است و «mp۳» غلط است، نه ترجمه.
 */
export function formatLabel(format: string | undefined, lang = 'fa'): string {
  const [codec, ...rest] = (format ?? 'mp3').split(' ')
  return rest.length ? `${codec} ${digits(rest.join(' '), lang)}` : codec
}

const UNITS_FA = ['بایت', 'کیلوبایت', 'مگابایت', 'گیگابایت']
const UNITS_EN = ['B', 'KB', 'MB', 'GB']

/** حجم خوانا — «۴٫۲ مگابایت» */
export function bytes(n: number, lang = 'fa'): string {
  const units = lang === 'fa' ? UNITS_FA : UNITS_EN
  let value = Math.max(0, n)
  let step = 0
  while (value >= 1024 && step < units.length - 1) {
    value /= 1024
    step++
  }
  // زیر ۱۰ یک رقم اعشار می‌خواهد، بالاترش نویز است. «۱٫۰» هم نویز است.
  const text =
    value >= 10 || step === 0
      ? String(Math.round(value))
      : value.toFixed(1).replace(/\.0$/, '')
  return `${digits(text.replace('.', lang === 'fa' ? '٫' : '.'), lang)} ${units[step]}`
}

/** تاریخ کوتاه محلی از ثانیه‌ی یونیکس */
export function shortDate(seconds: number, lang = 'fa'): string {
  const locale = lang === 'fa' ? 'fa-IR' : 'en-US'
  try {
    return new Date(seconds * 1000).toLocaleDateString(locale, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  } catch {
    return ''
  }
}

/** ساعت و دقیقه — «۲۱:۴۰» — برای «آخرین پخش‌ها» کنارِ تاریخ */
export function clock(seconds: number, lang = 'fa'): string {
  const locale = lang === 'fa' ? 'fa-IR' : 'en-US'
  try {
    return new Date(seconds * 1000).toLocaleTimeString(locale, {
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return ''
  }
}

/**
 * تمیزکردن فاصله‌های زائد نام هنرمند (به‌خصوص فاصله‌های دور کاما و کامای تمام‌عرض در ساندکلاد)
 */
export function cleanArtist(artist: string | undefined | null): string {
  // ponytail: فقط نرمال‌سازی کاما و فاصله‌ها؛ جداسازی آرایه‌ای در صورت نیاز اضافه شود.
  if (!artist) return ''
  return artist
    .replace(/，/g, ',')
    .replace(/\s*([,،])\s*/g, '$1 ')
    .replace(/\s+/g, ' ')
    .trim()
}

