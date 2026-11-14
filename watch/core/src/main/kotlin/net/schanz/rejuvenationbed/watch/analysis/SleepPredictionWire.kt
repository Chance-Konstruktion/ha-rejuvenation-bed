package net.schanz.rejuvenationbed.watch.analysis

/** Local-only contract for derived Watch estimates sent to the paired phone. */
object SleepPredictionWire {
    const val SCHEMA = "rejuvenation-bed-sleep-estimates-v1"
    const val MESSAGE_PATH = "/m2/sleep-estimates"
    const val PHONE_PREFERENCES = "rejuvenation_bed_phone_sleep_validation"
    const val PHONE_PAYLOAD_KEY = "latest_watch_estimates"
    const val MAX_MESSAGE_BYTES = 48 * 1024
    const val COMPARISON_BUCKET_MILLIS = 5L * 60L * 1000L
    const val MAX_PREDICTION_AGE_MILLIS = 10L * 60L * 1000L
}
