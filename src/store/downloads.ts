import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import { api } from '../lib/api'
import { useI18n } from '../lib/i18n'
import type { DownloadProgress, JobStatus, Quality, Track } from '../lib/types'
import { useNet } from './net'
import { useToasts } from './toasts'

export interface Job {
  id: string
  /**
   * شناسه‌ی جاب سمت سرور — از اولین پیامِ SSE بعد از POST می‌آید. لایک و
   * ثبتِ پخش باید با همین شناسه زده شوند؛ شناسه‌ی محلیِ بالا سرور آن را
   * نمی‌شناسد و درخواست ۴۰۴ می‌خورد.
   */
  jobId?: string
  batchId: string
  track: Track
  quality: Quality
  status: JobStatus
  percent: number
  error?: string
  fileUrl?: string
  /** همان فایل برای پخش در مرورگر */
  streamUrl?: string
  format?: string
  /** فایل سالم است ولی AcoustID ترک دیگری را شناخته */
  warning?: string
  /** فایل .lrc اگر متن هم‌زمان‌شده پیدا شده باشد */
  lyricsUrl?: string
  /** هم‌ترازیِ بلندی که سرور اندازه گرفته (دسی‌بل) */
  gainDb?: number
  /** نسخه‌ای که کاربر دستی انتخاب کرده — resolver دور زده می‌شود */
  candidateUrl?: string
  createdAt: number
  /** زمان شروع دانلود واقعی */
  startedAt?: number
  /** زمان رسیدن به وضعیت نهایی — پایه‌ی محاسبه‌ی ETA */
  finishedAt?: number
}

/**
 * یک بچ = یک چیزی که کاربر ثبت کرده (آلبوم، پلی‌لیست، یا یک ترک تکی).
 * صف بر همین اساس گروه‌بندی می‌شود، نه ترک‌به‌ترک.
 */
export interface Batch {
  id: string
  title: string
  artworkUrl: string | null
  quality: Quality
  createdAt: number
}

export const isActive = (s: JobStatus) =>
  s === 'queued' || s === 'searching' || s === 'downloading' || s === 'tagging'

/**
 * کاری که هست ولی جلو نمی‌رود — منتظرِ برگشتنِ اینترنتِ بین‌الملل.
 *
 * عمداً «فعال» حساب نمی‌شود: نه اسپینر می‌خواهد (چیزی در جریان نیست) و نه در
 * تخمینِ زمان می‌آید (زمانش نامعلوم است و واردکردنش هر ETAی را بی‌معنی
 * می‌کرد). ولی «تمام‌شده» هم نیست، و همین تفاوت است که `finished` را درست
 * نگه می‌دارد.
 */
export const isWaiting = (s: JobStatus) => s === 'deferred'

export const isDone = (s: JobStatus) => s === 'ready'

/**
 * کاری که شناسه‌ی (ترک، کیفیت)‌اش هنوز آزاد نشده — در جریان یا منتظرِ
 * اینترنت. dedupe باید روی همین باشد، نه فقط فعال‌ها: وگرنه دوباره‌کلیکِ
 * «دانلود همه» حینِ قطعی، یک ستِ کامل دومی ثبت می‌کرد و وقتی اینترنت
 * برمی‌گشت هر دو ست با هم دانلود می‌شدند.
 */
export const isUnfinished = (s: JobStatus) => isActive(s) || isWaiting(s)

/** کدِ خطای شناخته‌شده → رشته‌ی ترجمه‌شده؛ پیام‌های ناشناخته همان‌طور نشان داده می‌شوند */
export function jobErrorText(
  error: string | undefined,
  t: { connectionLost: string; unknownError: string },
): string {
  if (!error) return t.unknownError
  if (error === 'connection-lost') return t.connectionLost
  if (error === 'unknown-error') return t.unknownError
  return error
}

/**
 * پیامِ «رفت تو صف».
 *
 * در حالتِ اینترانت همان صف معنیِ دیگری دارد و باید صریح گفته شود: دانلود
 * *شروع نمی‌شود* تا اینترنتِ بین‌الملل برگردد. بدون این، کاربر چند دقیقه به
 * نواری نگاه می‌کند که تکان نمی‌خورد و نتیجه می‌گیرد برنامه گیر کرده.
 */
function queuedToast(title: string): void {
  const { t } = useI18n.getState()
  const intranet = useNet.getState().layer === 'internet'
  useToasts.getState().push(intranet ? t.intranetDownload : t.toastQueued(title), 'info')
}

