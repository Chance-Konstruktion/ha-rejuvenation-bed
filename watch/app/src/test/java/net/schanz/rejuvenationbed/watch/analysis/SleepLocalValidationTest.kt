package net.schanz.rejuvenationbed.watch.analysis

import net.schanz.rejuvenationbed.watch.health.IbiMesspunkt
import net.schanz.rejuvenationbed.watch.health.StepIntervalSample
import net.schanz.rejuvenationbed.watch.sleep.SleepStage
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class SleepLocalValidationTest {
    @Test
    fun buildsFiveMinutePredictionsFromRollingThirtyMinuteWindows() {
        val start = 0L
        val end = 60L * 60L * 1000L
        val ibi = buildList {
            repeat(3_600) { index ->
                val interval = when (index % 4) {
                    0 -> 850.0
                    1 -> 890.0
                    2 -> 820.0
                    else -> 870.0
                }
                add(IbiMesspunkt((index + 1L) * 1_000L, interval, 0.99))
            }
        }
        val steps = (0 until 12).map { index ->
            StepIntervalSample(
                startEpochMillis = start + index * 300_000L,
                endEpochMillis = start + (index + 1L) * 300_000L,
                steps = if (index % 3 == 0) 2 else 0
            )
        }

        val predictions = SleepLocalValidation.predictions(
            ibiSamples = ibi,
            stepIntervals = steps,
            startEpochMillis = start,
            endEpochMillis = end,
            enabled = true
        )

        assertEquals(7, predictions.size)
        assertEquals(30L * 60L * 1000L, predictions.first().measuredAtEpochMillis)
        assertEquals(end, predictions.last().measuredAtEpochMillis)
        assertTrue(predictions.all { it.stage != SleepStage.UNKNOWN })
    }

    @Test
    fun disabledExperimentProducesUnknownPredictionsForEveryWindow() {
        val predictions = SleepLocalValidation.predictions(
            ibiSamples = emptyList(),
            stepIntervals = emptyList(),
            startEpochMillis = 0L,
            endEpochMillis = 60L * 60L * 1000L,
            enabled = false
        )
        assertEquals(7, predictions.size)
        assertTrue(predictions.all { it.stage == SleepStage.UNKNOWN })
    }

    @Test
    fun comparesTheRollingEstimateSeriesAgainstSyntheticHealthConnectStages() {
        val start = 0L
        val end = 60L * 60L * 1000L
        val ibis = buildList {
            repeat(3_600) { index ->
                val interval = when (index % 4) {
                    0 -> 850.0
                    1 -> 890.0
                    2 -> 820.0
                    else -> 870.0
                }
                add(IbiMesspunkt((index + 1L) * 1_000L, interval, 0.99))
            }
        }
        val steps = (0 until 12).map { index ->
            StepIntervalSample(
                startEpochMillis = start + index * 300_000L,
                endEpochMillis = start + (index + 1L) * 300_000L,
                steps = if (index % 3 == 0) 2 else 0
            )
        }
        val references = listOf(
            SleepStageReferenceInterval(start, end, SleepStage.LIGHT)
        )

        val result = SleepLocalValidation.compare(
            ibiSamples = ibis,
            stepIntervals = steps,
            references = references,
            startEpochMillis = start,
            endEpochMillis = end,
            enabled = true
        )

        // The first 30 minutes are only the lookback used to build the first estimate.
        assertEquals(6, result.comparedWindows)
        assertTrue(result.confusionMatrix.values.sumOf { row -> row.values.sum() } == 6)
    }
}
