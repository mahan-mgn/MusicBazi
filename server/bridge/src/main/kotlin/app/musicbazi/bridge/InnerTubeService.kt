package app.musicbazi.bridge

import com.metrolist.innertubex.InnerTube
import com.metrolist.innertubex.InnerTubeLogLevel
import com.metrolist.innertubex.InnerTubeLogger
import com.metrolist.innertubex.cipher.YouTubeCipherService
import com.metrolist.innertubex.extraction.AudioQuality
import com.metrolist.innertubex.extraction.ContentHints
import com.metrolist.innertubex.extraction.InnerTubeExtractor
import com.metrolist.innertubex.extraction.StreamResolveException
import com.metrolist.innertubex.extraction.YtConfigParserImpl
import com.metrolist.innertubex.extraction.generateClientPlaybackNonce
import com.metrolist.innertubex.sabr.ExperimentalSabrApi
import com.metrolist.innertubex.sabr.SabrAudioStream
import io.ktor.client.HttpClient
import io.ktor.client.engine.okhttp.OkHttp
import io.ktor.client.plugins.HttpTimeout
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.serialization.kotlinx.json.json
import kotlinx.serialization.json.Json
import org.slf4j.LoggerFactory
import com.metrolist.innertubex.extraction.ExtractedStream
import com.metrolist.innertubex.extraction.strategy.ClientFailureKind
import kotlinx.coroutines.CancellationException
import java.util.concurrent.ConcurrentHashMap

interface IInnerTubeResolver {
    suspend fun resolve(
        videoId: String,
        purpose: String = "playback",
        qualityStr: String? = null,
        refreshVisitor: Boolean = false,
    ): BridgeResolvedStream
}

