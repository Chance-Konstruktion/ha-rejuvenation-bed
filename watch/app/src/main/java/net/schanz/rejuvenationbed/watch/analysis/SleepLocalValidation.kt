package net.schanz.rejuvenationbed.watch.analysis

import net.schanz.rejuvenationbed.watch.health.IbiMesspunkt
import net.schanz.rejuvenationbed.watch.health.StepIntervalSample

/**
 * Builds a five-minute series of estimates from rolling, complete 30-minute
 * windows and compares it to a local Health Connect reference.
 *
 * This is deliberately an explicit validation operation: callers must pass
 * enabled=true, and the read-only Health Connect records are never persisted
 * by this class or uploaded.
 */
object SleepLocalValidation {
    const val DEFAULT_ANALYSIS_WINDOW_MILLIS = 30L * 60L * 1000L
    const val DEFAULT_PREDICTION_STEP_MILLIS = 5L * 60L * 1000L
    const val DEFAULT_COMPARISON_BUCKET_MILLIS = 5L * 60L * 1000L
    const val DEFAULT_MAXIMUM_PREDICTION_AGE_MILLIS = 10L * 60L * 1000L

    fun predictions(
        ibiSamples: List<IbiMesspunkt>,
        stepIntervals: List<StepIntervalSample>,
        startEpochMillis: Long,
        endEpochMillis: Long,
        enabled: Boolean,
        analysisWindowMillis: Long = DEFAULT_ANALYSIS_WINDOW_MILLIS,
        predictionStepMillis: Long = DEFAULT_PREDICTION_STEP_MILLIS
    ): List<SleepStagePrediction> {
        require(startEpochMillis >= 0L) { "start must be non-negative" }
        require(endEpochMillis > startEpochMillis) { "range must be positive" }
        require(analysisWindowMillis > 0L) { "analysis window must be positive" }
        require(predictionStepMillis > 0L) { "prediction step must be positive" }

        val result = mutableListOf<SleepStagePrediction>()
        var windowEnd = startEpochMillis + analysisWindowMillis
        while (windowEnd <= endEpochMillis) {
            val windowStart = windowEnd - analysisWindowMillis
            val features = SleepHrvExtractor.extract(
                ibiSamples = ibiSamples,
                stepIntervals = stepIntervals,
                startEpochMillis = windowStart,
                endEpochMillis = windowEnd
            )
            val estimate = net.schanz.rejuvenationbed.watch.sleep.SleepStageEstimator.estimate(
                features = features,
                nowEpochMillis = windowEnd,
                enabled = enabled
            )
            result += SleepStagePrediction(
                measuredAtEpochMillis = windowEnd,
                stage = estimate.stage,
                confidence = estimate.confidence,
                sampleCoverage = estimate.sampleCoverage,
                algorithmVersion = estimate.algorithmVersion
            )
            windowEnd += predictionStepMillis
        }
        return result
    }

    fun compare(
        ibiSamples: List<IbiMesspunkt>,
        stepIntervals: List<StepIntervalSample>,
        references: List<SleepStageReferenceInterval>,
        startEpochMillis: Long,
        endEpochMillis: Long,
        enabled: Boolean,
        analysisWindowMillis: Long = DEFAULT_ANALYSIS_WINDOW_MILLIS,
        predictionStepMillis: Long = DEFAULT_PREDICTION_STEP_MILLIS,
        comparisonBucketMillis: Long = DEFAULT_COMPARISON_BUCKET_MILLIS,
        maximumPredictionAgeMillis: Long = DEFAULT_MAXIMUM_PREDICTION_AGE_MILLIS
    ): SleepStageAgreementResult {
        val estimateSeries = predictions(
            ibiSamples = ibiSamples,
            stepIntervals = stepIntervals,
            startEpochMillis = startEpochMillis,
            endEpochMillis = endEpochMillis,
            enabled = enabled,
            analysisWindowMillis = analysisWindowMillis,
            predictionStepMillis = predictionStepMillis
        )
        return SleepStageAgreement.compare(
            predictions = estimateSeries,
            references = references,
            startEpochMillis = startEpochMillis,
            endEpochMillis = endEpochMillis,
            bucketMillis = comparisonBucketMillis,
            maximumPredictionAgeMillis = maximumPredictionAgeMillis
        )
    }
}
