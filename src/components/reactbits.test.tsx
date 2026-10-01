import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AnimatedList from './AnimatedList'
import ClickSpark from './ClickSpark'
import CountUp from './CountUp'
import LogoLoop from './LogoLoop'
import PillNav from './PillNav'
import ShinyText from './ShinyText'
import SpotlightCard from './SpotlightCard'

/**
 * تستِ دودِ کامپوننت‌های برداشته‌شده از reactbits.
 *
 * این‌جا DOM نیست و هدف هم DOM نیست: فقط مسیرِ رندر اجرا می‌شود تا مطمئن شویم
 * هیچ‌کدامشان بیرون از مرورگر (و پیش از اجرای افکت‌ها) به `window` یا
 * `document` دست نمی‌زنند و می‌ترکند. همان چیزی که موقعِ اضافه‌کردنِ یک
 * کامپوننتِ آماده بیشتر از همه می‌شکند.
 *
 * `useLayoutEffect` روی سرور اجرا نمی‌شود و ری‌اکت برایش هشدار می‌دهد؛ آن یک
 * هشدارِ شناخته‌شده است و پایین صریح از بقیه‌ی خطاها جدا می‌شود.
 */

const KNOWN = 'useLayoutEffect'
let errors: string[] = []

beforeEach(() => {
  errors = []
  vi.spyOn(console, 'error').mockImplementation((...args: unknown[]) => {
    errors.push(String(args[0]))
  })
})

afterEach(() => {
  vi.restoreAllMocks()
  // هر خطای دیگری یعنی رندر واقعاً مشکل داشته
  expect(errors.filter((e) => !e.includes(KNOWN))).toEqual([])
})

describe('PillNav', () => {
  const items = [
    { label: 'خانه', href: '/' },
    { label: 'کتابخانه', href: '/?library=1' },
  ]

  it('هر دو مقصد را با href واقعی رندر می‌کند', () => {
    const html = renderToStaticMarkup(<PillNav items={items} logoAlt="موزیک بازی" />)
    expect(html).toContain('href="/?library=1"')
    expect(html).toContain('خانه')
    expect(html).toContain('کتابخانه')
  })

  it('قرصِ فعال را با aria-current علامت می‌زند', () => {
    const html = renderToStaticMarkup(<PillNav items={items} activeHref="/?library=1" />)
    expect(html).toContain('aria-current="page"')
  })

  it('بدون activeHref هیچ قرصی فعال نیست', () => {
    const html = renderToStaticMarkup(<PillNav items={items} />)
    expect(html).not.toContain('aria-current')
  })

  it('با mobileMenu=false منوی موبایل ساخته نمی‌شود', () => {
    const html = renderToStaticMarkup(<PillNav items={items} mobileMenu={false} />)
    expect(html).not.toContain('hamburger-line')
  })
})

describe('LogoLoop', () => {
  it('روی سرور فقط یک دنباله رندر می‌شود', () => {
    const html = renderToStaticMarkup(
      <LogoLoop ariaLabel="منبع‌ها">
        <li>spotify</li>
        <li>deezer</li>
      </LogoLoop>,
    )
    expect(html.match(/<ul/g)).toHaveLength(1)
    expect(html).toContain('aria-label="منبع‌ها"')
  })
})

describe('ShinyText', () => {
  it('متن را نمی‌شکند — یک گره‌ی متنیِ سالم', () => {
    const html = renderToStaticMarkup(<ShinyText>کتابخانه‌ی موسیقیِ تو</ShinyText>)
    expect(html).toContain('>کتابخانه‌ی موسیقیِ تو<')
    expect(html).toContain('shiny-text')
  })

  it('با disabled کلاسِ انیمیشن را نمی‌گذارد', () => {
    const html = renderToStaticMarkup(<ShinyText disabled>سلام</ShinyText>)
    expect(html).not.toContain('shiny-text')
  })
})

describe('SpotlightCard', () => {
  it('با as="button" واقعاً دکمه می‌شود', () => {
    const html = renderToStaticMarkup(
      <SpotlightCard as="button" aria-label="باز کردن">
        محتوا
      </SpotlightCard>,
    )
    expect(html.startsWith('<button')).toBe(true)
    expect(html).toContain('aria-label="باز کردن"')
  })

  it('پیش‌فرض div است', () => {
    expect(renderToStaticMarkup(<SpotlightCard>x</SpotlightCard>).startsWith('<div')).toBe(true)
  })
})

describe('AnimatedList', () => {
  it('بچه‌ها را دست‌نخورده و بدونِ لایه‌ی اضافه رندر می‌کند', () => {
    const html = renderToStaticMarkup(
      <AnimatedList className="space-y-0.5">
        <div>a</div>
        <div>b</div>
      </AnimatedList>,
    )
    expect(html).toBe('<div class="space-y-0.5"><div>a</div><div>b</div></div>')
  })
})

describe('CountUp', () => {
  const faDigits = (n: number) => String(n).replace(/\d/g, (d) => '۰۱۲۳۴۵۶۷۸۹'[Number(d)])

  it('مقدارِ نهایی همیشه برای صفحه‌خوان هست، حتی پیش از شمردن', () => {
    const html = renderToStaticMarkup(<CountUp value={124} format={faDigits} />)
    expect(html).toContain('۱۲۴')
    expect(html).toContain('sr-only')
  })

  it('فرمت‌کننده‌ی بیرونی را به کار می‌گیرد، نه ارقامِ لاتین', () => {
    const html = renderToStaticMarkup(<CountUp value={7} format={faDigits} />)
    expect(html).not.toContain('>7<')
  })
})

describe('ClickSpark', () => {
  it('دکمه‌ی داخلش را نگه می‌دارد و canvas را کنارش می‌گذارد', () => {
    const html = renderToStaticMarkup(
      <ClickSpark>
        <button>دانلود همه</button>
      </ClickSpark>,
    )
    expect(html).toContain('<button>دانلود همه</button>')
    expect(html).toContain('<canvas')
    expect(html).toContain('pointer-events-none')
  })
})
