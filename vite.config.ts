import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: 'autoUpdate',
      // اسناد ساختِ خودِ اپ پیش‌کش می‌شوند؛ هیچ runtimeCaching خودکاری برای
      // /api نداریم — کش‌کردنِ کورکورانه‌ی استریمِ صوت هم دیسک را پر می‌کرد
      // هم پاسخِ Range را می‌شکست. به‌جایش `sw-offline.js` فقط همان فایل‌هایی
      // را سرو می‌کند که کاربر خودش برای آفلاین سنجاق کرده، و Range را دستی
      // جواب می‌دهد تا جابه‌جایی روی نوار پخش کار کند.
      workbox: {
        /*
         * `.ico` عمداً در این لیست نیست.
         *
         * سرورِ محلیِ Capacitor (که فایل‌های داخل APK را روی https://localhost
         * سرو می‌کند) برای پسوندِ ico نوعِ MIME نمی‌شناسد و ۴۰۴ برمی‌گرداند.
         * ورک‌باکس یک پاسخِ بدِ پیش‌کش را شکستِ کلِ نصب حساب می‌کند، یعنی داخل
         * اپ اندروید سرویس‌ورکر اصلاً فعال نمی‌شد — و با آن، کلِ کتابخانه‌ی
         * آفلاین. خودِ فایل سرِ جایش است و مرورگرها از `index.html` برش
         * می‌دارند؛ فقط پیش‌کش نمی‌شود.
         */
        globPatterns: ['**/*.{js,css,html,svg,png,woff2}'],
        // خودِ افزونه‌ی سرویس‌ورکر نباید در پیش‌کشِ همان سرویس‌ورکر بنشیند
        globIgnores: ['**/sw-offline.js'],
        importScripts: ['sw-offline.js'],
      },
      // favicon.ico اینجا هم نمی‌آید — `includeAssets` مستقیم به پیش‌کش اضافه
      // می‌کند و همان ۴۰۴ دوباره تکرار می‌شد
      includeAssets: ['icon.png', 'apple-touch-icon-180x180.png'],
      manifest: {
        name: 'آنستریم — Unstream',
        short_name: 'آنستریم',
        description: 'دانلودر و پخش‌کننده‌ی موزیک، آلبوم و پلی‌لیست',
        lang: 'fa',
        dir: 'rtl',
        start_url: '/',
        display: 'standalone',
        background_color: '#070707',
        theme_color: '#070707',
        icons: [
          { src: 'pwa-64x64.png', sizes: '64x64', type: 'image/png' },
          { src: 'pwa-192x192.png', sizes: '192x192', type: 'image/png' },
          { src: 'pwa-512x512.png', sizes: '512x512', type: 'image/png' },
          {
            src: 'maskable-icon-512x512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'maskable',
          },
        ],
      },
    }),
  ],
  test: {
    /*
     * منطقِ خالص، به‌علاوه‌ی تستِ دودِ رندرِ کامپوننت‌ها.
     *
     * هنوز نه DOMی در کار است نه کتابخانه‌ی تستِ جدا: تست‌های `.tsx` فقط با
     * `react-dom/server` مارک‌آپ می‌سازند تا مطمئن شویم مسیرِ رندر بیرون از
     * مرورگر هم نمی‌ترکد. هر چیزی فراتر از این (کلیک، افکت، چیدمان) همچنان
     * به jsdom نیاز دارد و این‌جا نیست.
     */
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
    /*
     * زبان را روی فارسی میخکوب می‌کند. ادعاهایِ تست‌ها روی متنِ رندرشده است و
     * متن به `navigator.language` (محیطِ ماشین) وابسته نباشد.
     */
    setupFiles: ['src/test/env.ts'],
  },
  server: {
    // روی همه‌ی اینترفیس‌ها گوش می‌دهد، نه فقط localhost — وگرنه گوشی که روی
    // همان وای‌فای است اصلاً نمی‌تواند به دِوسرور وصل شود. پروکسیِ /api روی
    // خودِ دِوسرور اجرا می‌شود، پس 127.0.0.1:8000 از دید سرور درست می‌ماند.
    host: true,
    port: 5174,
    proxy: {
      // بک‌اند FastAPI روی 8000 بالا میاد؛ فرانت با /api صداش می‌زنه
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  build: {
    // وندورهای پایدار جدا شوند: react/gsap با هر تغییرِ کدِ اپ هَش‌شان عوض
    // می‌شد و مرورگر مجبور بود دوباره دانلودشان کند. حالا هَشِ این چانک‌ها
    // فقط وقتی عوض می‌شود که خودِ وابستگی ارتقا یابد، نه هر دیپلوی.
    // (Vite 8 روی rolldown است: manualChunks باید تابع باشد نه شیء)
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (id.includes('node_modules')) {
            if (id.includes('react-dom') || id.includes('/react/') || id.includes('scheduler'))
              return 'react'
            if (id.includes('gsap')) return 'gsap'
          }
        },
      },
    },
  },
  // `npm run preview` هم برای تستِ بیلدِ واقعی روی گوشی لازم است
  preview: {
    host: true,
    port: 4174,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
