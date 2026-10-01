import { memo, useCallback, useEffect, useMemo, useRef } from 'react'
import { useI18n } from '../lib/i18n'
import { reducedMotion } from '../lib/motion'
import { haptic } from '../lib/native'
import { usePlayer, type PlayItem } from '../store/player'
import { useSwipe } from '../lib/useSwipe'
import { useFloatingTabBarScroll } from '../lib/useFloatingTabBarScroll'
import { HomeIcon, LibraryIcon, NextIcon, PauseIcon, PlayIcon, SearchIcon, StatsIcon } from './icons'
import Artwork from './Artwork'
import type { Tab } from './TabBar'
import { integrateSpring, type SpringState } from './TabBar'

const LENS_PAD = 6
const COVER_VT = 'cover-art'

interface Props {
  active: Tab
  onHome: () => void
  onLibrary: () => void
  onStats: () => void
  onSearch: () => void
}

/**
 * The BitChord Liquid Glass Navigation Bar:
 *
 * An adaptive floating navigation component that houses the navigation tabs,
 * a standalone circular Search tab, and the Now Playing mini-player accessory.
 *
 * In expanded mode:
 * - Upper tier: Full-width Now Playing floating pill (40px art, title, artist, transport).
 * - Lower tier: Grouped tabs capsule (Home, Library, Stats) + Standalone circular Search button.
 *
 * In inline mode (active only when a track is playing and scrolling down >= 50px):
 * - Seamlessly collapses into a single 56px floating row across the screen:
 *   [Active Tab Pill] [Compact Now Playing: 32px art, title, play/pause] [Search Circle]
 * - Scrolling back up (or tapping the active tab) expands it back out.
 *
 * All surfaces share BitChord's real liquid glass material:
 * - 16px blur with 150% saturation boost
 * - 40% surface tint (#121212 dark / #FAFAFA light)
 * - 0.5px hairline rim & 45-degree specular highlight
 * - 24px soft drop shadow
 * - Inverted scrim sliding lens indicator (dark: black 50%, light: white 50%)
 */
