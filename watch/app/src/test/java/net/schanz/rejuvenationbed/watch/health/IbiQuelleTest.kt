package net.schanz.rejuvenationbed.watch.health

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class IbiQuelleTest {
    @Test
    fun fakeEmitsDeterministicSamplesThroughTheAdapterContract() {
        val samples = listOf(
            IbiMesspunkt(1_000L, 820.0),
            IbiMesspunkt(2_000L, 810.0, 0.95)
        )
        val source = FakeIbiQuelle(samples)
        val received = mutableListOf<IbiMesspunkt>()

        assertEquals(IbiQuelleStatus.Verfuegbar, source.status())
        assertEquals(IbiStartErgebnis.Gestartet, source.starten(IbiEmpfaenger(received::add)))
        assertEquals(samples, received)
        source.stoppen()
    }

    @Test
    fun unavailableFakeFailsClosed() {
        val source = FakeIbiQuelle(emptyList(), verfuegbar = false)
        assertFalse(source.status() is IbiQuelleStatus.Verfuegbar)
        assertTrue(source.starten(IbiEmpfaenger { error("must not emit") }) is IbiStartErgebnis.NichtVerfuegbar)
    }

    @Test
    fun samsungAdapterNamesMissingAarInsteadOfPretendingToMeasure() {
        val source = SamsungHealthSensorSdkIbiQuelle()
        val status = source.status()
        assertTrue(status is IbiQuelleStatus.NichtVerfuegbar)
        assertTrue((status as IbiQuelleStatus.NichtVerfuegbar).grund.contains("AAR"))
        assertTrue(source.starten(IbiEmpfaenger { error("must not emit") }) is IbiStartErgebnis.NichtVerfuegbar)
    }

    @Test
    fun ibIQualityMustBeInRange() {
        runCatching { IbiMesspunkt(1L, 800.0, 1.1) }
            .onSuccess { error("invalid quality accepted") }
    }
}
