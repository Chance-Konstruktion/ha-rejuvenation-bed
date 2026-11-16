package net.schanz.rejuvenationbed.watch.ha

import android.content.Context
import net.schanz.rejuvenationbed.watch.analysis.SleepFeatureExtractor
import net.schanz.rejuvenationbed.watch.analysis.SleepHrvExtractor
import net.schanz.rejuvenationbed.watch.debug.DebugProtokoll
import net.schanz.rejuvenationbed.watch.health.HeartRateSampleStore
import net.schanz.rejuvenationbed.watch.health.IbiMesspunktSpeicher
import net.schanz.rejuvenationbed.watch.sleep.SleepEstimatorSettings
import net.schanz.rejuvenationbed.watch.sleep.SleepEstimatorWahl
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.concurrent.Executors

/**
 * Steuerung der HA-Übertragung: baut die Nutzlasten aus den lokalen Speichern,
 * hält sie in der Warteschlange und versucht die Abholung über den lokalen
 * Webhook. Messen bleibt völlig unberührt — hier wird nur GESENDET, und zwar
 * nie im Weg der Messung (alles läuft auf einem eigenen Hintergrund-Faden).
 *
 * Wege:
 * - [beimLiefern] aus dem passiven Dienst: die laufende Phase (beide Stellungen).
 * - [nachStopp] aus dem Stopp der Messung: der Nachtbericht, in „Gesamtdaten“
 *   zusätzlich die 5-Minuten-Pakete mit den Messreihen.
 * - [jetztSenden] vom Schlaf-Blatt: dasselbe wie nach Stopp, von Hand angestoßen.
 *
 * Hausregeln: Es geht nur der lokale Webhook ([HaWebhookSender]); keine Mess-
 * werte und keine Adresse in Protokoll oder Statuszeile — die Zeilen nennen
 * Nacht-Datum, Anzahlen und Gründe, sonst nichts.
 */
object HaUebertragung {
    private const val ART = "HA"

