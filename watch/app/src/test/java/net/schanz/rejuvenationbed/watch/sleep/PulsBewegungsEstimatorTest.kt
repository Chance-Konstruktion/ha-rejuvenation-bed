package net.schanz.rejuvenationbed.watch.sleep

import net.schanz.rejuvenationbed.watch.analysis.SleepFeatureWindow
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Grobe Puls+Bewegungs-Schätzung: deterministische Hypothesen-Regeln auf
 * vollständigen 30-Minuten-Fenstern. Die Schwellen sind bewusst grob und
 * unvalidiert — geprüft wird hier nur, dass die Regeln reproduzierbar sind,
 * fail-closed ohne ausreichende Daten bleiben und die Ausgabe die
 * Kennung „puls-bewegung-grob-0.1“ trägt.
 */
class PulsBewegungsEstimatorTest {

    private fun fenster(
        mean: Double?,
        spread: Double?,
        steps: Long = 0L,
        sampleCount: Int = 180,
        occupiedBuckets: Int = 6,
        bucketCount: Int = 6
    ): SleepFeatureWindow = SleepFeatureWindow(
        startEpochMillis = 3_600_000L,
        endEpochMillis = 3_600_000L + 30L * 60L * 1000L,
        heartRateSampleCount = sampleCount,
        heartRateOccupiedBuckets = occupiedBuckets,
        heartRateBucketCount = bucketCount,
        heartRateMeanBpm = mean,
        heartRateMedianBpm = mean,
        heartRateStdDevBpm = spread,
        heartRateMinBpm = mean?.let { it - (spread ?: 2.0) },
        heartRateMaxBpm = mean?.let { it + (spread ?: 2.0) },
        stepsInWindow = steps,
        stepIntervalCount = if (steps > 0L) 2 else 0
    )

    private val jetzt = 3_600_000L + 30L * 60L * 1000L + 60_000L

    @Test
    fun ausgeschaltetBleibtUnknown() {
        val schaetzung = PulsBewegungsEstimator.estimate(fenster(52.0, 4.0), true, jetzt, enabled = false)
        assertEquals(SleepStage.UNKNOWN, schaetzung.stage)
        assertEquals(0.0, schaetzung.confidence, 1e-9)
        assertEquals(PulsBewegungsEstimator.ALGORITHM_VERSION, schaetzung.algorithmVersion)
    }

    @Test
    fun ohneFensterBleibtUnknown() {
        val schaetzung = PulsBewegungsEstimator.estimate(null, true, jetzt, enabled = true)
        assertEquals(SleepStage.UNKNOWN, schaetzung.stage)
        assertEquals(0.0, schaetzung.sampleCoverage, 1e-9)
    }

    @Test
    fun zuWenigPulsBleibtUnknown() {
        val schaetzung = PulsBewegungsEstimator.estimate(
            fenster(52.0, 4.0, sampleCount = 2, occupiedBuckets = 1), true, jetzt, enabled = true
        )
        assertEquals(SleepStage.UNKNOWN, schaetzung.stage)
        assertTrue(schaetzung.sampleCoverage < 0.2)
    }

    @Test
    fun geringePulsAbdeckungBleibtUnknown() {
        val schaetzung = PulsBewegungsEstimator.estimate(
            fenster(52.0, 4.0, occupiedBuckets = 2, bucketCount = 6), true, jetzt, enabled = true
        )
        assertEquals(SleepStage.UNKNOWN, schaetzung.stage)
        assertEquals(2.0 / 6.0, schaetzung.sampleCoverage, 1e-9)
    }

    @Test
    fun ohneBewegungsdatenBleibtUnknown() {
        val schaetzung = PulsBewegungsEstimator.estimate(fenster(52.0, 4.0), false, jetzt, enabled = true)
        assertEquals(SleepStage.UNKNOWN, schaetzung.stage)
    }

    @Test
    fun gehenImFensterGiltAlsWach() {
        val schaetzung = PulsBewegungsEstimator.estimate(
            fenster(72.0, 9.0, steps = 90), true, jetzt, enabled = true
        )
        assertEquals(SleepStage.AWAKE, schaetzung.stage)
        assertEquals(0.85, schaetzung.confidence, 1e-9)
    }

    @Test
    fun hoheStreuungGiltAlsWach() {
        val schaetzung = PulsBewegungsEstimator.estimate(
            fenster(68.0, 13.0), true, jetzt, enabled = true
        )
        assertEquals(SleepStage.AWAKE, schaetzung.stage)
    }

    @Test
    fun hoherMittelwertGiltAlsWach() {
        val schaetzung = PulsBewegungsEstimator.estimate(
            fenster(91.0, 5.0), true, jetzt, enabled = true
        )
        assertEquals(SleepStage.AWAKE, schaetzung.stage)
    }

    @Test
    fun tieferRuhrigerPulsGiltAlsTief() {
        val schaetzung = PulsBewegungsEstimator.estimate(
            fenster(52.0, 4.0), true, jetzt, enabled = true
        )
        assertEquals(SleepStage.DEEP, schaetzung.stage)
        assertEquals(0.78, schaetzung.confidence, 1e-9)
    }

    @Test
    fun ruhenderPulsMitStreuungGiltAlsRem() {
        val schaetzung = PulsBewegungsEstimator.estimate(
            fenster(72.0, 7.0), true, jetzt, enabled = true
        )
        assertEquals(SleepStage.REM, schaetzung.stage)
    }

    @Test
    fun mittlererPulsGiltAlsLeicht() {
        val schaetzung = PulsBewegungsEstimator.estimate(
            fenster(62.0, 6.0), true, jetzt, enabled = true
        )
        assertEquals(SleepStage.LIGHT, schaetzung.stage)
    }

    @Test
    fun keinePassendeRegelBleibtUnknown() {
        val schaetzung = PulsBewegungsEstimator.estimate(
            fenster(58.0, 9.0), true, jetzt, enabled = true
        )
        assertEquals(SleepStage.UNKNOWN, schaetzung.stage)
    }

    @Test
    fun ausreichendeSchaetzungIstBenutzbar() {
        val schaetzung = PulsBewegungsEstimator.estimate(
            fenster(52.0, 4.0), true, jetzt, enabled = true
        )
        assertTrue(schaetzung.isUsable(nowEpochMillis = jetzt))
        assertFalse(schaetzung.isUsable(nowEpochMillis = jetzt + 300_000L))
    }

    @Test
    fun rohigeBewegungAnDerGrenze() {
        // 60 Schritte in 30 min = 2,0/min → Schwelle „wach“ (>=).
        val anGrenze = PulsBewegungsEstimator.estimate(fenster(72.0, 9.0, steps = 60), true, jetzt, enabled = true)
        assertEquals(SleepStage.AWAKE, anGrenze.stage)
        // 15 Schritte in 30 min = 0,5/min → ruhig liegend, hier Tiefschlaf-Bereich.
        val ruhig = PulsBewegungsEstimator.estimate(fenster(52.0, 4.0, steps = 15), true, jetzt, enabled = true)
        assertEquals(SleepStage.DEEP, ruhig.stage)
    }
}
