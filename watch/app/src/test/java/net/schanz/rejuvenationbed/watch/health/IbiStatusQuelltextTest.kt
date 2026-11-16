package net.schanz.rejuvenationbed.watch.health

import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.file.Files
import java.nio.file.Path

/**
 * #8/Ziel B: Die IBI-Quelle ist ohne Samsung-Partner-Zugang nicht verfügbar.
 * Damit das nicht in stillen Leerlauf fällt, benennt der Messstart im
 * Protokoll (Art „IBI“) den Zustand der Quelle samt Grund. Der Registrierungs-
 * Code hängt an Android und läuft nicht in der JVM — diese Wache liest den
 * Quelltext und pinnt die Stelle.
 */
class IbiStatusQuelltextTest {
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
    fun messstartNenntDenIbiQuellenStatus() {
        val start = rumpf(quelle("PassiveHeartRateRegistration.kt"), "start")
        assertTrue("der Messstart muss den IBI-Status ins Protokoll schreiben", "\"IBI\"" in start)
        assertTrue("die IBI-Zeile muss einen benannten Grund enthalten", "nicht verfügbar" in start)
        assertTrue("die IBI-Zeile muss die Quelle benennen", "Quelle" in start)
    }

    @Test
    fun adapterNenntDenPartnerZugangAlsGrund() {
        val text = quelle("IbiQuelle.kt")
        assertTrue(
            "der Adapter muss die fehlende AAR samt Partner-Zugang benennen",
            "Samsung-AAR fehlt" in text && "Partner-Zugang" in text
        )
    }
}
