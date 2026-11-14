package net.schanz.rejuvenationbed.watch.sleep

/**
 * Wire values intentionally match SleepStageResolver in Rejuvenation Bed.
 */
enum class SleepStage(val wireValue: String) {
    AWAKE("awake"),
    LIGHT("light"),
    DEEP("deep"),
    REM("rem"),
    UNKNOWN("unknown");

    companion object {
        fun fromWireValue(value: String?): SleepStage {
            val normalized = value?.trim()?.lowercase()
            return entries.firstOrNull { it.wireValue == normalized } ?: UNKNOWN
        }
    }
}

/**
 * A local wellness estimate. It must not be treated as a medical measurement.
 */
data class SleepStageEstimate(
    val stage: SleepStage,
    val confidence: Double,
    val sampleCoverage: Double,
    val measuredAtEpochMillis: Long,
    val algorithmVersion: String
) {
    init {
        require(confidence in 0.0..1.0) { "confidence must be between 0 and 1" }
        require(sampleCoverage in 0.0..1.0) { "sampleCoverage must be between 0 and 1" }
        require(measuredAtEpochMillis >= 0) { "timestamp must be non-negative" }
        require(algorithmVersion.isNotBlank()) { "algorithmVersion must not be blank" }
    }

    fun isUsable(
        minimumConfidence: Double = 0.75,
        minimumCoverage: Double = 0.80,
        nowEpochMillis: Long,
        maximumAgeMillis: Long = 120_000
    ): Boolean {
        require(minimumConfidence in 0.0..1.0)
        require(minimumCoverage in 0.0..1.0)
        require(maximumAgeMillis >= 0)
        val age = nowEpochMillis - measuredAtEpochMillis
        return stage != SleepStage.UNKNOWN &&
            confidence >= minimumConfidence &&
            sampleCoverage >= minimumCoverage &&
            age in 0..maximumAgeMillis
    }
}
