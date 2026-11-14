package net.schanz.rejuvenationbed.watch.health

import android.content.Context
import android.os.SystemClock
import androidx.health.services.client.data.DataPointContainer
import androidx.health.services.client.data.DataType
import androidx.health.services.client.data.UserActivityInfo
import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant
import kotlin.math.abs

data class HeartRateSample(
    val measuredAtEpochMillis: Long,
    val beatsPerMinute: Double
)

/**
 * Health Services STEPS values are deltas over an interval, not raw accelerometer samples.
 * The interval bounds are retained so downstream analysis never invents exact movement times.
 */
data class StepIntervalSample(
    val startEpochMillis: Long,
    val endEpochMillis: Long,
    val steps: Long
)

/**
 * Private, bounded on-device store. No health values are logged or uploaded.
 */
object HeartRateSampleStore {
    private const val PREFERENCES = "rejuvenation_bed_watch_health"
    private const val KEY_SAMPLES = "heart_rate_samples"
    private const val KEY_STEP_INTERVALS = "step_intervals"
    private const val KEY_USER_ACTIVITY = "user_activity_states"
    private const val KEY_STATUS = "heart_rate_collection_status"
    private const val KEY_ENABLED = "heart_rate_collection_enabled"
    private const val KEY_BOOT_MARKER = "heart_rate_collection_boot_marker"
    private const val MAX_AGE_MILLIS = 10L * 60L * 60L * 1000L
    private const val MAX_HEART_RATE_SAMPLES = 2500
    private const val MAX_STEP_INTERVALS = 4000
    private const val MAX_ACTIVITY_EVENTS = 100
    private const val MAX_ACTIVITY_STATE_AGE_MILLIS = 18L * 60L * 60L * 1000L

    @Synchronized
    fun append(context: Context, dataPoints: DataPointContainer) {
        val preferences = context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
        if (!preferences.getBoolean(KEY_ENABLED, false)) return

        // Reject delayed callbacks from a passive registration belonging to a prior boot.
        val bootInstant = currentBootInstant()
        val registeredBootMarker = preferences.getLong(KEY_BOOT_MARKER, -1L)
        if (!isCurrentBoot(registeredBootMarker, bootInstant)) return

        val newHeartRateSamples = dataPoints.getData(DataType.HEART_RATE_BPM).mapNotNull { point ->
            val bpm = point.value
            if (!bpm.isFinite() || bpm !in 30.0..220.0) {
                null
            } else {
                HeartRateSample(
                    measuredAtEpochMillis = point.getTimeInstant(bootInstant).toEpochMilli(),
                    beatsPerMinute = bpm
                )
            }
        }

        val newStepIntervals = dataPoints.getData(DataType.STEPS).mapNotNull { point ->
            val steps = point.value
            val start = point.getStartInstant(bootInstant).toEpochMilli()
            val end = point.getEndInstant(bootInstant).toEpochMilli()
            if (steps !in 0L..1_000_000L || start < 0L || end <= start) {
                null
            } else {
                StepIntervalSample(
                    startEpochMillis = start,
                    endEpochMillis = end,
                    steps = steps
                )
            }
        }

        if (newHeartRateSamples.isEmpty() && newStepIntervals.isEmpty()) return

        val now = System.currentTimeMillis()
        val cutoff = now - MAX_AGE_MILLIS

        if (newHeartRateSamples.isNotEmpty()) {
            val existing = parseHeartRate(preferences.getString(KEY_SAMPLES, null))
            val retained = (existing + newHeartRateSamples)
                .distinctBy { it.measuredAtEpochMillis }
                .filter { it.measuredAtEpochMillis in cutoff..now }
                .sortedBy { it.measuredAtEpochMillis }
                .takeLast(MAX_HEART_RATE_SAMPLES)

            val encoded = JSONArray().apply {
                retained.forEach { sample ->
                    put(
                        JSONObject()
                            .put("ts", sample.measuredAtEpochMillis)
                            .put("bpm", sample.beatsPerMinute)
                    )
                }
            }
            preferences.edit().putString(KEY_SAMPLES, encoded.toString()).apply()
        }

        if (newStepIntervals.isNotEmpty()) {
            val existing = parseStepIntervals(preferences.getString(KEY_STEP_INTERVALS, null))
            val retained = (existing + newStepIntervals)
                .distinctBy { it.startEpochMillis to it.endEpochMillis }
                .filter { it.endEpochMillis in cutoff..now }
                .sortedBy { it.endEpochMillis }
                .takeLast(MAX_STEP_INTERVALS)

            val encoded = JSONArray().apply {
                retained.forEach { interval ->
                    put(
                        JSONObject()
                            .put("start", interval.startEpochMillis)
                            .put("end", interval.endEpochMillis)
                            .put("steps", interval.steps)
                    )
                }
            }
            preferences.edit().putString(KEY_STEP_INTERVALS, encoded.toString()).apply()
        }

        preferences.edit().putString(KEY_STATUS, "collecting").apply()
    }

