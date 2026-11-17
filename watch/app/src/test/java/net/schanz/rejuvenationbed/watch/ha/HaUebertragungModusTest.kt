package net.schanz.rejuvenationbed.watch.ha

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Schalter-Zustand: Standard „Nur Schlafphase“, Unbekanntes fällt zurück, Wire-Werte klar. */
class HaUebertragungModusTest {

    @Test
    fun standardIstNurSchlafphase() {
        assertEquals(HaUebertragungModus.PHASE_ONLY, HaUebertragungModus.standard())
    }

    @Test
    fun ausNullIstStandard() {
        assertEquals(HaUebertragungModus.PHASE_ONLY, HaUebertragungModus.aus(null))
        assertEquals(HaUebertragungModus.PHASE_ONLY, HaUebertragungModus.aus(""))
    }

    @Test
    fun beideStellungenLesenSichZurueck() {
        HaUebertragungModus.entries.forEach { modus ->
            assertEquals(modus, HaUebertragungModus.aus(modus.wireValue))
        }
    }

    @Test
    fun unbekannterWertFaelltAufStandard() {
        // fail-closed: ein Nutzlast- oder Speicherwert, den die Uhr nicht kennt,
        // erweitert die Übertragung nicht stillschweigend.
        assertEquals(HaUebertragungModus.PHASE_ONLY, HaUebertragungModus.aus("alles"))
    }

    @Test
    fun wireWerteSindUnterscheidbar() {
        assertTrue(
            "die Stellungen brauchen verschiedene Wire-Werte",
            HaUebertragungModus.entries.map { it.wireValue }.toSet().size == HaUebertragungModus.entries.size
        )
    }

    @Test
    fun dieEngeStellungNenntDieReihenDieBleiben() {
        val liste = HaUebertragungModus.PHASE_ONLY.nichtUebermittelt
        assertTrue("Puls-Reihe bleibt lokal", liste.any { it.contains("Puls-Reihe") })
        assertTrue("IBI-Reihe bleibt lokal", liste.any { it.contains("IBI-Reihe") })
        assertTrue("Bewegungsfenster bleiben lokal", liste.any { it.contains("Bewegungsfenster") })
    }

    @Test
    fun dieBreiteStellungNenntDieReihenDieGehen() {
        val liste = HaUebertragungModus.GESAMTDATEN.uebertrageneWerte
        assertTrue("Puls-Reihe geht", liste.any { it.contains("Puls-Reihe") })
        assertTrue("IBI-Reihe geht, wenn eine Quelle da ist", liste.any { it.contains("IBI-Reihe") })
        assertTrue("Bewegungsfenster gehen", liste.any { it.contains("Bewegungsfenster") })
        assertTrue("Plattform-Reihe geht", liste.any { it.contains("Plattform-Schlafstatus") })
    }

    @Test
    fun keineStellungVersprichtKanaeleDieDieUhrNichtLiefert() {
        // Atemfrequenz, SpO2 und Hauttemperatur stehen NUR im „Nicht“-Anteil —
        // die Uhr hat diese Kanäle nicht, sie werden nie erfunden (!19).
        HaUebertragungModus.entries.forEach { modus ->
            assertFalse(
                "${modus.name} darf die fehlenden Kanäle nicht als übertragen ankündigen",
                modus.uebertrageneWerte.any { it.contains("SpO2") || it.contains("Atemfrequenz") || it.contains("Hauttemperatur") }
            )
        }
        assertTrue(
            "die Breite Stellung benennt die fehlenden Kanäle ehrlich",
            HaUebertragungModus.GESAMTDATEN.nichtUebermittelt.any { it.contains("SpO2") }
        )
    }
}
