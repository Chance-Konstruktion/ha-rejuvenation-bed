package net.schanz.rejuvenationbed.watch.sleep

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SleepStageTest {
    @Test
    fun mapsHomeAssistantWireValues() {
        assertEquals(SleepStage.AWAKE, SleepStage.fromWireValue("awake"))
        assertEquals(SleepStage.LIGHT, SleepStage.fromWireValue("light"))
        assertEquals(SleepStage.DEEP, SleepStage.fromWireValue("deep"))
        assertEquals(SleepStage.REM, SleepStage.fromWireValue("rem"))
    }

    @Test
    fun unknownOrUnexpectedValuesFailClosed() {
        assertEquals(SleepStage.UNKNOWN, SleepStage.fromWireValue(null))
        assertEquals(SleepStage.UNKNOWN, SleepStage.fromWireValue(" not-a-stage "))
    }

    @Test
    fun rejectsLowConfidenceOrPoorCoverage() {
        val estimate = estimate(confidence = 0.42, coverage = 0.95)
        assertFalse(estimate.isUsable(nowEpochMillis = NOW))
        val poorCoverage = estimate(confidence = 0.95, coverage = 0.30)
        assertFalse(poorCoverage.isUsable(nowEpochMillis = NOW))
    }

    @Test
    fun rejectsStaleAndFutureMeasurements() {
        assertFalse(estimate(measuredAt = NOW - 180_000).isUsable(nowEpochMillis = NOW))
        assertFalse(estimate(measuredAt = NOW + 10_000).isUsable(nowEpochMillis = NOW))
    }

    @Test
    fun acceptsRecentHighQualityEstimate() {
        assertTrue(estimate().isUsable(nowEpochMillis = NOW))
    }

    private fun estimate(
        confidence: Double = 0.91,
        coverage: Double = 0.94,
        measuredAt: Long = NOW
    ) = SleepStageEstimate(
        stage = SleepStage.REM,
        confidence = confidence,
        sampleCoverage = coverage,
        measuredAtEpochMillis = measuredAt,
        algorithmVersion = "m0-test"
    )

    private companion object {
        const val NOW = 1_800_000_000_000L
    }
}
