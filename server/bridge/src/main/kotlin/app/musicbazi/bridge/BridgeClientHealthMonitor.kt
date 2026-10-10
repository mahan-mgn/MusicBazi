package app.musicbazi.bridge

import com.metrolist.innertubex.extraction.strategy.ClientFailureKind
import com.metrolist.innertubex.extraction.strategy.ClientHealthMonitor
import com.metrolist.innertubex.extraction.strategy.ClientHealthScope
import org.slf4j.LoggerFactory
import java.util.concurrent.ConcurrentHashMap

/**
 * پیاده‌سازی Health Monitor کلاینت‌های InnerTubeX روی نقطه اتصال رسمی کتابخانه
 * (com.metrolist.innertubex.extraction.strategy.ClientHealthMonitor) — Phase 7.
 *
 * هیچ تغییری در کتابخانه InnerTubeX، الگوریتم انتخاب کلاینت یا نسخه dependency
 * داده نمی‌شود؛ این کلاس فقط hook ای است که خود کتابخانه برای host تعریف کرده.
 * کتابخانه روی شکست‌ها (PLAYER_REQUEST / PLAYABILITY) خودش recordFailure صدا
 * می‌زند و scoreAdjustment فقط ترتیب نامزدها را deprioritize می‌کند — بنابراین
 * کلاینت ناسالم hard-exclude نمی‌شود و InnerTubeX خودش کلاینت‌های سالم بعدی را
 * امتحان می‌کند.
 *
 * مدل Health:
 *   key    = manifestId + "|" + content scope
 *   threshold = ۲ شکست متوالی (قابل تنظیم با env)
 *   cooldown  = ۳۰۰ ثانیه (قابل تنظیم با env)؛ پس از آن HALF-OPEN و تلاش مجدد مجاز
 *   success   = reset کامل entry همان کلاینت (host-side، طبق قرارداد کتابخانه)
 *   TTL       = پاک‌سازی entry های کهنه برای جلوگیری از رشد حافظه
 *
 * امنیت: state فقط شامل شناسه کلاینت/نوع شکست/شمارنده/مهر زمانی است. هیچ URL
 * امضاشده، cookie، PO token یا داده‌ای session ذخیره یا لاگ نمی‌شود.
 */
