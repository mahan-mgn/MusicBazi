package app.musicbazi.bridge

import com.metrolist.innertubex.InnerTube
import io.ktor.client.HttpClient
import io.ktor.client.request.get
import io.ktor.client.request.header
import io.ktor.client.statement.bodyAsText
import io.ktor.http.HttpStatusCode
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import org.slf4j.LoggerFactory
import java.util.concurrent.atomic.AtomicReference

interface IVisitorDataManager {
    val currentVisitorData: String?
    suspend fun getVisitorData(refresh: Boolean = false): String?
    fun ensureInjected(innerTube: InnerTube, refresh: Boolean = false): String?
    suspend fun ensureInjectedAsync(innerTube: InnerTube, refresh: Boolean = false): String?
    fun isBotOrVisitorError(error: Throwable?, httpStatus: Int? = null): Boolean
    suspend fun onBotDetected(): String?
}

/**
 * مدیریت چرخه حیات Visitor Data برای استخراج پایدار از YouTube InnerTube (Phase 1).
 *
 * قابلیت‌ها:
 *  - استخراج امن از endpoint پروتکل sw.js_data با پشتیبانی از JSON ساخت‌یافته و Regex
 *  - نگهداری Thread-safe درون حافظه
 *  - کنترل همروندی Single-Flight (جلوگیری از Thundering Herd روی درخواست‌های هم‌زمان)
 *  - تزریق به نمونه InnerTube پیش از استخراج استریم
 *  - تازه‌سازی هوشمند هنگام دریافت خطاهای معتبر ربات (بدون تعمیم خودکار خطاهای عمومی ۴۰۳)
 *  - عدم نشت توکن یا داده‌های حساس به لاگ‌ها
 */
