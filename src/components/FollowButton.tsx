import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { useI18n } from '../lib/i18n'
import type { ArtistDetail } from '../lib/types'
import { useTelegram } from '../store/telegram'
import { useToasts } from '../store/toasts'
import { CheckIcon, PlusIcon, Spinner } from './icons'

/**
 * دکمه‌ی «دنبال کردن» روی صفحه‌ی هنرمند.
 *
 * ردیفِ دنبال‌کردن در دیتابیسِ سرور می‌نشیند و به چتِ وصل‌شده می‌چسبد؛ باتِ
 * تلگرام همان ردیف‌ها را هر ۳۰ دقیقه چک می‌کند و انتشارِ تازه را خودکار
 * می‌فرستد. وب توکنِ تلگرام ندارد، پس اینجا هم مثل بقیه‌ی مسیرهای تلگرامی
 * فقط با سرور حرف می‌زنیم.
 *
 * صفحه‌ی «کاربر» دکمه ندارد: حلقه‌ی بات دیسکوگرافیِ آلبوم‌ها را می‌پاید و
 * کاربر آلبومی ندارد — دکمه‌ای که هیچ‌وقت خبری نمی‌دهد بدتر از نبودنش است.
 */
export default function FollowButton({ artist }: { artist: ArtistDetail }) {
  const { t } = useI18n()
  const pushToast = useToasts((s) => s.push)
  const status = useTelegram((s) => s.status)
  const openPairing = useTelegram((s) => s.openPairing)
  const [followed, setFollowed] = useState(false)
  const [busy, setBusy] = useState(false)

  // وضعیتِ دکمه از سرور می‌آید — همان هنرمند ممکن است از تلگرام دنبال شده باشد
  useEffect(() => {
    const chatId = status?.chatId
    if (chatId == null) return
    let live = true
    api
      .followState(chatId, artist.id)
      .then((s) => live && setFollowed(s.followed))
      .catch(() => {}) // پرسشِ ناموفق فقط یعنی دکمه در حالتِ خنثی می‌ماند
    return () => {
      live = false
    }
  }, [status?.chatId, status?.connected, artist.id])

  // همان قاعده‌ی دکمه‌ی تلگرام: باتِ پایین = دکمه‌ی شکسته نداریم. بعد از
  // هوک‌هاست چون شرطِ بازگشتِ زود، هوکِ بعدی را حذف می‌کند.
  if (!status?.connected) return null

  async function toggle() {
    if (status?.chatId == null) {
      // هنوز چتی وصل نشده — همان پنجره‌ی کدِ همیشگی، بعدش کاربر دوباره می‌زند
      await openPairing()
      return
    }
    setBusy(true)
    try {
      if (followed) {
        await api.unfollow(status.chatId, artist.id)
        setFollowed(false)
        pushToast(t.followStopped(artist.name), 'info')
      } else {
        // seedِ آخرین انتشار از همین صفحه می‌آید؛ بدونش اولین چکِ بات
        // کلِ دیسکوگرافی را «تازه» حساب می‌کرد
        const latestAlbum = artist.albums[0]
        const latestTrack = artist.topTracks[0]
        const lastReleaseId = latestAlbum?.id ?? latestTrack?.id ?? null
        const lastReleaseTitle = latestAlbum?.title ?? latestTrack?.title ?? null
        await api.follow(status.chatId, {
          artistId: artist.id,
          artistName: artist.name,
          artistSourceUrl: artist.sourceUrl,
          source: artist.source,
          artworkUrl: artist.artworkUrl,
          lastReleaseId,
          lastReleaseTitle,
        })
        setFollowed(true)
        pushToast(t.followStarted(artist.name), 'success')
      }
    } catch {
      pushToast(t.followFailed, 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <button
      onClick={toggle}
      disabled={busy}
      title={followed ? t.unfollow : t.followHint}
      aria-pressed={followed}
      className={
        followed
          ? 'inline-flex items-center gap-2 rounded-full border border-accent bg-black/45 px-4 py-2.5 text-sm font-semibold text-accent backdrop-blur-md transition hover:border-danger hover:text-danger'
          : 'inline-flex items-center gap-2 rounded-full border border-white/25 bg-black/45 px-4 py-2.5 text-sm text-white! backdrop-blur-md transition hover:border-white/50 hover:bg-black/60'
      }
    >
      {busy ? (
        <Spinner className="size-4" />
      ) : followed ? (
        <CheckIcon className="size-4" />
      ) : (
        <PlusIcon className="size-4" />
      )}
      {followed ? t.following : t.follow}
    </button>
  )
}