    @Synchronized
    fun appendUserActivity(context: Context, info: UserActivityInfo) {
        val preferences = context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
        if (!preferences.getBoolean(KEY_ENABLED, false)) return

        val bootInstant = currentBootInstant()
        val registeredBootMarker = preferences.getLong(KEY_BOOT_MARKER, -1L)
        if (!isCurrentBoot(registeredBootMarker, bootInstant)) return

        val changedAt = info.stateChangeTime.toEpochMilli()
        val now = System.currentTimeMillis()
        // Health Services may report the actual transition long after it occurred.
        // Retain historical transition time, but reject clearly stale/future events.
        if (changedAt !in (now - MAX_ACTIVITY_STATE_AGE_MILLIS)..(now + 30_000L)) return

        val newEvent = PlatformSleepStateEvent(
            state = PlatformSleepState.fromHealthServices(info),
            changedAtEpochMillis = changedAt
        )
        val existing = parseActivity(preferences.getString(KEY_USER_ACTIVITY, null))
        val retained = (existing + newEvent)
            .distinctBy { it.changedAtEpochMillis }
            .sortedBy { it.changedAtEpochMillis }
            .takeLast(MAX_ACTIVITY_EVENTS)

        val encoded = JSONArray().apply {
            retained.forEach { event ->
                put(
                    JSONObject()
                        .put("changed_at", event.changedAtEpochMillis)
                        .put("state", event.state.name)
                )
            }
        }
        preferences.edit()
            .putString(KEY_USER_ACTIVITY, encoded.toString())
            .putString(KEY_STATUS, "collecting")
            .apply()
    }

    fun heartRateSamples(context: Context): List<HeartRateSample> {
        val preferences = context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
        val cutoff = System.currentTimeMillis() - MAX_AGE_MILLIS
        return parseHeartRate(preferences.getString(KEY_SAMPLES, null))
            .filter { it.measuredAtEpochMillis in cutoff..System.currentTimeMillis() }
            .sortedBy { it.measuredAtEpochMillis }
    }

    fun stepIntervals(context: Context): List<StepIntervalSample> {
        val preferences = context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
        val cutoff = System.currentTimeMillis() - MAX_AGE_MILLIS
        return parseStepIntervals(preferences.getString(KEY_STEP_INTERVALS, null))
            .filter { it.endEpochMillis in cutoff..System.currentTimeMillis() }
            .sortedBy { it.endEpochMillis }
    }

    fun latestPlatformSleepState(context: Context): PlatformSleepStateEvent? {
        val now = System.currentTimeMillis()
        val cutoff = now - MAX_ACTIVITY_STATE_AGE_MILLIS
        val preferences = context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
        val status = preferences.getString(KEY_STATUS, "not_started")
        if (status != "registered" && status != "collecting") return null
        val registeredBootMarker = preferences.getLong(KEY_BOOT_MARKER, -1L)
        if (!isCurrentBoot(registeredBootMarker, currentBootInstant())) return null
        return parseActivity(preferences.getString(KEY_USER_ACTIVITY, null))
            .filter { it.isFresh(now, MAX_ACTIVITY_STATE_AGE_MILLIS) }
            .maxByOrNull { it.changedAtEpochMillis }
    }

