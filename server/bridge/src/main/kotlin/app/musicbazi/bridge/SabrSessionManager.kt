package app.musicbazi.bridge

import kotlinx.coroutines.Job
import org.slf4j.LoggerFactory
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap

/**
 * Thread-safe registry and lifecycle coordinator for standalone SABR streaming sessions.
 * Enforces:
 *  - Max 8 active concurrent sessions
 *  - 5-minute TTL expiration and automatic eviction
 *  - Single-consumer mutual exclusion per session (prevents concurrent read corruption)
 *  - Strict video ID validation
 */
class SabrSessionManager(
    private val sabrResolver: ISabrResolver,
    private val maxActiveSessions: Int = 8,
    private val sessionTtlMs: Long = 5 * 60 * 1000L,
    private val clock: () -> Long = System::currentTimeMillis
) {
    private val logger = LoggerFactory.getLogger(SabrSessionManager::class.java)
    private val sessions = ConcurrentHashMap<String, SabrSession>()

    fun activeSessionCount(): Int {
        cleanExpiredSessions()
        return sessions.values.count {
            it.state == SabrSessionState.PREPARED || it.state == SabrSessionState.STREAMING
        }
    }

    fun cleanExpiredSessions() {
        val now = clock()
        val it = sessions.entries.iterator()
        while (it.hasNext()) {
            val entry = it.next()
            val session = entry.value
            if (session.state == SabrSessionState.PREPARED && now >= session.expiresAtEpochMs) {
                session.markExpired()
                logger.info("Marked expired SABR session=${session.id} videoId=${session.videoId}")
            } else if (session.state == SabrSessionState.COMPLETED ||
                session.state == SabrSessionState.CANCELLED ||
                session.state == SabrSessionState.FAILED ||
                session.state == SabrSessionState.EXPIRED
            ) {
                // نشست‌های خاتمه‌یافته یا منقضی‌شده پس از گذشت مهلت تکمیلی (۶۰ ثانیه) به‌طور کامل پاک‌سازی می‌شوند
                if (now >= session.expiresAtEpochMs + 60_000L) {
                    it.remove()
                }
            }
        }
    }

    suspend fun prepareSession(
        videoId: String,
        quality: String? = null,
        playerTimeMs: Long = 0L
    ): SabrPrepareResponse {
        val cleanVid = videoId.trim()
        if (cleanVid.length != 11 || !cleanVid.matches(Regex("^[A-Za-z0-9_-]{11}$"))) {
            throw SabrSessionError.InvalidRequest("Invalid video_id format: must be 11 characters")
        }
        if (playerTimeMs < 0) {
            throw SabrSessionError.InvalidRequest("player_time_ms cannot be negative")
        }

        cleanExpiredSessions()
        val currentActive = sessions.values.count {
            it.state == SabrSessionState.PREPARED || it.state == SabrSessionState.STREAMING
        }
        if (currentActive >= maxActiveSessions) {
            logger.warn("SABR active session limit reached: $currentActive/$maxActiveSessions")
            throw SabrSessionError.LimitExceeded("Active SABR session limit ($maxActiveSessions) reached")
        }

        val resolveResult = sabrResolver.resolveSabr(cleanVid, quality, playerTimeMs)
        val sessionId = UUID.randomUUID().toString()
        val now = clock()
        val expiresAt = now + sessionTtlMs

        val session = SabrSession(
            id = sessionId,
            videoId = cleanVid,
            mimeType = resolveResult.mimeType,
            codec = resolveResult.codec,
            durationMs = resolveResult.durationMs,
            bitrate = resolveResult.bitrate,
            sampleRate = resolveResult.sampleRate,
            channels = resolveResult.channels,
            itag = resolveResult.itag,
            clientName = resolveResult.clientName,
            createdAtEpochMs = now,
            expiresAtEpochMs = expiresAt,
            streamSupplier = {
                resolveResult.streamFactory(resolveResult.bootstrap, playerTimeMs)
            }
        )

        sessions[sessionId] = session
        logger.info("Prepared SABR session=$sessionId videoId=$cleanVid itag=${session.itag} codec=${session.codec}")

        return SabrPrepareResponse(
            ok = true,
            session_id = sessionId,
            video_id = cleanVid,
            mime_type = session.mimeType,
            codec = session.codec,
            duration_ms = session.durationMs,
            bitrate = session.bitrate,
            sample_rate = session.sampleRate,
            channels = session.channels,
            itag = session.itag,
            client_name = session.clientName
        )
    }

    fun getSessionForStreaming(sessionId: String, currentJob: Job?): SabrSession {
        cleanExpiredSessions()
        val session = sessions[sessionId]
            ?: throw SabrSessionError.NotFound("Session $sessionId not found")

        val now = clock()
        if (now >= session.expiresAtEpochMs && session.state == SabrSessionState.PREPARED) {
            session.markExpired()
            sessions.remove(sessionId)
            throw SabrSessionError.Expired("Session $sessionId has expired")
        }

        when (session.state) {
            SabrSessionState.PREPARED -> {
                if (!session.tryStartStreaming(currentJob)) {
                    throw SabrSessionError.InUse("Session $sessionId is already in use")
                }
                return session
            }
            SabrSessionState.STREAMING -> {
                throw SabrSessionError.InUse("Session $sessionId is already being streamed by another consumer")
            }
            SabrSessionState.COMPLETED,
            SabrSessionState.CANCELLED,
            SabrSessionState.FAILED -> {
                throw SabrSessionError.AlreadyConsumed("Session $sessionId has already been consumed (state=${session.state})")
            }
            SabrSessionState.EXPIRED -> {
                throw SabrSessionError.Expired("Session $sessionId has expired")
            }
        }
    }

    fun getSession(sessionId: String): SabrSession? = sessions[sessionId]

    fun clearAll() {
        sessions.clear()
    }
}
