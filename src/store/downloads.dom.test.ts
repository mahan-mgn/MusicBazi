// @vitest-environment jsdom
//
// خودِ انتخاب خالص است، ولی `downloads` غیرمستقیم `i18n` را می‌آورد و آن در
// سطحِ ماژول به `document` دست می‌زند — همان قراردادی که
// `AnimatedList.dom.test.tsx` هم دنبال می‌کند.
import { describe, expect, it } from 'vitest'
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
})
