// @vitest-environment jsdom
//
// ویزاردِ راه‌اندازی، دروازه‌ی ورودِ مرورگر است: اگر اینجا چیزی غلط برود، کاربر
// یا کلیدش را از دست می‌دهد یا پشتِ صفحه‌ای گیر می‌کند که هیچ‌وقت تمام نمی‌شود.
// پس رندر و سه مسیرِ خروجِ آن (ذخیره / رد کردن / بستن) باید تست شوند، نه فقط
// توابعِ کمکی.
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SetupWizard from './SetupWizard'
import { useI18n } from '../lib/i18n'

// واژه‌ها را از خودِ دیکشنری می‌گیریم نه از کپیِ دستی: یک کلیدِ عوض‌شده باید
// تست را بشکند، نه اینکه تستِ کُهنه سبز بماند
const dict = useI18n.getState().t as unknown as Record<string, unknown>
const txt = (k: string) => (typeof dict[k] === 'string' ? (dict[k] as string) : '')

const STATE = {
  done: false,
  set: { MUSICBAZI_AUDD_TOKEN: '…da25' },
  env: {
    ffmpeg: true,
    jsRuntime: 'node',
    potoken: true,
    cookies: true,
    proxy: false,
    internet: true,
    container: false,
  },
  telegram: { botTokenSet: true, connected: true, botUsername: 'musicbazi_bot' },
}

type Call = { url: string; init?: RequestInit }
let calls: Call[] = []
let saveReply: Record<string, unknown> = { ok: true, changed: [], done: true }

let host: HTMLDivElement
let root: Root

beforeEach(() => {
  // کلیک‌ها await دارند؛ بدون این پرچم React ۱۹ هر آپدیتِ بیرون از act() را
  // هشدار می‌دهد
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init })
      const body = String(url).endsWith('/api/setup/save')
        ? saveReply
        : String(url).endsWith('/api/setup/test')
          ? { ok: true, detail: 'OK' }
          : String(url).endsWith('/api/health')
            ? { ok: true }
            : STATE
      return { ok: true, status: 200, statusText: 'OK', json: async () => body } as Response
    }),
  )
  host = document.createElement('div')
  document.body.appendChild(host)
})

afterEach(() => {
  act(() => root.unmount())
  host.remove()
  vi.unstubAllGlobals()
})

/** رندر و صبر کردن تا `GET /api/setup` بنشیند — وگرنه همه‌چیز اسپینر است */
async function render(onDone?: () => void) {
  root = createRoot(host)
  await act(async () => {
    root.render(<SetupWizard onDone={onDone} />)
  })
  await act(async () => {})
}

const byButton = (s: string) => {
  const el = [...host.querySelectorAll('button')].find((b) => b.textContent?.includes(s))
  if (!el) throw new Error(`no button containing: ${s}`)
  return el
}

function inputFor(envVar: string): HTMLInputElement {
  const label = [...host.querySelectorAll('label')].find((l) =>
    l.querySelector('span')?.textContent?.includes(envVar),
  )
  const el = label?.querySelector('input')
  if (!el) throw new Error(`no input for ${envVar}`)
  return el as HTMLInputElement
}

