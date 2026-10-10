package app.musicbazi.bridge

import kotlinx.coroutines.runBlocking
import org.slf4j.LoggerFactory

/**
 * Diagnostic harness for verifying live YouTube stream resolution via InnerTubeX
 * without leaking signed CDN URLs.
 */
object ProbeHarness {
    private val log = LoggerFactory.getLogger(ProbeHarness::class.java)

    @JvmStatic
    fun main(args: Array<String>) = runBlocking {
        val videoId = args.firstOrNull { !it.startsWith("--") } ?: "dQw4w9WgXcQ"
        val isSabr = args.contains("--sabr") || System.getProperty("mode") == "sabr"

        if (isSabr) {
            println("=== MusicBazi InnerTubeX SABR Diagnostic Probe ===")
            println("Target videoId: $videoId")

            val service = InnerTubeService()
            val startMs = System.currentTimeMillis()

            try {
                val res = service.resolveSabr(videoId)
                val elapsedMs = System.currentTimeMillis() - startMs

                println("--- SABR Resolution Result ---")
                println("Resolution: SUCCESS")
                println("Elapsed: ${elapsedMs}ms")
                println("Client: ${res.clientName}")
                println("MIME: ${res.mimeType}")
                println("Codec: ${res.codec}")
                println("Bitrate: ${res.bitrate} bps")
                println("ITAG: ${res.itag}")
                println("Duration: ${res.durationMs} ms")
                println("Bootstrap VideoId: ${res.bootstrap.videoId}")
                println("Bootstrap Server URL: [REDACTED HTTPS GOOGLEVIDEO ENDPOINT]")
                println("Testing byte flow (reading initial chunk only)...")

                val flow = res.streamFactory(res.bootstrap, 0L)
                kotlinx.coroutines.withTimeout(20_000) {
                    flow.collect { chunk ->
                        println("Received initial audio chunk: ${chunk.size} bytes")
                        throw kotlinx.coroutines.CancellationException("Diagnostic probe finished")
                    }
                }
            } catch (e: kotlinx.coroutines.CancellationException) {
                if (e.message == "Diagnostic probe finished") {
                    println("Stream Test: SUCCESS (Initial audio bytes received, flow cancelled cleanly)")
                } else {
                    println("Stream Test: CANCELLED (${e.message})")
                }
                println("==================================================")
            } catch (e: Exception) {
                val elapsedMs = System.currentTimeMillis() - startMs
                println("--- SABR Diagnostic Result ---")
                println("Resolution: FAILED")
                println("Elapsed: ${elapsedMs}ms")
                println("Error Type: ${e.javaClass.simpleName}")
                println("Message: ${e.message}")
                println("==================================================")
            }
            return@runBlocking
        }

        println("=== MusicBazi InnerTubeX Diagnostic Probe ===")
        println("Target videoId: $videoId")

        val service = InnerTubeService()
        val startMs = System.currentTimeMillis()

        try {
            val stream = service.resolve(videoId = videoId, purpose = "playback")
            val elapsedMs = System.currentTimeMillis() - startMs

            println("--- Diagnostic Result ---")
            println("Resolution: SUCCESS")
            println("Elapsed: ${elapsedMs}ms")
            println("Source: ${stream.source}")
            println("Video ID: ${stream.video_id}")
            println("Selected Client: ${stream.resolver_metadata["client_name"]}")
            println("Profile ID: ${stream.resolver_metadata["profile_id"]}")
            println("ITAG: ${stream.resolver_metadata["itag"]}")
            println("MIME Type: ${stream.mime_type}")
            println("Codec: ${stream.codec}")
            println("Bitrate: ${stream.bitrate} bps")
            println("Sample Rate: ${stream.sample_rate} Hz")
            println("Channels: ${stream.channels}")
            println("Content Length: ${stream.content_length} bytes")
            println("Duration: ${stream.duration} s")
            println("Expires At (Epoch): ${stream.expires_at}")
            println("Stream Type: ${stream.stream_type}")
            println("Requires Range: ${stream.requires_range}")
            println("Loudness: ${stream.loudness_db} dB")
            println("Signed URL: [REDACTED BY PROBE HARNESS]")
            println("=========================================")
        } catch (e: Exception) {
            val elapsedMs = System.currentTimeMillis() - startMs
            println("--- Diagnostic Result ---")
            println("Resolution: FAILED")
            println("Elapsed: ${elapsedMs}ms")
            println("Error Type: ${e.javaClass.simpleName}")
            println("Message: ${e.message}")
            println("=========================================")
        }
    }
}
