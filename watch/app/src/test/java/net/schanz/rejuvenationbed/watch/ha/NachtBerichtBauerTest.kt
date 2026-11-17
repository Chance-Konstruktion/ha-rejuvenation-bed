package net.schanz.rejuvenationbed.watch.ha

import net.schanz.rejuvenationbed.watch.analysis.SleepHrvFeatures
import net.schanz.rejuvenationbed.watch.health.HeartRateSample
import net.schanz.rejuvenationbed.watch.health.IbiMesspunkt
import net.schanz.rejuvenationbed.watch.health.StepIntervalSample
import net.schanz.rejuvenationbed.watch.sleep.SleepStage
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.ZoneId

/**
 * Nutzlast je Schalter-Stellung — alles synthetisch (keine echten Nächte).
 * Der Vertrag entspricht HA (rejuvenation-bed-night-report-v1): Zeitstempel
 * mit Offset, Ergebnis immer, Rohreihen nur als Gesamtdaten-Pakete.
 */
class NachtBerichtBauerTest {

    private val zone: ZoneId = ZoneId.of("Europe/Berlin")

    // 2026-11-15T23:10+01:00 — fester synthetischer Zeitpunkt, damit die Tests
    // deterministisch bleiben; der Offset (+01:00) muss in der Nutzlast stehen.
    private val start = 1794780600000L // 2026-11-15T23:10+01:00
    private val ende = start + 8L * 60L * 60L * 1000L

    private fun pulsSerie(): List<HeartRateSample> = (0 until 40).map {
        HeartRateSample(
            measuredAtEpochMillis = start + it * 5L * 60L * 1000L + 1_000L,
            beatsPerMinute = 52.0 + it % 7
        )
    }

    private fun schrittSerie(): List<StepIntervalSample> = (0 until 10).map {
        StepIntervalSample(
            startEpochMillis = start + it * 45L * 60L * 1000L,
            endEpochMillis = start + it * 45L * 60L * 1000L + 300_000L,
            steps = 3L + it
        )
    }

    private fun fensterErgebnis(nr: Int, stage: SleepStage) = NachtFensterErgebnis(
        startEpochMillis = start + nr * 30L * 60L * 1000L,
        endEpochMillis = start + (nr + 1) * 30L * 60L * 1000L,
        stage = stage,
        confidence = 0.8,
        sampleCoverage = 0.9,
        algorithmVersion = "puls-bewegung-grob-0.1"
    )

    private fun hrvVerlaesslich(): SleepHrvFeatures = SleepHrvFeatures(
        startEpochMillis = start,
        endEpochMillis = ende,
        rawIbiCount = 200,
        acceptedIbiCount = 180,
        rejectedIbiCount = 20,
        meanIbiMillis = 980.0,
        rmssdMillis = 41.5,
        sdnnMillis = 57.2,
        ibiCoverage = 0.85,
        signalQuality = 0.9,
        movementBucketCount = 16,
        movementCoverage = 0.9,
        movementVarianceStepsPerMinuteSquared = 2.0
    )

    // ── laufende Phase ─────────────────────────────────────────────────────

    @Test
    fun phasenUpdateTraegtStellungUndOffset() {
        val schaetzung = net.schanz.rejuvenationbed.watch.sleep.SleepStageEstimate(
            stage = SleepStage.DEEP,
            confidence = 0.82,
            sampleCoverage = 0.9,
            measuredAtEpochMillis = ende,
            algorithmVersion = "puls-bewegung-grob-0.1"
        )
        val json = JSONObject(
            NachtBerichtBauer.bauePhasenUpdate(schaetzung, HaUebertragungModus.PHASE_ONLY, zone, jetztEpochMillis = ende + 60_000L)
        )
        assertEquals(NachtBerichtBauer.SCHEMA, json.getString("schema"))
        assertEquals(NachtBerichtBauer.TYPE_PHASE, json.getString("type"))
        assertEquals("deep", json.getString("stage"))
        assertEquals("phase_only", json.getString("modus"))
        assertEquals("estimate", json.getString("source"))
        assertTrue("measured_at MUSS mit Offset kommen (HA lehnt ohne Offset ab)", json.getString("measured_at").contains("+01:00"))
    }

    @Test
    fun phasenUpdateAusIbiTraegtEstimateIbiQuelle() {
        val schaetzung = net.schanz.rejuvenationbed.watch.sleep.SleepStageEstimate(
            stage = SleepStage.REM,
            confidence = 0.8,
            sampleCoverage = 0.9,
            measuredAtEpochMillis = ende,
            algorithmVersion = "m2-rules-0.1"
        )
        val json = JSONObject(
            NachtBerichtBauer.bauePhasenUpdate(schaetzung, HaUebertragungModus.GESAMTDATEN, zone, jetztEpochMillis = ende + 60_000L)
        )
        assertEquals("estimate-ibi", json.getString("source"))
        assertEquals("gesamtdaten", json.getString("modus"))
    }