class BridgeClientHealthMonitor(
    private val failureThreshold: Int = envInt("MUSICBAZI_INNERTUBEX_CLIENT_HEALTH_THRESHOLD", 2),
    private val cooldownMs: Long = envLong("MUSICBAZI_INNERTUBEX_CLIENT_HEALTH_COOLDOWN_SECONDS", 300) * 1000L,
    private val entryTtlMs: Long = envLong("MUSICBAZI_INNERTUBEX_CLIENT_HEALTH_TTL_SECONDS", 3600) * 1000L,
    private val unhealthyScorePenalty: Int = -1_000,
    private val nowMs: () -> Long = System::currentTimeMillis,
) : ClientHealthMonitor {

    private class Entry {
        var failureCount: Int = 0
        var lastFailureAtMs: Long = 0L
        var unhealthyUntilMs: Long = 0L
        var lastFailureKind: String = ""
        var lastUpdateMs: Long = 0L
    }

    private val entries = ConcurrentHashMap<String, Entry>()
    private val logger = LoggerFactory.getLogger(BridgeClientHealthMonitor::class.java)

    private fun key(clientId: String, scope: ClientHealthScope?): String =
        "${clientId}|${scope?.content?.name ?: "ANY"}"

    override fun scoreAdjustment(clientId: String, scope: ClientHealthScope?): Int {
        val entry = entries[key(clientId, scope)] ?: return 0
        synchronized(entry) {
            if (entry.unhealthyUntilMs <= 0L) return 0
            val now = nowMs()
            if (now >= entry.unhealthyUntilMs) {
                // HALF-OPEN: پایان cooldown، تلاش مجدد مجاز (بدون جریمه)
                return 0
            }
            return unhealthyScorePenalty
        }
    }

    override fun recordFailure(clientId: String, kind: ClientFailureKind, scope: ClientHealthScope?) {
        val now = nowMs()
        val k = key(clientId, scope)
        val entry = entries.computeIfAbsent(k) { Entry() }
        var becameUnhealthy = false
        var countAtLog = 0
        synchronized(entry) {
            // شکستِ خیلی قدیمِ یک کلاینت سالم، زنجیره «متوالی» را ادامه نمی‌دهد
            if (entry.unhealthyUntilMs <= 0L && entry.failureCount > 0 &&
                now - entry.lastFailureAtMs > cooldownMs
            ) {
                entry.failureCount = 0
            }
            entry.failureCount += 1
            entry.lastFailureAtMs = now
            entry.lastFailureKind = kind.name
            entry.lastUpdateMs = now
            countAtLog = entry.failureCount
            if (entry.failureCount >= failureThreshold) {
                entry.unhealthyUntilMs = now + cooldownMs
                becameUnhealthy = true
            }
        }
        if (becameUnhealthy) {
            logger.warn(
                "client={} scope={} event=failure kind={} failure_count={} state=UNHEALTHY cooldownMs={}",
                clientId, scope?.content?.name ?: "ANY", kind.name, countAtLog, cooldownMs
            )
        } else {
            logger.info(
                "client={} scope={} event=failure kind={} state=HEALTHY",
                clientId, scope?.content?.name ?: "ANY", kind.name
            )
        }
        cleanup()
    }

    override fun recordSuccess(clientId: String, scope: ClientHealthScope?) {
        val removed = if (scope == null) {
            // موفقیت host-side مرجع نهایی است: همه scope های این کلاینت بازیابی می‌شوند
            removeAllForClient(clientId)
        } else {
            entries.remove(key(clientId, scope)) != null
        }
        if (removed) {
            logger.info("client={} event=recovered state=HEALTHY", clientId)
        }
    }

    private fun removeAllForClient(clientId: String): Boolean {
        val prefix = "$clientId|"
        var any = false
        val matching = entries.keys.filter { it.startsWith(prefix) }
        for (k in matching) {
            if (entries.remove(k) != null) any = true
        }
        return any
    }

    /**
     * حذف entry های منقضی (TTL) برای bound نگه‌داشتن حافظه؛ تعداد حذف‌شده‌ها.
     */
    fun cleanup(): Int {
        val now = nowMs()
        var removed = 0
        val iterator = entries.entries.iterator()
        while (iterator.hasNext()) {
            val e = iterator.next()
            synchronized(e.value) {
                if (now - e.value.lastUpdateMs > entryTtlMs) {
                    iterator.remove()
                    removed++
                }
            }
        }
        return removed
    }

    /**
     * نمای تشخیصی فقط-خواندنی (بدون هیچ داده حساس) برای diagnostics آینده.
     */
    fun snapshot(): Map<String, Map<String, Any>> {
        val now = nowMs()
        val result = mutableMapOf<String, Map<String, Any>>()
        for ((k, entry) in entries) {
            synchronized(entry) {
                if (now - entry.lastUpdateMs > entryTtlMs) return@synchronized
                val state = when {
                    entry.unhealthyUntilMs <= 0L -> "HEALTHY"
                    now < entry.unhealthyUntilMs -> "UNHEALTHY"
                    else -> "HALF_OPEN"
                }
                result[k] = mapOf(
                    "failure_count" to entry.failureCount,
                    "last_failure_kind" to entry.lastFailureKind,
                    "state" to state,
                )
            }
        }
        return result
    }

    companion object {
        private fun envInt(name: String, default: Int): Int =
            System.getenv(name)?.toIntOrNull() ?: default

        private fun envLong(name: String, default: Long): Long =
            System.getenv(name)?.toLongOrNull() ?: default
    }
}