/** کنسل‌کننده‌ی هر کار، بیرون از state نگه داشته می‌شود */
const cancelers = new Map<string, () => void>()

/** سقف دانلودهای فعال هم‌زمان در فرانت — جلوگیری از اشباع ۶ سوکت HTTP/1.1 مرورگر */
const MAX_CONCURRENT_ACTIVE_DOWNLOADS = 3

let batchSeq = 0

export interface BatchView {
  batch: Batch
  jobs: Job[]
  total: number
  done: number
  active: number
  /** کارهایی که منتظرِ برگشتنِ اینترنت‌اند */
  waiting: number
  failed: number
  /** ۰ تا ۱۰۰ روی کل بچ */
  percent: number
  /** ثانیه‌ی باقی‌مانده، یا null اگر هنوز قابل تخمین نیست */
  etaSeconds: number | null
  finished: boolean
}

interface DownloadState {
  jobs: Job[]
  batches: Batch[]
  collapsed: boolean
  enqueue: (track: Track, quality: Quality, batch?: Partial<Batch>) => void
  enqueueMany: (tracks: Track[], quality: Quality, batch: Partial<Batch>) => void
  /** دانلود دوباره‌ی یک ترک از نسخه‌ای که کاربر خودش انتخاب کرده */
  pickSource: (track: Track, quality: Quality, candidateUrl: string) => void
  cancel: (jobId: string) => void
  retry: (jobId: string) => void
  remove: (jobId: string) => void
  dismissBatch: (batchId: string) => void
  clearFinished: () => void
  setCollapsed: (v: boolean) => void
  /**
   * بعد از رفرشِ صفحه: به جاب‌های نیمه‌کاره‌ی دارای شناسه‌ی سروری دوباره وصل
   * می‌شود و بقیه را خطای قابلِ retry می‌دهد. توسط persist بعد از rehydrate
   * صدا زده می‌شود — بخشی از API عمومیِ استور نیست.
   */
  resumeStaleJobs: () => void
}

