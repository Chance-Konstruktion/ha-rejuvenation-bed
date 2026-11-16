package net.schanz.rejuvenationbed.watch.ha

import net.schanz.rejuvenationbed.watch.health.HeartRateSample
import net.schanz.rejuvenationbed.watch.health.IbiMesspunkt
import net.schanz.rejuvenationbed.watch.sleep.SleepStage
import net.schanz.rejuvenationbed.watch.sleep.SleepStageEstimate
import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import kotlin.math.ceil

/** Ein 30-Minuten-Fenster mit seinem Schätzergebnis — Grundlage der Zeitleiste. */
data class NachtFensterErgebnis(
    val startEpochMillis: Long,
    val endEpochMillis: Long,
    val stage: SleepStage,
    val confidence: Double,
    val sampleCoverage: Double,
    val algorithmVersion: String
) {
    /** Nur brauchbare Fenster bilden Segmente; unbrauchbare bleiben Lücke. */
    val brauchbar: Boolean get() = stage != SleepStage.UNKNOWN
}

/** Ein zusammenhängendes Phasen-Segment der Nacht (mehrere gleiche Fenster). */
data class NachtSegment(
    val stage: SleepStage,
    val startEpochMillis: Long,
    val endEpochMillis: Long,
    val confidence: Double,
    val sampleCoverage: Double,
    val algorithmVersion: String
)

/** Ein Plattform-Schlafstatus-Wechsel (Wear OS, grob schläft/wach). */
data class PlattformWechsel(
    val changedAtEpochMillis: Long,
    val zustandName: String
)

/**
 * Baut die Nutzlasten für den lokalen Home-Assistant-Webhook — reine Logik,
 * ohne Android-Zugriff, in JVM-Unit-Tests geprüft.
 *
 * Vertrag wie HA ihn rechnet (`rejuvenation-bed-night-report-v1`): alle
 * Zeitstempel als ISO-8601 MIT Offset (HA streift den Offset selbst ab,
 * damit Differenzen zonenunabhängig stimmen); die laufende Phase MUSS den
 * Offset tragen, sonst wird die Annahme abgelehnt. Kein Wert wird erfunden:
 * Kanäle, die die Uhr nicht liefert (Atemfrequenz, SpO2, Hauttemperatur),
 * stehen mit benanntem Grund als „nicht geliefert“ im Bericht.
 */
object NachtBerichtBauer {
    const val SCHEMA = "rejuvenation-bed-night-report-v1"
    const val TYPE_NACHT = "night_report"
    const val TYPE_PHASE = "phase_update"
    const val TYPE_DATEN = "night_data"

    /** Gesamtdaten gehen je 5 Minuten als Paket — „z. B. je 5 min“ des Auftrags. */
    const val BLOCK_MILLIS = 5L * 60L * 1000L

    /** Quelle eines Werts, damit HA „IBI echt“ und „grobe Schätzung“ trennen kann (!19). */
    fun quelleVonAlgorithmus(algorithmVersion: String): String =
        when (algorithmVersion) {
            "m2-rules-0.1" -> "estimate-ibi"
            "puls-bewegung-grob-0.1" -> "estimate"
            else -> "estimate"
        }

    private fun iso(epochMillis: Long, zone: ZoneId): String =
        DateTimeFormatter.ISO_OFFSET_DATE_TIME.format(Instant.ofEpochMilli(epochMillis).atZone(zone))

    private fun zahl(wert: Double, stellen: Int = 3): Double {
        val faktor = Math.pow(10.0, stellen.toDouble())
        return Math.round(wert * faktor) / faktor
    }

    // ── laufende Phase ─────────────────────────────────────────────────────

    /** phase_update für den Nachtbericht-Sensor — nur mit frischer, brauchbarer Schätzung. */
    fun bauePhasenUpdate(
        estimate: SleepStageEstimate,
        modus: HaUebertragungModus,
        zone: ZoneId,
        jetztEpochMillis: Long = System.currentTimeMillis()
    ): String {
        require(
            estimate.stage != SleepStage.UNKNOWN &&
                estimate.isUsable(nowEpochMillis = jetztEpochMillis)
        ) { "Die laufende Phase geht nur frisch und brauchbar an HA" }
        return JSONObject()
            .put("schema", SCHEMA)
            .put("type", TYPE_PHASE)
            .put("stage", estimate.stage.wireValue)
            .put("confidence", zahl(estimate.confidence))
            .put("coverage", zahl(estimate.sampleCoverage))
            .put("measured_at", iso(estimate.measuredAtEpochMillis, zone))
            .put("source", quelleVonAlgorithmus(estimate.algorithmVersion))
            .put("algorithm", estimate.algorithmVersion)
            .put("modus", modus.wireValue)
            .toString()
    }

