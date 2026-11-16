package net.schanz.rejuvenationbed.watch.sleep

import net.schanz.rejuvenationbed.watch.analysis.SleepFeatureWindow
import net.schanz.rejuvenationbed.watch.analysis.SleepHrvFeatures
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Fund 39678 an !19 (rot→grün): das Schlaf-Blatt rief den groben Schätzer
 * direkt und verlor `enabled` (Default false) — mit Schalter EIN und ohne IBI
 * blieb dauerhaft „unbekannt · Schätzer ausgeschaltet“, die grobe Schätzung
 * war nie erreichbar. Diese Prüfung stellt GENAU diesen Fall: Schalter EIN,
 * keine IBI → die grobe Puls+Bewegungs-Schätzung muss sichtbar (benutzbar)
 * sein. Vor der Heilung rot, danach grün.
 */
class SleepEstimatorWahlTest {
    private val jetzt = 1_800_000_000_000L

    /** Nacht-Szenario wie 15./16.11.: ibi_sample leer (keine IBI). */
    private fun ohneIbi() = SleepHrvFeatures(
        startEpochMillis = 1_000L,
        endEpochMillis = 1_801_000L,
        rawIbiCount = 0,
        acceptedIbiCount = 0,
        rejectedIbiCount = 0,
        meanIbiMillis = null,
        rmssdMillis = null,
        sdnnMillis = null,
        ibiCoverage = 0.0,
        signalQuality = 0.0,
        movementBucketCount = 0,
        movementCoverage = 0.0,
        movementVarianceStepsPerMinuteSquared = null
    )

    /** Verlässliche IBI für den M2-Zweig der Kette. */
    private fun mitVerlaesslicherIbi() = SleepHrvFeatures(
        startEpochMillis = 1_000L,
        endEpochMillis = 1_801_000L,
        rawIbiCount = 1_800,
        acceptedIbiCount = 1_800,
        rejectedIbiCount = 0,
        meanIbiMillis = 960.0,
        rmssdMillis = 70.0,
        sdnnMillis = 60.0,
        ibiCoverage = 0.95,
        signalQuality = 0.99,
        movementBucketCount = 6,
        movementCoverage = 1.0,
        movementVarianceStepsPerMinuteSquared = 1.0
    )

    private fun fenster(mean: Double, spread: Double, steps: Long = 0L) = SleepFeatureWindow(
        startEpochMillis = 3_600_000L,
        endEpochMillis = 3_600_000L + 30L * 60L * 1000L,
        heartRateSampleCount = 180,
        heartRateOccupiedBuckets = 6,
        heartRateBucketCount = 6,
        heartRateMeanBpm = mean,
        heartRateMedianBpm = mean,
        heartRateStdDevBpm = spread,
        heartRateMinBpm = mean - spread,
        heartRateMaxBpm = mean + spread,
        stepsInWindow = steps,
        stepIntervalCount = if (steps > 0L) 2 else 0
    )

    @Test
    fun schalterEinOhneIbiZeigtDieGrobeSchaetzung() {
        val schaetzung = SleepEstimatorWahl.schaetzung(
            hrv = ohneIbi(),
            fenster = fenster(mean = 52.0, spread = 4.0),
            hatBewegungsdaten = true,
            jetztEpochMillis = jetzt,
            experimentAktiv = true
        )
        assertEquals(PulsBewegungsEstimator.ALGORITHM_VERSION, schaetzung.algorithmVersion)
        assertEquals(SleepStage.DEEP, schaetzung.stage)
        assertTrue(
            "die grobe Schätzung muss sichtbar (benutzbar) sein — Fund 39678",
            schaetzung.isUsable(nowEpochMillis = jetzt)
        )
    }

    @Test
    fun schalterAusBleibtUnknownMitM2Kennung() {
        val schaetzung = SleepEstimatorWahl.schaetzung(
            hrv = ohneIbi(),
            fenster = fenster(mean = 52.0, spread = 4.0),
            hatBewegungsdaten = true,
            jetztEpochMillis = jetzt,
            experimentAktiv = false
        )
        assertEquals(SleepStage.UNKNOWN, schaetzung.stage)
        assertEquals(SleepStageEstimator.ALGORITHM_VERSION, schaetzung.algorithmVersion)
    }

    @Test
    fun verlaesslicheIbiNimmtDenM2SchaetzerNichtDenGrob() {
        val schaetzung = SleepEstimatorWahl.schaetzung(
            hrv = mitVerlaesslicherIbi(),
            fenster = fenster(mean = 52.0, spread = 4.0),
            hatBewegungsdaten = true,
            jetztEpochMillis = jetzt,
            experimentAktiv = true
        )
        assertEquals(SleepStageEstimator.ALGORITHM_VERSION, schaetzung.algorithmVersion)
        assertEquals(SleepStage.DEEP, schaetzung.stage)
    }

    @Test
    fun grobeSchaetzungOhneBewegungsdatenBleibtUnknownMitGrund() {
        val schaetzung = SleepEstimatorWahl.schaetzung(
            hrv = ohneIbi(),
            fenster = fenster(mean = 52.0, spread = 4.0),
            hatBewegungsdaten = false,
            jetztEpochMillis = jetzt,
            experimentAktiv = true
        )
        assertEquals(SleepStage.UNKNOWN, schaetzung.stage)
        assertEquals("keine Bewegungsdaten", schaetzung.grund)
    }
}
