import { useEffect, useRef, useState } from 'react'
import { useBackDismiss } from '../lib/back'
import { useI18n, type Dict } from '../lib/i18n'
import {
  fetchSetupState,
  saveSetup,
  testSetupKey,
  uploadCookies,
  type SetupKey,
  type SetupState,
  type TestGroup,
} from '../lib/setup'
import { CheckIcon, CloseIcon, EyeIcon, EyeOffIcon, Spinner, TelegramIcon, WarnIcon } from './icons'
import { GeminiLogo, GeniusLogo, SpotifyLogo } from './logos'

/**
 * ویزاردِ راه‌اندازی — *شخصیِ هر حساب*.
 *
 * هر کاربری که ثبت‌نام می‌کند کلیدِ اسپاتیفای/Genius/Gemini/AcoustID/AudD و
 * کوکیِ یوتیوبِ خودش را می‌دهد؛ سرور آن‌ها را به‌ازای همان حساب در دیتابیس
 * ذخیره می‌کند. روی دامنه، بدونِ این، هر بازدیدکننده سهمیه و کلیدِ پرداختیِ
 * صاحبِ سرور را خرج می‌کرد.
 *
 * سه چیز را با هم انجام می‌دهد تا کاربر مجبور نشود README را بخواند:
 *   ۱. وضعیتِ سرور را می‌سنجد (ffmpeg، JS runtime، PO Token، اینترنت). اینها
 *      مالِ سرورند — کاربر عوضشان نمی‌کند، فقط باید بداند چرا کار نمی‌کند.
 *   ۲. هر کلید را *قبل از ذخیره* با سرویسِ خودش می‌آزماید.
 *   ۳. در دیتابیسِ همین حساب ذخیره می‌کند.
 *
 * **ری‌استارتی در کار نیست.** مقدارها زنده از دیتابیس خوانده می‌شوند، پس
 * درخواستِ بعدی همان مقدارِ تازه را می‌بیند. نسخه‌ی قبلی `.env` می‌نوشت و
 * مجبور بود سرور را پایین/بالا کند.
 *
 * اگر کاربر هنوز وارد نشده باشد، ویزارد وضعیتِ سرور را نشان می‌دهد ولی
 * ذخیره‌کردن ۴۰۱ می‌گیرد — و دروازه خودش فقط برای حسابِ واردشده باز می‌شود.
 */

/** گروه‌های آزمودنی — هرکدام یک یا دو فیلد را با هم می‌فرستند */
type Probe =
  | { kind: 'idle' }
  | { kind: 'busy' }
  | { kind: 'ok'; detail: string }
  | { kind: 'fail'; detail: string }

const EMPTY: Probe = { kind: 'idle' }

/**
 * چیدمانِ فرم. `group` یعنی این فیلدها با *یک* کلیک آزموده می‌شوند (اسپاتیفای
 * دو قسمتی است و تک‌سرآزمودنی‌اش همیشه «غلط» می‌گفت).
 *
 * عمداً فقط کلیدهای شخصی: پروکسی و توکنِ باتِ تلگرام مالِ سرورند و کاربر
 * اصلاً نمی‌بیندشان.
 */
const FIELDS: {
  id: TestGroup
  group: SetupKey[]
  label: (t: Dict) => string
  hint: (t: Dict) => string
  url?: string
  secrets?: SetupKey[]
}[] = [
  {
    id: 'spotify',
    group: ['MUSICBAZI_SPOTIFY_CLIENT_ID', 'MUSICBAZI_SPOTIFY_CLIENT_SECRET'],
    label: (t) => t.setupSpotify,
    hint: (t) => t.setupSpotifyHint,
    url: 'https://developer.spotify.com/dashboard',
    secrets: ['MUSICBAZI_SPOTIFY_CLIENT_SECRET'],
  },
  {
    id: 'gemini',
    group: ['MUSICBAZI_GEMINI_API_KEY'],
    label: (t) => t.setupGemini,
    hint: (t) => t.setupGeminiHint,
    url: 'https://aistudio.google.com/apikey',
    secrets: ['MUSICBAZI_GEMINI_API_KEY'],
  },
  {
    id: 'genius',
    group: ['MUSICBAZI_GENIUS_ACCESS_TOKEN'],
    label: (t) => t.setupGenius,
    hint: (t) => t.setupGeniusHint,
    url: 'https://genius.com/api-clients',
    secrets: ['MUSICBAZI_GENIUS_ACCESS_TOKEN'],
  },
  {
    id: 'acoustid',
    group: ['MUSICBAZI_ACOUSTID_KEY'],
    label: (t) => t.setupAcoustid,
    hint: (t) => t.setupAcoustidHint,
    url: 'https://acoustid.org/new-application',
  },
  {
    id: 'audd',
    group: ['MUSICBAZI_AUDD_TOKEN'],
    label: (t) => t.setupAudd,
    hint: (t) => t.setupAuddHint,
    url: 'https://dashboard.audd.io',
    secrets: ['MUSICBAZI_AUDD_TOKEN'],
  },
]

