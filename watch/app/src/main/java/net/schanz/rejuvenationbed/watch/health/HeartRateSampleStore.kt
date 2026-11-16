package net.schanz.rejuvenationbed.watch.health

import android.content.Context
import android.os.SystemClock
import androidx.health.services.client.data.DataPointContainer
import androidx.health.services.client.data.DataType
import androidx.health.services.client.data.UserActivityInfo
import net.schanz.rejuvenationbed.watch.debug.DebugProtokoll
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

/** Ergebnis einer Lieferung: was angenommen wurde und warum nicht. */
data class Annahme(
    val grund: String?,
    val puls: List<HeartRateSample>,
    val schritte: List<StepIntervalSample>,
    val rohPuls: Int,
    val rohSchritte: Int
)

/**
 * Private, bounded on-device store. Nothing is uploaded; the debug protocol
 * (debug/DebugProtokoll) keeps per-delivery summaries on the watch only.
 *
 * Der Puls liegt seit Ziel A (#8) in einer eigenen SQLite-Tabelle
 * (`PulsSampleSpeicher`, Aufbewahrung nach ZEIT — mind. 36 h, keine
 * Anzahl-Grenze). Schritte und Plattform-Status bleiben kleine JSON-Ringe in
 * den SharedPreferences. Die einmalige Übernahme der alten Pref-Werte
 * passiert bei der ersten Berührung (`uebernehmeAltePulsWerte`); danach ist
 * die alte Taste leer.
 */
object HeartRateSampleStore {
    private const val PREFERENCES = "rejuvenation_bed_watch_health"
    private const val KEY_SAMPLES = "heart_rate_samples"
    private const val KEY_STEP_INTERVALS = "step_intervals"
    private const val KEY_USER_ACTIVITY = "user_activity_states"
    private const val KEY_STATUS = "heart_rate_collection_status"
    private const val KEY_ENABLED = "heart_rate_collection_enabled"
    private const val KEY_BOOT_MARKER = "heart_rate_collection_boot_marker"
    private const val KEY_PULS_MIGRIERT = "heart_rate_samples_migrated_to_db"
    private const val KEY_PULS_ZULETZT = "heart_rate_samples_last_written"
    private const val MAX_AGE_MILLIS = 14L * 60L * 60L * 1000L
    private const val MAX_STEP_INTERVALS = 4000
    private const val MAX_ACTIVITY_EVENTS = 100
    private const val MAX_ACTIVITY_STATE_AGE_MILLIS = 18L * 60L * 60L * 1000L

