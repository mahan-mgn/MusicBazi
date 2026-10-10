package app.musicbazi.bridge

import com.metrolist.innertubex.extraction.strategy.ClientFailureKind
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class ClientRotationTest {

    private class FakeClock(var now: Long = 1_000_000L) {
        fun advance(ms: Long) {
            now += ms
        }
    }

    // -------------------------------------------------------------------------
    // ۹. عدم تکرار Client ردشده در بازه محدودیت (۱۰ دقیقه) (Scenario 9)
    // -------------------------------------------------------------------------

    @Test
    fun testClientExclusionTtlAndVideoScope() {
        val clock = FakeClock()
        val exclusionManager = ClientExclusionManager(
            exclusionTtlMs = 600_000L, // 10 minutes
            nowMs = { clock.now }
        )

        val videoId1 = "vid_101"
        val videoId2 = "vid_102"
        val client = "ANDROID_VR"

        // کلاینت برای ویدیو ۱ رد می‌شود
        exclusionManager.exclude(videoId1, client)

        assertTrue(exclusionManager.isExcluded(videoId1, client), "کلاینت باید برای ویدیوی ردشده در لیست محرومیت باشد")
        assertTrue(exclusionManager.excludedFor(videoId1).contains(client))

        // ایزولاسیون ویدیو: شکست در ویدیوی ۱ نباید ویدیوی ۲ را محروم کند
        assertFalse(exclusionManager.isExcluded(videoId2, client), "شکست در یک ویدیو نباید کلاینت را برای ویدیوهای دیگر محروم کند")
        assertFalse(exclusionManager.excludedFor(videoId2).contains(client))

        // گذشت ۵ دقیقه: هنوز محروم است
        clock.advance(300_000L)
        assertTrue(exclusionManager.isExcluded(videoId1, client))

        // گذشت ۶ دقیقه دیگر (مجموع ۱۱ دقیقه): پایان TTL و آزادسازی کلاینت
        clock.advance(360_000L)
        assertFalse(exclusionManager.isExcluded(videoId1, client), "پس از پایان ۱۰ دقیقه کلاینت باید از محرومیت خارج شود")
        assertFalse(exclusionManager.excludedFor(videoId1).contains(client))
    }

    // -------------------------------------------------------------------------
    // ۱۰. ثبت بازخورد خطاهای حین پخش (onPlaybackRefused) (Scenario 10)
    // -------------------------------------------------------------------------

    @Test
    fun testOnPlaybackRefusedBenchesClientAndNotifiesHealthMonitor() {
        val clock = FakeClock()
        val exclusion = ClientExclusionManager(nowMs = { clock.now })
        val healthMonitor = BridgeClientHealthMonitor(nowMs = { clock.now })
        val service = InnerTubeService(
            clientHealthMonitor = healthMonitor,
            exclusionManager = exclusion
        )

        val videoId = "test_vid_refuse"
        val streamUrl = "https://rr1---sn-abc.googlevideo.com/videoplayback?id=123"
        val profileId = "TVHTML5__nopo"
        val clientName = "TVHTML5"

        // شبیه‌سازی ایجاد استریم و ثبت در minted
        service.rememberMinted(streamUrl, videoId, profileId, clientName)

        // ۱. خطای 500 یا غیر-انقضا نباید کلاینت را بن کند
        val handled500 = service.onPlaybackRefused(streamUrl, videoId, 500, clientName, profileId)
        assertFalse(handled500, "خطای 500 نباید به عنوان رد شدن کلاینت ثبت شود")
        assertFalse(exclusion.isExcluded(videoId, profileId))

        // ۲. خطای 403 با شواهد انقضا/رد شدن CDN کلاینت را نیمکت‌نشین می‌کند
        val handled403 = service.onPlaybackRefused(streamUrl, videoId, 403, clientName, profileId)
        assertTrue(handled403, "خطای 403 با شواهد کافی باید پذیرفته شود")
        assertTrue(exclusion.isExcluded(videoId, profileId), "profileId باید در لیست محرومیت ثبت شود")
        assertTrue(exclusion.isExcluded(videoId, clientName), "clientName باید در لیست محرومیت ثبت شود")

        // بررسی ثبت شکست در ClientHealthMonitor
        val snapshot = healthMonitor.snapshot()
        val healthKey = "TVHTML5|ANY"
        assertTrue(snapshot.containsKey(healthKey), "باید شکست در مانیتور سلامت کلاینت ثبت شده باشد")
    }

    // -------------------------------------------------------------------------
    // ۷ و ۸. چرخش کلاینت‌ها و اعمال سقف ۳ تلاش (Scenario 7 & 8)
    // -------------------------------------------------------------------------

    @Test
    fun testExclusionManagerAccumulatesSkipClients() {
        val exclusion = ClientExclusionManager()
        val videoId = "vid_rotation"

        // شبیه‌سازی سه کلاینت در تلاش‌های پیاپی
        val client1 = "WEB_REMIX"
        val client2 = "IOS"
        val client3 = "ANDROID"

        exclusion.exclude(videoId, client1)
        assertEquals(setOf(client1), exclusion.excludedFor(videoId))

        exclusion.exclude(videoId, client2)
        assertEquals(setOf(client1, client2), exclusion.excludedFor(videoId))

        exclusion.exclude(videoId, client3)
        assertEquals(setOf(client1, client2, client3), exclusion.excludedFor(videoId))
    }
}
