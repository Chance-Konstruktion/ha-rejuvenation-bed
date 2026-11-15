package net.schanz.rejuvenationbed.watch.analysis

import net.schanz.rejuvenationbed.watch.sleep.SleepStage
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SleepStageAgreementTest {
    @Test
    fun perfectSyntheticAgreementHasAccuracyAndKappaOne() {
        val start = 0L
        val predictions = listOf(
            SleepStagePrediction(0L, SleepStage.LIGHT),
            SleepStagePrediction(300_000L, SleepStage.DEEP),
            SleepStagePrediction(600_000L, SleepStage.REM)
        )
        val references = listOf(
            SleepStageReferenceInterval(0L, 300_000L, SleepStage.LIGHT),
            SleepStageReferenceInterval(300_000L, 600_000L, SleepStage.DEEP),
            SleepStageReferenceInterval(600_000L, 900_000L, SleepStage.REM)
        )

        val result = SleepStageAgreement.compare(
            predictions, references, start, 900_000L,
            bucketMillis = 300_000L,
            maximumPredictionAgeMillis = 300_000L
        )

        assertEquals(3, result.comparedWindows)
        assertEquals(1.0, result.accuracy!!, 0.0)
        assertEquals(1.0, result.cohensKappa!!, 0.0)
    }

    @Test
    fun unknownReferenceIntervalsAreExcludedAndUnknownPredictionIsCounted() {
        val result = SleepStageAgreement.compare(
            predictions = listOf(
                SleepStagePrediction(0L, SleepStage.UNKNOWN),
                SleepStagePrediction(300_000L, SleepStage.AWAKE)
            ),
            references = listOf(
                SleepStageReferenceInterval(0L, 300_000L, SleepStage.LIGHT),
                SleepStageReferenceInterval(300_000L, 600_000L, SleepStage.UNKNOWN)
            ),
            startEpochMillis = 0L,
            endEpochMillis = 600_000L,
            bucketMillis = 300_000L,
            maximumPredictionAgeMillis = 300_000L
        )

        assertEquals(1, result.comparedWindows)
        assertEquals(1, result.confusionMatrix.getValue(SleepStage.LIGHT).getValue(SleepStage.UNKNOWN))
        assertEquals(0.0, result.accuracy!!, 0.0)
        assertNotNull(result.cohensKappa)
    }

    @Test
    fun missingPredictionProducesNoScoreInsteadOfInventingOne() {
        val result = SleepStageAgreement.compare(
            predictions = emptyList(),
            references = listOf(SleepStageReferenceInterval(0L, 300_000L, SleepStage.LIGHT)),
            startEpochMillis = 0L,
            endEpochMillis = 300_000L,
            bucketMillis = 300_000L
        )
        assertEquals(0, result.comparedWindows)
        assertNull(result.accuracy)
        assertNull(result.cohensKappa)
        assertTrue(result.confusionMatrix.values.all { row -> row.values.all { it == 0 } })
    }
}