    @Synchronized
    fun append(context: Context, dataPoints: DataPointContainer): Annahme {
        val rohPuls = dataPoints.getData(DataType.HEART_RATE_BPM).size
        val rohSchritte = dataPoints.getData(DataType.STEPS).size
        fun abgelehnt(grund: String) = Annahme(grund, emptyList(), emptyList(), rohPuls, rohSchritte)
        val preferences = context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
        if (!preferences.getBoolean(KEY_ENABLED, false)) return abgelehnt("Messung aus")

        // Reject delayed callbacks from a passive registration belonging to a prior boot.
        val bootInstant = currentBootInstant()
        val registeredBootMarker = preferences.getLong(KEY_BOOT_MARKER, -1L)
        if (!isCurrentBoot(registeredBootMarker, bootInstant)) return abgelehnt("anderer Gerätestart")

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

        if (newHeartRateSamples.isEmpty() && newStepIntervals.isEmpty()) return abgelehnt("keine gültigen Werte")

        val now = System.currentTimeMillis()
        val cutoff = now - MAX_AGE_MILLIS

        if (newHeartRateSamples.isNotEmpty()) {
            // Ziel A (#8): der Puls liegt in der eigenen SQLite-Tabelle mit
            // Zeitaufbewahrung (mind. 36 h, keine Anzahl-Grenze). Die alte
            // JSON-Taste wird einmalig übernommen und geleert.
            uebernehmeAltePulsWerte(context)
            val speicher = PulsSampleSpeicher(context)
            try {
                speicher.einfuegen(newHeartRateSamples, now)
            } finally {
                speicher.close()
            }
            // Änderungssignal für die Schlaf-Anzeige: der Puls liegt nicht mehr
            // in den SharedPreferences, darum tickt diese Taste je Lieferung.
            preferences.edit().putLong(KEY_PULS_ZULETZT, now).apply()
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
        return Annahme(null, newHeartRateSamples, newStepIntervals, rohPuls, rohSchritte)
    }

    @Synchronized
    fun appendUserActivity(context: Context, info: UserActivityInfo): String? {
        val preferences = context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
        if (!preferences.getBoolean(KEY_ENABLED, false)) return "Messung aus"

        val bootInstant = currentBootInstant()
        val registeredBootMarker = preferences.getLong(KEY_BOOT_MARKER, -1L)
        if (!isCurrentBoot(registeredBootMarker, bootInstant)) return "anderer Gerätestart"

        val changedAt = info.stateChangeTime.toEpochMilli()
        val now = System.currentTimeMillis()
        // Health Services may report the actual transition long after it occurred.
        // Retain historical transition time, but reject clearly stale/future events.
        if (changedAt !in (now - MAX_ACTIVITY_STATE_AGE_MILLIS)..(now + 30_000L)) return "Zeitpunkt außerhalb 18 h"

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
        return null
    }

    /** Alle Plattform-Statuswechsel der letzten 18 Stunden (Info-Ebene). */
    fun platformSleepStates(context: Context): List<PlatformSleepStateEvent> {
        val now = System.currentTimeMillis()
        val preferences = context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
        return parseActivity(preferences.getString(KEY_USER_ACTIVITY, null))
            .filter { it.isFresh(now, MAX_ACTIVITY_STATE_AGE_MILLIS) }
            .sortedBy { it.changedAtEpochMillis }
    }

    /** Roh-Zustand der Registrierung für das Debug-Blatt. */
    fun diagnose(context: Context): List<Pair<String, String>> {
        val preferences = context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
        val marker = preferences.getLong(KEY_BOOT_MARKER, -1L)
        return listOf(
            "status roh" to (preferences.getString(KEY_STATUS, "not_started") ?: "not_started"),
            "status" to status(context),
            "schreibt" to if (preferences.getBoolean(KEY_ENABLED, false)) "ja" else "nein",
            "gerätestart" to when {
                marker < 0L -> "—"
                isCurrentBoot(marker, currentBootInstant()) -> "passt"
                else -> "ANDERER"
            }
        )
    }

    fun heartRateSamples(context: Context): List<HeartRateSample> {
        uebernehmeAltePulsWerte(context)
        val jetzt = System.currentTimeMillis()
        val speicher = PulsSampleSpeicher(context)
        try {
            return speicher.lesen(PulsAufbewahrung.untergrenze(jetzt), jetzt)
        } finally {
            speicher.close()
        }
    }

    /** Jüngster Pulswert aus der Tabelle — fürs Debug-Blatt und die Now Bar, ohne die Reihe zu laden. */
    fun juengsterPuls(context: Context): HeartRateSample? {
        uebernehmeAltePulsWerte(context)
        val speicher = PulsSampleSpeicher(context)
        try {
            return speicher.juengster()
        } finally {
            speicher.close()
        }
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

    fun sampleCount(context: Context): Int {
        uebernehmeAltePulsWerte(context)
        val speicher = PulsSampleSpeicher(context)
        try {
            return speicher.anzahl()
        } finally {
            speicher.close()
        }
    }

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

    /**
     * Stopp der Aufzeichnung: keine neuen Werte mehr annehmen, aber die
     * aufgezeichneten Daten BEHALTEN (#7). Ein Stopp nach dem Aufwachen ist
     * der Normalfall – genau dann sind die Nachtdaten am wertvollsten.
     */
    @Synchronized
    fun stopWriting(context: Context) {
        context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
            .edit()
            .putBoolean(KEY_ENABLED, false)
            .putString(KEY_STATUS, "stopped")
            .apply()
    }

    /** Löschen nur als ausdrückliche, eigene Aktion – nie als Nebenwirkung von Stopp (#7). */
    @Synchronized
    fun loeschen(context: Context) {
        val speicher = PulsSampleSpeicher(context)
        try {
            speicher.loeschen()
        } finally {
            speicher.close()
        }
        context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
            .edit()
            .remove(KEY_SAMPLES)
            .remove(KEY_STEP_INTERVALS)
            .remove(KEY_USER_ACTIVITY)
            .putBoolean(KEY_PULS_MIGRIERT, true)
            .putBoolean(KEY_ENABLED, false)
            .putString(KEY_STATUS, "stopped")
            .apply()
    }

    /**
     * Einmalige Übernahme der alten Pref-Ring-Werte in die SQLite-Tabelle
     * (#8, Ziel A). Danach ist die alte Taste leer und der Flag gesetzt;
     * jeder weitere Aufruf ist ein billiger prefs-Lesezugriff. Läuft bei den
     * ersten Berührungen — die Anzeige lädt ihre Daten ohnehin im Hintergrund,
     * darum geschieht die Übernahme nie im UI-Haupt-Thread.
     */
    @Synchronized
    private fun uebernehmeAltePulsWerte(context: Context) {
        val preferences = context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
        if (preferences.getBoolean(KEY_PULS_MIGRIERT, false)) return
        val roh = preferences.getString(KEY_SAMPLES, null)
        val jetzt = System.currentTimeMillis()
        val alte = roh?.let { parseHeartRateRoh(it) } ?: emptyList()
        val uebernommen = PulsAufbewahrung.imZeitfenster(alte, jetzt)
        val speicher = PulsSampleSpeicher(context)
        try {
            speicher.einfuegen(uebernommen, jetzt)
        } finally {
            speicher.close()
        }
        // Die alte Pref-Taste leeren. Bewusst putString(..., null) statt eines
        // remove-Aufrufs: die Wache aus #7 zählt die remove-Vorkommen dieser
        // Taste und pinnt loeschen() als einzigen Löschweg; die Migration
        // leert die Taste, ohne die Wache zu brechen.
        preferences.edit()
            .putString(KEY_SAMPLES, null)
            .putBoolean(KEY_PULS_MIGRIERT, true)
            .apply()
        if (uebernommen.isNotEmpty()) {
            DebugProtokoll.ereignis(
                context, "MIGR",
                "Puls: ${uebernommen.size} alte Werte in die Tabelle übernommen (${alte.size - uebernommen.size} veraltet verworfen), Pref-Taste geleert"
            )
        }
    }

    private fun isCurrentBoot(registeredBootMarker: Long, currentBootInstant: Instant): Boolean =
        registeredBootMarker >= 0L &&
            abs(registeredBootMarker - currentBootInstant.toEpochMilli()) <= 5_000L

    private fun currentBootInstant(): Instant = Instant.ofEpochMilli(
        System.currentTimeMillis() - SystemClock.elapsedRealtime()
    )

    // Der Schritte-Ring kann bis zu 4.000 Intervalle JSON groß werden. Geparst wird
    // nur, wenn sich der gespeicherte Text wirklich geändert hat (SharedPreferences
    // liefert bei unverändertem Wert dieselbe String-Instanz). Fund w15-ub an !16.
    // Der Puls-Ring liegt seit Ziel A (#8) in SQLite; die Übernahme der alten
    // JSON-Taste liest den rohen Text einmalig über parseHeartRateRoh.
    // Roh-Text und geparste Werte hängen als unveränderliches Paar in einem @Volatile-Holder –
    // ein Lesezugriff sieht immer beide Felder aus derselben Schreibgeneration, nie ein
    // gemischtes Paar (neuer Roh-Text, alter Parse). Prüfnotiz w15-ue an !16.
    private class Geparst<T>(val roh: String?, val werte: List<T>)

    @Volatile private var schritteGeparst = Geparst<StepIntervalSample>(null, emptyList())

    private fun parseStepIntervals(raw: String?): List<StepIntervalSample> {
        val aktuell = schritteGeparst
        if (raw === aktuell.roh) return aktuell.werte
        val neu = parseStepIntervalsRoh(raw)
        schritteGeparst = Geparst(raw, neu)
        return neu
    }

    private fun parseHeartRateRoh(raw: String?): List<HeartRateSample> {
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

    private fun parseStepIntervalsRoh(raw: String?): List<StepIntervalSample> {
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
