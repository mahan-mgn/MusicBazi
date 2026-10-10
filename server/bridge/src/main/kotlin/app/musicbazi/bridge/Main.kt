package app.musicbazi.bridge

import com.metrolist.innertubex.extraction.StreamResolveException
import com.metrolist.innertubex.sabr.SabrFailureKind
import com.metrolist.innertubex.sabr.SabrProtocolException
import io.ktor.http.ContentType
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.serialization.kotlinx.json.json
import io.ktor.server.application.Application
import io.ktor.server.application.install
import io.ktor.server.cio.CIO
import io.ktor.server.engine.embeddedServer
import io.ktor.server.plugins.contentnegotiation.ContentNegotiation
import io.ktor.server.request.receive
import io.ktor.server.response.header
import io.ktor.server.response.respond
import io.ktor.server.response.respondBytesWriter
import io.ktor.server.routing.get
import io.ktor.server.routing.post
import io.ktor.server.routing.routing
import io.ktor.utils.io.writeFully
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.buffer
import kotlinx.serialization.json.Json
import org.slf4j.LoggerFactory
import java.io.IOException

private val log = LoggerFactory.getLogger("MusicBaziBridge")

fun main(args: Array<String>) {
    val port = System.getenv("MUSICBAZI_INNERTUBEX_PORT")?.toIntOrNull()
        ?: args.firstOrNull()?.toIntOrNull()
        ?: 8765
    val host = System.getenv("MUSICBAZI_INNERTUBEX_HOST") ?: "127.0.0.1"

    log.info("Starting MusicBazi InnerTubeX Bridge on http://$host:$port")
    embeddedServer(CIO, port = port, host = host) {
        bridgeModule()
    }.start(wait = true)
}

