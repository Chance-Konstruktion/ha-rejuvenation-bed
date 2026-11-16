package net.schanz.rejuvenationbed.watch.health

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.file.Files
import java.nio.file.Path

/**
 * #7: Der Stopp nach dem Aufwachen löschte die ganze Nacht. Store und Registrierung hängen an
 * Android (Context, Health Services) und laufen nicht in der JVM – diese Wache liest den Quelltext
 * und pinnt: stop() ruft stopWriting und nie loeschen; stopWriting entfernt keinen Daten-Schlüssel;
 * der Ring reicht für eine Nacht bei ~1 Pulswert/s. Prüfnotizen an !16 (w15-ub, w15-ue): loeschen()
 * ist der einzige Löschweg und wird nur aus der eigenen Aktion in der Info-Ebene gerufen – dort mit
 * Rückfrage, Bestätigen nicht vorgewählt, nur sichtbar ohne laufende Messung.
 */
class StoppBehaeltDatenQuelltextTest {
    private val basisPfad = "src/main/java/net/schanz/rejuvenationbed/watch/health/"

    private fun quelle(name: String, ordner: String = basisPfad): String {
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

    /** Quell-Ordner der Uhr-App (src/main/java), vom Arbeitsverzeichnis aufwärts gesucht. */
    private fun appOrdner(): Path {
        var ort: Path? = Path.of(System.getProperty("user.dir"))
        repeat(8) {
            ort?.let { basis ->
                listOf("src/main/java", "watch/app/src/main/java").forEach { kandidat ->
                    val ordner = basis.resolve(kandidat)
                    if (Files.isDirectory(ordner)) return ordner
                }
            }
            ort = ort?.parent
        }
        throw AssertionError("src/main/java der Uhr-App nicht gefunden")
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
    fun stoppRuftStopWritingUndNieLoeschen() {
        val stop = rumpf(quelle("PassiveHeartRateRegistration.kt"), "stop")
        assertTrue("stop() muss stopWriting rufen", "HeartRateSampleStore.stopWriting(" in stop)
        assertFalse("stop() darf nicht löschen", "loeschen(" in stop)
        assertFalse("stop() darf nicht clear() rufen", "clear(" in stop)
    }

    @Test
    fun stopWritingEntferntKeineDaten() {
        val rumpf = rumpf(quelle("HeartRateSampleStore.kt"), "stopWriting")
        assertFalse("stopWriting darf nichts entfernen", ".remove(" in rumpf || ".clear(" in rumpf)
    }

    @Test
    fun loeschenIstDerEinzigeLoeschweg() {
        val store = quelle("HeartRateSampleStore.kt")
        val remove = Regex("""\.remove\(KEY_SAMPLES\)""").findAll(store).count()
        assertTrue("KEY_SAMPLES wird genau einmal entfernt (in loeschen)", remove == 1)
        assertTrue(".remove(KEY_SAMPLES) gehört in loeschen", ".remove(KEY_SAMPLES)" in rumpf(store, "loeschen"))
    }

    @Test
    fun loeschenHatGenauEinenAnruferDieInfoAktion() {
        // #7 (Prüfnotizen an !16): das Löschen ist eine ausdrückliche, eigene Aktion –
        // der Store-Weg HeartRateSampleStore.loeschen( wird genau einmal gerufen, in der
        // Info-Ebene des Schlaf-Blatts; nie aus Stopp, Service oder einem anderen Blatt.
        val anrufer = Files.walk(appOrdner()).use { pfade ->
            pfade
                .filter { pfad -> pfad.toString().endsWith(".kt") }
                .map { pfad -> pfad.fileName.toString() to runCatching { Files.readString(pfad) }.getOrDefault("") }
                .toList()
                .filter { (_, text) -> "HeartRateSampleStore.loeschen(" in text }
                .map { (name, _) -> name }
        }
        assertTrue(
            "genau ein Anrufer von HeartRateSampleStore.loeschen( erwartet (SchlafBlatt.kt), gefunden: $anrufer",
            anrufer == listOf("SchlafBlatt.kt")
        )
    }

    @Test
    fun dieInfoAktionFragtNachUndZeigtNurOhneMessung() {
        val blatt = quelle("SchlafBlatt.kt", "src/main/java/net/schanz/rejuvenationbed/watch/blatt/")
        val rumpf = rumpf(blatt, "SchlafInfo")
        assertTrue("die Aktion ruft loeschen() aus der Info-Ebene", "HeartRateSampleStore.loeschen(" in rumpf)
        assertTrue("Rückfrage bietet Abbrechen", "\"ABBRECHEN\"" in rumpf)
        assertTrue("Rückfrage bietet Bestätigen", "\"BESTÄTIGEN\"" in rumpf)
        assertTrue("Bestätigen ist nicht vorgewählt (kein Hervor)", "hervor = true" !in rumpf)
        assertTrue("nur sichtbar, wenn nicht gemessen wird", "!stand.misst" in rumpf)
        assertTrue("nach dem Löschen steht die Protokollzeile", "\"Daten gelöscht (Nutzer)\"" in rumpf)
    }

    @Test
    fun aufbewahrungReichtFuerEineNachtUndMehr() {
        // Ziel A (#8): der Puls liegt in einer SQLite-Tabelle mit Aufbewahrung
        // nach ZEIT statt in einem Anzahls-Ring. Die Nacht 15./16.11.
        // (02:22–15:43, ~13,5 h) war im 45.000-Ring schon nach 28 min angebrochen;
        // 36 h nach Zeit übertrifft die alte Absicht („Ring reicht für eine Nacht“)
        // deutlich. Die Konstante wird direkt geprüft, nicht aus dem Quelltext.
        assertTrue(
            "Aufbewahrung muss mindestens 36 h nach Zeit sein",
            PulsAufbewahrung.RETENTION_MILLIS >= 36L * 60L * 60L * 1000L
        )
        val tabelle = quelle("PulsSampleSpeicher.kt")
        assertFalse("die Puls-Tabelle darf keine Anzahl-Grenze haben (nur Zeit)", "takeLast" in tabelle)
        assertTrue("die Puls-Tabelle räumt nach Zeit auf", "measured_at < ?" in tabelle)
    }
}
