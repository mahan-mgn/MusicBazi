/*
 * Copyright (C) 2024-2026 Kushagra Singh / BitChord Contributors
 * Ported to Music Bazi (app.musicbazi.client.audio.quality)
 *
 * Licensed under the GNU General Public License v3.0 (GPL-3.0)
 */

package app.musicbazi.client.audio.quality

import java.text.Normalizer
import java.util.Locale
import kotlin.math.abs

/**
 * High-precision track identity and recording matcher.
 *
 * Ensures alternative quality candidates (e.g. 320kbps MP3 / FLAC) genuinely match
 * the currently requested recording before triggering a quality upgrade.
 * Rejects covers, remixes, live recordings, karaoke, and duration mismatches.
 */
object TrackMatcher {

    data class Target(
        val title: String,
        val artist: String = "",
        val durationSec: Int? = null,
        val album: String? = null,
        val isExplicit: Boolean? = null,
    )

    data class Candidate(
        val title: String,
        val artist: String = "",
        val durationSec: Int? = null,
        val album: String? = null,
        val isExplicit: Boolean? = null,
    )

    fun matches(candidate: Candidate, target: Target): Boolean {
        return score(candidate, target) != null
    }

    fun score(candidate: Candidate, target: Target): Int? {
        val wanted = parseTitle(target.title, target.artist)
        val got = parseTitle(candidate.title, candidate.artist)
        if (wanted.core.isBlank() || got.core.isBlank()) return null

        val isTitleMatch = when {
            wanted.core == got.core -> true
            wanted.core.length <= 3 || got.core.length <= 3 -> false
            else -> wanted.core.contains(got.core) || got.core.contains(wanted.core)
        }
        if (!isTitleMatch) return null

        // Version take mismatch rejection (e.g. Live, Remix, Instrumental)
        if (wanted.versions != got.versions) {
            return null
        }

        // Duration comparison
        val durScore = durationScore(target.durationSec, candidate.durationSec) ?: return null

        // Artist check
        val artScore = artistScore(target.artist, candidate.artist) ?: return null

        // Explicit check
        if (target.isExplicit != null && candidate.isExplicit != null && target.isExplicit != candidate.isExplicit) {
            return null
        }

        return BASE + artScore + durScore
    }

    internal data class TitleParts(
        val words: List<String>,
        val core: String,
        val versions: Set<String>,
        val context: Set<String>,
    )

    internal fun parseTitle(raw: String, artist: String = ""): TitleParts {
        val versions = sortedSetOf<String>()
        val context = mutableSetOf<String>()
        var text = normalize(raw)

        repeat(BRACKET_PASSES) {
            if (!BRACKETED.containsMatchIn(text)) return@repeat
            text = BRACKETED.replace(text) { match ->
                classify(match.groupValues[1], versions, context)
                " "
            }
        }

        text.indexOfFirst { it == '(' || it == '[' }.takeIf { it >= 0 }?.let { open ->
            classify(text.substring(open), versions, context)
            text = text.substring(0, open)
        }

        repeat(DASH_PASSES) {
            val dash = DASH.find(text) ?: return@repeat
            val head = text.substring(0, dash.range.first)
            val tail = text.substring(dash.range.last + 1)
            text = if (isArtistName(head, artist)) {
                classify(head, versions, context)
                tail
            } else {
                classify(tail, versions, context)
                head
            }
        }

        text = text.replace(FEATURING, " ")

        var words = text.split(WORD_SPLIT)
            .map { it.replace(NON_ALNUM, "") }
            .filter { it.isNotEmpty() && it !in JOINING_WORDS }

        while (words.size > 1) {
            val last = words.last()
            if (last in TRAILING_NOISE) {
                words = words.dropLast(1)
            } else if (last in TRAILING_TAKES) {
                versions += last
                words = words.dropLast(1)
            } else {
                break
            }
        }

        return TitleParts(
            words = words,
            core = words.joinToString(""),
            versions = versions,
            context = context,
        )
    }

    private fun classify(
        segment: String,
        versions: MutableSet<String>,
        context: MutableSet<String>,
    ) {
        val words = segment.split(WORD_SPLIT)
            .map { it.replace(NON_ALNUM, "") }
            .filter { it.isNotEmpty() }
        if (words.isEmpty()) return
        if (words.joinToString("") in NEUTRAL_SEGMENTS) return
        val marks = words.filter { it in VERSION_WORDS }
        if (marks.isNotEmpty()) {
            versions += marks
            return
        }
        context += words.filter { it.length > 2 && it !in NOISE_WORDS }
    }

