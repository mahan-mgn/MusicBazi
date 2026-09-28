import { useEffect, useRef, useState } from 'react'
import { useBackDismiss } from '../lib/back'
import { api, API_MODE } from '../lib/api'
import { useI18n } from '../lib/i18n'
import { fetchVibeStatus } from '../lib/setup'
import type { Track, VibeTurn } from '../lib/types'
import { VIBE_KEYS, vibeLabel } from '../lib/vibes'
import { itemFromJob, prefetchTracks, type QueueDownloadResult } from '../lib/vibePlayback'
import { useMoodChat } from '../store/moodChat'
import { usePlayer, type PlayItem } from '../store/player'
import { useSettings } from '../store/settings'
import { useToasts } from '../store/toasts'
import Artwork from './Artwork'
import {
  ChatIcon,
  CheckDrawIcon,
  CloseIcon,
  PlayIcon,
  PlusIcon,
  QueueIcon,
  RetryIcon,
  SparkleIcon,
  Spinner,
  TrashIcon,
  WarnIcon,
} from './icons'
import PlayButton from './PlayButton'
import { GeminiLogo } from './logos'

/** هر پیشنهاد حداکثر ۸ ترک — با MAX_TRACKSِ سرور (server/app/vibe.py) یکی است */
const MAX_TRACKS = 8

/**
 * سقفِ تاریخچه‌ای که به سرور می‌رود. سرور خودش کوتاه‌ترش می‌کند؛ این فقط
 * نگهبانِ اندازه‌ی بدنه است — گفتگوی طولانی نباید درخواست را کیلوبایتی کند.
 */
const MAX_HISTORY_TURNS = 8

interface Query {
  vibe?: string
  message?: string
}

interface TrackState {
  track: Track
  status: 'pending' | 'ready' | 'failed'
  /** دلیلِ شکست (وقتی سرور پیامی داده باشد) — برای متنِ زیرِ ردیف و تولتیپِ آیکون */
  error?: string
  /** فقط وقتی status ready است — بدونش دکمه‌ی پخش/افزودن به صف چیزی برای دادن به پلیر ندارد */
  item?: PlayItem
  /** شناسه‌ی جابِ فایلِ آماده — لازمِ «ذخیره در پلی‌لیست» */
  jobId?: string
  /** این ترک از قبل در کتابخانه بود — ردیفش بدونِ اسپینر و بدونِ دانلود باز می‌شود */
  owned?: boolean
  /**
   * ردیف از تاریخچه‌ی localStorage بازیابی شده — آدرسِ فایل ذخیره نمی‌شود
   * (بینِ دو اجرا می‌پَند)، پس نه پخشی دارد نه دانلودی. اسپینرِ ابدی روی این
   * ردیف‌ها دروغِ «در حالِ دانلود» است؛ بی‌حرکت نشان داده می‌شوند.
   */
  stale?: boolean
}

type Message =
  | { id: number; role: 'user'; text: string }
  | { id: number; role: 'bot'; status: 'thinking' }
  | { id: number; role: 'bot'; status: 'error'; query: Query; label: string }
  | {
      id: number
      role: 'bot'
      status: 'done'
      reply: string
      /** «چرا این‌ها؟» — فقط وقتی Gemini جواب داده */
      reason?: string
      tracks: TrackState[]
      query: Query
      label: string
    }

let nextId = 1

const HISTORY_KEY = 'moodchat:history'
// بیشتر از این فقط localStorage را پر می‌کند بدون فایده‌ی واقعی برای گفتگو
const MAX_HISTORY = 60

