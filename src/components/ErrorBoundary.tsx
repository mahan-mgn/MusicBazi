import { Component, type ErrorInfo, type ReactNode } from 'react'
import { apiUrl, isNativeApp, serverBase } from '../lib/server'
import { WarnIcon } from './icons'

interface Props {
  children: ReactNode
  fallback?: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
  errorInfo: ErrorInfo | null
}

export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
    }
  }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    this.setState({ errorInfo })

    // ارسال خطا به تله‌متری سرور در صورت امکان
    try {
      if (serverBase()) {
        void fetch(apiUrl('/api/client-error'), {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            kind: 'react-error-boundary',
            message: (error?.message ?? 'Unknown error').slice(0, 4000),
            stack: ((error?.stack ?? '') + '\n' + (errorInfo?.componentStack ?? '')).slice(0, 4000),
            url: location.pathname + location.search,
            app: isNativeApp() ? 'android' : 'web',
            device: navigator.userAgent.slice(0, 200),
          }),
          keepalive: true,
        }).catch(() => {})
      }
    } catch {
      // نادیده گرفتن خطای ارسال
    }
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null, errorInfo: null })
  }

  handleReload = () => {
    window.location.reload()
  }

  handleHome = () => {
    window.location.href = '/'
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback
      }

      return (
        <div
          role="alert"
          className="flex min-h-dvh w-full flex-col items-center justify-center bg-[#070707] px-4 py-8 text-[#f2f2f2] font-sans antialiased"
          dir="rtl"
        >
          <div className="relative mx-auto flex w-full max-w-md flex-col items-center rounded-2xl border border-white/10 bg-white/[0.04] p-6 text-center shadow-2xl backdrop-blur-xl sm:p-8">
            <div className="mb-4 grid size-14 place-items-center rounded-2xl bg-amber-500/10 text-amber-400 ring-1 ring-amber-500/20">
              <WarnIcon className="size-7" />
            </div>

            <h1 className="text-lg font-bold sm:text-xl">مشکلی در اجرای برنامه پیش آمد</h1>
            <p className="mt-2 text-xs leading-relaxed text-[#999] sm:text-sm">
              یک خطای غیرمنتظره در رندر صفحه رخ داد. داده‌های شما حفظ شده‌اند و می‌توانید صفحه را بازنشانی کنید.
            </p>

            <div className="mt-6 flex w-full flex-col gap-2 sm:flex-row sm:justify-center">
              <button
                type="button"
                onClick={this.handleReset}
                className="inline-flex h-10 items-center justify-center rounded-xl bg-white/10 px-4 text-xs font-semibold text-white transition hover:bg-white/15 active:scale-95"
              >
                تلاش مجدد
              </button>
              <button
                type="button"
                onClick={this.handleReload}
                className="inline-flex h-10 items-center justify-center rounded-xl bg-accent px-4 text-xs font-semibold text-accent-fg shadow-lg shadow-accent/20 transition hover:brightness-110 active:scale-95"
              >
                بارگذاری مجدد
              </button>
              <button
                type="button"
                onClick={this.handleHome}
                className="inline-flex h-10 items-center justify-center rounded-xl border border-white/10 px-4 text-xs font-semibold text-[#bbb] transition hover:border-white/20 hover:text-white active:scale-95"
              >
                صفحه اصلی
              </button>
            </div>

            {this.state.error && (
              <details className="mt-6 w-full text-start text-[11px] text-[#777]">
                <summary className="cursor-pointer select-none text-[#999] hover:text-white">
                  جزئیات فنی خطا
                </summary>
                <div
                  className="mt-2 max-h-40 overflow-auto rounded-lg bg-black/50 p-3 font-mono text-[10px] text-red-300/80"
                  dir="ltr"
                >
                  <p className="font-bold">{this.state.error.name}: {this.state.error.message}</p>
                  {this.state.error.stack && (
                    <pre className="mt-1 whitespace-pre-wrap">{this.state.error.stack}</pre>
                  )}
                </div>
              </details>
            )}
          </div>
        </div>
      )
    }

    return this.props.children
  }
}
