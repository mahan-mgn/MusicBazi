import { useCallback, useEffect, useState } from 'react'
import { useDialog } from '../lib/useDialog'
import { api, API_MODE } from '../lib/api'
import { duration as fmtDuration } from '../lib/format'
import { useI18n } from '../lib/i18n'
import type { CandidateOption, Quality, Source, Track } from '../lib/types'
import { useDownloads } from '../store/downloads'
import { useToasts } from '../store/toasts'
import SourceBadge from './SourceBadge'
import { CloseIcon, LinkIcon, Spinner } from './icons'

/**
 * انتخاب دستی نسخه.
 *
 * resolver از روی عنوان و مدت‌زمان امتیاز می‌دهد و زیر آستانه ترجیح می‌دهد شکست
 * بخورد تا فایل اشتباه بدهد — که یعنی گاهی هیچی نمی‌دهد. این دیالوگ همان لیستِ
 * کاندیدها را بدون آستانه نشان می‌دهد و تصمیم را به کاربر می‌دهد.
 */
export default function SourcePicker({
  track,
  quality,
  onClose,
}: {
  track: Track
  quality: Quality
  onClose: () => void
}) {
  const [options, setOptions] = useState<CandidateOption[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [searched, setSearched] = useState<Source[]>([])
  const { t, lang } = useI18n()
  const pickSource = useDownloads((s) => s.pickSource)
  const pushToast = useToasts((s) => s.push)
  // این دیالوگ گاهی *روی* یک مودالِ دیگر باز می‌شود (از منویِ ردیفِ کتابخانه)؛
  // قفلِ اسکرولِ `useDialog` شمارشی است و همان‌جا هم درست می‌ماند
  const dialog = useDialog<HTMLDivElement>(true, onClose)

  const load = useCallback(
    async (source?: Source) => {
      setLoading(true)
      try {
        const found = await api.candidates(track, source)
        if (found === null) {
          setOptions([])
          return
        }
        // نتایج منبع دوم به قبلی‌ها اضافه می‌شوند، جایگزینشان نمی‌شوند
        setOptions((prev) => [...(prev ?? []), ...found])
        if (source) setSearched((prev) => [...prev, source])
      } catch {
        pushToast(t.pickSourceFailed, 'error')
        setOptions((prev) => prev ?? [])
      } finally {
        setLoading(false)
      }
    },
    [track, pushToast, t],
  )

  // فقط یک بار موقع باز شدن — `load` خودش برای دکمه‌ی ساندکلاد صدا زده می‌شود
  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function choose(option: CandidateOption) {
    pickSource(track, quality, option.url)
    onClose()
  }

  const supported = API_MODE === 'http'
  const items = options ?? []
  const searchedSources = new Set<Source>(searched)
  for (const item of items) {
    if (item.source) searchedSources.add(item.source)
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t.pickSourceTitle(track.title)}
      className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-3 pb-[calc(0.75rem+var(--safe-b))] backdrop-blur-sm sm:p-4"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        ref={dialog}
        tabIndex={-1}
        className="glass toast-in flex max-h-[80dvh] w-full max-w-lg flex-col overflow-hidden rounded-2xl shadow-2xl shadow-black/50"
      >
        <div className="flex items-start gap-3 border-b border-line-soft px-4 py-3">
          <div className="min-w-0 flex-1">
            <h2 className="bidi truncate text-sm font-semibold">
              {t.pickSourceTitle(track.title)}
            </h2>
            <p className="mt-1 text-[11px] leading-5 text-muted">
              {supported ? t.pickSourceBody : t.pickSourceUnavailable}
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label={t.close}
            className="grid size-9 shrink-0 place-items-center rounded-md text-muted-2 transition hover:bg-panel-2 hover:text-fg sm:size-7"
          >
            <CloseIcon className="size-4" />
          </button>
        </div>

        <div className="scroll-pane min-h-0 flex-1 space-y-1 overflow-y-auto p-2">
          {items.map((option) => (
            <div
              key={option.url}
              className="group flex items-center gap-2 rounded-lg px-2 py-2 transition hover:bg-panel-2"
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <p className="bidi truncate text-xs" title={option.title}>
                    {option.title}
                  </p>
                  <SourceBadge source={option.source} />
                </div>
                <p className="bidi truncate text-[11px] text-muted">
                  <bdi>{option.uploader}</bdi>
                  {option.durationMs
                    ? ` · ${fmtDuration(option.durationMs, lang)}`
                    : ''}
                  {` · ${t.matchScore(Math.round(option.score))}`}
                </p>
              </div>

              <a
                href={option.url}
                target="_blank"
                rel="noreferrer"
                title={t.openCandidate}
                aria-label={t.openCandidate}
                className="hover-reveal grid size-8 shrink-0 place-items-center rounded-md text-muted-2 opacity-0 transition hover:text-fg group-hover:opacity-100 sm:size-7"
              >
                <LinkIcon className="size-3.5" />
              </a>

              <button
                onClick={() => choose(option)}
                className="shrink-0 rounded-md border border-accent/40 bg-accent-dim px-2 py-1 text-[11px] font-semibold text-accent transition hover:brightness-110"
              >
                {t.useThis}
              </button>
            </div>
          ))}

          {loading && (
            <p className="flex items-center justify-center gap-2 p-6 text-xs text-muted">
              <Spinner className="size-4" />
              {t.searching}
            </p>
          )}

          {!loading && !items.length && (
            <p className="p-6 text-center text-xs text-muted">
              {supported ? t.pickSourceEmpty : t.pickSourceUnavailable}
            </p>
          )}
        </div>

        {supported && !searchedSources.has('soundcloud') && (
          <div className="border-t border-line-soft px-4 py-2.5">
            <button
              onClick={() => void load('soundcloud')}
              disabled={loading}
              className="text-[11px] text-muted transition hover:text-fg disabled:opacity-45"
            >
              {t.trySoundcloud}
              <span className="text-muted-2"> — {t.slowSearch}</span>
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
