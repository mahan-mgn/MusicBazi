// @vitest-environment jsdom
//
// چت‌بات وایب دو باگِ واقعی داشت که هر دو «حالتِ بازیابی‌شده» را می‌زدند:
// ردیف‌های تاریخچه‌ی localStorage بعد از رفرش با اسپینری می‌ماندند که هیچ‌وقت
// تمام نمی‌شد، و یک تاریخچه‌ی خراب کل رندر را می‌ترکاند. این‌ها در تستِ توابعِ
// خالص دیده نمی‌شوند — باید رندرِ واقعیِ همان حالت‌ها ادعا شود.
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import MoodChat from './MoodChat'
import { useMoodChat } from '../store/moodChat'

const HISTORY_KEY = 'moodchat:history'

const track = (id: string) => ({
  id,
  title: 'تیتل',
  artist: 'هنرمند',
  durationMs: 200_000,
  artworkUrl: null,
  source: 'soundcloud',
  sourceUrl: `https://soundcloud.com/x/${id}`,
  previewUrl: null,
})

const doneMessage = {
  id: 2,
  role: 'bot',
  status: 'done',
  reply: 'بفرما',
  label: 'غمگین',
  query: { vibe: 'sad' },
  tracks: [{ track: track('t1'), status: 'pending', stale: true }],
}

let host: HTMLDivElement
let root: Root

beforeEach(() => {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  localStorage.clear()
  useMoodChat.getState().setOpen(true)
  host = document.createElement('div')
  document.body.appendChild(host)
})

afterEach(() => {
  act(() => root.unmount())
  host.remove()
  localStorage.clear()
  useMoodChat.getState().setOpen(false)
  vi.unstubAllGlobals()
})

async function render() {
  root = createRoot(host)
  await act(async () => {
    root.render(<MoodChat />)
  })
  await act(async () => {})
}

describe('MoodChat — تاریخچه‌ی بازیابی‌شده', () => {
  it('ردیفِ stale بعد از رفرش اسپینرِ ابدی ندارد', async () => {
    localStorage.setItem(
      HISTORY_KEY,
      JSON.stringify([{ id: 1, role: 'user', text: 'غمگین' }, doneMessage]),
    )
    await render()
    // خودِ ردیفِ ترک رندر شده باشد، وگرنه ادعای پایین تهی است
    expect(host.textContent).toContain('تیتل')
    expect(host.querySelector('.animate-spin')).toBeNull()
  })

  it('تاریخچه‌ی خراب (کاربر بی‌متن، done بی‌tracks) رندر را نمی‌شکند', async () => {
    localStorage.setItem(
      HISTORY_KEY,
      JSON.stringify([
        { id: 1, role: 'user' }, // بی‌text — حبابِ کاربر روی undefined می‌ترکید
        { id: 2, role: 'bot', status: 'done', reply: 'x', tracks: null, query: {}, label: 'x' },
        { id: 3, role: 'bot', status: 'thinking' },
        doneMessage,
      ]),
    )
    await render()
    // فقط پیامِ سالم می‌ماند
    expect(host.textContent).toContain('بفرما')
    expect(host.textContent).not.toContain('داره پلی‌لیست می‌سازه')
  })

  it('ردیفِ تازه (نه stale) همان اسپینر همیشگی را دارد', async () => {
    localStorage.setItem(
      HISTORY_KEY,
      JSON.stringify([
        {
          ...doneMessage,
          tracks: [{ track: track('t1'), status: 'pending' }],
        },
      ]),
    )
    await render()
    // بدونِ stale یعنی ردیفِ زنده‌ی همین نشست است — اسپینر درست است
    expect(host.querySelector('.animate-spin')).not.toBeNull()
  })
})
