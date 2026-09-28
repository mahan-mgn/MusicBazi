import { useEffect, useRef, useState } from 'react'
import { useI18n, type Dict } from '../lib/i18n'
import {
  fetchSetupState,
  saveSetup,
  testSetupKey,
  waitForServer,
  uploadCookies,
  type SetupKey,
  type SetupState,
  type TestGroup,
} from '../lib/setup'
import { CheckIcon, CloseIcon, HeadphonesIcon, Spinner, TelegramIcon, WarnIcon } from './icons'
import { GeminiLogo, GeniusLogo, SpotifyLogo } from './logos'

/**
 * ویزاردِ راه‌اندازی — دروازه‌ی ورودِ مرورگر.
 *
 * کلیدها سمتِ سرور است، نه مرورگر. این یک واقعیتِ معماری است و نه ترجیح:
 * رازِ اسپاتیفای و توکنِ تلگرام اگر به صفحه بروند، در DevTools و در کشِ
 * سرویس‌ورکر و در دسترسِ هر اسکریپتِ تزریق‌شده می‌افتند. پس این صفحه فقط
 * *می‌فرستد*؛ نوشتنِ `.env` و آزمودنِ کلید و ری‌استارت را سرور انجام می‌دهد.
 *
 * سه چیز را با هم انجام می‌دهد تا کاربر مجبور نشود README را بخواند:
 *   ۱. محیط را می‌سنجد (ffmpeg، جاوااسکریپت‌ران‌تایم، PO Token، اینترنت).
 *   ۲. هر کلید را *قبل از ذخیره* با سرویسِ خودش می‌آزماید.
 *   ۳. سرور را ری‌استارت می‌کند تا مقدارهای تازه واقعاً به کار بروند.
 *
 * گامِ سوم ضروری است: `config.py` مقدارها را در زمانِ import می‌خواند. بدونش
 * کاربر کلیدِ درست را می‌دهد و «باز هم» چیزی کار نمی‌کند.
 */

/** گروه‌های آزمودنی — هرکدام یک یا دو فیلد را با هم می‌فرستند */
type Probe = { kind: 'idle' } | { kind: 'busy' } | { kind: 'ok'; detail: string } | { kind: 'fail'; detail: string }

const EMPTY: Probe = { kind: 'idle' }

/**
 * چیدمانِ فرم. `group` یعنی این فیلدها با *یک* کلیک آزموده می‌شوند (اسپاتیفای
 * دو قسمتی است و تک‌سرآزمودنی‌اش همیشه «غلط» می‌گفت).
 */
const FIELDS: {
  id: TestGroup
  group: SetupKey[]
  label: (t: Dict) => string
  hint: (t: Dict) => string
  url?: string
  secret?: boolean
}[] = [
  {
    id: 'spotify',
    group: ['UNSTREAM_SPOTIFY_CLIENT_ID', 'UNSTREAM_SPOTIFY_CLIENT_SECRET'],
    label: (t) => t.setupSpotify,
    hint: (t) => t.setupSpotifyHint,
    url: 'https://developer.spotify.com/dashboard',
  },
  {
    id: 'proxy',
    group: ['UNSTREAM_PROXY'],
    label: (t) => t.setupProxy,
    hint: (t) => t.setupProxyHint,
  },
  {
    id: 'telegram',
    group: ['UNSTREAM_TELEGRAM_BOT_TOKEN'],
    label: (t) => t.setupTelegram,
    hint: (t) => t.setupTelegramHint,
    url: 'https://t.me/BotFather',
    secret: true,
  },
  {
    id: 'gemini',
    group: ['UNSTREAM_GEMINI_API_KEY'],
    label: (t) => t.setupGemini,
    hint: (t) => t.setupGeminiHint,
    url: 'https://aistudio.google.com/apikey',
    secret: true,
  },
  {
    id: 'genius',
    group: ['UNSTREAM_GENIUS_ACCESS_TOKEN'],
    label: (t) => t.setupGenius,
    hint: (t) => t.setupGeniusHint,
    url: 'https://genius.com/api-clients',
    secret: true,
  },
  {
    id: 'acoustid',
    group: ['UNSTREAM_ACOUSTID_KEY'],
    label: (t) => t.setupAcoustid,
    hint: (t) => t.setupAcoustidHint,
    url: 'https://acoustid.org/new-application',
  },
  {
    id: 'audd',
    group: ['UNSTREAM_AUDD_TOKEN'],
    label: (t) => t.setupAudd,
    hint: (t) => t.setupAuddHint,
    url: 'https://dashboard.audd.io',
    secret: true,
  },
]

