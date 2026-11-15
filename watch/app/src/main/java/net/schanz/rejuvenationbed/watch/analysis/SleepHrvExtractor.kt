package net.schanz.rejuvenationbed.watch.analysis

import net.schanz.rejuvenationbed.watch.health.IbiMesspunkt
import net.schanz.rejuvenationbed.watch.health.StepIntervalSample
import kotlin.math.sqrt

/**
 * HRV and movement features for one complete analysis window.
 *
 * coverage is approximated from accepted NN intervals, not from a claimed
 * continuous sensor uptime. signalQuality is the fraction of raw IBI samples
 * surviving physiological, provider-quality and artefact gates.
 */
data class SleepHrvFeatures(
    val startEpochMillis: Long,
    val endEpochMillis: Long,
    val rawIbiCount: Int,
    val acceptedIbiCount: Int,
    val rejectedIbiCount: Int,
    val meanIbiMillis: Double?,
    val rmssdMillis: Double?,
    val sdnnMillis: Double?,
    val ibiCoverage: Double,
    val signalQuality: Double,
    val movementBucketCount: Int,
    val movementCoverage: Double,
    val movementVarianceStepsPerMinuteSquared: Double?
) {
    val hasReliableIbi: Boolean
        get() = acceptedIbiCount >= MINIMUM_IBI_SAMPLES &&
            ibiCoverage >= MINIMUM_IBI_COVERAGE &&
            signalQuality >= MINIMUM_SIGNAL_QUALITY &&
            rmssdMillis != null && sdnnMillis != null

    companion object {
        const val MINIMUM_IBI_SAMPLES = 120
        const val MINIMUM_IBI_COVERAGE = 0.70
        const val MINIMUM_SIGNAL_QUALITY = 0.80
    }
}

object SleepHrvExtractor {
    const val DEFAULT_MOVEMENT_BUCKET_MILLIS = 5L * 60L * 1000L
    private const val MIN_IBI_MILLIS = 300.0
    private const val MAX_IBI_MILLIS = 2_000.0
    private const val PROVIDER_QUALITY_FLOOR = 0.50
    private const val ARTEFACT_RELATIVE_LIMIT = 0.20
    private const val ARTEFACT_ABSOLUTE_LIMIT_MILLIS = 250.0

    fun extract(
        ibiSamples: List<IbiMesspunkt>,
        stepIntervals: List<StepIntervalSample>,
        startEpochMillis: Long,
        endEpochMillis: Long,
        movementBucketMillis: Long = DEFAULT_MOVEMENT_BUCKET_MILLIS
    ): SleepHrvFeatures {
        require(startEpochMillis >= 0L) { "start must be non-negative" }
        require(endEpochMillis > startEpochMillis) { "window must have positive duration" }
        require(movementBucketMillis > 0L) { "movement bucket must be positive" }

        val windowDuration = (endEpochMillis - startEpochMillis).toDouble()
        // Count every timestamped input before filtering so raw + rejected = accepted + rejected.
        // Invalid intervals, poor provider quality, duplicate timestamps and artefacts all
        // contribute to the rejected count and lower the reported signal-quality fraction.
        val inWindow = ibiSamples.filter {
            it.measuredAtEpochMillis in (startEpochMillis + 1L)..endEpochMillis
        }
        val candidates = inWindow
            .asSequence()
            .filter { it.intervalMillis.isFinite() && it.intervalMillis in MIN_IBI_MILLIS..MAX_IBI_MILLIS }
            .filter { it.signalQuality == null || it.signalQuality >= PROVIDER_QUALITY_FLOOR }
            .distinctBy { it.measuredAtEpochMillis }
            .sortedBy { it.measuredAtEpochMillis }
            .toList()

        val accepted = removeArtefacts(candidates)
        val intervals = accepted.map { it.intervalMillis }
        val mean = intervals.takeIf { it.isNotEmpty() }?.average()
        val differences = intervals.zipWithNext { left, right -> right - left }
        val rmssd = differences.takeIf { it.isNotEmpty() }
            ?.let { sqrt(it.sumOf { delta -> delta * delta } / it.size) }
        val sdnn = intervals.takeIf { it.size >= 2 }?.let { values ->
            val average = values.average()
            val sumSquares = values.sumOf { (it - average) * (it - average) }
            sqrt(sumSquares / (values.size - 1))
        }
        val acceptedDuration = intervals.sum()
        val coverage = (acceptedDuration / windowDuration).coerceIn(0.0, 1.0)
        val rawCount = inWindow.size
        val signalQuality = if (rawCount == 0) 0.0 else accepted.size.toDouble() / rawCount

        val movement = movementFeatures(
            stepIntervals = stepIntervals,
            startEpochMillis = startEpochMillis,
            endEpochMillis = endEpochMillis,
            bucketMillis = movementBucketMillis
        )

        return SleepHrvFeatures(
            startEpochMillis = startEpochMillis,
            endEpochMillis = endEpochMillis,
            rawIbiCount = rawCount,
            acceptedIbiCount = accepted.size,
            rejectedIbiCount = (rawCount - accepted.size).coerceAtLeast(0),
            meanIbiMillis = mean,
            rmssdMillis = rmssd,
            sdnnMillis = sdnn,
            ibiCoverage = coverage,
            signalQuality = signalQuality,
            movementBucketCount = movement.first,
            movementCoverage = movement.second,
            movementVarianceStepsPerMinuteSquared = movement.third
        )
    }

