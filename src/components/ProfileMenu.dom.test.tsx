// @vitest-environment jsdom

import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * منوی پروفایل در تاپ‌بار.
 *
 * چیزی که این فایل از آن محافظت می‌کند: مهمان باید راهی به صفحه‌ی ورود داشته
 * باشد و کاربرِ وارد‌شده راهی به خروج — بدونِ اینکه برای فهمیدنِ «کدام حالت را
 * می‌بینم؟» لازم باشد به متنِ داخلِ دکمه نگاه کرد.
 */

let userState: { id: string; displayName: string; username: string | null; avatarUrl: string | null } | null =
  null
let loading = false
let offline = false
const logout = vi.fn()

vi.mock('../store/auth', () => ({
  useAuth: Object.assign(
    (selector: (s: unknown) => unknown) =>
      selector({ user: userState, loading, offline, logout }),
    { getState: () => ({ user: userState, loading, offline, logout }) },
  ),
}))

vi.mock('./Artwork', () => ({
  default: ({ alt }: { alt: string }) => <span data-testid="avatar">{alt}</span>,
}))

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const { default: ProfileMenu } = await import('./ProfileMenu')

function setup() {
  const host = document.createElement('div')
  document.body.append(host)
  let root: Root
  const onProfile = vi.fn()
  const onLogin = vi.fn()
  act(() => {
    root = createRoot(host)
    root.render(<ProfileMenu onProfile={onProfile} onLogin={onLogin} />)
  })
  return {
    host,
    onProfile,
    onLogin,
    unmount: () => act(() => root.unmount()),
  }
}

function trigger(host: HTMLElement) {
  return host.querySelector('button') as HTMLButtonElement
}

function menuItems(host: HTMLElement) {
  return [...host.querySelectorAll('[role="menuitem"]')]
}

function click(el: Element) {
  act(() => (el as HTMLElement).click())
}

beforeEach(() => {
  userState = null
  loading = false
  offline = false
  logout.mockReset()
})

afterEach(() => {
  document.body.innerHTML = ''
})

describe('ProfileMenu', () => {
  it('shows the profile button without a menu until it is opened', () => {
    const { host, unmount } = setup()
    expect(menuItems(host)).toHaveLength(0)
    unmount()
  })

  it('offers sign-in to a guest', () => {
    const { host, onLogin, unmount } = setup()
    click(trigger(host))
    const items = menuItems(host)
    expect(items.map((i) => i.textContent)).toContain('ورود')
    click(items[0])
    expect(onLogin).toHaveBeenCalled()
    unmount()
  })

  it('shows the handle and the profile entry when signed in', () => {
    userState = { id: 'u1', displayName: 'مهان', username: 'mahan', avatarUrl: '/api/avatar/u1' }
    const { host, onProfile, unmount } = setup()
    click(trigger(host))
    expect(host.textContent).toContain('@mahan')
    const profile = menuItems(host).find((i) => i.textContent === 'پروفایل')!
    click(profile)
    expect(onProfile).toHaveBeenCalled()
    unmount()
  })

  it('signs out from the menu', () => {
    userState = { id: 'u1', displayName: 'مهان', username: null, avatarUrl: null }
    const { host, unmount } = setup()
    click(trigger(host))
    click(menuItems(host).find((i) => i.textContent === 'خروج از حساب')!)
    expect(logout).toHaveBeenCalled()
    unmount()
  })

  it('falls back to the email when no handle was chosen', () => {
    /*
     * نام کاربری اختیاری است، پس کاربرِ گوگل ممکن است هیچ‌وقت یکی نسازد — و
     * آن‌وقت هویت باید از جای دیگری نشان داده شود.
     */
    userState = { id: 'u1', displayName: 'مهان', username: null, avatarUrl: null }
    const { host, unmount } = setup()
    click(trigger(host))
    expect(host.textContent).toContain('مهان')
    unmount()
  })

  it('does not pretend to be a guest while a stored token is being read', () => {
    /*
     * بازگشت از گوگل یک بارگذاریِ تازه‌ی سند است و پروفایل با یک درخواستِ
     * بعدی می‌آید. در آن پنجره، `user` خالی ولی `loading` روشن است — نشان دادنِ
     * دکمه‌ی «ورود» اینجا یعنی کاربر فکر می‌کند ورودش نگرفت و دنبالِ رفرش
     * می‌رود؛ همان چیزی که این تغییر برای حذفش است.
     */
    loading = true
    const { host, unmount } = setup()
    expect(trigger(host).getAttribute('aria-busy')).toBe('true')
    expect(trigger(host).querySelector('svg.animate-spin')).not.toBeNull()
    unmount()
  })

  it('does not claim to be a guest when the token has no profile yet', () => {
    /*
     * توکن هست ولی `/auth/me` جواب نداد (شبکه یا سرورِ در دسترس‌نبودن).
     * «ورود» نشان دادن اینجا همان علامتی است که کاربر فکر می‌کند ورودش نگرفت؛
     * برچسب و متنِ منو باید بگویند «وارد شده‌ای، پروفایل نیامد».
     */
    offline = true
    const { host, unmount } = setup()
    expect(trigger(host).getAttribute('aria-label')).toBe('حساب در دسترس نیست')
    click(trigger(host))
    expect(host.textContent).toContain('وارد شده‌ای ولی سرور پروفایلت را برنگرداند')
    unmount()
  })

  it('treats a signed-in profile as reachable again', () => {
    // همان کاربر، دفعه‌ی بعد که پروفایل رسید، باید دوباره راهِ پروفایل را ببیند
    offline = true
    userState = { id: 'u1', displayName: 'مهان', username: null, avatarUrl: null }
    const { host, unmount } = setup()
    expect(trigger(host).getAttribute('aria-label')).toBe('باز کردن پروفایل')
    unmount()
  })

  it('labels the button for screen readers in both states', () => {
    const guest = setup()
    expect(trigger(guest.host).getAttribute('aria-label')).toBe('ورود')
    guest.unmount()

    userState = { id: 'u1', displayName: 'مهان', username: null, avatarUrl: null }
    const signed = setup()
    expect(trigger(signed.host).getAttribute('aria-label')).toBe('باز کردن پروفایل')
    signed.unmount()
  })
})
