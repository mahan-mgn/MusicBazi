/*
 * Copyright (C) 2024-2026 Kushagra Singh / BitChord Contributors
 * Ported to Music Bazi (app.musicbazi.client.audio.dsp)
 *
 * Licensed under the GNU General Public License v3.0 (GPL-3.0)
 */

package app.musicbazi.client.audio.dsp

import kotlin.math.abs
import kotlin.math.log10
import kotlin.math.pow
import kotlin.math.sqrt

/**
 * The shape of one filter in [EqLayout].
 */
enum class FilterKind { BELL, LOW_SHELF, HIGH_SHELF }

/** A slot's fixed identity: its shape and where on the spectrum it sits. */
class FilterSlot(val kind: FilterKind, val frequencyHz: Float)

/**
 * Every filter either tab can ask for, in one fixed list.
 */
object EqLayout {

    /** The seven centres the manual tab puts a slider under. */
    val MANUAL_BANDS_HZ = floatArrayOf(60f, 150f, 400f, 1_000f, 2_500f, 6_000f, 14_000f)

    /**
     * Wide enough to overlap its neighbours — the centres are about 1.3 octaves
     * apart, so a Q near 1 means pushing every slider up lifts the whole band
     * evenly instead of leaving scallops between them.
     */
    const val MANUAL_Q = 1.0f

    /** Slots 0..6: the manual tab. */
    const val MANUAL_FIRST = 0
    const val MANUAL_COUNT = 7

    /** Slots 7..9: the tone pad's tilt pair and its mid contour. */
    const val TONE_LOW = 7
    const val TONE_MID = 8
    const val TONE_HIGH = 9

    const val SLOTS = 10

    val slots: List<FilterSlot> = buildList {
        MANUAL_BANDS_HZ.forEachIndexed { index, hz ->
            val kind = when (index) {
                0 -> FilterKind.LOW_SHELF
                MANUAL_BANDS_HZ.lastIndex -> FilterKind.HIGH_SHELF
                else -> FilterKind.BELL
            }
            add(FilterSlot(kind, hz))
        }
        add(FilterSlot(FilterKind.LOW_SHELF, 250f))
        add(FilterSlot(FilterKind.BELL, 1_000f))
        add(FilterSlot(FilterKind.HIGH_SHELF, 4_000f))
    }

    /** How far a manual slider travels either way. */
    const val MANUAL_RANGE_DB = 12f

    /** How far the tone pad travels on each axis, in whole steps. */
    const val TONE_STEPS = 5

    /** Decibels per step of the pad, so a corner is ±6 dB. */
    const val TONE_DB_PER_STEP = 1.2f

    /** Frequency of the tone pad's tilt pair, for the UI to describe. */
    val TONE_TILT_HZ = floatArrayOf(250f, 4_000f)
}

/**
 * A tuning, rendered: what every slot in [EqLayout] is set to right now.
 */
class EqCurve(
    val gainsDb: FloatArray,
    val qs: FloatArray,
    /**
     * Make-up attenuation, always at or below zero.
     */
    val preampDb: Float,
) {
    companion object {
        val FLAT = of(FloatArray(EqLayout.SLOTS), FloatArray(EqLayout.SLOTS) { 0.707f })

        /** Builds a curve and works out the attenuation it needs. */
        fun of(gainsDb: FloatArray, qs: FloatArray): EqCurve =
            EqCurve(gainsDb, qs, preampFor(gainsDb, qs))
    }
}

/** The seven sliders, as a curve. Slots the tone pad owns stay flat. */
fun manualCurve(bandsDb: List<Float>): EqCurve {
    val gains = FloatArray(EqLayout.SLOTS)
    val qs = FloatArray(EqLayout.SLOTS) { 0.707f }
    for (band in 0 until EqLayout.MANUAL_COUNT) {
        gains[EqLayout.MANUAL_FIRST + band] =
            bandsDb.getOrElse(band) { 0f }.coerceIn(-EqLayout.MANUAL_RANGE_DB, EqLayout.MANUAL_RANGE_DB)
        qs[EqLayout.MANUAL_FIRST + band] = EqLayout.MANUAL_Q
    }
    return EqCurve.of(gains, qs)
}

/**
 * The tone pad, as a curve. Slots the manual tab owns stay flat.
 */
fun toneCurve(x: Int, y: Int, focused: Boolean): EqCurve {
    val gains = FloatArray(EqLayout.SLOTS)
    val qs = FloatArray(EqLayout.SLOTS) { 0.707f }
    val steps = EqLayout.TONE_STEPS
    val tilt = x.coerceIn(-steps, steps) * EqLayout.TONE_DB_PER_STEP
    val contour = y.coerceIn(-steps, steps) * EqLayout.TONE_DB_PER_STEP

    gains[EqLayout.TONE_LOW] = -tilt
    gains[EqLayout.TONE_HIGH] = tilt
    gains[EqLayout.TONE_MID] = contour

    val shelfQ = if (focused) 0.9f else 0.5f
    val bellQ = if (focused) 2.2f else 0.7f
    qs[EqLayout.TONE_LOW] = shelfQ
    qs[EqLayout.TONE_HIGH] = shelfQ
    qs[EqLayout.TONE_MID] = bellQ
    return EqCurve.of(gains, qs)
}

/**
 * How far down the curve has to be pulled to stop it clipping.
 */
private fun preampFor(gainsDb: FloatArray, qs: FloatArray): Float {
    var peak = 0f
    for (point in 0 until RESPONSE_POINTS) {
        val hz = responseFrequency(point)
        var sum = 0f
        for (slot in 0 until EqLayout.SLOTS) {
            sum += sectionGainDb(EqLayout.slots[slot], gainsDb[slot], qs[slot], hz)
        }
        if (sum > peak) peak = sum
    }
    return -peak
}

/** Log-spaced across the audible band: 20 Hz to 20 kHz. */
private fun responseFrequency(point: Int): Float {
    val fraction = point.toDouble() / (RESPONSE_POINTS - 1)
    return (20.0 * (1_000.0).pow(fraction)).toFloat()
}

/**
 * One section's contribution at [hz], in decibels.
 */
internal fun sectionGainDb(slot: FilterSlot, gainDb: Float, q: Float, hz: Float): Float {
    if (abs(gainDb) < 0.01f) return 0f
    val a = 10.0.pow(gainDb / 40.0)
    val a2 = a * a
    val x = (hz / slot.frequencyHz).toDouble()
    val x2 = x * x
    val qq = (q * q).toDouble()
    val magnitude = when (slot.kind) {
        FilterKind.BELL -> {
            val flat = (1 - x2) * (1 - x2)
            sqrt((flat + x2 * a2 / qq) / (flat + x2 / (a2 * qq)))
        }
        FilterKind.LOW_SHELF -> {
            val common = x2 * a / qq
            a * sqrt(((a - x2) * (a - x2) + common) / ((1 - a * x2) * (1 - a * x2) + common))
        }
        FilterKind.HIGH_SHELF -> {
            val common = x2 * a / qq
            a * sqrt(((1 - a * x2) * (1 - a * x2) + common) / ((a - x2) * (a - x2) + common))
        }
    }
    return (20.0 * log10(magnitude)).toFloat()
}

private const val RESPONSE_POINTS = 96