    private fun removeArtefacts(samples: List<IbiMesspunkt>): List<IbiMesspunkt> {
        if (samples.size < 5) return samples
        return samples.filterIndexed { index, sample ->
            val from = maxOf(0, index - 2)
            val to = minOf(samples.lastIndex, index + 2)
            val neighbours = samples.subList(from, to + 1)
                .map { it.intervalMillis }
                .sorted()
            val median = neighbours[neighbours.size / 2]
            val limit = maxOf(ARTEFACT_ABSOLUTE_LIMIT_MILLIS, median * ARTEFACT_RELATIVE_LIMIT)
            kotlin.math.abs(sample.intervalMillis - median) <= limit
        }
    }

    private fun movementFeatures(
        stepIntervals: List<StepIntervalSample>,
        startEpochMillis: Long,
        endEpochMillis: Long,
        bucketMillis: Long
    ): Triple<Int, Double, Double?> {
        val bucketCount = ((endEpochMillis - startEpochMillis + bucketMillis - 1L) / bucketMillis).toInt()
        val buckets = MutableList(bucketCount) { 0L }
        val occupied = BooleanArray(bucketCount)
        stepIntervals.forEach { interval ->
            if (interval.endEpochMillis > startEpochMillis && interval.endEpochMillis <= endEpochMillis &&
                interval.startEpochMillis < interval.endEpochMillis && interval.steps >= 0L
            ) {
                val index = ((interval.endEpochMillis - startEpochMillis - 1L) / bucketMillis)
                    .toInt()
                    .coerceIn(0, bucketCount - 1)
                buckets[index] = (buckets[index] + interval.steps).coerceAtMost(Long.MAX_VALUE)
                occupied[index] = true
            }
        }
        val occupiedCount = occupied.count { it }
        val coverage = if (bucketCount == 0) 0.0 else occupiedCount.toDouble() / bucketCount
        if (occupiedCount < 3) return Triple(bucketCount, coverage, null)

        // Only buckets with actual platform data participate; missing buckets are
        // unknown, not fabricated zero-movement observations.
        val rates = buckets.indices.filter { occupied[it] }.map { index ->
            val bucketStart = startEpochMillis + index * bucketMillis
            val bucketEnd = minOf(endEpochMillis, bucketStart + bucketMillis)
            val minutes = (bucketEnd - bucketStart).toDouble() / 60_000.0
            if (minutes <= 0.0) 0.0 else buckets[index].toDouble() / minutes
        }
        val mean = rates.average()
        val variance = rates.sumOf { (it - mean) * (it - mean) } / rates.size
        return Triple(bucketCount, coverage, variance)
    }
}
