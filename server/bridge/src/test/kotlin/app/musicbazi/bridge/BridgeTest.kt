package app.musicbazi.bridge

import com.metrolist.innertubex.extraction.StreamResolveException
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.client.request.get
import io.ktor.client.request.post
import io.ktor.client.request.setBody
import io.ktor.client.statement.bodyAsText
import io.ktor.http.ContentType
import io.ktor.http.HttpStatusCode
import io.ktor.http.contentType
import io.ktor.serialization.kotlinx.json.json
import io.ktor.server.testing.testApplication
import kotlinx.serialization.json.Json
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class BridgeTest {

    private val json = Json { ignoreUnknownKeys = true }

    @Test
    fun testHealthEndpoint() = testApplication {
        application {
            bridgeModule(MockResolver())
        }

        val client = createClient {
            install(ContentNegotiation) { json() }
        }

        val response = client.get("/health")
        assertEquals(HttpStatusCode.OK, response.status)

        val health = json.decodeFromString<HealthResponse>(response.bodyAsText())
        assertTrue(health.ok)
        assertEquals("musicbazi-innertubex", health.service)
        assertTrue(health.ready)
        assertEquals("v0.7.4", health.version)
    }

    @Test
    fun testResolveMissingVideoId() = testApplication {
        application {
            bridgeModule(MockResolver())
        }

        val client = createClient {
            install(ContentNegotiation) { json() }
        }

        val response = client.post("/resolve") {
            contentType(ContentType.Application.Json)
            setBody(ResolveRequest(video_id = ""))
        }

        assertEquals(HttpStatusCode.BadRequest, response.status)
        val err = json.decodeFromString<ResolveErrorResponse>(response.bodyAsText())
        assertEquals("INVALID_REQUEST", err.error.code)
    }

    @Test
    fun testResolveSuccessful() = testApplication {
        val mock = MockResolver()
        application {
            bridgeModule(mock)
        }

        val client = createClient {
            install(ContentNegotiation) { json() }
        }

        val response = client.post("/resolve") {
            contentType(ContentType.Application.Json)
            setBody(ResolveRequest(request_id = "req-1", video_id = "valid_vid"))
        }

        assertEquals(HttpStatusCode.OK, response.status)
        val res = json.decodeFromString<ResolveSuccessResponse>(response.bodyAsText())
        assertTrue(res.ok)
        assertEquals("req-1", res.request_id)
        assertEquals("innertubex", res.resolver)
        assertEquals("valid_vid", res.stream.video_id)
        assertEquals("audio/webm", res.stream.mime_type)
        assertEquals("opus", res.stream.codec)
        assertEquals(160000, res.stream.bitrate)
        assertEquals("PROGRESSIVE", res.stream.stream_type)
    }

    @Test
    fun testResolveNoPlayableStream() = testApplication {
        val mock = MockResolver(failWith = StreamResolveException(
            reason = StreamResolveException.Reason.NO_PLAYABLE_STREAM,
            message = "No stream available"
        ))
        application {
            bridgeModule(mock)
        }

        val client = createClient {
            install(ContentNegotiation) { json() }
        }

        val response = client.post("/resolve") {
            contentType(ContentType.Application.Json)
            setBody(ResolveRequest(video_id = "unplayable_vid"))
        }

        assertEquals(HttpStatusCode.UnprocessableEntity, response.status)
        val err = json.decodeFromString<ResolveErrorResponse>(response.bodyAsText())
        assertEquals("NO_STREAM", err.error.code)
    }

    @Test
    fun testResolveAgeRestricted() = testApplication {
        val mock = MockResolver(failWith = StreamResolveException(
            reason = StreamResolveException.Reason.AGE_RESTRICTED,
            message = "Track is age restricted"
        ))
        application {
            bridgeModule(mock)
        }

        val client = createClient {
            install(ContentNegotiation) { json() }
        }

        val response = client.post("/resolve") {
            contentType(ContentType.Application.Json)
            setBody(ResolveRequest(video_id = "age_restricted_vid"))
        }

        assertEquals(HttpStatusCode.UnprocessableEntity, response.status)
        val err = json.decodeFromString<ResolveErrorResponse>(response.bodyAsText())
        assertEquals("AGE_RESTRICTED", err.error.code)
    }

    @Test
    fun testResolveNetworkFailure() = testApplication {
        val mock = MockResolver(failWith = IOException("Socket connection reset"))
        application {
            bridgeModule(mock)
        }

        val client = createClient {
            install(ContentNegotiation) { json() }
        }

        val response = client.post("/resolve") {
            contentType(ContentType.Application.Json)
            setBody(ResolveRequest(video_id = "net_fail_vid"))
        }

        assertEquals(HttpStatusCode.BadGateway, response.status)
        val err = json.decodeFromString<ResolveErrorResponse>(response.bodyAsText())
        assertEquals("NETWORK_ERROR", err.error.code)
        assertTrue(err.error.retryable)
    }

    @Test
    fun testResolveWithRefreshVisitorFlag() = testApplication {
        val mock = MockResolver()
        application {
            bridgeModule(mock)
        }

        val client = createClient {
            install(ContentNegotiation) { json() }
        }

        val response = client.post("/resolve") {
            contentType(ContentType.Application.Json)
            setBody(ResolveRequest(request_id = "req-refresh", video_id = "vid_refresh", refresh_visitor = true))
        }

        assertEquals(HttpStatusCode.OK, response.status)
        assertTrue(mock.lastRefreshVisitor, "فلگ refresh_visitor باید به resolver منتقل شود")
    }

    @Test
    fun testVisitorRefreshEndpoint() = testApplication {
        application {
            bridgeModule(MockResolver())
        }

        val client = createClient {
            install(ContentNegotiation) { json() }
        }

        val response = client.post("/visitor/refresh")
        assertEquals(HttpStatusCode.OK, response.status)
        val res = json.decodeFromString<VisitorRefreshResponse>(response.bodyAsText())
        assertTrue(res.ok)
    }

    @Test
    fun testRefuseEndpoint() = testApplication {
        application {
            bridgeModule(MockResolver())
        }

        val client = createClient {
            install(ContentNegotiation) { json() }
        }

        val response = client.post("/refuse") {
            contentType(ContentType.Application.Json)
            setBody(PlaybackRefusalRequest(video_id = "test_vid", status_code = 403, client_name = "WEB_REMIX"))
        }

        assertEquals(HttpStatusCode.OK, response.status)
        val res = json.decodeFromString<RefusalResponse>(response.bodyAsText())
        assertTrue(res.ok)
    }

    @Test
    fun testSessionChangedEndpoint() = testApplication {
        application {
            bridgeModule(MockResolver())
        }

        val client = createClient {
            install(ContentNegotiation) { json() }
        }

        val response = client.post("/session/changed")
        assertEquals(HttpStatusCode.OK, response.status)
    }

    private class MockResolver(
        private val failWith: Exception? = null
    ) : IInnerTubeResolver {
        var lastRefreshVisitor: Boolean = false

        override suspend fun resolve(
            videoId: String,
            purpose: String,
            qualityStr: String?,
            refreshVisitor: Boolean,
        ): BridgeResolvedStream {
            lastRefreshVisitor = refreshVisitor
            if (failWith != null) throw failWith
            return BridgeResolvedStream(
                source = "youtube",
                video_id = videoId,
                url = "https://rr1---sn-abc.googlevideo.com/videoplayback?id=$videoId&expire=1795000000",
                mime_type = "audio/webm",
                codec = "opus",
                bitrate = 160000,
                sample_rate = 48000,
                channels = 2,
                content_length = 3500000L,
                expires_at = 1795000000L,
                duration = 210.0,
                headers = mapOf("User-Agent" to "Mozilla/5.0"),
                requires_range = false,
                resolver_metadata = mapOf("client_name" to "WEB_REMIX", "itag" to "251"),
                is_lossless = false,
                stream_type = "PROGRESSIVE"
            )
        }
    }
}
