// @vitest-environment jsdom

import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * صفحه‌ی ورود.
 *
 * چیزی که این فایل از آن محافظت می‌کند: صفحه هرگز نباید کاربر را گیر بیندازد.
 * ورود اختیاری است، پس «بدون حساب» باید همیشه کار کند — حتی وقتی سرور کلید
 * گوگل ندارد، حتی وقتی شبکه نیست، و حتی وقتی خودِ درخواستِ ورود خطا می‌دهد.
 */

const login = vi.fn()
const register = vi.fn()

vi.mock('../store/auth', () => ({
  useAuth: () => ({
    user: null,
    busy: false,
    providers: providersState,
    login,
    register,
  }),
}))

vi.mock('../lib/api', () => ({ api: {}, API_MODE: 'http' }))

let providersState: { google: boolean; googleReason: string | null } = {
  google: true,
  googleReason: null,
}

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

function setup() {
  const host = document.createElement('div')
  document.body.append(host)
  let root: Root
  const onDone = vi.fn()
  act(() => {
    root = createRoot(host)
    root.render(<LoginView onDone={onDone} />)
  })
  return { host, onDone, unmount: () => act(() => root.unmount()) }
}

const LoginView = (await import('./LoginView')).default

function button(host: HTMLElement, text: string): HTMLButtonElement {
  const found = [...host.querySelectorAll('button')].find((b) => b.textContent?.includes(text))
  if (!found) throw new Error(`دکمه پیدا نشد: ${text}`)
  return found as HTMLButtonElement
}

function inputs(host: HTMLElement): HTMLInputElement[] {
  return [...host.querySelectorAll('input')]
}

async function type(input: HTMLInputElement, value: string) {
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
    setter.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

beforeEach(() => {
  providersState = { google: true, googleReason: null }
  login.mockReset()
  register.mockReset()
  window.location.hash = ''
})

afterEach(() => {
  document.body.innerHTML = ''
})

describe('LoginView', () => {
  it('always offers a way past the screen, because sign-in is optional', () => {
    const { host, onDone, unmount } = setup()
    const guest = button(host, 'بدون حساب')
    act(() => guest.click())
    expect(onDone).toHaveBeenCalled()
    unmount()
  })

  it('shows the Google button when the server has it configured', () => {
    const { host, unmount } = setup()
    const google = button(host, 'ادامه با گوگل')
    expect(google.disabled).toBe(false)
    unmount()
  })

  it('disables Google with a reason instead of hiding it', () => {
    /*
     * دکمه‌ی ناموجود کاربر را گیج می‌کند («چرا گزینه‌ی گوگل نیست؟»)؛ دکمه‌ی
     * خاکستری با توضیح می‌گوید چه خبر است و چه باید کرد.
     */
    providersState = { google: false, googleReason: 'needs_https' }
    const { host, unmount } = setup()
    expect(button(host, 'ادامه با گوگل').disabled).toBe(true)
    expect(host.textContent).toContain('https')
    unmount()
  })

  it('signs in with the typed credentials', async () => {
    login.mockResolvedValue(undefined)
    const { host, onDone, unmount } = setup()
    const [username, password] = inputs(host)
    await type(username, 'mahan')
    await type(password, 'hunter2hunter2')

    await act(async () => {
      button(host, 'ورود به حساب').click()
    })

    expect(login).toHaveBeenCalledWith('mahan', 'hunter2hunter2')
    expect(onDone).toHaveBeenCalled()
    unmount()
  })

  it('offers a display name only when creating an account', async () => {
    const { host, unmount } = setup()
    const before = inputs(host).length
    await act(async () => button(host, 'ساخت حساب').click())
    // نام نمایشی یک فیلد اضافه می‌کند
    expect(inputs(host).length).toBe(before + 1)
    unmount()
  })

  it('shows the server error under the form instead of swallowing it', async () => {
    login.mockRejectedValue(new Error('نام کاربری یا رمز اشتباه است'))
    const { host, onDone, unmount } = setup()
    const [username, password] = inputs(host)
    await type(username, 'mahan')
    await type(password, 'wrongwrongwrong')

    await act(async () => {
      button(host, 'ورود به حساب').click()
    })

    const alert = host.querySelector('[role="alert"]')
    expect(alert?.textContent).toContain('نام کاربری یا رمز اشتباه است')
    // خطا یعنی نرفته‌ایم؛ صفحه باید باز بماند
    expect(onDone).not.toHaveBeenCalled()
    unmount()
  })

  it('translates a Google return error from the hash', () => {
    window.location.hash = '#auth_error=expired'
    const { host, unmount } = setup()
    expect(host.textContent).toContain('زمان ورود تمام شد')
    unmount()
  })

  it('labels fields without swallowing the hint into the accessible name', async () => {
    /*
     * اگر ورودی *داخلِ* `<label>` باشد، متنِ راهنما هم بخشی از نامِ فیلد
     * می‌شود و صفحه‌خوان «نام کاربری ۳ تا ۲۴ کاراکتر…» می‌خواند. برچسب جدا و
     * `aria-describedby` این را درست می‌کند.
     */
    const { host, unmount } = setup()
    await act(async () => button(host, 'ساخت حساب').click())

    const username = host.querySelector<HTMLInputElement>('#login-username')!
    expect(username.labels?.[0]?.textContent).toBe('نام کاربری')
    // راهنما هست، ولی از راهِ توضیح نه نام
    expect(username.getAttribute('aria-describedby')).toBe('login-username-hint')
    expect(host.querySelector('#login-username-hint')?.textContent).toContain('۳ تا ۲۴')

    const password = host.querySelector<HTMLInputElement>('#login-password')!
    expect(password.labels?.[0]?.textContent).toBe('رمز')
    unmount()
  })
})
