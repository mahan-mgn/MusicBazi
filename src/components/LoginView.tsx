import { useEffect, useRef, useState, type FormEvent } from 'react'

import { API_MODE } from '../lib/api'
import { useI18n } from '../lib/i18n'
import { useBackDismiss } from '../lib/back'
import { apiUrl } from '../lib/server'
import { useAuth } from '../store/auth'
import { GoogleIcon, Spinner } from './icons'

/**
 * صفحه‌ی ورود — تمام‌صفحه و بیرونِ پوسته.
 *
 * بیرونِ پوسته است (نه یک view داخلِ اپ) چون تاپ‌بار و تب‌بار روی صفحه‌ای که
 * هنوز کسی وارد نشده، فقط حواس‌پرتی‌اند: کاربرِ بی‌حساب دنبالِ «کتابخانه»
 * نیست، دنبالِ ورود است یا دنبالِ رد شدن از این صفحه.
 *
 * ورود اختیاری است، پس `Escape` و دکمه‌ی «بدون حساب» هر دو می‌بندندش. این با
 * گیتِ اجباری فرق دارد و عمدی است — تصمیمِ کاربر.
 */

interface Props {
  onDone: () => void
}

export default function LoginView({ onDone }: Props) {
  const { t } = useI18n()
  const auth = useAuth()
  const { providers, busy } = auth

  const [mode, setMode] = useState<'in' | 'up'>('in')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [error, setError] = useState<string | null>(null)

  const firstField = useRef<HTMLInputElement>(null)

  useBackDismiss(true, onDone)

  useEffect(() => {
    firstField.current?.focus({ preventScroll: true })
  }, [])

  // خطای بازگشتِ گوگل از fragment می‌آید (`App` آن را می‌خواند و پاک می‌کند)؛
  // این‌جا فقط به زبانِ کاربر ترجمه می‌شود.
  const googleError = useGoogleError()

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    try {
      if (mode === 'in') {
        await auth.login(username.trim(), password)
      } else {
        await auth.register(username.trim(), password, displayName.trim() || undefined)
      }
      onDone()
    } catch (err) {
      setError(err instanceof Error ? err.message : t.loginFailed)
    }
  }

  const googleOff = !providers.google
  const googleHint =
    providers.googleReason === 'needs_https'
      ? t.googleNeedsHttps
      : providers.googleReason === 'not_configured'
        ? t.googleNotConfigured
        : null

  return (
    <div className="relative flex min-h-dvh flex-col items-center justify-center overflow-hidden px-safe py-10">
      <Backdrop />

      <div className="glass rise relative w-full max-w-sm rounded-3xl border border-line-soft p-6 sm:p-8">
        <header className="mb-6 flex flex-col items-center gap-3 text-center">
          <img src="/logo.png" alt="" className="size-12 rounded-2xl" />
          <div>
            <h1 className="text-2xl font-black">{t.loginTitle}</h1>
            <p className="mt-1 text-xs leading-relaxed text-muted bidi">{t.loginSubtitle}</p>
          </div>
        </header>

        {googleError && <Notice tone="error">{googleError}</Notice>}

        {/*
          دکمه‌ی گوگل حتی وقتی خاموش است نشان داده می‌شود، فقط غیرفعال — با
          دکمه‌ی ناموجود، کاربری که منتظرِ ورودِ گوگل بود فکر می‌کند اپ خراب
          است؛ با دکمه‌ی خاکستری و یک خط توضیح، می‌فهمد چرا و چه کند.
        */}
        <button
          type="button"
          disabled={googleOff || busy}
          title={googleHint ?? undefined}
          onClick={startGoogle}
          className="flex w-full items-center justify-center gap-2.5 rounded-full border border-line bg-panel-2 py-3 text-sm font-semibold transition enabled:hover:border-muted-2 disabled:opacity-45"
        >
          <GoogleIcon className="size-4" />
          {t.loginWithGoogle}
        </button>
        {googleOff && googleHint && (
          <p className="mt-2 text-center text-[11px] leading-relaxed text-muted-2 bidi">{googleHint}</p>
        )}

        <Divider label={t.loginOr} />

        <div className="mb-4 grid grid-cols-2 gap-1 rounded-full bg-panel-2 p-1">
          <Tab active={mode === 'in'} onClick={() => switchMode('in')}>
            {t.loginTabSignIn}
          </Tab>
          <Tab active={mode === 'up'} onClick={() => switchMode('up')}>
            {t.loginTabSignUp}
          </Tab>
        </div>

        <form onSubmit={submit} className="space-y-3">
          {mode === 'up' && (
            <Field id="login-name" label={t.displayName} hint={t.displayNameOptional}>
              <input
                id="login-name"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder={t.displayNamePlaceholder}
                autoComplete="name"
                className={inputClass}
              />
            </Field>
          )}

          <Field
            id="login-username"
            label={t.username}
            hint={mode === 'up' ? t.usernameRules : undefined}
          >
            <input
              id="login-username"
              ref={firstField}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder={t.usernamePlaceholder}
              autoComplete="username"
              aria-describedby={mode === 'up' ? 'login-username-hint' : undefined}
              // `dir="ltr"`: نامِ کاربری همیشه لاتین است، حتی در رابطِ فارسی
              dir="ltr"
              required
              className={`${inputClass} text-start`}
            />
          </Field>

          <Field
            id="login-password"
            label={t.password}
            hint={mode === 'up' ? t.passwordRules : undefined}
          >
            <input
              id="login-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={t.passwordPlaceholder}
              autoComplete={mode === 'in' ? 'current-password' : 'new-password'}
              aria-describedby={mode === 'up' ? 'login-password-hint' : undefined}
              dir="ltr"
              required
              minLength={8}
              className={`${inputClass} text-start`}
            />
          </Field>

          {error && <Notice tone="error">{error}</Notice>}

          <button
            type="submit"
            disabled={busy}
            className="inline-flex w-full items-center justify-center gap-2 rounded-full bg-accent px-4 py-3 text-sm font-semibold text-accent-fg transition enabled:hover:brightness-110 disabled:opacity-45"
          >
            {busy && <Spinner className="size-3.5" />}
            {mode === 'in' ? t.loginSubmit : t.registerSubmit}
          </button>
        </form>

        <button
          type="button"
          onClick={onDone}
          className="mt-5 w-full text-center text-xs text-muted transition hover:text-fg"
        >
          {t.loginGuest}
        </button>
      </div>
    </div>
  )

  function switchMode(next: 'in' | 'up') {
    setMode(next)
    // خطای «نام کاربری یا رمز اشتباه» در تبِ ثبت‌نام بی‌معناست
    setError(null)
  }

  function startGoogle() {
    // ناوبریِ کامل (نه fetch): صفحه‌ی رضایتِ گوگل باید در نشستِ خودش باز شود
    // و برگشتش یک redirect معمولی است.
    //
    // `apiUrl` نه مسیرِ نسبی: در اپ نیتیو صفحه از `https://localhost` سرو
    // می‌شود ولی API مبدأِ دیگری دارد؛ نسبی‌بودن یعنی رفتن به یک مسیرِ ناموجود.
    window.location.href = apiUrl('/api/auth/google/start')
  }
}

