import { useEffect, useState } from 'react'
import { useI18n } from '../lib/i18n'
import { bytes as fmtBytes } from '../lib/format'
import { batteryIgnoring, haptic, openBatterySettings, openAppSettings } from '../lib/native'
import { isNativeApp } from '../lib/server'
import { checkForUpdate, dismissUpdate, openApkDownload, type UpdateInfo } from '../lib/update'
import { useToasts } from '../store/toasts'
import { BatteryIcon, DownloadIcon } from './icons'

/**
 * دو چیز که فقط داخلِ اپِ اندروید معنا دارند و هیچ‌کدام صفحه‌ی جدا نمی‌خواهند.
 *
 * هر دو «سلامتِ نصب»اند، نه قابلیت: یا نسخه‌ی تازه‌ای هست که کاربر از آن بی‌خبر
 * است، یا اندروید دارد پخش را می‌خواباند. جای این‌ها منو/نوارِ وضعیتی است، نه
 * یک تب — و روی وب اصلاً رندر نمی‌شوند.
 */

/* ---------- بنرِ بروزرسانی ---------- */

export function UpdateBanner() {
  const { t, lang } = useI18n()
  const push = useToasts((s) => s.push)
  const [info, setInfo] = useState<UpdateInfo | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!isNativeApp()) return
    let alive = true
    // کمی دیرتر از اولین رندر: اول صفحه باید نشسته باشد، بعد یک بنر بالا بیاید
    const id = setTimeout(() => {
      void checkForUpdate().then((u) => alive && setInfo(u))
    }, 1500)
    return () => {
      alive = false
      clearTimeout(id)
    }
  }, [])

  if (!info) return null

  const size = info.bytes > 0 ? ` · ${fmtBytes(info.bytes, lang)}` : ''

  return (
    <div
      role="status"
      className="glass-tint sticky top-header z-20 flex flex-wrap items-center justify-center gap-x-2 gap-y-1 px-3 py-1.5 text-[11px] bg-accent/15 text-fg"
    >
      <span className="flex items-center gap-1.5">
        <DownloadIcon className="size-3.5 shrink-0 text-accent" />
        {t.updateAvailable(info.versionName + size)}
      </span>
      <span className="opacity-60" dir="ltr">
        {t.updateFrom(info.installed, info.versionName)}
      </span>

      {/*
        یادداشتِ انتشار — تنها جایی که کاربرِ نسخه‌ی قدیمی می‌فهمد این آپدیت
        یک کارِ اضافه لازم دارد. بدونِ این، نصبِ روی نسخه‌ی امضاشده با کلیدِ
        دیگر با `INSTALL_FAILED_UPDATE_INCOMPATIBLE` می‌ترکد و کاربر فکر می‌کند
        فایلِ دانلودی خراب است.
      */}
      {info.notes && (
        <p className="basis-full text-center leading-snug text-muted">{info.notes}</p>
      )}

      {info.apkUrl ? (
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            setBusy(true)
            void openApkDownload(info.apkUrl as string).then((ok) => {
              setBusy(false)
              push(ok ? t.updateOpened : t.updateCopied, ok ? 'info' : 'error')
            })
          }}
          className="rounded-full border border-accent/50 px-2.5 py-0.5 font-medium text-accent transition hover:bg-accent/10 disabled:opacity-50"
        >
          {t.updateInstall}
        </button>
      ) : (
        <span className="opacity-60">— {t.updateNoFile}</span>
      )}

      <button
        type="button"
        onClick={() => {
          dismissUpdate(info.versionName || info.versionCode)
          setInfo(null)
        }}
        className="rounded-full px-2 py-0.5 text-muted underline underline-offset-2 transition hover:text-fg"
      >
        {t.updateLater}
      </button>
    </div>
  )
}

/* ---------- ردیفِ باتری، داخلِ منو ---------- */

export function BatteryRow() {
  const { t } = useI18n()
  const [ignoring, setIgnoring] = useState<boolean | null>(null)

  useEffect(() => {
    if (!isNativeApp()) return
    let alive = true
    void batteryIgnoring().then((value) => alive && setIgnoring(value))
    return () => {
      alive = false
    }
  }, [])

  // `null` یعنی نمی‌دانیم (وب، اندرویدِ قدیمی، یا ROMی که این API را بسته).
  // گفتنِ «برو این‌را روشن کن» وقتی چیزی خاموش نیست، فقط بی‌اعتمادی می‌سازد.
  if (ignoring === null) return null

  return (
    <>
      <div className="my-1 border-t border-line-soft" />
      <button
        role="menuitem"
        onClick={() => {
          haptic.tap()
          // اگر صفحه‌ی تنظیماتِ باتری نبود (بعضی ROMها)، به صفحه‌ی اطلاعاتِ اپ
          // می‌افتیم — هر دو دستِ کاربر را به همان جا می‌رسانند
          void openBatterySettings().then((ok) => {
            if (!ok) void openAppSettings()
          })
        }}
        className="flex w-full items-start gap-2.5 rounded-lg px-2.5 py-2.5 text-start text-xs text-muted transition hover:bg-panel-2 hover:text-fg"
      >
        <BatteryIcon className={`mt-0.5 size-4 shrink-0 ${ignoring ? 'text-accent' : 'text-warn'}`} />
        <span className="min-w-0 flex-1">
          <span className="block">{t.batteryRow}</span>
          <span className={`block text-[10px] leading-snug ${ignoring ? 'text-muted-2' : 'text-warn'}`}>
            {ignoring ? t.batteryOn : t.batteryOff}
          </span>
        </span>
        {!ignoring && <span className="shrink-0 text-[10px] text-accent">{t.batteryFix}</span>}
      </button>
    </>
  )
}
