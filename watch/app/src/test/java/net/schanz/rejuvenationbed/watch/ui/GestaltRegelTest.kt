package net.schanz.rejuvenationbed.watch.ui

import net.schanz.rejuvenationbed.watch.health.HeartRateCapability
import net.schanz.rejuvenationbed.watch.nowbar.NowBarText
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class GestaltRegelTest {
    @Test
    fun raumLeiterIstDerVierertakt() {
        assertEquals(listOf(4, 8, 12, 16, 24, 40), (1..6).map { GestaltRegel.raum(it) })
        GestaltRegel.RAUM_LEITER.forEach { assertEquals(0, it % 4) }
    }

    @Test(expected = IllegalArgumentException::class)
    fun raumNebenDerLeiterIstVerboten() {
        GestaltRegel.raum(7)
    }

    @Test
    fun jederFuenfteStrichIstLangUndStrichNullStehtOben() {
        assertEquals(12, (0 until GestaltRegel.STRICHE).count { GestaltRegel.strichLang(it) })
        assertEquals(-90.0, GestaltRegel.strichWinkel(0), 1e-9)
        assertEquals(0.0, GestaltRegel.strichWinkel(15), 1e-9)
    }

    @Test
    fun ringAnteilBleibtZwischenNullUndEins() {
        assertEquals(0f, GestaltRegel.ringAnteil(3, 0), 0f)
        assertEquals(0.5f, GestaltRegel.ringAnteil(2, 4), 1e-6f)
        assertEquals(1f, GestaltRegel.ringAnteil(9, 4), 0f)
    }

    @Test
    fun amoledIstEchtSchwarzUndDerAkzentIstDerBernstein() {
        assertEquals(0xFF000000.toInt(), GestaltRegel.HINTERGRUND)
        assertEquals(0xFFD99130.toInt(), GestaltRegel.AKZENT)
    }

    @Test
    fun jedeSchriftHaeltAaAufSchwarz() {
        listOf(GestaltRegel.TEXT, GestaltRegel.GRAU, GestaltRegel.GRAU2, GestaltRegel.AKZENT).forEach { farbe ->
            assertTrue(GestaltRegel.kontrast(farbe, GestaltRegel.HINTERGRUND) >= 4.5)
        }
        assertTrue(GestaltRegel.kontrast(GestaltRegel.TEXT_AUF_AKZENT, GestaltRegel.AKZENT) >= 4.5)
    }

    @Test
    fun typoSkalaSteigtMonoton() {
        val skala = listOf(GestaltRegel.TYPO_KLEIN, GestaltRegel.TYPO_TEXT, GestaltRegel.TYPO_HELD, GestaltRegel.TYPO_BUEHNE)
        assertEquals(skala.sorted(), skala)
        assertEquals(skala.size, skala.toSet().size)
    }

    @Test
    fun statusTraegtImmerEinWort() {
        val faelle = listOf(
            GestaltRegel.schlafStatus(HeartRateCapability.Checking, false, "not_started", false),
            GestaltRegel.schlafStatus(HeartRateCapability.Unsupported, false, "not_started", false),
            GestaltRegel.schlafStatus(HeartRateCapability.Failed("x"), false, "not_started", false),
            GestaltRegel.schlafStatus(HeartRateCapability.Supported, true, "not_started", false),
            GestaltRegel.schlafStatus(HeartRateCapability.Supported, false, "not_started", false),
            GestaltRegel.schlafStatus(HeartRateCapability.Supported, false, "registered", false),
            GestaltRegel.schlafStatus(HeartRateCapability.Supported, false, "collecting", false),
            GestaltRegel.schlafStatus(HeartRateCapability.Supported, false, "permission_lost", false)
        )
        faelle.forEach { assertTrue(it.wort.isNotBlank()) }
        assertEquals(GestaltRegel.StatusArt.BEREIT, faelle[4].art)
        assertEquals(GestaltRegel.StatusArt.LAEUFT, faelle[6].art)
        assertEquals(GestaltRegel.StatusArt.FEHLER, faelle[7].art)
    }

    @Test
    fun losKnopfFolgtDemZustand() {
        val s = HeartRateCapability.Supported
        assertEquals("MESSEN", GestaltRegel.losKnopf(s, false, "not_started", false))
        assertEquals("ERLAUBEN", GestaltRegel.losKnopf(s, true, "not_started", false))
        assertEquals("STOPP", GestaltRegel.losKnopf(s, false, "collecting", false))
        assertEquals("—", GestaltRegel.losKnopf(HeartRateCapability.Unsupported, false, "not_started", false))
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