const inputClass =
  'w-full rounded-xl border border-line bg-panel-2 px-3.5 py-3 text-sm outline-none transition placeholder:text-muted-2 focus:border-accent/70'

/**
 * پس‌زمینه‌ی هنری.
 *
 * صفحه‌ی ورود اولین چیزی است که کاربر می‌بیند و اگر یک فرم روی سیاهیِ خالی
 * باشد، اپ ارزان به نظر می‌رسد — درحالی‌که بقیه‌ی اپ شیشه‌ای و پررنگ است.
 * دو هاله‌ی رنگی + لوگوی محو، همان زبانِ بصری را بدونِ وابستگی به داده می‌سازد
 * (ورود هنوز کاربری ندارد که کاورش را پس‌زمینه کنیم).
 */
function Backdrop() {
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
      <div
        className="absolute -top-1/3 start-[-20%] size-[70vmax] rounded-full opacity-[0.16] blur-3xl"
        style={{ background: 'radial-gradient(circle, var(--accent), transparent 62%)' }}
      />
      <div
        className="absolute -bottom-1/3 end-[-15%] size-[60vmax] rounded-full opacity-[0.14] blur-3xl"
        style={{ background: 'radial-gradient(circle, var(--accent-2), transparent 62%)' }}
      />
      <img
        src="/logo.png"
        alt=""
        className="absolute start-1/2 top-1/2 size-[46vmax] -translate-x-1/2 -translate-y-1/2 opacity-[0.03] blur-2xl"
      />
    </div>
  )
}

