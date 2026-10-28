// @vitest-environment jsdom
//
// خودِ انتخاب خالص است، ولی `downloads` غیرمستقیم `i18n` را می‌آورد و آن در
// سطحِ ماژول به `document` دست می‌زند — همان قراردادی که
// `AnimatedList.dom.test.tsx` هم دنبال می‌کند.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { selectTrackJob, type Job } from './downloads'
import type { JobStatus, Quality, Track } from '../lib/types'

function track(id: string): Track {
  return {
    id,
    title: id,
    artist: 'Googoosh',
    durationMs: 200_000,
    artworkUrl: null,
    source: 'deezer',
    sourceUrl: `https://example.com/${id}`,
    previewUrl: null,
  }
}

let seq = 0
function job(trackId: string, quality: Quality, status: JobStatus, createdAt = ++seq): Job {
  return {
    id: `job-${trackId}-${quality}-${createdAt}`,
    batchId: 'b1',
    track: track(trackId),
    quality,
    status,
    percent: status === 'ready' ? 100 : 0,
    createdAt,
  }
}

/**
 * دلیلِ وجودِ این تست: `TrackRow` وضعیتش را از همین انتخاب می‌گیرد — نوار
 * پیشرفت، متنِ وضعیت، و اینکه دکمه «دانلود» باشد یا «لغو».
 *
 * انتخابِ قبلی فقط `trackId` را می‌دید و *اولین* کار را برمی‌داشت. کیفیت ولی
 * بخشی از هویتِ یک دانلود است (هم اینجا، هم در کشِ سرور)، پس گرفتنِ دوباره‌ی
 * یک ترک با کیفیتِ دیگر کارِ تازه‌ای می‌سازد — و ردیف همچنان کارِ کهنه‌ی
 * «آماده» را نشان می‌داد: انگار دکمه اصلاً کار نکرده.
 */
describe('انتخابِ کارِ یک ردیف', () => {
  it('کارِ همان کیفیت را می‌دهد، نه اولین کارِ همان ترک', () => {
    const jobs = [job('t1', '320', 'ready'), job('t1', '128', 'downloading')]
    expect(selectTrackJob(jobs, 't1', '128')?.status).toBe('downloading')
    expect(selectTrackJob(jobs, 't1', '320')?.status).toBe('ready')
  })

  it('کیفیتی که کاری ندارد، هیچ می‌دهد — نه وضعیتِ کیفیتِ دیگر', () => {
    const jobs = [job('t1', '320', 'ready')]
    expect(selectTrackJob(jobs, 't1', 'flac')).toBeUndefined()
  })

  it('ترکِ دیگری را با هم‌کیفیتی اشتباه نمی‌گیرد', () => {
    const jobs = [job('t1', '320', 'ready'), job('t2', '320', 'downloading')]
    expect(selectTrackJob(jobs, 't2', '320')?.track.id).toBe('t2')
  })

  it('بینِ چند کارِ هم‌کلید، کارِ در جریان مقدم است', () => {
    // کاربر یک‌بار گرفته و لغو کرده، حالا دوباره می‌گیرد: ردیف باید کارِ
    // زنده را نشان بدهد نه لغوشده‌ی قدیمی
    const jobs = [
      job('t1', '320', 'canceled', 1),
      job('t1', '320', 'downloading', 2),
      job('t1', '320', 'error', 3),
    ]
    expect(selectTrackJob(jobs, 't1', '320')?.status).toBe('downloading')
  })

  it('وقتی هیچ‌کدام در جریان نیستند، تازه‌ترین برنده است', () => {
    const jobs = [job('t1', '320', 'error', 1), job('t1', '320', 'ready', 2)]
    expect(selectTrackJob(jobs, 't1', '320')?.status).toBe('ready')
  })

  it('صفِ خالی چیزی نمی‌دهد', () => {
    expect(selectTrackJob([], 't1', '320')).toBeUndefined()
  })
})

