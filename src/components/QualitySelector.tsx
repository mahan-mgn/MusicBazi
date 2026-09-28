import { usePopover } from '../lib/usePopover'
import { digits } from '../lib/format'
import { useI18n } from '../lib/i18n'
import { CODEC_QUALITIES, MP3_QUALITIES, type Quality } from '../lib/types'
import { useSettings } from '../store/settings'
import { CheckIcon, QualityDiamondIcon, SlidersIcon } from './icons'

interface QualitySelectorProps {
  open: boolean
  onClose: () => void
  onOpenAudioSettings?: () => void
}

/**
 * پاپ‌اور تعاملی و مدرن انتخاب کیفیت استریم داخل پلیر Now Playing.
 */
export default function QualitySelector({
  open,
  onClose,
  onOpenAudioSettings,
}: QualitySelectorProps) {
  const { quality, setQuality } = useSettings()
  const { t, lang } = useI18n()
  const box = usePopover<HTMLDivElement>(open, onClose)

  if (!open) return null

  const pick = (q: Quality) => {
    setQuality(q)
    onClose()
  }

  const isLossless = quality === 'flac' || quality === 'original'

  return (
    <div
      ref={box}
      role="dialog"
      aria-label={t.qualityMenu}
      className="pointer-events-auto fixed bottom-6 start-1/2 -translate-x-1/2 rtl:translate-x-1/2 z-[70] mb-3 w-72 sm:w-80 max-h-[min(26rem,calc(100vh-2rem))] overflow-y-auto space-y-3 rounded-2xl border border-white/15 bg-panel-2/95 p-3.5 shadow-2xl backdrop-blur-2xl ring-1 ring-black/40 animate-in fade-in zoom-in-95 duration-200"
    >
      {/* هدر پاپ‌اور */}
      <div className="flex items-center justify-between border-b border-line-soft pb-2.5">
        <div className="flex items-center gap-2">
          <div className="grid size-7 place-items-center rounded-lg bg-accent/15 text-accent">
            <QualityDiamondIcon className="size-4" />
          </div>
          <div>
            <h4 className="text-xs font-bold text-fg">{t.quality}</h4>
            <p className="text-[10px] text-muted-2">
              {isLossless ? 'Studio Master / Lossless' : 'High Quality Audio'}
            </p>
          </div>
        </div>

        {onOpenAudioSettings && (
          <button
            onClick={() => {
              onClose()
              onOpenAudioSettings()
            }}
            title={t.audioSettings}
            className="flex items-center gap-1 rounded-lg bg-panel/80 px-2 py-1 text-[11px] font-medium text-muted hover:text-fg hover:bg-panel transition"
          >
            <SlidersIcon className="size-3" />
            <span>{t.audioSettings}</span>
          </button>
        )}
      </div>

      {/* بخش کیفیت‌های برتر (Lossless / Studio) */}
      <div className="space-y-1">
        <p className="px-2 text-[10px] font-semibold uppercase tracking-wider text-muted-2">
          Lossless & Studio
        </p>

        <button
          onClick={() => pick('flac')}
          className={`group flex w-full items-center justify-between rounded-xl px-2.5 py-1.5 text-xs transition ${
            quality === 'flac'
              ? 'bg-amber-500/20 text-amber-300 font-semibold ring-1 ring-amber-500/30'
              : 'text-fg hover:bg-white/5'
          }`}
        >
          <div className="flex items-center gap-2">
            <span className="size-1.5 rounded-full bg-amber-400" />
            <span className="font-bold">FLAC</span>
            <span className="text-[10px] text-muted-2">Lossless 16/24-bit</span>
          </div>
          {quality === 'flac' && <CheckIcon className="size-4 text-amber-400" />}
        </button>

        <button
          onClick={() => pick('original')}
          className={`group flex w-full items-center justify-between rounded-xl px-2.5 py-1.5 text-xs transition ${
            quality === 'original'
              ? 'bg-accent/20 text-accent font-semibold ring-1 ring-accent/30'
              : 'text-fg hover:bg-white/5'
          }`}
        >
          <div className="flex items-center gap-2">
            <span className="size-1.5 rounded-full bg-accent" />
            <span className="font-bold">{t.qualityOriginal}</span>
            <span className="text-[10px] text-muted-2">Bit-perfect source</span>
          </div>
          {quality === 'original' && <CheckIcon className="size-4 text-accent" />}
        </button>
      </div>

      {/* بخش MP3 */}
      <div className="space-y-1">
        <p className="px-2 text-[10px] font-semibold uppercase tracking-wider text-muted-2">
          {t.qualityMp3}
        </p>
        <div className="grid grid-cols-3 gap-1.5">
          {MP3_QUALITIES.map((q) => {
            const active = quality === q.id
            return (
              <button
                key={q.id}
                onClick={() => pick(q.id)}
                className={`flex flex-col items-center justify-center rounded-xl py-1.5 text-xs transition ${
                  active
                    ? 'bg-accent font-bold text-accent-fg shadow-sm'
                    : 'bg-panel/70 text-muted hover:text-fg hover:bg-panel'
                }`}
              >
                <span>{digits(q.kbps, lang)}</span>
                <span className={`text-[9px] ${active ? 'text-accent-fg/80' : 'text-muted-2'}`}>kbps</span>
              </button>
            )
          })}
        </div>
      </div>

      {/* بخش کدک‌ها */}
      <div className="space-y-1">
        <p className="px-2 text-[10px] font-semibold uppercase tracking-wider text-muted-2">
          {t.qualityCodec}
        </p>
        <div className="grid grid-cols-2 gap-1.5">
          {CODEC_QUALITIES.map((q) => {
            const active = quality === q.id
            return (
              <button
                key={q.id}
                onClick={() => pick(q.id)}
                className={`flex items-center justify-center gap-1.5 rounded-xl py-1.5 text-xs transition ${
                  active
                    ? 'bg-accent font-bold text-accent-fg shadow-sm'
                    : 'bg-panel/70 text-muted hover:text-fg hover:bg-panel'
                }`}
              >
                <span className="uppercase">{q.label}</span>
                <span className={`text-[9px] ${active ? 'text-accent-fg/80' : 'text-muted-2'}`}>HD</span>
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}
