package net.schanz.rejuvenationbed.watch.blatt

import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.file.Files
import java.nio.file.Path

/**
 * Die Abgleich-Statuszeilen des Schlaf-Blatts sind Compose-UI und werden von den JVM-Unit-Tests nicht
 * gerendert – Fund w14-tu: ein § statt $ brach dort die String-Interpolation, android-watch blieb grün
 * und die Diagnose der Watch-4-Nacht zeigte die wörtliche Vorlage statt des Fehlertexts. Diese Wache
 * liest den Quelltext des Blatts und pinnt beide Stellen, falls die Interpolation wieder gebrochen wird.
 */
class SchlafBlattQuelltextTest {
    private val relativ = "src/main/java/net/schanz/rejuvenationbed/watch/blatt/SchlafBlatt.kt"

    /** Findet SchlafBlatt.kt vom Arbeitsverzeichnis aufwärts (Gradle läuft je nach Aufruf woanders). */
    private fun quelle(): Path {
        var ort: Path? = Path.of(System.getProperty("user.dir"))
        repeat(8) {
            ort?.let { basis ->
                listOf(relativ, "watch/app/$relativ").forEach { kandidat ->
                    val datei = basis.resolve(kandidat)
                    if (Files.isRegularFile(datei)) return datei
                }
            }
            ort = ort?.parent
        }
        throw AssertionError("SchlafBlatt.kt nicht gefunden (von ${System.getProperty("user.dir")} aufwärts gesucht)")
    }

    @Test
    fun dieQuelleHatKeinAbsatzZeichen() {
        val treffer = Files.readString(quelle()).lines()
            .mapIndexedNotNull { i, zeile -> if ('§' in zeile) i + 1 else null }
        assertTrue("§ in Zeilen $treffer: String-Interpolation bricht und der Fehlertext geht verloren", treffer.isEmpty())
    }

    @Test
    fun dieAbgleichFehlerZeilenInterpolieren() {
        val text = Files.readString(quelle())
        assertTrue("die „Nicht gesendet“-Zeile fehlt oder interpoliert nicht", "Nicht gesendet: \${" in text)
        assertTrue("die „Nicht bereit“-Zeile fehlt oder interpoliert nicht", "Nicht bereit: \${" in text)
    }

    /**
     * #8/Ziel C: „Phase: unbekannt“ ohne Wort ist für niemanden brauchbar.
     * Das Gesicht nennt den Grund (Schalter AUS / keine IBI / zu wenige IBI),
     * die Info-Ebene sagt es ausdrücklich in Worten.
     */
    @Test
    fun derFehlendePhasenGrundIstSichtbar() {
        val text = Files.readString(quelle())
        assertTrue(
            "das Gesicht muss den Grund der unbekannten Phase anzeigen",
            "Phase: unbekannt · \${stand.schaetzung.grund}" in text
        )
        assertTrue(
            "die Info-Ebene muss den Grund ausdrücklich benennen",
            "keine Phasen, weil: \${stand.schaetzung.grund}" in text
        )
    }
}
