import { useCallback, useEffect, useState } from 'react'
import { dominantColor, tintVars } from '../lib/artColor'
import { digits, duration as fmtDuration } from '../lib/format'
import { haptic } from '../lib/native'
import { useI18n } from '../lib/i18n'
import { useSwipe } from '../lib/useSwipe'
import { COVER_VT } from '../lib/viewTransition'
import { usePlayer } from '../store/player'
import { useSettings } from '../store/settings'
import Artwork from './Artwork'
import AudioSettings from './AudioSettings'
import NowPlaying from './NowPlaying'
import Range from './Range'
import {
  ChevronIcon,
  HeartIcon,
  MuteIcon,
  NextIcon,
  PauseIcon,
  PlayIcon,
  PrevIcon,
  RepeatIcon,
  ShuffleIcon,
  VolumeIcon,
  WarnIcon,
} from './icons'

export default function PlayerBar() {
  const {
    queue,
    index,
    playing,
    position,
    duration,
    volume,
    muted,
    repeat,
    shuffle,
    failed,
    toggle,
    next,
    prev,
    seek,
    setVolume,
    toggleMute,
    cycleRepeat,
    toggleShuffle,
  } = usePlayer()
  const { t, lang } = useI18n()
  const liquidGlass = useSettings((s) => s.liquidGlass)
  const [expanded, setExpanded] = useState(false)

  /*
   * لرزشِ ریز روی کنترل‌های پخش.
   *
   * اینجا و نه داخلِ استورِ پخش‌کننده: استور با تمام‌شدنِ هر ترک خودش `next`
   * را صدا می‌زند، و لرزشِ خودبه‌خودِ بینِ آهنگ‌ها دقیقاً همان چیزی است که
   * کاربر بابتش هپتیکِ اپ را خاموش می‌کند.
   */
  const withTap = (run: () => void) => () => {
    haptic.tap()
    run()
  }

  const item = queue[index]

  /*
   * رنگِ نوار از رنگِ غالبِ کاورِ همان ترک — مثل اسپاتیفای.
   *
   * دو نسخه از رنگ لازم است و هر دو همین‌جا حساب می‌شوند، چون CSS خالص
   * (color-mix با درصدِ ثابت) نمی‌تواند روشنایی را هدف بگیرد:
   * - پس‌زمینه: رنگِ خام با مشکیِ زیاد — تیره می‌ماند، پس متن‌های سفید/خاکستری
   *   همیشه خوانا هستند.
   * - اکسنت‌ها (نوار پیشرفت، دستگیره، دکمه‌ی پخش): رنگِ روشن‌شده تا
   *   luminance ≈ 0.55 — روی زمینه‌ی تیره کنتراستِ متنِ مشکی تضمینی است،
   *   حتی برای کاورهای تیره.
   * `dominantColor` کش دارد، پس برگشتن به ترکِ قبلی رایگان است؛ null یعنی
   * کاور نبود یا بوم tainted شد → نوار همان تمِ --panel/--accent می‌ماند.
   */
  const [tint, setTint] = useState<[number, number, number] | null>(null)
  useEffect(() => {
    let cancelled = false
    // رنگِ قبلی روی صفحه می‌ماند تا رنگِ تازه برسد — یک فریم null یعنی
    // چشمکِ سفید/خاکستری وسطِ تعویضِ ترک، حتی وقتی نتیجه کش‌شده است
    void dominantColor(item?.track.artworkUrl ?? null).then((c) => {
      if (!cancelled) setTint(c)
    })
    return () => {
      cancelled = true
    }
  }, [item?.track.artworkUrl])

  const tintCss = tint ? tintVars(tint) : null
  const tintStyle = tintCss
    ? ({
        '--pb-rgb': tintCss.rgb,
        '--pb-strong': tintCss.strong,
      } as React.CSSProperties)
    : undefined

  // فاصله‌ی زیر صفحه فقط وقتی لازم است که نوار واقعاً هست؛ گذاشتنِ همیشگی‌اش
  // در ویوهای بدون پخش یک نوار خالی فضا می‌گرفت
  useEffect(() => {
    document.body.classList.toggle('has-player', Boolean(item))
    return () => document.body.classList.remove('has-player')
  }, [item])

  /*
   * باز کردنِ نمای کامل (شیت تمام‌صفحه) با انیمیشن اسلاید سخت‌افزاریِ رو به بالا.
   */
  const expand = useCallback(() => setExpanded(true), [])

  // قلبِ نوارِ پخش = ناوبری به «لایک‌ها»، نه لایکِ همان ترک. رویداد است نه
  // ایمپورتِ ناوبری — همان الگویِ «برو به کتابخانه» که شنونده‌اش در App است
  const openLiked = useCallback(() => {
    window.dispatchEvent(new Event('unstream:open-liked'))
  }, [])

  // میان‌برِ «F» — خودِ شنونده در `Shortcuts` است تا همه‌ی میان‌برها یک‌جا بمانند
  useEffect(() => {
    window.addEventListener('unstream:expand-player', expand)
    return () => window.removeEventListener('unstream:expand-player', expand)
  }, [expand])

  /*
   * سوایپِ افقی روی مینی‌پلیر = ترکِ بعدی/قبلی.
   *
   * فقط روی گوشی: آن‌جا نه دکمه‌ی «قبلی» جا می‌شود و نه «بعدی» هدفِ راحتی
   * است، و همان ژستی که کاربر رفلکسی امتحان می‌کند تا امروز هیچ‌کاری نمی‌کرد.
   */
  const swipe = useSwipe<HTMLDivElement, HTMLButtonElement>({
    onLeft: next,
    onRight: prev,
    enabled: Boolean(item),
  })

  if (!item) return null

  const { track } = item
  const total = duration || track.durationMs / 1000
  const pct = total > 0 ? Math.min(100, (position / total) * 100) : 0
  const repeatLabel =
    repeat === 'one' ? t.repeatOne : repeat === 'all' ? t.repeatAll : t.repeatOff

  const subtitle = failed ? (
    <span className="inline-flex items-center gap-1 text-danger">
      <WarnIcon className="size-3" />
      {t.playFailed}
    </span>
  ) : (
    <bdi>{track.artist}</bdi>
  )

  return (
    <>
      {/* player-dock: روی گوشی کپسولی شناور دقیقاً بالای کپسولِ تب‌بار و هم‌اندازه‌ی
          آن، روی دسکتاپ نوارِ تمام‌عرضِ ته صفحه — خودِ داک فقط موقعیت و تینت را
          نگه می‌دارد، سطحِ شیشه‌ای را بچه‌ها می‌سازند */}
      <div
        className={`player-dock pointer-events-none fixed inset-x-0 z-30 max-sm:px-3 ${
          liquidGlass ? 'max-sm:hidden' : ''
        }`}
        data-tint={tint ? '' : undefined}
        style={tintStyle}
      >
        {/* ---------- موبایل: مینی‌پلیر (تنها زمانی که Liquid Glass خاموش باشد) ---------- */}
        {!liquidGlass && (
          <div
            className="glass player-shell pointer-events-auto relative mx-auto mb-3 h-14 max-w-md touch-pan-y overflow-hidden rounded-full sm:hidden"
            ref={swipe.ref}
          >
            {/* dir=ltr عمدی و هم‌راستا با `.seek`: زمان همیشه از چپ به راست جلو
                می‌رود، حتی در رابط فارسی — وگرنه این خط از راست پر می‌شد و با
                نوار جابه‌جاییِ نمای کامل خلافِ هم می‌شدند. absolute در کفِ کپسول:
                همان «نشانه‌ی پیشرفت» قبلی، حالا به‌جای لبه‌ی چسبان، لبه‌ی عدسی */}
            <div
              dir="ltr"
              role="progressbar"
              aria-label={t.seekBar}
              aria-valuemin={0}
              aria-valuemax={Math.round(total)}
              aria-valuenow={Math.round(position)}
              className="player-liquid-gutter absolute inset-x-5 bottom-0.5 h-[3px] overflow-hidden rounded-full"
            >
              <div
                className="player-liquid-beam h-full w-full origin-left rounded-full transition-transform duration-300 ease-linear will-change-transform"
                style={{ transform: `scaleX(${pct / 100})` }}
              />
            </div>

            <div className="flex h-full items-center gap-1.5 px-3">
              {/* عنوان و کاور زیر انگشت حرکت می‌کنند؛ دکمه‌های کنارشان نه —
                  وگرنه هدفِ لمسیِ «پخش» وسطِ سوایپ جابه‌جا می‌شد */}
              <button
                onClick={expand}
                aria-label={t.expandPlayer}
                ref={swipe.content}
                className="flex min-w-0 flex-1 touch-pan-y items-center gap-2.5 rounded-xl p-0.5 text-start transition-opacity active:opacity-75"
              >
                <Artwork
                  src={track.artworkUrl}
                  alt={track.album ?? track.title}
                  seed={track.albumId ?? track.id}
                  transitionName={expanded ? undefined : COVER_VT}
                  rounded="rounded-xl"
                  className="size-10 shrink-0 shadow-md shadow-black/40 ring-1 ring-white/15 transition-all duration-300 dark:ring-white/15 [data-theme='light']:ring-black/10"
                />
                <span className="min-w-0 flex-1">
                  <span className="bidi block truncate text-[13px] font-semibold tracking-tight text-fg">
                    {track.title}
                  </span>
                  <span className="bidi block truncate text-[11px] font-normal text-muted">
                    {subtitle}
                  </span>
                </span>
              </button>

              <button
                onClick={withTap(toggle)}
                aria-label={playing ? t.pause : t.play}
                className="player-hero-btn grid size-10 shrink-0 place-items-center rounded-full"
              >
                {playing ? (
                  <PauseIcon className="size-5" />
                ) : (
                  <PlayIcon className="size-5" />
                )}
              </button>

              <button
                onClick={withTap(next)}
                aria-label={t.nextTrack}
                className="grid size-9 shrink-0 place-items-center rounded-full text-muted transition-all duration-150 hover:bg-white/10 hover:text-fg active:scale-92 active:bg-white/15 dark:hover:bg-white/10 [data-theme='light']:hover:bg-black/5"
              >
                <NextIcon className="size-5" />
              </button>

              <button
                onClick={withTap(openLiked)}
                aria-label={t.liked}
                className="player-like-btn grid size-9 shrink-0 place-items-center rounded-full text-like transition-all hover:bg-like/10"
              >
                <HeartIcon filled className="size-[22px]" />
              </button>
            </div>
          </div>
        )}

        {/* ---------- دسکتاپ و تبلت ---------- */}
        {/* تب‌باری روی دسکتاپ نیست، پس اینجا همان نوارِ تمام‌عرضِ چسبان به ته
            صفحه می‌ماند — هم‌خانواده‌ی هدر: glass-bar با لبه‌ی بالایی. سطحِ
            شیشه‌ای تمام‌عرض است (خطِ لبه تا گوشه‌ها برود) و محتوا داخلِ
            max-w-6xl وسط‌چین. */}
        <div className="glass-bar player-bar-desktop pointer-events-auto hidden w-full border-t border-line-soft sm:block">
          <div className="px-safe mx-auto flex w-full max-w-6xl items-center gap-4 py-2.5">
            <button
              onClick={expand}
              aria-label={t.expandPlayer}
              title={t.expandPlayer}
              className="group flex min-w-0 shrink-0 items-center gap-3 rounded-xl p-1 text-start transition-all duration-200 hover:bg-white/5 dark:hover:bg-white/5 [data-theme='light']:hover:bg-black/5"
            >
              <Artwork
                src={track.artworkUrl}
                alt={track.album ?? track.title}
                seed={track.albumId ?? track.id}
                transitionName={expanded ? undefined : COVER_VT}
                rounded="rounded-xl"
                className="size-11 shrink-0 shadow-md shadow-black/40 ring-1 ring-white/15 transition-all duration-300 dark:ring-white/15 [data-theme='light']:ring-black/10"
              />

              <div className="w-36 min-w-0 md:w-44 lg:w-52">
                <p
                  className="bidi truncate text-xs font-semibold tracking-tight text-fg transition-colors group-hover:text-accent"
                  title={track.title}
                >
                  {track.title}
                </p>
                <p className="bidi truncate text-[11px] text-muted transition-colors group-hover:text-fg">
                  {subtitle}
                </p>
              </div>
            </button>

            <div className="flex min-w-0 flex-1 flex-col gap-1">
              <div className="flex items-center justify-center gap-1.5">
                <button
                  onClick={withTap(toggleShuffle)}
                  aria-label={t.shuffle}
                  aria-pressed={shuffle}
                  title={t.shuffle}
                  className={`relative grid size-8 place-items-center rounded-lg transition-all duration-150 hover:bg-white/10 hover:text-fg active:scale-95 [data-theme='light']:hover:bg-black/5 ${
                    shuffle ? 'text-accent' : 'text-muted-2'
                  }`}
                >
                  <ShuffleIcon className="size-3.5" />
                  {shuffle && (
                    <span className="absolute bottom-1 size-1 rounded-full bg-accent" />
                  )}
                </button>

                <button
                  onClick={withTap(prev)}
                  aria-label={t.prevTrack}
                  title={t.prevTrack}
                  className="grid size-8 place-items-center rounded-lg text-muted transition-all duration-150 hover:bg-white/10 hover:text-fg active:scale-95 [data-theme='light']:hover:bg-black/5"
                >
                  <PrevIcon className="size-4" />
                </button>

                <button
                  onClick={withTap(toggle)}
                  aria-label={playing ? t.pause : t.play}
                  title={playing ? t.pause : t.play}
                  className="player-hero-btn grid size-10 place-items-center rounded-full"
                >
                  {playing ? (
                    <PauseIcon className="size-4.5" />
                  ) : (
                    <PlayIcon className="size-4.5" />
                  )}
                </button>

                <button
                  onClick={withTap(next)}
                  aria-label={t.nextTrack}
                  title={t.nextTrack}
                  className="grid size-8 place-items-center rounded-lg text-muted transition-all duration-150 hover:bg-white/10 hover:text-fg active:scale-95 [data-theme='light']:hover:bg-black/5"
                >
                  <NextIcon className="size-4" />
                </button>

                <button
                  onClick={withTap(cycleRepeat)}
                  aria-label={repeatLabel}
                  title={repeatLabel}
                  className={`relative grid size-8 place-items-center rounded-lg transition-all duration-150 hover:bg-white/10 hover:text-fg active:scale-95 [data-theme='light']:hover:bg-black/5 ${
                    repeat === 'off' ? 'text-muted-2' : 'text-accent'
                  }`}
                >
                  <RepeatIcon className="size-3.5" one={repeat === 'one'} />
                  {repeat !== 'off' && (
                    <span className="absolute bottom-1 size-1 rounded-full bg-accent" />
                  )}
                </button>
              </div>

              <div className="flex items-center gap-2.5" dir="ltr">
                <span className="w-10 shrink-0 text-end font-mono text-[11px] font-medium tabular-nums text-muted-2">
                  {fmtDuration(position * 1000, lang)}
                </span>
                <Range
                  value={Math.min(position, total)}
                  max={total}
                  onChange={seek}
                  label={t.seekBar}
                  className="player-range-seek"
                />
                <span className="w-10 shrink-0 font-mono text-[11px] font-medium tabular-nums text-muted-2">
                  {fmtDuration(total * 1000, lang)}
                </span>
              </div>
            </div>

            {/* نوار صدا از md به بالا — روی تبلتِ باریک جای عنوان را می‌گرفت */}
            <div className="hidden shrink-0 items-center gap-1.5 md:flex">
              <AudioSettings />
              <div className="flex items-center gap-1 rounded-xl p-0.5 transition-colors hover:bg-white/5 dark:hover:bg-white/5 [data-theme='light']:hover:bg-black/5">
                <button
                  onClick={withTap(toggleMute)}
                  aria-label={muted ? t.unmute : t.mute}
                  title={muted ? t.unmute : t.mute}
                  className="grid size-8 place-items-center rounded-lg text-muted-2 transition-all duration-150 hover:bg-white/10 hover:text-fg active:scale-95 [data-theme='light']:hover:bg-black/5"
                >
                  {muted || volume === 0 ? (
                    <MuteIcon className="size-4" />
                  ) : (
                    <VolumeIcon className="size-4" />
                  )}
                </button>
                <Range
                  value={muted ? 0 : volume}
                  max={1}
                  onChange={setVolume}
                  label={t.volume}
                  className="w-18 md:w-20 transition-all"
                />
              </div>
            </div>

            {queue.length > 1 && (
              <span className="hidden shrink-0 items-center rounded-full border border-white/10 bg-white/5 px-2.5 py-0.5 font-mono text-[10px] tabular-nums text-muted shadow-xs transition-colors hover:border-white/20 lg:inline-flex dark:border-white/10 dark:bg-white/5 [data-theme='light']:border-black/10 [data-theme='light']:bg-black/5 [data-theme='light']:text-muted">
                {digits(index + 1, lang)}/{digits(queue.length, lang)}
              </span>
            )}

            <button
              onClick={expand}
              aria-label={t.expandPlayer}
              title={t.expandPlayer}
              className="grid size-8 shrink-0 place-items-center rounded-lg text-muted-2 transition-all duration-150 hover:bg-white/10 hover:text-fg active:scale-95 [data-theme='light']:hover:bg-black/5"
            >
              <ChevronIcon className="size-3.5 rotate-90" flip={false} />
            </button>

            <button
              onClick={withTap(openLiked)}
              aria-label={t.liked}
              title={t.liked}
              className="player-like-btn grid size-8 shrink-0 place-items-center rounded-lg text-like transition-all hover:bg-like/15"
            >
              <HeartIcon filled className="size-4" />
            </button>
          </div>
        </div>
      </div>

      {/*
        اعلامِ ترکِ جاری برای صفحه‌خوان.
        بدون این، عوض‌شدنِ آهنگ — چه خودکار در ته صف، چه با «بعدی» — هیچ
        صدایی نداشت: همه‌ی اطلاعاتِ نوار پخش دیداری بود. `polite` است نه
        `assertive` چون حرفِ کاربر را نباید قطع کند.
      */}
      <p className="sr-only" aria-live="polite">
        {`${track.title} — ${track.artist}`}
      </p>

      {expanded && <NowPlaying onClose={() => setExpanded(false)} initialTint={tint} />}
    </>
  )
}