/** پیامِ «در حالِ فکر کردن» موقتی است — اگر وسطِ یک درخواست رفرش شود، معنایی برای ماندن ندارد */
function readHistory(): Message[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY)
    const parsed: unknown = raw ? JSON.parse(raw) : []
    if (!Array.isArray(parsed)) return []
    // فیلترِ سطحی کافی نیست: یک تاریخچه‌ی خراب (user بی‌text، done بی‌tracks)
    // رندر را می‌ترکاند و بعد از آن هیچ‌وقت پاک نمی‌شود — هر بار از نو می‌آید.
    // «در حالِ فکر کردن» هم می‌افتد: حبابی که هیچ‌وقت جواب نمی‌گیرد دروغِ
    // دومِ همان جنس است (writeHistory هم هرگز چنین ردیفی نمی‌نویسد)
    return (parsed as Message[]).filter((m) => {
      if (typeof m?.id !== 'number') return false
      if (m.role === 'user') return typeof m.text === 'string'
      if (m.role !== 'bot') return false
      return m.status === 'error' || (m.status === 'done' && Array.isArray(m.tracks))
    })
  } catch {
    return []
  }
}

function writeHistory(messages: Message[]) {
  try {
    const persistable = messages.filter((m) => !(m.role === 'bot' && m.status === 'thinking'))
    // item/streamUrl ذخیره نمی‌شوند: آدرس‌های فایل بعد از رفرش ممکن است
    // معتبر نباشند، و ترک‌های ready در بارِ بعد دوباره از سرور می‌آیند
    const slim = persistable.slice(-MAX_HISTORY).map((m) =>
      m.role === 'bot' && m.status === 'done'
        ? {
            ...m,
            tracks: m.tracks.map((ts) => ({
              track: ts.track,
              status: 'pending' as const,
              stale: true,
            })),
          }
        : m,
    )
    localStorage.setItem(HISTORY_KEY, JSON.stringify(slim))
  } catch {
    // سهمیه‌ی localStorage پر است — تاریخچه صرفاً یک راحتی است، نه چیز حیاتی
  }
}

/**
 * تاریخچه‌ی گفتگو به شکلِ نوبت‌های Gemini.
 *
 * پیام‌های خطا و «در حالِ فکر کردن» رد می‌شوند: به مدل گفتنِ «گرفتن پیشنهاد
 * ناموفق بود» هیچ ارجاعِ مفیدی نمی‌دهد، فقط توکن می‌سوزاند.
 */
function toTurns(messages: Message[]): VibeTurn[] {
  const turns: VibeTurn[] = []
  for (const m of messages) {
    if (m.role === 'user') turns.push({ role: 'user', text: m.text })
    else if (m.role === 'bot' && m.status === 'done') turns.push({ role: 'model', text: m.reply })
  }
  return turns.slice(-MAX_HISTORY_TURNS)
}