    @Test(expected = IllegalArgumentException::class)
    fun veraltetePhaseWirdNichtGesendet() {
        val schaetzung = net.schanz.rejuvenationbed.watch.sleep.SleepStageEstimate(
            stage = SleepStage.DEEP,
            confidence = 0.82,
            sampleCoverage = 0.9,
            measuredAtEpochMillis = ende,
            algorithmVersion = "puls-bewegung-grob-0.1"
        )
        NachtBerichtBauer.bauePhasenUpdate(schaetzung, HaUebertragungModus.PHASE_ONLY, zone, jetztEpochMillis = ende + 10L * 60L * 1000L)
    }

    // ── Nachtbericht je Stellung ───────────────────────────────────────────

    private fun baueBericht(modus: HaUebertragungModus, hrv: SleepHrvFeatures?): JSONObject = JSONObject(
        NachtBerichtBauer.baueNachtbericht(
            nachtStartEpochMillis = start,
            nachtEndeEpochMillis = ende,
            fenster = listOf(fensterErgebnis(0, SleepStage.LIGHT), fensterErgebnis(1, SleepStage.DEEP)),
            puls = pulsSerie(),
            ibi = emptyList(),
            schritte = schrittSerie(),
            hrv = hrv,
            modus = modus,
            zone = zone
        )
    )

    @Test
    fun beideStellungenTragenDasErgebnis() {
        HaUebertragungModus.entries.forEach { modus ->
            val bericht = baueBericht(modus, hrvVerlaesslich())
            assertEquals(NachtBerichtBauer.SCHEMA, bericht.getString("schema"))
            assertEquals(NachtBerichtBauer.TYPE_NACHT, bericht.getString("type"))
            assertEquals(modus.wireValue, bericht.getString("modus"))
            assertEquals(2, bericht.getJSONArray("phases").length())
            assertTrue("Puls-Zusammenfassung dabei", bericht.has("pulse"))
            assertTrue("Schritte dabei", bericht.has("movement"))
            assertTrue("HRV aus IBI dabei", bericht.has("hrv"))
            assertTrue("start mit Offset", bericht.getString("start").contains("+"))
            assertTrue("end mit Offset", bericht.getString("end").contains("+"))
        }
    }

    @Test
    fun dieEngeStellungTraegtKeineRohreihen() {
        val bericht = baueBericht(HaUebertragungModus.PHASE_ONLY, hrvVerlaesslich())
        assertFalse("keine Puls-Samples im Bericht", bericht.getJSONObject("pulse").has("samples"))
        assertFalse("keine rohen IBI im Bericht", bericht.has("ibi"))
        assertFalse("keine Bewegungsfenster im Bericht", bericht.getJSONObject("movement").has("windows"))
        assertTrue(
            "HRV als Zusammenfassung, mit Herkunft",
            bericht.getJSONObject("hrv").getString("quelle") == "auf der Uhr aus IBI berechnet"
        )
    }

    @Test
    fun dieBreiteStellungTraegtAuchKeineRohreihenImBericht() {
        // Die Reihen laufen als 5-Minuten-Pakete über die Warteschlange — der
        // Bericht bleibt klein; HA mischt die Pakete zur Nacht.
        val bericht = baueBericht(HaUebertragungModus.GESAMTDATEN, hrvVerlaesslich())
        assertFalse(bericht.getJSONObject("pulse").has("samples"))
        assertFalse(bericht.has("ibi"))
    }

    @Test
    fun fehlendeHrvQuelleStehtMitGrundDa() {
        val ohneIbi = baueBericht(HaUebertragungModus.PHASE_ONLY, null)
        assertTrue("hrv_grund benennt: keine IBI", ohneIbi.getString("hrv_grund").contains("keine IBI"))
        val zuWenige = baueBericht(HaUebertragungModus.PHASE_ONLY, hrvVerlaesslich().copy(acceptedIbiCount = 40, rawIbiCount = 60))
        assertTrue(
            "hrv_grund benennt die Grenze",
            zuWenige.getString("hrv_grund").contains("zu wenige brauchbare IBI (40")
        )
    }

    @Test
    fun fehlendeKanaleSindBenannt() {
        val bericht = baueBericht(HaUebertragungModus.PHASE_ONLY, null)
        val kanale = bericht.getJSONObject("channels")
        assertTrue(kanale.has("respiratory_rate"))
        assertTrue(kanale.has("spo2"))
        assertTrue(kanale.has("skin_temperature"))
        assertFalse(kanale.getJSONObject("spo2").getBoolean("provided"))
        assertTrue(kanale.getJSONObject("spo2").getString("reason").isNotBlank())
    }

    @Test
    fun nachtKennungIstDatumDesBeginns() {
        val bericht = baueBericht(HaUebertragungModus.PHASE_ONLY, null)
        assertEquals(10, bericht.getString("night").length)
        assertTrue(bericht.getString("night").startsWith("20"))
    }

    // ── Zeitleiste ─────────────────────────────────────────────────────────

    @Test
    fun gleicheFolgefensterVerschmelzen() {
        val segmente = NachtBerichtBauer.baueZeitleiste(
            listOf(
                fensterErgebnis(0, SleepStage.LIGHT),
                fensterErgebnis(1, SleepStage.LIGHT),
                fensterErgebnis(2, SleepStage.DEEP)
            )
        )
        assertEquals(2, segmente.size)
        assertEquals(SleepStage.LIGHT, segmente[0].stage)
        assertEquals(start + 2 * 30L * 60L * 1000L, segmente[0].endEpochMillis)
        assertEquals(SleepStage.DEEP, segmente[1].stage)
    }

