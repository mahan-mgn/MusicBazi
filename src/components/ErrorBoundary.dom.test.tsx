// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ErrorBoundary from './ErrorBoundary'

// @ts-expect-error React act environment flag
globalThis.IS_REACT_ACT_ENVIRONMENT = true

function Bomb({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) {
    throw new Error('Test explosion')
  }
  return <div>Component rendered safely</div>
}

describe('ErrorBoundary', () => {
  let container: HTMLDivElement
  let root: Root

  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    // Suppress console.error during error boundary tests
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    act(() => root.unmount())
    container.remove()
    vi.restoreAllMocks()
  })

  it('renders children normally when there is no error', () => {
    act(() => {
      root.render(
        <ErrorBoundary>
          <Bomb shouldThrow={false} />
        </ErrorBoundary>,
      )
    })

    expect(container.textContent).toContain('Component rendered safely')
  })

  it('catches render error and displays friendly fallback instead of black screen', () => {
    act(() => {
      root.render(
        <ErrorBoundary>
          <Bomb shouldThrow={true} />
        </ErrorBoundary>,
      )
    })

    expect(container.textContent).toContain('مشکلی در اجرای برنامه پیش آمد')
    expect(container.textContent).toContain('تلاش مجدد')
    expect(container.textContent).toContain('بارگذاری مجدد')
    expect(container.textContent).toContain('صفحه اصلی')
    expect(container.textContent).toContain('Test explosion')
  })

  it('allows recovering via reset after error condition is cleared', () => {
    let throwError = true
    function ControlledBomb() {
      if (throwError) throw new Error('Boom')
      return <div>Recovered safely</div>
    }

    act(() => {
      root.render(
        <ErrorBoundary>
          <ControlledBomb />
        </ErrorBoundary>,
      )
    })

    expect(container.textContent).toContain('مشکلی در اجرای برنامه پیش آمد')

    // Clear error condition and click retry
    throwError = false
    const retryBtn = Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('تلاش مجدد'),
    )
    expect(retryBtn).toBeDefined()

    act(() => {
      retryBtn?.click()
    })

    expect(container.textContent).toContain('Recovered safely')
  })
})
