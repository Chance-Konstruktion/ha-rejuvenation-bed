package net.schanz.rejuvenationbed.watch.sleep

import net.schanz.rejuvenationbed.watch.analysis.SleepFeatureWindow
import net.schanz.rejuvenationbed.watch.analysis.SleepHrvFeatures

/**
 * Die Schätzer-Kette des Schlaf-Blatts als reine JVM-Funktion:
 * mit verlässlicher IBI der `m2-rules-0.1`-Schätzer, ohne IBI die grobe
 * Puls+Bewegungs-Schätzung. Beide Zweige stehen nur hinter dem
 * Versuchs-Schalter; der Schalter-Wert wird an JEDEN Zweig weitergereicht.
 *
 * Fund 39678 an !19: die Kette hing im Schlaf-Blatt und der grobe Zweig
 * verlor `enabled` (Default false) — mit Schalter EIN blieb alles
 * „Schätzer ausgeschaltet“, die grobe Schätzung war nie erreichbar. Hier
 * ist der Fall JVM-geprüft; das Schlaf-Blatt ruft nur noch diese Funktion.
 */
object SleepEstimatorWahl {
    fun schaetzung(
        hrv: SleepHrvFeatures,
        fenster: SleepFeatureWindow?,
        hatBewegungsdaten: Boolean,
        jetztEpochMillis: Long,
        experimentAktiv: Boolean
    ): SleepStageEstimate = when {
        !experimentAktiv -> SleepStageEstimator.estimate(hrv, jetztEpochMillis, enabled = false)
        hrv.hasReliableIbi -> SleepStageEstimator.estimate(hrv, jetztEpochMillis, enabled = true)
        else -> PulsBewegungsEstimator.estimate(
            window = fenster,
            hatBewegungsdaten = hatBewegungsdaten,
            nowEpochMillis = jetztEpochMillis,
            // Genau die Heilung von Fund 39678: dieser Zweig wird nur bei
            // experimentAktiv == true erreicht — er muss das Experiment
            // ausdrücklich einschalten, sonst bleibt er dauerhaft UNKNOWN.
            enabled = true
        )
    }
}