export default function MoodChat() {
  const open = useMoodChat((s) => s.open)
  // دکمه‌ی برگشتِ اندروید پنل را می‌بندد، نه اینکه از صفحه بیرون برود
  useBackDismiss(open, () => useMoodChat.getState().toggle())
  const setOpen = useMoodChat((s) => s.setOpen)
  const toggleOpen = useMoodChat((s) => s.toggle)
  const pendingVibe = useMoodChat((s) => s.pendingVibe)
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<Message[]>(() => {
    const restored = readHistory()
    const maxId = restored.reduce((max, m) => Math.max(max, m.id), 0)
    if (maxId >= nextId) nextId = maxId + 1
    return restored
  })
  const [busy, setBusy] = useState(false)
  // وضعیتِ مسیرِ تشخیص — یک‌بار موقع باز شدن پنل پرسیده می‌شود، نه با هر پیام
  const [vibeStatus, setVibeStatus] = useState<{ llm: boolean; model: string | null } | null>(null)
  const listRef = useRef<HTMLDivElement>(null)
  // ترک‌هایی که همین گفتگو قبلاً دیده — با هر درخواست فرستاده می‌شود تا
  // پیشنهادِ بعدی همان‌ها را دوباره نیاورد؛ ref است چون خودش رندر نمی‌خواهد.
  // از تاریخچه‌ی بازیابی‌شده هم پر می‌شود، وگرنه بعد از رفرش دوباره تکراری می‌آمد
  const seenIds = useRef<Set<string>>(
    new Set(messages.flatMap((m) => (m.role === 'bot' && m.status === 'done' ? m.tracks.map((ts) => ts.track.id) : []))),
  )
  const { t } = useI18n()

  useEffect(() => {
    writeHistory(messages)
  }, [messages])

  useEffect(() => {
    if (!open || API_MODE !== 'http' || vibeStatus) return
    let alive = true
    void fetchVibeStatus().then((s) => {
      if (alive) setVibeStatus(s)
    })
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])
  const pushToast = useToasts((s) => s.push)
  const quality = useSettings((s) => s.quality)

  const scrollToEnd = () => {
    requestAnimationFrame(() => {
      const el = listRef.current
      if (el) el.scrollTop = el.scrollHeight
    })
  }

  const setTrackStatus = (botId: number, trackId: string, patchData: Partial<TrackState>) => {
    setMessages((prev) =>
      prev.map((m) =>
        m.id === botId && m.role === 'bot' && m.status === 'done'
          ? { ...m, tracks: m.tracks.map((ts) => (ts.track.id === trackId ? { ...ts, ...patchData } : ts)) }
          : m,
      ),
    )
  }

  async function send(query: Query, label: string) {
    if (busy) return
    setBusy(true)

    const userId = nextId++
    const botId = nextId++
    // تاریخچه قبل از افزودنِ پیامِ جاری گرفته می‌شود: خودِ این پیام در `text`
    // جدا می‌رود و دوباره‌اش در history یعنی دو بار گفتنِ یک چیز
    const history = toTurns(messages)
    setMessages((prev) => [
      ...prev,
      { id: userId, role: 'user', text: label },
      { id: botId, role: 'bot', status: 'thinking' },
    ])
    setInput('')
    scrollToEnd()

    try {
      // آخرین ۲۰۰ تا کافی است — گفتگو هر چقدر طول بکشد، بدنه‌ی درخواست کوچک می‌ماند
      const excludeIds = Array.from(seenIds.current).slice(-200)
      const result = await api.vibeSuggest({ ...query, excludeIds, history })
      const tracks = result.tracks.slice(0, MAX_TRACKS)
      tracks.forEach((track) => seenIds.current.add(track.id))
      const ready = result.ready ?? {}
      setMessages((prev) =>
        prev.map((m) =>
          m.id === botId
            ? {
                id: botId,
                role: 'bot',
                status: 'done',
                reply: result.reply,
                reason: result.reason ?? undefined,
                tracks: tracks.map((track) => {
                  // از قبل در کتابخانه است: همان لحظه ready، بدونِ دانلود
                  const owned = ready[track.id]
                  return owned
                    ? {
                        track,
                        status: 'ready' as const,
                        item: itemFromJob(track, owned),
                        jobId: owned.jobId,
                        owned: true,
                      }
                    : { track, status: 'pending' as const }
                }),
                query,
                label,
              }
            : m,
        ),
      )
      scrollToEnd()

      if (!tracks.length) return

      if (API_MODE !== 'http') {
        // مود دمو دانلودِ واقعی ندارد؛ ردیف‌ها را بی‌اسپینر می‌گذاریم تا
        // «در حالِ دانلود»ی که هیچ‌وقت تمام نمی‌شود دروغ نباشد
        setMessages((prev) =>
          prev.map((m) =>
            m.id === botId && m.role === 'bot' && m.status === 'done'
              ? { ...m, tracks: m.tracks.map((ts) => ({ ...ts, stale: true })) }
              : m,
          ),
        )
        pushToast(t.moodChatPlaybackUnavailable, 'info')
        return
      }

      // دانلود در پس‌زمینه و کم‌تعدادِ هم‌زمان شروع می‌شود تا دکمه‌ی پخش زودتر
      // فعال شود — ولی خودِ صفِ پخش را کاربر باید دستی دست بزند؛ باز کردنِ چت
      // و گفتنِ یک حال نباید بی‌اجازه پخشِ فعلی را قطع کند.
      //
      // سقفِ هم‌زمانی (۳) عمدی است: هشت jobِ موازی یعنی هشت ytdlp و ffmpeg روی
      // همان ماشینِ خانگی، و اولین ترک دیرتر آماده می‌شود.
      // همه را می‌دهیم؛ resolveOwned همان‌جا تشخیص می‌دهد کدام از قبل روی
      // دیسک است و آن یکی را اصلاً به صفِ دانلود نمی‌فرستد
      //
      // عمداً await نمی‌شود: هشت دانلودِ ytdlp چند دقیقه طول می‌کشد و نگه‌داشتنِ
      // `busy` یعنی کاربر تا آخر نمی‌تواند پیامِ بعدی را بفرستد — درحالی‌که
      // پیشنهاد و تاریخچه از قبل آماده‌اند. ردیف‌ها با رسیدنِ هر دانلود
      // جداگانه به‌روز می‌شوند.
      void prefetchTracks(tracks, quality, (track) => ready[track.id] ?? null, (track, res: QueueDownloadResult) => {
        if (!res.item) setTrackStatus(botId, track.id, { status: 'failed', error: res.error })
        else setTrackStatus(botId, track.id, { status: 'ready', item: res.item, jobId: res.jobId })
      })
    } catch {
      setMessages((prev) =>
        prev.map((m) => (m.id === botId ? { id: botId, role: 'bot', status: 'error', query, label } : m)),
      )
      pushToast(t.moodChatFetchFailed, 'error')
    } finally {
      setBusy(false)
    }
  }

  const sendVibe = (key: string) => void send({ vibe: key }, vibeLabel(t, key))

  // درخواستِ آمده از کاشی‌های خانه. اگر همین حالا درخواستی در جریان باشد
  // نگه داشته می‌شود تا تمام شود — send خودش درخواستِ هم‌زمان را دور می‌ریزد و
  // آن‌وقت کلیکِ کاربر بی‌صدا گم می‌شد.
  useEffect(() => {
    if (!pendingVibe || busy) return
    useMoodChat.getState().consume()
    sendVibe(pendingVibe)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingVibe, busy])

  const sendMessage = () => {
    const text = input.trim()
    if (!text) return
    void send({ message: text }, text)
  }

  const repeat = (query: Query, label: string) => void send(query, label)

  const clearChat = () => {
    setMessages([])
    seenIds.current.clear()
  }

  return (
    <>
      <button
        onClick={toggleOpen}
        aria-label={t.moodChatOpen}
        title={t.moodChatOpen}
        className="bottom-safe fixed start-4 z-40 grid size-14 place-items-center rounded-full bg-accent text-accent-fg shadow-lg shadow-black/40 transition hover:brightness-110 sm:size-12"
      >
        {open ? <CloseIcon className="size-5" /> : <ChatIcon className="size-5" />}
      </button>

      {open && (
        <div
          // ارتفاع هم سقفِ نسبی می‌گیرد: ۲۸rem روی گوشیِ کوتاه (و هر گوشیِ
          // افقی) از بالای صفحه می‌زد بیرون. سقفِ دوم خودِ همان فاصله‌ای است که
          // `bottom-safe-2` + هدر پایین/بالا می‌گیرند، پس پنل هیچ‌وقت پشتِ
          // نوارِ پخش یا زیرِ هدر نمی‌رود
          className="glass bottom-safe-2 fixed start-3 z-40 flex h-[min(28rem,calc(100dvh-var(--player-h)-max(var(--tab-h),var(--safe-b))-9rem))] w-[min(22rem,calc(100vw-1.5rem))] flex-col overflow-hidden rounded-2xl shadow-2xl shadow-black/40 sm:start-4"
        >
          <div className="flex items-center justify-between gap-2 border-b border-line-soft px-4 py-3">
            <div className="min-w-0">
              <h2 className="text-sm font-semibold">{t.moodChatTitle}</h2>
              <p className="truncate text-[11px] text-muted-2">{t.moodChatSubtitle}</p>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              {messages.length > 0 && (
                <button
                  onClick={clearChat}
                  aria-label={t.moodChatClear}
                  title={t.moodChatClear}
                  className="grid size-7 place-items-center rounded-md text-muted-2 transition hover:bg-panel-2 hover:text-fg"
                >
                  <TrashIcon className="size-4" />
                </button>
              )}
              <button
                onClick={() => setOpen(false)}
                aria-label={t.close}
                className="grid size-7 place-items-center rounded-md text-muted-2 transition hover:bg-panel-2 hover:text-fg"
              >
                <CloseIcon className="size-4" />
              </button>
            </div>
          </div>

          {/*
            نشانگرِ «چطور فکر می‌کنم»: بدونِ کلیدِ Gemini چت روی نگاشتِ
            کلیدواژه‌ای است و کیفیتِ تشخیص فرق می‌کند. پنهان‌کردنش یعنی کاربر
            هیچ‌وقت نمی‌فهمد چرا «یه چیز آرومِ بی‌کلام» را درست نفهمیدم.
          */}
          {vibeStatus && (
            <div className="border-b border-line-soft px-4 py-1 text-[10px] text-muted-2">
              {vibeStatus.llm ? (
                <span className="inline-flex items-center gap-1.5">
                  <GeminiLogo className="size-3" />
                  {t.moodChatPoweredBy(vibeStatus.model ?? 'Gemini')}
                </span>
              ) : (
                <span>{t.moodChatKeywordMode}</span>
              )}
            </div>
          )}

          <div ref={listRef} className="scroll-pane flex-1 space-y-3 overflow-y-auto px-3 py-3">
            {messages.length === 0 && <IntroBubble text={t.moodChatIntro} />}
            {messages.map((m) => (
              <MessageBubble key={m.id} message={m} onRepeat={repeat} />
            ))}
          </div>

          <div className="no-scrollbar flex gap-1.5 overflow-x-auto border-t border-line-soft px-3 py-2">
            {VIBE_KEYS.map((key) => (
              <button
                key={key}
                disabled={busy}
                onClick={() => sendVibe(key)}
                className="shrink-0 rounded-full border border-line bg-panel-2 px-2.5 py-1 text-[11px] text-muted transition hover:border-accent/40 hover:text-fg active:scale-95 disabled:opacity-50"
              >
                {vibeLabel(t, key)}
              </button>
            ))}
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault()
              sendMessage()
            }}
            className="flex items-center gap-2 border-t border-line-soft p-2.5"
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={t.moodChatPlaceholder}
              disabled={busy}
              // سرور هم همین‌جا کوتاه می‌کند (main.py) — تایپِ بیشتر از این
              // بی‌فایده است چون نصفِ پیام برای مدل می‌رود
              maxLength={500}
              className="w-full rounded-full border border-line bg-panel-2 px-3 py-1.5 text-xs outline-none placeholder:text-muted-2 disabled:opacity-60"
            />
            <button
              type="submit"
              disabled={busy || !input.trim()}
              aria-label={t.moodChatSend}
              title={t.moodChatSend}
              className="grid size-8 shrink-0 place-items-center rounded-full bg-accent text-accent-fg transition hover:brightness-110 disabled:opacity-50"
            >
              <ChatIcon className="size-4" />
            </button>
          </form>
        </div>
      )}
    </>
  )
}

