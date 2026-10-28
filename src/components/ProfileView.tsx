import { useEffect, useRef, useState } from 'react'

import { useI18n } from '../lib/i18n'
import { useAuth } from '../store/auth'
import Artwork from './Artwork'
import { ConfirmRow, Row, Section } from './settingRows'
import { Spinner, UserIcon } from './icons'

/**
 * صفحه‌ی پروفایل.
 *
 * همان قالبِ صفحه‌ی تنظیمات را دارد (سرصفحه‌ی درشت + کارت‌های `Section`) تا
 * کاربر حس نکند به بخشِ جداگانه‌ای از اپ رفته. تنها تفاوت، آواتارِ بزرگِ
 * بالای صفحه است که هویت را همان‌جا نشان می‌دهد.
 */

export default function ProfileView({ onLogin }: { onLogin: () => void }) {
  const { t, lang } = useI18n()
  const { user, busy, updateProfile, setAvatar, clearAvatar, logout } = useAuth()

  const [displayName, setDisplayName] = useState(user?.displayName ?? '')
  const [username, setUsername] = useState(user?.username ?? '')
  const [error, setError] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  // با بارگذاریِ پروفایل (مثلاً بعدِ ورود در تبِ دیگر) فرم هم‌راستا می‌شود
  useEffect(() => {
    setDisplayName(user?.displayName ?? '')
    setUsername(user?.username ?? '')
    setError(null)
  }, [user?.id, user?.displayName, user?.username])

  if (!user) {
    return (
      <div className="rise space-y-4 pb-4">
        <header>
          <h1 className="text-2xl font-black sm:text-3xl">{t.profileTitle}</h1>
        </header>
        <Section title={t.guestHint} hint={t.guestHintBody}>
          <button
            onClick={onLogin}
            className="w-full rounded-full bg-accent px-4 py-3 text-sm font-semibold text-accent-fg transition hover:brightness-110"
          >
            {t.login}
          </button>
        </Section>
      </div>
    )
  }

  const dirty = displayName.trim() !== user.displayName || username.trim() !== (user.username ?? '')

  async function save() {
    setError(null)
    try {
      await updateProfile({
        displayName: displayName.trim(),
        // رشته‌ی خالی یعنی «نام کاربری نمی‌خواهم» — که برای حسابِ گوگل معنا دارد
        username: username.trim(),
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : t.loginFailed)
    }
  }

  async function pick(file: File | undefined) {
    if (!file) return
    setError(null)
    try {
      await setAvatar(file)
    } catch (err) {
      setError(err instanceof Error ? err.message : t.loginFailed)
    }
  }

  return (
    <div className="rise space-y-4 pb-4">
      <header>
        <h1 className="text-2xl font-black sm:text-3xl">{t.profileTitle}</h1>
      </header>

      <section className="rounded-2xl border border-line-soft bg-panel/50 p-4">
        <div className="flex flex-col items-center gap-3 sm:flex-row sm:gap-5">
          {/*
            هاله‌ی رنگیِ پشتِ آواتار از خودِ عکس می‌آید (`artColor`)، مثل
            صفحه‌ی هنرمند — بدونش کارتِ آواتار روی پس‌زمینه‌ی تیره تخت می‌شود.
          */}
          <div className="relative shrink-0">
            <div
              aria-hidden
              className="absolute -inset-2 rounded-full opacity-40 blur-xl"
              style={{ background: 'radial-gradient(circle, var(--accent), transparent 68%)' }}
            />
            <div className="relative grid size-24 place-items-center overflow-hidden rounded-full border border-line bg-panel-2 sm:size-28">
              {user.avatarUrl ? (
                <Artwork
                  src={user.avatarUrl}
                  alt={user.displayName}
                  seed={user.id}
                  rounded="rounded-full"
                  className="size-24 sm:size-28"
                />
              ) : (
                <UserIcon className="size-10 text-muted-2" />
              )}
            </div>
          </div>

          <div className="min-w-0 flex-1 text-center sm:text-start">
            <p className="truncate text-lg font-bold bidi">{user.displayName}</p>
            {user.username && (
              <p className="mt-0.5 truncate text-xs text-muted-2" dir="ltr">
                @{user.username}
              </p>
            )}
            <div className="mt-3 flex flex-wrap justify-center gap-2 sm:justify-start">
              <button
                onClick={() => fileInput.current?.click()}
                disabled={busy}
                className="inline-flex items-center gap-1.5 rounded-full border border-line px-3 py-2 text-xs text-muted transition enabled:hover:border-muted-2 enabled:hover:text-fg disabled:opacity-45"
              >
                {busy && <Spinner className="size-3" />}
                {busy ? t.avatarUploading : t.changePhoto}
              </button>
              {user.avatarUrl && (
                <button
                  onClick={() => void clearAvatar()}
                  disabled={busy}
                  className="rounded-full border border-line px-3 py-2 text-xs text-muted transition enabled:hover:border-danger enabled:hover:text-danger disabled:opacity-45"
                >
                  {t.removePhoto}
                </button>
              )}
            </div>
          </div>
        </div>

        <input
          ref={fileInput}
          type="file"
          // `accept` راهنمای پیکرِ فایل است، نه اعتبارسنجی — سرور خودش نوع را
          // از بایت‌ها تشخیص می‌دهد
          accept="image/*"
          className="hidden"
          onChange={(e) => {
            void pick(e.target.files?.[0])
            // پاک‌کردنِ مقدار: انتخابِ دوباره‌ی همان فایل باید رویداد بدهد
            e.target.value = ''
          }}
        />
      </section>

      <Section title={t.accountInfo}>
        {/*
          ورودی‌ها `stacked` می‌خواهند، نه ردیفِ کنارِ برچسب. `Row`ِ عادی
          برچسب را `flex-1` می‌کند و ورودیِ `w-full` کنارش جمع می‌شود — روی
          موبایل برچسب به ستونی ۱۷ پیکسلی می‌رسید و «Display name» سه خط
          می‌شد. زیرِ برچسب، ورودی تمامِ عرض را می‌گیرد.
        */}
        <Row label={t.displayName} stacked>
          <input
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            maxLength={60}
            className={fieldClass}
          />
        </Row>

        <Row label={t.username} hint={t.usernameRules} stacked>
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder={t.usernameOptional}
            dir="ltr"
            className={`${fieldClass} text-start`}
          />
        </Row>

        <Row
          label={t.email}
          hint={user.kind === 'google' ? t.emailReadOnly : undefined}
        >
          <span className="text-xs text-muted-2" dir="ltr">
            {user.email ?? '—'}
          </span>
        </Row>

        <Row label={t.accountKind}>
          <span className="rounded-full border border-line bg-panel-2 px-2.5 py-1 text-[11px] text-muted">
            {user.kind === 'google'
              ? t.accountKindGoogle
              : user.kind === 'local'
                ? t.accountKindLocal
                : t.accountKindGuest}
          </span>
        </Row>

        <Row label={t.memberSince}>
          <span className="text-xs text-muted-2">
            {user.createdAt ? new Date(user.createdAt * 1000).toLocaleDateString(lang === 'fa' ? 'fa-IR' : 'en-GB') : '—'}
          </span>
        </Row>

        {error && (
          <p role="alert" className="mt-2 rounded-xl border border-danger/40 bg-danger/10 px-3 py-2 text-xs text-danger bidi">
            {error}
          </p>
        )}

        <button
          onClick={() => void save()}
          disabled={!dirty || busy}
          className="mt-3 w-full rounded-full bg-accent px-4 py-2.5 text-sm font-semibold text-accent-fg transition enabled:hover:brightness-110 disabled:opacity-45"
        >
          {busy ? t.profileSaving : t.profileSave}
        </button>
      </Section>

      <Section title={t.logout}>
        <ConfirmRow
          label={t.logout}
          hint={t.logoutConfirmBody}
          actionLabel={t.logout}
          confirmLabel={t.logoutConfirm}
          tone="danger"
          onAction={logout}
        />
      </Section>
    </div>
  )
}

const fieldClass =
  'w-full max-w-[15rem] rounded-xl border border-line bg-panel-2 px-3 py-2 text-xs outline-none transition placeholder:text-muted-2 focus:border-accent/70'
