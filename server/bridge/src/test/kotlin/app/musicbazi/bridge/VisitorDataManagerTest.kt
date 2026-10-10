package app.musicbazi.bridge

import com.metrolist.innertubex.InnerTube
import com.sun.net.httpserver.HttpServer
import io.ktor.client.HttpClient
import io.ktor.client.engine.okhttp.OkHttp
import io.ktor.client.plugins.HttpTimeout
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import java.io.IOException
import java.net.InetSocketAddress
import java.util.concurrent.atomic.AtomicInteger
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class VisitorDataManagerTest {

    private val sampleToken = "Cgt4c1lWN0c5TXlhWSikgqu5BjIKCgJVUxIEGgAgTQ%3D%3D"
    private val sampleToken2 = "CgtvQmV2cFBmZ1lPVSjCg-jDBgIKCgJVUxIEGgAgTQ%3D%3D"

    private fun sampleSwJsData(token: String = sampleToken): String {
        return ")]}'\n[[[\"test\",0,[\"sub\",1,[\"deep\",2,[\"token\",3,0,0,0,0,0,0,0,0,0,0,0,\"$token\"]]]]]]"
    }

    private fun createTestClient(): HttpClient {
        return HttpClient(OkHttp) {
            install(HttpTimeout) {
                requestTimeoutMillis = 5_000
                connectTimeoutMillis = 2_000
                socketTimeoutMillis = 3_000
            }
        }
    }

    // -------------------------------------------------------------------------
    // 1. استخراج (Extraction)
    // -------------------------------------------------------------------------

    @Test
    fun testExtractVisitorDataFromStandardSwJsData() {
        val raw = sampleSwJsData(sampleToken)
        val extracted = VisitorDataManager.extractVisitorData(raw)
        assertEquals(sampleToken, extracted)
    }

    @Test
    fun testExtractVisitorDataWithAlternativeAntiHijackPrefix() {
        val raw = "/*-secure-\n[[\"$sampleToken2\"]]"
        val extracted = VisitorDataManager.extractVisitorData(raw)
        assertEquals(sampleToken2, extracted)
    }

    @Test
    fun testExtractVisitorDataFromRawJson() {
        val raw = "{\"visitorData\": \"$sampleToken\"}"
        val extracted = VisitorDataManager.extractVisitorData(raw)
        assertEquals(sampleToken, extracted)
    }

    @Test
    fun testExtractVisitorDataFallbackRegexOnMalformedJson() {
        val corrupted = ")]}'\n[INVALID_JSON_CONTENT, random text, $sampleToken, trailing text"
        val extracted = VisitorDataManager.extractVisitorData(corrupted)
        assertEquals(sampleToken, extracted)
    }

    // -------------------------------------------------------------------------
    // 2. پاسخ‌های نامعتبر (Invalid Responses) - نباید کرش کند
    // -------------------------------------------------------------------------

    @Test
    fun testExtractVisitorDataEmptyAndBlank() {
        assertNull(VisitorDataManager.extractVisitorData(""))
        assertNull(VisitorDataManager.extractVisitorData("   "))
        assertNull(VisitorDataManager.extractVisitorData("\n\t"))
    }

    @Test
    fun testExtractVisitorDataHtmlOrGarbage() {
        val htmlError = "<html><head><title>404 Not Found</title></head><body>Error</body></html>"
        assertNull(VisitorDataManager.extractVisitorData(htmlError))

        val randomJson = "{\"status\": \"error\", \"message\": \"something went wrong\"}"
        assertNull(VisitorDataManager.extractVisitorData(randomJson))
    }

    // -------------------------------------------------------------------------
    // 3. دریافت از شبکه، کش و تازه‌سازی (Network, Cache, Refresh)
    // -------------------------------------------------------------------------

    @Test
    fun testGetVisitorDataNetworkAndCache() {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        val requestCount = AtomicInteger(0)

        server.createContext("/sw.js_data") { exchange ->
            requestCount.incrementAndGet()
            val body = sampleSwJsData(sampleToken).toByteArray()
            exchange.responseHeaders.set("Content-Type", "application/json")
            exchange.sendResponseHeaders(200, body.size.toLong())
            exchange.responseBody.use { it.write(body) }
        }
        server.start()

        val client = createTestClient()
        val port = server.address.port
        val url = "http://127.0.0.1:$port/sw.js_data"

        try {
            val manager = VisitorDataManager(httpClient = client, endpointUrl = url)

            // درخواست اول: دریافت از سرور
            runBlocking {
                val token1 = manager.getVisitorData(refresh = false)
                assertEquals(sampleToken, token1)
                assertEquals(1, requestCount.get())

                // درخواست دوم بدون refresh: خواندن از کش بدون تماس با سرور
                val token2 = manager.getVisitorData(refresh = false)
                assertEquals(sampleToken, token2)
                assertEquals(1, requestCount.get(), "درخواست دوم باید از کش پاسخ داده شود")

                // درخواست سوم با refresh: تماس مجدد با سرور
                val token3 = manager.getVisitorData(refresh = true)
                assertEquals(sampleToken, token3)
                assertEquals(2, requestCount.get(), "درخواست با refresh باید شبکه را فراخوانی کند")
            }
        } finally {
            server.stop(0)
            client.close()
        }
    }

    // -------------------------------------------------------------------------
    // 4. خطای شبکه و پاسخ خطادار سرور (Network Error Handling)
    // -------------------------------------------------------------------------

    @Test
    fun testNetworkHttp500DoesNotCrash() {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/sw.js_data") { exchange ->
            exchange.sendResponseHeaders(500, -1)
            exchange.close()
        }
        server.start()

        val client = createTestClient()
        val port = server.address.port
        val url = "http://127.0.0.1:$port/sw.js_data"

        try {
            val manager = VisitorDataManager(httpClient = client, endpointUrl = url)
            runBlocking {
                val result = manager.getVisitorData(refresh = false)
                assertNull(result, "در خطای 500 باید null برگردد بدون کرش")
            }
        } finally {
            server.stop(0)
            client.close()
        }
    }

    @Test
    fun testServerUnreachableDoesNotCrash() {
        val client = createTestClient()
        // آدرس سرور ناموجود
        val url = "http://127.0.0.1:59999/sw.js_data"

        val manager = VisitorDataManager(httpClient = client, endpointUrl = url)
        runBlocking {
            val result = manager.getVisitorData(refresh = false)
            assertNull(result, "در صورت در دسترس نبودن سرور باید null برگردد بدون کرش")
        }
        client.close()
    }

    // -------------------------------------------------------------------------
    // 5. تزریق به نمونه InnerTube (Injection)
    // -------------------------------------------------------------------------

    @Test
    fun testEnsureInjectedAsyncSetsInnerTubeVisitorData() {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/sw.js_data") { exchange ->
            val body = sampleSwJsData(sampleToken).toByteArray()
            exchange.sendResponseHeaders(200, body.size.toLong())
            exchange.responseBody.use { it.write(body) }
        }
        server.start()

        val client = createTestClient()
        val port = server.address.port
        val url = "http://127.0.0.1:$port/sw.js_data"

        try {
            val manager = VisitorDataManager(httpClient = client, endpointUrl = url)
            val innerTube = InnerTube(client)

            runBlocking {
                assertNull(innerTube.visitorData)
                val token = manager.ensureInjectedAsync(innerTube, refresh = false)
                assertEquals(sampleToken, token)
                assertEquals(sampleToken, innerTube.visitorData, "توکن باید در session نمونه InnerTube ثبت شود")
            }
        } finally {
            server.stop(0)
            client.close()
        }
    }

    // -------------------------------------------------------------------------
    // 6. همروندی Single-Flight (Concurrent Requests)
    // -------------------------------------------------------------------------

    @Test
    fun testConcurrentRequestsExecuteSingleFlight() {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        val requestCount = AtomicInteger(0)

        server.createContext("/sw.js_data") { exchange ->
            requestCount.incrementAndGet()
            Thread.sleep(50) // تاخیر عمدی برای ایجاد تداخل همروندی
            val body = sampleSwJsData(sampleToken).toByteArray()
            exchange.sendResponseHeaders(200, body.size.toLong())
            exchange.responseBody.use { it.write(body) }
        }
        server.start()

        val client = createTestClient()
        val port = server.address.port
        val url = "http://127.0.0.1:$port/sw.js_data"

        try {
            val manager = VisitorDataManager(httpClient = client, endpointUrl = url)

            runBlocking {
                // ۲۰ درخواست هم‌زمان برای دریافت توکن در حالت کش خالی
                val jobs = (1..20).map {
                    async {
                        manager.getVisitorData(refresh = false)
                    }
                }
                val results = jobs.awaitAll()

                // همه باید مقدار صحیح را دریافت کرده باشند
                for (res in results) {
                    assertEquals(sampleToken, res)
                }

                // با وجود ۲۰ درخواست هم‌زمان، دقیقاً ۱ درخواست شبکه باید انجام شده باشد
                assertEquals(1, requestCount.get(), "درخواست‌های هم‌زمان باید با Single-Flight تجمیع شوند")
            }
        } finally {
            server.stop(0)
            client.close()
        }
    }

    // -------------------------------------------------------------------------
    // 7. تشخیص خطای بات در مقابل خطای عمومی ۴۰۳ (Bot Detection vs 403)
    // -------------------------------------------------------------------------

    @Test
    fun testIsBotOrVisitorErrorCorrectClassification() {
        val manager = VisitorDataManager()

        // ۱. خطاهای صریح بات/کپچا باید شناسایی شوند
        assertTrue(manager.isBotOrVisitorError(Exception("Sign in to confirm you're not a bot")))
        assertTrue(manager.isBotOrVisitorError(Exception("YouTube reCAPTCHA challenge triggered")))
        assertTrue(manager.isBotOrVisitorError(Exception("Sign in required: LOGIN_REQUIRED")))
        assertTrue(manager.isBotOrVisitorError(Exception("automated queries detected from network")))
        assertTrue(manager.isBotOrVisitorError(null, httpStatus = 429))

        // ۲. خطای در علت زنجیره‌ای (cause)
        val wrapped = IOException("Wrapper", Exception("Please confirm you're not a robot"))
        assertTrue(manager.isBotOrVisitorError(wrapped))

        // ۳. الزامات بند ۳: هر خطای 403 نباید خودکار خطای بات فرض شود!
        assertFalse(manager.isBotOrVisitorError(Exception("HTTP 403 Forbidden: signature expired"), httpStatus = 403))
        assertFalse(manager.isBotOrVisitorError(Exception("HTTP 403 Forbidden"), httpStatus = 403))
        assertFalse(manager.isBotOrVisitorError(Exception("Access denied by CDN"), httpStatus = 403))

        // ۴. خطاهای عادی محدودیت سنی یا محتوا
        assertFalse(manager.isBotOrVisitorError(Exception("Track is age restricted")))
        assertFalse(manager.isBotOrVisitorError(Exception("Video unavailable in your region")))
        assertFalse(manager.isBotOrVisitorError(IOException("Connection reset by peer")))
    }

    // -------------------------------------------------------------------------
    // 8. ابطال و رفرش هنگام خطای بات (onBotDetected)
    // -------------------------------------------------------------------------

    @Test
    fun testOnBotDetectedRefreshesToken() {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        val tokenServed = AtomicInteger(1)

        server.createContext("/sw.js_data") { exchange ->
            val current = if (tokenServed.getAndIncrement() == 1) sampleToken else sampleToken2
            val body = sampleSwJsData(current).toByteArray()
            exchange.sendResponseHeaders(200, body.size.toLong())
            exchange.responseBody.use { it.write(body) }
        }
        server.start()

        val client = createTestClient()
        val port = server.address.port
        val url = "http://127.0.0.1:$port/sw.js_data"

        try {
            val manager = VisitorDataManager(httpClient = client, endpointUrl = url)

            runBlocking {
                val initial = manager.getVisitorData(refresh = false)
                assertEquals(sampleToken, initial)

                // شبیه‌سازی تشخیص ربات و رفرش
                val refreshed = manager.onBotDetected()
                assertEquals(sampleToken2, refreshed, "پس از onBotDetected باید توکن جدید دریافت شود")
                assertEquals(sampleToken2, manager.currentVisitorData)
            }
        } finally {
            server.stop(0)
            client.close()
        }
    }
}