/** آواتارِ کوچکِ بات — کنارِ هر حبابِ بات، برای هویتِ بصری در برابرِ حباب‌های خنثیِ کاربر */
function BotAvatar() {
  return (
    <div className="grid size-6 shrink-0 place-items-center self-end rounded-full bg-accent/15 text-accent p-1">
      <GeminiLogo className="size-full" />
    </div>
  )
}

/**
 * سه نقطه‌ی «در حالِ فکر کردن» — قراردادِ بصریِ چت‌ها. اسپینرِ قبلی «دارد
 * می‌چرخد» می‌گفت، نقطه‌ها «داره فکر می‌کنه» می‌گویند؛ برای یک گفتگو دومی
 * درست‌تر است.
 */
function ThinkingDots() {
  return (
    <span className="flex items-center gap-1" aria-hidden>
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="think-dot size-1.5 rounded-full bg-muted"
          style={{ animationDelay: `${i * 0.15}s` }}
        />
      ))}
    </span>
  )
}

function IntroBubble({ text }: { text: string }) {
  return (
    <div className="rise flex justify-start gap-1.5">
      <BotAvatar />
      <p className="max-w-[85%] rounded-2xl rounded-ss-sm bg-panel-2 px-3 py-2 text-xs text-muted">{text}</p>
    </div>
  )
}

