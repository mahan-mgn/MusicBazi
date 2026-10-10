// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ThinSlider from './ThinSlider'

let host: HTMLDivElement
let root: Root

beforeEach(() => {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
})

afterEach(() => {
  act(() => {
    root.unmount()
  })
  host.remove()
  vi.restoreAllMocks()
})

describe('ThinSlider component', () => {
  it('renders with role="slider" and correct aria attributes', () => {
    act(() => {
      root.render(<ThinSlider value={30} min={0} max={100} label="Seek bar" />)
    })

    const slider = host.querySelector('[role="slider"]')
    expect(slider).toBeDefined()
    expect(slider?.getAttribute('aria-label')).toBe('Seek bar')
    expect(slider?.getAttribute('aria-valuenow')).toBe('30')
    expect(slider?.getAttribute('aria-valuemin')).toBe('0')
    expect(slider?.getAttribute('aria-valuemax')).toBe('100')
  })

  it('handles arrow key navigation to increment/decrement value', () => {
    const onChange = vi.fn()
    const onChangeFinished = vi.fn()

    act(() => {
      root.render(
        <ThinSlider
          value={50}
          min={0}
          max={100}
          onChange={onChange}
          onChangeFinished={onChangeFinished}
        />,
      )
    })

    const slider = host.querySelector('[role="slider"]') as HTMLDivElement
    expect(slider).toBeDefined()

    act(() => {
      slider.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }))
    })

    expect(onChange).toHaveBeenCalledWith(55)
    expect(onChangeFinished).toHaveBeenCalledWith(55)

    act(() => {
      slider.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }))
    })

    expect(onChange).toHaveBeenCalledWith(45)
    expect(onChangeFinished).toHaveBeenCalledWith(45)
  })

  it('reports the final pointer value before marking the change finished', () => {
    const onChange = vi.fn()
    const onChangeFinished = vi.fn()

    act(() => {
      root.render(
        <ThinSlider
          value={0}
          max={100}
          onChange={onChange}
          onChangeFinished={onChangeFinished}
        />,
      )
    })

    const slider = host.querySelector('[role="slider"]') as HTMLDivElement
    const bar = slider.querySelector('div') as HTMLDivElement
    vi.spyOn(bar, 'getBoundingClientRect').mockReturnValue({
      left: 0,
      right: 100,
      top: 0,
      bottom: 6,
      width: 100,
      height: 6,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    })

    const pointerEvent = (type: string) => {
      const event = new Event(type, { bubbles: true, cancelable: true })
      Object.defineProperties(event, {
        pointerId: { value: 1 },
        clientX: { value: 75 },
      })
      return event
    }

    act(() => {
      slider.dispatchEvent(pointerEvent('pointerdown'))
    })
    act(() => {
      slider.dispatchEvent(pointerEvent('pointerup'))
    })

    expect(onChange).toHaveBeenLastCalledWith(75)
    expect(onChangeFinished).toHaveBeenCalledWith(75)
    expect(onChange.mock.invocationCallOrder.at(-1)).toBeLessThan(
      onChangeFinished.mock.invocationCallOrder[0],
    )
  })

  it('respects disabled prop', () => {
    const onChange = vi.fn()

    act(() => {
      root.render(<ThinSlider value={50} min={0} max={100} disabled onChange={onChange} />)
    })

    const slider = host.querySelector('[role="slider"]') as HTMLDivElement
    expect(slider.getAttribute('tabindex')).toBe('-1')
    expect(slider.className).toContain('cursor-not-allowed')

    act(() => {
      slider.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }))
    })

    expect(onChange).not.toHaveBeenCalled()
  })
})