export default function SetupWizard({ onDone }: { onDone?: () => void }) {
  const { t } = useI18n()
  const [state, setState] = useState<SetupState | null>(null)
  const [values, setValues] = useState<Partial<Record<SetupKey, string>>>({})
  const [probes, setProbes] = useState<Record<string, Probe>>({})
  const [cookieProbe, setCookieProbe] = useState<Probe>(EMPTY)
  const [busy, setBusy] = useState(false)
  const [waiting, setWaiting] = useState(false)
  const [fatal, setFatal] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    let alive = true
    void fetchSetupState().then((s) => {
      if (!alive) return
      setState(s)
      // null یعنی به سرور نرسیدیم. بی‌این، چک‌لیست تا ابد «در حال بررسی…»
      // می‌ماند و کاربر نمی‌فهمد سرور پایین است یا اینترنت
      if (!s) setFatal(t.setupEnvUnavailable)
    })
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  /**
   * آزمایشِ هم‌زمان دو گروه: نتیجه‌ای که *بعد از* عوض‌شدنِ مقدارِ همان گروه
   * می‌رسد نباید نشان داده شود — «کلید سالم است» برای مقداری که دیگر در فیلد
   * نیست، از نبودنش بدتر است. شمارنده به‌ازای هر فیلد، پاسخِ کهنه را بازمی‌گرداند.
   */
  const testSeq = useRef<Record<string, number>>({})

  const set = (key: SetupKey, value: string) => {
    setValues((v) => ({ ...v, [key]: value }))
    // مقدار عوض شده یعنی نتیجه‌ی آزمایشِ قبلی دیگر به این مقدار نمی‌خورد —
    // هم خطِ نتیجه پاک می‌شود، هم آزمایشِ در جاری که با مقدارِ *قدیم* رفته
    // بی‌اعتبار می‌گردد (وگرنه پاسخِ دیررس همان نتیجه‌ی پاک‌شده را برمی‌گرداند)
    for (const f of FIELDS) {
      if (f.group.includes(key)) testSeq.current[f.id] = (testSeq.current[f.id] ?? 0) + 1
    }
    setProbes((p) => {
      const next = { ...p }
      for (const f of FIELDS) if (f.group.includes(key)) delete next[f.id]
      return next
    })
  }

  async function test(field: (typeof FIELDS)[number]) {
    const seq = (testSeq.current[field.id] ?? 0) + 1
    testSeq.current[field.id] = seq
    setProbes((p) => ({ ...p, [field.id]: { kind: 'busy' } }))
    const sent: Partial<Record<SetupKey, string>> = {}
    for (const key of field.group) sent[key] = values[key] ?? ''
    try {
      const r = await testSetupKey(field.id, sent)
      if (testSeq.current[field.id] !== seq) return
      setProbes((p) => ({ ...p, [field.id]: r.ok ? { kind: 'ok', detail: r.detail } : { kind: 'fail', detail: r.detail } }))
    } catch (err) {
      if (testSeq.current[field.id] !== seq) return
      setProbes((p) => ({ ...p, [field.id]: { kind: 'fail', detail: err instanceof Error ? err.message : String(err) } }))
    }
  }

  async function pickCookies(file: File) {
    setCookieProbe({ kind: 'busy' })
    try {
      const r = await uploadCookies(file)
      setCookieProbe({ kind: 'ok', detail: t.setupCookiesOk(r.cookies, r.youtube) })
      // چک‌لیستِ «وضعیتِ این سرور» بی‌خبر از کوکیِ تازه می‌ماند — دوباره بپرس
      void fetchSetupState().then((s) => {
        if (s) setState(s)
      })
    } catch (err) {
      setCookieProbe({ kind: 'fail', detail: err instanceof Error ? err.message : String(err) })
    }
  }

  /**
   * ذخیره و ری‌استارت.
   *
   * فقط کلیدهایی می‌روند که کاربر چیزی تایپ کرده — فرستادنِ رشته‌ی خالی یعنی
   * پاک‌کردنِ کلیدی که از قبل کار می‌کرده.
   */
  async function save() {
    const payload = Object.fromEntries(
      Object.entries(values).filter(([, v]) => v && v.trim()),
    ) as Partial<Record<SetupKey, string>>
    const hasPayload = Object.keys(payload).length > 0
    // بدونِ کلیدِ تازه هم باید ری‌استارت شود اگر چیزی روی دیسک خوانده‌نشده باشد
    const restart = hasPayload || !!state?.restartNeeded
    setBusy(true)
    setFatal('')
    try {
      const r = await saveSetup(payload, { restart, done: true })
      // سرور گفت خودش نمی‌تواند ری‌استارت شود (Job Objectِ ویندوز اجازه‌ی
      // breakaway نداد). زنده است و مقدارها روی دیسک‌اند — فقط دستی باید بالا
      // بیاید. نگه‌داشتنِ کاربر روی «در حال انتظار» بدترین کار است.
      if (r.manualRestart) {
        setBusy(false)
        setFatal(t.setupManualRestart)
        return
      }
      if (r.restarting) {
        setWaiting(true)
        const back = await waitForServer()
        if (!back) {
          // سرور برنگشته. اینجا نباید کاربر را پشتِ یک صفحه‌ی سفید گذاشت:
          // «ادامه» را نشان می‌دهیم تا خودش رفرش کند و راهنمایِ دستی هم می‌آید.
          setWaiting(false)
          setBusy(false)
          setFatal(t.setupRestartFailed)
          return
        }
        // `?setup=1` باید قبل از reload پاک شود، وگرنه صفحه‌ی تازه‌بارگذاری‌شده
        // دوباره خودش را درِ ویزارد می‌بندد — کاربرِ «فقط کلید اضافه کردم» گیر
        // می‌افتد و باید دو بار صفحه را ببندد
        const p = new URLSearchParams(location.search)
        p.delete('setup')
        const qs = p.toString()
        window.history.replaceState(null, '', qs ? `/?${qs}` : '/')
        location.reload()
        return
      }
      onDone?.()
    } catch (err) {
      setBusy(false)
      setFatal(err instanceof Error ? err.message : String(err))
    }
  }

  /** رد کردن — بدون هیچ کلیدی وارد می‌شود. قابلیت‌های اختیاری خاموش می‌مانند. */
  async function skip() {
    setBusy(true)
    setFatal('')
    try {
      await saveSetup({}, { restart: false, done: true })
      onDone?.()
    } catch (err) {
      setBusy(false)
      setFatal(err instanceof Error ? err.message : String(err))
    }
  }

  const env = state?.env
  const filled = FIELDS.filter((f) => f.group.some((k) => (values[k] ?? '').trim())).length
  const testedOk = FIELDS.filter((f) => probes[f.id]?.kind === 'ok').length

  return (
    <div className="flex min-h-dvh flex-col items-center px-safe py-10">
      <div className="w-full max-w-lg">
        <div className="mb-6 flex items-center gap-2.5">
          <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-accent text-accent-fg">
            <HeadphonesIcon className="size-5" />
          </span>
          <span className="text-lg font-bold">{t.brand}</span>
          {onDone && (
            <button
              onClick={() => void skip()}
              aria-label={t.close}
              className="ms-auto grid size-9 place-items-center rounded-full text-muted-2 transition hover:bg-panel-2 hover:text-fg"
            >
              <CloseIcon className="size-4" />
            </button>
          )}
        </div>

        <h1 className="text-xl font-bold">{t.setupTitle}</h1>
        <p className="mt-2 text-sm leading-7 text-muted">{t.setupBody}</p>

        {/*
         * روی دیسک چیزی هست که سرور هنوز نخوانده — معمولاً از اجرایِ قبلی که
         * ری‌استارت نشده. بدونِ این، کاربر می‌بیند «کلید ست است» ولی همان
         * قابلیت همچنان کار نمی‌کند و چیزی برای سرزنش کردن ندارد.
         */}
        {state?.restartNeeded && (
          <p className="mt-5 flex items-start gap-1.5 rounded-xl border border-accent/40 bg-accent/10 p-3 text-xs leading-6 text-fg">
            <WarnIcon className="mt-0.5 size-3.5 shrink-0 text-accent" />
            <span>{t.setupRestartNeeded}</span>
          </p>
        )}

        {/* ---------- محیط ---------- */}
        <section className="mt-6 rounded-2xl border border-line bg-panel p-4">
          <h2 className="text-sm font-bold">{t.setupEnvTitle}</h2>
          {!state ? (
            <p className="mt-3 flex items-center gap-2 text-xs text-muted">
              <Spinner className="size-3.5" />
              {t.setupEnvLoading}
            </p>
          ) : (
            <ul className="mt-3 grid gap-2 text-xs">
              <EnvRow ok={env!.ffmpeg} label={t.setupEnvFfmpeg} bad={t.setupEnvFfmpegBad} />
              <EnvRow
                ok={env!.potoken}
                label={t.setupEnvPotoken}
                bad={t.setupEnvPotokenBad}
                optional
              />
              <EnvRow
                ok={!!env!.jsRuntime}
                label={t.setupEnvJs(env!.jsRuntime ?? '—')}
                bad={t.setupEnvJsBad}
              />
              <EnvRow ok={env!.internet} label={t.setupEnvNet} bad={t.setupEnvNetBad} />
              <EnvRow ok={env!.proxy} label={t.setupEnvProxy} bad={t.setupEnvProxyBad} optional />
              <EnvRow ok={env!.cookies} label={t.setupEnvCookies} bad={t.setupEnvCookiesBad} optional />
            </ul>
          )}
        </section>

        {/* ---------- کوکی یوتیوب ---------- */}
        <section className="mt-5 rounded-2xl border border-line bg-panel p-4">
          <h2 className="text-sm font-bold">{t.setupCookiesTitle}</h2>
          <p className="mt-1 text-xs leading-6 text-muted">{t.setupCookiesBody}</p>
          <button
            onClick={() => fileRef.current?.click()}
            disabled={cookieProbe.kind === 'busy'}
            className="mt-3 inline-flex items-center gap-2 rounded-full border border-line px-4 py-2 text-sm transition enabled:hover:border-muted-2 disabled:opacity-45"
          >
            {cookieProbe.kind === 'busy' ? <Spinner className="size-4" /> : null}
            {t.setupCookiesPick}
          </button>
          <input
            ref={fileRef}
            type="file"
            accept=".txt"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) void pickCookies(f)
              e.target.value = ''
            }}
          />
          <ProbeLine probe={cookieProbe} />
        </section>

        {/* ---------- کلیدها ---------- */}
        <section className="mt-5 rounded-2xl border border-line bg-panel p-4">
          <h2 className="text-sm font-bold">{t.setupKeysTitle}</h2>
          <p className="mt-1 text-xs leading-6 text-muted">{t.setupKeysBody}</p>

          {FIELDS.map((f) => (
            <div key={f.id} className="mt-5 first:mt-4">
              <div className="flex flex-wrap items-center gap-x-2">
                {f.id === 'gemini' && <GeminiLogo className="size-4 shrink-0" />}
                {f.id === 'genius' && <GeniusLogo className="size-4 shrink-0 rounded" />}
                {f.id === 'spotify' && <SpotifyLogo className="size-4 shrink-0" />}
                {f.id === 'telegram' && <TelegramIcon className="size-4 shrink-0 text-[#229ED9]" />}
                <h3 className="text-xs font-bold">{f.label(t)}</h3>
                {f.url && (
                  <a
                    href={f.url}
                    target="_blank"
                    rel="noreferrer noopener"
                    dir="ltr"
                    className="text-[10.5px] text-accent underline decoration-accent/40 underline-offset-2 hover:decoration-accent"
                  >
                    {f.url.replace(/^https?:\/\//, '')}
                  </a>
                )}
                {state?.set[f.group[0]] && (
                  <span className="text-[10.5px] text-muted-2">
                    {t.setupAlreadySet(state.set[f.group[0]]!)}
                  </span>
                )}
              </div>
              <p className="mt-0.5 text-[11px] leading-5 text-muted-2">{f.hint(t)}</p>

              {f.group.map((key) => (
                <label key={key} className="mt-2 block">
                  <span className="mb-1 block text-[10.5px] font-semibold uppercase tracking-wide text-muted-2" dir="ltr">
                    {key.replace('UNSTREAM_', '')}
                  </span>
                  <div className="flex gap-2">
                    <input
                      type={f.secret ? 'password' : 'text'}
                      value={values[key] ?? ''}
                      onChange={(e) => set(key, e.target.value)}
                      autoComplete="off"
                      spellCheck={false}
                      dir="ltr"
                      className="min-w-0 flex-1 rounded-xl border border-line bg-panel-2 px-3 py-2.5 text-sm outline-none transition placeholder:text-muted-2 focus:border-accent/70"
                    />
                    <button
                      onClick={() => void test(f)}
                      disabled={
                        probes[f.id]?.kind === 'busy' || !f.group.every((k) => (values[k] ?? '').trim())
                      }
                      className="shrink-0 rounded-xl border border-line px-3 text-xs transition enabled:hover:border-accent/60 disabled:opacity-40"
                    >
                      {probes[f.id]?.kind === 'busy' ? <Spinner className="size-3.5" /> : t.setupTest}
                    </button>
                  </div>
                </label>
              ))}
              {/* نتیجه یک خط است، حتی وقتی دو فیلد گروه‌اند */}
              <ProbeLine probe={probes[f.id] ?? EMPTY} />
            </div>
          ))}
        </section>

        {fatal && (
          <p className="mt-5 flex items-start gap-1.5 rounded-xl border border-danger/40 bg-danger/10 p-3 text-xs leading-6 text-danger">
            <WarnIcon className="mt-0.5 size-3.5 shrink-0" />
            <span>{fatal}</span>
          </p>
        )}

        <div className="mt-6 flex gap-2">
          <button
            onClick={() => void skip()}
            disabled={busy}
            className="inline-flex flex-1 items-center justify-center rounded-full border border-line px-4 py-2.5 text-sm text-muted transition enabled:hover:border-muted-2 enabled:hover:text-fg disabled:opacity-45"
          >
            {t.setupSkip}
          </button>
          <button
            onClick={() => void save()}
            disabled={busy || waiting}
            className="inline-flex flex-[1.4] items-center justify-center gap-2 rounded-full bg-accent px-4 py-2.5 text-sm font-semibold text-accent-fg transition enabled:hover:brightness-110 disabled:opacity-45"
          >
            {busy || waiting ? <Spinner className="size-4" /> : null}
            {waiting ? t.setupWaiting : filled ? t.setupSave(filled, testedOk) : t.setupSaveNothing}
          </button>
        </div>

        <p className="mt-3 text-[11px] leading-6 text-muted-2">{t.setupKeysFootnote}</p>
      </div>
    </div>
  )
}

