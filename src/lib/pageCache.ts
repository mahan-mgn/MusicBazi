import type { AlbumDetail, ArtistDetail, SearchResults } from './types'

/**
 * کشِ صفحه‌ها — تا برگشت به صفحه‌ای که همین حالا دیده‌ای، از نو لود نشود.
 *
 * چرا این‌جا و نه سمتِ سرور: `/api/artist` عمداً آنلاین همیشه از پلتفرم تازه
 * می‌گیرد (کشِ SQLite فقط فالبکِ قطعیِ بین‌الملل است) و همان رفتار باید بماند —
 * صفحه‌ی یک‌ساعته یعنی انتشارِ تازه تا رفرشِ دستی دیده نمی‌شود. پس تازگی سمتِ
 * سرور درست است و آن‌چه کم بود، حافظه‌ی *فرانت* است: محتوایی که کاربر چند لحظه
 * پیش دیده باید فوراً برگردد، حتی وقتی درخواستِ تازه‌ای در پس‌زمینه جریان دارد.
 *
 * فقط در حافظه — با بستنِ اپ می‌رود. نوشتن روی دیسک یعنی سهمیه‌ی localStorage و
 * هزینه‌ی سریالایزِ صفحه‌ی سنگینِ آرتیست، به‌ازای سودی که یک نشستِ کاری هم از آن
 * بیشتر نیاز ندارد.
 */

/** یک دسته‌ی کش با ظرفیتِ محدود. ترتیبِ درج = ترتیبِ LRU. */
export interface Lane<T> {
  read(key: string): T | undefined
  write(key: string, data: T): void
  /**
   * درخواستِ در جریانِ همین کلید را برمی‌گرداند، وگرنه یکی می‌سازد و پاسخِ
   * موفقش را می‌نویسد. یعنی دو مصرف‌کننده‌ی هم‌زمان یک ترک نمی‌فرستند.
   *
   * سیگنال را *خودِ خط* می‌سازد و به کارخانه می‌دهد — عمداً، وگرنه مصرف‌کننده‌ای
   * که زودتر می‌رود، با `abort`ش درخواستِ مشترک را می‌کشد و مصرف‌کننده‌ی بعدی
   * همان کلید یک `AbortError` می‌گیرد. در `StrictMode` این هر بار رخ می‌دهد:
   * افکت دو بار سوار می‌شود و پاک‌سازیِ دورِ اول، درخواستِ دورِ دوم را می‌کشد.
   */
  load(key: string, run: (signal: AbortSignal) => Promise<T>): Promise<T>
  /** دور انداختنِ کلید — اگر درخواستی در جریان باشد، لغوش هم می‌کند */
  drop(key: string): void
  size(): number
  clear(): void
}

export function createLane<T>(max: number): Lane<T> {
  const entries = new Map<string, T>()
  const inflight = new Map<string, Promise<T>>()
  const controllers = new Map<string, AbortController>()

  const touch = (key: string, data: T) => {
    // درجِ دوباره هم مقدار را نو می‌کند هم کلید را به انتهای Map می‌برد؛
    // بدونِ این حذفِ دوباره، ترتیبِ درج کهنه می‌ماند و LRU اشتباه قربانی می‌گیرد
    entries.delete(key)
    entries.set(key, data)
    while (entries.size > max) {
      const oldest = entries.keys().next().value
      if (oldest === undefined) break
      entries.delete(oldest)
    }
  }

  const forget = (key: string) => {
    inflight.delete(key)
    controllers.delete(key)
  }

  return {
    read: (key) => entries.get(key),
    write: touch,
    load: (key, run) => {
      const pending = inflight.get(key)
      if (pending) return pending

      const controller = new AbortController()
      controllers.set(key, controller)

      /*
       * `Promise.resolve().then(...)` نه `run(...)` مستقیم: اگر خودِ `run` پرت
       * کند (نه این‌که Promiseِ ردشده برگرداند) هم به یک Promiseِ ردشده تبدیل
       * می‌شود، پس پاک‌سازیِ پایین در هر حالتی اجرا می‌شود.
       */
      const request = Promise.resolve()
        .then(() => run(controller.signal))
        .then((data) => {
          touch(key, data)
          return data
        })
        .finally(() => {
          // موفق باشد یا نه، این درخواست تمام شده. Promiseِ شکست‌خورده نباید تا
          // ابد «در جریان» بماند، وگرنه «تلاش دوباره» همیشه همان شکستِ قبلی را
          // می‌بیند. `finally` ردشدن را دست‌نخورده رد می‌کند، پس مصرف‌کننده
          // همچنان خطا را می‌گیرد.
          forget(key)
        })
      inflight.set(key, request)
      return request
    },
    drop: (key) => {
      controllers.get(key)?.abort()
      forget(key)
      entries.delete(key)
    },
    size: () => entries.size,
    clear: () => {
      for (const controller of controllers.values()) controller.abort()
      entries.clear()
      inflight.clear()
      controllers.clear()
    },
  }
}

/*
 * سقف‌ها اندازه‌گیری نشده‌اند، تخمینِ محافظه‌کارانه‌اند: صفحه‌ی آرتیست بزرگ‌ترین
 * بار است (دیسکوگرافیِ کامل) و ۱۲ تا برای یک نشستِ کاری سخاوتمندانه است؛
 * ترک‌های جستجو و آلبوم کوچک‌ترند پس جای بیشتری دارند. همه سه Map چند صد
 * کیلوبایت می‌شوند، در برابرِ صدها مگابایتی که فایل‌های صوتی می‌گیرند ناچیز.
 */
export const pageCache = {
  results: createLane<SearchResults>(20),
  artist: createLane<ArtistDetail>(12),
  album: createLane<AlbumDetail>(20),
  clearAll() {
    pageCache.results.clear()
    pageCache.artist.clear()
    pageCache.album.clear()
  },
}
