package net.schanz.rejuvenationbed.watch.sleep

import net.schanz.rejuvenationbed.watch.analysis.SleepHrvFeatures
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class SleepStageEstimatorTest {
    @Test
    fun isDisabledByDefaultAndAlwaysFailsClosedWithoutIbi() {
        val now = 1_800_000_000_000L
        val disabled = SleepStageEstimator.estimate(features(), now)
        assertEquals(SleepStage.UNKNOWN, disabled.stage)
        assertEquals(0.0, disabled.confidence, 0.0)

        val noIbi = SleepStageEstimator.estimate(features(accepted = 0, coverage = 0.0), now, enabled = true)
        assertEquals(SleepStage.UNKNOWN, noIbi.stage)
    }

    @Test
    fun highQualityDeepLikeSyntheticSignalProducesRepeatableCandidate() {
        val now = 1_800_000_000_000L
        val input = features(
            meanIbi = 960.0,
            rmssd = 70.0,
            sdnn = 60.0,
            movementVariance = 1.0
        )
        val first = SleepStageEstimator.estimate(input, now, enabled = true)
        val second = SleepStageEstimator.estimate(input, now, enabled = true)
        assertEquals(first, second)
        assertEquals(SleepStage.DEEP, first.stage)
        assertTrue(first.confidence >= SleepStageEstimator.MINIMUM_CONFIDENCE)
        assertEquals(SleepStageEstimator.ALGORITHM_VERSION, first.algorithmVersion)
    }

    @Test
    fun insufficientMovementCoverageRemainsUnknown() {
        val result = SleepStageEstimator.estimate(
            features(movementCoverage = 0.2),
            1_800_000_000_000L,
            enabled = true
        )
        assertEquals(SleepStage.UNKNOWN, result.stage)
    }

    private fun features(
        accepted: Int = 1_800,
        meanIbi: Double = 960.0,
        rmssd: Double = 70.0,
        sdnn: Double = 60.0,
        coverage: Double = 0.95,
        movementCoverage: Double = 1.0,
        movementVariance: Double? = 1.0
    ) = SleepHrvFeatures(
        startEpochMillis = 1_000L,
        endEpochMillis = 1_801_000L,
        rawIbiCount = accepted,
        acceptedIbiCount = accepted,
        rejectedIbiCount = 0,
        meanIbiMillis = meanIbi,
        rmssdMillis = if (accepted >= 2) rmssd else null,
        sdnnMillis = if (accepted >= 2) sdnn else null,
        ibiCoverage = coverage,
        signalQuality = if (accepted == 0) 0.0 else 0.99,
        movementBucketCount = 6,
        movementCoverage = movementCoverage,
        movementVarianceStepsPerMinuteSquared = movementVariance
    )
}