describe('enqueueMany و صف کلاینت', () => {
  it('در ثبت دسته‌ای ترک‌ها، همه در استور قرار می‌گیرند', async () => {
    const { useDownloads } = await import('./downloads')
    useDownloads.setState({ jobs: [], batches: [] })
    const tracks = Array.from({ length: 6 }, (_, i) => track(`track-${i + 1}`))
    useDownloads.getState().enqueueMany(tracks, '320', { title: 'Batch 1' })

    const jobs = useDownloads.getState().jobs
    expect(jobs.length).toBe(6)
    expect(jobs.map((j) => j.track.id)).toEqual([
      'track-1',
      'track-2',
      'track-3',
      'track-4',
      'track-5',
      'track-6',
    ])
  })

  it('ترک‌های معوق (deferred) را دوباره در صف اضافه نمی‌کند', async () => {
    const { useDownloads } = await import('./downloads')
    useDownloads.setState({
      jobs: [job('t-def', '320', 'deferred')],
      batches: [{ id: 'b1', title: 'Batch', artworkUrl: null, quality: '320', createdAt: 1 }],
    })
    // تلاش برای اضافه کردن دوباره همان ترک با همان کیفیت
    useDownloads.getState().enqueue(track('t-def'), '320')
    expect(useDownloads.getState().jobs.length).toBe(1)

    // تلاش با enqueueMany
    useDownloads.getState().enqueueMany([track('t-def')], '320', { title: 'Batch 2' })
    expect(useDownloads.getState().jobs.length).toBe(1)
  })

  it('clearFinished کارهای معوق (deferred) را پاک نمی‌کند', async () => {
    const { useDownloads } = await import('./downloads')
    useDownloads.setState({
      jobs: [
        job('t-done', '320', 'ready'),
        job('t-err', '320', 'error'),
        job('t-wait', '320', 'deferred'),
      ],
      batches: [{ id: 'b1', title: 'Batch', artworkUrl: null, quality: '320', createdAt: 1 }],
    })

    useDownloads.getState().clearFinished()
    const remaining = useDownloads.getState().jobs
    expect(remaining.length).toBe(1)
    expect(remaining[0].status).toBe('deferred')
  })

  it('retry مقدار gainDb را ریست می‌کند', async () => {
    const { useDownloads } = await import('./downloads')
    const erroredJob: Job = {
      ...job('t-err', '320', 'error'),
      gainDb: -3.5,
    }
    useDownloads.setState({
      jobs: [erroredJob],
      batches: [{ id: 'b1', title: 'Batch', artworkUrl: null, quality: '320', createdAt: 1 }],
    })

    useDownloads.getState().retry(erroredJob.id)
    const retried = useDownloads.getState().jobs.find((j) => j.id === erroredJob.id)
    expect(retried?.status).toBe('queued')
    expect(retried?.gainDb).toBeUndefined()
  })
})

/**
 * `pump` — سقفِ دانلودِ هم‌زمانِ قابل‌تنظیم.
 *
 * تا پیش از این یک ثابتِ سطحِ ماژول بود و صفحه‌ی تنظیمات حالا آن را عوض
 * می‌کند. دوچیز باید ثابت بماند: سقف واقعاً از تنظیمات خوانده شود، و بالا
 * بردنش *همان لحظه* کارهای «در انتظار» را راه بیندازد — وگرنه کاربر تنظیم
 * را عوض می‌کند و تا رویدادِ بعدیِ صف هیچ اتفاقی نمی‌بیند.
 */
describe('pump و سقفِ هم‌زمانیِ دانلود', () => {
  function queued(id: string): Job {
    return {
      ...job(id, '320', 'queued'),
      id,
      track: { ...track(id), id },
    }
  }

  it('به‌اندازه‌ی سقفِ تنظیمات کار شروع می‌کند', async () => {
    const { useDownloads } = await import('./downloads')
    const { useSettings } = await import('./settings')
    const api = await import('../lib/api')
    const started: string[] = []
    // `start` فقط تا اولین پیامِ پیشرفت زنده می‌ماند؛ اینجا فقط می‌خواهیم
    // بشماریم چند کار اصلاً *شروع* شده‌اند
    const spy = vi.spyOn(api.api, 'download').mockImplementation((req) => {
      started.push(req.track.id)
      return () => {}
    })

    useSettings.setState({ maxConcurrentDownloads: 2 })
    useDownloads.setState({
      jobs: [queued('a'), queued('b'), queued('c')],
      batches: [{ id: 'b1', title: 'Batch', artworkUrl: null, quality: '320', createdAt: 1 }],
    })

    useDownloads.getState().pump()
    expect(started).toHaveLength(2)
    spy.mockRestore()
  })

  it('بالا بردنِ سقف، کارهای در انتظار را همان لحظه راه می‌اندازد', async () => {
    const { useDownloads } = await import('./downloads')
    const { useSettings } = await import('./settings')
    const api = await import('../lib/api')
    const started: string[] = []
    const spy = vi.spyOn(api.api, 'download').mockImplementation((req) => {
      started.push(req.track.id)
      return () => {}
    })

    useSettings.setState({ maxConcurrentDownloads: 1 })
    useDownloads.setState({
      jobs: [queued('a'), queued('b'), queued('c')],
      batches: [{ id: 'b1', title: 'Batch', artworkUrl: null, quality: '320', createdAt: 1 }],
    })
    useDownloads.getState().pump()
    expect(started).toHaveLength(1)

    // سقفِ بالاتر باید بقیه را هم بلافاصله بردارد
    useSettings.setState({ maxConcurrentDownloads: 3 })
    useDownloads.getState().pump()
    expect(started).toHaveLength(3)
    spy.mockRestore()
  })
})

/**
 * صف باید بینِ تست‌ها تمیز شود.
 *
 * `cancelers` بیرون از state و در سطحِ ماژول است؛ یک کارِ «شروع‌شده» از تستِ
 * قبلی باعث می‌شود `drainQueue` آن را *فعال* بشمارد و جای خالیِ کمتری ببیند —
 * یعنی تستِ بعدی به‌جای ۲ کار، ۱ کار شروع می‌کند. `remove` تنها راهِ عمومیِ
 * پاک‌کردنِ آن نگاشت است.
 */
beforeEach(async () => {
  const { useDownloads } = await import('./downloads')
  for (const job of [...useDownloads.getState().jobs]) {
    useDownloads.getState().remove(job.id)
  }
  useDownloads.setState({ jobs: [], batches: [] })
})

afterEach(() => {
  vi.restoreAllMocks()
})
