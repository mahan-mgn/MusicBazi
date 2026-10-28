/*
 * مدیریت کش استریم‌های صوتی در مرورگر (Web Audio Stream Cache Manager)
 *
 * معادل `AudioCacheManager.kt` اندروید (بر پایه Media3 SimpleCache با ردیابی LRU).
 * استریم‌های پخش‌شده یا پیش‌بارگذاری‌شده را در Cache Storage ذخیره می‌کند تا
 * در صورت اختلال یا قطعی شبکه اینترانت خانگی، پخش بدون توقف ادامه یابد.
 */

const STREAM_CACHE_NAME = 'musicbazi-stream-cache-v1'
const MAX_CACHED_TRACKS = 50
const ACCESS_TRACKER_KEY = 'mb_stream_cache_lru'

interface CacheEntry {
  url: string
  lastAccess: number
  sizeEstimate?: number
}

function getLruList(): CacheEntry[] {
  if (typeof localStorage === 'undefined') return []
  try {
    const raw = localStorage.getItem(ACCESS_TRACKER_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function saveLruList(list: CacheEntry[]): void {
  if (typeof localStorage === 'undefined') return
  try {
    localStorage.setItem(ACCESS_TRACKER_KEY, JSON.stringify(list))
  } catch {
    // خطای سقف حافظه localStorage
  }
}

export class WebAudioCacheManager {
  static isSupported(): boolean {
    return typeof caches !== 'undefined'
  }

  /**
   * بررسی اینکه آیا استریم در کش موجود است
   */
  static async has(url: string): Promise<boolean> {
    if (!this.isSupported()) return false
    try {
      const cache = await caches.open(STREAM_CACHE_NAME)
      const matched = await cache.match(url)
      return Boolean(matched)
    } catch {
      return false
    }
  }

  /**
   * دریافت استریم از کش در صورت وجود
   */
  static async get(url: string): Promise<Response | null> {
    if (!this.isSupported()) return null
    try {
      const cache = await caches.open(STREAM_CACHE_NAME)
      const response = await cache.match(url)
      if (response) {
        this.touch(url)
        return response
      }
      return null
    } catch {
      return null
    }
  }

  /**
   * ذخیره یک استریم کامل یا بافر اولیه آن در کش
   */
  static async put(url: string, response: Response): Promise<void> {
    if (!this.isSupported()) return
    try {
      const cache = await caches.open(STREAM_CACHE_NAME)
      await cache.put(url, response.clone())
      this.touch(url)
      void this.prune()
    } catch (err) {
      console.warn('[WebAudioCacheManager] Failed to put stream in cache:', err)
    }
  }

  /**
   * به‌روزرسانی برچسب زمان دسترسی جهت الگوریتم LRU
   */
  private static touch(url: string): void {
    const list = getLruList().filter((e) => e.url !== url)
    list.unshift({ url, lastAccess: Date.now() })
    saveLruList(list.slice(0, MAX_CACHED_TRACKS * 2))
  }

  /**
   * حذف قدیمی‌ترین آیتم‌ها طبق سیاست LRU در صورت تجاوز از سقف تعداد
   */
  private static async prune(): Promise<void> {
    const list = getLruList()
    if (list.length <= MAX_CACHED_TRACKS) return

    const toRemove = list.slice(MAX_CACHED_TRACKS)
    const toKeep = list.slice(0, MAX_CACHED_TRACKS)

    try {
      const cache = await caches.open(STREAM_CACHE_NAME)
      for (const item of toRemove) {
        await cache.delete(item.url)
      }
      saveLruList(toKeep)
    } catch (err) {
      console.warn('[WebAudioCacheManager] Error pruning cache:', err)
    }
  }

  /**
   * پاک‌سازی کامل کش استریم‌ها
   */
  static async clear(): Promise<void> {
    if (!this.isSupported()) return
    try {
      await caches.delete(STREAM_CACHE_NAME)
      if (typeof localStorage !== 'undefined') {
        localStorage.removeItem(ACCESS_TRACKER_KEY)
      }
    } catch (err) {
      console.warn('[WebAudioCacheManager] Failed to clear stream cache:', err)
    }
  }
}
