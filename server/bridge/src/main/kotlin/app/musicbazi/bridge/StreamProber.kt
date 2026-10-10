package app.musicbazi.bridge

import io.ktor.client.HttpClient
import io.ktor.client.plugins.HttpTimeout
import io.ktor.client.request.header
import io.ktor.client.request.prepareGet
import io.ktor.client.statement.bodyAsChannel
import io.ktor.utils.io.readAvailable
import kotlinx.coroutines.CancellationException
import org.slf4j.LoggerFactory
import java.io.IOException

enum class ProbeVerdict {
    OK,
    REFUSED,     // 403, 404, 410, محتوای غیرصوتی (HTML/کپچا)، Range نامعتبر
    UNREACHABLE  // خطای سرور 5xx، قطعی شبکه، تایم‌اوت، خواندن ناقص داده
}

interface IStreamProber {
    suspend fun probe(
        url: String,
        headers: Map<String, String> = emptyMap(),
        contentLength: Long? = null,
        isHls: Boolean = false
    ): ProbeVerdict
}

/**
 * اعتبارسنجی پیش‌پخش (Pre-flight Probe) برای بررسی واقعی اعتبار استریم پیش از تحویل به پلیر (Phase 2).
 *
 * ویژگی‌ها:
 *  - ارسال درخواست HTTP Range محدودشده برای استریم‌های Progressive
 *  - در صورت معتبر بودن طول و امکان‌پذیر بودن (> 1MB)، پروب بالاتر از مرز ۱ مگابایت (1048576) جهت کشف محدودیت‌های CDN
 *  - بررسی وضعیت HTTP، Content-Type، Content-Range و دریافت واقعی ۱۶ کیلوبایت صوت
 *  - جلوگیری از دانلود کامل فایل در صورت نادیده‌گرفتن Range و پاسخ ۲۰۰ توسط سرور
 *  - تفکیک قطعی خطای دسترسی (REFUSED) از خطای موقت شبکه (UNREACHABLE)
 *  - مدیریت سازگار استریم‌های HLS
 */
