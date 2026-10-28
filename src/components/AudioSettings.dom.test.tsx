// @vitest-environment jsdom
import { act } from 'react'
import { EQ_PRESETS_DB } from '../lib/audio/dsp/EqPresets'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AudioSettings from './AudioSettings'
import { useSettings } from '../store/settings'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

describe('AudioSettings popover', () => {
  let container: HTMLDivElement
  let root: Root

  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    useSettings.setState({ normalize: true })
  })

  afterEach(() => {
    act(() => root.unmount())
    container.remove()
  })

  it('renders trigger button and toggles open state', () => {
    act(() => {
      root.render(<AudioSettings />)
    })

    const trigger = container.querySelector('button[aria-haspopup="dialog"]') as HTMLButtonElement
    expect(trigger).not.toBeNull()

    // دیالوگ در ابتدا بسته است
    expect(document.body.querySelector('[role="dialog"]')).toBeNull()

    // با کلیک باز می‌شود
    act(() => {
      trigger.click()
    })
    const dialog = document.body.querySelector('[role="dialog"]') as HTMLDivElement
    expect(dialog).not.toBeNull()

    // سوئیچ هم‌ترازی بلندی وجود دارد و فعال است
    const switchBtn = document.body.querySelector('button[role="switch"]') as HTMLButtonElement
    expect(switchBtn).not.toBeNull()
    expect(switchBtn.getAttribute('aria-checked')).toBe('true')
    expect(useSettings.getState().normalize).toBe(true)

    // با کلیک روی سوئیچ، مقدار غیرفعال می‌شود
    act(() => {
      switchBtn.click()
    })
    expect(switchBtn.getAttribute('aria-checked')).toBe('false')
    expect(useSettings.getState().normalize).toBe(false)
  })

  it('toggles equalizer enabled and updates preset in popover', () => {
    useSettings.setState({ eqEnabled: false, eqBands: [0, 0, 0, 0, 0, 0, 0] })
    act(() => {
      root.render(<AudioSettings />)
    })

    const trigger = container.querySelector('button[aria-haspopup="dialog"]') as HTMLButtonElement
    act(() => {
      trigger.click()
    })

    const switches = document.body.querySelectorAll('button[role="switch"]')
    // سوئیچ دوم برای اکولایزر است
    const eqSwitch = switches[1] as HTMLButtonElement
    expect(eqSwitch).not.toBeNull()
    expect(eqSwitch.getAttribute('aria-checked')).toBe('false')

    act(() => {
      eqSwitch.click()
    })
    expect(useSettings.getState().eqEnabled).toBe(true)
    expect(eqSwitch.getAttribute('aria-checked')).toBe('true')

    // با کلیک روی یکی از پریست‌ها، پریست تنظیم می‌شود
    const presetBtns = [...document.body.querySelectorAll('button')].filter((b) =>
      b.getAttribute('aria-pressed') !== null,
    )
    const bassBtn = presetBtns.find((b) => b.textContent?.includes('بم') || b.textContent?.includes('Bass'))
    expect(bassBtn).toBeDefined()
    act(() => {
      bassBtn?.click()
    })
    expect(useSettings.getState().eqBands).toEqual(EQ_PRESETS_DB.BASS_BOOST)
  })

  it('renders as menu item when asMenuItem prop is passed', () => {
    act(() => {
      root.render(<AudioSettings asMenuItem />)
    })

    const trigger = container.querySelector('button[aria-haspopup="dialog"]') as HTMLButtonElement
    expect(trigger).not.toBeNull()
    expect(trigger.textContent).toMatch(/Sound|تنظیم صدا/i)
  })

  it('stays open and does not call onClose when clicking controls inside dialog', () => {
    useSettings.setState({ crossfade: 5, automix: true, smartDj: true })
    const onClose = vi.fn()
    act(() => {
      root.render(<AudioSettings open={true} onClose={onClose} />)
    })

    const dialog = document.body.querySelector('[role="dialog"]') as HTMLDivElement
    expect(dialog).not.toBeNull()

    // تمام سوئیچ‌های داخل پنل
    const switches = document.body.querySelectorAll('button[role="switch"]')
    expect(switches.length).toBeGreaterThanOrEqual(2)

    // کلیک روی یکی از سوئیچ‌ها نباید دیالوگ را ببندد
    const automixSwitch = switches[1] as HTMLButtonElement
    act(() => {
      automixSwitch.click()
    })
    expect(onClose).not.toHaveBeenCalled()
  })
})
