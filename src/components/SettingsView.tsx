import { useCallback, useEffect, useState } from 'react'
import { apiUrl, isLocalServer, isNativeApp, serverBase } from '../lib/server'
import { MAX_BOOST_DB } from '../lib/audioEngine'
import { EQ_PRESET_ORDER, EQ_PRESETS_DB, matchingPreset, type EqPresetName } from '../lib/audio/dsp/EqPresets'
import { bytes, digits } from '../lib/format'
import { useI18n } from '../lib/i18n'
import { nativeAppInfo } from '../lib/native'
import { fetchSetupState, type SetupState } from '../lib/setup'
import { removeStored } from '../lib/storage'
import { CODEC_QUALITIES, MP3_QUALITIES, type Quality } from '../lib/types'
import { isDone, useDownloads } from '../store/downloads'
import { useOffline } from '../store/offline'
import { usePlayer } from '../store/player'
import { useRecent } from '../store/recent'
import { useSearchHistory } from '../store/searchHistory'
import {
  MAX_CONCURRENT_DOWNLOADS,
  MAX_CROSSFADE,
  MIN_CONCURRENT_DOWNLOADS,
  useSettings,
  type NativeAudioEngineMode,
} from '../store/settings'
import {
  ConfirmRow,
  Divider,
  LinkRow,
  Row,
  Section,
  SegmentedRow,
  SliderRow,
  StatusRow,
  StepperRow,
  ToggleRow,
} from './settingRows'
import { CheckIcon, DownloadIcon, LyricsIcon, OfflineIcon, SlidersIcon, TrashIcon } from './icons'

/**
 * صفحه‌ی تنظیمات.
 *
 * تا پیش از این، ترجیح‌ها سه پاپ‌آورِ بی‌خبر از هم بودند: پاپ‌آورِ صدا در نوار
 * پخش (فقط دسکتاپ)، انتخابگر کیفیت در هدر، و منوی «⋯» موبایل. نتیجه این بود
 * که روی گوشی «هم‌ترازی بلندی» و «کراس‌فید» اصلاً در دسترس نبودند و
 * `nativeAudioEngine` — که در استور ذخیره می‌شد — هیچ UI‌ای نداشت.
 *
 * این صفحه فقط *بازچینش* نیست: همه از همان یک استور می‌خوانند و می‌نویسند،
 * پس هر تغییری این‌جا همان لحظه در پاپ‌آورهای قدیمی هم دیده می‌شود.
 *
 * تنظیم‌های سمتِ سرور (ترتیبِ Providerهای متن، سقفِ دانلودِ سرور، کلیدها)
 * فقط‌خواندنی‌اند: جای‌شان `.env` سرور است و از ویزاردِ راه‌اندازی عوض می‌شوند.
 * ساختنِ یک API تازه برای ویرایششان یعنی دو منبعِ حقیقت که باید هم‌زمان
 * نگه داشته شوند.
 */

interface Props {
  /** باز کردنِ ویزاردِ راه‌اندازی و کلیدها (`?setup=1`) */
  onSetup: () => void
  /** صفحه‌ی «آدرس سرور» — فقط در اپ نیتیو معنا دارد */
  onServer: () => void
}

/** آنچه از `/api/health` لازم داریم — عمداً کم و اختیاری تا خطا نکند */
interface HealthInfo {
  ok?: boolean
  audioSources?: string[]
  proxy?: string
  youtube?: { cookies?: boolean; poToken?: boolean; jsRuntime?: string | boolean }
  features?: {
    lyrics?: boolean
    geniusLyrics?: boolean
    fileRetentionDays?: number
  }
  intranet?: { cached?: { files?: number; bytes?: number } }
}

/**
 * کلیدهایی که «بازگشت به پیش‌فرض» پاک می‌کند.
 *
 * عمداً فهرستِ صریح است و نه پیمایشِ همه‌ی `localStorage`: کلیدهای داده‌ای
 * (`search:history`، `recent:played`، `offline:pinned`، `server:base`) نباید
 * با یک کلیک بروند — آن‌ها *محتوایند*، نه تنظیم. پاک‌کردنشان کنشِ جدا در
 * بخشِ «داده» است، با توضیحِ خودش.
 */
