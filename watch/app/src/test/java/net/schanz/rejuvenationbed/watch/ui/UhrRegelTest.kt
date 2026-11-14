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
