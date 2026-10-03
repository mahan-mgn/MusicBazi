import { useMemo, useState, type CSSProperties } from 'react'
import { usePopover } from '../lib/usePopover'
import { useI18n } from '../lib/i18n'
import PillNav from './PillNav'
import QualityPicker from './QualityPicker'
import SearchBar from './SearchBar'
import type { Tab } from './TabBar'
import { DotsIcon, LinkIcon, MicIcon, MoonIcon, PhoneIcon, SlidersIcon, SunIcon } from './icons'
import { isLocalServer, isNativeApp, serverBase } from '../lib/server'
import { BatteryRow } from './NativeHealth'
import { useSettings } from '../store/settings'
import TopFadeBlur from './TopFadeBlur'

interface Props {
  onHome: () => void
  onLibrary: () => void
  onStats: () => void
  onIdentify: () => void
  /** «آدرس سرور» — فقط در اپ نیتیو معنا دارد */
  onServer: () => void
  /** «راه‌اندازی» — تنظیم کلیدها و بررسی پیش‌نیازها */
  onSetup?: () => void
  /** همان تبی که تب‌بارِ موبایل هم نشان می‌دهد؛ اینجا قرصِ فعال را مشخص می‌کند */
  active: Tab
  searchValue: string
  searchLoading: boolean
  onSearch: (value: string, opts: { live: boolean }) => void
}

/*
 * آدرسِ واقعیِ هر مقصد — همانی که `App.tsx` در نوار آدرس می‌گذارد.
 *
 * `PillNav` با `onClick` ناوبریِ داخلی را صدا می‌زند و نمی‌گذارد مرورگر صفحه را
 * از نو بار کند، ولی `href` باید درست بماند تا کلیکِ وسط، «کپی لینک» و نوارِ
 * وضعیتِ مرورگر همان جایی را نشان بدهند که واقعاً باز می‌شود.
 */
const HOME_HREF = '/'
const LIBRARY_HREF = '/?library=1'
const STATS_HREF = '/?stats=1'

/*
 * اندازه‌ی ناوبری، هم‌قدِ بقیه‌ی کنترل‌های همین ردیف.
 *
 * پیش‌فرضِ خودِ کامپوننت ۴۲ پیکسل ارتفاع و متنِ ۱۶ است — برای یک هدرِ ۵۶ پیکسلی
 * که کنارش دکمه‌های ۳۶ پیکسلی نشسته‌اند، بلند بود.
 */
const NAV_SIZE = {
  ['--nav-h']: '36px',
  ['--pill-pad-x']: '14px',
  ['--pill-font']: '13px',
} as CSSProperties

const menuItem =
  'flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2.5 text-start text-xs text-muted transition hover:bg-panel-2 hover:text-fg'

/**
 * همان کنترل‌هایی که روی دسکتاپ کنارِ هم در نوار بالا نشسته‌اند، روی موبایل
 * پشتِ یک دکمه جمع می‌شوند.
 *
 * دلیلش حساب ساده است: شناسایی + کیفیت + زبان + تم روی عرضِ ۳۶۰ پیکسل حدود
 * ۱۷۰ پیکسل می‌خورند و از سرچ‌بار — که کارِ اصلیِ همین صفحه است — یک جعبه‌ی
 * صد پیکسلی باقی می‌گذارند.
 */
