package net.schanz.rejuvenationbed.watch.sleep

import net.schanz.rejuvenationbed.watch.analysis.SleepHrvFeatures
import kotlin.math.abs

/**
 * Reproducible experimental ruleset. It is not a medical model and is not
 * validated against Watch 4 nights. The caller must opt in explicitly;
 * the default is disabled and therefore returns UNKNOWN.
 */
object SleepStageEstimator {
    const val ALGORITHM_VERSION = "m2-rules-0.1"
    const val MINIMUM_CONFIDENCE = 0.75
    const val MINIMUM_COVERAGE = 0.80

    fun estimate(
        features: SleepHrvFeatures,
        nowEpochMillis: Long,
        enabled: Boolean = false
    ): SleepStageEstimate {
        require(nowEpochMillis >= 0L) { "now must be non-negative" }

        if (!enabled) return unknown(nowEpochMillis, 0.0, "Schätzer ausgeschaltet")
        if (!features.hasReliableIbi) {
            return unknown(nowEpochMillis, features.ibiCoverage, "IBI-Qualität oder Abdeckung zu gering")
        }
        if (features.movementVarianceStepsPerMinuteSquared == null ||
            features.movementCoverage < 0.50
        ) {
            return unknown(nowEpochMillis, minOf(features.ibiCoverage, features.movementCoverage),
                "Bewegungsdaten unvollständig")
        }

        val meanIbi = features.meanIbiMillis ?: return unknown(nowEpochMillis, 0.0, "IBI-Mittelwert fehlt")
        val rmssd = features.rmssdMillis ?: return unknown(nowEpochMillis, 0.0, "RMSSD fehlt")
        val sdnn = features.sdnnMillis ?: return unknown(nowEpochMillis, 0.0, "SDNN fehlt")
        val movementVariance = features.movementVarianceStepsPerMinuteSquared
        val coverage = minOf(features.ibiCoverage, features.movementCoverage)

        // Candidate rules are intentionally explicit and deterministic. They
        // are hypotheses for local comparison, not validated sleep physiology.
        val candidate = when {
            movementVariance >= 16.0 || (meanIbi < 720.0 && rmssd < 20.0) ->
                SleepStage.AWAKE to minOf(0.88, 0.76 + (movementVariance / 200.0))

            meanIbi >= 900.0 && rmssd >= 45.0 && sdnn >= 40.0 && movementVariance <= 6.0 ->
                SleepStage.DEEP to confidence(
                    base = 0.78,
                    rmssd = (rmssd - 45.0) / 100.0,
                    sdnn = (sdnn - 40.0) / 100.0,
                    movementPenalty = movementVariance / 100.0
                )

            meanIbi in 700.0..1_000.0 && rmssd >= 32.0 && sdnn >= 35.0 && movementVariance <= 10.0 ->
                SleepStage.REM to confidence(
                    base = 0.76,
                    rmssd = (rmssd - 32.0) / 120.0,
                    sdnn = (sdnn - 35.0) / 120.0,
                    movementPenalty = movementVariance / 120.0
                )

            meanIbi in 650.0..1_100.0 && rmssd >= 15.0 && movementVariance <= 20.0 ->
                SleepStage.LIGHT to confidence(
                    base = 0.75,
                    rmssd = (rmssd - 15.0) / 160.0,
                    sdnn = (sdnn - 20.0) / 180.0,
                    movementPenalty = movementVariance / 180.0
                )

            else -> null
        } ?: return unknown(nowEpochMillis, coverage, "Keine Regel mit ausreichender Trennschärfe")

        val confidence = candidate.second.coerceIn(0.0, 0.95)
        if (confidence < MINIMUM_CONFIDENCE || coverage < MINIMUM_COVERAGE) {
            return unknown(nowEpochMillis, coverage, "Konfidenz- oder Abdeckungsgrenze unterschritten")
        }

        return SleepStageEstimate(
            stage = candidate.first,
            confidence = confidence,
            sampleCoverage = coverage,
            measuredAtEpochMillis = nowEpochMillis,
            algorithmVersion = ALGORITHM_VERSION
        )
    }

    private fun confidence(
        base: Double,
        rmssd: Double,
        sdnn: Double,
        movementPenalty: Double
    ): Double = base + abs(rmssd) + abs(sdnn) - movementPenalty

    private fun unknown(nowEpochMillis: Long, coverage: Double, @Suppress("UNUSED_PARAMETER") reason: String) =
        SleepStageEstimate(
            stage = SleepStage.UNKNOWN,
            confidence = 0.0,
            sampleCoverage = coverage.coerceIn(0.0, 1.0),
            measuredAtEpochMillis = nowEpochMillis,
            algorithmVersion = ALGORITHM_VERSION
        )
}