export const useDownloads = create<DownloadState>()(
  persist(
    (set, get) => {
  function drainQueue() {
    const currentJobs = get().jobs
    // تعداد کارهای فعال که همین الان اتصال زنده با سرور دارند
    const runningCount = currentJobs.filter(
      (j) => cancelers.has(j.id) && isActive(j.status),
    ).length
    const availableSlots = MAX_CONCURRENT_ACTIVE_DOWNLOADS - runningCount
    if (availableSlots <= 0) return

    const pending = currentJobs.filter((j) => j.status === 'queued' && !cancelers.has(j.id))
    for (const nextJob of pending.slice(0, availableSlots)) {
      start(nextJob)
    }
  }

  /**
   * هر پیام پیشرفت — چه از `download` تازه و چه از `attach` بعد از رفرش — از
   * همین‌جا به state می‌رود. `silent` برای resume اولیه است: اگر بیست کار
   * نیمه‌کاره بعد از رفرش یک‌جا «آماده» شوند، بیست توست پشت‌سرهم آزاردهنده است.
   */
  function handleProgress(id: string, p: DownloadProgress, silent = false) {
    set({
      jobs: get().jobs.map((j) =>
        j.id === id
          ? {
              ...j,
              status: p.status,
              percent: p.percent,
              error: p.error,
              jobId: p.jobId ?? j.jobId,
              fileUrl: p.fileUrl,
              streamUrl: p.streamUrl,
              format: p.format ?? j.format,
              warning: p.warning ?? j.warning,
              lyricsUrl: p.lyricsUrl ?? j.lyricsUrl,
              gainDb: p.gainDb ?? j.gainDb,
              startedAt: p.status === 'downloading' && !j.startedAt ? Date.now() : j.startedAt,
              finishedAt: p.status === 'ready' ? Date.now() : j.finishedAt,
            }
          : j,
      ),
    })
    const { t } = useI18n.getState()
    if (p.status === 'ready') {
      cancelers.delete(id)
      if (!silent) {
        /*
         * «آماده شد» تا امروز فقط خبر بود و بن‌بست: فایل روی دیسک نشسته بود
         * و کاربر باید خودش راهش را به کتابخانه پیدا می‌کرد. حالا همان توست
         * مقصدش را هم دارد.
         *
         * ناوبری از طریق رویداد است نه ایمپورت: این استور نه از ری‌اکت خبر
         * دارد نه باید داشته باشد، و `App` تنها جایی است که می‌داند «رفتن به
         * کتابخانه» یعنی چه.
         */
        const current = get().jobs.find((j) => j.id === id)
        useToasts.getState().push(t.toastReady(current?.track.title ?? ''), 'success', {
          label: t.goToLibrary,
          run: () => window.dispatchEvent(new CustomEvent('musicbazi:open-library')),
        })
      }
      drainQueue()
    } else if (p.status === 'error') {
      cancelers.delete(id)
      if (!silent) {
        const current = get().jobs.find((j) => j.id === id)
        useToasts.getState().push(t.toastFailed(current?.track.title ?? ''), 'error')
      }
      drainQueue()
    } else if (p.status === 'canceled') {
      cancelers.delete(id)
      drainQueue()
    }
  }

  function start(job: Job) {
    const req = { track: job.track, quality: job.quality, candidateUrl: job.candidateUrl }
    const stop = api.download(req, (p) => handleProgress(job.id, p))
    cancelers.set(job.id, stop)
  }

  function makeBatch(seed: Partial<Batch>, quality: Quality, fallbackTitle: string): Batch {
    return {
      id: seed.id ?? `batch-${++batchSeq}-${Date.now()}`,
      title: seed.title ?? fallbackTitle,
      artworkUrl: seed.artworkUrl ?? null,
      quality,
      createdAt: Date.now(),
    }
  }

  function add(
    track: Track,
    quality: Quality,
    batch: Batch,
    quiet = false,
    candidateUrl?: string,
  ): boolean {
    // کیفیت هم بخشی از هویت کار است — سرور هم با همین جفت (ترک، کیفیت) کش می‌کند.
    // بدون آن، گرفتنِ همان ترک با کیفیت دیگر «قبلاً در صف است» می‌گرفت.
    // کارِ معوق هم حساب می‌شود وگرنه حینِ قطعی، دوباره‌ثبتِ همان ترک یک جابِ
    // دوم می‌ساخت که بعد از برگشتنِ اینترنت موازی با اولی دانلود می‌شد.
    const existing = get().jobs.find(
      (j) => j.track.id === track.id && j.quality === quality && isUnfinished(j.status),
    )
    if (existing) {
      if (!quiet) {
        useToasts.getState().push(useI18n.getState().t.toastAlready(track.title), 'info')
      }
      return false
    }
    const job: Job = {
      id: `job-${track.id}-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      batchId: batch.id,
      track,
      quality,
      status: 'queued',
      percent: 0,
      candidateUrl,
      createdAt: Date.now(),
    }
    set({ jobs: [...get().jobs, job] })
    drainQueue()
    return true
  }

  return {
    jobs: [],
    batches: [],
    collapsed: false,

    enqueue: (track, quality, seed = {}) => {
      const batch = makeBatch(
        { artworkUrl: track.artworkUrl, ...seed },
        quality,
        track.album ?? track.title,
      )
      if (!add(track, quality, batch)) return
      set({ batches: [batch, ...get().batches], collapsed: false })
      queuedToast(track.title)
    },

    enqueueMany: (tracks, quality, seed) => {
      if (!tracks.length) return
      const batch = makeBatch(seed, quality, tracks[0].album ?? tracks[0].title)
      const currentJobs = get().jobs
      const newJobs: Job[] = []
      const seen = new Set<string>()

      for (const track of tracks) {
        const key = `${track.id}-${quality}`
        if (seen.has(key)) continue
        const existing = currentJobs.find(
          (j) => j.track.id === track.id && j.quality === quality && isUnfinished(j.status),
        )
        if (existing) continue
        seen.add(key)
        newJobs.push({
          id: `job-${track.id}-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
          batchId: batch.id,
          track,
          quality,
          status: 'queued',
          percent: 0,
          createdAt: Date.now(),
        })
      }

      if (!newJobs.length) {
        // همه از قبل در صف‌اند — سکوت این‌جا یعنی کاربر فکر می‌کند دکمه کار
        // نکرده. همان پیامِ «از قبل تو صفه» که enqueue تکی می‌دهد.
        useToasts.getState().push(useI18n.getState().t.toastAlready(batch.title), 'info')
        return
      }
      set({
        jobs: [...currentJobs, ...newJobs],
        batches: [batch, ...get().batches],
        collapsed: false,
      })
      queuedToast(batch.title)
      drainQueue()
    },

    pickSource: (track, quality, candidateUrl) => {
      const batch = makeBatch({ artworkUrl: track.artworkUrl }, quality, track.title)
      // quiet نیست: اگر همین ترک همین الان در جریان باشد، کاربر باید بفهمد
      // چرا انتخابش اثر نکرد
      if (!add(track, quality, batch, false, candidateUrl)) return
      set({ batches: [batch, ...get().batches], collapsed: false })
      queuedToast(track.title)
    },

    cancel: (jobId) => {
      cancelers.get(jobId)?.()
      cancelers.delete(jobId)
      set({
        jobs: get().jobs.map((j) =>
          j.id === jobId ? { ...j, status: 'canceled', percent: 0 } : j,
        ),
      })
      drainQueue()
    },

    retry: (jobId) => {
      const job = get().jobs.find((j) => j.id === jobId)
      if (!job) return
      // اگر اتصال قبلی هنوز باز است باید بسته شود؛ وگرنه start جایگزینش می‌کرد و
      // آن EventSource تا آخر عمر صفحه بی‌صاحب باز می‌ماند
      cancelers.get(jobId)?.()
      cancelers.delete(jobId)
      const fresh: Job = {
        ...job,
        status: 'queued',
        percent: 0,
        error: undefined,
        warning: undefined,
        fileUrl: undefined,
        streamUrl: undefined,
        lyricsUrl: undefined,
        gainDb: undefined,
        // جابِ سرورِ قبلی مرده؛ تلاشِ دوباره جابِ تازه می‌سازد و شناسه‌اش با
        // اولین پیام SSE می‌آید. نگه‌داشتنِ شناسه‌ی کهنه یعنی لایک/ZIP به جابِ
        // مرده زده می‌شد.
        jobId: undefined,
        startedAt: undefined,
        finishedAt: undefined,
      }
      set({ jobs: get().jobs.map((j) => (j.id === jobId ? fresh : j)) })
      drainQueue()
    },

    remove: (jobId) => {
      cancelers.get(jobId)?.()
      cancelers.delete(jobId)
      set({ jobs: get().jobs.filter((j) => j.id !== jobId) })
      drainQueue()
    },

    dismissBatch: (batchId) => {
      get()
        .jobs.filter((j) => j.batchId === batchId)
        .forEach((j) => {
          cancelers.get(j.id)?.()
          cancelers.delete(j.id)
        })
      set({
        jobs: get().jobs.filter((j) => j.batchId !== batchId),
        batches: get().batches.filter((b) => b.id !== batchId),
      })
      drainQueue()
    },

    clearFinished: () => {
      // کارِ معوق (منتظرِ اینترنت) «تمام‌شده» نیست — پاک‌کردنش یعنی ردیفی که
      // هنوز سمت سرور زنده است از UI می‌افتد، EventSource‌اش بی‌صاحب می‌ماند
      // و وقتی آماده شد توستش برای ردیفی می‌آید که دیگر وجود ندارد.
      const kept = get().jobs.filter((j) => isUnfinished(j.status))
      for (const j of get().jobs) {
        if (!kept.some((k) => k.id === j.id) && cancelers.has(j.id)) {
          cancelers.get(j.id)?.()
          cancelers.delete(j.id)
        }
      }
      const liveBatches = new Set(kept.map((j) => j.batchId))
      set({ jobs: kept, batches: get().batches.filter((b) => liveBatches.has(b.id)) })
    },

    setCollapsed: (collapsed) => set({ collapsed }),

    resumeStaleJobs: () => {
      for (const job of get().jobs) {
        if (isDone(job.status) || job.status === 'error' || job.status === 'canceled') continue
        if (job.jobId && api.attach) {
          cancelers.set(job.id, api.attach(job.jobId, (p) => handleProgress(job.id, p, true)))
        } else {
          // جابِ بدونِ شناسه‌ی سروری یعنی POST هرگز جواب نداد — ادامه‌اش قابل
          // بازیابی نیست؛ خطای قابلِ retry می‌گیرد تا کاربر دوباره بزند
          handleProgress(job.id, { status: 'error', percent: 0, error: 'connection-lost' }, true)
        }
      }
    },
  }
},
{
  name: 'musicbazi-downloads',
      storage: createJSONStorage(() => localStorage),
      // فقط داده‌ها — اکشن‌ها و باز/بسته‌بودنِ پنل مالِ همین نشست‌اند
      partialize: (s) => ({ jobs: s.jobs, batches: s.batches }) as DownloadState,
      onRehydrateStorage: () => (state) => state?.resumeStaleJobs(),
    },
  ),
)

