/**
 * ساختنِ APK/PBFِ ریلیز + آماده‌کردنِ `latest.json` برای انتشار روی سرور.
 *
 * چرا اسکریپت و نه فقط `gradlew assembleRelease`؟ چون آپدیت‌چکِ اپ به دو چیز
 * نیاز دارد که gradlew تولید نمی‌کند: manifestِ نسخه، و کپی‌شدنِ فایل کنارش روی
 * سرور. بدونِ این، `versionCode` در `build.gradle` می‌ماند و هیچ‌کس یادش نمی‌آید
 * `latest.json` را هم عوض کند — یعنی بنرِ «بروزرسانی هست» روی همان نسخه‌ی
 * خودش می‌ماند و کاربر چیزی نصب نمی‌کند.
 *
 * اجرا:
 *   node scripts/android-release.mjs            # بیلد + ساختنِ پوشه‌ی release/
 *   node scripts/android-release.mjs --publish  # و کپی‌کردن روی سرور (MUSICBAZI_RELEASES_DIR)
 *
 * `mapping.txt` هم کنار خروجی می‌نشیند: بدونِ آن، stacktraceی که از
 * `POST /api/client-error` می‌آید (که R8 آن را مبهم کرده) هیچ‌وقت رمزگشا نمی‌شود.
 */

import { cp, mkdir, readdir, readFile, rm, stat, writeFile } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const OUT = join(ROOT, 'release-out')

/** نسخه را از `android/app/build.gradle` می‌خواند — تنها منبعِ حقیقت */
async function readVersion() {
  const text = await readFile(join(ROOT, 'android/app/build.gradle'), 'utf8')
  const code = Number(text.match(/versionCode\s+(\d+)/)?.[1] ?? 0)
  const name = text.match(/versionName\s+"([^"]+)"/)?.[1] ?? ''
  if (!code || !name) throw new Error('versionCode/versionName در build.gradle پیدا نشد')
  return { code, name }
}

const gradlew = join(ROOT, 'android', process.platform === 'win32' ? 'gradlew.bat' : 'gradlew')

function run(task) {
  console.log(`› ${task}`)
  const res = spawnSync(gradlew, [task, '--console=plain'], {
    cwd: join(ROOT, 'android'),
    stdio: 'inherit',
    shell: process.platform === 'win32',
  })
  if (res.status !== 0) process.exit(res.status ?? 1)
}

/*
 * همگام‌سازیِ وب‌اپدیت‌ها داخلِ `android/app/src/main/assets/public` — قبل از هر بیلد.

 این اسکریپت مستقیم gradlew را صدا می‌زند (نه `npm run android:release`)، پس اگر
 اینجا sync نشود، APK از assetsِ دورِ *قبل* ساخته می‌شود: تست‌ها سبز، بیلد سبز،
 ولی کدِ تازه داخلِ اپ نیست. یک بار این اتفاق افتاد و تا بازکردنِ خودِ APK با
 `unzip | grep` کشف نشد. `--no-sync` برای وقتی که مطمئنی assets تازه است.
*/
function syncWebAssets() {
  if (process.argv.includes('--no-sync')) return
  console.log('› npm run android:sync')
  const npmCmd = process.platform === 'win32' ? 'npm.cmd' : 'npm'
  const res = spawnSync(npmCmd, ['run', 'android:sync'], {
    cwd: ROOT,
    stdio: 'inherit',
    shell: process.platform === 'win32',
  })
  if (res.status !== 0) process.exit(res.status ?? 1)
}

const { code, name } = await readVersion()
const wantApk = process.argv.includes('--apk')
const wantBundle = process.argv.includes('--bundle')
const publish = process.argv.includes('--publish')

syncWebAssets()

// هیچ فلگی داده نشد → هر دو
if (!wantApk && !wantBundle) {
  run('assembleRelease')
  run('bundleRelease')
} else {
  if (wantApk) run('assembleRelease')
  if (wantBundle) run('bundleRelease')
}

await mkdir(OUT, { recursive: true })