const SETTING_KEYS = [
  'theme',
  'quality',
  'lang',
  'ui:liquidGlass',
  'ui:reduceMotion',
  'audio:normalize',
  'audio:crossfade',
  'audio:eqBands',
  'audio:tone',
  'audio:balance',
  'audio:spatial',
  'audio:nativeEngine',
  'audio:boost',
  'downloads:maxConcurrent',
  'privacy:errorReports',
  'library:view',
  'library:sort',
  'player:volume',
  'player:resume',
]

export default function SettingsView({ onSetup, onServer }: Props) {
  const { t, lang, setLang } = useI18n()

  /*
   * selector به‌جای destructureِ کلِ استور: این صفحه ~۱۵ کنترل دارد و با
   * `useSettings()` هر تغییرِ یک کلید، کلِ صفحه را رندرِ دوباره می‌کند —
   * همان چیزی که `TabBar` با یک کامنتِ صریح از آن پرهیز کرده.
   */
  const theme = useSettings((s) => s.theme)
  const setTheme = useSettings((s) => s.setTheme)
  const liquidGlass = useSettings((s) => s.liquidGlass)
  const setLiquidGlass = useSettings((s) => s.setLiquidGlass)
  const reduceMotion = useSettings((s) => s.reduceMotion)
  const setReduceMotion = useSettings((s) => s.setReduceMotion)
  const quality = useSettings((s) => s.quality)
  const setQuality = useSettings((s) => s.setQuality)
  const normalize = useSettings((s) => s.normalize)
  const setNormalize = useSettings((s) => s.setNormalize)
  const boost = useSettings((s) => s.boost)
  const setBoost = useSettings((s) => s.setBoost)
  const crossfade = useSettings((s) => s.crossfade)
  const setCrossfade = useSettings((s) => s.setCrossfade)
  const eqBands = useSettings((s) => s.eqBands)
  const setEqBands = useSettings((s) => s.setEqBands)
  const eqEnabled = useSettings((s) => s.eqEnabled)
  const setEqEnabled = useSettings((s) => s.setEqEnabled)
  const spatialAudio = useSettings((s) => s.spatialAudio)
  const setSpatialAudio = useSettings((s) => s.setSpatialAudio)
  const nativeEngine = useSettings((s) => s.nativeAudioEngine)
  const setNativeEngine = useSettings((s) => s.setNativeAudioEngine)
  const maxConcurrent = useSettings((s) => s.maxConcurrentDownloads)
  const setMaxConcurrent = useSettings((s) => s.setMaxConcurrentDownloads)
  const errorReporting = useSettings((s) => s.errorReporting)
  const setErrorReporting = useSettings((s) => s.setErrorReporting)

  const sleepAt = usePlayer((s) => s.sleepAt)
  const setSleepTimer = usePlayer((s) => s.setSleepTimer)
  const searchHistory = useSearchHistory((s) => s.items)
  const clearSearchHistory = useSearchHistory((s) => s.clear)
  const recent = useRecent((s) => s.items)
  const clearRecent = useRecent((s) => s.clear)
  const pingedCount = useOffline((s) => Object.keys(s.items).length)
  const unpin = useOffline((s) => s.unpin)
  const finishedJobs = useDownloads((s) => s.jobs.filter((j) => isDone(j.status)).length)
  const clearFinished = useDownloads((s) => s.clearFinished)

  const [health, setHealth] = useState<HealthInfo | null>(null)
  /*
   * حالتِ اولیه بر اساسِ وجودِ سرور تعیین می‌شود، نه همیشه `loading`.
   *
   * در حالتِ mock هیچ سروری نیست و effect پایین زودتر return می‌کند؛ اگر
   * مقدارِ اولیه `loading` باشد، «در حال بررسی…» تا ابد روی صفحه می‌ماند و
   * کاربر فکر می‌کند سرورش خراب است.
   */
  const [healthState, setHealthState] = useState<'loading' | 'ready' | 'unreachable'>(() =>
    serverBase() || isNativeApp() ? 'loading' : 'unreachable',
  )
  const [setup, setSetup] = useState<SetupState | null>(null)
  const [storage, setStorage] = useState<number | null>(null)
  const [version, setVersion] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const native = isNativeApp()
  /** آیا سروری در کار است؟ در حالتِ demo/mock نه */
  const hasServer = Boolean(serverBase()) || native

  /*
   * وضعیتِ سرور.
   *
   * در حالتِ mock اصلاً پرسیده نمی‌شود: آن‌جا داده داخلِ خودِ مرورگر ساخته
   * می‌شود و سروری نیست — پرسیدن یعنی یک درخواستِ شکست‌خورده که فقط پیامِ
   * «سرور جواب نمی‌دهد» را بی‌دلیل نشان می‌دهد. همان درسی که `App` برای
   * `fetchSetupState` گرفته.
   */
  useEffect(() => {
    if (!serverBase() && !isNativeApp()) return
    let alive = true
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), 6000)
    fetch(apiUrl('/api/health'), { signal: ctrl.signal })
      .then((r) => (r.ok ? r.json() : null))
      .then((body: HealthInfo | null) => {
        if (!alive) return
        setHealth(body)
        setHealthState(body ? 'ready' : 'unreachable')
      })
      .catch(() => {
        if (alive) setHealthState('unreachable')
      })
      .finally(() => clearTimeout(timer))
    return () => {
      alive = false
      clearTimeout(timer)
      ctrl.abort()
    }
  }, [])

  // چک‌لیستِ محیطِ سرور (ffmpeg، PO Token، کوکی‌ها…) — همان چیزی که ویزارد
  // می‌خواند، این‌جا فقط نمایشی
  useEffect(() => {
    let alive = true
    void fetchSetupState().then((s) => {
      if (alive) setSetup(s)
    })
    return () => {
      alive = false
    }
  }, [])

  useEffect(() => {
    if (typeof navigator === 'undefined' || !navigator.storage?.estimate) return
    navigator.storage
      .estimate()
      .then((est) => setStorage(est.usage ?? null))
      .catch(() => setStorage(null))
  }, [])

  useEffect(() => {
    if (!native) return
    void nativeAppInfo().then((info) => setVersion(info?.versionName ?? null))
  }, [native])

  /**
   * بالا بردنِ سقف باید همین لحظه اثر کند.
   *
   * `drainQueue` را فقط رویدادهای خودِ صف صدا می‌زنند، پس بدونِ این یک ترک
   * «در انتظار» تا رویدادِ بعدی معطل می‌ماند و کاربر فکر می‌کند تنظیم کار
   * نکرده. پایین آوردن عمداً کاری نمی‌کند: کشتنِ دانلودِ نیمه‌کاره بدتر از
   * تمام‌شدنش با چند اتصالِ اضافه است.
   */
  const stepMaxConcurrent = useCallback(
    (delta: number) => {
      // مقدارِ فعلی از خودِ استور خوانده می‌شود نه از closureِ رندر: دکمه‌های
      // −/+ به‌سرعت پشت‌سرهم زده می‌شوند و React بینِ دو کلیکِ هم‌فریم رندر
      // نمی‌کند — با مقدارِ کهنه، دو ضربه‌ی «+» یکی حساب می‌شد
      const current = useSettings.getState().maxConcurrentDownloads
      const next = Math.max(
        MIN_CONCURRENT_DOWNLOADS,
        Math.min(MAX_CONCURRENT_DOWNLOADS, current + delta),
      )
      if (next === current) return
      setMaxConcurrent(next)
      if (next > current) useDownloads.getState().pump()
    },
    [setMaxConcurrent],
  )

  const clearPins = useCallback(async () => {
    setBusy(true)
    try {
      for (const item of Object.values(useOffline.getState().items)) {
        await unpin(item)
      }
    } finally {
      setBusy(false)
    }
  }, [unpin])

  const resetSettings = useCallback(() => {
    for (const key of SETTING_KEYS) removeStored(key)
    // ری‌لود ساده‌ترین راهِ درست است: استورها، سرویس‌ورکر و موتورِ صدا همه در
    // لحظه‌ی بالا آمدن مقدارها را خوانده‌اند و نیمه‌عوض‌کردنشان فقط باگ می‌سازد
    location.reload()
  }, [])

  const engineLabels: Record<NativeAudioEngineMode, string> = {
    auto: t.nativeEngineAuto,
    on: t.nativeEngineOn,
    off: t.nativeEngineOff,
  }

  const eqPresetLabels: Record<EqPresetName, string> = {
    FLAT: t.eqPresetFlat,
    ACOUSTIC: t.eqPresetAcoustic,
    BASS_BOOST: t.eqPresetBassBoost,
    BASS_CUT: t.eqPresetBassCut,
    VOCAL: t.eqPresetVocal,
    TREBLE_BOOST: t.eqPresetTrebleBoost,
    TREBLE_CUT: t.eqPresetTrebleCut,
    LOUDNESS: t.eqPresetLoudness,
    SPOKEN_WORD: t.eqPresetSpokenWord,
    ELECTRONIC: t.eqPresetElectronic,
    ROCK: t.eqPresetRock,
    HIP_HOP: t.eqPresetHipHop,
    JAZZ: t.eqPresetJazz,
    CLASSICAL: t.eqPresetClassical,
    SMALL_SPEAKERS: t.eqPresetSmallSpeakers,
    LATE_NIGHT: t.eqPresetLateNight,
    CUSTOM: t.eqCustom,
  }

  const ready = (value: boolean | undefined) => (value ? t.available : t.unavailable)

  return (
    <div className="rise space-y-4 pb-4">
      <header>
        <h1 className="text-2xl font-black sm:text-3xl">{t.settings}</h1>
        <p className="mt-1 text-xs text-muted">{t.settingsSubtitle}</p>
      </header>

      {/* ---------- ظاهر ---------- */}
      <Section title={t.settingsAppearance} icon={<SlidersIcon className="size-4 text-muted-2" />}>
        <SegmentedRow
          label={t.theme}
          hint={t.themeAutoHint}
          value={theme}
          onChange={setTheme}
          options={[
            { value: 'dark', label: t.themeDark },
            { value: 'light', label: t.themeLight },
            { value: 'system', label: t.themeAuto },
          ]}
        />
        <Divider />
        <SegmentedRow
          label={t.language}
          value={lang}
          onChange={setLang}
          options={[
            { value: 'fa', label: 'فارسی' },
            { value: 'en', label: 'English' },
          ]}
        />
        <Divider />
        <ToggleRow
          label={t.liquidGlass}
          hint={t.liquidGlassHint}
          checked={liquidGlass}
          onChange={setLiquidGlass}
        />
        <Divider />
        <ToggleRow
          label={t.reduceMotion}
          hint={t.reduceMotionHint}
          checked={reduceMotion}
          onChange={setReduceMotion}
        />
      </Section>

      {/* ---------- پخش و صدا ---------- */}
      <Section title={t.settingsPlayback} icon={<SlidersIcon className="size-4 text-muted-2" />}>
        <SegmentedRow
          label={t.defaultQuality}
          hint={t.defaultQualityHint}
          value={quality}
          onChange={setQuality}
          options={[
            ...MP3_QUALITIES.map((q) => ({ value: q.id, label: digits(q.kbps, lang) })),
            ...CODEC_QUALITIES.map((q) => ({ value: q.id, label: q.label })),
            { value: 'original' as Quality, label: t.qualityOriginal },
          ]}
        />
        <Divider />
        <ToggleRow label={t.normalize} hint={t.normalizeHint} checked={normalize} onChange={setNormalize} />
        <Divider />
        <SliderRow
          label={t.boost}
          hint={t.boostHint}
          value={boost}
          max={MAX_BOOST_DB}
          format={(v) => (v === 0 ? t.boostOff : t.boostValue(v))}
          onChange={setBoost}
        />
        <SliderRow
          label={t.crossfade}
          value={crossfade}
          max={MAX_CROSSFADE}
          format={(v) => (v === 0 ? t.crossfadeOff : t.crossfadeValue(v))}
          onChange={setCrossfade}
        />
        <Divider />
        <ToggleRow
          label={t.equalizer}
          hint={t.equalizerHint}
          checked={eqEnabled}
          onChange={setEqEnabled}
        />
        <SegmentedRow
          label={t.eqPreset}
          value={matchingPreset(eqBands)}
          disabled={!eqEnabled}
          onChange={(nextPreset) => {
            const bands = EQ_PRESETS_DB[nextPreset]
            if (bands) setEqBands([...bands])
            if (!eqEnabled) setEqEnabled(true)
          }}
          options={EQ_PRESET_ORDER.filter((preset) => preset !== 'CUSTOM').map((preset) => ({
            value: preset,
            label: eqPresetLabels[preset],
          }))}
        />
        <Divider />
        <ToggleRow
          label={t.spatialAudio}
          checked={spatialAudio}
          onChange={setSpatialAudio}
          // روی وب گرافِ Web Audio ممکن است نداشته باشیم؛ بی‌توضیح گذاشتنش
          // یعنی کاربر فکر کند خراب است
          hint={engineHint(spatialAudio, t)}
        />
        {sleepAt !== null && (
          <>
            <Divider />
            <Row label={t.sleepActive}>
              <button
                onClick={() => setSleepTimer(null)}
                className="shrink-0 rounded-full border border-line px-3 py-1.5 text-[11px] text-muted transition hover:text-fg"
              >
                {t.cancel}
              </button>
            </Row>
          </>
        )}
        {/*
          موتورِ نیتیو فقط داخلِ اپِ اندروید معنا دارد — در مرورگر WebViewی
          وجود ندارد که بخواهد روشن/خاموش شود.
        */}
        {native && (
          <>
            <Divider />
            <SegmentedRow
              label={t.nativeAudioEngine}
              hint={t.nativeEngineHint}
              value={nativeEngine}
              onChange={setNativeEngine}
              options={[
                { value: 'auto', label: engineLabels.auto },
                { value: 'on', label: engineLabels.on },
                { value: 'off', label: engineLabels.off },
              ]}
            />
          </>
        )}
      </Section>

      {/* ---------- دانلود و آفلاین ---------- */}
      <Section title={t.settingsDownloads} icon={<DownloadIcon className="size-4 text-muted-2" />}>
        <StepperRow
          label={t.maxConcurrentDownloads}
          hint={t.maxConcurrentDownloadsHint}
          value={maxConcurrent}
          min={MIN_CONCURRENT_DOWNLOADS}
          max={MAX_CONCURRENT_DOWNLOADS}
          onStep={stepMaxConcurrent}
        />
        <p className="pb-1 text-[11px] text-muted-2">{retentionText(health, t, lang)}</p>
        <Divider />
        <ConfirmRow
          label={t.clearFinishedDownloads}
          hint={finishedJobs > 0 ? digits(finishedJobs, lang) : t.nothingToClear}
          actionLabel={t.clear}
          confirmLabel={t.clearFinishedDownloads}
          tone="danger"
          busy={finishedJobs === 0}
          onAction={clearFinished}
        />
        <Divider />
        <Row label={t.offlinePins} hint={t.offlinePinsHint}>
          <div className="flex shrink-0 items-center gap-2">
            <span className="text-[11px] tabular-nums text-muted-2">
              {digits(pingedCount, lang)}
            </span>
            <button
              onClick={() => void clearPins()}
              disabled={pingedCount === 0 || busy}
              className="rounded-full border border-line px-3 py-1.5 text-[11px] text-muted transition enabled:hover:border-danger/50 enabled:hover:text-danger disabled:opacity-40"
            >
              {t.unpinAll}
            </button>
          </div>
        </Row>
      </Section>

      {/* ---------- متن ---------- */}
      <Section title={t.settingsLyrics} icon={<LyricsIcon className="size-4 text-muted-2" />}>
        {/*
          وضعیت فقط وقتی نمایش داده می‌شود که سروری باشد. در حالتِ demo
          `health` هیچ‌وقت نمی‌آید و «آماده نیست» می‌شد — یعنی یک هشدارِ دروغ
          درباره‌ی چیزی که اصلاً سروری برای داشتنش وجود ندارد.
        */}
        {hasServer && (
          <>
            <StatusRow
              label={t.settingsLyrics}
              value={ready(health?.features?.lyrics)}
              tone={health?.features?.lyrics ? 'ok' : 'off'}
            />
            <StatusRow
              label="Genius"
              value={ready(health?.features?.geniusLyrics)}
              tone={health?.features?.geniusLyrics ? 'ok' : 'off'}
            />
          </>
        )}
        <p className={`${hasServer ? 'pt-2' : ''} text-[11px] leading-5 text-muted-2`}>{t.lyricsProviderNote}</p>
        <p className="text-[11px] leading-5 text-muted-2">{t.lyricsGlobalNote}</p>
        {/*
          قبلاً این‌جا یک دکمه‌ی «پاک‌کردنِ همه‌ی انتخاب‌ها» بود. سرور فقط
          اندپوینتِ per-track دارد (`?track_id=`) و فهرست‌کردن ندارد، پس آن
          دکمه هیچ کاری نمی‌کرد. صریح گفته می‌شود بهتر از یک دکمه‌ی بی‌اثر است.
        */}
        <p className="pt-1 text-[11px] leading-5 text-muted-2">{t.lyricsClearUnavailable}</p>
      </Section>

      {/* ---------- داده و حریم خصوصی ---------- */}
      <Section title={t.settingsData} icon={<TrashIcon className="size-4 text-muted-2" />}>
        <ConfirmRow
          label={t.searchHistory}
          hint={searchHistory.length > 0 ? digits(searchHistory.length, lang) : t.nothingToClear}
          actionLabel={t.clearAll}
          confirmLabel={t.clear}
          busy={searchHistory.length === 0}
          onAction={clearSearchHistory}
        />
        <Divider />
        <ConfirmRow
          label={t.continueListening}
          hint={recent.length > 0 ? digits(recent.length, lang) : t.nothingToClear}
          actionLabel={t.clearAll}
          confirmLabel={t.clear}
          busy={recent.length === 0}
          onAction={clearRecent}
        />
        <Divider />
        <ConfirmRow
          label={t.resumePoint}
          actionLabel={t.clear}
          // `player:resume` را `close()` هم پاک می‌کند، ولی آن کل صف را
          // می‌بندد و پخشِ جاری را قطع می‌کند — این‌جا فقط خودِ کلید می‌رود.
          // تأییدِ دو مرحله‌ای لازم نیست: پاک‌کردنش بی‌خطر است و با یک بار
          // گوش‌دادن دوباره پر می‌شود
          onAction={() => removeStored('player:resume')}
        />
        <Divider />
        <ToggleRow
          label={t.errorReporting}
          hint={t.errorReportingHint}
          checked={errorReporting}
          onChange={setErrorReporting}
        />
        <Divider />
        <StatusRow
          label={t.storageUsed}
          value={storage === null ? t.storageUnknown : bytes(storage, lang)}
        />
        {native && (
          <>
            <Divider />
            <ConfirmRow
              label={t.checkUpdate}
              hint={t.updateBannerReset}
              actionLabel={t.clear}
              onAction={() => removeStored('update:dismissed')}
            />
          </>
        )}
        <Divider />
        <ConfirmRow
          label={t.resetSettings}
          hint={t.resetSettingsHint}
          actionLabel={t.resetAll}
          confirmLabel={t.resetConfirm}
          tone="danger"
          onAction={resetSettings}
        />
      </Section>

      {/* ---------- سرور و راه‌اندازی ---------- */}
      <Section title={t.settingsServer} icon={<SlidersIcon className="size-4 text-muted-2" />}>
        {/*
          در حالتِ mock اصلاً چیزی نشان داده نمی‌شود: آن‌جا داده داخلِ خودِ
          مرورگر ساخته می‌شود و سروری وجود ندارد، پس «سرور جواب نمی‌دهد» یک
          هشدارِ دروغ است — نه یک وضعیتِ واقعی. همان تصمیمی که `Footer` برای
          لینکِ راه‌اندازی گرفته.
        */}
        {hasServer && healthState === 'loading' && (
          <StatusRow label={t.serverStatus} value={t.serverChecking} />
        )}
        {hasServer && healthState === 'unreachable' && (
          <StatusRow label={t.serverStatus} value={t.serverUnreachable} tone="warn" />
        )}
        {hasServer && healthState === 'ready' && health && (
          <>
            <StatusRow label={t.ffmpeg} value={health.features ? t.available : t.unavailable} tone={health.features ? 'ok' : 'warn'} />
            <StatusRow label={t.jsRuntime} value={health.youtube?.jsRuntime ? t.available : t.unavailable} tone={health.youtube?.jsRuntime ? 'ok' : 'warn'} />
            <StatusRow label={t.poToken} value={ready(health.youtube?.poToken)} tone={health.youtube?.poToken ? 'ok' : 'warn'} />
            <StatusRow label={t.cookies} value={ready(health.youtube?.cookies)} tone={health.youtube?.cookies ? 'ok' : 'warn'} />
            <StatusRow label={t.proxy} value={health.proxy ?? t.unavailable} tone={health.proxy ? 'ok' : 'off'} />
            {health.audioSources && (
              <StatusRow label={t.audioSources} value={health.audioSources.join('، ')} />
            )}
            {setup && (
              <>
                <Divider />
                <StatusRow label={t.internet} value={ready(setup.env.internet)} tone={setup.env.internet ? 'ok' : 'warn'} />
              </>
            )}
          </>
        )}
        {native && (
          <>
            <Divider />
            <Row label={t.serverAddress} hint={isLocalServer() ? t.serverLocalBadge : undefined}>
              <div className="flex shrink-0 items-center gap-2">
                <span className="max-w-40 truncate text-[11px] text-muted-2" dir="ltr">
                  {serverBase() || '—'}
                </span>
                <button
                  onClick={onServer}
                  className="rounded-full border border-line px-3 py-1.5 text-[11px] text-muted transition hover:text-fg"
                >
                  {t.serverChange}
                </button>
              </div>
            </Row>
          </>
        )}
        <Divider />
        <LinkRow label={t.serverSetupLink} onClick={onSetup} />
      </Section>

      {/* ---------- درباره ---------- */}
      <Section title={t.settingsAbout} icon={<CheckIcon className="size-4 text-muted-2" />}>
        {/*
          نسخه فقط در اپِ نیتیو خوانده می‌شود: در مرورگر «نسخه» یعنی همان
          بسته‌ای که سرویس‌ورکر کش کرده، و عددِ نسخه‌ی پکیج به کاربر چیزی
          نمی‌گوید. این‌جا فقط چیزی که خودِ گوشی می‌داند نشان داده می‌شود.
        */}
        {native && <StatusRow label={t.appVersion} value={version ?? t.notInstalled} />}
        <p className="pt-2 text-[11px] leading-5 text-muted-2">
          <OfflineIcon className="me-1 inline size-3.5 align-[-2px]" />
          {t.builtBy}{' '}
          <a
            href="https://github.com/mahan-mgn"
            target="_blank"
            rel="noreferrer"
            className="text-accent transition hover:brightness-125"
          >
            mahan-mgn
          </a>
        </p>
      </Section>
    </div>
  )
}

/** متنِ «نگهداری فایل روی سرور» — عددش از سرور می‌آید، نه از تنظیماتِ محلی */
function retentionText(
  health: HealthInfo | null,
  t: ReturnType<typeof useI18n.getState>['t'],
  lang: string,
): string {
  const days = health?.features?.fileRetentionDays
  if (typeof days !== 'number') return ''
  return `${t.serverRetention}: ${days === 0 ? t.available : t.retentionDays(Math.round(days))}${
    days === 0 ? '' : ` · ${digits(days, lang)}`
  }`
}

/** راهنمای گرافِ صدا — فقط وقتی معنا دارد که چیزی برای گفتن باشد */
function engineHint(_on: boolean, t: ReturnType<typeof useI18n.getState>['t']): string | undefined {
  if (isNativeApp() || typeof window === 'undefined') return undefined
  const Ctx =
    (window as unknown as { AudioContext?: unknown; webkitAudioContext?: unknown }).AudioContext ??
    (window as unknown as { webkitAudioContext?: unknown }).webkitAudioContext
  return Ctx ? undefined : t.audioGraphMissing
}
