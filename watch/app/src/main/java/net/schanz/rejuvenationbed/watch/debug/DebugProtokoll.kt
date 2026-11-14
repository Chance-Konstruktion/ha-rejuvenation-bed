package net.schanz.rejuvenationbed.watch.debug

import android.content.Context
import android.util.Log
import net.schanz.rejuvenationbed.watch.health.HeartRateSample
import net.schanz.rejuvenationbed.watch.health.StepIntervalSample
import java.io.File
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

/**
 * Debug-Protokoll der Uhr: Ereignisse der Sensor-Kette (Fähigkeiten, Rechte,
 * Registrierung, Lieferungen von Health Services, Plattform-Schlafstatus,
 * Live-Test). Bleibt auf der Uhr: App-privat unter files/debug/protokoll.txt
 * und im Logcat unter dem Tag „RBW“. Kein Upload.
 *
 * Abruf am PC (Debug-Build):
 *   adb shell run-as net.schanz.rejuvenationbed.watch cat files/debug/protokoll.txt
 *   adb logcat -s RBW
 */
object DebugProtokoll {
    const val TAG = "RBW"
    private const val DATEI = "debug/protokoll.txt"
    private const val MAX_BYTES = 96_000L
    private const val BEHALTEN_ZEILEN = 600
    private const val ZAEHLER = "rejuvenation_bed_watch_debug"

    private val zeitFormat = DateTimeFormatter.ofPattern("dd.MM. HH:mm:ss", Locale.GERMANY)

    fun datei(context: Context): File = File(context.applicationContext.filesDir, DATEI)

    @Synchronized
    fun ereignis(context: Context, art: String, text: String) {
        val jetzt = System.currentTimeMillis()
        val zeile = "${zeit(jetzt)} ${art.padEnd(7)} $text"
        Log.i(TAG, "$art $text")
        runCatching {
            val f = datei(context)
            f.parentFile?.mkdirs()
            f.appendText(zeile + "\n")
            if (f.length() > MAX_BYTES) {
                val rest = f.readLines().takeLast(BEHALTEN_ZEILEN)
                f.writeText(rest.joinToString("\n", postfix = "\n"))
            }
        }
        context.applicationContext.getSharedPreferences(ZAEHLER, Context.MODE_PRIVATE)
            .edit()
            .putLong("zuletzt_$art", jetzt)
            .putInt("anzahl_$art", anzahl(context, art) + 1)
            .apply()
    }

    fun letzte(context: Context, anzahl: Int): List<String> =
        runCatching { datei(context).readLines().takeLast(anzahl) }.getOrDefault(emptyList())

    fun anzahl(context: Context, art: String): Int =
        context.applicationContext.getSharedPreferences(ZAEHLER, Context.MODE_PRIVATE)
            .getInt("anzahl_$art", 0)

    fun zuletzt(context: Context, art: String): Long? =
        context.applicationContext.getSharedPreferences(ZAEHLER, Context.MODE_PRIVATE)
            .getLong("zuletzt_$art", -1L).takeIf { it > 0L }

    @Synchronized
    fun loeschen(context: Context) {
        runCatching { datei(context).delete() }
        context.applicationContext.getSharedPreferences(ZAEHLER, Context.MODE_PRIVATE)
            .edit().clear().apply()
    }

    fun zeit(epochMillis: Long): String =
        zeitFormat.format(Instant.ofEpochMilli(epochMillis).atZone(ZoneId.systemDefault()))
}

/** Reine Text-Bausteine des Protokolls (JVM-geprüft). */
object DebugText {
    private val uhr = DateTimeFormatter.ofPattern("HH:mm", Locale.GERMANY)

    fun uhrzeit(epochMillis: Long, zone: ZoneId = ZoneId.systemDefault()): String =
        uhr.format(Instant.ofEpochMilli(epochMillis).atZone(zone))

    /** Alter als „12 s“, „7 min“, „3 h 05“. */
    fun alter(millis: Long): String {
        val s = (millis / 1000L).coerceAtLeast(0L)
        return when {
            s < 60L -> "$s s"
            s < 3600L -> "${s / 60L} min"
            else -> "${s / 3600L} h ${String.format(Locale.GERMANY, "%02d", (s % 3600L) / 60L)}"
        }
    }

    /**
     * Zusammenfassung EINER Lieferung von Health Services: wie viele Werte,
     * welche Spanne, wie alt der jüngste Wert beim Eintreffen war.
     */
    fun lieferung(
        puls: List<HeartRateSample>,
        schritte: List<StepIntervalSample>,
        jetzt: Long,
        zone: ZoneId = ZoneId.systemDefault()
    ): String {
        val teile = mutableListOf<String>()
        if (puls.isEmpty()) {
            teile += "Puls 0"
        } else {
            val min = puls.minOf { it.beatsPerMinute }
            val max = puls.maxOf { it.beatsPerMinute }
            val erst = puls.minOf { it.measuredAtEpochMillis }
            val letzt = puls.maxOf { it.measuredAtEpochMillis }
            teile += String.format(
                Locale.GERMANY, "Puls %d (%.0f–%.0f bpm, %s–%s, Verzug %s)",
                puls.size, min, max, uhrzeit(erst, zone), uhrzeit(letzt, zone), alter(jetzt - letzt)
            )
        }
        teile += if (schritte.isEmpty()) {
            "Schritte 0"
        } else {
            "Schritte ${schritte.size} (${schritte.sumOf { it.steps }})"
        }
        return teile.joinToString(" · ")
    }
}
