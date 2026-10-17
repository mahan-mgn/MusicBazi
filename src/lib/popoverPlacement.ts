/**
 * محاسبهٔ موقعیتِ پاپ‌اور — تابعِ **خالص**، بدونِ DOM.
 *
 * جدا نگه داشته شده چون jsdom اندازهٔ واقعیِ عناصر را نمی‌دهد و `getBoundingClientRect`
 * همیشه صفر برمی‌گرداند. با تابعِ خالص، ریاضیِ موقعیت‌دهی را می‌شود مستقل و
 * کامل تست کرد — چیزی که با رندرِ واقعی ممکن نبود.
 */

export interface Rect {
  top: number
  left: number
  right: number
  bottom: number
  width: number
  height: number
}

export interface PlacementInput {
  /** کادرِ دکمهٔ لنگر (مختصات viewport). */
  anchor: Rect
  /** اندازهٔ طبیعیِ منو. */
  menu: { width: number; height: number }
  /** اندازهٔ viewport. */
  viewport: { width: number; height: number }
  /** فاصله از لبه‌ها. */
  margin?: number
  /** فاصلهٔ منو از دکمه. */
  gap?: number
}

export interface Placement {
  top: number
  left: number
  maxHeight: number
  /** `bottom` یعنی منو زیرِ دکمه باز می‌شود؛ `top` یعنی بالای آن. */
  placement: 'bottom' | 'top'
}

/**
 * منو کجا بنشیند تا همیشه کامل دیده شود؟
 *
 * قواعد:
 *  ۱. **پیش‌فرض زیرِ دکمه.** پاپ‌اور معمولاً زیرِ لنگر باز می‌شود و کاربر
 *     انتظارش را دارد.
 *  ۲. **فقط وقتی بالا جای بیشتری هست، flip کن.** نه «هر وقت پایین جا نبود» —
 *     اگر پایین ۱۰۰px و بالا ۱۵۰px باشد، بالا بهتر است؛ ولی اگر پایین ۱۰۰px
 *     و بالا ۸۰px باشد، همان پایین با اسکرول بهتر از بالا با اسکرول است.
 *  ۳. **هرگز از viewport بیرون نزند.** هم عمودی (با `maxHeight`) و هم افقی
 *     (با کلمپِ `left`).
 *  ۴. **همیشه اسکرول داشته باشد** وقتی محتوا بلندتر از فضاست — منویی که
 *     بریده می‌شود ولی اسکرول ندارد، همان باگِ قبلی است.
 */
export function placeMenu({
  anchor,
  menu,
  viewport,
  margin = 8,
  gap = 6,
}: PlacementInput): Placement {
  const spaceBelow = viewport.height - anchor.bottom - gap - margin
  const spaceAbove = anchor.top - gap - margin

  // کدام سمت فضای بیشتری دارد؟ (با احتسابِ ارتفاعِ خودِ منو)
  const belowFits = menu.height <= spaceBelow
  const aboveFits = menu.height <= spaceAbove
  let placement: 'bottom' | 'top'
  if (belowFits && aboveFits) {
    // هر دو جا می‌شود → پیش‌فرض زیرِ دکمه
    placement = 'bottom'
  } else if (belowFits) {
    placement = 'bottom'
  } else if (aboveFits) {
    placement = 'top'
  } else {
    // هیچ‌کدام کامل جا نمی‌شود → سمتی که فضای بیشتری دارد
    placement = spaceBelow >= spaceAbove ? 'bottom' : 'top'
  }

  const available = placement === 'bottom' ? spaceBelow : spaceAbove
  // ارتفاع = کوچک‌ترینِ «اندازهٔ منو»، «فضای همان سمت»، و «۷۰٪ صفحه».
  //
  // ⚠️ اینجا `MIN_USEFUL_HEIGHT` **کف نمی‌گذارد**: کف‌گذاشتن یعنی وقتی فضا
  // کم است منو از viewport بیرون بزند — همان چیزی که این تابع باید جلویش
  // را بگیرد. اگر فضا واقعاً کم باشد، منو کوتاه و اسکرول‌دار می‌شود.
  const maxHeight = Math.max(0, Math.min(menu.height, available, viewport.height * 0.7))

  // لبهٔ *پایینِ* منو به لبهٔ مجاورِ دکمه می‌چسبد؛ بعد داخلِ viewport کلمپ
  // می‌شود تا در فضای بسیار کم هم بیرون نزند.
  const top =
    placement === 'bottom' ? anchor.bottom + gap : anchor.top - gap - maxHeight
  const clampedTop = Math.max(margin, Math.min(top, viewport.height - maxHeight - margin))

  // کلمپِ افقی: منو هرگز از لبه‌ها بیرون نزند
  const desiredLeft = anchor.left
  const maxLeft = viewport.width - menu.width - margin
  const left = Math.max(margin, Math.min(desiredLeft, Math.max(margin, maxLeft)))

  return { top: clampedTop, left, maxHeight, placement }
}

/**
 * در عرضِ کم، منو به‌جای پاپ‌اور یک شیتِ پایین است.
 *
 * آستانهٔ ۶۴۰px: پایین‌تر از آن، دکمه‌های لمسی بزرگ‌اند و یک شیتِ تمام‌عرض
 * راحت‌تر از پاپ‌اورِ باریک است.
 */
export const SHEET_BREAKPOINT = 640

export function isSheetLayout(viewportWidth: number): boolean {
  return viewportWidth < SHEET_BREAKPOINT
}
