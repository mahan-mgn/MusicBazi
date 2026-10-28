// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * چرخه‌ی توکنِ مدیا در لایه‌ی HTTP.
 *
 * `readJson` هر پاسخِ سرور را از `attachMediaToken` می‌گذراند و آن از ثبت‌کننده‌ی
 * `mediaToken()` می‌پرسد. برای پاسخِ خودِ `/auth/media` این یعنی پرسیدنِ دوباره —
 * هر پاسخ یک درخواستِ تازه می‌ساخت و `refresh` هرگز تمام نمی‌شد؛ در عمل تاپ‌بار
 * روی «ورود» می‌ماند تا کاربر صفحه را دستی رفرش کند.
 */

const authMediaToken = vi.fn()
let resolveMedia: (() => Promise<string | null>) | null = null

vi.mock('../auth', async () => {
  const actual = await vi.importActual<typeof import('../auth')>('../auth')
  return {
    ...actual,
    token: () => 'session-token',
    clearToken: vi.fn(),
    cachedMediaToken: () => null,
    setMediaToken: vi.fn(),
    attachMediaToken: async function attach<T>(value: T): Promise<T> {
      const media = resolveMedia ? await resolveMedia() : null
      if (!media) return value
      return walk(value, media) as T
    },
  }
})

/** همان کاری که `walkMedia` می‌کند، تا تست مسیرِ واقعی را بسنجد */
function walk(value: unknown, media: string): unknown {
  if (typeof value === 'string') {
    return value.startsWith('/api/downloads/') ? `${value}?mt=${media}` : value
  }
  if (value && typeof value === 'object') {
    const out: Record<string, unknown> = {}
    for (const [key, item] of Object.entries(value)) out[key] = walk(item, media)
    return out
  }
  return value
}

const fetch = vi.fn()

beforeEach(() => {
  vi.stubGlobal('fetch', fetch)
  authMediaToken.mockReset()
  fetch.mockReset()
  resolveMedia = null
})

afterEach(() => {
  vi.unstubAllGlobals()
})

async function freshApi() {
  vi.resetModules()
  return import('./http')
}

function jsonResponse(body: unknown) {
  return {
    ok: true,
    status: 200,
    statusText: 'OK',
    json: async () => body,
  }
}

describe('media token request', () => {
  it('does not re-enter the media resolver for its own response', async () => {
    let mediaCalls = 0
    resolveMedia = async () => {
      mediaCalls++
      return 'media-token'
    }
    fetch.mockResolvedValue(jsonResponse({ token: 'media-token', expiresAt: 123 }))

    const { httpApi } = await freshApi()
    const api = httpApi
    const result = await api.authMediaToken()

    expect(result).toEqual({ token: 'media-token', expiresAt: 123 })
    // صفر بار: پاسخِ همین درخواست اصلاً نباید از مسیرِ توکنِ مدیا بگذرد
    expect(mediaCalls).toBe(0)
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it('still garnishes ordinary responses with the media token', async () => {
    let mediaCalls = 0
    resolveMedia = async () => {
      mediaCalls++
      return 'media-token'
    }
    fetch.mockResolvedValue(jsonResponse({ id: 'u1', avatarUrl: '/api/downloads/x/thumb' }))

    const { httpApi } = await freshApi()
    const api = httpApi
    const user = await api.authMe()

    expect(mediaCalls).toBe(1)
    expect(user.avatarUrl).toBe('/api/downloads/x/thumb?mt=media-token')
  })
})
