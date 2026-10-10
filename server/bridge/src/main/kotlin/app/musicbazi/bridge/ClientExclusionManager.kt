package app.musicbazi.bridge

import java.util.concurrent.ConcurrentHashMap

/**
 * مدیریت نیمکت‌نشینی موقت کلاینت‌های ردشده در سطح ویدیو (Phase 2).
 * ساختار نگاشت: videoId -> clientId -> expiryMs (مدت پیش‌فرض ۱۰ دقیقه مطابق با BitChord).
 */
class ClientExclusionManager(
    private val exclusionTtlMs: Long = 10 * 60 * 1000L, // 10 minutes
    private val nowMs: () -> Long = System::currentTimeMillis
) {
    private val excluded = ConcurrentHashMap<String, ConcurrentHashMap<String, Long>>()

    fun exclude(videoId: String, clientId: String) {
        if (videoId.isBlank() || clientId.isBlank()) return
        excluded.getOrPut(videoId) { ConcurrentHashMap() }[clientId] = nowMs() + exclusionTtlMs
    }

    fun excludedFor(videoId: String): Set<String> {
        val entries = excluded[videoId] ?: return emptySet()
        val now = nowMs()
        entries.entries.removeIf { it.value <= now }
        return entries.keys.toSet()
    }

    fun isExcluded(videoId: String, clientId: String): Boolean {
        val entries = excluded[videoId] ?: return false
        val exp = entries[clientId] ?: return false
        if (nowMs() >= exp) {
            entries.remove(clientId)
            return false
        }
        return true
    }

    fun clear() {
        excluded.clear()
    }
}
