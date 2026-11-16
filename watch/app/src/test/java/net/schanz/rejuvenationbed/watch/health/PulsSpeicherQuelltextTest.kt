package net.schanz.rejuvenationbed.watch.health

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.file.Files
import java.nio.file.Path

/**
 * #8/Ziel A: Der Puls liegt in einer eigenen SQLite-Tabelle mit Aufbewahrung
 * nach ZEIT (mind. 36 h) statt als JSON-Ring in den SharedPreferences. Die
 * SQLite-Schicht selbst läuft nicht in der JVM — diese Wache liest den
 * Quelltext und pinnt: append schreibt keinen Puls-JSON mehr, die Migration
 * leert die alte Taste benannt, die Tabelle räumt nach Zeit ohne Anzahl-Grenze
 * auf und die Anzeige lädt ihre Daten nie im UI-Haupt-Thread.
 */
class PulsSpeicherQuelltextTest {
    private val basisPfad = "src/main/java/net/schanz/rejuvenationbed/watch/"

    private fun quelle(name: String, ordner: String): String {
        var ort: Path? = Path.of(System.getProperty("user.dir"))
        repeat(8) {
            ort?.let { basis ->
                listOf(ordner + name, "watch/app/$ordner$name").forEach { kandidat ->
                    val datei = basis.resolve(kandidat)
                    if (Files.isRegularFile(datei)) return Files.readString(datei)
                }
            }
            ort = ort?.parent
        }
        throw AssertionError("$name nicht gefunden")
    }

    /** Rumpf der Funktion `fun <name>(` bis zur passenden schließenden Klammer. */
    private fun rumpf(text: String, name: String): String {
        val start = text.indexOf("fun $name(")
        assertTrue("fun $name( fehlt", start >= 0)
        val auf = text.indexOf('{', start)
        var tiefe = 0
        for (i in auf until text.length) {
            when (text[i]) {
                '{' -> tiefe++
                '}' -> if (--tiefe == 0) return text.substring(auf, i + 1)
            }
        }
        throw AssertionError("Rumpf von $name nicht geschlossen")
    }

    @Test
    fun appendSchreibtKeinenPulsJsonMehr() {
        val append = rumpf(quelle("HeartRateSampleStore.kt", basisPfad + "health/"), "append")
        assertFalse(
            "append darf den Puls nicht mehr als JSON in die Preferences schreiben",
            "putString(KEY_SAMPLES" in append
        )
        assertTrue("append muss die einmalige Übernahme anstoßen", "uebernehmeAltePulsWerte(" in append)
        assertTrue("append muss in die SQLite-Tabelle schreiben", "PulsSampleSpeicher" in append)
        assertTrue("append muss den UI-Takt setzen (Anzeige-Auffrischung)", "KEY_PULS_ZULETZT" in append)
    }

    @Test
    fun dieTabelleRaeumtNachZeitOhneAnzahlGrenzeAuf() {
        val tabelle = quelle("PulsSampleSpeicher.kt", basisPfad + "health/")
        assertTrue("Einfügen filtert nach der Zeitgrenze", "PulsAufbewahrung.untergrenze" in tabelle)
        assertTrue("Aufräumen nach Zeit", "measured_at < ?" in tabelle)
        assertFalse("keine Anzahl-Grenze im Speicher", Regex("MAX_\\w+").containsMatchIn(tabelle))
        assertTrue("eigene Datenbank neben sleep_ibi_local.db", "sleep_puls_local.db" in tabelle)
    }

    @Test
    fun dieMigrationLeertDieAlteTasteBenannt() {
        val store = quelle("HeartRateSampleStore.kt", basisPfad + "health/")
        val uebernahme = rumpf(store, "uebernehmeAltePulsWerte")
        assertTrue("Migration leert die alte Pref-Taste (putString null statt remove)", "putString(KEY_SAMPLES, null)" in uebernahme)
        assertTrue("Migration setzt den Einmal-Flag", "KEY_PULS_MIGRIERT, true" in uebernahme)
        assertTrue("Migration protokolliert benannt", "\"MIGR\"" in uebernahme)
    }

    @Test
    fun dieAnzeigeLaedtNieImHauptThread() {
        val blattOrdner = basisPfad + "blatt/"
        val blatt = quelle("SchlafBlatt.kt", blattOrdner)
        assertTrue("der erste Stand ist leer und billig (kein synchrones Laden)", "leererSchlafStand(context)" in blatt)
        assertTrue(
            "produceState lädt immer im Hintergrund, auch beim ersten Mal",
            "value = withContext(Dispatchers.Default) { berechneSchlafStand(context, experimentAktiv) }" in blatt
        )
        val debug = quelle("DebugBlatt.kt", blattOrdner)
        assertTrue("das Debug-Blatt liest Puls-Werte im Hintergrund", "Dispatchers.IO" in debug)
        assertFalse(
            "das Debug-Blatt lädt die ganze Puls-Reihe nicht mehr",
            "HeartRateSampleStore.heartRateSamples(" in debug
        )
    }
}
