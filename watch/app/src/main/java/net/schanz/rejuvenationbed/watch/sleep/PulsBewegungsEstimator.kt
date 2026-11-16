package net.schanz.rejuvenationbed.watch.sleep

import net.schanz.rejuvenationbed.watch.analysis.SleepFeatureWindow

/**
 * Grobe Ersatz-Schätzung NUR aus Puls und Bewegung (ohne IBI/HRV), weil die
 * echte IBI-Quelle ohne Samsung-Partner-Zugang nicht verfügbar ist
 * (Fund-Notiz: docs/IBI_ADAPTER.md). Sie ist ausdrücklich eine **grobe
 * Schätzung** und kein validiertes Modell:
 *
 * - Die Schwellen sind unbeholfene Hypothesen aus üblichen Ruhepulsbereichen,
 *   nicht aus echten Nächten abgeleitet und nicht validiert.
 * - Schritt-Deltas sind ein grober Bewegungsindikator; ein Fenster ohne
 *   Schritt-Deltas ist keine gemessene „Nullbewegung“.
 * - Die Ausgabe trägt die Versionskennung `puls-bewegung-grob-0.1` und wird
 *   in der UI als „grobe Schätzung“ beschriftet.
 * - Unzureichende Daten bleiben `unknown` (fail-closed wie der M2-Schätzer).
 */
object PulsBewegungsEstimator {
    const val ALGORITHM_VERSION = "puls-bewegung-grob-0.1"

    /** Mindestens die Hälfte der 5-Minuten-Buckets muss Puls enthalten. */
    const val MINIMUM_BUCKET_OCCUPANCY = 0.5

    /** Ab dieser Schrittrate zählt das Fenster als „wach“ (gehen aufstehen). */
    const val MINIMUM_STEPS_PER_MINUTE_AWAKE = 2.0

    /** Bis zu dieser Schrittrate gilt ein Fenster als ruhig liegend. */
    const val MAXIMUM_STEPS_PER_MINUTE_REST = 0.5

    fun estimate(
        window: SleepFeatureWindow?,
        hatBewegungsdaten: Boolean,
        nowEpochMillis: Long,
        enabled: Boolean = false
    ): SleepStageEstimate {
        require(nowEpochMillis >= 0L) { "now must be non-negative" }

        if (!enabled) return unknown(nowEpochMillis, 0.0, "Schätzer ausgeschaltet")
        if (window == null) return unknown(nowEpochMillis, 0.0, "kein vollständiges 30-Minuten-Fenster")
        if (!window.hasMinimumHeartRateFeatures) {
            return unknown(nowEpochMillis, window.heartRateBucketOccupancy, "zu wenig Puls im Fenster")
        }
        val abdeckung = window.heartRateBucketOccupancy.coerceIn(0.0, 1.0)
        if (abdeckung < MINIMUM_BUCKET_OCCUPANCY) {
            return unknown(nowEpochMillis, abdeckung, "Puls-Abdeckung zu gering")
        }
        if (!hatBewegungsdaten) {
            return unknown(nowEpochMillis, abdeckung, "keine Bewegungsdaten")
        }
        val mean = window.heartRateMeanBpm
        val spread = window.heartRateStdDevBpm
        if (mean == null || spread == null) {
            return unknown(nowEpochMillis, abdeckung, "Puls-Merkmale fehlen")
        }

        val minutes = (window.endEpochMillis - window.startEpochMillis).toDouble() / 60_000.0
        val stepsPerMinute = if (minutes > 0.0) window.stepsInWindow / minutes else 0.0

        // Ausdrücklich grobe, deterministische Hypothesen-Regeln (siehe Klassen-Doc).
        val candidate = when {
            stepsPerMinute >= MINIMUM_STEPS_PER_MINUTE_AWAKE ->
                SleepStage.AWAKE to 0.85

            spread >= 12.0 || mean >= 85.0 ->
                SleepStage.AWAKE to 0.76

            stepsPerMinute <= MAXIMUM_STEPS_PER_MINUTE_REST && mean <= 55.0 && spread <= 5.0 ->
                SleepStage.DEEP to 0.78

            stepsPerMinute <= MAXIMUM_STEPS_PER_MINUTE_REST && mean >= 68.0 && spread >= 6.0 ->
                SleepStage.REM to 0.76

            stepsPerMinute <= MAXIMUM_STEPS_PER_MINUTE_REST && mean <= 70.0 && spread <= 8.0 ->
                SleepStage.LIGHT to 0.76

            else -> null
        } ?: return unknown(nowEpochMillis, abdeckung, "Keine Regel mit ausreichender Trennschärfe")

        return SleepStageEstimate(
            stage = candidate.first,
            confidence = candidate.second.coerceIn(0.0, 0.95),
            sampleCoverage = abdeckung,
            measuredAtEpochMillis = nowEpochMillis,
            algorithmVersion = ALGORITHM_VERSION
        )
    }

    private fun unknown(nowEpochMillis: Long, coverage: Double, @Suppress("UNUSED_PARAMETER") reason: String) =
        SleepStageEstimate(
            stage = SleepStage.UNKNOWN,
            confidence = 0.0,
            sampleCoverage = coverage.coerceIn(0.0, 1.0),
            measuredAtEpochMillis = nowEpochMillis,
            algorithmVersion = ALGORITHM_VERSION
        )
}
