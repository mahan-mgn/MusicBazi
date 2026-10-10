import { describe, expect, it } from 'vitest'
import { CODEC_QUALITIES, MP3_QUALITIES, QUALITIES, SOURCE_LABEL } from './types'

/**
 * این‌ها به‌جای «تست منطق»، قرارداد بین فرانت و بک‌اند را قفل می‌کنند.
 * کیفیتی که فقط یک طرف بشناسد، در زمان اجرا ۴۲۲ می‌دهد نه خطای کامپایل —
 * قبلاً دقیقاً همین اتفاق برای «۱۹۲» افتاده بود.
 */
describe('quality contract', () => {
  it('matches the Quality literal on the server', () => {
    expect(QUALITIES).toEqual(['128', '192', '320', 'm4a', 'opus', 'flac', 'original'])
  })

  it('has no duplicates between the two groups', () => {
    const ids = [...MP3_QUALITIES.map((q) => q.id), ...CODEC_QUALITIES.map((q) => q.id)]
    expect(new Set(ids).size).toBe(ids.length)
  })

  it('keeps mp3 bitrates numeric and codecs textual', () => {
    expect(MP3_QUALITIES.every((q) => /^\d+$/.test(q.id))).toBe(true)
    expect(CODEC_QUALITIES.every((q) => !/^\d+$/.test(q.id))).toBe(true)
  })
})

describe('source labels', () => {
  it('covers every source the server can return', () => {
    expect(Object.keys(SOURCE_LABEL).sort()).toEqual([
      'apple',
      'deezer',
      'soundcloud',
      'spotify',
      'youtube',
      'youtube_music',
    ])
  })
})