    // ── Phasen-Zeitleiste ──────────────────────────────────────────────────

    /** Brauchbare Fenster zu Segmenten zusammenziehen; gleiche Stufe = ein Segment. */
    fun baueZeitleiste(fenster: List<NachtFensterErgebnis>): List<NachtSegment> {
        val geordnet = fenster.filter { it.brauchbar }.sortedBy { it.startEpochMillis }
        val segmente = mutableListOf<NachtSegment>()
        for (f in geordnet) {
            val letztes = segmente.lastOrNull()
            if (letztes != null && letztes.stage == f.stage &&
                letztes.algorithmVersion == f.algorithmVersion &&
                letztes.endEpochMillis == f.startEpochMillis
            ) {
                val dauerAlt = (letztes.endEpochMillis - letztes.startEpochMillis).toDouble()
                val dauerNeu = (f.endEpochMillis - f.startEpochMillis).toDouble()
                val gesamt = dauerAlt + dauerNeu
                val zusammen = NachtSegment(
                    stage = letztes.stage,
                    startEpochMillis = letztes.startEpochMillis,
                    endEpochMillis = f.endEpochMillis,
                    confidence = (letztes.confidence * dauerAlt + f.confidence * dauerNeu) / gesamt,
                    sampleCoverage = (letztes.sampleCoverage * dauerAlt + f.sampleCoverage * dauerNeu) / gesamt,
                    algorithmVersion = letztes.algorithmVersion
                )
                segmente[segmente.size - 1] = zusammen
            } else {
                segmente += NachtSegment(
                    stage = f.stage,
                    startEpochMillis = f.startEpochMillis,
                    endEpochMillis = f.endEpochMillis,
                    confidence = f.confidence,
                    sampleCoverage = f.sampleCoverage,
                    algorithmVersion = f.algorithmVersion
                )
            }
        }
        return segmente
    }

    // ── Nachtbericht ───────────────────────────────────────────────────────

    /** Alles, was der Bericht über die Kanäle weiß, die die Uhr NICHT liefert. */
    private fun fehlendeKanale(): JSONObject = JSONObject()
        .put(
            "respiratory_rate",
            JSONObject()
                .put("provided", false)
                .put("reason", "die Uhr stellt keinen Atemfrequenz-Kanal bereit")
        )
        .put(
            "spo2",
            JSONObject()
                .put("provided", false)
                .put("reason", "die Uhr stellt keinen SpO2-Kanal bereit")
        )
        .put(
            "skin_temperature",
            JSONObject()
                .put("provided", false)
                .put("reason", "die Uhr stellt keinen Hauttemperatur-Kanal bereit")
        )

    private fun bauePhasen(segmente: List<NachtSegment>, zone: ZoneId): JSONArray = JSONArray().apply {
        segmente.forEach { seg ->
            put(
                JSONObject()
                    .put("stage", seg.stage.wireValue)
                    .put("start", iso(seg.startEpochMillis, zone))
                    .put("end", iso(seg.endEpochMillis, zone))
                    .put("source", quelleVonAlgorithmus(seg.algorithmVersion))
                    .put("confidence", zahl(seg.confidence))
                    .put("coverage", zahl(seg.sampleCoverage))
                    .put("algorithm", seg.algorithmVersion)
            )
        }
    }

    private fun bauePulsZusammenfassung(puls: List<HeartRateSample>, start: Long, ende: Long): JSONObject? {
        if (puls.isEmpty()) return null
        val bpm = puls.map { it.beatsPerMinute }
        val blockAnzahl = ceil((ende - start).toDouble() / BLOCK_MILLIS).toInt().coerceAtLeast(1)
        val belegt = puls.map { Math.floorDiv(it.measuredAtEpochMillis, BLOCK_MILLIS) }.distinct().size
        return JSONObject()
            .put("min", zahl(bpm.min(), 1))
            .put("mean", zahl(bpm.sum() / bpm.size, 1))
            .put("max", zahl(bpm.max(), 1))
            .put("coverage", zahl(belegt.toDouble() / blockAnzahl))
            .put("quelle", "Health Services (echt)")
    }