class InnerTubeService(
    private val httpClient: HttpClient = createDefaultHttpClient(),
    clientHealthMonitor: BridgeClientHealthMonitor = BridgeClientHealthMonitor(),
    val visitorDataManager: IVisitorDataManager = VisitorDataManager(httpClient),
    val prober: IStreamProber = StreamProber(httpClient),
    val exclusionManager: ClientExclusionManager = ClientExclusionManager(),
) : IInnerTubeResolver, ISabrResolver {
    private val logger = LoggerFactory.getLogger(InnerTubeService::class.java)

    data class MintedInfo(
        val videoId: String,
        val profileId: String,
        val clientName: String,
        val atMs: Long
    )
    private val minted = ConcurrentHashMap<String, MintedInfo>()

    fun rememberMinted(url: String, videoId: String, profileId: String, clientName: String) {
        if (minted.size >= 64) {
            val cutoff = System.currentTimeMillis() - 20 * 60 * 1000L
            minted.entries.removeIf { it.value.atMs < cutoff }
            if (minted.size >= 64) minted.clear()
        }
        minted[url] = MintedInfo(videoId, profileId, clientName, System.currentTimeMillis())
    }

    /**
     * ثبت بازخورد خطای ردشدن حین پخش (۴۰۳/۴۰۴/۴۱۰) و نیمکت‌نشینی کلاینت متناظر (Phase 2).
     */
    fun onPlaybackRefused(
        url: String?,
        videoId: String,
        statusCode: Int,
        clientName: String?,
        profileId: String?
    ): Boolean {
        if (statusCode !in setOf(403, 404, 410)) return false
        val info = url?.let { minted.remove(it) }
        val targetVid = videoId.ifBlank { info?.videoId.orEmpty() }
        val pId = profileId ?: info?.profileId
        val cName = clientName ?: info?.clientName

        if (targetVid.isNotBlank()) {
            if (!pId.isNullOrBlank()) {
                exclusionManager.exclude(targetVid, pId)
            }
            if (!cName.isNullOrBlank()) {
                exclusionManager.exclude(targetVid, cName)
            }
        }

        val healthClientId = when {
            pId?.contains("__") == true -> pId.substringBefore("__")
            !cName.isNullOrBlank() -> cName
            !pId.isNullOrBlank() -> pId
            else -> null
        }
        if (healthClientId != null) {
            clientHealthMonitor.recordFailure(healthClientId, ClientFailureKind.PLAYABILITY, scope = null)
        }
        logger.warn(
            "Playback refusal recorded status={} client={} profile={} videoId={}",
            statusCode, cName ?: "unknown", pId ?: "unknown", targetVid
        )
        return true
    }

    /**
     * ابطال وضعیت کلاینت‌های محروم و آدرس‌های ضرب‌شده هنگام تغییر نشست یا کوکی (مشابه BitChord).
     */
    fun onSessionChanged() {
        exclusionManager.clear()
        minted.clear()
        logger.info("InnerTubeService: session changed, exclusion manager and minted cache cleared")
    }

    private val itxLogger = InnerTubeLogger { event ->
        if (event.level == InnerTubeLogLevel.ERROR || event.level == InnerTubeLogLevel.WARN) {
            logger.warn("[ITX] ${event.tag}: ${event.message}")
        }
    }

    val innerTube = InnerTube(httpClient, logger = itxLogger)
    private val cipherService = YouTubeCipherService(httpClient, logger = itxLogger)
    private val configParser = YtConfigParserImpl(httpClient, innerTube, logger = itxLogger, cipherService = cipherService)

    /**
     * Health کلاینت‌های یوتیوب روی نقطه اتصال رسمی InnerTubeX وصل می‌شود (Phase 7).
     * کتابخانه خودش شکست‌ها را per-client ثبت می‌کند و از scoreAdjustment برای
     * deprioritize کردن کلاینت ناسالم و امتحان کلاینت سالم بعدی استفاده می‌کند.
     */
    val clientHealthMonitor = clientHealthMonitor

    val extractor = InnerTubeExtractor(
        configParser = configParser,
        cipherService = cipherService,
        innerTube = innerTube,
        clientHealthMonitor = clientHealthMonitor,
        logger = itxLogger
    )

    /**
     * ایزولاسیون کامل کلاینت‌های SABR: یک نمونه مجزا از extractor با health monitor اختصاصی
     * تا خطاهای احتمالی پروتکل یا attestation کلاینت‌های SABR هرگز به سلامت کلاینت‌های
     * تولیدی Progressive و HLS نشت نکند (الزام بند ۵ فاز ۱۷).
     */
    private val sabrExtractor = InnerTubeExtractor(
        configParser = configParser,
        cipherService = cipherService,
        innerTube = innerTube,
        clientHealthMonitor = BridgeClientHealthMonitor(),
        logger = itxLogger
    )

    override suspend fun resolve(
        videoId: String,
        purpose: String,
        qualityStr: String?,
        refreshVisitor: Boolean,
    ): BridgeResolvedStream {
        // Phase 1: تضمین تزریق Visitor Data معتبر پیش از درخواست استخراج
        visitorDataManager.ensureInjectedAsync(innerTube, refresh = refreshVisitor)

        val hints = ContentHints().withStreamCapabilities(
            allowHls = (purpose == "playback"),
            allowSabr = false,
            allowBoundedRange = (purpose == "playback")
        )

        val audioQuality = when (qualityStr?.lowercase()) {
            "low", "128" -> AudioQuality.LOW
            "mp4", "m4a" -> AudioQuality.MP4
            else -> AudioQuality.AUTO
        }

        val skipClients = mutableSetOf<String>()
        val maxAttempts = 3
        var lastFailureReason: StreamResolveException? = null

        for (attempt in 1..maxAttempts) {
            val excluded = exclusionManager.excludedFor(videoId) + skipClients

            val stream = try {
                extractor.extract(
                    videoId = videoId,
                    hints = hints,
                    excludedClients = excluded,
                    audioQuality = audioQuality,
                    clientPlaybackNonce = generateClientPlaybackNonce()
                )
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                if (visitorDataManager.isBotOrVisitorError(e)) {
                    logger.warn("Bot verification detected during extraction for videoId={}, refreshing visitor data", videoId)
                    visitorDataManager.onBotDetected()?.let { fresh ->
                        innerTube.visitorData = fresh
                    }
                }
                if (e is StreamResolveException) {
                    lastFailureReason = e
                } else {
                    lastFailureReason = StreamResolveException(
                        reason = StreamResolveException.Reason.NETWORK,
                        message = e.message ?: "Extraction failure",
                        cause = e
                    )
                }
                null
            }

            if (stream == null) {
                logger.warn("InnerTubeX returned no candidate on attempt={}/{} for videoId={}", attempt, maxAttempts, videoId)
                break
            }

            // Phase 2: اعتبارسنجی پیش‌پخش (Pre-flight Probe)
            val isHls = stream.audioUrl.contains(".m3u8") || stream.itag == 96
            val probeVerdict = prober.probe(
                url = stream.audioUrl,
                headers = stream.headers,
                contentLength = stream.contentLengthBytes,
                isHls = isHls
            )

            if (probeVerdict == ProbeVerdict.OK) {
                logger.info(
                    "InnerTubeX stream validated via probe on attempt={}/{} [vid={}, client={}, profile={}, itag={}]",
                    attempt, maxAttempts, videoId, stream.clientName, stream.profileId, stream.itag
                )
                rememberMinted(stream.audioUrl, videoId, stream.profileId, stream.clientName)

                val healthClientId = if (stream.profileId.contains("__")) {
                    stream.profileId.substringBefore("__")
                } else {
                    stream.clientName
                }
                clientHealthMonitor.recordSuccess(healthClientId, scope = null)

                return toBridgeResolvedStream(videoId, stream)
            }

            logger.warn(
                "Probe rejected candidate on attempt={}/{} [vid={}, client={}, profile={}, verdict={}]",
                attempt, maxAttempts, videoId, stream.clientName, stream.profileId, probeVerdict
            )

            if (probeVerdict == ProbeVerdict.REFUSED) {
                exclusionManager.exclude(videoId, stream.profileId)
                exclusionManager.exclude(videoId, stream.clientName)
                val healthClientId = if (stream.profileId.contains("__")) {
                    stream.profileId.substringBefore("__")
                } else {
                    stream.clientName
                }
                clientHealthMonitor.recordFailure(healthClientId, ClientFailureKind.PLAYABILITY, scope = null)
            }

            skipClients.add(stream.profileId)
            skipClients.add(stream.clientName)
        }

        throw lastFailureReason ?: StreamResolveException(
            reason = StreamResolveException.Reason.NO_PLAYABLE_STREAM,
            message = "No playable stream returned by InnerTubeX after $maxAttempts attempts"
        )
    }

    private fun toBridgeResolvedStream(videoId: String, stream: ExtractedStream): BridgeResolvedStream {
        val rawMime = stream.mimeType ?: "audio/webm"
        val cleanMime = rawMime.substringBefore(";").trim()
        val codec = stream.codecs ?: if (cleanMime.contains("mp4")) "mp4a.40.2" else "opus"
        val isLossless = cleanMime.contains("flac") || cleanMime.contains("wav")

        val durationSec = stream.mediaMetadata?.durationSeconds?.toDouble()
        val expiresAtSec = stream.expiresAt?.epochSeconds

        val streamType = if (stream.audioUrl.contains(".m3u8") || stream.itag == 96) "HLS" else "PROGRESSIVE"

        val metadata = mutableMapOf<String, String>()
        metadata["client_name"] = stream.clientName
        metadata["profile_id"] = stream.profileId
        metadata["itag"] = stream.itag.toString()
        metadata["resolver"] = "innertubex"

        return BridgeResolvedStream(
            source = "youtube",
            video_id = videoId,
            url = stream.audioUrl,
            mime_type = cleanMime,
            codec = codec,
            bitrate = stream.bitrate,
            sample_rate = stream.sampleRate,
            channels = 2,
            content_length = stream.contentLengthBytes,
            expires_at = expiresAtSec,
            duration = durationSec,
            headers = stream.headers,
            requires_range = stream.requireBoundedRange,
            resolver_metadata = metadata,
            is_lossless = isLossless,
            bit_depth = null,
            loudness_db = stream.loudnessDb,
            stream_type = streamType
        )
    }

    /**
     * متد مستقل و ایزوله برای حل استریم SABR و استخراج Bootstrap (فاز ۱۷).
     * مسیر تولید عادی resolve() با allowSabr = false کاملاً دست‌نخورده باقی می‌ماند.
     */
    @OptIn(ExperimentalSabrApi::class)
    override suspend fun resolveSabr(
        videoId: String,
        qualityStr: String?,
        playerTimeMs: Long
    ): SabrResolveResult {
        visitorDataManager.ensureInjectedAsync(innerTube, refresh = false)

        val hints = ContentHints(
            sabrFirst = true
        ).withStreamCapabilities(
            allowHls = false,
            allowSabr = true,
            allowBoundedRange = false
        )

        val audioQuality = when (qualityStr?.lowercase()) {
            "low", "128" -> AudioQuality.LOW
            "mp4", "m4a" -> AudioQuality.MP4
            else -> AudioQuality.AUTO
        }

        val stream = sabrExtractor.extract(
            videoId = videoId,
            hints = hints,
            excludedClients = emptySet(),
            audioQuality = audioQuality,
            clientPlaybackNonce = generateClientPlaybackNonce()
        ) ?: throw StreamResolveException(
            reason = StreamResolveException.Reason.NO_PLAYABLE_STREAM,
            message = "No playable stream returned by InnerTubeX for SABR"
        )

        val bootstrap = stream.sabrBootstrap ?: throw StreamResolveException(
            reason = StreamResolveException.Reason.NO_PLAYABLE_STREAM,
            message = "InnerTubeX did not return a SABR bootstrap for this track"
        )

        val rawMime = stream.mimeType ?: "audio/webm"
        val cleanMime = rawMime.substringBefore(";").trim()
        val codec = stream.codecs ?: if (cleanMime.contains("mp4")) "mp4a.40.2" else "opus"
        val durationMs = stream.mediaMetadata?.durationSeconds?.let { it * 1000L }
            ?: bootstrap.durationMs

        return SabrResolveResult(
            bootstrap = bootstrap,
            mimeType = cleanMime,
            codec = codec,
            bitrate = stream.bitrate,
            sampleRate = stream.sampleRate,
            channels = 2,
            durationMs = durationMs,
            itag = stream.itag,
            clientName = stream.clientName,
            streamFactory = { bs, timeMs ->
                SabrAudioStream(
                    httpClient = httpClient,
                    bootstrap = bs,
                    initialPlayerTimeMs = timeMs,
                    logger = itxLogger
                ).bytes()
            }
        )
    }

    companion object {
        fun createDefaultHttpClient(): HttpClient {
            return HttpClient(OkHttp) {
                install(ContentNegotiation) {
                    json(Json { ignoreUnknownKeys = true; explicitNulls = false })
                }
                install(HttpTimeout) {
                    requestTimeoutMillis = 20_000
                    connectTimeoutMillis = 10_000
                    socketTimeoutMillis = 15_000
                }
                expectSuccess = false
            }
        }
    }
}
