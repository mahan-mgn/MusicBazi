package app.musicbazi.bridge

import com.metrolist.innertubex.extraction.strategy.ClientFailureKind
import com.metrolist.innertubex.extraction.strategy.ClientHealthScope
import com.metrolist.innertubex.extraction.strategy.ClientHealthContent
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * تست‌های Phase 7 — سلامت کلاینت‌های InnerTubeX در Bridge.
 */
class BridgeClientHealthMonitorTest {

    private class FakeClock(var now: Long = 1_000_000L) {
        fun advance(ms: Long) {
            now += ms
        }
    }

    private fun monitor(clock: FakeClock, threshold: Int = 2, cooldownMs: Long = 300_000L) =
        BridgeClientHealthMonitor(
            failureThreshold = threshold,
            cooldownMs = cooldownMs,
            entryTtlMs = 3_600_000L,
            nowMs = { clock.now },
        )

    @Test
    fun newClientIsHealthyAndEligible() {
        val clock = FakeClock()
        val m = monitor(clock)
        assertEquals(0, m.scoreAdjustment("WEB_REMIX"))
    }

    @Test
    fun firstFailureDoesNotDeprioritize() {
        val clock = FakeClock()
        val m = monitor(clock)
        m.recordFailure("WEB_REMIX", ClientFailureKind.PLAYER_REQUEST)
        assertEquals(0, m.scoreAdjustment("WEB_REMIX"))
    }

    @Test
    fun thresholdReachedDeprioritizesClient() {
        val clock = FakeClock()
        val m = monitor(clock)
        m.recordFailure("WEB_REMIX", ClientFailureKind.PLAYER_REQUEST)
        m.recordFailure("WEB_REMIX", ClientFailureKind.PLAYER_REQUEST)
        assertEquals(-1_000, m.scoreAdjustment("WEB_REMIX"))
    }

    @Test
    fun cooldownExpiryAllowsRetry() {
        val clock = FakeClock()
        val m = monitor(clock)
        m.recordFailure("WEB_REMIX", ClientFailureKind.PLAYER_REQUEST)
        m.recordFailure("WEB_REMIX", ClientFailureKind.PLAYER_REQUEST)
        assertEquals(-1_000, m.scoreAdjustment("WEB_REMIX"))

        clock.advance(301_000L)
        assertEquals(0, m.scoreAdjustment("WEB_REMIX"))
    }

    @Test
    fun successResetsFailureCount() {
        val clock = FakeClock()
        val m = monitor(clock)
        m.recordFailure("WEB_REMIX", ClientFailureKind.PLAYER_REQUEST)
        m.recordFailure("WEB_REMIX", ClientFailureKind.PLAYER_REQUEST)
        assertEquals(-1_000, m.scoreAdjustment("WEB_REMIX"))

        m.recordSuccess("WEB_REMIX", scope = null)
        assertEquals(0, m.scoreAdjustment("WEB_REMIX"))

        // شمارنده صفر شده: یک شکست جدید نباید دوباره ناسالم کند
        m.recordFailure("WEB_REMIX", ClientFailureKind.PLAYER_REQUEST)
        assertEquals(0, m.scoreAdjustment("WEB_REMIX"))
    }

    @Test
    fun clientsAreIndependent() {
        val clock = FakeClock()
        val m = monitor(clock)
        m.recordFailure("VISIONOS_0_1", ClientFailureKind.PLAYABILITY)
        m.recordFailure("VISIONOS_0_1", ClientFailureKind.PLAYABILITY)
        assertEquals(-1_000, m.scoreAdjustment("VISIONOS_0_1"))
        assertEquals(0, m.scoreAdjustment("WEB_REMIX"))
        assertEquals(0, m.scoreAdjustment("TVHTML5_SIMPLY"))
    }

    @Test
    fun contentScopesAreIndependent() {
        val clock = FakeClock()
        val m = monitor(clock)
        val normal = ClientHealthScope(content = ClientHealthContent.NORMAL, authenticated = false, wantVideo = false)
        val explicit = ClientHealthScope(content = ClientHealthContent.EXPLICIT, authenticated = false, wantVideo = false)
        m.recordFailure("WEB_REMIX", ClientFailureKind.PLAYER_REQUEST, normal)
        m.recordFailure("WEB_REMIX", ClientFailureKind.PLAYER_REQUEST, normal)
        assertEquals(-1_000, m.scoreAdjustment("WEB_REMIX", normal))
        assertEquals(0, m.scoreAdjustment("WEB_REMIX", explicit))
    }

    @Test
    fun cleanupRemovesExpiredEntries() {
        val clock = FakeClock()
        val m = monitor(clock)
        m.recordFailure("WEB_REMIX", ClientFailureKind.PLAYER_REQUEST)
        assertTrue(m.snapshot().containsKey("WEB_REMIX|ANY"))

        clock.advance(3_600_001L)
        assertEquals(1, m.cleanup())
        assertFalse(m.snapshot().containsKey("WEB_REMIX|ANY"))
        assertEquals(0, m.scoreAdjustment("WEB_REMIX"))
    }

    @Test
    fun halfOpenFailureRemarksUnhealthy() {
        val clock = FakeClock()
        val m = monitor(clock)
        m.recordFailure("WEB_REMIX", ClientFailureKind.PLAYER_REQUEST)
        m.recordFailure("WEB_REMIX", ClientFailureKind.PLAYER_REQUEST)
        clock.advance(301_000L)
        assertEquals(0, m.scoreAdjustment("WEB_REMIX"))

        m.recordFailure("WEB_REMIX", ClientFailureKind.PLAYER_REQUEST)
        assertEquals(-1_000, m.scoreAdjustment("WEB_REMIX"))
    }

    @Test
    fun concurrentFailuresAreThreadSafe() {
        val clock = FakeClock()
        val m = monitor(clock)
        val threads = (1..8).map {
            Thread {
                repeat(50) { m.recordFailure("WEB_REMIX", ClientFailureKind.PLAYER_REQUEST) }
            }
        }
        threads.forEach { it.start() }
        threads.forEach { it.join() }
        assertEquals(-1_000, m.scoreAdjustment("WEB_REMIX"))
    }

    @Test
    fun snapshotContainsOnlyTechnicalFields() {
        val clock = FakeClock()
        val m = monitor(clock)
        m.recordFailure("WEB_REMIX", ClientFailureKind.PLAYER_REQUEST)
        val entry = m.snapshot()["WEB_REMIX|ANY"]!!
        assertEquals(1, entry["failure_count"])
        assertEquals("PLAYER_REQUEST", entry["last_failure_kind"])
        assertEquals("HEALTHY", entry["state"])
        assertEquals(setOf("failure_count", "last_failure_kind", "state"), entry.keys)
    }
}
