import { describe, expect, it } from 'vitest'
import { artBlurUrl } from './Artwork'

// تنها دروازه‌ی تصمیمِ «بلورِ سمتِ سرور» در برابرِ «بلورِ زنده‌ی CSS».
// بازگشتِ اشتباه یعنی هر کاور بی‌صدا به CSS blur می‌افتد (گران) یا هیرو می‌شکند.
describe('artBlurUrl', () => {
  it('کاورِ محلی را به مسیرِ بلورِ سرور می‌برد', () => {
    expect(artBlurUrl('/api/art/ab12cd')).toBe('/api/art-blur/ab12cd')
  })

  it('کاورِ مطلقِ محلی در اپ اندروید را هم به مسیرِ بلورِ سرور می‌برد', () => {
    expect(artBlurUrl('http://192.168.1.50:8080/api/art/ab12cd')).toBe(
      'http://192.168.1.50:8080/api/art-blur/ab12cd',
    )
  })

  it('کاورِ CDN (غیرمحلی) را null می‌دهد تا مصرف‌کننده به CSS blur برگردد', () => {
    expect(artBlurUrl('https://i.scdn.co/image/ab67616d')).toBeNull()
  })

  it('نبودِ آدرس → null، بدونِ استثنا', () => {
    expect(artBlurUrl(null)).toBeNull()
  })
})