class StreamProber(
    private val httpClient: HttpClient = createDefaultProberClient()
) : IStreamProber {
    private val logger = LoggerFactory.getLogger(StreamProber::class.java)

    override suspend fun probe(
        url: String,
        headers: Map<String, String>,
        contentLength: Long?,
        isHls: Boolean
    ): ProbeVerdict {
        if (url.isBlank()) return ProbeVerdict.REFUSED

        return try {
            if (isHls || url.contains(".m3u8")) {
                probeHls(url, headers)
            } else {
                probeProgressive(url, headers, contentLength)
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: IOException) {
            logger.warn("Probe network error (type={}): {}", e.javaClass.simpleName, e.message)
            ProbeVerdict.UNREACHABLE
        } catch (e: Exception) {
            logger.warn("Probe unexpected error (type={}): {}", e.javaClass.simpleName, e.message)
            ProbeVerdict.UNREACHABLE
        }
    }

    private suspend fun probeHls(url: String, headers: Map<String, String>): ProbeVerdict {
        val statement = httpClient.prepareGet(url) {
            headers.forEach { (k, v) -> header(k, v) }
        }
        return statement.execute { response ->
            val status = response.status.value
            if (status in setOf(403, 404, 410)) return@execute ProbeVerdict.REFUSED
            if (status !in 200..299) return@execute ProbeVerdict.UNREACHABLE

            val contentType = response.headers["Content-Type"]?.lowercase() ?: ""
            if (contentType.contains("text/html")) return@execute ProbeVerdict.REFUSED

            val channel = response.bodyAsChannel()
            val buf = ByteArray(1024)
            val read = channel.readAvailable(buf, 0, buf.size)
            if (read <= 0) return@execute ProbeVerdict.UNREACHABLE
            ProbeVerdict.OK
        }
    }

    private suspend fun probeProgressive(
        url: String,
        headers: Map<String, String>,
        contentLength: Long?
    ): ProbeVerdict {
        val clen = contentLength ?: parseClenFromUrl(url)
        val authBoundary = 1024L * 1024L // 1 MiB
        val probeReadBytes = 16L * 1024L  // 16 KiB

        // فقط در صورت معتبر بودن طول و امکان‌پذیر بودن (> 1MB + 16KB)، پروب بالای ۱ مگابایت انجام می‌شود
        val start = if (clen != null && clen > authBoundary + probeReadBytes) {
            authBoundary
        } else {
            0L
        }
        val span = 64L * 1024L // 64 KiB
        val end = if (clen != null) {
            minOf(start + span - 1, clen - 1)
        } else {
            start + span - 1
        }

        val statement = httpClient.prepareGet(url) {
            headers.forEach { (k, v) ->
                if (!k.equals("Range", ignoreCase = true)) {
                    header(k, v)
                }
            }
            header("Range", "bytes=$start-$end")
            header("Accept-Encoding", "identity")
        }

        return statement.execute { response ->
            val status = response.status.value
            if (status in setOf(403, 404, 410)) return@execute ProbeVerdict.REFUSED
            if (status != 200 && status != 206) return@execute ProbeVerdict.UNREACHABLE

            val contentType = response.headers["Content-Type"]?.lowercase() ?: ""
            if (contentType.contains("text/html") || contentType.contains("text/plain")) {
                return@execute ProbeVerdict.REFUSED
            }
            if (contentType.isNotBlank() &&
                !contentType.startsWith("audio/") &&
                !contentType.startsWith("video/") &&
                !contentType.contains("octet-stream")
            ) {
                return@execute ProbeVerdict.REFUSED
            }

            if (status == 206) {
                val contentRange = response.headers["Content-Range"] ?: return@execute ProbeVerdict.REFUSED
                val actualStart = parseRangeStart(contentRange)
                if (actualStart != null && actualStart != start) {
                    return@execute ProbeVerdict.REFUSED
                }
            }

            // خواندن بایت‌های واقعی صوت؛ در صورت پاسخ 200 (نادیده‌گرفتن Range) فقط 16KB خوانده شده و با اتمام بلوک execute اتصال فوراً بسته می‌شود
            val channel = response.bodyAsChannel()
            val targetBytes = probeReadBytes.toInt()
            val buf = ByteArray(targetBytes)
            var totalRead = 0
            while (totalRead < targetBytes && !channel.isClosedForRead) {
                val read = channel.readAvailable(buf, totalRead, targetBytes - totalRead)
                if (read <= 0) break
                totalRead += read
            }
            val minExpected = if (clen != null && clen < targetBytes) clen.toInt() else targetBytes
            if (totalRead < minExpected && channel.isClosedForRead) {
                return@execute ProbeVerdict.UNREACHABLE
            }
            ProbeVerdict.OK
        }
    }

    companion object {
        fun createDefaultProberClient(): HttpClient {
            return HttpClient(io.ktor.client.engine.okhttp.OkHttp) {
                install(HttpTimeout) {
                    requestTimeoutMillis = 6_000
                    connectTimeoutMillis = 3_000
                    socketTimeoutMillis = 4_000
                }
            }
        }

        fun parseClenFromUrl(url: String): Long? {
            val query = url.substringAfter('?', "")
            if (query.isEmpty()) return null
            for (param in query.split('&')) {
                val kv = param.split('=', limit = 2)
                if (kv[0] == "clen" && kv.size == 2) {
                    return kv[1].toLongOrNull()
                }
            }
            return null
        }

        fun parseRangeStart(contentRange: String): Long? {
            val prefix = "bytes "
            val clean = contentRange.trim()
            val afterPrefix = if (clean.startsWith(prefix, ignoreCase = true)) clean.substring(prefix.length) else clean
            val startPart = afterPrefix.substringBefore('-').trim()
            return startPart.toLongOrNull()
        }
    }
}
