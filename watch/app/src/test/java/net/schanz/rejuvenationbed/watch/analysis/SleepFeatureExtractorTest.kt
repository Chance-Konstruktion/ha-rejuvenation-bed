package net.schanz.rejuvenationbed.watch.analysis

import net.schanz.rejuvenationbed.watch.health.HeartRateSample
import net.schanz.rejuvenationbed.watch.health.StepIntervalSample
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SleepFeatureExtractorTest {
    @Test
    fun aggregatesHeartRateAndStepDeltasIntoCompletedWindows() {
        val heartRate = listOf(
            hr(1, 60.0), hr(6, 62.0), hr(11, 64.0),
            hr(16, 66.0), hr(21, 64.0), hr(26, 62.0)
        )
        val steps = listOf(
            step(0, 10, 8),
            step(10, 20, 3),
            step(20, 30, 5)
        )

        val windows = SleepFeatureExtractor.extract(
            heartRateSamples = heartRate,
            stepIntervals = steps,
            nowEpochMillis = 60 * MINUTE
        )

        assertEquals(2, windows.size)
        val first = windows.first()
        assertEquals(6, first.heartRateSampleCount)
        assertEquals(6, first.heartRateOccupiedBuckets)
        assertEquals(0.0, first.heartRateBucketOccupancy - 1.0, 0.0001)
        assertEquals(63.0, first.heartRateMeanBpm!!, 0.0001)
        assertEquals(63.0, first.heartRateMedianBpm!!, 0.0001)
        assertEquals(60.0, first.heartRateMinBpm!!, 0.0001)
        assertEquals(66.0, first.heartRateMaxBpm!!, 0.0001)
        assertEquals(16L, first.stepsInWindow)
        assertEquals(3, first.stepIntervalCount)
        assertTrue(first.hasMinimumHeartRateFeatures)
    }

    @Test
    fun sparseSamplesDoNotPassMinimumFeatureGate() {
        val samples = listOf(hr(1, 60.0), hr(2, 61.0), hr(3, 62.0))
        val windows = SleepFeatureExtractor.extract(
            heartRateSamples = samples,
            stepIntervals = emptyList(),
            nowEpochMillis = 60 * MINUTE
        )

        val firstWindow = windows.first()
        assertEquals(3, firstWindow.heartRateSampleCount)
        assertEquals(1, firstWindow.heartRateOccupiedBuckets)
        assertFalse(firstWindow.hasMinimumHeartRateFeatures)
    }

    @Test
    fun incompleteCurrentWindowIsNotPublished() {
        val samples = listOf(hr(1, 60.0), hr(6, 61.0), hr(11, 62.0))
        val windows = SleepFeatureExtractor.extract(
            heartRateSamples = samples,
            stepIntervals = emptyList(),
            nowEpochMillis = 20 * MINUTE
        )
        assertTrue(windows.isEmpty())
    }

    @Test
    fun invalidAndFutureHeartRateSamplesAreIgnored() {
        val samples = listOf(
            hr(1, 60.0),
            hr(6, Double.NaN),
            hr(11, 250.0),
            HeartRateSample(61 * MINUTE, 65.0)
        )
        val windows = SleepFeatureExtractor.extract(
            heartRateSamples = samples,
            stepIntervals = emptyList(),
            nowEpochMillis = 60 * MINUTE
        )
        val firstWindow = windows.first()
        assertEquals(1, firstWindow.heartRateSampleCount)
        assertFalse(firstWindow.hasMinimumHeartRateFeatures)
    }

    private fun hr(minutes: Long, bpm: Double) =
        HeartRateSample(minutes * MINUTE, bpm)

    private fun step(startMinutes: Long, endMinutes: Long, count: Long) =
        StepIntervalSample(startMinutes * MINUTE, endMinutes * MINUTE, count)

    private companion object {
        const val MINUTE = 60_000L
    }
}