fun Application.bridgeModule(
    service: IInnerTubeResolver = InnerTubeService(),
    sabrSessionManager: SabrSessionManager = SabrSessionManager(
        sabrResolver = (service as? ISabrResolver) ?: (service as? InnerTubeService) ?: NoOpSabrResolver
    )
) {
    install(ContentNegotiation) {
        json(Json {
            ignoreUnknownKeys = true
            prettyPrint = false
            encodeDefaults = true
        })
    }

    routing {
        get("/health") {
            val hasVisitor = (service as? InnerTubeService)?.visitorDataManager?.currentVisitorData != null
            call.respond(
                HttpStatusCode.OK,
                HealthResponse(
                    ok = true,
                    service = "musicbazi-innertubex",
                    ready = true,
                    version = "v0.7.4",
                    has_visitor_data = hasVisitor
                )
            )
        }

        post("/visitor/refresh") {
            val manager = (service as? InnerTubeService)?.visitorDataManager
            val fresh = manager?.getVisitorData(refresh = true)
            call.respond(
                HttpStatusCode.OK,
                VisitorRefreshResponse(
                    ok = true,
                    refreshed = !fresh.isNullOrBlank()
                )
            )
        }

        post("/refuse") {
            val req = try {
                call.receive<PlaybackRefusalRequest>()
            } catch (e: Exception) {
                call.respond(
                    HttpStatusCode.BadRequest,
                    RefusalResponse(ok = false, handled = false)
                )
                return@post
            }

            val handled = (service as? InnerTubeService)?.onPlaybackRefused(
                url = req.url,
                videoId = req.video_id,
                statusCode = req.status_code,
                clientName = req.client_name,
                profileId = req.profile_id
            ) ?: false

            call.respond(HttpStatusCode.OK, RefusalResponse(ok = true, handled = handled))
        }

        post("/session/changed") {
            (service as? InnerTubeService)?.onSessionChanged()
            call.respond(HttpStatusCode.OK, mapOf("ok" to true))
        }

        post("/resolve") {
            val req = try {
                call.receive<ResolveRequest>()
            } catch (e: Exception) {
                call.respond(
                    HttpStatusCode.BadRequest,
                    ResolveErrorResponse(
                        ok = false,
                        error = BridgeError(code = "INVALID_REQUEST", message = "Malformed request JSON: ${e.message}", retryable = false)
                    )
                )
                return@post
            }

            if (req.video_id.isBlank()) {
                call.respond(
                    HttpStatusCode.BadRequest,
                    ResolveErrorResponse(
                        ok = false,
                        request_id = req.request_id,
                        error = BridgeError(code = "INVALID_REQUEST", message = "video_id is required", retryable = false)
                    )
                )
                return@post
            }

            log.info("Resolving videoId=${req.video_id} purpose=${req.purpose} reqId=${req.request_id}")
            try {
                val stream = service.resolve(
                    videoId = req.video_id.trim(),
                    purpose = req.purpose,
                    qualityStr = req.quality,
                    refreshVisitor = req.refresh_visitor,
                )
                log.info("Resolved videoId=${req.video_id} client=${stream.resolver_metadata["client_name"]} bitrate=${stream.bitrate} codec=${stream.codec}")
                call.respond(
                    HttpStatusCode.OK,
                    ResolveSuccessResponse(
                        ok = true,
                        request_id = req.request_id,
                        resolver = "innertubex",
                        stream = stream
                    )
                )
            } catch (e: CancellationException) {
                throw e
            } catch (e: StreamResolveException) {
                val code = when (e.reason) {
                    StreamResolveException.Reason.NO_PLAYABLE_STREAM -> "NO_STREAM"
                    StreamResolveException.Reason.UNAVAILABLE -> "UNAVAILABLE"
                    StreamResolveException.Reason.AGE_RESTRICTED -> "AGE_RESTRICTED"
                    StreamResolveException.Reason.EXPLICIT_UNSUPPORTED -> "CLIENT_REJECTED"
                    StreamResolveException.Reason.NETWORK -> "NETWORK_ERROR"
                    else -> "NO_STREAM"
                }
                log.warn("StreamResolveException for videoId=${req.video_id}: code=$code message=${e.message}")
                call.respond(
                    HttpStatusCode.UnprocessableEntity,
                    ResolveErrorResponse(
                        ok = false,
                        request_id = req.request_id,
                        resolver = "innertubex",
                        error = BridgeError(code = code, message = e.message ?: "No playable stream found", retryable = false)
                    )
                )
            } catch (e: IOException) {
                log.warn("Network error during resolution for videoId=${req.video_id}: ${e.message}")
                call.respond(
                    HttpStatusCode.BadGateway,
                    ResolveErrorResponse(
                        ok = false,
                        request_id = req.request_id,
                        resolver = "innertubex",
                        error = BridgeError(code = "NETWORK_ERROR", message = "Upstream YouTube network failure: ${e.message}", retryable = true)
                    )
                )
            } catch (e: Exception) {
                log.error("Unexpected error resolving videoId=${req.video_id}: ${e.javaClass.simpleName}: ${e.message}")
                call.respond(
                    HttpStatusCode.InternalServerError,
                    ResolveErrorResponse(
                        ok = false,
                        request_id = req.request_id,
                        resolver = "innertubex",
                        error = BridgeError(code = "UNKNOWN", message = e.message ?: "Unexpected resolution failure", retryable = false)
                    )
                )
            }
        }

        // --- Phase 17: Standalone SABR Prototype Endpoints ---

        post("/sabr/prepare") {
            val req = try {
                call.receive<SabrPrepareRequest>()
            } catch (e: Exception) {
                call.respond(
                    HttpStatusCode.BadRequest,
                    SabrErrorResponse(error = BridgeError("INVALID_REQUEST", "Malformed request JSON: ${e.message}", retryable = false))
                )
                return@post
            }

            try {
                val res = sabrSessionManager.prepareSession(
                    videoId = req.video_id,
                    quality = req.quality,
                    playerTimeMs = req.player_time_ms
                )
                call.respond(HttpStatusCode.OK, res)
            } catch (e: SabrSessionError) {
                call.respond(
                    e.httpStatusCode,
                    SabrErrorResponse(error = BridgeError(e.code, e.message, retryable = false))
                )
            } catch (e: CancellationException) {
                throw e
            } catch (e: StreamResolveException) {
                val code = when (e.reason) {
                    StreamResolveException.Reason.NO_PLAYABLE_STREAM -> "NO_SABR_STREAM"
                    StreamResolveException.Reason.UNAVAILABLE -> "UNAVAILABLE"
                    StreamResolveException.Reason.AGE_RESTRICTED -> "AGE_RESTRICTED"
                    StreamResolveException.Reason.EXPLICIT_UNSUPPORTED -> "CLIENT_REJECTED"
                    StreamResolveException.Reason.NETWORK -> "NETWORK_ERROR"
                    else -> "NO_SABR_STREAM"
                }
                log.warn("SABR prepare StreamResolveException for videoId=${req.video_id}: code=$code message=${e.message}")
                call.respond(
                    HttpStatusCode.UnprocessableEntity,
                    SabrErrorResponse(error = BridgeError(code, e.message ?: "No playable SABR stream available", retryable = false))
                )
            } catch (e: SabrProtocolException) {
                val code = when (e.kind) {
                    SabrFailureKind.ATTESTATION_REQUIRED -> "ATTESTATION_REQUIRED"
                    SabrFailureKind.RELOAD_PLAYER -> "RELOAD_PLAYER"
                    SabrFailureKind.PROTOCOL -> "PROTOCOL_ERROR"
                }
                log.warn("SABR prepare protocol error for videoId=${req.video_id}: kind=$code")
                call.respond(
                    HttpStatusCode.BadGateway,
                    SabrErrorResponse(error = BridgeError(code, "SABR protocol error: $code", retryable = false))
                )
            } catch (e: IOException) {
                log.warn("SABR prepare network error for videoId=${req.video_id}: ${e.message}")
                call.respond(
                    HttpStatusCode.BadGateway,
                    SabrErrorResponse(error = BridgeError("NETWORK_ERROR", "Upstream YouTube network failure", retryable = true))
                )
            } catch (e: Exception) {
                log.error("Unexpected error in /sabr/prepare: ${e.javaClass.simpleName}: ${e.message}")
                call.respond(
                    HttpStatusCode.InternalServerError,
                    SabrErrorResponse(error = BridgeError("UNKNOWN", "Failed to prepare SABR session", retryable = false))
                )
            }
        }

        get("/sabr/stream/{session_id}") {
            val sessionId = call.parameters["session_id"]
            if (sessionId.isNullOrBlank()) {
                call.respond(
                    HttpStatusCode.BadRequest,
                    SabrErrorResponse(error = BridgeError("INVALID_REQUEST", "session_id is required", retryable = false))
                )
                return@get
            }

            val session = try {
                sabrSessionManager.getSessionForStreaming(sessionId, coroutineContext[Job])
            } catch (e: SabrSessionError) {
                call.respond(
                    e.httpStatusCode,
                    SabrErrorResponse(error = BridgeError(e.code, e.message, retryable = false))
                )
                return@get
            }

            log.info("Starting SABR stream session=$sessionId videoId=${session.videoId}")
            val startMs = System.currentTimeMillis()
            var bytesSent = 0L

            call.response.header(HttpHeaders.CacheControl, "no-cache, no-store, must-revalidate")
            call.response.header("X-Content-Type-Options", "nosniff")

            val rawMime = session.mimeType
            val contentType = try {
                ContentType.parse(rawMime)
            } catch (e: Exception) {
                ContentType.Application.OctetStream
            }

            try {
                call.respondBytesWriter(contentType = contentType, status = HttpStatusCode.OK) {
                    val writeChannel = this
                    try {
                        val flow = session.openStream()
                        flow.buffer(capacity = 4).collect { chunk ->
                            if (chunk.isNotEmpty()) {
                                writeChannel.writeFully(chunk)
                                writeChannel.flush()
                                bytesSent += chunk.size
                            }
                        }
                        session.markCompleted()
                        val duration = System.currentTimeMillis() - startMs
                        log.info("Finished SABR stream session=$sessionId bytesSent=$bytesSent elapsed=${duration}ms")
                    } catch (e: CancellationException) {
                        session.markCancelled()
                        val cancelElapsed = System.currentTimeMillis() - startMs
                        log.info("SABR stream cancelled by client session=$sessionId bytesSent=$bytesSent cancelElapsed=${cancelElapsed}ms")
                        throw e
                    } catch (e: Throwable) {
                        session.markFailed()
                        log.warn("SABR stream error session=$sessionId: ${e.javaClass.simpleName}")
                        throw e
                    }
                }
            } catch (e: CancellationException) {
                session.markCancelled()
                throw e
            } catch (e: Throwable) {
                session.markFailed()
                log.warn("SABR response pipe failed session=$sessionId: ${e.message}")
            }
        }
    }
}