    private val arbeitsfaden = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "ha-uebertragung").apply { isDaemon = true }
    }

    /** Statuszeile für das Schlaf-Blatt — Modus, Adresse, Warteschlange, letzter Ausgang. */
    fun statusZeile(context: Context): String {
        val modus = HaUebertragungsEinstellungen.modus(context)
        val adresse = if (HaUebertragungsEinstellungen.hatAdresse(context)) "Adresse gesetzt" else "keine Adresse"
        val warte = HaUebertragungsEinstellungen.warteschlange(context)
        val antwort = HaUebertragungsEinstellungen.letzteAntwort(context)
        return buildString {
            append("${modus.anzeige} · $adresse · Warteschlange ${warte.umfasst()}")
            antwort?.let { append(" · $it") }
        }
    }

    /** Nach einer Lieferung von Health Services: die laufende Phase (falls frisch). */
    fun beimLiefern(context: Context) {
        arbeitsfaden.execute {
            runCatching { laufendePhaseStellen(context) }
                .onFailure { DebugProtokoll.ereignis(context, ART, "Laufende Phase nicht angelegt: ${it.javaClass.simpleName}") }
            abholen(context)
        }
    }

    /** Nach dem Stopp: Nachtbericht (beide Stellungen), in „Gesamtdaten“ die Pakete. */
    fun nachStopp(context: Context) {
        arbeitsfaden.execute {
            runCatching { nachtAnstellen(context) }
                .onFailure { DebugProtokoll.ereignis(context, ART, "Nachtbericht nicht angelegt: ${it.javaClass.simpleName}") }
            abholen(context)
        }
    }

    /** Von Hand aus dem Schlaf-Blatt: Nachtbericht und Pakete frisch anstellen, abholen. */
    fun jetztSenden(context: Context, onErgebnis: (String) -> Unit) {
        arbeitsfaden.execute {
            val ausgang = runCatching {
                nachtAnstellen(context)
                abholen(context)
                HaUebertragungsEinstellungen.letzteAntwort(context) ?: "keine Antwort"
            }.getOrElse { "Nicht gesendet: ${it.message ?: it.javaClass.simpleName}" }
            onErgebnis(ausgang)
        }
    }

    /**
     * Vergessen: Warteschlange und Messungs-Anker weg (Rohdaten-Kopien der
     * Pakete nicht länger auf der Uhr behalten als die Daten selbst). Wird
     * aus der Lösch-Aktion des Schlaf-Blatts gerufen — dort, wo auch die
     * Messdaten gelöscht werden.
     */
    fun vergessen(context: Context) {
        arbeitsfaden.execute {
            HaUebertragungsEinstellungen.leere(context)
            HaUebertragungsEinstellungen.loescheMessungStart(context)
            DebugProtokoll.ereignis(context, ART, "Warteschlange geleert (Nutzer hat Daten gelöscht)")
        }
    }

    // ── Anstellen ──────────────────────────────────────────────────────────

    private fun laufendePhaseStellen(context: Context) {
        if (!HaUebertragungsEinstellungen.hatAdresse(context)) return
        val modus = HaUebertragungsEinstellungen.modus(context)
        val jetzt = System.currentTimeMillis()
        // Einmal lesen, mehrfach nutzen — jede Lieferung läuft durch diesen Weg.
        val puls = HeartRateSampleStore.heartRateSamples(context)
        val schritte = HeartRateSampleStore.stepIntervals(context)
        val schaetzung = SleepEstimatorWahl.schaetzung(
            hrv = neuesteFensterHrv(context, jetzt, schritte),
            fenster = SleepFeatureExtractor.extract(
                heartRateSamples = puls,
                stepIntervals = schritte,
                nowEpochMillis = jetzt
            ).lastOrNull(),
            hatBewegungsdaten = schritte.isNotEmpty(),
            jetztEpochMillis = jetzt,
            experimentAktiv = SleepEstimatorSettings.isEnabled(context)
        )
        if (!schaetzung.isUsable(nowEpochMillis = jetzt)) return
        val json = NachtBerichtBauer.bauePhasenUpdate(
            estimate = schaetzung,
            modus = modus,
            zone = ZoneId.systemDefault(),
            jetztEpochMillis = jetzt
        )
        stelleAn(context, NachtBerichtBauer.TYPE_PHASE, "phase", json)
    }

    private fun nachtAnstellen(context: Context) {
        if (!HaUebertragungsEinstellungen.hatAdresse(context)) {
            HaUebertragungsEinstellungen.setzeLetzteAntwort(context, "keine HA-Adresse gesetzt")
            return
        }
        val modus = HaUebertragungsEinstellungen.modus(context)
        val zone = ZoneId.systemDefault()
        val start = HaUebertragungsEinstellungen.messungStart(context)
        val puls = HeartRateSampleStore.heartRateSamples(context)
        val schritte = HeartRateSampleStore.stepIntervals(context)
        val ibi = leseIbi(context)
        val plattform = HeartRateSampleStore.platformSleepStates(context)
        val juengste = maxOf(
            puls.lastOrNull()?.measuredAtEpochMillis ?: Long.MIN_VALUE,
            schritte.lastOrNull()?.endEpochMillis ?: Long.MIN_VALUE,
            ibi.lastOrNull()?.measuredAtEpochMillis ?: Long.MIN_VALUE,
            plattform.lastOrNull()?.changedAtEpochMillis ?: Long.MIN_VALUE
        )
        if (start == null && juengste == Long.MIN_VALUE) {
            HaUebertragungsEinstellungen.setzeLetzteAntwort(context, "keine Messdaten auf der Uhr")
            return
        }
        val nachtStart = start ?: juengste
        val nachtEnde = if (juengste > Long.MIN_VALUE) maxOf(juengste, nachtStart + 60_000L) else nachtStart + 60_000L
        val nacht = DateTimeFormatter.ISO_LOCAL_DATE.format(java.time.Instant.ofEpochMilli(nachtStart).atZone(zone))

        val experimentAktiv = SleepEstimatorSettings.isEnabled(context)
        val fenster = nachtFenster(context, nachtStart, nachtEnde, puls, schritte, ibi, experimentAktiv)
        val hrv = SleepHrvExtractor.extract(
            ibiSamples = ibi.filter { it.measuredAtEpochMillis in (nachtStart + 1L)..nachtEnde },
            stepIntervals = schritte,
            startEpochMillis = nachtStart,
            endEpochMillis = nachtEnde
        )
        val bericht = NachtBerichtBauer.baueNachtbericht(
            nachtStartEpochMillis = nachtStart,
            nachtEndeEpochMillis = nachtEnde,
            fenster = fenster,
            puls = puls.filter { it.measuredAtEpochMillis in (nachtStart + 1L)..nachtEnde },
            ibi = ibi.filter { it.measuredAtEpochMillis in (nachtStart + 1L)..nachtEnde },
            schritte = schritte,
            hrv = hrv,
            modus = modus,
            zone = zone
        )
        stelleAn(context, NachtBerichtBauer.TYPE_NACHT, NachtBerichtBauer.nachtSchluessel(nacht), bericht)

        if (modus == HaUebertragungModus.GESAMTDATEN) {
            val pakete = NachtBerichtBauer.baueDatenPakete(
                nacht = nacht,
                nachtStartEpochMillis = nachtStart,
                nachtEndeEpochMillis = nachtEnde,
                puls = puls,
                ibi = ibi,
                schritte = schritte,
                plattformWechsel = plattform.map {
                    PlattformWechsel(it.changedAtEpochMillis, it.state.name)
                },
                modus = modus,
                zone = zone
            )
            pakete.forEach { (schluessel, json) ->
                stelleAn(context, NachtBerichtBauer.TYPE_DATEN, schluessel, json)
            }
            DebugProtokoll.ereignis(context, ART, "Nacht $nacht angestellt: Bericht + ${pakete.size} Messreihen-Pakete")
        } else {
            DebugProtokoll.ereignis(context, ART, "Nacht $nacht angestellt: Bericht (nur Schlafphase)")
        }
    }

    /** Brauchbare Schätzungen je vollständigem 30-Minuten-Fenster der Nacht. */
    private fun nachtFenster(
        context: Context,
        nachtStart: Long,
        nachtEnde: Long,
        puls: List<net.schanz.rejuvenationbed.watch.health.HeartRateSample>,
        schritte: List<net.schanz.rejuvenationbed.watch.health.StepIntervalSample>,
        ibi: List<net.schanz.rejuvenationbed.watch.health.IbiMesspunkt>,
        experimentAktiv: Boolean
    ): List<NachtFensterErgebnis> {
        val dauer = nachtEnde - nachtStart
        if (dauer < SleepFeatureExtractor.DEFAULT_WINDOW_MILLIS) return emptyList()
        val alleFenster = SleepFeatureExtractor.extract(
            heartRateSamples = puls,
            stepIntervals = schritte,
            nowEpochMillis = nachtEnde,
            lookbackMillis = dauer
        ).filter { it.startEpochMillis >= nachtStart && it.endEpochMillis <= nachtEnde }
        val ergebnisse = mutableListOf<NachtFensterErgebnis>()
        for (fenster in alleFenster) {
            val ibiImFenster = ibi.filter {
                it.measuredAtEpochMillis in (fenster.startEpochMillis + 1L)..fenster.endEpochMillis
            }
            val hrv = SleepHrvExtractor.extract(
                ibiSamples = ibiImFenster,
                stepIntervals = schritte,
                startEpochMillis = fenster.startEpochMillis,
                endEpochMillis = fenster.endEpochMillis
            )
            val schaetzung = SleepEstimatorWahl.schaetzung(
                hrv = hrv,
                fenster = fenster,
                hatBewegungsdaten = schritte.isNotEmpty(),
                jetztEpochMillis = fenster.endEpochMillis,
                experimentAktiv = experimentAktiv
            )
            if (schaetzung.stage != net.schanz.rejuvenationbed.watch.sleep.SleepStage.UNKNOWN) {
                ergebnisse += NachtFensterErgebnis(
                    startEpochMillis = fenster.startEpochMillis,
                    endEpochMillis = fenster.endEpochMillis,
                    stage = schaetzung.stage,
                    confidence = schaetzung.confidence,
                    sampleCoverage = schaetzung.sampleCoverage,
                    algorithmVersion = schaetzung.algorithmVersion
                )
            }
        }
        return ergebnisse
    }

    private fun neuesteFensterHrv(
        context: Context,
        jetzt: Long,
        schritte: List<net.schanz.rejuvenationbed.watch.health.StepIntervalSample>
    ): net.schanz.rejuvenationbed.watch.analysis.SleepHrvFeatures {
        val fensterEnde = Math.floorDiv(jetzt, SleepFeatureExtractor.DEFAULT_WINDOW_MILLIS) *
            SleepFeatureExtractor.DEFAULT_WINDOW_MILLIS
        val fensterStart = fensterEnde - SleepFeatureExtractor.DEFAULT_WINDOW_MILLIS
        val ibi = leseIbi(context, fensterStart, fensterEnde)
        return SleepHrvExtractor.extract(
            ibiSamples = ibi,
            stepIntervals = schritte,
            startEpochMillis = fensterStart,
            endEpochMillis = fensterEnde
        )
    }

    private fun leseIbi(context: Context, start: Long = System.currentTimeMillis() - 12L * 60L * 60L * 1000L, ende: Long = System.currentTimeMillis()): List<net.schanz.rejuvenationbed.watch.health.IbiMesspunkt> {
        val speicher = IbiMesspunktSpeicher(context)
        return try {
            speicher.lesen(start, ende)
        } finally {
            speicher.close()
        }
    }

    // ── Abholen ────────────────────────────────────────────────────────────

    private fun stelleAn(context: Context, art: String, schluessel: String, json: String) {
        val warte = HaUebertragungsEinstellungen.warteschlange(context)
        warte.anstellen(art, schluessel, json, System.currentTimeMillis())
        HaUebertragungsEinstellungen.sichereWarteschlange(context, warte)
    }

    /** Sendungen abarbeiten; beim ersten Fehlschlag abbrechen — die Wiederholung kommt beim nächsten Anstoß. */
    private fun abholen(context: Context) {
        if (!HaUebertragungsEinstellungen.hatAdresse(context)) return
        val adresse = HaUebertragungsEinstellungen.adresse(context) ?: return
        val warte = HaUebertragungsEinstellungen.warteschlange(context)
        var gesendet = 0
        while (true) {
            val eintrag = warte.naechster() ?: break
            val ergebnis = HaWebhookSender.senden(adresse, eintrag.json)
            if (ergebnis.erfolgreich) {
                warte.alsErledigt(eintrag.schluessel)
                gesendet += 1
            } else {
                warte.alsFehlgeschlagen(eintrag.schluessel, System.currentTimeMillis())
                DebugProtokoll.ereignis(
                    context, ART,
                    "Sendung fehlgeschlagen (${eintrag.art}): ${ergebnis.grund} — ${warte.umfasst()} Sendungen warten"
                )
                HaUebertragungsEinstellungen.setzeLetzteAntwort(context, "Sendung nicht angenommen: ${ergebnis.grund}")
                break
            }
        }
        if (gesendet > 0) {
            val rest = warte.umfasst()
            val text = if (rest == 0) {
                "Sendung an HA angenommen (${if (gesendet == 1) "1 Sendung" else "$gesendet Sendungen"}) — Warteschlange leer"
            } else {
                "Sendung an HA angenommen ($gesendet) — $rest warten"
            }
            HaUebertragungsEinstellungen.setzeLetzteAntwort(context, text)
            DebugProtokoll.ereignis(context, ART, text)
            HaUebertragungsEinstellungen.sichereWarteschlange(context, warte)
        }
    }
}
