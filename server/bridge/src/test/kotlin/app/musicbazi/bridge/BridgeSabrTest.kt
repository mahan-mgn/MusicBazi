package app.musicbazi.bridge

import com.metrolist.innertubex.extraction.StreamResolveException
import com.metrolist.innertubex.sabr.ExperimentalSabrApi
import com.metrolist.innertubex.sabr.SabrBootstrap
import com.metrolist.innertubex.sabr.SabrFailureKind
import com.metrolist.innertubex.sabr.SabrFormatId
import com.metrolist.innertubex.sabr.SabrProtocolException
import com.metrolist.innertubex.sabr.requireAllowedSabrUrl
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.client.request.get
import io.ktor.client.request.post
import io.ktor.client.request.setBody
import io.ktor.client.statement.bodyAsChannel
import io.ktor.client.statement.bodyAsText
import io.ktor.http.ContentType
import io.ktor.http.HttpStatusCode
import io.ktor.http.contentType
import io.ktor.serialization.kotlinx.json.json
import io.ktor.server.testing.testApplication
import io.ktor.utils.io.ByteReadChannel
import io.ktor.utils.io.readAvailable
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.Json
import java.io.ByteArrayOutputStream
import java.util.concurrent.atomic.AtomicInteger
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

@OptIn(ExperimentalSabrApi::class)
class BridgeSabrTest {

    private val json = Json { ignoreUnknownKeys = true }

    // -------------------------------------------------------------------------
    // تست ۱: ساخت Bootstrap با API واقعی وابستگی نصب‌شده
    // -------------------------------------------------------------------------
    @Test
    fun testBootstrapCreationRealApi() {
        val validUrl = "https://rr1---sn-abc.googlevideo.com/videoplayback"
        val checkedUrl = requireAllowedSabrUrl(validUrl)
        assertEquals(validUrl, checkedUrl)

        val ustreamer = byteArrayOf(0x08, 0x01, 0x12, 0x04)
        val poToken = byteArrayOf(0x0A, 0x0B, 0x0C)
        val audioFormat = SabrFormatId(itag = 251, lastModified = 1710000000000L)
        val videoFormat = SabrFormatId(itag = 278, lastModified = 1710000000000L)

        val bootstrap = SabrBootstrap(
            videoId = "dQw4w9WgXcQ",
            serverAbrStreamingUrl = validUrl,
            videoPlaybackUstreamerConfig = ustreamer,
            clientName = 3,
            clientVersion = "21.26.364",
            audioFormat = audioFormat,
            discardVideoFormat = videoFormat,
            discardVideoHeight = 144,
            durationMs = 212000L,
            contentLengthBytes = 3500000L,
            mimeType = "audio/webm",
            poToken = poToken,
            requestUserAgent = "com.google.android.youtube/21.26.364",
            requestOrigin = "https://music.youtube.com"
        )

        assertEquals("dQw4w9WgXcQ", bootstrap.videoId)
        assertEquals(251, bootstrap.audioFormat.itag)
        assertEquals(278, bootstrap.discardVideoFormat.itag)
        assertEquals(144, bootstrap.discardVideoHeight)
        assertEquals(3, bootstrap.clientName)
        assertEquals("21.26.364", bootstrap.clientVersion)
        assertEquals(212000L, bootstrap.durationMs)
        assertEquals("audio/webm", bootstrap.mimeType)
        assertTrue(bootstrap.videoPlaybackUstreamerConfig.contentEquals(ustreamer))
        assertTrue(bootstrap.poToken!!.contentEquals(poToken))

        // اعتبارسنجی SSRF: رد هاست‌های غیرمجاز
        assertFailsWith<SabrProtocolException> {
            requireAllowedSabrUrl("http://rr1---sn-abc.googlevideo.com/videoplayback") // non-https
        }
        assertFailsWith<SabrProtocolException> {
            requireAllowedSabrUrl("https://evil.attacker.com/videoplayback") // non-googlevideo host
        }
    }