function MessageBubble({ message, onRepeat }: { message: Message; onRepeat: (query: Query, label: string) => void }) {
  const { t } = useI18n()

  if (message.role === 'user') {
    return (
      <div className="rise flex justify-end">
        <p className="max-w-[85%] rounded-2xl rounded-ee-sm bg-accent px-3 py-1.5 text-xs text-accent-fg">
          {message.text}
        </p>
      </div>
    )
  }

  return (
    <div className="rise flex justify-start gap-1.5">
      <BotAvatar />
      <div className="max-w-[85%] rounded-2xl rounded-ss-sm bg-panel-2 px-3 py-2 text-xs">
        {message.status === 'thinking' && (
          <span className="flex items-center gap-2 text-muted">
            <ThinkingDots />
            {t.moodChatThinking}
          </span>
        )}
        {message.status === 'error' && (
          <div className="space-y-1.5">
            <p className="text-danger">{t.moodChatFetchFailed}</p>
            <button
              onClick={() => onRepeat(message.query, message.label)}
              className="inline-flex items-center gap-1 rounded-full border border-line px-2.5 py-1 text-[11px] text-fg transition hover:bg-panel"
            >
              <RetryIcon className="size-3" />
              {t.moodChatRetry}
            </button>
          </div>
        )}
        {message.status === 'done' && <MessageDone message={message} onRepeat={onRepeat} />}
      </div>
    </div>
  )
}

