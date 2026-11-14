package net.schanz.rejuvenationbed.watch.analysis

import net.schanz.rejuvenationbed.watch.sleep.SleepStage

/** One timestamped watch estimate. UNKNOWN remains a prediction class. */
data class SleepStagePrediction(
    val measuredAtEpochMillis: Long,
    val stage: SleepStage,
    val confidence: Double = 0.0,
    val sampleCoverage: Double = 0.0,
    val algorithmVersion: String? = null
) {
    init {
        require(measuredAtEpochMillis >= 0L)
        require(confidence in 0.0..1.0)
        require(sampleCoverage in 0.0..1.0)
        require(algorithmVersion == null || algorithmVersion.isNotBlank())
    }
}

/** A Health Connect SleepSessionRecord stage interval. */
data class SleepStageReferenceInterval(
    val startEpochMillis: Long,
    val endEpochMillis: Long,
    val stage: SleepStage
) {
    init {
        require(startEpochMillis >= 0L)
        require(endEpochMillis > startEpochMillis)
    }
}

data class SleepStageAgreementResult(
    val comparedWindows: Int,
    val accuracy: Double?,
    val cohensKappa: Double?,
    /** Rows are reference/actual; columns are estimated/predicted. */
    val confusionMatrix: Map<SleepStage, Map<SleepStage, Int>>
)

object SleepStageAgreement {
    val labels: List<SleepStage> = listOf(
        SleepStage.AWAKE,
        SleepStage.LIGHT,
        SleepStage.DEEP,
        SleepStage.REM,
        SleepStage.UNKNOWN
    )

    /**
     * Align estimates and Health Connect intervals to a fixed grid. A prediction
     * is carried forward only within [maximumPredictionAgeMillis]. Reference
     * UNKNOWN / generic SLEEPING intervals are excluded rather than guessed.
     */
    fun compare(
        predictions: List<SleepStagePrediction>,
        references: List<SleepStageReferenceInterval>,
        startEpochMillis: Long,
        endEpochMillis: Long,
        bucketMillis: Long = 5L * 60L * 1000L,
        maximumPredictionAgeMillis: Long = 10L * 60L * 1000L
    ): SleepStageAgreementResult {
        require(startEpochMillis >= 0L)
        require(endEpochMillis > startEpochMillis)
        require(bucketMillis > 0L)
        require(maximumPredictionAgeMillis >= 0L)

        val orderedPredictions = predictions
            .filter { it.measuredAtEpochMillis in startEpochMillis..endEpochMillis }
            .sortedBy { it.measuredAtEpochMillis }
        val matrix = labels.associateWith { actual ->
            labels.associateWith { 0 }.toMutableMap()
        }.toMutableMap()

        var compared = 0
        var correct = 0
        var bucketStart = startEpochMillis
        while (bucketStart < endEpochMillis) {
            val bucketEnd = minOf(endEpochMillis, bucketStart + bucketMillis)
            val midpoint = bucketStart + (bucketEnd - bucketStart) / 2L
            val actual = references.firstOrNull {
                midpoint >= it.startEpochMillis && midpoint < it.endEpochMillis
            }?.stage
            if (actual != null && actual != SleepStage.UNKNOWN) {
                val estimate = orderedPredictions.lastOrNull { it.measuredAtEpochMillis <= midpoint }
                if (estimate != null && midpoint - estimate.measuredAtEpochMillis <= maximumPredictionAgeMillis) {
                    matrix.getValue(actual)[estimate.stage] =
                        matrix.getValue(actual).getValue(estimate.stage) + 1
                    compared += 1
                    if (actual == estimate.stage) correct += 1
                }
            }
            bucketStart = bucketEnd
        }

        val frozenMatrix = matrix.mapValues { (_, row) -> row.toMap() }
        val accuracy = if (compared == 0) null else correct.toDouble() / compared
        val kappa = cohenKappa(frozenMatrix, compared)
        return SleepStageAgreementResult(compared, accuracy, kappa, frozenMatrix)
    }

    private fun cohenKappa(
        matrix: Map<SleepStage, Map<SleepStage, Int>>,
        total: Int
    ): Double? {
        if (total == 0) return null
        val observed = labels.sumOf { label -> matrix.getValue(label).getValue(label) }.toDouble() / total
        val rowTotals = labels.associateWith { actual ->
            labels.sumOf { predicted -> matrix.getValue(actual).getValue(predicted) }
        }
        val columnTotals = labels.associateWith { predicted ->
            labels.sumOf { actual -> matrix.getValue(actual).getValue(predicted) }
        }
        val expected = labels.sumOf { label ->
            rowTotals.getValue(label).toDouble() * columnTotals.getValue(label).toDouble()
        } / (total.toDouble() * total.toDouble())
        return if (expected >= 1.0) {
            if (observed >= 1.0) 1.0 else 0.0
        } else {
            (observed - expected) / (1.0 - expected)
        }
    }
}
