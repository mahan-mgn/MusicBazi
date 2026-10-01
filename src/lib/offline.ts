import type { LibraryItem } from './types'

/**
 * سنجاق‌کردنِ ترک برای پخشِ آفلاین.
 *
 * PWA از قبل شِلِ اپ را آفلاین بالا می‌آورد ولی خودِ صدا همیشه از شبکه می‌آمد —
 * یعنی در هواپیما یا آسانسور، کتابخانه‌ای که «روی دیسک است» پخش نمی‌شد. اینجا
 * فایل صوتی (به‌علاوه‌ی متن و کاورش) در Cache Storage می‌نشیند و سرویس‌ورکر
 * موقع پخش از همان‌جا سرو می‌کند — با پشتیبانی Range، وگرنه نوار جابه‌جایی
 * کار نمی‌کرد.
 *
 * همان نامِ کشی که `public/sw-offline.js` می‌خواند. نوشتن از سمتِ صفحه است چون
 * Cache API اینجا هم در دسترس است و رفت‌وبرگشتِ پیام با سرویس‌ورکر چیزی اضافه
 * نمی‌کرد.
 */
const CACHE = 'musicbazi-offline-v1'

export function supported(): boolean {
  return typeof caches !== 'undefined'
}

/**
 * از مرورگر می‌خواهد این فضا را جزو «ماندگار» حساب کند.
 *
 * بدونش، کشِ ما جزو فضای قابل‌دورانداختن است و مرورگر موقع کمبود جا بی‌خبر
 * پاکش می‌کند — دقیقاً همان چیزی که کاربر برای آفلاین بودن رویش حساب کرده.
 * جوابِ منفی مشکلی نیست؛ فقط تضمینی نداریم.
 */
async function requestPersistence(): Promise<void> {
  try {
    if (navigator.storage?.persist && !(await navigator.storage.persisted())) {
      await navigator.storage.persist()
    }
  } catch {
    // مرورگر پشتیبانی نمی‌کند — بی‌اهمیت
  }
}

/** آدرس‌هایی که برای آفلاین بودنِ یک ردیف لازم‌اند */
function assets(item: LibraryItem): { url: string; optional: boolean }[] {
  const list = [{ url: item.streamUrl, optional: false }]
  if (item.lyricsUrl) list.push({ url: item.lyricsUrl, optional: true })
  return list
}

export async function pin(item: LibraryItem): Promise<void> {
  if (!supported()) throw new Error('offline unsupported')
  await requestPersistence()
  const cache = await caches.open(CACHE)

  for (const asset of assets(item)) {
    try {
      await cache.add(asset.url)
    } catch (err) {
      // فایل صوتی نیامد یعنی سنجاق شکست خورده؛ متن آهنگ نیامد یعنی هیچ
      if (!asset.optional) throw err
    }
  }

  // `no-cors` نه `cache.add`: کاور در مرورگر از آینه‌ی محلیِ سرور می‌آید
  // (هم‌مبدأ، بی‌دردسر) ولی در اپِ اندروید همان آدرس مطلق و برون‌مبدأ است، و
  // اگر کسی آینه را خاموش کرده باشد مستقیم از CDNِ کاتالوگ می‌آید که CORS
  // ندارد. `cache.add` در آن دو حالت رد می‌شد. پاسخِ opaque را نمی‌شود خواند
  // ولی می‌شود ذخیره و دوباره سرو کرد، و `<img>` هم بیشتر از این نمی‌خواهد.
  const art = item.track.artworkUrl
  if (art) {
    try {
      await cache.put(art, await fetch(art, { mode: 'no-cors' }))
    } catch {
      // بدون کاور هم پخش می‌شود — Artwork گرادیانِ جایگزین را نشان می‌دهد
    }
  }
}

export async function unpin(item: LibraryItem): Promise<void> {
  if (!supported()) return
  const cache = await caches.open(CACHE)
  for (const asset of assets(item)) await cache.delete(asset.url)
  // کاور عمداً می‌ماند: ممکن است ترکِ سنجاق‌شده‌ی دیگری از همان آلبوم هنوز
  // به آن نیاز داشته باشد، و چند کیلوبایت تصویر ارزشِ ردگیری ندارد
}

/** آیا فایل صوتیِ این ردیف واقعاً در کش هست — منبعِ حقیقت، نه فهرستِ محلی */
export async function isPinned(item: LibraryItem): Promise<boolean> {
  if (!supported()) return false
  const cache = await caches.open(CACHE)
  return Boolean(await cache.match(item.streamUrl))
}

/**
 * حجمِ تقریبیِ چیزی که سنجاق شده.
 *
 * از `navigator.storage.estimate` نمی‌آید چون آن، کلِ سهمیه‌ی مبدأ را می‌گوید
 * (شاملِ پیش‌کشِ خودِ اپ)؛ اینجا فقط اندازه‌ی همان ردیف‌هایی جمع می‌شود که
 * کاربر خودش سنجاق کرده.
 */
export function pinnedBytes(items: LibraryItem[]): number {
  return items.reduce((sum, item) => sum + (item.bytes || 0), 0)
}

/** آدرس‌های کش‌شده — برای همگام‌کردنِ فهرستِ محلی با واقعیت */
export async function cachedUrls(): Promise<Set<string>> {
  if (!supported()) return new Set()
  const cache = await caches.open(CACHE)
  const keys = await cache.keys()
  return new Set(keys.map((request) => request.url))
}