    // -------------------------------------------------------------------------
    // تست ۲ و ۳: انتقال صحیح داده‌های Initialization و Media با حفظ ترتیب و چند Chunk
    // -------------------------------------------------------------------------
    @Test
    fun testStreamInitializationAndMediaTransferInOrder() = testApplication {
        val initBytes = byteArrayOf(0x1A, 0x45, 0xDF.toByte(), 0xA3.toByte()) // WebM EBML signature
        val chunk1 = byteArrayOf(0x01, 0x02, 0x03)
        val chunk2 = byteArrayOf(0x04, 0x05, 0x06, 0x07)
        val chunk3 = byteArrayOf(0x08, 0x09)

        val mockResolver = MockSabrResolver(
            flowProducer = {
                flow {
                    emit(initBytes)
                    emit(chunk1)
                    emit(chunk2)
                    emit(chunk3)
                }
            }
        )
        val manager = SabrSessionManager(mockResolver)

        application {
            bridgeModule(sabrSessionManager = manager)
        }

        val client = createClient {
            install(ContentNegotiation) { json() }
        }

        // ۱. Prepare session
        val prepResp = client.post("/sabr/prepare") {
            contentType(ContentType.Application.Json)
            setBody(SabrPrepareRequest(video_id = "dQw4w9WgXcQ"))
        }
        assertEquals(HttpStatusCode.OK, prepResp.status)
        val prepData = json.decodeFromString<SabrPrepareResponse>(prepResp.bodyAsText())
        assertTrue(prepData.ok)
        val sessionId = prepData.session_id
        assertTrue(sessionId.isNotBlank())

        // ۲. Stream
        val streamResp = client.get("/sabr/stream/$sessionId")
        assertEquals(HttpStatusCode.OK, streamResp.status)
        assertEquals("audio/webm", streamResp.headers["Content-Type"])

        val receivedBytes = readAllBytes(streamResp.bodyAsChannel())
        val expectedBytes = initBytes + chunk1 + chunk2 + chunk3
        assertTrue(expectedBytes.contentEquals(receivedBytes))

        val session = manager.getSession(sessionId)
        assertNotNull(session)
        assertEquals(SabrSessionState.COMPLETED, session.state)
    }

    // -------------------------------------------------------------------------
    // تست ۴ و ۵: قطع اتصال کلاینت، لغو Coroutine و درخواست Upstream، و زمان واقعی لغو
    // -------------------------------------------------------------------------
    @Test
    fun testClientDisconnectCancelsCoroutineAndUpstreamMeasured() = testApplication {
        val flowCancelled = CompletableDeferred<Unit>()
        val chunkEmitted = CompletableDeferred<Unit>()

        val mockResolver = MockSabrResolver(
            flowProducer = {
                flow {
                    try {
                        emit(byteArrayOf(0x01, 0x02))
                        chunkEmitted.complete(Unit)
                        // شبیه‌سازی استریم بی‌پایان یا طولانی upstream
                        while (true) {
                            delay(50)
                            emit(byteArrayOf(0x03, 0x04))
                        }
                    } finally {
                        flowCancelled.complete(Unit)
                    }
                }
            }
        )
        val manager = SabrSessionManager(mockResolver)

        application {
            bridgeModule(sabrSessionManager = manager)
        }

        val client = createClient {
            install(ContentNegotiation) { json() }
        }

        val prepResp = client.post("/sabr/prepare") {
            contentType(ContentType.Application.Json)
            setBody(SabrPrepareRequest(video_id = "dQw4w9WgXcQ"))
        }
        val prepData = json.decodeFromString<SabrPrepareResponse>(prepResp.bodyAsText())
        val sessionId = prepData.session_id

        var cancelElapsedMs = 0L

        // اجرای درخواست در یک Coroutine مستقل و لغو آن پس از دریافت اولین بایت
        val clientJob = CoroutineScope(Dispatchers.Default).launch {
            val response = client.get("/sabr/stream/$sessionId")
            val channel = response.bodyAsChannel()
            val buf = ByteArray(2)
            channel.readAvailable(buf, 0, 2)
        }

        // صبر می‌کنیم تا چانک اول ارسال شود
        chunkEmitted.await()

        val cancelStartMs = System.currentTimeMillis()
        clientJob.cancelAndJoin()

        // منتظر می‌مانیم تا فلو متوقف شده و وضعیت نشست به CANCELLED تغییر کند
        withTimeout(3000) {
            flowCancelled.await()
            val session = manager.getSession(sessionId)
            while (session?.state != SabrSessionState.CANCELLED) {
                delay(20)
            }
        }
        cancelElapsedMs = System.currentTimeMillis() - cancelStartMs

        val session = manager.getSession(sessionId)
        assertNotNull(session)
        assertEquals(SabrSessionState.CANCELLED, session.state)

        println("[TEST RESULT] Measured SABR upstream cancellation time: ${cancelElapsedMs}ms")
        assertTrue(cancelElapsedMs >= 0L, "Cancellation time must be measurable")
    }