/**
 * کارِ مربوط به یک (ترک، کیفیت) — همان جفتی که در بقیه‌ی این استور و در سرور
 * هویتِ یک دانلود است.
 *
 * قبلاً فقط با `trackId` می‌گشت و *اولین* کار را برمی‌داشت. یعنی اگر ترکی
 * یک‌بار با ۳۲۰ گرفته شده بود و کاربر حالا همان را با ۱۲۸ می‌گرفت، ردیف
 * همچنان کارِ کهنه‌ی «آماده» را نشان می‌داد: نه نوار پیشرفتی، نه امکانِ لغو —
 * دکمه انگار هیچ کاری نکرده بود.
 *
 * بینِ چند کارِ هم‌کلید، کارِ در جریان مقدم است (همان چیزی که کاربر همین حالا
 * منتظرش است) و بعد تازه‌ترین.
 */
export function selectTrackJob(
  jobs: Job[],
  trackId: string,
  quality: Quality,
): Job | undefined {
  let best: Job | undefined
  for (const job of jobs) {
    if (job.track.id !== trackId || job.quality !== quality) continue
    if (!best) {
      best = job
      continue
    }
    const bestActive = isActive(best.status)
    const jobActive = isActive(job.status)
    if (jobActive !== bestActive) {
      if (jobActive) best = job
      continue
    }
    if (job.createdAt >= best.createdAt) best = job
  }
  return best
}

