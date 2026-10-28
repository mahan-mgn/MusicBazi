import { useState, type ReactNode } from 'react'
import { usePopover } from '../lib/usePopover'
import { ChevronIcon, Spinner } from './icons'
import Range from './Range'

/**
 * پریمیتیوهای ردیفِ تنظیمات.
 *
 * پروژه عمداً هیچ کامپوننتِ Button/Card/Select عمومی ندارد و همه‌چیز از
 * Tailwindِ خام ساخته می‌شود. این فایل همان شکاف را فقط برای *ردیف‌های*
 * تنظیمات پر می‌کند — چون صفحه‌ی تنظیمات ~۳۰ ردیفِ هم‌شکل دارد و تکرارِ
 * دستیِ همان مارک‌آپ سی‌بار، جایی است که چیدمان‌ها بی‌دلیل از هم واگرا می‌شوند.
 *
 * این‌ها کامپوننتِ عمومیِ UI نیستند و از `src/components/` هم بیرون نمی‌روند:
 * `AudioSettings` دست‌نخورده می‌ماند تا رفتاری پس گرفته نشود.
 */

/** کارتِ یک بخش، با سرصفحه‌ی میله‌دارِ آمار و آیکون. */
export function Section({
  title,
  icon,
  hint,
  children,
}: {
  title: string
  icon?: ReactNode
  hint?: string
  children: ReactNode
}) {
  return (
    <section className="rounded-2xl border border-line-soft bg-panel/50 p-3 sm:p-4">
      <h2 className="mb-1 flex items-center gap-2 text-sm font-bold sm:text-base">
        <span aria-hidden className="h-4 w-1 shrink-0 rounded-full bg-accent" />
        {icon}
        {title}
      </h2>
      {hint && <p className="mb-3 text-[11px] leading-5 text-muted-2">{hint}</p>}
      <div className={hint ? '' : 'mt-2'}>{children}</div>
    </section>
  )
}

/** ردیفِ عمومی: برچسب و راهنما سمتِ شروع، کنترل سمتِ پایان. */
export function Row({
  label,
  hint,
  children,
  stacked = false,
}: {
  label: string
  hint?: string
  children?: ReactNode
  /** کنترل زیرِ متن بیاید — برای فهرست‌های بلند مثلِ کیفیت */
  stacked?: boolean
}) {
  return (
    <div
      className={`flex py-2.5 ${
        stacked ? 'flex-col gap-2' : 'flex-wrap items-center justify-between gap-x-3 gap-y-2'
      }`}
    >
      <div className="min-w-0 flex-1">
        <p className="text-xs font-medium">{label}</p>
        {hint && <p className="mt-0.5 text-[11px] leading-snug text-muted-2">{hint}</p>}
      </div>
      {children}
    </div>
  )
}

/** ردیفِ روشن/خاموش — کلیدِ بومی، همان چیزی که `AudioSettings` هم دارد. */
export function ToggleRow({
  label,
  hint,
  checked,
  onChange,
  disabled,
}: {
  label: string
  hint?: string
  checked: boolean
  onChange: (v: boolean) => void
  disabled?: boolean
}) {
  return (
    <label className={`flex cursor-pointer items-start gap-2.5 py-2.5 ${disabled ? 'opacity-45' : ''}`}>
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 size-3.5 shrink-0 accent-[var(--accent)]"
      />
      <span className="min-w-0">
        <span className="block text-xs font-medium">{label}</span>
        {hint && (
          <span className="mt-0.5 block text-[11px] leading-snug text-muted-2">{hint}</span>
        )}
      </span>
    </label>
  )
}

/**
 * قرص‌های پاره‌ای — همان الگوی اکولایزر و بازهٔ آمار.
 *
 * `aria-pressed` عمدی است و نه `role="radio"`: دکمه‌های مستقلِ معمولی‌اند و
 * نه یک گروهِ فرمِ مقید، و صفحه‌خوان با `aria-pressed` همان چیزی را می‌فهمد
 * که باید.
 */
