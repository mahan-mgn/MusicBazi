// @vitest-environment jsdom
//
// ویزاردِ راه‌اندازی، دروازه‌ی ورودِ مرورگر است: اگر اینجا چیزی غلط برود، کاربر
// یا کلیدش را از دست می‌دهد یا پشتِ یک صفحه‌ی «در حال انتظار» گیر می‌کند که هیچ‌وقت
// تمام نمی‌شود. پس رندر و سه مسیرِ خروجِ آن (ری‌استارت موفق / ری‌استارتِ دستی /
// رد کردن) باید تست شوند، نه فقط توابعِ کمکی.
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
  restartNeeded: false,
  env: {
    ffmpeg: true,
    jsRuntime: 'node',
    potoken: true,
    cookies: true,
    proxy: false,
    internet: true,
    container: false,
  },
}

type Call = { url: string; init?: RequestInit }
let calls: Call[] = []
let saveReply: Record<string, unknown> = { ok: true, changed: [], restarting: false, manualRestart: false }

let reload = vi.fn()
let host: HTMLDivElement
let root: Root

beforeEach(() => {
  // کلیک‌ها await دارند؛ بدون این پرچم React ۱۹ هر آپدیتِ بیرون از act() را
  // هشدار می‌دهد
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  calls = []
  reload = vi.fn()
  // یکی از تست‌ها restartNeeded را روشن می‌کند؛ بدونِ ریست، به بقیه سرایت می‌کرد
  STATE.restartNeeded = false
  // jsdom روی reload واقعی صفحه را می‌بَرَد؛ stub هم صدا می‌کُش هم قابلِ ادعاست
  Object.defineProperty(window, 'location', {
    value: { ...window.location, reload, href: 'http://localhost/?setup=1' },
    writable: true,
  })
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init })
      const body =
        String(url).endsWith('/api/setup/save')
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

// «ادامه» هم در متنِ هشدارِ restartNeeded می‌آید، پس کلیک باید فقط دکمه بگردد
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
  it('محیط و هر هفت گروهِ کلیدی را رندر می‌کند', async () => {
    await render()
    expect(host.textContent).toContain(txt('setupTitle'))
    const labels = [...host.querySelectorAll('label')].map((l) => l.textContent ?? '')
    for (const v of [
      'SPOTIFY_CLIENT_ID',
      'SPOTIFY_CLIENT_SECRET',
      'GENIUS_ACCESS_TOKEN',
      'ACOUSTID_KEY',
      'AUDD_TOKEN',
      'GEMINI_API_KEY',
      'TELEGRAM_BOT_TOKEN',
      'PROXY',
    ])
      expect(labels.some((l) => l.includes(v)), v).toBe(true)
    // مقدارِ قبلی فقط ماسک است؛ خودِ کلید هیچ‌وقت به صفحه نمی‌آید
    expect(host.textContent).toContain('…da25')
    expect(host.textContent).not.toContain('audd-live-check')
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
      restart: boolean
      done: boolean
    }
    expect(body.values).toEqual({ MUSICBAZI_AUDD_TOKEN: 'fresh-token' })
    expect(body.restart).toBe(true)
    expect(body.done).toBe(true)
  })

  it('ری‌استارتِ موفق: صبر تا سلامتی، بعد reload', async () => {
    saveReply = { ok: true, changed: ['MUSICBAZI_AUDD_TOKEN'], restarting: true, manualRestart: false }
    await render()
    await type(inputFor('AUDD_TOKEN'), 'fresh-token')
    await click(byButton(txt('setupSaveNothing'))!)
    expect(host.textContent).toContain(txt('setupWaiting'))
    // `waitForServer` اول ۱.۲ ثانیه صبر می‌کند (سرور هنوز نفرستاده که می‌میرد)،
    // پس مهلتِ پیش‌فرضِ waitFor (۱ ثانیه) از خودش کوتاه‌تر است
    await vi.waitFor(() => expect(reload).toHaveBeenCalled(), { timeout: 8000 })
  })

  it('manualRestart: راهنمایِ دستی نشان می‌دهد و بی‌هدف سلامتی را نمی‌کاود', async () => {
    saveReply = { ok: true, changed: [], restarting: false, manualRestart: true }
    await render()
    await type(inputFor('AUDD_TOKEN'), 'fresh-token')
    await click(byButton(txt('setupSaveNothing'))!)
    expect(host.textContent).toContain(txt('setupManualRestart'))
    expect(host.textContent).not.toContain(txt('setupWaiting'))
    expect(reload).not.toHaveBeenCalled()
    // هیچ pollingی نباید شروع شده باشد
    expect(calls.some((c) => c.url.endsWith('/api/health'))).toBe(false)
  })

  it('«رد کردن» سرور را ری‌استارت نمی‌کند ولی دروازه را باز می‌کند', async () => {
    let done = false
    await render(() => {
      done = true
    })
    await click(byButton(txt('setupSkip'))!)
    const save = calls.find((c) => c.url.endsWith('/api/setup/save'))!
    const body = JSON.parse(String(save.init!.body)) as { values: unknown; restart: boolean }
    expect(body.values).toEqual({})
    expect(body.restart).toBe(false)
    expect(done).toBe(true)
  })

  it('restartNeeded روی دیسک، ری‌استارت را بی‌کلیدِ تازه هم لازم می‌کند', async () => {
    // سرور از اجرایِ قبلی مقدارِ خوانده‌نشده دارد؛ کاربر چیزی تایپ نکرده، ولی
    // بی‌ری‌استارت آن مقدار هیچ‌وقت به کار نمی‌رود
    STATE.restartNeeded = true
    saveReply = { ok: true, changed: [], restarting: false, manualRestart: false }
    await render()
    expect(host.textContent).toContain(txt('setupRestartNeeded'))
    await click(byButton(txt('setupSaveNothing'))!)
    const save = calls.find((c) => c.url.endsWith('/api/setup/save'))!
    const body = JSON.parse(String(save.init!.body)) as { values: unknown; restart: boolean }
    expect(body.values).toEqual({})
    expect(body.restart).toBe(true)
  })
})