    fun sampleCount(context: Context): Int = heartRateSamples(context).size

    fun stepIntervalCount(context: Context): Int = stepIntervals(context).size

    fun status(context: Context): String {
        val preferences = context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
        val status = preferences.getString(KEY_STATUS, "not_started") ?: "not_started"
        if (status == "registered" || status == "collecting") {
            val registeredBootMarker = preferences.getLong(KEY_BOOT_MARKER, -1L)
            if (!isCurrentBoot(registeredBootMarker, currentBootInstant())) {
                // Passive registrations do not survive a device reboot. Report them as inactive.
                return "not_started"
            }
        }
        return status
    }

    @Synchronized
    fun markRegistered(context: Context) {
        context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
            .edit()
            .putBoolean(KEY_ENABLED, true)
            .putLong(KEY_BOOT_MARKER, currentBootInstant().toEpochMilli())
            .putString(KEY_STATUS, "registered")
            .commit()
    }

    @Synchronized
    fun setStatus(context: Context, status: String) {
        val active = status == "registered" || status == "collecting"
        val editor = context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
            .edit()
            .putBoolean(KEY_ENABLED, active)
            .putString(KEY_STATUS, status)
        if (active) editor.putLong(KEY_BOOT_MARKER, currentBootInstant().toEpochMilli())
        editor.apply()
    }

    @Synchronized
    fun clear(context: Context) {
        context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
            .edit()
            .remove(KEY_SAMPLES)
            .remove(KEY_STEP_INTERVALS)
            .remove(KEY_USER_ACTIVITY)
            .putBoolean(KEY_ENABLED, false)
            .putString(KEY_STATUS, "stopped")
            .apply()
    }

    private fun isCurrentBoot(registeredBootMarker: Long, currentBootInstant: Instant): Boolean =
        registeredBootMarker >= 0L &&
            abs(registeredBootMarker - currentBootInstant.toEpochMilli()) <= 5_000L

    private fun currentBootInstant(): Instant = Instant.ofEpochMilli(
        System.currentTimeMillis() - SystemClock.elapsedRealtime()
    )

    private fun parseHeartRate(raw: String?): List<HeartRateSample> {
        if (raw.isNullOrBlank()) return emptyList()
        return runCatching {
            val array = JSONArray(raw)
            buildList {
                for (index in 0 until array.length()) {
                    val item = array.getJSONObject(index)
                    add(
                        HeartRateSample(
                            measuredAtEpochMillis = item.getLong("ts"),
                            beatsPerMinute = item.getDouble("bpm")
                        )
                    )
                }
            }
        }.getOrDefault(emptyList())
    }

    private fun parseStepIntervals(raw: String?): List<StepIntervalSample> {
        if (raw.isNullOrBlank()) return emptyList()
        return runCatching {
            val array = JSONArray(raw)
            buildList {
                for (index in 0 until array.length()) {
                    val item = array.getJSONObject(index)
                    add(
                        StepIntervalSample(
                            startEpochMillis = item.getLong("start"),
                            endEpochMillis = item.getLong("end"),
                            steps = item.getLong("steps")
                        )
                    )
                }
            }
        }.getOrDefault(emptyList())
    }

    private fun parseActivity(raw: String?): List<PlatformSleepStateEvent> {
        if (raw.isNullOrBlank()) return emptyList()
        return runCatching {
            val array = JSONArray(raw)
            buildList {
                for (index in 0 until array.length()) {
                    val item = array.getJSONObject(index)
                    val state = runCatching { PlatformSleepState.valueOf(item.getString("state")) }
                        .getOrDefault(PlatformSleepState.UNKNOWN)
                    add(
                        PlatformSleepStateEvent(
                            state = state,
                            changedAtEpochMillis = item.getLong("changed_at")
                        )
                    )
                }
            }
        }.getOrDefault(emptyList())
    }
}
