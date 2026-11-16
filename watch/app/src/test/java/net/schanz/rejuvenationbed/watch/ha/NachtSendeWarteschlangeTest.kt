package net.schanz.rejuvenationbed.watch.ha

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Wiederholung ohne Doppelung: fehlgeschlagene Sendungen bleiben, gleiche Schlüssel ersetzen. */
class NachtSendeWarteschlangeTest {

    private fun stellen(warte: NachtSendeWarteschlange, schluessel: String, json: String, jetzt: Long = 100L) {
        warte.anstellen(NachtBerichtBauer.TYPE_DATEN, schluessel, json, jetzt)
    }

    @Test
    fun fehlgeschlageneSendungBleibtMitVersuchszahl() {
        val warte = NachtSendeWarteschlange()
        stellen(warte, "daten-2026-11-15-1000", "{\"a\":1}")
        warte.alsFehlgeschlagen("daten-2026-11-15-1000", 200L)
        warte.alsFehlgeschlagen("daten-2026-11-15-1000", 300L)
        assertEquals("bleibt stehen — die Wiederholung", 1, warte.umfasst())
        assertEquals("Versuchszähler steigt", 2, warte.alle().single().versuche)
        assertEquals(300L, warte.alle().single().zuletztEpochMillis)
    }

    @Test
    fun erledigteSendungGehtHeraus() {
        val warte = NachtSendeWarteschlange()
        stellen(warte, "daten-2026-11-15-1000", "{\"a\":1}")
        warte.alsErledigt("daten-2026-11-15-1000")
        assertTrue(warte.istLeer())
    }

    @Test
    fun gleicherSchluesselErsetztOhneDoppelung() {
        val warte = NachtSendeWarteschlange()
        stellen(warte, "daten-2026-11-15-1000", "{\"a\":1}", jetzt = 100L)
        stellen(warte, "daten-2026-11-15-1000", "{\"a\":2}", jetzt = 500L)
        assertEquals("ein Eintrag, nicht zwei", 1, warte.umfasst())
        assertEquals("neuer Inhalt", "{\"a\":2}", warte.alle().single().json)
        assertEquals("ursprünglicher Anstell-Zeitpunkt bleibt", 100L, warte.alle().single().zuletztEpochMillis)
    }

    @Test
    fun fehlgeschlagenerUndNeuAngestellterSchluesselBehaeltVersuche() {
        val warte = NachtSendeWarteschlange()
        stellen(warte, "nacht-2026-11-15", "{}")
        warte.alsFehlgeschlagen("nacht-2026-11-15", 200L)
        stellen(warte, "nacht-2026-11-15", "{}")
        assertEquals("Wiederholung zählt weiter", 1, warte.alle().single().versuche)
    }

    @Test
    fun reihenfolgeAeltesterErster() {
        val warte = NachtSendeWarteschlange()
        stellen(warte, "nacht-2026-11-14", "{}", jetzt = 1L)
        stellen(warte, "daten-2026-11-14-1000", "{}", jetzt = 2L)
        stellen(warte, "daten-2026-11-14-2000", "{}", jetzt = 3L)
        assertEquals("nacht-2026-11-14", warte.naechster()?.schluessel)
        warte.alsErledigt("nacht-2026-11-14")
        assertEquals("daten-2026-11-14-1000", warte.naechster()?.schluessel)
    }

    @Test
    fun volleWarteschlangeWirftAeltestenHeraus() {
        val warte = NachtSendeWarteschlange(maximaleGroesse = 2)
        stellen(warte, "a", "{}", jetzt = 1L)
        stellen(warte, "b", "{}", jetzt = 2L)
        val verworfen = warte.anstellen(NachtBerichtBauer.TYPE_DATEN, "c", "{}", 3L)
        assertEquals("der Älteste wich", 1, verworfen)
        assertFalse(warte.enthaelt("a"))
        assertTrue(warte.enthaelt("b"))
        assertTrue(warte.enthaelt("c"))
    }

    @Test
    fun unbrauchbareEintraegeWerdenNichtAngestellt() {
        val warte = NachtSendeWarteschlange()
        assertEquals(0, warte.anstellen(NachtBerichtBauer.TYPE_DATEN, "", "{}", 1L))
        assertEquals(0, warte.anstellen("", "x", "{}", 1L))
        assertTrue(warte.istLeer())
    }

    @Test
    fun jsonRundtripMitVersuchszahl() {
        val warte = NachtSendeWarteschlange()
        stellen(warte, "daten-2026-11-15-1000", "{\"a\":1}", jetzt = 100L)
        warte.alsFehlgeschlagen("daten-2026-11-15-1000", 150L)
        stellen(warte, "nacht-2026-11-15", "{}", jetzt = 200L)
        val geladen = NachtSendeWarteschlange.ausJson(warte.alsJson())
        assertEquals(2, geladen.umfasst())
        assertEquals(1, geladen.alle().first { it.schluessel == "daten-2026-11-15-1000" }.versuche)
        assertEquals(0, geladen.alle().first { it.schluessel == "nacht-2026-11-15" }.versuche)
        assertEquals(
            "der letzte Versuch bleibt erhalten",
            150L,
            geladen.alle().first { it.schluessel == "daten-2026-11-15-1000" }.zuletztEpochMillis
        )
    }

    @Test
    fun unlesbareAblageErgibtLeereWarteschlange() {
        assertTrue(NachtSendeWarteschlange.ausJson(null).istLeer())
        assertTrue(NachtSendeWarteschlange.ausJson("").istLeer())
        assertTrue(NachtSendeWarteschlange.ausJson("kein JSON").istLeer())
        assertTrue(NachtSendeWarteschlange.ausJson("[{\"schluessel\":\"\",\"art\":\"x\",\"json\":\"{}\"}]").istLeer())
    }
}
