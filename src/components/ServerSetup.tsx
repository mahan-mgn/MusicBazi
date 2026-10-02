import { useState } from 'react'
import { useBackDismiss } from '../lib/back'
import { useI18n } from '../lib/i18n'
import {
  discoverLanServer,
  isLocalServer,
  lastRemoteBase,
  localBase,
  normalizeBase,
  serverBase,
  setServerBase,
} from '../lib/server'
import {
  CheckIcon,
  CloseIcon,
  HeadphonesIcon,
  PerformanceGaugeIcon,
  PhoneIcon,
  SearchIcon,
  Spinner,
  WarnIcon,
} from './icons'

type Probe = { kind: 'idle' } | { kind: 'busy' } | { kind: 'ok' } | { kind: 'fail' }

/**
 * «سرور کجاست؟» — فقط در اپ اندروید دیده می‌شود.
 *
 * در مرورگر این سؤال بی‌معناست: صفحه از روی همان سروری آمده که API را می‌دهد.
 * ولی اپِ نصب‌شده روی گوشی، رابط را از داخلِ خودش سرو می‌کند و هیچ ایده‌ای
 * ندارد که بک‌اند روی کدام دستگاه است.
 *
 * دو جواب ممکن است و هر دو اینجا هست:
 *
 *   **روی این گوشی** — بک‌اند داخل Termux روی `127.0.0.1` می‌دود. کتابخانه‌ی
 *     گوشی از کامپیوتر جداست و برای هیچ‌کدام از کارها به دستگاهِ دیگری نیاز
 *     نیست. این گزینه اول می‌آید چون سؤالِ اصلیِ کاربر همین است.
 *   **یک کامپیوتر دیگر** — همان رفتارِ قبلی، برای کسی که سرورِ خانه را ترجیح
 *     می‌دهد (قدرتِ بیشترِ CPU برای ترنسکد، آرشیوِ بزرگ‌تر).
 *
 * دکمه‌ی «امتحان کن» عمدی است و نه یک ذخیره‌ی خوش‌بینانه: تایپِ اشتباهِ یک رقم
 * از آی‌پی، بعداً به‌شکلِ «هیچ‌چی کار نمی‌کند» ظاهر می‌شود و کاربر هیچ راهی ندارد
 * بفهمد تقصیرِ آدرس بوده یا سرور.
 */
