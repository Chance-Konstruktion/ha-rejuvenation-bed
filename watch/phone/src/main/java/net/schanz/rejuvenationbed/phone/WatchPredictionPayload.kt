package net.schanz.rejuvenationbed.phone
import net.schanz.rejuvenationbed.watch.analysis.SleepPredictionWire
import net.schanz.rejuvenationbed.watch.analysis.SleepStagePrediction
import net.schanz.rejuvenationbed.watch.sleep.SleepStage
import org.json.JSONObject

data class WatchPredictionPayload(
    val startEpochMillis: Long,
    val endEpochMillis: Long,
    val algorithmVersion: String,
    val predictions: List<SleepStagePrediction>
) {
    init {
        require(startEpochMillis >= 0L)
        require(endEpochMillis > startEpochMillis)
        require(algorithmVersion.isNotBlank())
        require(predictions.isNotEmpty())
        require(predictions.all {
            it.measuredAtEpochMillis in startEpochMillis..endEpochMillis && it.algorithmVersion == algorithmVersion
        })
    }

    companion object {
        fun decode(json: String): WatchPredictionPayload {
            require(json.toByteArray(Charsets.UTF_8).size <= SleepPredictionWire.MAX_MESSAGE_BYTES)
            val root = JSONObject(json)
            require(root.getString("schema") == SleepPredictionWire.SCHEMA) { "Unbekanntes Schema" }
            val algorithm = root.getString("algorithmVersion")
            val start = root.getLong("startEpochMillis")
            val end = root.getLong("endEpochMillis")
            val array = root.getJSONArray("predictions")
            require(array.length() in 1..180) { "Ungültige Anzahl an Vorhersagen" }
            val predictions = buildList {
                for (index in 0 until array.length()) {
                    val item = array.getJSONObject(index)
                    val prediction = SleepStagePrediction(
                        measuredAtEpochMillis = item.getLong("measuredAtEpochMillis"),
                        stage = SleepStage.fromWireValue(item.getString("stage")),
                        confidence = item.getDouble("confidence"),
                        sampleCoverage = item.getDouble("sampleCoverage"),
                        algorithmVersion = item.getString("algorithmVersion")
                    )
                    require(prediction.stage != SleepStage.UNKNOWN || prediction.confidence == 0.0)
                    add(prediction)
                }
            }
            return WatchPredictionPayload(start, end, algorithm, predictions)
        }
    }
}
