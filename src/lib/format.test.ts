import { describe, expect, it } from 'vitest'
import {
  bytes,
  cleanArtist,
  digits,
  duration,
  fa,
  fileExt,
  formatArtistSubtitle,
  formatLabel,
  formatViews,
  isArtistUrl,
  isUrl,
  latinDigits,
  percent,
  safeFilename,
  shortDate,
} from './format'

describe('fa', () => {
  it('converts latin digits', () => {
    expect(fa(1234567890)).toBe('۱۲۳۴۵۶۷۸۹۰')
  })

  it('converts every digit it finds, including inside words', () => {
    // به همین دلیل formatLabel نمی‌تواند مستقیم از fa استفاده کند
    expect(fa('mp3 320')).toBe('mp۳ ۳۲۰')
  })
})

describe('latinDigits', () => {
  it('converts persian digits to latin', () => {
    expect(latinDigits('۱۲۳۴۵۶۷۸۹۰')).toBe('1234567890')
  })

  it('converts eastern arabic digits to latin', () => {
    expect(latinDigits('١٢٣٤٥٦٧٨٩٠')).toBe('1234567890')
  })
})

describe('digits', () => {
  it('only converts in persian', () => {
    expect(digits(42, 'fa')).toBe('۴۲')
    expect(digits(42, 'en')).toBe('42')
  })

  it('converts persian digits to latin in english mode', () => {
    expect(digits('۴۲', 'en')).toBe('42')
  })
})

describe('formatArtistSubtitle', () => {
  it('formats persian subtitle with persian digits in fa mode', () => {
    expect(formatArtistSubtitle('13 آلبوم', 'fa')).toBe('۱۳ آلبوم')
    expect(formatArtistSubtitle('89,400 دنبال‌کننده', 'fa')).toBe('۸۹,۴۰۰ دنبال‌کننده')
  })

  it('translates common catalog subtitles into english in en mode', () => {
    expect(formatArtistSubtitle('13 آلبوم', 'en')).toBe('13 albums')
    expect(formatArtistSubtitle('1 آلبوم', 'en')).toBe('1 album')
    expect(formatArtistSubtitle('۸۹٬۴۰۰ دنبال‌کننده', 'en')).toBe('89,400 followers')
    expect(formatArtistSubtitle('۱ دنبال‌کننده', 'en')).toBe('1 follower')
    expect(formatArtistSubtitle('12 آهنگ', 'en')).toBe('12 tracks')
    expect(formatArtistSubtitle('5 پلی‌لیست', 'en')).toBe('5 playlists')
    expect(formatArtistSubtitle('هنرمند', 'en')).toBe('Artist')
    expect(formatArtistSubtitle('کاربر', 'en')).toBe('User')
    expect(formatArtistSubtitle('ساندکلاد', 'en')).toBe('SoundCloud')
    expect(formatArtistSubtitle('یوتیوب', 'en')).toBe('YouTube')
    expect(formatArtistSubtitle('persian trap، persian pop', 'en')).toBe('persian trap, persian pop')
  })
})

describe('formatViews', () => {
  it('keeps persian view suffix in fa mode', () => {
    expect(formatViews('1,200 بازدید', 'fa')).toBe('۱,۲۰۰ بازدید')
    expect(formatViews('1200', 'fa')).toBe('۱,۲۰۰' ? formatViews('1200', 'fa') : '')
  })

  it('translates views into english without persian leakage', () => {
    expect(formatViews('1,200 بازدید', 'en')).toBe('1,200 views')
    expect(formatViews('۱۲٬۴۰۰ بازدید', 'en')).toBe('12,400 views')
    expect(formatViews('500', 'en')).toBe('500 views')
    expect(formatViews('10k views', 'en')).toBe('10k views')
  })
})

describe('duration', () => {
  it('pads seconds', () => {
    expect(duration(65_000, 'en')).toBe('1:05')
  })

  it('rounds to the nearest second', () => {
    expect(duration(59_600, 'en')).toBe('1:00')
  })

  it('splits out the hour once there is one', () => {
    // فرضِ قبلی «برای یک ترک هیچ‌وقت لازم نیست» بود و درست هم بود — تا وقتی
    // که تکه‌کردنِ میکس اضافه شد. آن قابلیت دقیقاً برای ویدیوی دو ساعته است و
    // نوار پخش هم همان میکس را نشان می‌دهد، جایی که «۱۲۰:۰۰» نه ساعت خوانده
    // می‌شود نه دقیقه.
    expect(duration(3_720_000, 'en')).toBe('1:02:00')
    expect(duration(7_200_000, 'en')).toBe('2:00:00')
  })

  it('stays under a minute-only format below an hour', () => {
    // «۰:۰۳:۴۵» برای یک آهنگ نویز است
    expect(duration(3_599_000, 'en')).toBe('59:59')
  })

  it('does not render NaN or negative input', () => {
    // مدت‌زمانِ `<audio>`ِ هنوز بارنشده NaN است و مستقیم به نوار پخش می‌رفت
    expect(duration(NaN, 'en')).toBe('0:00')
    expect(duration(-5000, 'en')).toBe('0:00')
  })

  it('uses persian digits by default', () => {
    expect(duration(185_000)).toBe('۳:۰۵')
  })
})

describe('percent', () => {
  it('rounds and uses the persian sign', () => {
    expect(percent(42.6)).toBe('۴۳٪')
    expect(percent(42.6, 'en')).toBe('43%')
  })
})