function MessageDone({
  message,
  onRepeat,
}: {
  message: Extract<Message, { status: 'done' }>
  onRepeat: (query: Query, label: string) => void
}) {
  const { t } = useI18n()
  const [showReason, setShowReason] = useState(false)
  const [saving, setSaving] = useState(false)
  const readyItems = message.tracks.filter((ts) => ts.status === 'ready' && ts.item).map((ts) => ts.item!)
  const pushToast = useToasts((s) => s.push)

  /**
   * ذخیره‌ی همین پیشنهاد به‌عنوانِ پلی‌لیستِ دستی.
   *
   * فقط ترک‌های آماده (یا از قبل موجود در کتابخانه) می‌روند: پلی‌لیست روی
   * jobId می‌نشیند و ترکِ دانلودنشده jobId ندارد.
   */
  async function savePlaylist() {
    const jobIds = message.tracks
      .map((ts) => ts.jobId)
      .filter((id): id is string => Boolean(id))
      .filter((id, i, all) => all.indexOf(id) === i)
    if (!jobIds.length) return
    setSaving(true)
    try {
      // اسمِ پلی‌لیست برچسبِ همان درخواست است؛ برای پیامِ آزاد همان متنِ
      // کاربر است و می‌تواند چند صد حرف باشد — فهرستِ پلی‌لیست‌ها را یک‌خطی
      // نگه می‌داریم
      const created = await api.createPlaylist({
        name: message.label.slice(0, 60).trim() || t.moodChatTitle,
        jobIds,
      })
      pushToast(created ? t.moodChatSaved(created.name) : t.moodChatSaveFailed, created ? 'success' : 'error')
    } catch {
      pushToast(t.moodChatSaveFailed, 'error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-2">
      <p>{message.reply}</p>
      {message.reason && (
        <div>
          <button
            onClick={() => setShowReason((v) => !v)}
            aria-expanded={showReason}
            className="inline-flex items-center gap-1 text-[10px] text-muted-2 underline decoration-dotted underline-offset-2 transition hover:text-fg"
          >
            <SparkleIcon className="size-2.5" />
            {t.moodChatWhy}
          </button>
          {showReason && <p className="mt-1 border-s-2 border-accent/40 ps-2 text-[10px] text-muted">{message.reason}</p>}
        </div>
      )}
      {message.tracks.length === 0 ? (
        <p className="text-muted-2">{t.moodChatNoResults}</p>
      ) : (
        <ul className="space-y-1.5">
          {message.tracks.map(({ track, status, error, item, owned, stale }) => (
            <li key={track.id}>
              <div className="flex items-center gap-2">
                <Artwork
                  src={track.artworkUrl}
                  alt={track.title}
                  seed={track.albumId ?? track.id}
                  className="size-7 shrink-0"
                />
                <span className="min-w-0 flex-1 truncate">
                  <bdi>{track.title}</bdi> — <bdi className="text-muted-2">{track.artist}</bdi>
                </span>
                {status === 'pending' &&
                  (stale ? (
                    // ردیفِ بازیابی‌شده: نه دانلودی در کار است نه پخشی — یک
                    // خطِ بی‌حرکت به‌جای اسپینری که هیچ‌وقت تمام نمی‌شود
                    <span className="size-3.5 shrink-0 self-center border-b border-line" aria-hidden />
                  ) : (
                    <Spinner className="size-3.5 shrink-0 text-muted-2" />
                  ))}
                {status === 'ready' && item && (
                  <span className="flex shrink-0 items-center gap-1.5">
                    {/* تیکِ کشیده‌شده: لحظه‌ی «آماده شد» دیده شود، نه اینکه بی‌صدا رد شود */}
                    <CheckDrawIcon className={`size-3.5 ${owned ? 'text-muted-2' : 'text-accent'}`} />
                    <PlayButton items={readyItems} index={readyItems.indexOf(item)} />
                  </span>
                )}
                {status === 'failed' && (
                  <span title={error || t.moodChatTrackFailed} className="shake shrink-0">
                    <WarnIcon className="size-3.5 text-danger" />
                  </span>
                )}
              </div>
              {status === 'failed' && (
                <p className="ps-9 text-[10px] text-danger">{error || t.moodChatTrackFailed}</p>
              )}
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
        {readyItems.length > 0 && (
          <>
            <button
              onClick={() => usePlayer.getState().play(readyItems)}
              className="inline-flex items-center gap-1 rounded-full bg-accent px-2.5 py-1 text-[11px] font-medium text-accent-fg transition hover:brightness-110"
            >
              <PlayIcon className="size-3" />
              {t.moodChatPlay}
            </button>
            <button
              onClick={() => usePlayer.getState().enqueue(readyItems)}
              className="inline-flex items-center gap-1 rounded-full border border-line px-2.5 py-1 text-[11px] text-muted transition hover:text-fg"
            >
              <QueueIcon className="size-3" />
              {t.moodChatAddQueue}
            </button>
            {API_MODE === 'http' && (
              <button
                onClick={() => void savePlaylist()}
                disabled={saving}
                className="inline-flex items-center gap-1 rounded-full border border-line px-2.5 py-1 text-[11px] text-muted transition hover:text-fg disabled:opacity-50"
              >
                <PlusIcon className="size-3" />
                {t.moodChatSave}
              </button>
            )}
          </>
        )}
        <button
          onClick={() => onRepeat(message.query, message.label)}
          className="inline-flex items-center gap-1 rounded-full px-2 py-1 text-[11px] text-muted-2 transition hover:text-fg"
        >
          <SparkleIcon className="size-3" />
          {t.moodChatMore}
        </button>
      </div>
    </div>
  )
}
