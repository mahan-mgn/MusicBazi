import type { CapacitorConfig } from '@capacitor/cli'

/**
 * پوسته‌ی اندرویدِ موزیک بازی.
 *
 * کلِ رابط داخل خودِ APK بسته‌بندی می‌شود (`webDir: dist`) و فقط برای *داده*
 * به سرور وصل می‌شود — یعنی باز شدنِ اپ به شبکه وابسته نیست، ولی جستجو و
 * دانلود و پخش هستند. آدرس سرور را کاربر در اولین اجرا وارد می‌کند
 * (`src/lib/server.ts`)، پس اینجا هیچ آی‌پیِ سفت‌شده‌ای نیست.
 */
const config: CapacitorConfig = {
  appId: 'app.musicbazi.client',
  appName: 'Music Bazi',
  webDir: 'dist',
  android: {
    /*
     * سرورِ خانگی روی http ساده است (http://192.168.x.x:8080) و اندروید از
     * نسخه‌ی ۹ به بعد ترافیک رمزنشده را پیش‌فرض می‌بندد. بدون این، اپ نصب
     * می‌شود و هر درخواستی بی‌صدا شکست می‌خورد.
     *
     * اگر از تونلِ https استفاده می‌کنی این لازم نیست، ولی روشن‌بودنش هم چیزی
     * را ناامن‌تر نمی‌کند: خودِ اپ فقط به آدرسی می‌رود که کاربر داده.
     */
    allowMixedContent: true,
    /*
     * پس‌زمینه‌ی خودِ WebView. پیش‌فرضش سفید است و همان یک فریمِ سفید بینِ
     * رفتنِ اسپلشِ تیره و اولین نقاشیِ رابط، به‌شکلِ یک چشمکِ آزاردهنده دیده
     * می‌شود. بالاـکشیدنِ صفحه در انتهای لیست هم همین رنگ را نشان می‌دهد.
     */
    backgroundColor: '#070707',
  },
  server: {
    // اپ محتوا را از داخل خودش سرو می‌کند، نه از یک آدرس راه دور
    androidScheme: 'https',
  },
  plugins: {
    SplashScreen: {
      /*
       * اسپلش را خودِ اپ برمی‌دارد، نه یک تایمر.
       *
       * با `launchAutoHide` روشن، اسپلش بعد از مدتِ ثابتی می‌رفت و اگر رابط
       * هنوز آماده نبود کاربر یک صفحه‌ی خالی می‌دید. حالا `setupNative` آخرِ
       * کار برش می‌دارد — یعنی دقیقاً وقتی که چیدمان درست است.
       */
      launchAutoHide: false,
      backgroundColor: '#070707',
      androidSplashResourceName: 'splash',
      androidScaleType: 'CENTER_CROP',
      showSpinner: false,
      // اگر راه‌اندازی جایی گیر کرد، اپ نباید برای همیشه پشتِ اسپلش بماند
      launchFadeOutDuration: 220,
    },
    StatusBar: {
      // محتوا زیرِ نوار وضعیت کشیده می‌شود؛ جای خالی‌اش از `ShellPlugin` می‌آید
      overlaysWebView: true,
      style: 'DARK',
      backgroundColor: '#00000000',
    },
    Keyboard: {
      // خودِ WebView کوچک می‌شود تا نوارهای ثابتِ پایین بالای کیبورد بمانند
      resize: 'native',
      resizeOnFullScreen: true,
    },
  },
}

export default config