export function SegmentedRow<T extends string>({
  label,
  hint,
  value,
  options,
  onChange,
  disabled,
}: {
  label: string
  hint?: string
  value: T
  options: { value: T; label: string }[]
  onChange: (v: T) => void
  disabled?: boolean
}) {
  return (
    <Row label={label} hint={hint} stacked>
      <div className={`flex flex-wrap gap-1 transition-opacity ${disabled ? 'opacity-40' : ''}`}>
        {options.map((option) => (
          <button
            key={option.value}
            disabled={disabled}
            onClick={() => onChange(option.value)}
            aria-pressed={!disabled && value === option.value}
            className={`rounded-full border px-3 py-1.5 text-[11px] transition ${
              !disabled && value === option.value
                ? 'border-accent bg-accent font-semibold text-accent-fg'
                : 'border-line text-muted hover:text-fg'
            }`}
          >
            {option.label}
          </button>
        ))}
      </div>
    </Row>
  )
}

/** اسلایدر با مقدارِ قالب‌بندی‌شده. `dir="ltr"` تا در فارسی آینه نشود. */
export function SliderRow({
  label,
  hint,
  value,
  max,
  format,
  onChange,
}: {
  label: string
  hint?: string
  value: number
  max: number
  format: (v: number) => string
  onChange: (v: number) => void
}) {
  return (
    <div className="py-2.5">
      <div className="mb-1 flex items-center justify-between gap-3">
        <span className="text-xs font-medium">{label}</span>
        <span className="text-[11px] text-muted-2">{format(value)}</span>
      </div>
      {/* نوارِ range در RTL خودبه‌خود آینه می‌شود و کم/زیاد را وارونه نشان
          می‌دهد؛ مثلِ پاپ‌آورِ صدا صریحاً ltr می‌شود */}
      <div dir="ltr">
        <Range value={value} max={max} onChange={onChange} label={label} />
      </div>
      {hint && <p className="mt-1 text-[11px] leading-snug text-muted-2">{hint}</p>}
    </div>
  )
}

/**
 * ردیفِ شمارنده با دکمه‌های − و + — برای مقادیرِ کوچکِ گسسته.
 *
 * تغییر **نسبی** گزارش می‌شود (`+1`/`-1`) نه مقدارِ مطلق.
 *
 * دلیلش فقط زیبایی نیست: با مقدارِ مطلق، دو ضربه‌ی پشت‌سرهمِ «+» هر دو از
 * همان `value`ِ رندرشده حساب می‌شدند و یکی از دست می‌رفت — React بینِ دو
 * کلیکِ هم‌زمان رندر نمی‌کند و closure کهنه می‌ماند. با دلتا، مصرف‌کننده
 * مقدارِ فعلی را از خودِ استور می‌خواند و ترتیبِ رندر اهمیتی ندارد.
 */
export function StepperRow({
  label,
  hint,
  value,
  min,
  max,
  onStep,
}: {
  label: string
  hint?: string
  value: number
  min: number
  max: number
  onStep: (delta: number) => void
}) {
  const button =
    'grid size-7 place-items-center rounded-lg border border-line text-sm text-muted transition enabled:hover:border-accent/50 enabled:hover:text-fg disabled:opacity-35'
  return (
    <Row label={label} hint={hint}>
      {/* dir=ltr تا «− عدد +» در فارسی وارونه نشود */}
      <div className="flex shrink-0 items-center gap-1" dir="ltr">
        <button
          onClick={() => onStep(-1)}
          disabled={value <= min}
          aria-label={`${label} −`}
          className={button}
        >
          −
        </button>
        <span className="w-7 text-center text-xs font-semibold tabular-nums">{value}</span>
        <button
          onClick={() => onStep(1)}
          disabled={value >= max}
          aria-label={`${label} +`}
          className={button}
        >
          +
        </button>
      </div>
    </Row>
  )
}

/** ردیفِ فقط‌خواندنی — وضعیتِ سرور و آماری که تغییر نمی‌کند. */
export function StatusRow({
  label,
  value,
  tone = 'plain',
}: {
  label: string
  value: string
  tone?: 'plain' | 'ok' | 'off' | 'warn'
}) {
  const toneClass =
    tone === 'ok'
      ? 'text-accent'
      : tone === 'warn'
        ? 'text-warn'
        : tone === 'off'
          ? 'text-muted-2'
          : 'text-fg'
  return (
    <div className="flex items-center justify-between gap-3 py-1.5">
      <span className="min-w-0 text-xs text-muted">{label}</span>
      <span className={`shrink-0 text-xs font-medium ${toneClass}`} dir="auto">
        {value}
      </span>
    </div>
  )
}

/**
 * ردیفِ کنشی.
 *
 * `external` یعنی آدرسِ بیرونیِ مطلق (مخزن، داشبوردِ کلید) که باید در مرورگرِ
 * سیستم باز شود، نه داخلِ WebView. برای ناوبریِ داخلی `onClick` بده.
 */