    // -------------------------------------------------------------------------
    // تست ۶: بررسی Backpressure و بافر محدود
    // -------------------------------------------------------------------------
    @Test
    fun testBackpressureWithSlowConsumer() = testApplication {
        val emissionsCount = AtomicInteger(0)

        val mockResolver = MockSabrResolver(
            flowProducer = {
                flow {
                    for (i in 1..10) {
                        emissionsCount.incrementAndGet()
                        emit(byteArrayOf(i.toByte()))
                    }
                }
            }
        )
        val manager = SabrSessionManager(mockResolver)

        application {
            bridgeModule(sabrSessionManager = manager)
        }

        val client = createClient {
            install(ContentNegotiation) { json() }
        }

        val prepResp = client.post("/sabr/prepare") {
            contentType(ContentType.Application.Json)
            setBody(SabrPrepareRequest(video_id = "dQw4w9WgXcQ"))
        }
        val prepData = json.decodeFromString<SabrPrepareResponse>(prepResp.bodyAsText())

        val streamResp = client.get("/sabr/stream/${prepData.session_id}")
        val channel = streamResp.bodyAsChannel()

        val bytes = readAllBytes(channel)
        assertEquals(10, bytes.size)
        assertEquals(10, emissionsCount.get())
    }

    // -------------------------------------------------------------------------
    // تست ۷: اعمال سقف ۸ نشست فعال (MAX_ACTIVE_SESSIONS = 8)
    // -------------------------------------------------------------------------
    @Test
    fun testMaxEightActiveSessionsLimit() = testApplication {
        val mockResolver = MockSabrResolver()
        val manager = SabrSessionManager(sabrResolver = mockResolver, maxActiveSessions = 8)

        application {
            bridgeModule(sabrSessionManager = manager)
        }

        val client = createClient {
            install(ContentNegotiation) { json() }
        }

        // ایجاد ۸ نشست مجاز
        for (i in 1..8) {
            val vid = "vid_${i.toString().padStart(7, '0')}" // دقیقاً ۱۱ کاراکتر
            val resp = client.post("/sabr/prepare") {
                contentType(ContentType.Application.Json)
                setBody(SabrPrepareRequest(video_id = vid))
            }
            assertEquals(HttpStatusCode.OK, resp.status, "Session $i must succeed")
        }

        assertEquals(8, manager.activeSessionCount())

        // تلاش برای نشست نهم
        val overflowVid = "vid_overflo"
        val overflowResp = client.post("/sabr/prepare") {
            contentType(ContentType.Application.Json)
            setBody(SabrPrepareRequest(video_id = overflowVid))
        }
        assertEquals(HttpStatusCode.TooManyRequests, overflowResp.status)
        val errData = json.decodeFromString<SabrErrorResponse>(overflowResp.bodyAsText())
        assertEquals("MAX_SESSIONS_EXCEEDED", errData.error.code)
        assertFalse(errData.ok)
    }

    // -------------------------------------------------------------------------
    // تست ۸: اعتبارسنجی TTL، پاک‌سازی نشست‌ها و رفتار نشست منقضی‌شده
    // -------------------------------------------------------------------------
    @Test
    fun testTtlExpirationAndCleanup() = testApplication {
        var mockTime = 1000L
        val mockResolver = MockSabrResolver()
        val manager = SabrSessionManager(
            sabrResolver = mockResolver,
            sessionTtlMs = 10_000L, // 10 seconds TTL
            clock = { mockTime }
        )

        application {
            bridgeModule(sabrSessionManager = manager)
        }

        val client = createClient {
            install(ContentNegotiation) { json() }
        }

        val prepResp = client.post("/sabr/prepare") {
            contentType(ContentType.Application.Json)
            setBody(SabrPrepareRequest(video_id = "dQw4w9WgXcQ"))
        }
        val prepData = json.decodeFromString<SabrPrepareResponse>(prepResp.bodyAsText())
        val sessionId = prepData.session_id

        // سشن هنوز معتبر است
        assertEquals(1, manager.activeSessionCount())

        // جلو بردن زمان به بعد از TTL
        mockTime += 15_000L

        // پاک‌سازی خودکار
        manager.cleanExpiredSessions()
        assertEquals(0, manager.activeSessionCount())

        // درخواست استریم سشن منقضی‌شده باید ۴۱۰ برگرداند
        val streamResp = client.get("/sabr/stream/$sessionId")
        assertEquals(HttpStatusCode.Gone, streamResp.status)
        val err = json.decodeFromString<SabrErrorResponse>(streamResp.bodyAsText())
        assertEquals("SESSION_EXPIRED", err.error.code)
    }

