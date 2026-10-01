/* eslint-disable no-undef */
/**
 * لایه‌ی آفلاینِ کتابخانه — کنارِ سرویس‌ورکری که Workbox می‌سازد.
 *
 * این فایل با `importScripts` بالای همان سرویس‌ورکر می‌نشیند، پس شنونده‌ی
 * `fetch`ِ آن *اول* اجرا می‌شود. عمداً فقط دو نوع درخواست را برمی‌دارد و بقیه
 * را دست‌نخورده به Workbox می‌سپارد:
 *
 *   ۱. استریمِ فایل‌های سنجاق‌شده (`/api/downloads/{id}/stream`)
 *   ۲. کاور — چه از آینه‌ی محلیِ سرور (`/api/art/...`) چه مستقیم از CDNِ
 *      کاتالوگ‌ها؛ فقط اگر از قبل کش شده باشد
 *
 * پاسخ‌دادن به همه‌چیز، پیش‌کشِ خودِ اپ را که کارِ Workbox است می‌شکست.
 *
 * ذخیره‌سازی از سمتِ صفحه انجام می‌شود (`lib/offline.ts` با همین نامِ کش)؛
 * اینجا فقط خواندن است. دلیلش این است که Cache API در خودِ صفحه هم در دسترس
 * است و رفت‌وبرگشتِ پیام با سرویس‌ورکر چیزی اضافه نمی‌کرد.
 */

const OFFLINE_CACHE = 'musicbazi-offline-v1'
const STREAM_PATTERN = /^\/api\/downloads\/[^/]+\/stream$/

/**
 * کاور از آینه‌ی محلیِ سرور.
 *
 * تا وقتی کاور مستقیم از CDNِ کاتالوگ می‌آمد، شرطِ «برون‌مبدأ»ی پایین برش
 * می‌داشت. حالا در مرورگر هم‌مبدأ است و بدون این الگو، کاورِ ترکِ سنجاق‌شده
 * سرِ راه به پیش‌کشِ Workbox می‌رفت — که آن را ندارد — و در حالتِ کاملاً
 * آفلاین گم می‌شد. در اپِ اندروید همچنان برون‌مبدأ است و از همان شرطِ پایین
 * رد می‌شود.
 */
const ART_PATTERN = /^\/api\/art\/[0-9a-f]+$/

/**
 * تکه‌ی خواسته‌شده از یک فایلِ کش‌شده.
 *
 * بدون این، جابه‌جایی روی نوار پخش کار نمی‌کرد: `<audio>` برای هر seek یک
 * درخواستِ Range می‌فرستد و مرورگر پاسخِ ۲۰۰ کامل را به‌عنوان جوابِ Range
 * قبول نمی‌کند. کلِ فایل در حافظه خوانده می‌شود چون Cache API بدنه‌ی جزئی
 * نمی‌دهد — برای یک ترکِ چندمگابایتی قابل قبول است.
 */
function sliceResponse(response, rangeHeader, buffer) {
  const total = buffer.byteLength
  const match = /bytes=(\d*)-(\d*)/.exec(rangeHeader)
  if (!match) return response

  // `bytes=-500` یعنی «۵۰۰ بایتِ آخر»، نه «از صفر تا ۵۰۰». با خواندنِ ساده‌ی
  // دو گروه، آن حالت به بازه‌ی اولِ فایل تبدیل می‌شد و پلیر تکه‌ی اشتباه
  // می‌گرفت — بعضی مرورگرها دقیقاً همین شکل را برای خواندنِ تریلرِ فایل
  // (اتمِ moov در m4a) می‌فرستند.
  const hasStart = match[1] !== ''
  const hasEnd = match[2] !== ''
  const suffix = !hasStart && hasEnd
  const start = suffix ? Math.max(0, total - Number(match[2])) : hasStart ? Number(match[1]) : 0
  const end = suffix || !hasEnd ? total - 1 : Number(match[2])
  if (!hasStart && !hasEnd) {
    return new Response(null, {
      status: 416,
      headers: { 'content-range': `bytes */${total}` },
    })
  }
  if (Number.isNaN(start) || Number.isNaN(end) || start > end || start >= total) {
    return new Response(null, {
      status: 416,
      headers: { 'content-range': `bytes */${total}` },
    })
  }

  const last = Math.min(end, total - 1)
  return new Response(buffer.slice(start, last + 1), {
    status: 206,
    statusText: 'Partial Content',
    headers: {
      'content-type': response.headers.get('content-type') || 'application/octet-stream',
      'content-length': String(last - start + 1),
      'content-range': `bytes ${start}-${last}/${total}`,
      'accept-ranges': 'bytes',
      'access-control-allow-origin': '*',
    },
  })
}

async function serveStream(request) {
  const cache = await caches.open(OFFLINE_CACHE)
  // با خودِ URL مچ می‌کنیم نه با Request: هدرِ Range روی مچینگ اثری ندارد ولی
  // این‌طور صریح‌تر است که کلیدِ کش همان آدرس است
  const hit = await cache.match(request.url)
  if (!hit) {
    // سنجاق نشده — همان مسیرِ همیشگی. آفلاین باشد، خودِ fetch شکست می‌خورد و
    // پخش‌کننده «فایل قابل پخش نبود» نشان می‌دهد.
    return fetch(request)
  }

  const range = request.headers.get('range')
  if (!range) return hit

  const buffer = await hit.clone().arrayBuffer()
  return sliceResponse(hit, range, buffer)
}

async function serveImage(request) {
  const cache = await caches.open(OFFLINE_CACHE)
  const hit = await cache.match(request.url)
  if (hit) return hit
  try {
    return await fetch(request)
  } catch {
    // کاور نیامد — کامپوننت Artwork خودش گرادیانِ جایگزین را نشان می‌دهد
    return new Response(null, { status: 504 })
  }
}

self.addEventListener('fetch', (event) => {
  const request = event.request
  if (request.method !== 'GET') return

  let url
  try {
    url = new URL(request.url)
  } catch {
    return
  }

  // هم‌مبدأ (وب) یا برون‌مبدأ (اپ اندروید: مبدأ https://localhost است و سرور آی‌پی شبکه)
  if (STREAM_PATTERN.test(url.pathname)) {
    event.respondWith(serveStream(request))
    return
  }

  if (ART_PATTERN.test(url.pathname)) {
    event.respondWith(serveImage(request))
    return
  }

  // فقط تصویرِ برون‌مبدأ: دارایی‌های خودِ اپ (که هم‌مبدأاند) کارِ پیش‌کشِ
  // Workbox‌اند و برداشتنشان از این‌جا آفلاینِ خودِ اپ را می‌شکست
  if (url.origin !== self.location.origin && request.destination === 'image') {
    event.respondWith(serveImage(request))
  }
})
