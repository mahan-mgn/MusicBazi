import { apiUrl, isNativeApp, serverBase } from './server'
import { takeRendererCrash } from './native'

/**
 * فرستادنِ خطاهای سمتِ کاربر به سرور.
 *
 * چرا لازم است: WebView وقتی می‌ترکد هیچ ردی جا نمی‌گذارد. کاربر فقط می‌گوید
 * «اپ یک‌بار بسته شد» و تو هیچ‌وقت نمی‌فهمی کدام ترک، کدام گوشی، کدام نسخه.
 * یک `window.onerror` که به `POST /api/client-error` حرف بزند، تنها راهِ دیدنِ
 * کرش‌های *واقعیِ همین نصب‌هاست* — بدون سرویسِ بیرونی.
 *
 * سه چیز را می‌گیرد:
 *   ۱. خطای مدیریت‌نشده (`error`) و ردِ promise (`unhandledrejection`)
 *   ۲. مرگِ موتورِ رندرِ اندروید — که در اجرای *بعدی* خوانده می‌شود، چون در
 *      لحظه‌ی مرگ هیچ JSی زنده نیست که بفرستد
 *   ۳. فقط در مود http؛ در مود دمو سروری نیست و فرستادن یعنی درخواستِ شکست‌خورده
 *
 * سقفِ تعداد دارد: یک خطای داخلِ rAF می‌تواند ثانیه‌ای شصت بار بترکد و سرورِ
 * خانگی را با لاگِ تکراری پر کند. بعد از سقف، سکوت می‌کند — لاگِ ناقص بهتر از
 * دیسکِ پر است.
 */

const MAX_SENDS = 12

let sent = 0
let installed = false

/**
 * رضایتِ کاربر به فرستادنِ گزارش.
 *
 * پیش‌فرض روشن است، ولی این کلید باید *واقعاً* خاموش کند نه فقط UI را عوض
 * کند؛ پس هر مسیرِ ارسال — از جمله مسیرِ مستقلِ `ErrorBoundary` که خودش
 * `fetch` می‌زند — از همین یک پرچم می‌پرسد.
 */
let enabled = true

export function setErrorReportingEnabled(value: boolean): void {
  enabled = value
}

export function isErrorReportingEnabled(): boolean {
  return enabled
}

interface Payload {
  kind: string
  message: string
  stack: string
  url: string
  app: string
  device: string
}

function send(payload: Payload): void {
  if (!enabled || sent >= MAX_SENDS || !serverBase()) return
  sent++
  // `keepalive` تا اگر اپ همان لحظه بسته شد، درخواستِ آخر هم برسد — وگرنه
  // مهم‌ترین خط (همان که اپ را کشت) گم می‌شود
  void fetch(apiUrl('/api/client-error'), {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
    keepalive: true,
  }).catch(() => {
    // فرستادنِ خطا خودش خطا داد — اینجا چرخه را ادامه نده
  })
}

function base(kind: string, message: string, stack = ''): Payload {
  return {
    kind,
    message: message.slice(0, 4000),
    stack: stack.slice(0, 4000),
    url: location.pathname + location.search,
    app: `${isNativeApp() ? 'android' : 'web'}`,
    device: navigator.userAgent.slice(0, 200),
  }
}

/**
 * یک‌بار در بالا آمدنِ اپ.
 *
 * روی وب هم فعال است — آنجا هم «کدام ترک صفحه را می‌خواباند» بی‌پاسخ می‌ماند.
 * تنها شرط، داشتنِ آدرسِ سرور است.
 */
export function installErrorReporting(): void {
  if (installed || !serverBase()) return
  installed = true

  window.addEventListener('error', (event) => {
    // خطای بارگذاریِ <img>/<script> به `window.onerror` هم می‌رسد ولی message
    // ندارد؛ آن‌ها را نمی‌خواهیم — یک CDNِ بی‌دسترس، کرشِ اپ نیست
    if (!event.message) return
    send(base('error', event.message, event.error?.stack ?? ''))
  })

  window.addEventListener('unhandledrejection', (event) => {
    const reason = event.reason
    const message =
      reason instanceof Error ? reason.message : typeof reason === 'string' ? reason : String(reason ?? '')
    send(base('rejection', message, reason instanceof Error ? (reason.stack ?? '') : ''))
  })

  // مرگِ موتورِ رندر در اجرای *گذشته*
  if (isNativeApp()) {
    void takeRendererCrash().then((text) => {
      if (text) send(base('renderer', 'WebView render process gone', text))
    })
  }
}

/**
 * یک خطای *مدیریت‌شده* را هم گزارش می‌کند.
 *
 * جایی که کد استثنا را می‌گیرد تا اپ زنده بماند (مثل شکستِ دانلود)، دیگر
 * `window.onerror` چیزی نمی‌بیند — ولی برای ما همان مهم‌ترین خطاست.
 */
export function reportError(context: string, error: unknown): void {
  const message = error instanceof Error ? error.message : String(error ?? '')
  send(base(context.slice(0, 32), message, error instanceof Error ? (error.stack ?? '') : ''))
}