function GlassNavBar({ active, onHome, onLibrary, onStats, onSearch }: Props) {
  const t = useI18n((s) => s.t)
  const lang = useI18n((s) => s.lang)

  // Current track from player queue
  const queue = usePlayer((s) => s.queue)
  const index = usePlayer((s) => s.index)
  const item = queue[index] as PlayItem | undefined
  const track = item?.track
  const hasTrack = Boolean(item && track)

  const playing = usePlayer((s) => s.playing)
  const toggle = usePlayer((s) => s.toggle)
  const next = usePlayer((s) => s.next)
  const prev = usePlayer((s) => s.prev)
  const position = usePlayer((s) => s.position)
  const duration = usePlayer((s) => s.duration)

  // Scroll tracking connection matching BitChord's 50px threshold.
  // ONLY collapses when an active track is present; otherwise remains fully expanded.
  const { isInline, expand } = useFloatingTabBarScroll(hasTrack, 50)

  // Automatically expand navigation whenever the active tab changes
  useEffect(() => {
    expand()
  }, [active, expand])

  // Sync nav-inline class to document.body for floating buttons and layout transition
  useEffect(() => {
    document.body.classList.toggle('nav-inline', isInline)
    return () => document.body.classList.remove('nav-inline')
  }, [isInline])

  // Spring physics for the grouped tab selection lens
  const ulRef = useRef<HTMLUListElement>(null)
  const lensRef = useRef<HTMLLIElement>(null)
  const btnRefs = useRef<Array<HTMLButtonElement | null>>([])
  const rafRef = useRef(0)
  const sizeRafRef = useRef(0)
  const springRef = useRef<SpringState>({ x: 0, v: 0, target: 0, origin: 0 })
  const didInit = useRef(false)

  // Grouped tabs (excluding standalone Search)
  const groupedTabs = useMemo(
    () => [
      { key: 'home' as const, label: t.home, Icon: HomeIcon, run: onHome },
      { key: 'library' as const, label: t.library, Icon: LibraryIcon, run: onLibrary },
      { key: 'stats' as const, label: t.stats, Icon: StatsIcon, run: onStats },
    ],
    [t, onHome, onLibrary, onStats],
  )

  // Remember last selected grouped tab so that on Search, the left pill doesn't duplicate Search
  const lastGroupedTabRef = useRef<'home' | 'library' | 'stats'>('home')
  useEffect(() => {
    if (active !== 'search') {
      lastGroupedTabRef.current = active
    }
  }, [active])

  // Find index of current grouped tab (-1 if on search)
  const activeGroupIndex = groupedTabs.findIndex((gt) => gt.key === active)
  const isSearchActive = active === 'search'

  // Spring placement function with volumetric conservation (stretch & squash)
  const place = useCallback(
    (animate: boolean) => {
      const ul = ulRef.current
      const lens = lensRef.current
      if (!ul || !lens || activeGroupIndex === -1) {
        if (lens) lens.style.opacity = '0'
        return
      }

      const btn = btnRefs.current[activeGroupIndex]
      if (!btn) return

      lens.style.opacity = '1'
      const u = ul.getBoundingClientRect()
      const b = btn.getBoundingClientRect()
      const w = b.width - LENS_PAD * 2
      const h = b.height - LENS_PAD * 2
      const x = b.left - u.left + LENS_PAD

      const sw = `${w}px`,
        sh = `${h}px`
      if (lens.style.width !== sw) lens.style.width = sw
      if (lens.style.height !== sh) lens.style.height = sh

      const s = springRef.current
      cancelAnimationFrame(rafRef.current)

      const pose = (px: number, lift = 0, stretch = 1) => {
        lens.style.transform = `translate3d(${px}px,${-lift}px,0) scale(${stretch},${1 / stretch})`
      }

      if (!animate || reducedMotion()) {
        s.x = s.target = s.origin = x
        s.v = 0
        pose(x)
        return
      }

      s.origin = s.x
      s.target = x
      let last = performance.now()
      const tick = (now: number) => {
        const dt = Math.min((now - last) / 1000, 1 / 30)
        last = now

        if (integrateSpring(s, dt, 320, 26)) {
          lens.style.transform = `translate3d(${s.x}px,0,0)`
          return
        }

        // Volumetric conservation stretch (STRETCH = 0.16)
        const vel = Math.abs(s.v) / 60
        const stretch = 1 + Math.min(vel * 0.015, 0.16)
        const span = Math.abs(s.target - s.origin) || 1
        const prog = Math.min(Math.max((s.x - s.origin) / span, 0), 1)
        const lift = Math.min(span * 0.06, 3) * Math.sin(prog * Math.PI)
        pose(s.x, lift, stretch)
        rafRef.current = requestAnimationFrame(tick)
      }
      rafRef.current = requestAnimationFrame(tick)
    },
    [activeGroupIndex],
  )

  useEffect(() => {
    place(didInit.current)
    didInit.current = true
  }, [place])

  useEffect(() => {
    if (!didInit.current) return
    place(false)
  }, [lang, place])

  useEffect(() => {
    const measure = () => {
      sizeRafRef.current = 0
      place(false)
    }
    const onResize = () => {
      if (!sizeRafRef.current) sizeRafRef.current = requestAnimationFrame(measure)
    }
    window.addEventListener('resize', onResize)
    document.fonts?.ready.then(onResize).catch(() => {})
    return () => {
      window.removeEventListener('resize', onResize)
      if (sizeRafRef.current) cancelAnimationFrame(sizeRafRef.current)
    }
  }, [place])

  useEffect(
    () => () => {
      cancelAnimationFrame(rafRef.current)
      if (sizeRafRef.current) cancelAnimationFrame(sizeRafRef.current)
    },
    [],
  )

  // Mini-player swipe for next/previous track
  const swipe = useSwipe<HTMLDivElement, HTMLButtonElement>({
    onLeft: next,
    onRight: prev,
    enabled: hasTrack,
  })

  // Expand full player
  const expandPlayer = useCallback(() => {
    window.dispatchEvent(new Event('musicbazi:expand-player'))
  }, [])

  const total = duration || (track?.durationMs ? track.durationMs / 1000 : 0)
  const pct = total > 0 ? Math.min(100, (position / total) * 100) : 0

  // The inline tab shown on the left: active grouped tab, or the last grouped tab if search is active
  const inlineGroupTab =
    groupedTabs.find((gt) => gt.key === active) ??
    groupedTabs.find((gt) => gt.key === lastGroupedTabRef.current) ??
    groupedTabs[0]

  return (
    <nav
      aria-label={t.brand}
      className="fixed inset-x-3 bottom-[max(0.75rem,var(--safe-b))] z-40 mx-auto w-auto max-w-md select-none transition-all duration-300 ease-[cubic-bezier(0.32,0.72,0,1)] sm:hidden"
    >
      {/* =========================================================================
          MODE 1: INLINE STATE (Collapsed on Scroll Down - Only when playing)
          Single 56px floating row: [Active Tab Pill] [Compact Now Playing] [Search Circle]
          ========================================================================= */}
      {isInline && hasTrack && track ? (
        <div className="flex h-14 items-center gap-2">
          {/* Active / Previous Group Tab Pill (tapping it switches or expands) */}
          <button
            onClick={() => {
              haptic.select()
              if (active === 'search') {
                inlineGroupTab.run()
              }
              expand()
            }}
            data-lg=""
            data-lg-radius="28"
            aria-label={inlineGroupTab.label}
            className={`tabbar-shell flex h-14 shrink-0 items-center gap-1.5 rounded-full px-4 transition-transform active:scale-95 ${
              active === inlineGroupTab.key ? 'ring-1 ring-white/20' : ''
            }`}
          >
            <inlineGroupTab.Icon className="size-5 text-fg" />
            <span className="text-[11px] font-semibold text-fg">{inlineGroupTab.label}</span>
          </button>

          {/* Compact Now Playing Accessory */}
          <div
            ref={swipe.ref}
            data-lg=""
            data-lg-radius="28"
            className="player-shell relative flex h-14 min-w-0 flex-1 items-center gap-2.5 overflow-hidden rounded-full px-3"
          >
            {/* Progress Beam */}
            <div
              dir="ltr"
              className="player-liquid-gutter absolute inset-x-4 bottom-0.5 h-[2.5px] overflow-hidden rounded-full"
            >
              <div
                className="player-liquid-beam h-full w-full origin-left rounded-full transition-transform duration-300 ease-linear"
                style={{ transform: `scaleX(${pct / 100})` }}
              />
            </div>

            <button
              onClick={expandPlayer}
              ref={swipe.content}
              className="flex min-w-0 flex-1 items-center gap-2 text-start transition-opacity active:opacity-75"
            >
              <Artwork
                src={track.artworkUrl}
                alt={track.album ?? track.title}
                seed={track.albumId ?? track.id}
                transitionName={COVER_VT}
                rounded="rounded-lg"
                className="size-8 shrink-0 shadow-sm ring-1 ring-white/15"
              />
              <span className="bidi truncate text-xs font-semibold text-fg">{track.title}</span>
            </button>

            <button
              onClick={(e) => {
                e.stopPropagation()
                haptic.select()
                toggle()
              }}
              aria-label={playing ? t.pause : t.play}
              className="grid size-8 shrink-0 place-items-center rounded-full text-fg transition active:scale-90"
            >
              {playing ? (
                <PauseIcon className="size-4" />
              ) : (
                <PlayIcon className="size-4" />
              )}
            </button>
          </div>

          {/* Standalone Circular Search Tab */}
          <button
            onClick={() => {
              haptic.select()
              onSearch()
              expand()
            }}
            data-lg=""
            data-lg-radius="28"
            aria-label={t.search}
            className={`glass-standalone ${
              isSearchActive ? 'scale-[1.04] ring-1 ring-white/40 bg-white/15' : ''
            }`}
          >
            <SearchIcon className={`size-5 transition-colors ${isSearchActive ? 'text-fg' : 'text-fg/65'}`} />
          </button>
        </div>
      ) : (
        /* =========================================================================
           MODE 2: EXPANDED STATE (Default / Scroll Up / Idle)
           - Upper Tier: Now Playing floating pill (when track is active)
           - Lower Tier: Grouped TabBar Capsule (Home, Library, Stats) + Search Circle
           ========================================================================= */
        <div className="flex flex-col gap-2">
          {/* Upper Tier: Now Playing Floating Pill */}
          {hasTrack && track && (
            <div
              ref={swipe.ref}
              data-lg=""
              data-lg-radius="28"
              className="player-shell relative flex h-14 w-full items-center gap-2 overflow-hidden rounded-full px-3.5 transition-transform active:scale-[1.01]"
            >
              {/* Progress Beam */}
              <div
                dir="ltr"
                className="player-liquid-gutter absolute inset-x-5 bottom-0.5 h-[3px] overflow-hidden rounded-full"
              >
                <div
                  className="player-liquid-beam h-full w-full origin-left rounded-full bg-accent transition-transform duration-300 ease-linear will-change-transform"
                  style={{ transform: `scaleX(${pct / 100})` }}
                />
              </div>

              {/* Artwork & Info (tap expands full player, swipe skips) */}
              <button
                onClick={expandPlayer}
                ref={swipe.content}
                aria-label={t.expandPlayer}
                className="flex min-w-0 flex-1 touch-pan-y items-center gap-2.5 text-start transition-opacity active:opacity-75"
              >
                <Artwork
                  src={track.artworkUrl}
                  alt={track.album ?? track.title}
                  seed={track.albumId ?? track.id}
                  transitionName={COVER_VT}
                  rounded="rounded-xl"
                  className="size-10 shrink-0 shadow-md shadow-black/40 ring-1 ring-white/15"
                />
                <span className="min-w-0 flex-1">
                  <span className="bidi block truncate text-[13px] font-semibold tracking-tight text-fg">
                    {track.title}
                  </span>
                  <span className="bidi block truncate text-[11px] font-normal text-fg/65">
                    {track.artist}
                  </span>
                </span>
              </button>

              {/* Play / Pause Button */}
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  haptic.select()
                  toggle()
                }}
                aria-label={playing ? t.pause : t.play}
                className="grid size-10 shrink-0 place-items-center rounded-full text-fg transition active:scale-90"
              >
                {playing ? (
                  <PauseIcon className="size-5" />
                ) : (
                  <PlayIcon className="size-5" />
                )}
              </button>

              {/* Next Track Button */}
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  haptic.select()
                  next()
                }}
                aria-label={t.nextTrack}
                className="grid size-9 shrink-0 place-items-center rounded-full text-fg/65 transition hover:text-fg active:scale-90"
              >
                <NextIcon className="size-5" />
              </button>
            </div>
          )}

          {/* Lower Tier: Grouped TabBar Capsule + Standalone Circular Search Tab */}
          <div className="flex h-14 w-full items-stretch gap-2">
            {/* Grouped TabBar Capsule (Home, Library, Stats) */}
            <div
              data-lg=""
              data-lg-radius="28"
              className="tabbar-shell relative flex h-full flex-1 items-stretch overflow-hidden rounded-full"
            >
              <ul
                ref={ulRef}
                className="relative flex h-full w-full items-stretch overflow-hidden rounded-full"
              >
                {/* BitChord Inverted Scrim Spring Lens */}
                <li
                  ref={lensRef}
                  aria-hidden="true"
                  className="tabbar-lens pointer-events-none absolute top-[6px] left-0 z-0 block rounded-full transition-opacity duration-150"
                />

                {groupedTabs.map(({ key, label, Icon, run }, i) => {
                  const on = active === key
                  return (
                    <li key={key} className="relative z-10 flex-1">
                      <button
                        ref={(el) => {
                          btnRefs.current[i] = el
                        }}
                        onPointerDown={() => {
                          if (!on) haptic.select()
                        }}
                        onClick={() => run()}
                        aria-current={on ? 'page' : undefined}
                        className="flex size-full flex-col items-center justify-center gap-1"
                      >
                        <span
                          className={`grid h-7 w-12 place-items-center rounded-full transition-transform duration-200 ${
                            on ? 'scale-[1.07] text-fg' : 'text-fg/65'
                          }`}
                        >
                          <Icon className="size-5" />
                        </span>
                        <span
                          className={`text-[10px] leading-none transition-colors ${
                            on ? 'font-semibold text-fg' : 'text-fg/65'
                          }`}
                        >
                          {label}
                        </span>
                      </button>
                    </li>
                  )
                })}
              </ul>
            </div>

            {/* Standalone Circular Search Button (matching BitChord standaloneTab) */}
            <button
              onClick={() => {
                haptic.select()
                onSearch()
              }}
              data-lg=""
              data-lg-radius="28"
              aria-label={t.search}
              className={`glass-standalone ${
                isSearchActive ? 'scale-[1.04] ring-1 ring-white/40 bg-white/15' : ''
              }`}
            >
              <SearchIcon className={`size-5 transition-colors ${isSearchActive ? 'text-fg' : 'text-fg/65'}`} />
            </button>
          </div>
        </div>
      )}
    </nav>
  )
}

export default memo(GlassNavBar)