export default function ServerSetup({ onDone }: { onDone?: () => void }) {
  useBackDismiss(Boolean(onDone), onDone ?? (() => {}))
  const { t } = useI18n()
  const [value, setValue] = useState(isLocalServer() ? '' : serverBase())
  const [probe, setProbe] = useState<Probe>({ kind: 'idle' })
  const [localProbe, setLocalProbe] = useState<Probe>({ kind: 'idle' })
  const [showSteps, setShowSteps] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [scanFailed, setScanFailed] = useState(false)

  const remoteRemembered = lastRemoteBase()

  async function handleAutoScan() {
    setScanning(true)
    setScanFailed(false)
    setProbe({ kind: 'idle' })
    try {
      const found = await discoverLanServer()
      if (found) {
        setValue(found)
        setProbe({ kind: 'busy' })
        const alive = await ping(found)
        setProbe({ kind: alive ? 'ok' : 'fail' })
      } else {
        setScanFailed(true)
      }
    } finally {
      setScanning(false)
    }
  }

  const target = normalizeBase(value)

  /**
   * یک آدرس را با `/api/health` می‌سنجد.
   *
   * تایم‌اوت دستی لازم است: آی‌پیِ اشتباه در شبکه‌ی محلی جواب نمی‌دهد بلکه تا
   * آخرِ مهلتِ TCP سکوت می‌کند و کاربر یک دقیقه اسپینر می‌بیند.
   */
  async function ping(url: string): Promise<boolean> {
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), 6000)
    try {
      const res = await fetch(`${url}/api/health`, { signal: ctrl.signal })
      return res.ok
    } catch {
      return false
    } finally {
      clearTimeout(timer)
    }
  }

  /**
   * ذخیره و ادامه.
   *
   * ری‌لود ساده‌ترین راهِ درست است: استورها، سرویس‌ورکر و صفِ پخش همه در
   * لحظه‌ی بالا آمدن آدرس را خوانده‌اند و نیمه‌عوض‌کردنشان فقط باگ می‌سازد.
   */
  function commit(raw: string) {
    setServerBase(raw)
    location.reload()
  }

  async function useLocal() {
    setLocalProbe({ kind: 'busy' })
    const url = localBase()
    // اگر سرورِ گوشی جواب داد که مستقیم می‌رویم جلو؛ اگر نداد، همان آدرس را
    // ذخیره می‌کنیم ولی هشدار را نشان می‌دهیم — چون ممکن است کاربر چند ثانیه
    // بعد Termux را روشن کند و نخواهیم دوباره کل این صفحه را بگرداند.
    const alive = await ping(url)
    setLocalProbe({ kind: alive ? 'ok' : 'fail' })
    if (alive) commit(url)
  }

  async function test() {
    if (!target) return
    setProbe({ kind: 'busy' })
    const alive = await ping(target)
    setProbe({ kind: alive ? 'ok' : 'fail' })
  }

  return (
    <div className="flex min-h-dvh flex-col items-center justify-center px-safe py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-2.5">
          <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-accent text-accent-fg">
            <HeadphonesIcon className="size-5" />
          </span>
          <span className="text-lg font-bold">{t.brand}</span>
          {onDone && (
            <button
              onClick={onDone}
              aria-label={t.close}
              className="ms-auto grid size-9 place-items-center rounded-full text-muted-2 transition hover:bg-panel-2 hover:text-fg"
            >
              <CloseIcon className="size-4" />
            </button>
          )}
        </div>

        {/* ---------- روی این گوشی ---------- */}
        <section className="rounded-2xl border border-accent/35 bg-panel-2/60 p-4">
          <div className="flex items-start gap-3">
            <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-accent/15 text-accent">
              <PhoneIcon className="size-4" />
            </span>
            <div className="min-w-0">
              <h1 className="text-base font-bold">{t.serverLocalTitle}</h1>
              <p className="mt-1 text-xs leading-6 text-muted">{t.serverLocalBody}</p>
            </div>
          </div>

          <button
            onClick={() => void useLocal()}
            disabled={localProbe.kind === 'busy'}
            className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-full bg-accent px-4 py-2.5 text-sm font-semibold text-accent-fg transition enabled:hover:brightness-110 disabled:opacity-45"
          >
            {localProbe.kind === 'busy' ? <Spinner className="size-4" /> : null}
            {t.serverLocal}
          </button>

          {localProbe.kind === 'fail' && (
            <p className="mt-2.5 flex items-start gap-1.5 text-xs leading-5 text-danger">
              <WarnIcon className="mt-0.5 size-3.5 shrink-0" />
              {t.serverLocalHint}
            </p>
          )}

          {/*
           * +/− به‌جای شورونِ چرخان: شورون با flipِ RTL‌اش وقتی بچرخد در یکی از
           * دو جهت به بالا اشاره می‌کند و در دیگری به پایین — یعنی حالتِ باز/
           * بسته در فارسی و انگلیسی فرق می‌افتاد. این هیچ جهتی ندارد.
           */}
          <button
            onClick={() => setShowSteps((v) => !v)}
            aria-expanded={showSteps}
            className="mt-2.5 inline-flex items-center gap-1.5 text-[11px] font-semibold text-accent transition hover:brightness-125"
          >
            <span className="grid size-4 shrink-0 place-items-center rounded-md border border-accent/40 text-[11px] leading-none">
              {showSteps ? '−' : '+'}
            </span>
            {t.serverLocalHow}
          </button>
          {showSteps && (
            <pre
              dir="ltr"
              className="mt-2 overflow-x-auto rounded-xl border border-line bg-panel p-3 text-start font-mono text-[10.5px] leading-5 text-muted"
            >
              {t.serverLocalSteps}
            </pre>
          )}
        </section>

        {/* ---------- یا یک کامپیوتر دیگر ---------- */}
        <section className="mt-6">
          <div className="flex items-center gap-2">
            <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-panel-2 text-accent">
              <PerformanceGaugeIcon className="size-4" />
            </span>
            <h2 className="text-sm font-bold">{t.serverTitle}</h2>
          </div>
          <p className="mt-1 text-xs leading-6 text-muted">{t.serverBody}</p>

          <label className="mt-4 block">
            <span className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wide text-muted-2">
              {t.serverLabel}
            </span>
            <input
              value={value}
              onChange={(e) => {
                setValue(e.target.value)
                setProbe({ kind: 'idle' })
                setScanFailed(false)
              }}
              placeholder={t.serverPlaceholder}
              inputMode="url"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              dir="ltr"
              className="w-full rounded-xl border border-line bg-panel-2 px-3.5 py-3 text-sm outline-none transition placeholder:text-muted-2 focus:border-accent/70"
            />
          </label>

          <div className="mt-2.5 flex flex-wrap items-center justify-between gap-2">
            <button
              type="button"
              onClick={() => void handleAutoScan()}
              disabled={scanning}
              className="inline-flex items-center gap-1.5 text-xs font-medium text-accent transition hover:brightness-125 disabled:opacity-50 cursor-pointer"
            >
              {scanning ? <Spinner className="size-3.5" /> : <SearchIcon className="size-3.5" />}
              {scanning ? t.serverScanning : t.serverAutoScan}
            </button>

            {remoteRemembered && remoteRemembered !== value && (
              <button
                type="button"
                onClick={() => {
                  setValue(remoteRemembered)
                  setProbe({ kind: 'idle' })
                  setScanFailed(false)
                }}
                className="inline-flex items-center rounded-lg border border-line bg-panel-2 px-2 py-0.5 text-[11px] text-muted transition hover:border-accent/40 hover:text-fg cursor-pointer"
              >
                {t.serverSwitchTo(remoteRemembered)}
              </button>
            )}
          </div>

          {scanFailed && (
            <p className="mt-2 flex items-center gap-1.5 text-xs text-warn">
              <WarnIcon className="size-3.5 shrink-0" />
              {t.serverScanNotFound}
            </p>
          )}

          <p className="mt-2 text-[11px] leading-5 text-muted-2">{t.serverHint}</p>

          {probe.kind === 'ok' && (
            <p className="mt-3 flex items-center gap-1.5 text-xs text-accent">
              <CheckIcon className="size-3.5 shrink-0" />
              {t.serverOk}
            </p>
          )}
          {probe.kind === 'fail' && (
            <p className="mt-3 flex items-start gap-1.5 text-xs leading-5 text-danger">
              <WarnIcon className="mt-0.5 size-3.5 shrink-0" />
              {t.serverFailed}
            </p>
          )}

          <div className="mt-4 flex gap-2">
            <button
              onClick={() => void test()}
              disabled={!target || probe.kind === 'busy'}
              className="inline-flex flex-1 items-center justify-center gap-2 rounded-full border border-line px-4 py-2.5 text-sm text-fg transition enabled:hover:border-muted-2 disabled:opacity-45"
            >
              {probe.kind === 'busy' ? <Spinner className="size-4" /> : null}
              {probe.kind === 'busy' ? t.serverTesting : t.serverTest}
            </button>
            <button
              onClick={() => commit(value)}
              disabled={!target}
              className="inline-flex flex-1 items-center justify-center rounded-full bg-accent px-4 py-2.5 text-sm font-semibold text-accent-fg transition enabled:hover:brightness-110 disabled:opacity-45"
            >
              {t.serverSave}
            </button>
          </div>
        </section>
      </div>
    </div>
  )
}
