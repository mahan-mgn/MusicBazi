import { useI18n } from '../lib/i18n'
import { API_MODE } from '../lib/api'
import { TelegramConnection } from './TelegramLink'

const AUTHORS = [
  { handle: 'mahan-mgn', url: 'https://github.com/mahan-mgn', avatar: '/avatar.jpg' },
]

/** آواتار اختصاصی یا تولیدی — بدون درخواست شبکه‌ی خارجی */
function Avatar({ seed, avatar }: { seed: string; avatar?: string }) {
  if (avatar) {
    return <img src={avatar} alt="" aria-hidden className="size-4 shrink-0 rounded-full object-cover" />
  }
  let h = 0
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0
  const hue = h % 360
  return (
    <span
      aria-hidden
      className="grid size-4 shrink-0 place-items-center rounded-full text-[8px] font-bold text-black/70"
      style={{ background: `linear-gradient(140deg, hsl(${hue} 55% 62%), hsl(${(hue + 48) % 360} 55% 45%))` }}
    >
      {seed[0].toUpperCase()}
    </span>
  )
}

export default function Footer() {
  const { t } = useI18n()

  return (
    <footer className="px-safe pb-8 text-center text-[11px] text-muted-2">
      {API_MODE === 'mock' && (
        <p className="mb-3">
          <span className="rounded-full border border-line bg-panel px-2 py-1">{t.demoMode}</span>
        </p>
      )}
      {/*
       * راهِ برگشت به ویزاردِ راه‌اندازی. یک لینکِ معمولی با `href`، نه
       * ناوبریِ داخلی: صفحه از نو بار می‌شود و `App` خودش دوباره از سرور
       * می‌پرسد — همان مسیری که بارِ اول رفتیم، بدونِ هیچ stateِ تازه.
       */}
      {API_MODE === 'http' && (
        <p className="mb-3">
          <a
            href="/?setup=1"
            className="rounded-full border border-line bg-panel px-2.5 py-1 transition hover:border-accent/50 hover:text-fg"
          >
            {t.setupMenu}
          </a>
        </p>
      )}
      {/* اینجا، نه در تنظیماتِ صدا: «فایل‌ها به کدام چت می‌روند» چیزی است که
          کاربر باید بدون گشتن ببیند و بتواند قطعش کند */}
      <div className="mx-auto mb-3 w-fit max-w-sm">
        <TelegramConnection />
      </div>

      <p className="inline-flex flex-wrap items-center justify-center gap-1.5">
        <span>{t.builtBy}</span>
        {AUTHORS.map((author, i) => (
          <span key={author.handle} className="inline-flex items-center gap-1.5">
            {i > 0 && <span className="text-muted-2">{t.and}</span>}
            <a
              href={author.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 transition hover:text-fg"
            >
              <Avatar seed={author.handle} avatar={author.avatar} />
              {author.handle}
            </a>
          </span>
        ))}
      </p>
    </footer>
  )
}
