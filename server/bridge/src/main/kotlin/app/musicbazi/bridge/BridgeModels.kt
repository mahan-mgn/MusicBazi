package app.musicbazi.bridge

import kotlinx.serialization.Serializable

@Serializable
data class ResolveRequest(
    val request_id: String = "",
    val video_id: String,
    val purpose: String = "playback",
    val quality: String? = null,
    val refresh_visitor: Boolean = false
)

@Serializable
data class VisitorRefreshResponse(
    val ok: Boolean = true,
    val refreshed: Boolean = false
)

@Serializable
data class PlaybackRefusalRequest(
    val video_id: String,
    val status_code: Int,
    val client_name: String? = null,
    val profile_id: String? = null,
    val url: String? = null
)

@Serializable
data class RefusalResponse(
    val ok: Boolean = true,
    val handled: Boolean = true
)

@Serializable
data class BridgeResolvedStream(
    val source: String = "youtube",
    val video_id: String,
    val url: String,
    val mime_type: String,
    val codec: String,
    val bitrate: Int? = null,
    val sample_rate: Int? = null,
    val channels: Int? = null,
    val content_length: Long? = null,
    val expires_at: Long? = null,
    val duration: Double? = null,
    val headers: Map<String, String> = emptyMap(),
    val requires_range: Boolean = false,
    val resolver_metadata: Map<String, String> = emptyMap(),
    val is_lossless: Boolean = false,
    val bit_depth: Int? = null,
    val loudness_db: Double? = null,
    val stream_type: String = "PROGRESSIVE"
)

@Serializable
data class ResolveSuccessResponse(
    val ok: Boolean = true,
    val request_id: String = "",
    val resolver: String = "innertubex",
    val stream: BridgeResolvedStream
)

@Serializable
data class BridgeError(
    val code: String,
    val message: String,
    val retryable: Boolean = false
)

@Serializable
data class ResolveErrorResponse(
    val ok: Boolean = false,
    val request_id: String = "",
    val resolver: String = "innertubex",
    val error: BridgeError
)

@Serializable
data class HealthResponse(
    val ok: Boolean = true,
    val service: String = "musicbazi-innertubex",
    val ready: Boolean = true,
    val version: String = "v0.7.4",
    val has_visitor_data: Boolean = false
)
