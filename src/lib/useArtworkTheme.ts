/**
 * هوکِ مشترکِ «تمِ بر پایه‌ی تصویر».
 *
 * پیش از این، شش جا تقریباً همین افکت را دستی نوشته بودند و هر کدام یک رفتارِ
 * متفاوت برای «هنوز نرسیده» و «استخراج نشد» داشتند. این هوک سه تضمین می‌دهد:
 *
 * ۱. فریمِ اولِ سنکرون: اگر رنگ از قبل در کش باشد (`peekArtworkColor`)، همان
 *    لحظه‌ی اول رندر حاضر است. بازگشتِ دوباره به یک صفحه هیچ فریمِ خاکستری یا
 *    رنگِ جایگزین ندارد.
 * ۲. نگه‌داشتنِ رنگِ قبلی: تا وقتی رنگِ تازه نرسیده، رنگِ قبلی روی صفحه
 *    می‌ماند. تنها استثنا وقتی است که ترکِ تازه *کاور ندارد* — آن‌جا باید
 *    فوراً پاک شود، وگرنه نوارِ پخش رنگِ ترکِ قبلی را به ترکِ بی‌کاور نسبت
 *    می‌دهد.
 * ۳. هویتِ پایدار: مقدارِ برگشتی روی کلیدِ رنگ memo می‌شود، پس `useMemo`های
 *    پایین‌دستی واقعاً hit می‌شوند. (قبلاً `fallbackTint(...)` در هر رندر یک
 *    آرایه‌ی تازه می‌ساخت و memo را بی‌اثر می‌کرد.)
 */

import { useEffect, useMemo, useState } from 'react'
import { dominantColor, peekArtworkColor, type RGB } from './artColor'
import { pageTheme, type PageTheme, type ThemeMode } from './pageTheme'

/**
 * تمِ حل‌شده‌ی تمِ فعلیِ اپ.
 *
 * از `document` خوانده می‌شود، نه از استور: تنها نویسنده‌ی آن
 * `applyTheme` در `store/settings.ts` است و همان‌جا `data-theme` را می‌گذارد.
 * خواندنِ مستقیم یعنی این ماژول به استور گره نمی‌خورد و در تست هم بدونِ
 * راه‌اندازیِ zustand کار می‌کند.
 *
 * حالتِ `system` هم پوشش داده می‌شود چون `applyTheme` آن را از قبل حل کرده و
 * مقدارِ واقعی را روی `data-theme` نوشته است.
 */
function resolvedMode(): ThemeMode {
  if (typeof document === 'undefined') return 'dark'
  return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark'
}

/**
 * @param src      آدرسِ کاورِ فعلی؛ `null` یعنی این آیتم کاور ندارد.
 * @param seed     سیدِ پایدار برای تمِ جایگزین (شناسه‌ی هنرمند/آلبوم/ترک).
 * @param initial  رنگِ پیشنهادی برای *فریمِ اول* (مثلاً نوار پخش که همین کاور
 *                 را استخراج کرده). فقط رنگِ اولین رندر را می‌سازد؛ بعد از آن
 *                 کش حرفِ آخر را می‌زند، چون رنگِ واقعیِ همان کاور است. در
 *                 مسیرِ واقعیِ تولید این دو یکی‌اند (هر دو از `dominantColor`
 *                 می‌آیند) و هیچ رندرِ اضافه‌ای هم رخ نمی‌دهد.
 */
export function useArtworkTheme(
  src: string | null,
  seed: string,
  initial?: RGB | null,
): PageTheme {
  const [extracted, setExtracted] = useState<RGB | null>(
    () => initial ?? peekArtworkColor(src),
  )
  const [mode, setMode] = useState<ThemeMode>(resolvedMode)

  /*
   * تمِ روشن/تیره *زنده* عوض می‌شود (کاربر یا سیستم‌عامل در حالتِ `system`) و
   * پایه‌ی صفحه در دو تم دو رنگِ متفاوت است، پس باید دنبالش بیاییم. یک
   * `MutationObserver` روی `data-theme` هم تعویضِ دستی را می‌گیرد هم تغییرِ
   * سیستم را — بدونِ گره‌خوردن به استور.
   */
  useEffect(() => {
    const el = document.documentElement
    const sync = () => setMode(resolvedMode())
    const observer = new MutationObserver(sync)
    observer.observe(el, { attributes: true, attributeFilter: ['data-theme'] })
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    if (!src) {
      // کاورِ نداشتن یعنی «رنگی نیست»، نه «هنوز نرسیده»
      setExtracted(null)
      return
    }

    const warm = peekArtworkColor(src)
    if (warm) {
      setExtracted(warm)
      return
    }

    /*
     * مسیرِ سرد: رنگِ قبلی دست‌نخورده می‌ماند و نتیجه — موفق یا ناموفق —
     * بعداً می‌نشیند. `null` یعنی استخراج نشد و تمِ سید جایگزین می‌شود.
     * `cancelled` جلوی نشستنِ نتیجه‌ی دیررسِ کاورِ قبلی را می‌گیرد.
     */
    let cancelled = false
    void dominantColor(src).then((rgb) => {
      if (!cancelled) setExtracted(rgb)
    })
    return () => {
      cancelled = true
    }
  }, [src])

  return useMemo(() => pageTheme(extracted, seed, mode), [extracted, seed, mode])
}

/**
 * منبعِ تمِ یک ویو — یک‌جا، تا شل و خودِ ویو نتوانند واگرا شوند.
 *
 * `App` این را برای لایه‌ی پس‌زمینه‌ی تمام‌صفحه می‌خواند و ویوها همان قاعده را
 * در مستنداتشان دارند (`artist.artworkUrl || artist.bannerUrl`). اگر دو نسخه
 * می‌شد، روزی که یکی عوض شود صفحه دو رنگِ مختلف می‌گرفت بی‌آنکه چیزی سرخ شود.
 */
export function pageThemeSourceOf(
  view: { kind: string },
  artist: { artworkUrl?: string | null; bannerUrl?: string | null; id: string } | null,
  album: { artworkUrl?: string | null; id: string } | null,
): { src: string | null; seed: string } | null {
  if (view.kind === 'artist' && artist) {
    return { src: artist.artworkUrl || artist.bannerUrl || null, seed: artist.id }
  }
  if (view.kind === 'album' && album) {
    return { src: album.artworkUrl || null, seed: album.id }
  }
  return null
}