/** وضعیت دانلود یک ترک مشخص (برای رندر ردیف‌ها) */
export function useTrackJob(trackId: string, quality: Quality): Job | undefined {
  return useDownloads((s) => selectTrackJob(s.jobs, trackId, quality))
}

/** بک‌اند چند ترک را همزمان می‌برد؛ ETA بدون این ضریب چند برابر بیش‌برآورد می‌شود */
const ASSUMED_CONCURRENCY = 3

/**
 * ETA بر اساس میانگین زمان واقعیِ ترک‌های تمام‌شده‌ی همین بچ.
 * تا وقتی حداقل یکی تمام نشده تخمینی نمی‌دهیم — عدد ساختگی بدتر از نبودنش است.
 */
function estimateEta(jobs: Job[]): number | null {
  const completed = jobs.filter((j) => j.finishedAt)
  if (!completed.length) return null

  const avgMs =
    completed.reduce((sum, j) => sum + (j.finishedAt! - j.createdAt), 0) / completed.length

  const remaining = jobs.filter((j) => isActive(j.status))
  if (!remaining.length) return null

  // ترکی که نیمه‌دانلود شده، نصف کار برایش مانده
  const work = remaining.reduce((sum, j) => sum + (1 - j.percent / 100), 0)
  const lanes = Math.min(ASSUMED_CONCURRENCY, remaining.length)
  const seconds = Math.round((work / lanes) * (avgMs / 1000))
  return seconds > 0 ? seconds : null
}

/** بچ‌ها به‌همراه آمار محاسبه‌شده، تازه‌ترین اول */
export function useBatchViews(): BatchView[] {
  const jobs = useDownloads((s) => s.jobs)
  const batches = useDownloads((s) => s.batches)

  /*
   * بچی که دیگر هیچ کاری ندارد اصلاً نباید کارتی داشته باشد. `finished` روی
   * چنین بچی false می‌ماند (چون `own.length > 0` شرطِ آن است) و دکمه‌ی بستن
   * هم با همان شرط رندر می‌شود — یعنی کارتِ «۰ از ۰» تا رفرشِ صفحه روی پنل
   * می‌ماند بی‌آنکه راهی برای بستنش باشد.
   */
  return batches
    .filter((batch) => jobs.some((j) => j.batchId === batch.id))
    .map((batch) => {
      const own = jobs.filter((j) => j.batchId === batch.id)
      const done = own.filter((j) => isDone(j.status)).length
      const active = own.filter((j) => isActive(j.status)).length
      const waiting = own.filter((j) => isWaiting(j.status)).length
      const failed = own.filter((j) => j.status === 'error').length
      const percent = own.length
        ? own.reduce((sum, j) => sum + (isDone(j.status) ? 100 : j.percent), 0) / own.length
        : 0

      return {
        batch,
        jobs: own,
        total: own.length,
        done,
        active,
        waiting,
        failed,
        percent,
        etaSeconds: active ? estimateEta(own) : null,
        // بچی که فقط کارِ معوق دارد تمام نشده — بدونِ شرطِ `waiting`، کارتش
        // در حالتِ اینترانت فوراً «تمام شد» می‌گرفت درحالی‌که هیچ فایلی نیامده
        finished: own.length > 0 && active === 0 && waiting === 0,
      }
    })
}