function ProbeLine({ probe }: { probe: Probe }) {
  if (probe.kind === 'idle') return null
  if (probe.kind === 'busy') return null
  return (
    <p
      className={
        probe.kind === 'ok'
          ? 'mt-2 flex items-start gap-1.5 text-[11px] leading-5 text-accent'
          : 'mt-2 flex items-start gap-1.5 text-[11px] leading-5 text-danger'
      }
    >
      {probe.kind === 'ok' ? (
        <CheckIcon className="mt-0.5 size-3.5 shrink-0" />
      ) : (
        <WarnIcon className="mt-0.5 size-3.5 shrink-0" />
      )}
      <span dir="auto">{probe.detail}</span>
    </p>
  )
}

function EnvRow({ ok, label, bad, optional }: { ok: boolean; label: string; bad: string; optional?: boolean }) {
  return (
    <li className="flex items-start gap-2">
      {ok ? (
        <CheckIcon className="mt-0.5 size-3.5 shrink-0 text-accent" />
      ) : (
        <WarnIcon className={`mt-0.5 size-3.5 shrink-0 ${optional ? 'text-muted-2' : 'text-danger'}`} />
      )}
      <span className={ok ? 'text-fg' : optional ? 'text-muted' : 'text-danger'} dir="auto">
        {ok ? label : bad}
      </span>
    </li>
  )
}
