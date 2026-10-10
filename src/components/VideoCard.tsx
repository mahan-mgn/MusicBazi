import { duration, formatViews } from '../lib/format'
import { useI18n } from '../lib/i18n'
import type { Track } from '../lib/types'
import Artwork from './Artwork'
import { PauseIcon, PlayIcon } from './icons'

interface Props {
  track: Track
  isPlaying?: boolean
  onPlay: () => void
}

export default function VideoCard({ track, isPlaying = false, onPlay }: Props) {
  const { lang, t } = useI18n()
  const durationText = track.durationMs > 0 ? duration(track.durationMs, lang) : null

  return (
    <div className="group relative flex w-full flex-col overflow-hidden rounded-xl border border-line-soft bg-panel/50 p-2 text-start transition hover:border-line hover:bg-panel-2">
      <div className="relative aspect-video w-full overflow-hidden rounded-lg bg-black/40">
        <Artwork
          src={track.artworkUrl}
          alt={track.title}
          seed={track.id}
          rounded="rounded-lg"
          className="size-full object-cover transition duration-300 group-hover:scale-105"
        />

        {/* دکمه پخش وسط تصویر */}
        <button
          type="button"
          onClick={onPlay}
          aria-label={isPlaying ? t.pause : t.playTrack(track.title)}
          className={`absolute inset-0 grid place-items-center bg-black/35 transition ${
            isPlaying ? 'opacity-100' : 'opacity-0 group-hover:opacity-100 focus-visible:opacity-100'
          }`}
        >
          <span className="grid size-10 place-items-center rounded-full bg-accent text-accent-fg shadow-xl transition-transform group-hover:scale-110">
            {isPlaying ? <PauseIcon className="size-4" /> : <PlayIcon className="size-4 ms-0.5" />}
          </span>
        </button>

        {/* نشان مدت زمان گوشه تصویر */}
        {durationText && (
          <span className="absolute bottom-1.5 end-1.5 rounded bg-black/80 px-1.5 py-0.5 text-[10px] font-semibold text-white backdrop-blur-xs">
            {durationText}
          </span>
        )}
      </div>

      <div className="mt-2 flex-1 min-w-0 px-0.5">
        <h4
          onClick={onPlay}
          className="bidi line-clamp-2 cursor-pointer text-xs font-bold text-fg transition-colors hover:text-accent sm:text-sm"
          title={track.title}
        >
          {track.title}
        </h4>
        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[10px] text-muted-2 sm:text-xs">
          <span className="truncate">{track.artist}</span>
          {track.views && (
            <>
              <span>•</span>
              <span className="shrink-0">{formatViews(track.views, lang)}</span>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