function OverflowMenu({
  onIdentify,
  onServer,
  onSetup,
}: {
  onIdentify: () => void
  onServer: () => void
  onSetup?: () => void
}) {
  const { t, lang, setLang } = useI18n()
  const { theme, toggleTheme, liquidGlass, setLiquidGlass } = useSettings()
  const [open, setOpen] = useState(false)
  const box = usePopover<HTMLDivElement>(open, () => setOpen(false))

  // همان الگوی بستنِ QualityPicker: کلیک بیرون یا Escape
  const native = isNativeApp()

  return (
    <div ref={box} className={native ? 'relative' : 'relative sm:hidden'}>
      <button
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t.moreMenu}
        title={t.moreMenu}
        className="grid size-9 place-items-center rounded-full border border-line bg-panel text-muted transition hover:text-fg"
      >
        <DotsIcon className="size-4" />
      </button>

      {open && (
        <div
          role="menu"
          className="sheet-in absolute end-0 z-40 mt-2 w-48 rounded-xl border border-line bg-panel p-1.5 shadow-xl"
        >
          {native && (
            <button
              role="menuitem"
              onClick={() => {
                setOpen(false)
                onServer()
              }}
              className={menuItem}
            >
              {isLocalServer() ? (
                <PhoneIcon className="size-4 shrink-0" />
              ) : (
                <LinkIcon className="size-4 shrink-0" />
              )}
              <span className="min-w-0 flex-1">
                <span className="block">{t.serverChange}</span>
                {/*
                 * سرورِ محلی به‌جای آدرس، برچسب می‌گیرد: «http://127.0.0.1:8000»
                 * به کاربر چیزی نمی‌گوید، ولی «همین گوشی» دقیقاً همان چیزی است
                 * که باید بداند — کتابخانه‌ای که می‌بیند روی این دستگاه است.
                 */}
                {serverBase() && (
                  <span
                    dir="ltr"
                    className="block truncate text-[10px] text-muted-2"
                  >
                    {isLocalServer() ? t.serverBadgeLocal : serverBase()}
                  </span>
                )}
              </span>
            </button>
          )}

          {onSetup && (
            <button
              role="menuitem"
              onClick={() => {
                setOpen(false)
                onSetup()
              }}
              className={menuItem}
            >
              <SlidersIcon className="size-4 shrink-0" />
              <span>{t.setupMenu}</span>
            </button>
          )}

          {(native || onSetup) && <div className="my-1 border-t border-line-soft" />}

          <button
            role="menuitem"
            onClick={() => {
              setOpen(false)
              onIdentify()
            }}
            className={menuItem}
          >
            <MicIcon className="size-4 shrink-0" />
            {t.identify}
          </button>

          <button
            role="menuitem"
            onClick={() => {
              setOpen(false)
              setLang(lang === 'fa' ? 'en' : 'fa')
            }}
            className={menuItem}
          >
            <span aria-hidden className="grid size-4 shrink-0 place-items-center text-[10px] font-bold">
              {lang === 'fa' ? 'EN' : 'فا'}
            </span>
            {t.langSwitch}
          </button>

          <button
            role="menuitem"
            onClick={() => {
              setOpen(false)
              toggleTheme()
            }}
            className={menuItem}
          >
            {theme === 'dark' ? (
              <SunIcon className="size-4 shrink-0" />
            ) : (
              <MoonIcon className="size-4 shrink-0" />
            )}
            {theme === 'dark' ? t.themeLight : t.themeDark}
          </button>

          <button
            role="menuitem"
            onClick={() => {
              setOpen(false)
              setLiquidGlass(!liquidGlass)
            }}
            className={menuItem}
          >
            <span
              aria-hidden
              className={`size-3.5 shrink-0 rounded-full border transition ${
                liquidGlass ? 'border-accent bg-accent' : 'border-muted-2 bg-transparent'
              }`}
            />
            <span className="min-w-0 flex-1">
              <span className="block">{t.liquidGlass}</span>
              <span className="block text-[10px] text-muted-2">{liquidGlass ? 'فعال' : 'غیرفعال'}</span>
            </span>
          </button>

          {/* ردیفِ سلامتِ نصب (باتری) — روی وب هیچ رندر نمی‌شود */}
          <BatteryRow />
        </div>
      )}
    </div>
  )
}