export function LinkRow({
  label,
  hint,
  href,
  onClick,
  external,
}: {
  label: string
  hint?: string
  href?: string
  onClick?: () => void
  external?: boolean
}) {
  const className =
    'flex w-full items-center gap-3 rounded-xl border border-line bg-panel-soft px-3 py-2.5 text-start transition hover:border-accent/40'
  const inner = (
    <>
      <span className="min-w-0 flex-1">
        <span className="block text-xs font-medium text-fg">{label}</span>
        {hint && <span className="mt-0.5 block text-[11px] leading-snug text-muted-2">{hint}</span>}
      </span>
      <ChevronIcon className="size-3.5 shrink-0 text-muted-2" />
    </>
  )
  if (href) {
    return (
      <a
        href={href}
        onClick={onClick}
        className={className}
        {...(external ? { target: '_blank', rel: 'noreferrer' } : {})}
      >
        {inner}
      </a>
    )
  }
  return (
    <button onClick={onClick} className={className}>
      {inner}
    </button>
  )
}

const actionTone = {
  default: 'border-line text-fg hover:border-accent/50',
  danger: 'border-danger/40 text-danger hover:border-danger',
} as const

/**
 * تأییدِ دو مرحله‌ای درون‌خطی.
 *
 * پنجره‌ی تأییدِ سیستمی عمدی نیست: در Android WebView `confirm()` می‌تواند
 * بی‌صدا `false` برگرداند (و بعد کاربر فکر کند اپ خراب است)، و یک دیالوگِ
 * کامل برای «پاک‌کردنِ تاریخچه» سنگین است. ضربه‌ی اول سؤال می‌پرسد، ضربه‌ی
 * دوم انجام می‌دهد، و خروج از حالتِ تأیید با هر کلیکِ بیرون خودکار است.
 */
export function ConfirmRow({
  label,
  hint,
  actionLabel,
  confirmLabel,
  tone = 'default',
  busy,
  onAction,
}: {
  label: string
  hint?: string
  /** متنِ دکمه در حالتِ عادی — باید *کنش* را بگوید، نه نامِ ردیف را */
  actionLabel: string
  /**
   * متنِ دکمه بعد از ضربه‌ی اول. **اختیاری**: ندادنش یعنی کنشِ برگشت‌پذیرِ
   * بی‌خطر و یک ضربه کافی است — پرسیدنِ «مطمئنی؟» برای چیزی که با یک رفرش
   * برمی‌گردد فقط اصطکاک است.
   */
  confirmLabel?: string
  tone?: 'default' | 'danger'
  busy?: boolean
  onAction: () => void
}) {
  const [armed, setArmed] = useState(false)
  // لایه‌ی برگشت فقط وقتی ثبت می‌شود که چیزی برای لغوکردن باشد — وگرنه هر
  // ردیف در حالتِ عادی یک لایه‌ی خالی روی پشته می‌گذارد و دکمه‌ی برگشتِ
  // اندروید بی‌دلیل یک ضربه مصرف می‌کند
  const box = usePopover<HTMLDivElement>(armed && Boolean(confirmLabel), () => setArmed(false))

  return (
    <div ref={box} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 py-1.5">
      <div className="min-w-0 flex-1">
        <p className="text-xs font-medium">{label}</p>
        {hint && <p className="mt-0.5 text-[11px] leading-snug text-muted-2">{hint}</p>}
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        {armed && confirmLabel && (
          <button
            onClick={() => setArmed(false)}
            aria-label="Cancel"
            className="rounded-full border border-line px-2.5 py-1 text-[11px] text-muted transition hover:text-fg"
          >
            ✕
          </button>
        )}
        <button
          onClick={() => {
            if (!confirmLabel || armed) {
              setArmed(false)
              onAction()
              return
            }
            setArmed(true)
          }}
          disabled={busy}
          className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[11px] font-semibold transition disabled:opacity-45 ${
            !confirmLabel || armed ? actionTone[tone] : 'border-line text-muted hover:text-fg'
          }`}
        >
          {busy && <Spinner className="size-3" />}
          {armed ? confirmLabel : actionLabel}
        </button>
      </div>
    </div>
  )
}

/** جداکننده‌ی نازکِ بینِ ردیف‌های یک بخش */
export function Divider() {
  return <div className="my-0.5 border-t border-line-soft" />
}
