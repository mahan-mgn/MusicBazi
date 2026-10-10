package app.musicbazi.bridge

import com.metrolist.innertubex.sabr.ExperimentalSabrApi
import com.metrolist.innertubex.sabr.SabrBootstrap
import io.ktor.http.HttpStatusCode
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.Flow
import kotlinx.serialization.Serializable
import java.util.concurrent.atomic.AtomicReference

@Serializable
data class SabrPrepareRequest(
    val video_id: String,
    val quality: String? = null,
    val player_time_ms: Long = 0L
)

@Serializable
data class SabrPrepareResponse(
    val ok: Boolean = true,
    val session_id: String,
    val video_id: String,
    val mime_type: String,
    val codec: String,
    val duration_ms: Long? = null,
    val bitrate: Int? = null,
    val sample_rate: Int? = null,
    val channels: Int? = null,
    val itag: Int? = null,
    val client_name: String? = null
)

@Serializable
data class SabrErrorResponse(
    val ok: Boolean = false,
    val error: BridgeError
)

enum class SabrSessionState {
    PREPARED,
    STREAMING,
    COMPLETED,
    CANCELLED,
    FAILED,
    EXPIRED
}

sealed class SabrSessionError(
    val httpStatusCode: HttpStatusCode,
    val code: String,
    override val message: String
) : Exception(message) {
    class InvalidRequest(message: String) : SabrSessionError(HttpStatusCode.BadRequest, "INVALID_REQUEST", message)
    class LimitExceeded(message: String) : SabrSessionError(HttpStatusCode.TooManyRequests, "MAX_SESSIONS_EXCEEDED", message)
    class NotFound(message: String) : SabrSessionError(HttpStatusCode.NotFound, "SESSION_NOT_FOUND", message)
    class Expired(message: String) : SabrSessionError(HttpStatusCode.Gone, "SESSION_EXPIRED", message)
    class InUse(message: String) : SabrSessionError(HttpStatusCode.Conflict, "SESSION_IN_USE", message)
    class AlreadyConsumed(message: String) : SabrSessionError(HttpStatusCode.Gone, "SESSION_ALREADY_CONSUMED", message)
}

/**
 * Isolated session model encapsulating SABR transport metadata and byte flow supplier.
 * Internal credentials, signed URLs, and bootstrap payloads are intentionally kept private.
 */
class SabrSession(
    val id: String,
    val videoId: String,
    val mimeType: String,
    val codec: String,
    val durationMs: Long?,
    val bitrate: Int?,
    val sampleRate: Int?,
    val channels: Int?,
    val itag: Int?,
    val clientName: String?,
    val createdAtEpochMs: Long,
    val expiresAtEpochMs: Long,
    private val streamSupplier: suspend () -> Flow<ByteArray>,
) {
    private val _state = AtomicReference(SabrSessionState.PREPARED)
    val state: SabrSessionState get() = _state.get()

    private val _activeJob = AtomicReference<Job?>(null)
    val activeJob: Job? get() = _activeJob.get()

    fun tryStartStreaming(job: Job?): Boolean {
        if (_state.compareAndSet(SabrSessionState.PREPARED, SabrSessionState.STREAMING)) {
            _activeJob.set(job)
            return true
        }
        return false
    }

    fun markCompleted() {
        _state.set(SabrSessionState.COMPLETED)
        _activeJob.set(null)
    }

    fun markCancelled() {
        _state.set(SabrSessionState.CANCELLED)
        _activeJob.set(null)
    }

    fun markFailed() {
        _state.set(SabrSessionState.FAILED)
        _activeJob.set(null)
    }

    fun markExpired() {
        _state.set(SabrSessionState.EXPIRED)
        _activeJob.set(null)
    }

    suspend fun openStream(): Flow<ByteArray> = streamSupplier()
}

@OptIn(ExperimentalSabrApi::class)
data class SabrResolveResult(
    val bootstrap: SabrBootstrap,
    val mimeType: String,
    val codec: String,
    val bitrate: Int? = null,
    val sampleRate: Int? = null,
    val channels: Int? = 2,
    val durationMs: Long? = null,
    val itag: Int? = null,
    val clientName: String? = null,
    val streamFactory: (SabrBootstrap, Long) -> Flow<ByteArray>
)

interface ISabrResolver {
    suspend fun resolveSabr(
        videoId: String,
        qualityStr: String? = null,
        playerTimeMs: Long = 0L
    ): SabrResolveResult
}

object NoOpSabrResolver : ISabrResolver {
    override suspend fun resolveSabr(
        videoId: String,
        qualityStr: String?,
        playerTimeMs: Long
    ): SabrResolveResult {
        throw SabrSessionError.NotFound("SABR resolution not available on this resolver")
    }
}