    private fun isArtistName(text: String, artist: String): Boolean {
        if (artist.isBlank()) return false
        val words = text.split(WORD_SPLIT).map { it.replace(NON_ALNUM, "") }.filter { it.isNotEmpty() }
        if (words.isEmpty()) return false
        val credited = normalize(artist).split(WORD_SPLIT)
            .map { it.replace(NON_ALNUM, "") }
            .filter { it.isNotEmpty() }
            .toSet()
        return words.all { it in credited }
    }

    internal fun normalize(text: String): String =
        Normalizer.normalize(text, Normalizer.Form.NFKC)
            .lowercase(Locale.ROOT)
            .replace("&", " and ")

    private fun artistScore(wanted: String, got: String): Int? {
        val want = artistNames(wanted)
        val have = artistNames(got)
        if (want.isEmpty() || have.isEmpty()) return 0
        val shared = want.any { w -> have.any { h -> w == h } }
        if (!shared) return null
        return if (want == have) ARTIST_EXACT else ARTIST_SHARED
    }

    internal fun artistNames(value: String): Set<List<String>> = normalize(value)
        .split(ARTIST_SEPARATORS)
        .map { name ->
            name.split(WORD_SPLIT)
                .map { it.replace(NON_ALNUM, "") }
                .filter { it.length > 1 }
        }
        .filter { it.isNotEmpty() }
        .toSet()

    private fun durationScore(wanted: Int?, got: Int?): Int? {
        if (wanted == null || got == null) return 0
        val drift = abs(wanted - got)
        return when {
            drift > DURATION_LIMIT_SEC -> null
            drift <= DURATION_TIGHT_SEC -> DURATION_TIGHT
            else -> DURATION_LOOSE
        }
    }

    private const val BASE = 100
    private const val ARTIST_EXACT = 25
    private const val ARTIST_SHARED = 10
    private const val DURATION_TIGHT = 40
    private const val DURATION_LOOSE = 15
    private const val DURATION_TIGHT_SEC = 3
    const val DURATION_LIMIT_SEC = 30

    private const val BRACKET_PASSES = 3
    private const val DASH_PASSES = 3
    private val BRACKETED = Regex("""[(\[]([^()\[\]]*)[)\]]""")
    private val DASH = Regex("""\s+[-–—|]+\s+""")
    private val FEATURING = Regex("""\b(feat|ft|featuring|with)\b.*""")
    private val WORD_SPLIT = Regex("""[\s.·~〜]+""")
    private val NON_ALNUM = Regex("""[^\p{L}\p{N}]""")

    private val ARTIST_SEPARATORS =
        Regex("""\s*(?:[,&/;·|、，×]|\band\b|\bx\b|\bvs\.?\b|\bfeat\.?\b|\bft\.?\b|\bfeaturing\b|\bwith\b)\s*""")

    private val VERSION_WORDS = setOf(
        "remix", "remixes", "rmx", "refix", "flip", "bootleg", "mashup",
        "live", "concert", "unplugged", "acoustic", "instrumental", "karaoke",
        "vocals", "vocal", "acapella", "acappella", "backing", "stems", "stem",
        "cover", "demo", "reprise", "remake", "rework", "extended", "edit",
        "version", "mix", "dub", "sped", "slowed", "reverb", "nightcore", "lofi",
    )

    private val TRAILING_TAKES = setOf(
        "instrumental", "karaoke", "acapella", "acappella", "remix", "rmx", "nightcore",
    )

    private val NEUTRAL_SEGMENTS = setOf(
        "albumversion", "originalversion", "originalmix", "singleversion",
        "radioversion", "radioedit", "stereoversion", "monoversion",
        "studioversion", "fullversion", "standardversion",
    )

    private val TRAILING_NOISE = setOf(
        "audio", "video", "official", "lyrics", "hd", "hq", "4k", "full", "track",
    )

    private val NOISE_WORDS = setOf(
        "the", "official", "audio", "video", "music", "lyric", "lyrics",
    )

    private val JOINING_WORDS = setOf(
        "the", "a", "an", "and", "or", "of", "in", "on", "at", "to", "for", "with",
    )
}
