/**
 * آیکون‌های لانچر و تصویرهای اسپلشِ اندروید را از روی همان لوگو می‌سازد.
 *
 * جایگزینِ `@capacitor/assets` است — نه از سرِ لجبازی، بلکه چون آن ابزار برای
 * خودش `sharp` نصب می‌کند و اینجا (ویندوز، با اسکریپت‌های نصبِ محدودشده)
 * باینری‌اش بالا نمی‌آید. این اسکریپت همان کار را با `sharp`ی می‌کند که خودِ
 * پروژه از قبل دارد.
 *
 * اجرا: `npm run android:assets` (خودش داخلِ `android:sync` هم صدا زده می‌شود)
 */

import { mkdir, writeFile } from 'node:fs/promises'
import sharp from 'sharp'

const BG = '#070707'
const RES = 'android/app/src/main/res'
const SOURCE = 'public/logo.png'
const logoPng = await sharp(SOURCE).resize(512, 512, { fit: 'cover' }).png().toBuffer()

const png = (source, width, height = width) =>
  sharp(source, { density: 384 }).resize(width, height, { kernel: 'lanczos3' }).png({ compressionLevel: 9 }).toBuffer()

async function write(path, buffer) {
  await mkdir(path.slice(0, path.lastIndexOf('/')), { recursive: true })
  await writeFile(path, buffer)
}

/* ---------- آیکونِ لانچر ---------- */

/** آیکونِ کامل: لوگو داخلِ مربعِ گردگوشه — برای اندرویدهای پیش از آیکونِ تطبیقی */
const fullIcon = logoPng

/** همان، ولی گِرد — بعضی لانچرها هنوز `ic_launcher_round` را جدا می‌خواهند */
const roundIcon = await sharp(logoPng).composite([{ input: Buffer.from(`<svg width="512" height="512"><circle cx="256" cy="256" r="256" fill="white"/></svg>`), blend: 'dest-in' }]).png().toBuffer()

/**
 * لایه‌ی جلوی آیکونِ تطبیقی: فقط لوگو، روی بومِ شفاف.
 *
 * ضریبِ ۰٫۵۵ از روی قاعده‌ی خودِ اندروید است: از بومِ ۱۰۸dp تنها ۷۲dpِ مرکزی
 * (۶۶٪) تضمین‌شده بیرونِ ماسک می‌ماند. لوگو در این ضریب حدود ۵۹dp می‌شود، پس
 * روی ماسکِ دایره‌ای هم گوشه‌هایش بریده نمی‌شوند.
 */
const foregroundLogo = await sharp(logoPng).resize(358, 358, { fit: 'contain', kernel: 'lanczos3' }).png().toBuffer()
const foreground = await sharp({ create: { width: 512, height: 512, channels: 4, background: { r: 0, g: 0, b: 0, alpha: 0 } } }).composite([{ input: foregroundLogo, left: 77, top: 77 }]).png().toBuffer()

/** dpi → اندازه‌ی آیکون (پیکسل). عددهای استانداردِ اندروید. */
const ICON = { mdpi: 48, hdpi: 72, xhdpi: 96, xxhdpi: 144, xxxhdpi: 192 }

for (const [dpi, size] of Object.entries(ICON)) {
  await write(`${RES}/mipmap-${dpi}/ic_launcher.png`, await png(fullIcon, size))
  await write(`${RES}/mipmap-${dpi}/ic_launcher_round.png`, await png(roundIcon, size))
  // لایه‌ی جلو روی بومِ ۱۰۸dp است نه ۴۸dp، پس ۲٫۲۵ برابرِ آیکونِ همان چگالی
  await write(
    `${RES}/mipmap-${dpi}/ic_launcher_foreground.png`,
    await png(foreground, Math.round(size * 2.25)),
  )
}

/* ---------- اسپلش ---------- */

/**
 * تصویرِ اسپلش برای یک نسبتِ مشخص.
 *
 * لوگو با نسبت به *کوچک‌ترین* بُعد اندازه می‌گیرد، نه به عرض: وگرنه همان تصویر
 * در حالت افقی یک لوگوی غول‌پیکرِ بریده می‌شد.
 */
async function splashSvg(width, height) {
  const min = Math.min(width, height)
  const size = Math.round(min * 0.28)
  const x = Math.round((width - size) / 2)
  const y = Math.round((height - size) / 2)
  const background = Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}"><rect width="100%" height="100%" fill="${BG}"/></svg>`)
  const splashLogo = await sharp(logoPng).resize(size, size, { kernel: 'lanczos3' }).png().toBuffer()
  return sharp(background).composite([{ input: splashLogo, left: x, top: y }]).png().toBuffer()
}

/** dpi → اندازه‌ی عمودیِ اسپلش؛ حالتِ افقی همین‌ها با جای عوض‌شده است */
const SPLASH = {
  mdpi: [320, 480],
  hdpi: [480, 800],
  xhdpi: [720, 1280],
  xxhdpi: [960, 1600],
  xxxhdpi: [1280, 1920],
}

for (const [dpi, [w, h]] of Object.entries(SPLASH)) {
  await write(`${RES}/drawable-port-${dpi}/splash.png`, await splashSvg(w, h))
  await write(`${RES}/drawable-land-${dpi}/splash.png`, await splashSvg(h, w))
}

// نسخه‌ی بی‌چگالی — وقتی اندروید هیچ‌کدام از بالایی‌ها را انتخاب نکند
await write(`${RES}/drawable/splash.png`, await splashSvg(480, 320))

// لوگوی باکیفیت برای اسپلش اسکرین اندروید ۱۲ به بعد
await write(`${RES}/drawable/splash_logo.png`, await png(logoPng, 512))

console.log('آیکون‌ها و اسپلش ساخته شدند.')
