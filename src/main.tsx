import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { registerSW } from 'virtual:pwa-register'
import App from './App'
import ErrorBoundary from './components/ErrorBoundary'
import './index.css'
import { setupNative } from './lib/native'
import { installErrorReporting } from './lib/telemetry'
import { useToasts } from './store/toasts'

/*
 * پوسته‌ی نیتیو پیش از اولین رندر راه می‌افتد، نه بعدش.
 *
 * حاشیه‌های امن متغیرِ CSSاند و اگر بعد از رندر بنشینند، کاربر یک فریم هدرِ
 * چسبیده‌به‌ساعت و نوارِ پخشِ زیرِ نوارِ ژست می‌بیند. `await` هم نمی‌شود کرد —
 * رندر نباید منتظرِ پلِ نیتیو بماند — پس اسپلش تا پایانِ همین کار سرِ جایش
 * می‌ماند و خودِ `setupNative` آخرِ کار برش می‌دارد.
 */
void setupNative()

// باید *پیش از* اولین رندر بنشیند، وگرنه خطای همان رندر (که معمولاً
// مهم‌ترین خط است) رد می‌شود. بی‌صداست: فقط یک fetchِ keepalive.
installErrorReporting()

// مقداردهی اولیه تلگرام مینی‌اپ در صورت باز شدن درون تلگرام
try {
  const tg = (window as unknown as { Telegram?: { WebApp?: { ready: () => void; expand: () => void } } }).Telegram?.WebApp
  tg?.ready?.()
  tg?.expand?.()
} catch {
  // بدون خطا در محیط‌های عادی مرورگر یا PWA
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
)

// در dev غیرفعال است (پلاگین فقط روی build سرویس‌ورکر می‌سازد)؛ اینجا فقط
// نسخه‌ی نصب‌شده‌ی واقعی را آپدیت می‌کند، نه هر رفرش معمولی را کند
registerSW({
  onNeedRefresh() {
    useToasts.getState().push('نسخه‌ی جدید آماده‌ست — صفحه رو رفرش کن', 'info')
  },
  onOfflineReady() {
    useToasts.getState().push('حالا آفلاین هم بالا میاد', 'info')
  },
})
