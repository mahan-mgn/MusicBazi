package app.musicbazi.bridge

import com.sun.net.httpserver.HttpServer
import io.ktor.client.HttpClient
import io.ktor.client.engine.okhttp.OkHttp
import io.ktor.client.plugins.HttpTimeout
import kotlinx.coroutines.runBlocking
import java.net.InetSocketAddress
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class StreamProberTest {

    private fun createClient(timeoutMs: Long = 3_000L): HttpClient {
        return HttpClient(OkHttp) {
            install(HttpTimeout) {
                requestTimeoutMillis = timeoutMs
                connectTimeoutMillis = 1_000L
                socketTimeoutMillis = 2_000L
            }
        }
    }

    // -------------------------------------------------------------------------
    // ۱. پروب موفق با دریافت واقعی داده صوتی (Scenario 1)
    // -------------------------------------------------------------------------

    @Test
    fun testSuccessfulProbeWithRealAudioBytes() {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        val dataChunk = ByteArray(64 * 1024) { (it % 256).toByte() }
        val rangeReceived = AtomicBoolean(false)

        server.createContext("/audio") { exchange ->
            val range = exchange.requestHeaders.getFirst("Range")
            if (range != null && range.startsWith("bytes=1048576-")) {
                rangeReceived.set(true)
                exchange.responseHeaders.set("Content-Type", "audio/webm")
                exchange.responseHeaders.set("Content-Range", "bytes 1048576-${1048576 + dataChunk.size - 1}/3500000")
                exchange.sendResponseHeaders(206, dataChunk.size.toLong())
                exchange.responseBody.use { it.write(dataChunk) }
            } else {
                exchange.sendResponseHeaders(400, -1)
                exchange.close()
            }
        }
        server.start()

        val client = createClient()
        val prober = StreamProber(client)
        val url = "http://127.0.0.1:${server.address.port}/audio?clen=3500000"

        try {
            runBlocking {
                val verdict = prober.probe(url, contentLength = 3500000L)
                assertEquals(ProbeVerdict.OK, verdict)
                assertTrue(rangeReceived.get(), "پروب فایل بزرگتر از ۱ مگابایت باید درخواست Range بالای ۱ مگابایت بفرستد")
            }
        } finally {
            server.stop(0)
            client.close()
        }
    }

    // -------------------------------------------------------------------------
    // ۲. خطای 403، 404، 410 در پروب (Scenario 2)
    // -------------------------------------------------------------------------

    @Test
    fun testProbeRefusedOn403Forbidden() {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/forbidden") { exchange ->
            exchange.sendResponseHeaders(403, -1)
            exchange.close()
        }
        server.start()

        val client = createClient()
        val prober = StreamProber(client)
        val url = "http://127.0.0.1:${server.address.port}/forbidden"

        try {
            runBlocking {
                val verdict = prober.probe(url)
                assertEquals(ProbeVerdict.REFUSED, verdict)
            }
        } finally {
            server.stop(0)
            client.close()
        }
    }

    @Test
    fun testProbeRefusedOn410Gone() {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/gone") { exchange ->
            exchange.sendResponseHeaders(410, -1)
            exchange.close()
        }
        server.start()

        val client = createClient()
        val prober = StreamProber(client)
        val url = "http://127.0.0.1:${server.address.port}/gone"

        try {
            runBlocking {
                val verdict = prober.probe(url)
                assertEquals(ProbeVerdict.REFUSED, verdict)
            }
        } finally {
            server.stop(0)
            client.close()
        }
    }

    // -------------------------------------------------------------------------
    // ۳. پاسخ 200 با محتوای HTML یا کپچا (Scenario 3)
    // -------------------------------------------------------------------------

    @Test
    fun testProbeRefusedWhenServerReturnsHtmlCaptcha() {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        val htmlBody = "<html><body>Please solve the reCAPTCHA to continue</body></html>".toByteArray()

        server.createContext("/captcha") { exchange ->
            exchange.responseHeaders.set("Content-Type", "text/html; charset=utf-8")
            exchange.sendResponseHeaders(200, htmlBody.size.toLong())
            exchange.responseBody.use { it.write(htmlBody) }
        }
        server.start()

        val client = createClient()
        val prober = StreamProber(client)
        val url = "http://127.0.0.1:${server.address.port}/captcha"

        try {
            runBlocking {
                val verdict = prober.probe(url)
                assertEquals(ProbeVerdict.REFUSED, verdict, "پاسخ HTML به جای استریم صوتی باید REFUSED شود")
            }
        } finally {
            server.stop(0)
            client.close()
        }
    }

    // -------------------------------------------------------------------------
    // ۴. پاسخ 206 با Content-Range معتبر و نامعتبر (Scenario 4)
    // -------------------------------------------------------------------------

    @Test
    fun testProbeRefusedWhenContentRangeStartMismatched() {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        val dataChunk = ByteArray(64 * 1024)

        server.createContext("/mismatched") { exchange ->
            exchange.responseHeaders.set("Content-Type", "audio/webm")
            // پروب برای کلن ۳.۵ مگابایت درخواست bytes=1048576-... می‌فرستد، اما سرور 0 می‌فرستد
            exchange.responseHeaders.set("Content-Range", "bytes 0-65535/3500000")
            exchange.sendResponseHeaders(206, dataChunk.size.toLong())
            exchange.responseBody.use { it.write(dataChunk) }
        }
        server.start()

        val client = createClient()
        val prober = StreamProber(client)
        val url = "http://127.0.0.1:${server.address.port}/mismatched?clen=3500000"

        try {
            runBlocking {
                val verdict = prober.probe(url, contentLength = 3500000L)
                assertEquals(ProbeVerdict.REFUSED, verdict, "مغایرت در شروع Content-Range باید REFUSED تلقی شود")
            }
        } finally {
            server.stop(0)
            client.close()
        }
    }

    @Test
    fun testProbeRefusedWhen206MissingContentRange() {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        val dataChunk = ByteArray(16 * 1024)

        server.createContext("/no-range-header") { exchange ->
            exchange.responseHeaders.set("Content-Type", "audio/webm")
            // بدون ارسال هدر Content-Range
            exchange.sendResponseHeaders(206, dataChunk.size.toLong())
            exchange.responseBody.use { it.write(dataChunk) }
        }
        server.start()

        val client = createClient()
        val prober = StreamProber(client)
        val url = "http://127.0.0.1:${server.address.port}/no-range-header"

        try {
            runBlocking {
                val verdict = prober.probe(url)
                assertEquals(ProbeVerdict.REFUSED, verdict)
            }
        } finally {
            server.stop(0)
            client.close()
        }
    }

    // -------------------------------------------------------------------------
    // ۵. سروری که Range را نادیده می‌گیرد و کل فایل را ۲۰۰ می‌دهد (Scenario 5)
    // -------------------------------------------------------------------------

    @Test
    fun testServerIgnoringRangeDoesNotDownloadWholeFile() {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        val bytesWritten = AtomicInteger(0)
        // سرور یک فایل بزرگ ۱۰ مگابایتی برمی‌گرداند
        val totalFileSize = 10 * 1024 * 1024L

        server.createContext("/ignore-range") { exchange ->
            exchange.responseHeaders.set("Content-Type", "audio/mp4")
            exchange.sendResponseHeaders(200, totalFileSize)
            try {
                // سرور با آهنگ استریم شروع به ارسال چانک‌ها می‌کند
                val os = exchange.responseBody
                val chunk = ByteArray(64 * 1024)
                var written = 0L
                while (written < totalFileSize) {
                    os.write(chunk)
                    os.flush()
                    written += chunk.size
                    bytesWritten.set(written.toInt())
                    Thread.sleep(10)
                }
                os.close()
            } catch (_: Exception) {
                // کلاینت پس از خواندن چانک اولیه اتصال را بسته است (رفتار مورد انتظار)
            }
        }
        server.start()

        val client = createClient()
        val prober = StreamProber(client)
        val url = "http://127.0.0.1:${server.address.port}/ignore-range"

        try {
            runBlocking {
                val verdict = prober.probe(url)
                assertEquals(ProbeVerdict.OK, verdict)
                // پروب نباید کل ۱۰ مگابایت را دانلود کرده باشد؛ دانلود متوقف شده است
                assertTrue(bytesWritten.get() < totalFileSize / 2, "پروب باید بلافاصله پس از خواندن چانک اولیه اتصال را ببندد و کل فایل را دانلود نکند")
            }
        } finally {
            server.stop(0)
            client.close()
        }
    }

    // -------------------------------------------------------------------------
    // ۶. خطای شبکه و Timeout (Scenario 6)
    // -------------------------------------------------------------------------

    @Test
    fun testProbeReturnsUnreachableOnServer500() {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/error500") { exchange ->
            exchange.sendResponseHeaders(500, -1)
            exchange.close()
        }
        server.start()

        val client = createClient()
        val prober = StreamProber(client)
        val url = "http://127.0.0.1:${server.address.port}/error500"

        try {
            runBlocking {
                val verdict = prober.probe(url)
                assertEquals(ProbeVerdict.UNREACHABLE, verdict)
            }
        } finally {
            server.stop(0)
            client.close()
        }
    }

    @Test
    fun testProbeReturnsUnreachableOnConnectionTimeout() {
        val client = createClient(timeoutMs = 500L)
        val prober = StreamProber(client)
        // پورت ناموجود که پاسخ نمی‌دهد
        val url = "http://127.0.0.1:59998/timeout"

        runBlocking {
            val verdict = prober.probe(url)
            assertEquals(ProbeVerdict.UNREACHABLE, verdict)
        }
        client.close()
    }

    // -------------------------------------------------------------------------
    // ۱۲. سازگاری فرمت HLS (Scenario 12)
    // -------------------------------------------------------------------------

    @Test
    fun testProbeHlsManifestSuccess() {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        val m3u8Content = "#EXTM3U\n#EXT-X-VERSION:3\n#EXTINF:10.0,\nseg1.ts\n".toByteArray()

        server.createContext("/playlist.m3u8") { exchange ->
            exchange.responseHeaders.set("Content-Type", "application/vnd.apple.mpegurl")
            exchange.sendResponseHeaders(200, m3u8Content.size.toLong())
            exchange.responseBody.use { it.write(m3u8Content) }
        }
        server.start()

        val client = createClient()
        val prober = StreamProber(client)
        val url = "http://127.0.0.1:${server.address.port}/playlist.m3u8"

        try {
            runBlocking {
                val verdict = prober.probe(url, isHls = true)
                assertEquals(ProbeVerdict.OK, verdict)
            }
        } finally {
            server.stop(0)
            client.close()
        }
    }
}
