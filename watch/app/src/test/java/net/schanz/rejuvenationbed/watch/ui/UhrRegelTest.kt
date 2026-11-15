package net.schanz.rejuvenationbed.watch.ui

import net.schanz.chance.gestalt.GestaltRegel
import net.schanz.rejuvenationbed.watch.health.HeartRateCapability
import net.schanz.rejuvenationbed.watch.health.PlatformSleepState
import net.schanz.rejuvenationbed.watch.nowbar.NowBarText
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Die Regeln dieser App. Die allgemeinen Gesetze (Farben, Kontrast, Raum) prüft das chance-framework selbst. */
class UhrRegelTest {
    @Test
    fun statusTraegtImmerEinWort() {
        val faelle = listOf(
            UhrRegel.schlafStatus(HeartRateCapability.Checking, false, "not_started", false),
            UhrRegel.schlafStatus(HeartRateCapability.Unsupported, false, "not_started", false),
            UhrRegel.schlafStatus(HeartRateCapability.Failed("x"), false, "not_started", false),
            UhrRegel.schlafStatus(HeartRateCapability.Supported, true, "not_started", false),
            UhrRegel.schlafStatus(HeartRateCapability.Supported, false, "not_started", false),
            UhrRegel.schlafStatus(HeartRateCapability.Supported, false, "registered", false),
            UhrRegel.schlafStatus(HeartRateCapability.Supported, false, "collecting", false),
            UhrRegel.schlafStatus(HeartRateCapability.Supported, false, "permission_lost", false)
        )
        faelle.forEach { assertTrue(it.wort.isNotBlank()) }
        assertEquals(GestaltRegel.StatusArt.BEREIT, faelle[4].art)
        assertEquals(GestaltRegel.StatusArt.LAEUFT, faelle[6].art)
        assertEquals(GestaltRegel.StatusArt.FEHLER, faelle[7].art)
    }

    @Test
    fun losKnopfFolgtDemZustand() {
        val s = HeartRateCapability.Supported
        assertEquals("MESSEN", UhrRegel.losKnopf(s, false, "not_started", false))
        assertEquals("ERLAUBEN", UhrRegel.losKnopf(s, true, "not_started", false))
        assertEquals("STOPP", UhrRegel.losKnopf(s, false, "collecting", false))
        assertEquals("—", UhrRegel.losKnopf(HeartRateCapability.Unsupported, false, "not_started", false))
    }

    @Test
    fun gesichtFolgtUhrzeitSchlafUndWahl() {
        val auto = UhrRegel.GesichtWahl.AUTO
        assertEquals(GestaltRegel.Modus.BETT, UhrRegel.gesicht(auto, 23, null))
        assertEquals(GestaltRegel.Modus.SOFA, UhrRegel.gesicht(auto, 18, null))
        assertEquals(GestaltRegel.Modus.SOFA, UhrRegel.gesicht(auto, 18, PlatformSleepState.AWAKE))
        assertEquals(GestaltRegel.Modus.BETT, UhrRegel.gesicht(auto, 15, PlatformSleepState.ASLEEP))
        assertEquals(GestaltRegel.Modus.SOFA, UhrRegel.gesicht(UhrRegel.GesichtWahl.SOFA, 2, PlatformSleepState.ASLEEP))
        assertEquals(GestaltRegel.Modus.BETT, UhrRegel.gesicht(UhrRegel.GesichtWahl.BETT, 12, null))
    }

    @Test
    fun gesichtWahlSchaltetDurchUndLiestSichZurueck() {
        assertEquals(UhrRegel.GesichtWahl.BETT, UhrRegel.GesichtWahl.AUTO.naechste())
        assertEquals(UhrRegel.GesichtWahl.SOFA, UhrRegel.GesichtWahl.BETT.naechste())
        assertEquals(UhrRegel.GesichtWahl.AUTO, UhrRegel.GesichtWahl.SOFA.naechste())
        assertEquals(UhrRegel.GesichtWahl.BETT, UhrRegel.GesichtWahl.aus(" bett "))
        assertEquals(UhrRegel.GesichtWahl.AUTO, UhrRegel.GesichtWahl.aus(null))
        assertEquals(UhrRegel.GesichtWahl.AUTO, UhrRegel.GesichtWahl.aus("quatsch"))
    }

    @Test
    fun dasEingebauteFrameworkHaeltSeineGesetze() {
        GestaltRegel.Modus.entries.forEach { assertTrue(it.name, GestaltRegel.kontrastGesetz(it)) }
        assertTrue(GestaltRegel.bettIstWarmUndGedimmt())
    }

    @Test
    fun bettSchriftHaeltDieFundPaare() {
        // Fund w14-tp: grau2 und ROT_BETT treten im Bett als echte Schrift auf (SchlafInfo, ThermoBlatt,
        // DebugBlatt, BlattHinweis, inaktiver Los-Knopf). Jede Bett-Schrift hält ≥ 4,5:1 auf jeder
        // Bett-Fläche und bleibt ≤ 7,5:1 gegen Schwarz; die Zahlen sind mit der WCAG-Formel gerechnet.
        val r = GestaltRegel.rollen(GestaltRegel.Modus.BETT)
        val schriften = listOf(
            "text" to r.text, "grau" to r.grau, "grau2" to r.grau2,
            "akzent" to r.akzent, "ROT_BETT" to GestaltRegel.ROT_BETT
        )
        val flaechen = listOf(
            "hintergrund" to r.hintergrund, "karte" to r.karte,
            "gedrueckt" to r.gedrueckt, "knopf" to r.knopf
        )
        schriften.forEach { (name, schrift) ->
            flaechen.forEach { (flaeche, hintergrund) ->
                assertTrue(
                    "$name auf $flaeche: ${GestaltRegel.kontrast(schrift, hintergrund)}",
                    GestaltRegel.kontrast(schrift, hintergrund) >= GestaltRegel.KONTRAST_MINDESTENS
                )
            }
            assertTrue(
                "$name auf Schwarz zu hell: ${GestaltRegel.kontrast(schrift, r.hintergrund)}",
                GestaltRegel.kontrast(schrift, r.hintergrund) <= GestaltRegel.BETT_TEXT_HOECHSTENS
            )
        }
        // Die im Fund genannten Lücken, mit den geheilten Tokens geschlossen (Δ 0,001):
        assertEquals(5.0546, GestaltRegel.kontrast(r.grau2, r.hintergrund), 0.001)
        assertEquals(5.2442, GestaltRegel.kontrast(GestaltRegel.ROT_BETT, r.hintergrund), 0.001)
        assertEquals(4.7707, GestaltRegel.kontrast(r.grau2, r.knopf), 0.001)
        // Die gesetzlichen Paare bleiben unverändert:
        assertEquals(6.9333, GestaltRegel.kontrast(r.text, r.hintergrund), 0.001)
        assertEquals(4.8535, GestaltRegel.kontrast(r.grau, r.gedrueckt), 0.001)
    }

    @Test
    fun nowBarTextIstKurz() {
        assertEquals("62 bpm", NowBarText.puls(62.4))
        assertEquals("misst", NowBarText.puls(null))
        assertEquals("misst", NowBarText.kuerzen("  "))
        val lang = NowBarText.kuerzen("Schlafmessung läuft gerade")
        assertTrue(lang.length <= NowBarText.MAX_ZEICHEN)
        assertTrue(lang.endsWith("…"))
        assertFalse(NowBarText.kuerzen("misst").endsWith("…"))
    }
}
