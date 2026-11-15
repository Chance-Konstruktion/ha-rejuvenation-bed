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
 * der Ring reicht für eine Nacht bei ~1 Pulswert/s.
 */
class StoppBehaeltDatenQuelltextTest {
    private val basisPfad = "src/main/java/net/schanz/rejuvenationbed/watch/health/"

    private fun quelle(name: String): String {
        var ort: Path? = Path.of(System.getProperty("user.dir"))
        repeat(8) {
            ort?.let { basis ->
                listOf(basisPfad + name, "watch/app/$basisPfad$name").forEach { kandidat ->
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
    fun ringReichtFuerEineNacht() {
        val store = quelle("HeartRateSampleStore.kt")
        val anzahl = Regex("""MAX_HEART_RATE_SAMPLES = ([\d_]+)""").find(store)!!.groupValues[1].replace("_", "").toInt()
        val stunden = Regex("""MAX_AGE_MILLIS = (\d+)L \* 60L""").find(store)!!.groupValues[1].toInt()
        assertTrue("Ring $anzahl < 10 h bei 1/s", anzahl >= 36_000)
        assertTrue("Höchstalter $stunden h < 12 h", stunden >= 12)
    }
}
