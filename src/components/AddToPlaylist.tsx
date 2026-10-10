import { useEffect, useState } from 'react'
import { usePopover } from '../lib/usePopover'
import { api } from '../lib/api'
import { useI18n } from '../lib/i18n'
import type { UserPlaylist } from '../lib/types'
import { useToasts } from '../store/toasts'
import { PlaylistIcon, PlusIcon, Spinner } from './icons'

/**
 * «افزودن به پلی‌لیست».
 *
 * فهرست فقط وقتی گرفته می‌شود که باز شود — یک کتابخانه‌ی صدتایی وگرنه صد
 * درخواستِ یکسان می‌زد. پلی‌لیستِ هوشمند اینجا نمی‌آید: عضوش با قانون تعیین
 * می‌شود، نه با انتخابِ دستی.
 *
 * بدنه از دکمه‌اش جدا شده چون سه جا لازمش داریم: دکمه‌ی خودِ ردیف، منویِ «⋯»
 * همان ردیف، و نوارِ انتخابِ چندتایی — و هر سه باید یک رفتار داشته باشند.
 */
export function PlaylistPicker({ jobIds, onDone }: { jobIds: string[]; onDone: () => void }) {
  const { t } = useI18n()
  const pushToast = useToasts((s) => s.push)
  const [lists, setLists] = useState<UserPlaylist[] | null>(null)
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')

  useEffect(() => {
    if (lists !== null) return
    void api
      .playlists()
      .then((found) => setLists(found?.filter((p) => p.kind === 'manual') ?? []))
      .catch(() => setLists([]))
  }, [lists])

  async function add(playlist: UserPlaylist) {
    try {
      const added = await api.addToPlaylist(playlist.id, jobIds)
      pushToast(added ? t.playlistAdded(added) : t.playlistAddedNone, added ? 'success' : 'info')
      onDone()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : t.fetchError, 'error')
    }
  }

  async function createAndAdd() {
    if (!name.trim()) return
    try {
      const created = await api.createPlaylist({ name: name.trim(), jobIds })
      if (!created) return
      pushToast(t.playlistAdded(jobIds.length), 'success')
      setLists([created, ...(lists ?? [])])
      setName('')
      setCreating(false)
      onDone()
    } catch (err) {
      pushToast(err instanceof Error ? err.message : t.fetchError, 'error')
    }
  }

  if (lists === null) {
    return (
      <div className="flex justify-center py-3">
        <Spinner className="size-4 text-muted-2" />
      </div>
    )
  }

  return (
    <>
      {lists.map((playlist) => (
        <button
          key={playlist.id}
          onClick={() => void add(playlist)}
          className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-start text-xs text-muted transition hover:bg-panel-2 hover:text-fg"
        >
          <PlaylistIcon className="size-3.5 shrink-0 text-muted-2" />
          <span className="bidi truncate">{playlist.name}</span>
        </button>
      ))}

      {lists.length > 0 && <div className="my-1 border-t border-line-soft" />}

      {creating ? (
        <div className="flex gap-1 p-1">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && void createAndAdd()}
            placeholder={t.playlistName}
            aria-label={t.playlistName}
            autoFocus
            className="min-w-0 flex-1 rounded-md border border-line bg-panel-2 px-2 py-1 text-[11px] outline-none placeholder:text-muted-2"
          />
          <button
            onClick={() => void createAndAdd()}
            disabled={!name.trim()}
            className="rounded-md bg-accent px-2 py-1 text-[11px] font-semibold text-accent-fg disabled:opacity-50"
          >
            {t.playlistCreate}
          </button>
        </div>
      ) : (
        <button
          onClick={() => setCreating(true)}
          className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-start text-xs text-accent transition hover:bg-panel-2"
        >
          <PlusIcon className="size-3.5 shrink-0" />
          {t.playlistNew}
        </button>
      )}
    </>
  )
}

export default function AddToPlaylist({
  jobIds,
  className = '',
}: {
  jobIds: string[]
  className?: string
}) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const box = usePopover<HTMLDivElement>(open, () => setOpen(false))

  return (
    <div ref={box} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label={t.playlistAdd}
        title={t.playlistAdd}
        className={`grid size-7 place-items-center rounded-md text-muted-2 transition hover:bg-panel-2 hover:text-fg ${className}`}
      >
        <PlaylistIcon className="size-4" />
      </button>

      {open && (
        <div
          className="absolute end-0 z-40 mt-1 w-52 rounded-xl border border-line bg-panel p-1.5 shadow-xl"
        >
          <PlaylistPicker jobIds={jobIds} onDone={() => setOpen(false)} />
        </div>
      )}
    </div>
  )
}
