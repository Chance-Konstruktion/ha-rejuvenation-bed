package net.schanz.rejuvenationbed.watch.debug

import net.schanz.rejuvenationbed.watch.health.HeartRateSample
import net.schanz.rejuvenationbed.watch.health.StepIntervalSample
import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.ZoneOffset

class DebugTextTest {
    private val utc = ZoneOffset.UTC

    @Test
    fun alterInSekundenMinutenStunden() {
        assertEquals("12 s", DebugText.alter(12_400L))
        assertEquals("7 min", DebugText.alter(7 * 60_000L + 5_000L))
        assertEquals("3 h 05", DebugText.alter(3 * 3_600_000L + 5 * 60_000L))
        assertEquals("0 s", DebugText.alter(-50L))
    }

    @Test
    fun lieferungNenntAnzahlSpanneUndVerzug() {
        val basis = 1_700_000_000_000L // 2023-11-14 22:13:20 UTC
        val puls = listOf(
            HeartRateSample(basis, 58.0),
            HeartRateSample(basis + 60_000L, 64.4)
        )
        val schritte = listOf(StepIntervalSample(basis, basis + 60_000L, 17))
        val text = DebugText.lieferung(puls, schritte, basis + 60_000L + 240_000L, utc)
        assertEquals("Puls 2 (58–64 bpm, 22:13–22:14, Verzug 4 min) · Schritte 1 (17)", text)
    }

    @Test
    fun leereLieferungBleibtLesbar() {
        assertEquals("Puls 0 · Schritte 0", DebugText.lieferung(emptyList(), emptyList(), 0L, utc))
    }
}
