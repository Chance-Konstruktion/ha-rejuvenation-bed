package net.schanz.rejuvenationbed.watch.analysis

import net.schanz.rejuvenationbed.watch.health.HeartRateSample
import net.schanz.rejuvenationbed.watch.health.StepIntervalSample
import kotlin.math.sqrt

/**
 * Descriptive signal features only. This class does not assign sleep stages.
 *
 * Heart-rate bucket occupancy describes where samples occurred; it is not a
 * measurement of continuous sensor uptime because Health Services batches data
 * at device-controlled, non-deterministic intervals.
 */
data class SleepFeatureWindow(
    val startEpochMillis: Long,
    val endEpochMillis: Long,
    val heartRateSampleCount: Int,
    val heartRateOccupiedBuckets: Int,
    val heartRateBucketCount: Int,
    val heartRateMeanBpm: Double?,
    val heartRateMedianBpm: Double?,
    val heartRateStdDevBpm: Double?,
    val heartRateMinBpm: Double?,
    val heartRateMaxBpm: Double?,
    val stepsInWindow: Long,
    val stepIntervalCount: Int
) {
    val heartRateBucketOccupancy: Double
        get() = if (heartRateBucketCount == 0) 0.0
        else heartRateOccupiedBuckets.toDouble() / heartRateBucketCount

    /**
     * A minimal feature-data gate for later model work, not a sleep-stage decision.
     */
    val hasMinimumHeartRateFeatures: Boolean
        get() = heartRateSampleCount >= 3 && heartRateOccupiedBuckets >= 2
}

object SleepFeatureExtractor {
    const val DEFAULT_WINDOW_MILLIS = 30L * 60L * 1000L
    const val DEFAULT_BUCKET_MILLIS = 5L * 60L * 1000L
    const val DEFAULT_LOOKBACK_MILLIS = 10L * 60L * 60L * 1000L

    fun extract(
        heartRateSamples: List<HeartRateSample>,
        stepIntervals: List<StepIntervalSample>,
        nowEpochMillis: Long,
        windowMillis: Long = DEFAULT_WINDOW_MILLIS,
        bucketMillis: Long = DEFAULT_BUCKET_MILLIS,
        lookbackMillis: Long = DEFAULT_LOOKBACK_MILLIS
    ): List<SleepFeatureWindow> {
        require(windowMillis > 0L && bucketMillis > 0L) { "window and bucket durations must be positive" }
        require(windowMillis % bucketMillis == 0L) { "window duration must be a multiple of bucket duration" }
        require(lookbackMillis >= windowMillis) { "lookback must cover at least one full window" }
        require(nowEpochMillis >= 0L) { "now must be non-negative" }

        val cutoff = nowEpochMillis - lookbackMillis
        val validHeartRate = heartRateSamples.filter {
            it.measuredAtEpochMillis in cutoff..nowEpochMillis &&
                it.beatsPerMinute.isFinite() &&
                it.beatsPerMinute in 30.0..220.0
        }
        if (validHeartRate.isEmpty()) return emptyList()

        val earliestSampleWindow = Math.floorDiv(
            validHeartRate.minOf { it.measuredAtEpochMillis },
            windowMillis
        ) * windowMillis
        val firstFullWindow = maxOf(earliestSampleWindow, ceilToWindow(cutoff, windowMillis))
        val lastFullWindow = Math.floorDiv(nowEpochMillis, windowMillis) * windowMillis - windowMillis
        if (firstFullWindow > lastFullWindow) return emptyList()

        val bucketCount = (windowMillis / bucketMillis).toInt()
        val windows = ArrayList<SleepFeatureWindow>()
        var windowStart = firstFullWindow

        while (windowStart <= lastFullWindow) {
            val windowEnd = windowStart + windowMillis
            val hr = validHeartRate.filter {
                it.measuredAtEpochMillis >= windowStart && it.measuredAtEpochMillis < windowEnd
            }
            val buckets = hr.map {
                ((it.measuredAtEpochMillis - windowStart) / bucketMillis).toInt()
            }.distinct().size

            val sortedValues = hr.map { it.beatsPerMinute }.sorted()
            val mean = sortedValues.takeIf { it.isNotEmpty() }?.average()
            val median = when {
                sortedValues.isEmpty() -> null
                sortedValues.size % 2 == 1 -> sortedValues[sortedValues.size / 2]
                else -> (sortedValues[sortedValues.size / 2 - 1] + sortedValues[sortedValues.size / 2]) / 2.0
            }
            val standardDeviation = mean?.let { average ->
                sqrt(sortedValues.sumOf { (it - average) * (it - average) } / sortedValues.size)
            }

            // A step delta belongs to the window containing its interval end.
            // Do not spread a batched delta uniformly across time: the platform
            // does not reveal when within the interval individual steps occurred.
            val steps = stepIntervals.filter {
                it.endEpochMillis > windowStart && it.endEpochMillis <= windowEnd
            }
            windows += SleepFeatureWindow(
                startEpochMillis = windowStart,
                endEpochMillis = windowEnd,
                heartRateSampleCount = hr.size,
                heartRateOccupiedBuckets = buckets,
                heartRateBucketCount = bucketCount,
                heartRateMeanBpm = mean,
                heartRateMedianBpm = median,
                heartRateStdDevBpm = standardDeviation,
                heartRateMinBpm = sortedValues.firstOrNull(),
                heartRateMaxBpm = sortedValues.lastOrNull(),
                stepsInWindow = steps.sumOf { it.steps },
                stepIntervalCount = steps.size
            )
            windowStart += windowMillis
        }

        return windows
    }

    private fun ceilToWindow(timestamp: Long, windowMillis: Long): Long =
        -Math.floorDiv(-timestamp, windowMillis) * windowMillis
}
