package net.schanz.rejuvenationbed.watch.health

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Aufbewahrung nach ZEIT (#8, Ziel A): der alte 45.000-Werte-Ring ließ die
 * ersten 28 min der Nacht 15./16.11. verschwinden. Die neue Grenze ist reine
 * JVM-Logik und wird hier direkt geprüft: 36 h bei 1 Hz ohne Verlust, der
 * Randfall an der Untergrenze, keine Anzahl-Grenze, Übernahme alter Daten.
 */
class PulsAufbewahrungTest {
    private val jetzt = 1_700_000_000_000L

    /** 1-Hz-Reihe, der jüngste Wert liegt bei `jetzt`. */
    private fun reiheBeiEinHertz(anzaehler: Int): List<HeartRateSample> =
        (0 until anzaehler).map { index ->
            HeartRateSample(
                measuredAtEpochMillis = jetzt - (anzaehler - 1 - index) * 1000L,
                beatsPerMinute = 50.0 + (index % 11)
            )
        }

    @Test
    fun sechsunddreissigStundenBeiEinHertzBleibenOhneVerlust() {
        val reihe = reiheBeiEinHertz(36 * 3600 + 1) // 129.601 Werte, 36 h inkl. Rändern
        val behalten = PulsAufbewahrung.imZeitfenster(reihe, jetzt)
        assertEquals(reihe.size, behalten.size)
        assertEquals(PulsAufbewahrung.untergrenze(jetzt), behalten.first().measuredAtEpochMillis)
        assertEquals(jetzt, behalten.last().measuredAtEpochMillis)
    }

    @Test
    fun eineSekundeUeberDerGrenzeFaellt() {
        val reihe = reiheBeiEinHertz(36 * 3600 + 2) // 36 h + 1 s
        val behalten = PulsAufbewahrung.imZeitfenster(reihe, jetzt)
        assertEquals(36 * 3600 + 1, behalten.size)
        assertTrue(
            "der älteste verlorene Wert liegt vor der Untergrenze",
            behalten.all { it.measuredAtEpochMillis >= PulsAufbewahrung.untergrenze(jetzt) }
        )
    }

    @Test
    fun zukuenftigeWerteFallen() {
        val reihe = listOf(
            HeartRateSample(jetzt - 1_000L, 60.0),
            HeartRateSample(jetzt + 5_000L, 61.0)
        )
        val behalten = PulsAufbewahrung.imZeitfenster(reihe, jetzt)
        assertEquals(listOf(jetzt - 1_000L), behalten.map { it.measuredAtEpochMillis })
    }

    @Test
    fun keineAnzahlGrenze() {
        // 100.000 Werte innerhalb von ~2 h (5 Hz-Abstand): weit über dem alten
        // 45.000-Ring — die Zeitgrenze kennt keine Anzahl-Obergrenze.
        val reihe = (0 until 100_000).map { index ->
            HeartRateSample(jetzt - 2L * 60L * 60L * 1000L + index * 72L, 55.0)
        }
        assertEquals(100_000, PulsAufbewahrung.imZeitfenster(reihe, jetzt).size)
    }

    @Test
    fun uebernahmeAlterDatenVeraltetesFaelltNeuesBleibt() {
        // Nachbildung der Migration: der alte Pref-Ring enthält veraltete und
        // frische Werte; übernommen wird nur das Zeitfenster.
        val alt = listOf(
            HeartRateSample(jetzt - 40L * 60L * 60L * 1000L, 58.0), // veraltet
            HeartRateSample(jetzt - 20L * 60L * 60L * 1000L, 57.0), // bleibt
            HeartRateSample(jetzt - 60L * 60L * 1000L, 56.0),       // bleibt
            HeartRateSample(jetzt, 55.0)                            // bleibt
        )
        val uebernommen = PulsAufbewahrung.imZeitfenster(alt, jetzt)
        assertEquals(3, uebernommen.size)
        assertTrue(uebernommen.all { it.measuredAtEpochMillis >= PulsAufbewahrung.untergrenze(jetzt) })
    }
}