    @Test
    fun unbrauchbareFensterBleibenLuecke() {
        val segmente = NachtBerichtBauer.baueZeitleiste(
            listOf(
                fensterErgebnis(0, SleepStage.LIGHT),
                fensterErgebnis(1, SleepStage.UNKNOWN),
                fensterErgebnis(2, SleepStage.LIGHT)
            )
        )
        assertEquals(2, segmente.size)
        assertEquals(start + 30L * 60L * 1000L, segmente[0].endEpochMillis)
        assertEquals(start + 2 * 30L * 60L * 1000L, segmente[1].startEpochMillis)
    }

    // ── Gesamtdaten-Pakete ─────────────────────────────────────────────────

    private fun pakete(
        modus: HaUebertragungModus,
        puls: List<HeartRateSample> = pulsSerie(),
        schritte: List<StepIntervalSample> = schrittSerie(),
        plattform: List<PlattformWechsel> = listOf(PlattformWechsel(start + 60_000L, "ASLEEP"))
    ) = NachtBerichtBauer.baueDatenPakete(
            nacht = "2026-11-15",
            nachtStartEpochMillis = start,
            nachtEndeEpochMillis = ende,
            puls = puls,
            ibi = emptyList(),
            schritte = schritte,
            plattformWechsel = plattform,
            modus = modus,
            zone = zone
        )

    @Test
    fun paketeNachFuenfMinutenBlocken() {
        val schluessel = pakete(HaUebertragungModus.GESAMTDATEN).map { it.first }
        assertTrue("die Reihe verteilt auf mehrere Blöcke", schluessel.size >= 3)
        schluessel.forEach { assertTrue(it.startsWith("daten-2026-11-15-")) }
        assertEquals("Schlüssel sind eindeutig (Zeitstempel als Schlüssel)", schluessel.toSet().size, schluessel.size)
    }

    @Test
    fun gleichesEingangLiefertGleicheSchluessel() {
        val erste = pakete(HaUebertragungModus.GESAMTDATEN).map { it.first }
        val zweite = pakete(HaUebertragungModus.GESAMTDATEN).map { it.first }
        assertEquals(erste, zweite)
    }

    @Test
    fun paketTraegtBlockUndReihen() {
        val liste = pakete(HaUebertragungModus.GESAMTDATEN)
        assertTrue(liste.isNotEmpty())
        val paket = JSONObject(liste.first().second)
        assertEquals(NachtBerichtBauer.TYPE_DATEN, paket.getString("type"))
        assertEquals("2026-11-15", paket.getString("night"))
        assertEquals("gesamtdaten", paket.getString("modus"))
        assertTrue(paket.getJSONObject("block").getString("start").contains("+"))
        // Die Reihen verteilen sich auf ihre Blöcke: Puls, Bewegung und Plattform
        // kommen je Block an, der Block trägt start und end mit Offset.
        var pulsPunkte = 0
        var bewegungFenster = 0
        var plattformWechsel = 0
        liste.forEach { (_, json) ->
            val objekt = JSONObject(json)
            objekt.optJSONObject("pulse")?.optJSONArray("samples")?.let { pulsPunkte += it.length() }
            objekt.optJSONObject("movement")?.optJSONArray("windows")?.let { bewegungFenster += it.length() }
            objekt.optJSONArray("platform")?.let { plattformWechsel += it.length() }
        }
        assertTrue("Puls-Punkte kommen an", pulsPunkte >= pulsSerie().size)
        assertEquals("Bewegungsfenster kommen an", schrittSerie().size, bewegungFenster)
        assertEquals("Plattform-Wechsel kommen an", 1, plattformWechsel)
    }

    @Test
    fun doppelteZeitstempelImEingangVerdichten() {
        val doppelt = pulsSerie() + pulsSerie().first().copy()
        val mitDoppelt = pakete(HaUebertragungModus.GESAMTDATEN, puls = doppelt)
        val ohneDoppelt = pakete(HaUebertragungModus.GESAMTDATEN)
        assertEquals(
            "gleicher Zeitstempel zählt einmal",
            ohneDoppelt.map { it.second }.sorted(),
            mitDoppelt.map { it.second }.sorted()
        )
    }

    @Test
    fun leereBloeckeKommenNichtInsNetz() {
        val lueckig = listOf(
            HeartRateSample(measuredAtEpochMillis = start + 1_000L, beatsPerMinute = 55.0),
            HeartRateSample(measuredAtEpochMillis = start + 4L * 60L * 60L * 1000L, beatsPerMinute = 56.0)
        )
        val schluessel = pakete(
            HaUebertragungModus.GESAMTDATEN,
            puls = lueckig,
            schritte = emptyList(),
            plattform = emptyList()
        ).map { it.first }
        assertEquals("nur die zwei belegten Blöcke, kein Füllmaterial", 2, schluessel.size)
    }
}
