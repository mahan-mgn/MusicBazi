import { useState } from 'react'

import { useI18n } from '../lib/i18n'
import { usePopover } from '../lib/usePopover'
import { useAuth } from '../store/auth'
import Artwork from './Artwork'
import { Spinner, UserIcon } from './icons'

/**
 * دکمه‌ی پروفایل در تاپ‌بار و منوی زیرش.
 *
 * آخرین آیتمِ خوشه‌ی دکمه‌هاست. در چیدمانِ راست‌به‌چپ این خوشه سمتِ چپ
 * می‌نشیند، پس آواتار در فارسی گوشه‌ی چپِ بالا می‌افتد و در انگلیسی راست —
 * یعنی همیشه «کنارِ بقیه‌ی دکمه‌ها»، که مهم‌تر از یک گوشه‌ی ثابت است: کنارِ
 * بقیه بودن، جای دکمه را قابلِ حدس می‌کند.

 * روی موبایل هم نشان داده می‌شود — تنها کنترلِ این خوشه است که پشتِ «⋯»
 * پنهان نمی‌شود، چون هویتِ کاربر مهم‌تر از بقیه‌ی آن آیتم‌هاست.
 */

interface Props {
  onProfile: () => void
  onLogin: () => void
}

export default function ProfileMenu({ onProfile, onLogin }: Props) {
  const { t } = useI18n()
  const user = useAuth((s) => s.user)
  const loading = useAuth((s) => s.loading)
  const offline = useAuth((s) => s.offline)
  const logout = useAuth((s) => s.logout)
  const [open, setOpen] = useState(false)
  const box = usePopover<HTMLDivElement>(open, () => setOpen(false))

  /*
   * «توکن هست ولی پروفایل هنوز نخوانده» با «مهمان» یکی نیست.
   *
   * بدونِ این تفکیک، بعدِ بازگشت از گوگل تا رسیدنِ پاسخِ `/auth/me` همان دکمه‌ی
   * «ورود» دیده می‌شود — یعنی دقیقاً همان چیزی که کاربر فکر می‌کند ورودش نگرفت.
   * حالتِ گذرا ولی صادق.
   */
  const pending = !user && loading
  /*
   * توکن هست ولی پروفایلش نیامد. این «مهمان» نیست و نباید دکمه‌ی «ورود» را
   * نشان بدهد: کاربری که همین حالا وارد شده، با دیدنِ «ورود» فکر می‌کند ورودش
   * نگرفته. برچسبِ خودِ دکمه هم باید همین را بگوید، وگرنه صفحه‌خوان همان
   * «Sign in»ِ گمراه‌کننده را می‌خواند.
   */
  const unresolved = !user && offline
  const label = user ? t.openProfile : unresolved ? t.accountUnreachable : t.login

  return (
    <div ref={box} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-label={label}
        aria-expanded={open}
        aria-haspopup="menu"
        aria-busy={pending}
        title={user ? user.displayName : label}
        className="grid size-8 place-items-center overflow-hidden rounded-full border border-line bg-panel text-muted transition hover:text-fg"
      >
        {user ? (
          <Artwork
            src={user.avatarUrl}
            alt={user.displayName}
            /* `seed` شناسه‌ی کاربر است تا گرادیانِ جایگزین بین نشست‌ها ثابت بماند */
            seed={user.id}
            rounded="rounded-full"
            className="size-8"
          />
        ) : pending ? (
          <Spinner className="size-4" />
        ) : (
          <UserIcon className={unresolved ? 'size-4 text-danger' : 'size-4'} />
        )}
      </button>

      {open && (
        <div
          role="menu"
          className="sheet-in absolute end-0 z-40 mt-2 w-52 rounded-xl border border-line bg-panel p-1.5 shadow-xl"
        >
          {user ? (
            <>
              <div className="px-2.5 py-2">
                <p className="truncate text-xs font-semibold text-fg bidi">{user.displayName}</p>
                <p className="mt-0.5 truncate text-[10px] text-muted-2" dir="ltr">
                  {user.username ? `@${user.username}` : (user.email ?? t.accountKindGoogle)}
                </p>
              </div>

              <Item
                onClick={() => {
                  setOpen(false)
                  onProfile()
                }}
              >
                {t.profile}
              </Item>

              <div className="my-1 h-px bg-line-soft" />

              <Item
                onClick={() => {
                  setOpen(false)
                  logout()
                }}
              >
                {t.logout}
              </Item>
            </>
          ) : (
            <>
              <div className="px-2.5 py-2">
                <p className="text-xs font-semibold text-fg">{unresolved ? t.accountUnreachable : t.guestHint}</p>
                <p className="mt-0.5 text-[10px] leading-relaxed text-muted-2 bidi">
                  {unresolved ? t.accountUnreachableBody : t.guestHintBody}
                </p>
              </div>
              <Item
                onClick={() => {
                  setOpen(false)
                  onLogin()
                }}
              >
                {t.login}
              </Item>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function Item({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      role="menuitem"
      onClick={onClick}
      className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2.5 text-start text-xs text-muted transition hover:bg-panel-2 hover:text-fg"
    >
      {children}
    </button>
  )
}