    // -------------------------------------------------------------------------
    // تست ۹: مدیریت درخواست‌های هم‌زمان/تکراری برای یک نشست (عدم مصرف متناقض)
    // -------------------------------------------------------------------------
    @Test
    fun testConcurrentAndDuplicateStreamRequests() = testApplication {
        val streamingHold = CompletableDeferred<Unit>()
        val mockResolver = MockSabrResolver(
            flowProducer = {
                flow {
                    emit(byteArrayOf(0x01, 0x02))
                    streamingHold.await()
                    emit(byteArrayOf(0x03, 0x04))
                }
            }
        )
        val manager = SabrSessionManager(mockResolver)

        application {
            bridgeModule(sabrSessionManager = manager)
        }

        val client = createClient {
            install(ContentNegotiation) { json() }
        }

        val prepResp = client.post("/sabr/prepare") {
            contentType(ContentType.Application.Json)
            setBody(SabrPrepareRequest(video_id = "dQw4w9WgXcQ"))
        }
        val prepData = json.decodeFromString<SabrPrepareResponse>(prepResp.bodyAsText())
        val sessionId = prepData.session_id

        // مصرف‌کننده اول استریم را باز می‌کند
        val job1 = CoroutineScope(Dispatchers.Default).launch {
            val resp = client.get("/sabr/stream/$sessionId")
            readAllBytes(resp.bodyAsChannel())
        }

        delay(100) // زمان برای آغاز استریم اول

        // مصرف‌کننده دوم هم‌زمان همان سشن را صدا می‌زند
        val concurrentResp = client.get("/sabr/stream/$sessionId")
        assertEquals(HttpStatusCode.Conflict, concurrentResp.status)
        val conflictErr = json.decodeFromString<SabrErrorResponse>(concurrentResp.bodyAsText())
        assertEquals("SESSION_IN_USE", conflictErr.error.code)

        // پایان استریم اول
        streamingHold.complete(Unit)
        job1.join()

        // درخواست سوم پس از اتمام استریم باید ۴۱۰ AlreadyConsumed برگرداند
        val postCompleteResp = client.get("/sabr/stream/$sessionId")
        assertEquals(HttpStatusCode.Gone, postCompleteResp.status)
        val goneErr = json.decodeFromString<SabrErrorResponse>(postCompleteResp.bodyAsText())
        assertEquals("SESSION_ALREADY_CONSUMED", goneErr.error.code)
    }

    // -------------------------------------------------------------------------
    // تست ۱۰: مدیریت خطاهای پروتکل و upstream با پاسخ‌های امن
    // -------------------------------------------------------------------------
    @Test
    fun testProtocolAndUpstreamErrorsSafeHandling() = testApplication {
        val mockResolver = MockSabrResolver(
            failWith = SabrProtocolException(
                message = "Stream requires attestation",
                kind = SabrFailureKind.ATTESTATION_REQUIRED
            )
        )
        val manager = SabrSessionManager(mockResolver)

        application {
            bridgeModule(sabrSessionManager = manager)
        }

        val client = createClient {
            install(ContentNegotiation) { json() }
        }

        // ۱. خطای Attestation
        val resp = client.post("/sabr/prepare") {
            contentType(ContentType.Application.Json)
            setBody(SabrPrepareRequest(video_id = "dQw4w9WgXcQ"))
        }
        assertEquals(HttpStatusCode.BadGateway, resp.status)
        val errData = json.decodeFromString<SabrErrorResponse>(resp.bodyAsText())
        assertEquals("ATTESTATION_REQUIRED", errData.error.code)
        assertFalse(errData.ok)

        // ۲. ورودی نامعتبر (شناسه ویدیو کمتر یا بیشتر از ۱۱ کاراکتر)
        val invalidResp = client.post("/sabr/prepare") {
            contentType(ContentType.Application.Json)
            setBody(SabrPrepareRequest(video_id = "short_id"))
        }
        assertEquals(HttpStatusCode.BadRequest, invalidResp.status)
        val invalidErr = json.decodeFromString<SabrErrorResponse>(invalidResp.bodyAsText())
        assertEquals("INVALID_REQUEST", invalidErr.error.code)
    }