/*
 * پاک‌سازیِ خروجیِ بیلد از دورِ قبل.

 `grab` فایل‌ها را هم‌نام می‌کند، پس اگر بیلدِ قبلی unsigned بوده و این‌بار
 امضا شده، هر دو در پوشه می‌مانند و `--publish` هر دو را روی سرور می‌ریزد —
 آن‌وقت `latest.json` به یکی اشاره می‌کند و کاربرِ دستی دیگری برمی‌دارد.
 (mapping/latest.json را نمی‌روبیم؛ mapping همین‌جا بازنویسی می‌شود و اگر
 بیلدِ تازه mapping نساخته، دومی از اول بی‌اعتبار است.)
*/
for (const f of await readdir(OUT)) {
  if (/\.(apk|aab)$/.test(f)) await rm(join(OUT, f))
}

const copied = []
async function grab(src, label) {
  if (!src || !existsSync(src)) {
    console.warn(`⚠ ${label} پیدا نشد: ${src}`)
    return null
  }
  const dest = join(OUT, src.split(/[\\/]/).pop())
  await cp(src, dest)
  copied.push(dest)
  return dest
}

/*
 * نامِ APK به امضاس: بدونِ `keystore.properties` خروجی `app-release-unsigned.apk`
 * است و با keystore می‌شود `app-release.apk`. جست‌وجویِ پوشه هر دو را می‌گیرد —
 * اگر فقط نامِ امضاشده را hardcode می‌کردیم، روی ماشینِ بدونِ کلید، manifestِ
 * «بدونِ فایل» ساخته می‌شد و بنرِ اپ هیچ‌وقت لینکِ دانلود نمی‌داد.
 */
async function findApk() {
  const dir = join(ROOT, 'android/app/build/outputs/apk/release')
  if (!existsSync(dir)) return null
  const names = (await readdir(dir)).filter((n) => /^app-release.*\.apk$/.test(n))
  // امضاشده برنده است؛ unsigned روی گوشی نصب نمی‌شود و گمراه‌کننده است
  return join(dir, names.find((n) => n === 'app-release.apk') ?? names[0] ?? '')
}

const apk = await grab(await findApk(), 'APK')
await grab(join(ROOT, 'android/app/build/outputs/bundle/release/app-release.aab'), 'AAB')
// یک APKِ سالمِ این اپ چند مگابایت است (وب‌باندل داخلش). چیزی زیرِ ۲۰۰KB یعنی
// یا بیلد نصفه بوده یا assets کپی نشده — پیش از انتشار باید معلوم شود
if (apk) {
  if ((await stat(apk)).size < 200_000) {
    console.warn('⚠ APK غیرعادی کوچک است — احتمالاً assets داخلش نرفته.')
  }
  if (apk.includes('unsigned')) {
    // روی گوشی نصب نمی‌شود؛ انتشارش یعنی بنری که دانلودش بی‌فایده است
    console.warn('⚠ APK امضا نشده — keystore.properties را بگذار، وگرنه منتشرش نکن.')
  }
}
await grab(
  join(ROOT, 'android/app/build/outputs/mapping/release/mapping.txt'),
  'mapping (R8)',
)

const notes = process.env.MUSICBAZI_RELEASE_NOTES ?? ''
const manifest = {
  versionCode: code,
  versionName: name,
  notes,
  file: apk ? apk.split(/[\\/]/).pop() : null,
}
await writeFile(join(OUT, 'latest.json'), JSON.stringify(manifest, null, 2) + '\n', 'utf8')

console.log(`\nنسخه ${name} (${code})`)
for (const f of copied) console.log('  ' + f)
console.log('  ' + join(OUT, 'latest.json'))

if (!publish) {
  console.log('\nبرای انتشار روی سرور: --publish  (یا فایل‌ها را در releases/ سرور کپی کن)')
} else if (apk && apk.includes('unsigned')) {
  // انتشارِ unsigned یعنی بنری که دانلودش بی‌فایده است: اندروید بسته‌ی
  // امضانشده را نمی‌پذیرد و کاربر فقط یک فایلِ ۱٫۵ مگابایتیِ بی‌مصرف دارد
  console.error('✖ APK امضا نشده — انتشار نمی‌شود. اول keystore.properties را بگذار.')
  process.exit(1)
} else {
  const dest = process.env.MUSICBAZI_RELEASES_DIR
  if (!dest) throw new Error('MUSICBAZI_RELEASES_DIR ست نشده — مقصد کپی کجاست؟')
  await mkdir(dest, { recursive: true })
  for (const f of [...copied, join(OUT, 'latest.json')]) {
    await cp(f, join(dest, f.split(/[\\/]/).pop()))
  }
  console.log(`\nدر ${dest} کپی شد — اپ تا دورِ بعدیِ بررسی خبر می‌دهد.`)
}
