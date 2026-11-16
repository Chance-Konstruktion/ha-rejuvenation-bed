package net.schanz.rejuvenationbed.watch.sleep

import net.schanz.rejuvenationbed.watch.analysis.SleepHrvFeatures
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * #8/Ziel C: „unbekannt“ ohne Wort ist für niemanden brauchbar — der Schätzer
 * muss benennen, WARUM keine Phase da ist (Schalter AUS / keine IBI /
 * zu wenige IBI < 120 / Abdeckung / Güte), und eine getroffene Regel muss
 * benennbar sein. Die Anzeige greift diese Worte 1:1 auf.
 */
class SleepStageEstimatorGrundTest {

    private fun features(
        raw: Int,
        accepted: Int = raw,
        coverage: Double = 0.95,
        signalQuality: Double = 0.99,
        rmssd: Double = 70.0,
        sdnn: Double = 60.0,
        movementCoverage: Double = 1.0,
        movementVariance: Double? = 1.0
    ) = SleepHrvFeatures(
        startEpochMillis = 1_000L,
        endEpochMillis = 1_801_000L,
        rawIbiCount = raw,
        acceptedIbiCount = accepted,
        rejectedIbiCount = raw - accepted,
        meanIbiMillis = 960.0,
        rmssdMillis = rmssd,
        sdnnMillis = sdnn,
        ibiCoverage = coverage,
        signalQuality = signalQuality,
        movementBucketCount = 6,
        movementCoverage = movementCoverage,
        movementVarianceStepsPerMinuteSquared = movementVariance
    )

    private val jetzt = 1_800_000_000_000L

    @Test
    fun schalterAusWirdBenannt() {
        val grund = SleepStageEstimator.estimate(features(raw = 1_800), jetzt, enabled = false).grund
        assertEquals("Versuch ausgeschaltet (Schalter AUS)", grund)
    }

    @Test
    fun keineIbiWirdBenannt() {
        // Die Nacht 15./16.11.: ibi_sample leer — genau dieser Fall muss sichtbar sein.
        val grund = SleepStageEstimator.estimate(features(raw = 0), jetzt, enabled = true).grund
        assertEquals("keine IBI vorhanden", grund)
    }

    @Test
    fun zuWenigeIbiWirdBenanntMitZahl() {
        val grund = SleepStageEstimator.estimate(features(raw = 87), jetzt, enabled = true).grund
        assertEquals("zu wenige IBI (87 < 120)", grund)
    }

    @Test
    fun geringeAbdeckungWirdBenannt() {
        val grund = SleepStageEstimator.estimate(features(raw = 1_800, coverage = 0.4), jetzt, enabled = true).grund
        assertEquals("IBI-Abdeckung zu gering", grund)
    }

    @Test
    fun geringeGueteWirdBenannt() {
        val grund = SleepStageEstimator.estimate(
            features(raw = 1_800, signalQuality = 0.5), jetzt, enabled = true
        ).grund
        assertEquals("IBI-Signalgüte zu gering", grund)
    }

    @Test
    fun fehlendeBewegungWirdBenannt() {
        val grund = SleepStageEstimator.estimate(
            features(raw = 1_800, movementCoverage = 0.2), jetzt, enabled = true
        ).grund
        assertEquals("Bewegungsdaten unvollständig", grund)
    }

    @Test
    fun eineTreffendeRegelTraegtRegelKennung() {
        val estimate = SleepStageEstimator.estimate(
            features(raw = 1_800, movementVariance = 1.0), jetzt, enabled = true
        )
        assertEquals(SleepStage.DEEP, estimate.stage)
        assertTrue(
            "die Kennung muss die getroffene Regel nennen, war: '${estimate.grund}'",
            estimate.grund.startsWith("regel: ")
        )
    }
}