    private fun baueSchritte(schritte: List<net.schanz.rejuvenationbed.watch.health.StepIntervalSample>, start: Long, ende: Long): JSONObject? {
        val imFenster = schritte.filter { it.endEpochMillis in (start + 1L)..ende }
        if (imFenster.isEmpty()) return null
        return JSONObject()
            .put("steps_total", imFenster.sumOf { it.steps })
            .put("quelle", "Health Services (echt)")
    }

    /**
     * Der Nachtbericht. Rohreihen gehen nicht hinein (sie laufen als
     * 5-Minuten-Pakete über die Warteschlange); in „Gesamtdaten“ meldet der
     * Bericht nur die Stellung, HA mischt die Pakete zur Nacht.
     */
    fun baueNachtbericht(
        nachtStartEpochMillis: Long,
        nachtEndeEpochMillis: Long,
        fenster: List<NachtFensterErgebnis>,
        puls: List<HeartRateSample>,
        ibi: List<IbiMesspunkt>,
        schritte: List<net.schanz.rejuvenationbed.watch.health.StepIntervalSample>,
        hrv: net.schanz.rejuvenationbed.watch.analysis.SleepHrvFeatures?,
        modus: HaUebertragungModus,
        zone: ZoneId,
        geraet: String = "galaxy-watch"
    ): String {
        require(nachtEndeEpochMillis > nachtStartEpochMillis) { "Die Nacht dauert länger" }
        val segmente = baueZeitleiste(fenster)
        val bericht = JSONObject()
            .put("schema", SCHEMA)
            .put("type", TYPE_NACHT)
            .put(
                "night",
                java.time.format.DateTimeFormatter.ISO_LOCAL_DATE.format(
                    Instant.ofEpochMilli(nachtStartEpochMillis).atZone(zone)
                )
            )
            .put("start", iso(nachtStartEpochMillis, zone))
            .put("end", iso(nachtEndeEpochMillis, zone))
            .put("device", geraet)
            .put("phases", bauePhasen(segmente, zone))
            .put("modus", modus.wireValue)
            .put("channels", fehlendeKanale())

        bauePulsZusammenfassung(puls, nachtStartEpochMillis, nachtEndeEpochMillis)?.let {
            bericht.put("pulse", it)
        }
        baueSchritte(schritte, nachtStartEpochMillis, nachtEndeEpochMillis)?.let {
            bericht.put("movement", it)
        }

        if (hrv != null && hrv.hasReliableIbi) {
            bericht.put(
                "hrv",
                JSONObject()
                    .put("rmssd", zahl(hrv.rmssdMillis!!, 1))
                    .put("sdnn", zahl(hrv.sdnnMillis!!, 1))
                    .put("mean_ibi", zahl(hrv.meanIbiMillis!!, 1))
                    .put("accepted", hrv.acceptedIbiCount)
                    .put("rejected", hrv.rejectedIbiCount)
                    .put("coverage", zahl(hrv.ibiCoverage))
                    .put("signal_quality", zahl(hrv.signalQuality))
                    .put("quelle", "auf der Uhr aus IBI berechnet")
                    .put("ibi_quelle", "echt")
            )
        } else {
            // Benannter Grund statt geratenem Wert — HRV kommt nur aus IBI (!19).
            val grund = when {
                hrv == null || hrv.rawIbiCount == 0 -> "keine IBI vorhanden"
                else -> "zu wenige brauchbare IBI (${hrv.acceptedIbiCount} von mindestens " +
                    net.schanz.rejuvenationbed.watch.analysis.SleepHrvFeatures.MINIMUM_IBI_SAMPLES + ")"
            }
            bericht.put("hrv_grund", grund)
        }
        return bericht.toString()
    }

    // ── Gesamtdaten-Pakete ─────────────────────────────────────────────────