class VisitorDataManager(
    private val httpClient: HttpClient = InnerTubeService.createDefaultHttpClient(),
    private val endpointUrl: String = SW_JS_DATA_URL,
    private val userAgent: String = DEFAULT_USER_AGENT,
    private val fallbackFetcher: (suspend () -> String?)? = null,
) : IVisitorDataManager {

    private val logger = LoggerFactory.getLogger(VisitorDataManager::class.java)
    private val mutex = Mutex()
    private val cachedVisitorData = AtomicReference<String?>(null)
    private var inFlight: CompletableDeferred<String?>? = null

    override val currentVisitorData: String?
        get() = cachedVisitorData.get()

    /**
     * دریافت توکن Visitor Data.
     * در صورت وجود در کش و عدم درخواست refresh، بدون ایجاد درخواست شبکه برگردانده می‌شود.
     * در درخواست‌های هم‌زمان، فقط یک درخواست شبکه ایجاد شده و بقیه منتظر همان می‌مانند (Single-Flight).
     */
    override suspend fun getVisitorData(refresh: Boolean): String? {
        if (!refresh) {
            val existing = cachedVisitorData.get()
            if (!existing.isNullOrBlank()) {
                return existing
            }
        }

        var isFlightLeader = false
        val flight = mutex.withLock {
            if (!refresh) {
                val existing = cachedVisitorData.get()
                if (!existing.isNullOrBlank()) {
                    return existing
                }
            }
            val currentFlight = inFlight
            if (currentFlight != null) {
                currentFlight
            } else {
                isFlightLeader = true
                val newFlight = CompletableDeferred<String?>()
                inFlight = newFlight
                newFlight
            }
        }

        if (!isFlightLeader) {
            return flight.await() ?: cachedVisitorData.get()
        }

        return try {
            val fresh = fetchFromNetwork() ?: fallbackFetcher?.invoke()
            if (!fresh.isNullOrBlank()) {
                cachedVisitorData.set(fresh)
                // اکیداً مقدار حساس لاگ نمی‌شود؛ فقط طول توکن ثبت می‌شود
                logger.info("Visitor data token acquired successfully (token_len={})", fresh.length)
            } else {
                logger.warn("Visitor data endpoint returned no valid token")
            }
            flight.complete(fresh)
            fresh ?: cachedVisitorData.get()
        } catch (e: CancellationException) {
            flight.cancel(e)
            throw e
        } catch (e: Exception) {
            logger.warn("Visitor data fetch failed (type={}): {}", e.javaClass.simpleName, e.message)
            flight.complete(null)
            cachedVisitorData.get()
        } finally {
            mutex.withLock {
                if (inFlight === flight) {
                    inFlight = null
                }
            }
        }
    }

    /**
     * تزریق همگام توکن کش‌شده به InnerTube.
     */
    override fun ensureInjected(innerTube: InnerTube, refresh: Boolean): String? {
        val current = cachedVisitorData.get()
        if (!current.isNullOrBlank() && !refresh) {
            innerTube.visitorData = current
            return current
        }
        return current
    }

    /**
     * تزریق ناهمگام توکن به InnerTube (با دریافت از شبکه در صورت نیاز).
     */
    override suspend fun ensureInjectedAsync(innerTube: InnerTube, refresh: Boolean): String? {
        val token = getVisitorData(refresh = refresh)
        if (!token.isNullOrBlank()) {
            innerTube.visitorData = token
        }
        return token
    }

    /**
     * تشخیص قطعی خطای ربات یا چالش اعتبارسنجی بازدیدکننده.
     * الزامات: هر خطای 403 به طور خودکار خطای ربات فرض نمی‌شود.
     */
    override fun isBotOrVisitorError(error: Throwable?, httpStatus: Int?): Boolean {
        if (httpStatus == 429) return true

        val msg = error?.message?.lowercase() ?: ""
        val causeMsg = error?.cause?.message?.lowercase() ?: ""
        val combined = "$msg | $causeMsg"

        val botEvidenceKeywords = listOf(
            "sign in to confirm you're not a bot",
            "confirm you're not a bot",
            "recaptcha",
            "captcha",
            "login_required",
            "unusual traffic",
            "automated queries",
            "robot",
            "bot check"
        )

        return botEvidenceKeywords.any { combined.contains(it) }
    }

    /**
     * ابطال و رفرش توکن هنگام تشخیص خطای ربات.
     */
    override suspend fun onBotDetected(): String? {
        logger.warn("Bot verification evidence detected; invalidating and refreshing visitor data")
        return getVisitorData(refresh = true)
    }

    private suspend fun fetchFromNetwork(): String? {
        return try {
            val response = httpClient.get(endpointUrl) {
                header("User-Agent", userAgent)
                header("Accept", "*/*")
            }
            if (response.status != HttpStatusCode.OK) {
                logger.warn("Visitor data endpoint returned non-200 HTTP status: {}", response.status.value)
                return null
            }
            val body = response.bodyAsText()
            extractVisitorData(body)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            logger.warn("Network error fetching visitor data from endpoint (type={}): {}", e.javaClass.simpleName, e.message)
            null
        }
    }

    companion object {
        const val SW_JS_DATA_URL = "https://www.youtube.com/sw.js_data"
        const val DEFAULT_USER_AGENT =
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
        private val VISITOR_DATA_REGEX = Regex("""Cg[A-Za-z0-9_%=-]{40,}""")

        /**
         * استخراج مقدار توکن Visitor Data از بدنه پاسخ sw.js_data.
         * مقاوم در برابر پیشوندهای ضد سرقت جاوااسکریپت ()]}' و تغییرات ساختار JSON.
         */
        fun extractVisitorData(rawText: String): String? {
            if (rawText.isBlank()) return null

            val jsonCandidate = when {
                rawText.startsWith(")]}'") -> rawText.substringAfter('\n').trimStart()
                rawText.startsWith("/*-secure-") -> rawText.substringAfter('\n').trimStart()
                rawText.startsWith(")]}") -> rawText.substringAfter('\n').trimStart()
                else -> rawText.trimStart()
            }

            try {
                val element = Json.parseToJsonElement(jsonCandidate)
                val found = findInJson(element)
                if (!found.isNullOrBlank()) {
                    return found
                }
            } catch (_: Exception) {
                // اگر پارس JSON شکست خورد، جستجوی مستقیم Regex روی متن انجام می‌شود
            }

            return VISITOR_DATA_REGEX.find(rawText)?.value
        }

        private fun findInJson(element: JsonElement): String? = when (element) {
            is JsonPrimitive -> element.contentOrNull?.takeIf { VISITOR_DATA_REGEX.matches(it) }
            is JsonArray -> element.firstNotNullOfOrNull { findInJson(it) }
            is JsonObject -> element.values.firstNotNullOfOrNull { findInJson(it) }
        }
    }
}