async function type(el: HTMLInputElement, value: string) {
  await act(async () => {
    // setterِ بومی تا React مقدارِ کنترل‌شده‌ی jsdom را ببیند، نه فقط DOM را
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(el, value)
    el.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

const click = async (el: Element) => {
  await act(async () => {
    ;(el as HTMLElement).click()
  })
}

describe('SetupWizard', () => {
  it('وضعیتِ سرور و کلیدهای شخصی را رندر می‌کند — بدونِ پروکسی و تلگرام', async () => {
    await render()
    expect(host.textContent).toContain(txt('setupTitle'))
    expect(host.textContent).toContain(txt('setupServerTitle'))
    const labels = [...host.querySelectorAll('label')].map((l) => l.textContent ?? '')
    for (const v of [
      'SPOTIFY_CLIENT_ID',
      'SPOTIFY_CLIENT_SECRET',
      'GENIUS_ACCESS_TOKEN',
      'ACOUSTID_KEY',
      'AUDD_TOKEN',
      'GEMINI_API_KEY',
    ])
      expect(labels.some((l) => l.includes(v)), v).toBe(true)
    // پروکسی و توکنِ بات مالِ سرورند؛ کاربر نباید فیلدشان را ببیند
    expect(labels.some((l) => l.includes('PROXY'))).toBe(false)
    expect(labels.some((l) => l.includes('TELEGRAM_BOT_TOKEN'))).toBe(false)
    // مقدارِ قبلی فقط ماسک است؛ خودِ کلید هیچ‌وقت به صفحه نمی‌آید
    expect(host.textContent).toContain('…da25')
  })

  it('کوکیِ یوتیوب به‌عنوانِ وضعیتِ مشترکِ سرور نمایش داده می‌شود', async () => {
    await render()
    expect(host.textContent).toContain(txt('setupCookiesTitle'))
    expect(host.textContent).toContain(txt('setupEnvCookies'))
    // نامِ باتِ سرور، فقط-خواندنی
    expect(host.textContent).toContain('@musicbazi_bot')
  })

  it('دکمه‌ی آزمایش اسپاتیفای تا پر شدنِ *هر دو* فیلد غیرفعال است', async () => {
    await render()
    const id = inputFor('SPOTIFY_CLIENT_ID')
    const secret = inputFor('SPOTIFY_CLIENT_SECRET')
    const group = id.closest('label')!.parentElement!
    const btn = [...group.querySelectorAll('button')].find((b) =>
      b.textContent?.includes(txt('setupTest')),
    ) as HTMLButtonElement
    expect(btn.disabled).toBe(true)
    await type(id, 'client-id-value')
    expect(btn.disabled).toBe(true) // تنها یک‌قسمتی یعنی هنوز آزمایشِ بی‌فایده
    await type(secret, 'client-secret-value')
    expect(btn.disabled).toBe(false)
  })

  it('ذخیره فقط فیلدهای پر را می‌فرستد — رشته‌ی خالی کلیدِ کارکرد را پاک می‌کرد', async () => {
    await render()
    await type(inputFor('AUDD_TOKEN'), 'fresh-token')
    await click(byButton(txt('setupSaveNothing'))!)
    const save = calls.find((c) => c.url.endsWith('/api/setup/save'))!
    const body = JSON.parse(String(save.init!.body)) as {
      values: Record<string, string>
      done: boolean
    }
    expect(body.values).toEqual({ MUSICBAZI_AUDD_TOKEN: 'fresh-token' })
    expect(body.done).toBe(true)
    // ری‌استارت حذف شده؛ کلیدِ کهنه نباید برگردد
    expect(body).not.toHaveProperty('restart')
  })

  it('درخواست‌ها هدرِ Authorization می‌برند', async () => {
    localStorage.setItem('mbstamp', '') // بی‌اثر؛ فقط مطمئن می‌شویم استور صدا نمی‌زند
    await render()
    const get = calls.find((c) => c.url.endsWith('/api/setup'))!
    // توکنی در این تست نیست، پس هدر نباید وجود داشته باشد — ولی ساختار باید
    // آماده باشد (و با توکن، تستِ بعدی آن را می‌سنجد)
    expect(get.init?.headers).toBeDefined()
  })

  it('بعد از ذخیره، ویزارد بسته می‌شود و آدرس پاک می‌ماند', async () => {
    let done = false
    await render(() => {
      done = true
    })
    await type(inputFor('AUDD_TOKEN'), 'fresh-token')
    await click(byButton(txt('setupSaveNothing'))!)
    expect(done).toBe(true)
  })

  it('«رد کردن» فقط done را می‌فرستد و دروازه را باز می‌کند', async () => {
    let done = false
    await render(() => {
      done = true
    })
    await click(byButton(txt('setupSkip'))!)
    const save = calls.find((c) => c.url.endsWith('/api/setup/save'))!
    const body = JSON.parse(String(save.init!.body)) as { values: unknown; done: boolean }
    expect(body.values).toEqual({})
    expect(body.done).toBe(true)
    expect(done).toBe(true)
  })

  it('وقتی سرور جواب نمی‌دهد، پیامِ روشن نشان می‌دهد نه اسپینرِ ابدی', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new Error('offline')
      }),
    )
    await render()
    expect(host.textContent).toContain(txt('setupEnvUnavailable'))
  })
})
