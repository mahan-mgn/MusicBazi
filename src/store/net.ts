import { create } from 'zustand'
import { api } from '../lib/api'
import { useI18n } from '../lib/i18n'
import { onNetworkChange } from '../lib/native'
import { useToasts } from './toasts'

/**
 * وضعیتِ شبکه در سه لایه — چون سه چیزِ متفاوت‌اند و کاربر برای هرکدام کارِ
 * متفاوتی باید بکند:
 *
 *   `device`   دستگاه اصلاً شبکه ندارد (وای‌فای/دیتا قطع). فقط چیزهایی که در
 *              مرورگر سنجاق شده‌اند پخش می‌شوند.
 *   `server`   شبکه هست ولی خودِ سرور جواب نمی‌دهد — کامپیوترِ خانه خاموش است،
 *              یا آدرسِ سرور در اپِ اندروید اشتباه است.
 *   `internet` سرور جواب می‌دهد ولی اینترنتِ بین‌الملل قطع است. کتابخانه،
 *              پلی‌لیست‌ها و هرچه کش شده کار می‌کنند؛ جستجوی زنده و دانلودِ
 *              تازه نه.
 *
 * لایه‌ی سوم را هیچ APIی در مرورگر نمی‌داند: از دیدِ گوشی، وای‌فای وصل است و
 * `navigator.onLine` می‌گوید آنلاین‌ای. تنها جایی که می‌شود فهمید، خودِ سرور
 * است — و برای همین این استور از سرور می‌پرسد، نه از مرورگر.
 */

/** فاصله‌ی پرسیدن وقتی همه‌چیز روبه‌راه است */
const POLL_OK = 30_000

/**
 * فاصله‌ی پرسیدن وقتی چیزی قطع است.
 *
 * تندتر، چون برگشتنِ اینترنت خبری است که کاربر منتظرش است و صفِ دانلودِ معوق
 * به آن بند است. خودِ اندپوینت فقط یک بولِ در حافظه را می‌خواند، پس این تندی
 * چیزی از سرور نمی‌گیرد.
 */
const POLL_DOWN = 10_000

export type NetLayer = 'ok' | 'internet' | 'server' | 'device' | 'unknown'

interface NetState {
  layer: NetLayer
  /** زمانِ آخرین بررسیِ *سرور* (اپاکِ ثانیه‌ای) — نه زمانِ آخرین پرسشِ ما */
  checkedAt: number
  /** پروبِ دستی در جریان است — دکمه‌ی «دوباره امتحان کن» */
  checking: boolean
  /** شروعِ پایشِ دوره‌ای. تابعِ برگشتی همه‌چیز را جمع می‌کند. */
  watch: () => () => void
  /** پروبِ فوری، با کلیکِ کاربر */
  recheck: () => Promise<void>
  /**
   * یک درخواستِ واقعی با کدِ «اینترانت» برگشت.
   *
   * مجانی‌ترین سیگنالِ ممکن است و از پروب دقیق‌تر: سرور همین الان صریح گفت
   * بین‌الملل ندارد. بدون این، نوارِ وضعیت تا دورِ بعدیِ پایش نمی‌آمد و کاربر
   * یک خطای بی‌توضیح می‌دید.
   */
  noteIntranet: () => void
}

/** آیا جستجوی زنده و دانلودِ تازه همین حالا ممکن است */
export function useOnline(): boolean {
  // `unknown` خوش‌بینانه آنلاین حساب می‌شود: تا وقتی چیزی خلافش نگفته، بستنِ
  // قابلیت‌ها فقط یک برنامه‌ی بی‌دلیل فلج است — مود دمو دقیقاً همین حالت است
  return useNet((s) => s.layer === 'ok' || s.layer === 'unknown')
}

/** آیا در حالتِ اینترانت‌ایم — سرور هست، بین‌الملل نه */
export function useIntranet(): boolean {
  return useNet((s) => s.layer === 'internet')
}

