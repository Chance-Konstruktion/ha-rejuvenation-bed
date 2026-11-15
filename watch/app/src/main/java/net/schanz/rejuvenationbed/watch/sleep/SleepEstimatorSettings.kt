package net.schanz.rejuvenationbed.watch.sleep

import android.content.Context

/** User-controlled experiment switch. The default is deliberately OFF. */
object SleepEstimatorSettings {
    private const val PREFERENCES = "rejuvenation_bed_watch_sleep"
    private const val KEY_EXPERIMENT_ENABLED = "experimental_sleep_estimator_enabled"

    fun isEnabled(context: Context): Boolean =
        context.applicationContext
            .getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
            .getBoolean(KEY_EXPERIMENT_ENABLED, false)

    fun setEnabled(context: Context, enabled: Boolean) {
        context.applicationContext
            .getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
            .edit()
            .putBoolean(KEY_EXPERIMENT_ENABLED, enabled)
            .apply()
    }
}