/**
 * فیلد فرم با برچسب و راهنما.
 *
 * ساختار عمداً سه‌تکه است (`<label>` جدا، نه پیچیدنِ input داخلش): وقتی ورودی
 * *داخلِ* برچسب باشد، متنِ راهنما هم بخشی از نامِ قابل‌دسترسِ فیلد می‌شود و
 * صفحه‌خوان چیزی مثل «نام کاربری ۳ تا ۲۴ کاراکتر…» می‌خواند به‌جای «نام
 * کاربری». `aria-describedby` راهنما را به‌عنوان *توضیح* وصل می‌کند، نه نام.
 */
function Field({
  id,
  label,
  hint,
  children,
}: {
  id: string
  label: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between gap-2">
        <label htmlFor={id} className="text-xs text-muted">
          {label}
        </label>
        {hint && (
          <span id={`${id}-hint`} className="text-[10px] text-muted-2 bidi">
            {hint}
          </span>
        )}
      </div>
      {children}
    </div>
  )
}

function Tab({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-full py-2 text-xs font-semibold transition ${
        active ? 'bg-panel text-fg shadow-sm' : 'text-muted hover:text-fg'
      }`}
    >
      {children}
    </button>
  )
}

function Divider({ label }: { label: string }) {
  return (
    <div className="my-5 flex items-center gap-3" role="separator">
      <span className="h-px flex-1 bg-line-soft" />
      <span className="text-[10px] text-muted-2">{label}</span>
      <span className="h-px flex-1 bg-line-soft" />
    </div>
  )
}

function Notice({ children, tone }: { children: React.ReactNode; tone: 'error' | 'info' }) {
  return (
    <p
      role={tone === 'error' ? 'alert' : undefined}
      className={`rounded-xl border px-3 py-2.5 text-xs leading-relaxed bidi ${
        tone === 'error' ? 'border-danger/40 bg-danger/10 text-danger' : 'border-line bg-panel-2 text-muted'
      }`}
    >
      {children}
    </p>
  )
}

/**
 * خطای بازگشتِ گوگل از `#auth_error=...`.
 *
 * مود دمو سرور ندارد، پس خطای گوگل هم بی‌معناست — و آن‌جا `API_MODE` تنها
 * چیزی است که تفاوت را می‌داند.
 */
function useGoogleError(): string | null {
  const { t } = useI18n()
  const [message, setMessage] = useState<string | null>(() => readGoogleError(t))
  useEffect(() => {
    setMessage(readGoogleError(t))
    // فقط یک‌بار در بوت؛ پیام باید با عوض‌شدنِ زبان هم ترجمه شود
  }, [t])
  return API_MODE === 'http' ? message : null
}

function readGoogleError(t: ReturnType<typeof useI18n.getState>['t']): string | null {
  if (typeof window === 'undefined') return null
  const match = /auth_error=([a-z]+)/.exec(window.location.hash)
  if (!match) return null
  const reason = match[1]
  return (
    {
      denied: t.googleDenied,
      expired: t.googleExpired,
      unreachable: t.googleUnreachable,
      invalid: t.googleInvalid,
    }[reason] ?? t.loginFailed
  )
}
