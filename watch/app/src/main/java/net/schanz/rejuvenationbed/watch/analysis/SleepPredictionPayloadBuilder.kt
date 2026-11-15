package net.schanz.rejuvenationbed.watch.analysis

import android.content.Context
import net.schanz.rejuvenationbed.watch.health.HeartRateSampleStore
import net.schanz.rejuvenationbed.watch.health.IbiMesspunktSpeicher
import net.schanz.rejuvenationbed.watch.sleep.SleepStageEstimator
import org.json.JSONArray
import org.json.JSONObject

/** Builds the phone-comparison payload from local derived estimates only. */
object SleepPredictionPayloadBuilder {
    const val LOOKBACK_MILLIS = 10L * 60L * 60L * 1000L

    fun build(context: Context, enabled: Boolean, nowEpochMillis: Long = System.currentTimeMillis()): String {
        require(enabled) { "Der Schlafphasen-Versuch muss ausdrücklich eingeschaltet sein" }
        require(nowEpochMillis >= LOOKBACK_MILLIS)
        val start = nowEpochMillis - LOOKBACK_MILLIS
        val end = nowEpochMillis
        val store = IbiMesspunktSpeicher(context.applicationContext)
        val ibi = try {
            store.lesen(start, end)
        } finally {
            store.close()
        }
        val steps = HeartRateSampleStore.stepIntervals(context.applicationContext)
        val predictions = SleepLocalValidation.predictions(
            ibiSamples = ibi,
            stepIntervals = steps,
            startEpochMillis = start,
            endEpochMillis = end,
            enabled = true
        )
        require(predictions.isNotEmpty()) { "Noch kein vollständiges 30-Minuten-Fenster vorhanden" }
        val algorithmVersions = predictions.mapNotNull { it.algorithmVersion }.distinct()
        require(algorithmVersions.size == 1 && algorithmVersions.single() == SleepStageEstimator.ALGORITHM_VERSION) {
            "Schätzungen tragen keine einheitliche Algorithmusversion"
        }
        val comparisonStart = predictions.first().measuredAtEpochMillis
        val comparisonEnd = predictions.last().measuredAtEpochMillis
        val array = JSONArray().apply {
            predictions.forEach { prediction ->
                put(
                    JSONObject()
                        .put("measuredAtEpochMillis", prediction.measuredAtEpochMillis)
                        .put("stage", prediction.stage.wireValue)
                        .put("confidence", prediction.confidence)
                        .put("sampleCoverage", prediction.sampleCoverage)
                        .put("algorithmVersion", prediction.algorithmVersion)
                )
            }
        }
        return JSONObject()
            .put("schema", SleepPredictionWire.SCHEMA)
            .put("algorithmVersion", algorithmVersions.single())
            .put("startEpochMillis", comparisonStart)
            .put("endEpochMillis", comparisonEnd)
            .put("predictions", array)
            .toString()
    }
}