    /**
     * Die Messreihen je 5 Minuten als Pakete. Jeder Block trägt seinen
     * Startzeitpunkt als Schlüssel; gleiche Eingabe liefert dieselben
     * Schlüssel — die Warteschlange erkennt Wiederholungen daran, und HA
     * fasst Punkte über den Zeitstempel zusammen, nie doppelt.
     */
    fun baueDatenPakete(
        nacht: String,
        nachtStartEpochMillis: Long,
        nachtEndeEpochMillis: Long,
        puls: List<HeartRateSample>,
        ibi: List<IbiMesspunkt>,
        schritte: List<net.schanz.rejuvenationbed.watch.health.StepIntervalSample>,
        plattformWechsel: List<PlattformWechsel>,
        modus: HaUebertragungModus,
        zone: ZoneId,
        blockMillis: Long = BLOCK_MILLIS
    ): List<Pair<String, String>> {
        require(blockMillis > 0) { "Der Block muss länger als nichts sein" }
        require(nachtEndeEpochMillis > nachtStartEpochMillis) { "Die Nacht dauert länger" }
        val ersteBlock = Math.floorDiv(nachtStartEpochMillis, blockMillis)
        val letzteBlock = Math.floorDiv(nachtEndeEpochMillis - 1, blockMillis)
        val pakete = mutableListOf<Pair<String, String>>()
        for (block in ersteBlock..letzteBlock) {
            val blockStart = block * blockMillis
            val blockEnde = blockStart + blockMillis
            val blockPuls = puls
                .filter { it.measuredAtEpochMillis in blockStart until blockEnde }
                .distinctBy { it.measuredAtEpochMillis }
                .sortedBy { it.measuredAtEpochMillis }
            val blockIbi = ibi
                .filter { it.measuredAtEpochMillis in blockStart until blockEnde }
                .distinctBy { it.measuredAtEpochMillis }
                .sortedBy { it.measuredAtEpochMillis }
            val blockSchritte = schritte
                .filter { it.endEpochMillis in blockStart until blockEnde }
                .distinctBy { it.startEpochMillis to it.endEpochMillis }
                .sortedBy { it.endEpochMillis }
            val blockPlattform = plattformWechsel
                .filter { it.changedAtEpochMillis in blockStart until blockEnde }
                .distinctBy { it.changedAtEpochMillis }
                .sortedBy { it.changedAtEpochMillis }
            if (blockPuls.isEmpty() && blockIbi.isEmpty() && blockSchritte.isEmpty() && blockPlattform.isEmpty()) {
                continue
            }
            val json = JSONObject()
                .put("schema", SCHEMA)
                .put("type", TYPE_DATEN)
                .put("night", nacht)
                .put("modus", modus.wireValue)
                .put(
                    "block",
                    JSONObject()
                        .put("start", iso(blockStart, zone))
                        .put("end", iso(blockEnde, zone))
                )
                .apply {
                    if (blockPuls.isNotEmpty()) {
                        put(
                            "pulse",
                            JSONObject().put(
                                "samples",
                                JSONArray().apply {
                                    blockPuls.forEach {
                                        put(
                                            JSONObject()
                                                .put("t", iso(it.measuredAtEpochMillis, zone))
                                                .put("bpm", Math.round(it.beatsPerMinute * 10.0) / 10.0)
                                        )
                                    }
                                }
                            )
                        )
                    }
                    if (blockIbi.isNotEmpty()) {
                        put(
                            "ibi",
                            JSONArray().apply {
                                blockIbi.forEach {
                                    val punkt = JSONObject()
                                        .put("t", iso(it.measuredAtEpochMillis, zone))
                                        .put("interval_ms", Math.round(it.intervalMillis * 10.0) / 10.0)
                                    if (it.signalQuality != null) punkt.put("quality", Math.round(it.signalQuality * 1000.0) / 1000.0)
                                    put(punkt)
                                }
                            }
                        )
                    }
                    if (blockSchritte.isNotEmpty()) {
                        put(
                            "movement",
                            JSONObject().put(
                                "windows",
                                JSONArray().apply {
                                    blockSchritte.forEach {
                                        put(
                                            JSONObject()
                                                .put("t", iso(it.endEpochMillis, zone))
                                                .put("steps", it.steps)
                                        )
                                    }
                                }
                            )
                        )
                    }
                    if (blockPlattform.isNotEmpty()) {
                        put(
                            "platform",
                            JSONArray().apply {
                                blockPlattform.forEach {
                                    put(
                                        JSONObject()
                                            .put("t", iso(it.changedAtEpochMillis, zone))
                                            .put("state", it.zustandName)
                                    )
                                }
                            }
                        )
                    }
                }
                .toString()
            pakete += "daten-$nacht-$blockStart" to json
        }
        return pakete
    }

    /** Schlüssel des Nachtberichts in der Warteschlange — eine Nacht, ein Bericht. */
    fun nachtSchluessel(nacht: String): String = "nacht-$nacht"

    /** Schlüssel der laufenden Phase — nur die neueste bleibt in der Warteschlange. */
    fun phasenSchluessel(zeitpunktEpochMillis: Long): String = "phase-$zeitpunktEpochMillis"
}
