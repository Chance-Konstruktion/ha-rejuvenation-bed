package net.schanz.rejuvenationbed.watch.analysis

import net.schanz.rejuvenationbed.watch.health.IbiMesspunkt
import net.schanz.rejuvenationbed.watch.health.StepIntervalSample
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SleepHrvExtractorTest {
    @Test
    fun computesRmssdSdnnCoverageAndMovementVariance() {
        val start = 1_000_000L
        val end = start + 30L * 60L * 1000L
        val ibis = buildList {
            repeat(1_800) { index ->
                val interval = when (index % 4) {
                    0 -> 820.0
                    1 -> 840.0
                    2 -> 810.0
                    else -> 830.0
                }
                add(IbiMesspunkt(start + (index + 1L) * 1_000L, interval, 0.99))
            }
        }
        val steps = listOf(
            StepIntervalSample(start, start + 300_000L, 0),
            StepIntervalSample(start + 300_000L, start + 600_000L, 2),
            StepIntervalSample(start + 600_000L, start + 900_000L, 1),
            StepIntervalSample(start + 900_000L, start + 1_200_000L, 8),
            StepIntervalSample(start + 1_200_000L, start + 1_500_000L, 3),
            StepIntervalSample(start + 1_500_000L, end, 0)
        )

        val result = SleepHrvExtractor.extract(ibis, steps, start, end)

        assertEquals(1_800, result.rawIbiCount)
        assertEquals(1_800, result.acceptedIbiCount)
        assertNotNull(result.rmssdMillis)
        assertNotNull(result.sdnnMillis)
        assertTrue(result.ibiCoverage > 0.80)
        assertEquals(1.0, result.signalQuality, 0.0001)
        assertNotNull(result.movementVarianceStepsPerMinuteSquared)
        assertTrue(result.hasReliableIbi)
    }

    @Test
    fun rejectsPhysiologicallyImplausibleLowQualityAndLocalOutlierIntervals() {
        val start = 0L
        val end = 600_000L
        val samples = buildList {
            repeat(600) { index ->
                add(IbiMesspunkt((index + 1L) * 1_000L, 850.0, 0.95))
            }
            add(IbiMesspunkt(601_000L, 1_900.0, 0.95))
            add(IbiMesspunkt(602_000L, 850.0, 0.10))
            add(IbiMesspunkt(603_000L, 2_500.0, 0.95))
        }

        val result = SleepHrvExtractor.extract(samples, emptyList(), start, end)

        assertEquals(600, result.acceptedIbiCount)
        assertEquals(600, result.rawIbiCount)
        assertFalse(result.hasReliableIbi)
    }

    @Test
    fun movementVarianceIsUnknownWithoutThreeObservedBuckets() {
        val start = 0L
        val steps = listOf(StepIntervalSample(0L, 60_000L, 4), StepIntervalSample(60_000L, 120_000L, 8))
        val result = SleepHrvExtractor.extract(emptyList(), steps, start, 1_800_000L)
        assertEquals(2.0 / 6.0, result.movementCoverage, 0.0001)
        assertEquals(null, result.movementVarianceStepsPerMinuteSquared)
    }

    @Test
    fun emptyInputsProduceUnknownQualityWithoutThrowing() {
        val result = SleepHrvExtractor.extract(emptyList(), emptyList(), 0L, 1_800_000L)
        assertEquals(0, result.acceptedIbiCount)
        assertEquals(0.0, result.ibiCoverage, 0.0)
        assertEquals(0.0, result.signalQuality, 0.0)
        assertFalse(result.hasReliableIbi)
    }
}