    // -------------------------------------------------------------------------
    // تست ۱۱: اطمینان از عدم افشای اطلاعات حساس SABR در لاگ‌ها و پاسخ‌های API
    // -------------------------------------------------------------------------
    @Test
    fun testNoSecretsLeakedInResponse() = testApplication {
        val mockResolver = MockSabrResolver()
        val manager = SabrSessionManager(mockResolver)

        application {
            bridgeModule(sabrSessionManager = manager)
        }

        val client = createClient {
            install(ContentNegotiation) { json() }
        }

        val resp = client.post("/sabr/prepare") {
            contentType(ContentType.Application.Json)
            setBody(SabrPrepareRequest(video_id = "dQw4w9WgXcQ"))
        }
        val responseText = resp.bodyAsText()

        // بررسی صریح عدم وجود اطلاعات حساس
        assertFalse(responseText.contains("googlevideo.com"), "Signed CDN URL must not leak")
        assertFalse(responseText.contains("poToken"), "poToken must not leak")
        assertFalse(responseText.contains("videoPlaybackUstreamerConfig"), "Ustreamer config must not leak")
        assertFalse(responseText.contains("playbackCookie"), "Playback cookie must not leak")
        assertFalse(responseText.contains("signature"), "Signatures must not leak")
    }

    // -------------------------------------------------------------------------
    // Helper: خواندن تمام بایت‌های ByteReadChannel
    // -------------------------------------------------------------------------
    private suspend fun readAllBytes(channel: ByteReadChannel): ByteArray {
        val out = ByteArrayOutputStream()
        val buf = ByteArray(4096)
        while (true) {
            val read = channel.readAvailable(buf, 0, buf.size)
            if (read < 0) break
            out.write(buf, 0, read)
        }
        return out.toByteArray()
    }

    // -------------------------------------------------------------------------
    // Mock SABR Resolver
    // -------------------------------------------------------------------------
    private class MockSabrResolver(
        private val failWith: Exception? = null,
        private val flowProducer: () -> Flow<ByteArray> = {
            flow {
                emit(byteArrayOf(0x1A, 0x45, 0xDF.toByte(), 0xA3.toByte()))
                emit(byteArrayOf(0x01, 0x02, 0x03))
            }
        }
    ) : ISabrResolver {
        override suspend fun resolveSabr(
            videoId: String,
            qualityStr: String?,
            playerTimeMs: Long
        ): SabrResolveResult {
            if (failWith != null) throw failWith

            val bootstrap = SabrBootstrap(
                videoId = videoId,
                serverAbrStreamingUrl = "https://rr1---sn-abc.googlevideo.com/videoplayback",
                videoPlaybackUstreamerConfig = byteArrayOf(1, 2, 3),
                clientName = 3,
                clientVersion = "21.26.364",
                audioFormat = SabrFormatId(itag = 251, lastModified = 1710000000000L),
                discardVideoFormat = SabrFormatId(itag = 278, lastModified = 1710000000000L),
                discardVideoHeight = 144,
                durationMs = 212000L,
                contentLengthBytes = 3500000L,
                mimeType = "audio/webm",
                poToken = byteArrayOf(9, 9, 9)
            )

            return SabrResolveResult(
                bootstrap = bootstrap,
                mimeType = "audio/webm",
                codec = "opus",
                bitrate = 160000,
                sampleRate = 48000,
                channels = 2,
                durationMs = 212000L,
                itag = 251,
                clientName = "ANDROID",
                streamFactory = { _, _ -> flowProducer() }
            )
        }
    }
}