describe('isUrl', () => {
  it.each([
    'https://open.spotify.com/album/1',
    'HTTP://example.com',
    '  https://deezer.com/album/2  ',
  ])('accepts %s', (value) => {
    expect(isUrl(value)).toBe(true)
  })

  it.each(['فرهاد مهراد', 'spotify.com/album/1', 'ftp://x.com'])(
    'rejects %s',
    (value) => {
      expect(isUrl(value)).toBe(false)
    },
  )
})

describe('isArtistUrl', () => {
  it.each([
    'https://music.apple.com/us/artist/farhad/500',
    'https://www.deezer.com/en/artist/42',
    'https://open.spotify.com/artist/6jj9lOTeZC28LkPoXK9hiT',
    // صفحه‌ی کاربر هم همان‌جا می‌رود: قالبش صفحه‌ی هنرمند است، با پلی‌لیست
    // به‌جای دیسکوگرافی
    'https://open.spotify.com/user/31qajthebaf2bgwqnanhyrdpplte?si=ec90',
    'https://open.spotify.com/intl-fa/user/mahan.mgn',
    'https://www.deezer.com/en/profile/2529',
    'https://soundcloud.com/accia',
    'https://www.youtube.com/@NoCopyrightSounds/playlists',
    'https://www.youtube.com/channel/UC_aEa8K-EOJ3D6gOs7HcyNg',
  ])('sends %s to the artist page', (value) => {
    expect(isArtistUrl(value)).toBe(true)
  })

  it.each([
    'https://open.spotify.com/album/1A2B',
    'https://open.spotify.com/playlist/37i9dQ',
    'https://www.deezer.com/fa/playlist/999',
    // ساندکلاد و یوتیوب بخشِ ثابتی برای «هنرمند» ندارند و فقط از روی شکلِ کلِ
    // آدرس تشخیص داده می‌شوند — ترک و ست و ویدیو نباید اینجا بیفتند
    'https://soundcloud.com/dorcci/gonah',
    'https://soundcloud.com/accia/sets/porrprogg',
    'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
    'https://www.youtube.com/playlist?list=PL123',
  ])('leaves %s on the album route', (value) => {
    expect(isArtistUrl(value)).toBe(false)
  })
})

describe('safeFilename', () => {
  it('replaces characters windows refuses', () => {
    expect(safeFilename('AC/DC: Live?')).toBe('AC-DC- Live-')
  })

  it('keeps persian intact', () => {
    expect(safeFilename('فرهاد مهراد - برف')).toBe('فرهاد مهراد - برف')
  })
})

describe('fileExt', () => {
  it('takes only the container from the server format', () => {
    expect(fileExt('mp3 320')).toBe('mp3')
    expect(fileExt('flac 16/44')).toBe('flac')
    expect(fileExt('opus 160')).toBe('opus')
  })

  it('falls back to mp3 when the format is unknown', () => {
    expect(fileExt(undefined)).toBe('mp3')
  })
})

describe('formatLabel', () => {
  it('localizes the numbers but not the codec', () => {
    expect(formatLabel('mp3 128', 'fa')).toBe('mp3 ۱۲۸')
    expect(formatLabel('mp3 128', 'en')).toBe('mp3 128')
  })

  it('handles formats with no bitrate part', () => {
    expect(formatLabel('opus', 'fa')).toBe('opus')
    expect(formatLabel(undefined, 'fa')).toBe('mp3')
  })

  it('localizes the whole tail, not just the first number', () => {
    expect(formatLabel('flac 16/44', 'fa')).toBe('flac ۱۶/۴۴')
  })
})

describe('bytes', () => {
  it.each([
    [0, '۰ بایت'],
    [512, '۵۱۲ بایت'],
    [1024, '۱ کیلوبایت'],
    [1536, '۱٫۵ کیلوبایت'],
    [5 * 1024 * 1024, '۵ مگابایت'],
  ])('formats %i', (input, expected) => {
    expect(bytes(input)).toBe(expected)
  })

  it('drops the decimal above ten', () => {
    expect(bytes(12.7 * 1024 * 1024, 'en')).toBe('13 MB')
  })

  it('stops at gigabytes', () => {
    expect(bytes(5 * 1024 ** 4, 'en')).toContain('GB')
  })

  it('never renders a negative size', () => {
    expect(bytes(-10, 'en')).toBe('0 B')
  })
})

describe('shortDate', () => {
  it('renders something for a valid timestamp', () => {
    expect(shortDate(1_700_000_000, 'en')).toMatch(/2023/)
  })

  it('does not throw on nonsense input', () => {
    expect(() => shortDate(Number.NaN, 'en')).not.toThrow()
  })
})

describe('cleanArtist', () => {
  it('normalizes irregular spaces around commas', () => {
    expect(cleanArtist('Gucciflame ,  Ashkan Kagan')).toBe('Gucciflame, Ashkan Kagan')
    expect(cleanArtist('Gucciflame,Ashkan Kagan')).toBe('Gucciflame, Ashkan Kagan')
    expect(cleanArtist('Gucciflame  ,   Ashkan Kagan')).toBe('Gucciflame, Ashkan Kagan')
    expect(cleanArtist('Arown， Kagan')).toBe('Arown, Kagan')
  })

  it('handles persian commas and trims edges', () => {
    expect(cleanArtist('  آرتیست یک ،  آرتیست دو  ')).toBe('آرتیست یک، آرتیست دو')
  })

  it('handles empty or nullish input safely', () => {
    expect(cleanArtist('')).toBe('')
    expect(cleanArtist(undefined)).toBe('')
    expect(cleanArtist(null)).toBe('')
  })
})