export default function SetupWizard({
  onDone,
  onServer,
}: {
  onDone?: () => void
  onServer?: () => void
}) {
  useBackDismiss(Boolean(onDone), onDone ?? (() => {}))
  const { t } = useI18n()
  const [state, setState] = useState<SetupState | null>(null)
  const [values, setValues] = useState<Partial<Record<SetupKey, string>>>({})
  const [showSecret, setShowSecret] = useState<Record<string, boolean>>({})
  const [probes, setProbes] = useState<Record<string, Probe>>({})
  const [cookieProbe, setCookieProbe] = useState<Probe>(EMPTY)
  const [busy, setBusy] = useState(false)
  const [fatal, setFatal] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  const toggleSecret = (key: string) => setShowSecret((s) => ({ ...s, [key]: !s[key] }))

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
      setProbes((p) => ({
        ...p,
        [field.id]: r.ok ? { kind: 'ok', detail: r.detail } : { kind: 'fail', detail: r.detail },
      }))
    } catch (err) {
      if (testSeq.current[field.id] !== seq) return
      setProbes((p) => ({
        ...p,
        [field.id]: { kind: 'fail', detail: err instanceof Error ? err.message : String(err) },
      }))
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
   * ذخیره در دیتابیسِ همین حساب.
   *
   * فقط کلیدهایی می‌روند که کاربر چیزی تایپ کرده — فرستادنِ رشته‌ی خالی یعنی
   * پاک‌کردنِ کلیدی که از قبل کار می‌کرده.
   */
  async function save() {
    const payload = Object.fromEntries(
      Object.entries(values).filter(([, v]) => v && v.trim()),
    ) as Partial<Record<SetupKey, string>>
    setBusy(true)
    setFatal('')
    try {
      await saveSetup(payload, { done: true })
      // `?setup=1` باید قبل از بستن پاک شود، وگرنه لینکِ «راه‌اندازی» در آدرس
      // می‌ماند و رفرشِ بعدی دوباره بازش می‌کند
      const p = new URLSearchParams(location.search)
      if (p.has('setup')) {
        p.delete('setup')
        const qs = p.toString()
        window.history.replaceState(null, '', qs ? `/?${qs}` : '/')
      }
      setBusy(false)
      onDone?.()
    } catch (err) {
      setBusy(false)
      setFatal(err instanceof Error ? err.message : String(err))
    }
  }

  /**
   * رد کردن — بدون هیچ کلیدی وارد می‌شود. قابلیت‌های اختیاری خاموش می‌مانند و
   * ویزارد دیگر برای این حساب باز نمی‌شود.
   */
  async function skip() {
    setBusy(true)
    setFatal('')
    try {
      await saveSetup({}, { done: true })
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
          <img src="/logo.png" alt="" className="size-10 rounded-xl object-cover shadow-sm" />
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
        <p className="mt-2 text-sm leading-7 text-muted">{t.setupPerUserBody}</p>

        {/* ---------- وضعیتِ سرور (فقط-خواندنی) ---------- */}
        <section className="mt-6 rounded-2xl border border-line bg-panel p-4">
          <h2 className="text-sm font-bold">{t.setupServerTitle}</h2>
          <p className="mt-1 text-xs leading-6 text-muted-2">{t.setupServerBody}</p>
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
              <EnvRow
                ok={env!.cookies}
                label={t.setupEnvCookies}
                bad={t.setupEnvCookiesBad}
                optional
              />
            </ul>
          )}
          {/* تلگرام یک بات برای کلِ سرور است؛ کاربر چتِ خودش را با کدِ
              جفت‌سازی وصل می‌کند و توکن را نمی‌بیند */}
          {state?.telegram && (
            <p className="mt-3 flex items-center gap-2 border-t border-line pt-3 text-[11px] leading-5 text-muted-2">
              <TelegramIcon className="size-3.5 shrink-0 text-[#229ED9]" />
              <span dir="auto">
                {state.telegram.botTokenSet
                  ? t.setupTelegramServer(state.telegram.botUsername || 'MusicBazi')
                  : t.setupTelegramServerNone}
              </span>
            </p>
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

        {/* ---------- کلیدهای شخصی ---------- */}
        <section className="mt-5 rounded-2xl border border-line bg-panel p-4">
          <h2 className="text-sm font-bold">{t.setupKeysTitle}</h2>
          <p className="mt-1 text-xs leading-6 text-muted">{t.setupKeysBody}</p>

          {FIELDS.map((f) => {
            const canTest =
              probes[f.id]?.kind !== 'busy' &&
              f.group.every((k) => (values[k] ?? '').trim() || Boolean(state?.set[k]))
            const isMulti = f.group.length > 1

            return (
              <div key={f.id} className="mt-5 first:mt-4">
                <div className="flex flex-wrap items-center gap-x-2">
                  {f.id === 'gemini' && <GeminiLogo className="size-4 shrink-0" />}
                  {f.id === 'genius' && <GeniusLogo className="size-4 shrink-0 rounded" />}
                  {f.id === 'spotify' && <SpotifyLogo className="size-4 shrink-0" />}
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
                  {!isMulti && state?.set[f.group[0]] && (
                    <span className="text-[10.5px] text-muted-2">
                      {t.setupAlreadySet(state.set[f.group[0]]!)}
                    </span>
                  )}
                </div>
                <p className="mt-0.5 text-[11px] leading-5 text-muted-2">{f.hint(t)}</p>

                {f.group.map((key) => {
                  const isSecret = f.secrets?.includes(key)
                  const isRevealed = Boolean(showSecret[key])
                  const setValue = state?.set[key]

                  return (
                    <label key={key} className="mt-2 block">
                      <div className="mb-1 flex items-center justify-between text-[10.5px]">
                        <span className="font-semibold uppercase tracking-wide text-muted-2" dir="ltr">
                          {key.replace('MUSICBAZI_', '')}
                        </span>
                        {isMulti && setValue && (
                          <span className="text-muted-2">{t.setupAlreadySet(setValue)}</span>
                        )}
                      </div>
                      <div className="flex gap-2">
                        <div className="relative min-w-0 flex-1">
                          <input
                            type={isSecret && !isRevealed ? 'password' : 'text'}
                            value={values[key] ?? ''}
                            onChange={(e) => set(key, e.target.value)}
                            placeholder={setValue ?? ''}
                            autoComplete="off"
                            spellCheck={false}
                            dir="ltr"
                            className={`w-full rounded-xl border border-line bg-panel-2 px-3 py-2.5 text-sm outline-none transition placeholder:text-muted-2/60 focus:border-accent/70 ${isSecret ? 'pe-9' : ''}`}
                          />
                          {isSecret && (
                            <button
                              type="button"
                              onClick={() => toggleSecret(key)}
                              title={isRevealed ? t.setupHideSecret : t.setupShowSecret}
                              aria-label={isRevealed ? t.setupHideSecret : t.setupShowSecret}
                              className="absolute inset-y-0 end-0 grid size-9 place-items-center text-muted-2 transition hover:text-fg"
                            >
                              {isRevealed ? (
                                <EyeOffIcon className="size-4" />
                              ) : (
                                <EyeIcon className="size-4" />
                              )}
                            </button>
                          )}
                        </div>
                        {!isMulti && (
                          <button
                            type="button"
                            onClick={() => void test(f)}
                            disabled={!canTest}
                            className="shrink-0 rounded-xl border border-line px-3 text-xs transition enabled:hover:border-accent/60 disabled:opacity-40"
                          >
                            {probes[f.id]?.kind === 'busy' ? (
                              <Spinner className="size-3.5" />
                            ) : (
                              t.setupTest
                            )}
                          </button>
                        )}
                      </div>
                    </label>
                  )
                })}

                {isMulti && (
                  <div className="mt-2.5 flex justify-end">
                    <button
                      type="button"
                      onClick={() => void test(f)}
                      disabled={!canTest}
                      className="inline-flex items-center gap-1.5 rounded-xl border border-line px-3.5 py-1.5 text-xs font-medium transition enabled:hover:border-accent/60 enabled:hover:text-fg disabled:opacity-40"
                    >
                      {probes[f.id]?.kind === 'busy' ? <Spinner className="size-3.5" /> : null}
                      <span>{t.setupTest}</span>
                    </button>
                  </div>
                )}

                {/* نتیجه یک خط است، حتی وقتی دو فیلد گروه‌اند */}
                <ProbeLine probe={probes[f.id] ?? EMPTY} />
              </div>
            )
          })}
        </section>

        {fatal && (
          <div className="mt-5 rounded-xl border border-danger/40 bg-danger/10 p-3 text-xs leading-6 text-danger">
            <div className="flex items-start gap-1.5">
              <WarnIcon className="mt-0.5 size-3.5 shrink-0" />
              <span>{fatal}</span>
            </div>
            {onServer && (
              <button
                type="button"
                onClick={onServer}
                className="mt-2.5 inline-flex items-center gap-1.5 rounded-lg border border-danger/40 bg-panel px-2.5 py-1 text-xs font-semibold text-fg transition hover:border-danger hover:text-danger cursor-pointer"
              >
                {t.serverChange}
              </button>
            )}
          </div>
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
            disabled={busy}
            className="inline-flex flex-[1.4] items-center justify-center gap-2 rounded-full bg-accent px-4 py-2.5 text-sm font-semibold text-accent-fg transition enabled:hover:brightness-110 disabled:opacity-45"
          >
            {busy ? <Spinner className="size-4" /> : null}
            {filled ? t.setupSave(filled, testedOk) : t.setupSaveNothing}
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

function EnvRow({
  ok,
  label,
  bad,
  optional,
}: {
  ok: boolean
  label: string
  bad: string
  optional?: boolean
}) {
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