async function probe(recheck: boolean): Promise<NetLayer> {
  // مرورگر که می‌گوید شبکه نیست، حرفش سند است — درخواست زدن فقط یک تایم‌اوتِ
  // بی‌فایده است. عکسش صادق نیست و برای همین بقیه‌ی این تابع وجود دارد.
  if (typeof navigator !== 'undefined' && navigator.onLine === false) return 'device'

  try {
    const status = await api.netStatus(recheck)
    if (status === null) return 'unknown'
    return status.online ? 'ok' : 'internet'
  } catch {
    // به خودِ سرور نرسیدیم. با شبکه‌ی سالمِ دستگاه یعنی سرور بالا نیست یا
    // آدرسش اشتباه است — که پیامِ کاملاً متفاوتی می‌خواهد.
    return 'server'
  }
}

export const useNet = create<NetState>((set, get) => ({
  layer: 'unknown',
  checkedAt: 0,
  checking: false,

  watch: () => {
    let timer: ReturnType<typeof setTimeout> | undefined
    let stopped = false
    // بدونِ این، هر رویدادِ بیداری (آنلاین/آفلاین/برگشتن به تب) یک زنجیره‌ی
    // تایمرِ *تازه* راه می‌انداخت بی‌آنکه قبلی را ببندد. چند زنجیره‌ی موازی
    // یعنی چند برابر درخواست به سرور، و بدتر: نتیجه‌ی یک پروبِ کهنه می‌توانست
    // بعد از یک پروبِ تازه بنشیند و وضعیت را عقب ببرد.
    let inflight = false

    const tick = async () => {
      if (stopped || inflight) return
      inflight = true
      clearTimeout(timer)
      try {
        // تبِ پنهان نباید هر ده ثانیه سرور را بیدار کند؛ موقعِ برگشتن،
        // شنونده‌ی پایین فوراً یک بررسیِ تازه می‌زند
        if (typeof document === 'undefined' || document.visibilityState === 'visible') {
          const layer = await probe(false)
          if (stopped) return
          set({ layer, checkedAt: Date.now() / 1000 })
        }
      } finally {
        inflight = false
        if (!stopped) timer = setTimeout(tick, get().layer === 'ok' ? POLL_OK : POLL_DOWN)
      }
    }

    // بلافاصله، نه بعد از اولین فاصله: کاربری که برنامه را در حالتِ قطعی باز
    // می‌کند نباید ده ثانیه یک UIِ خوش‌بینانه ببیند و بعد نوار بپرد
    void tick()

    const wake = () => void tick()
    const offNet = onNetworkChange(wake)
    window.addEventListener('online', wake)
    window.addEventListener('offline', wake)
    document.addEventListener('visibilitychange', wake)

    return () => {
      stopped = true
      clearTimeout(timer)
      offNet()
      window.removeEventListener('online', wake)
      window.removeEventListener('offline', wake)
      document.removeEventListener('visibilitychange', wake)
    }
  },

  noteIntranet: () => {
    if (get().layer !== 'internet') set({ layer: 'internet', checkedAt: Date.now() / 1000 })
  },

  recheck: async () => {
    if (get().checking) return
    set({ checking: true })
    try {
      // `true` یعنی سرور همین الان واقعاً پروب بزند. اگر اینترنت برگشته باشد،
      // همان درخواست صفِ دانلودِ معوق را هم راه می‌اندازد.
      const layer = await probe(true)
      set({ layer, checkedAt: Date.now() / 1000 })

      // بازخوردِ صریح، در هر دو جهت.
      //
      // موفقیت خودش دیده می‌شود (نوار غیب می‌شود) ولی شکست هیچ اثرِ بصری
      // نداشت: کاربر دکمه را می‌زد، چیزی عوض نمی‌شد، و نتیجه می‌گرفت خودِ
      // دکمه خراب است. سکوت بدترین جوابِ ممکن برای دکمه‌ای است که تنها راهِ
      // خروجِ دستی از این حالت است.
      const { t } = useI18n.getState()
      useToasts.getState().push(layer === 'ok' ? t.netBack : t.netStillDown, 'info')
    } finally {
      set({ checking: false })
    }
  },
}))
