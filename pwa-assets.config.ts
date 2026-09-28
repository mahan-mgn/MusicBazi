import { defineConfig, minimal2023Preset } from '@vite-pwa/assets-generator/config'

// از لوگوی اصلی خروجی‌های لازم برای manifest/apple-touch-icon
// می‌سازد: favicon.ico، 192/512 معمولی، 512 maskable، و 180 اپلی.
export default defineConfig({
  preset: {
    ...minimal2023Preset,
    maskable: {
      ...minimal2023Preset.maskable,
      // ماسک‌شونده باید فاصله‌ی امن داشته باشد وگرنه سیستم‌عامل موقع
      // گردکردن/دایره‌کردن آیکون، لبه‌ی گلیف را می‌بُرد
      resizeOptions: { background: '#070707', fit: 'contain', padding: 0.3 },
    },
  },
  images: ['public/logo.png'],
})