export default function Header({
  onHome,
  onLibrary,
  onStats,
  onIdentify,
  onServer,
  onSetup,
  active,
  searchValue,
  searchLoading,
  onSearch,
}: Props) {
  const { theme, toggleTheme } = useSettings()
  const { t, lang, setLang } = useI18n()

  /*
   * آرایه باید بینِ رندرها یکی بماند.
   *
   * هدر با هر ضربه‌کلید در سرچ‌بار دوباره رندر می‌شود و `PillNav` روی تغییرِ
   * `items` هندسه‌ی دایره‌ها را از نو می‌سازد — یعنی بدونِ این useMemo، هر
   * حرفی که تایپ می‌شد انیمیشنِ نیمه‌کاره‌ی هاور را وسطِ راه می‌کشت.
   */
  const navItems = useMemo(
    () => [
      { label: t.home, href: HOME_HREF, onClick: onHome },
      { label: t.library, href: LIBRARY_HREF, onClick: onLibrary },
      { label: t.stats, href: STATS_HREF, onClick: onStats },
    ],
    [t, onHome, onLibrary, onStats],
  )

  return (
    <>
      <TopFadeBlur />
      {/* pt-safe: در حالت PWA روی آیفون نوار وضعیت روی محتوا می‌افتد، چون
          status-bar-style=black-translucent است */}
      <header className="glass-bar pt-safe sticky top-0 z-30 border-b border-line-soft">
      <div className="px-safe mx-auto flex h-14 max-w-6xl items-center gap-2 sm:gap-3">
        {/*
          روی گوشی فقط نشانِ برند: مقصدها پایین در تب‌بارند و یک ردیفِ قرص کنارِ
          سرچ‌بار روی عرضِ ۳۶۰ پیکسل جایی باقی نمی‌گذارد.
        */}
        <button
          onClick={onHome}
          aria-label={t.brand}
          className="flex shrink-0 items-center gap-2 rounded-lg py-1 text-[15px] font-bold transition hover:opacity-80 sm:hidden"
        >
          <img src="/logo.png" alt="" className="size-7 rounded-lg object-cover" />
        </button>

        {/* روی دسکتاپ همین نشان، سرِ همان ناوبری می‌نشیند */}
        <PillNav
          className="hidden shrink-0 sm:block"
          logo="/logo.png"
          logoAlt={t.brand}
          logoHref={HOME_HREF}
          onLogoClick={onHome}
          items={navItems}
          activeHref={
            active === 'library'
              ? LIBRARY_HREF
              : active === 'stats'
                ? STATS_HREF
                : active === 'home'
                  ? HOME_HREF
                  : undefined
          }
          mobileMenu={false}
          initialLoadAnimation
          style={NAV_SIZE}
        />

        <div className="min-w-0 flex-1 sm:px-4">
          <div className="mx-auto w-full max-w-md">
            <SearchBar value={searchValue} loading={searchLoading} onSearch={onSearch} />
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-1.5 sm:gap-2">
          {/*
            «کتابخانه» دیگر اینجا دکمه نیست — قرصِ سمتِ چپِ همین ردیف است.
            روی گوشی هم که همان مقصد در تب‌بارِ پایین نشسته.
          */}

          {/* روی دسکتاپ همه‌شان باز و کنار هم؛ روی موبایل داخل «⋯» */}
          <button
            onClick={onIdentify}
            aria-label={t.identify}
            title={t.identify}
            className="hidden size-[30px] place-items-center rounded-full border border-line bg-panel text-muted transition hover:text-fg sm:grid"
          >
            <MicIcon className="size-3.5" />
          </button>

          <QualityPicker />

          <button
            onClick={() => setLang(lang === 'fa' ? 'en' : 'fa')}
            className="hidden rounded-full border border-line bg-panel px-2.5 py-1.5 text-xs text-muted transition hover:text-fg sm:inline-block sm:px-3"
          >
            {t.langSwitch}
          </button>

          <button
            onClick={toggleTheme}
            aria-label={theme === 'dark' ? t.themeLight : t.themeDark}
            className="hidden items-center gap-1.5 rounded-full border border-line bg-panel px-2.5 py-1.5 text-xs text-muted transition hover:text-fg sm:flex sm:px-3"
          >
            {theme === 'dark' ? <SunIcon className="size-3.5" /> : <MoonIcon className="size-3.5" />}
            <span className="hidden sm:inline">{theme === 'dark' ? t.themeLight : t.themeDark}</span>
          </button>

          <OverflowMenu onIdentify={onIdentify} onServer={onServer} onSetup={onSetup} />
        </div>
      </div>
    </header>
    </>
  )
}
