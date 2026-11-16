package net.schanz.rejuvenationbed.watch.blatt

import android.content.Context
import android.content.SharedPreferences
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.pager.VerticalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.BasicText
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import kotlinx.coroutines.withContext
import kotlinx.coroutines.Dispatchers
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import net.schanz.chance.gestalt.Augenbraue
import net.schanz.chance.gestalt.BlattHinweis
import net.schanz.chance.gestalt.GestaltRegel
import net.schanz.chance.gestalt.LocalChanceThema
import net.schanz.chance.gestalt.LosKnopf
import net.schanz.chance.gestalt.Raum
import net.schanz.chance.gestalt.StatusZeile
import net.schanz.chance.gestalt.UmrissKnopf
import net.schanz.chance.gestalt.Zifferblatt
import net.schanz.chance.gestalt.kroneScrollt
import net.schanz.rejuvenationbed.watch.analysis.SleepFeatureExtractor
import net.schanz.rejuvenationbed.watch.analysis.SleepFeatureWindow
import net.schanz.rejuvenationbed.watch.analysis.SleepHrvExtractor
import net.schanz.rejuvenationbed.watch.analysis.SleepPredictionPayloadBuilder
import net.schanz.rejuvenationbed.watch.health.IbiMesspunktSpeicher
import net.schanz.rejuvenationbed.watch.health.IbiQuelleStatus
import net.schanz.rejuvenationbed.watch.health.SamsungHealthSensorSdkIbiQuelle
import net.schanz.rejuvenationbed.watch.health.WearSleepPredictionSender
import net.schanz.rejuvenationbed.watch.sleep.PulsBewegungsEstimator
import net.schanz.rejuvenationbed.watch.sleep.SleepEstimatorSettings
import net.schanz.rejuvenationbed.watch.sleep.SleepEstimatorWahl
import net.schanz.rejuvenationbed.watch.sleep.SleepStageEstimator
import net.schanz.rejuvenationbed.watch.debug.DebugProtokoll
import net.schanz.rejuvenationbed.watch.debug.DebugText
import net.schanz.rejuvenationbed.watch.health.HealthServicesCapabilityProbe
import net.schanz.rejuvenationbed.watch.health.HeartRateCapability
import net.schanz.rejuvenationbed.watch.health.HeartRateSample
import net.schanz.rejuvenationbed.watch.health.HeartRateSampleStore
import net.schanz.rejuvenationbed.watch.health.PassiveHeartRateRegistration
import net.schanz.rejuvenationbed.watch.health.PlatformSleepStateEvent
import net.schanz.rejuvenationbed.watch.health.WearHealthPermissions
import net.schanz.rejuvenationbed.watch.ha.HaUebertragung
import net.schanz.rejuvenationbed.watch.ha.HaUebertragungModus
import net.schanz.rejuvenationbed.watch.ha.HaUebertragungsEinstellungen
import net.schanz.rejuvenationbed.watch.nowbar.NowBar
import net.schanz.rejuvenationbed.watch.nowbar.NowBarText
import net.schanz.rejuvenationbed.watch.ui.UhrRegel
import androidx.compose.foundation.text.BasicTextField
import java.util.Locale

/** Lokaler Stand der Schlafdaten, neu gelesen bei jeder Änderung im Speicher. */
data class SchlafStand(
    val puls: List<HeartRateSample>,
    val schrittIntervalle: Int,
    val fenster: List<SleepFeatureWindow>,
    val sammelStatus: String,
    val plattform: PlatformSleepStateEvent?,
    val plattformVerlauf: List<PlatformSleepStateEvent>,
    val hrv: net.schanz.rejuvenationbed.watch.analysis.SleepHrvFeatures,
    val schaetzung: net.schanz.rejuvenationbed.watch.sleep.SleepStageEstimate,
    val ibiQuelleStatus: String
) {
    val auswertbar: Int get() = fenster.count { it.hasMinimumHeartRateFeatures }
    val misst: Boolean get() = sammelStatus == "registered" || sammelStatus == "collecting"
}

@Composable
fun rememberSchlafStand(context: Context, experimentAktiv: Boolean): SchlafStand {
    val einstellungen = remember(context) {
        context.getSharedPreferences("rejuvenation_bed_watch_health", Context.MODE_PRIVATE)
    }
    var stand by remember { mutableIntStateOf(0) }
    DisposableEffect(einstellungen) {
        val horcher = SharedPreferences.OnSharedPreferenceChangeListener { _, _ -> stand += 1 }
        einstellungen.registerOnSharedPreferenceChangeListener(horcher)
        onDispose { einstellungen.unregisterOnSharedPreferenceChangeListener(horcher) }
    }
    // Ziel A (#8): die Nacht-Auswertung liest aus der SQLite-Tabelle (36 h bei
    // 1 Hz ≈ 130.000 Werte) — ALLES Laden läuft im Hintergrund, auch das erste.
    // Das Gesicht startet mit einem leeren Stand und füllt sich im Bruchteil
    // einer Sekunde; der Haupt-Thread hängt nie (Fund w15-ub an !16 wird damit
    // zur Regel statt zur Ausnahme). Jede Speicher-Änderung (Puls-Takt, Schritte,
    // Status) stößt neu an.
    val erster = remember(experimentAktiv) { leererSchlafStand(context) }
    val ergebnis by produceState(erster, stand, experimentAktiv) {
        value = withContext(Dispatchers.Default) { berechneSchlafStand(context, experimentAktiv) }
        if (value.misst) {
            // Now Bar nach dem Nachladen mit dem echten Pulswert frischen (der
            // leere Startstand hat noch keinen); no-op, wenn sie nicht läuft.
            NowBar.aktualisieren(context, NowBarText.puls(value.puls.lastOrNull()?.beatsPerMinute))
        }
    }
    return ergebnis
}

/** Anfangsstand ohne schwere Lesezugriffe: billige Status-Werte, leere Reihen. */
private fun leererSchlafStand(context: Context): SchlafStand {
    val hrv = net.schanz.rejuvenationbed.watch.analysis.SleepHrvFeatures(
        startEpochMillis = 0L,
        endEpochMillis = 0L,
        rawIbiCount = 0,
        acceptedIbiCount = 0,
        rejectedIbiCount = 0,
        meanIbiMillis = null,
        rmssdMillis = null,
        sdnnMillis = null,
        ibiCoverage = 0.0,
        signalQuality = 0.0,
        movementBucketCount = 0,
        movementCoverage = 0.0,
        movementVarianceStepsPerMinuteSquared = null
    )
    return SchlafStand(
        puls = emptyList(),
        schrittIntervalle = 0,
        fenster = emptyList(),
        sammelStatus = HeartRateSampleStore.status(context),
        plattform = HeartRateSampleStore.latestPlatformSleepState(context),
        plattformVerlauf = emptyList(),
        hrv = hrv,
        schaetzung = SleepStageEstimator.estimate(hrv, 0L, enabled = false),
        ibiQuelleStatus = SamsungHealthSensorSdkIbiQuelle().status().let { status ->
            when (status) {
                IbiQuelleStatus.Verfuegbar -> "verfügbar"
                is IbiQuelleStatus.NichtVerfuegbar -> status.grund
            }
        }
    )
}

private fun berechneSchlafStand(context: Context, experimentAktiv: Boolean): SchlafStand {
        val puls = HeartRateSampleStore.heartRateSamples(context)
        val schritte = HeartRateSampleStore.stepIntervals(context)
        val jetzt = System.currentTimeMillis()
        val fenster = SleepFeatureExtractor.extract(
            heartRateSamples = puls,
            stepIntervals = schritte,
            nowEpochMillis = jetzt
        )
        // HRV is evaluated over the latest complete 30-minute interval, independent
        // of whether the separate Health Services BPM stream happened to deliver data.
        val fensterEnde = Math.floorDiv(jetzt, SleepFeatureExtractor.DEFAULT_WINDOW_MILLIS) *
            SleepFeatureExtractor.DEFAULT_WINDOW_MILLIS
        val fensterStart = fensterEnde - SleepFeatureExtractor.DEFAULT_WINDOW_MILLIS
        val ibiSpeicher = IbiMesspunktSpeicher(context)
        val ibi = try {
            ibiSpeicher.lesen(fensterStart, fensterEnde)
        } finally {
            ibiSpeicher.close()
        }
        val hrv = SleepHrvExtractor.extract(
            ibiSamples = ibi,
            stepIntervals = schritte,
            startEpochMillis = fensterStart,
            endEpochMillis = fensterEnde
        )
        // Schätzer-Kette (Fund 39678 an !19): als JVM-geprüfte Funktion
        // SleepEstimatorWahl — mit verlässlicher IBI der M2-Schätzer, ohne IBI
        // die grobe Puls+Bewegungs-Schätzung; der Schalter geht an jeden Zweig.
        val schaetzung = SleepEstimatorWahl.schaetzung(
            hrv = hrv,
            fenster = fenster.lastOrNull(),
            hatBewegungsdaten = schritte.isNotEmpty(),
            jetztEpochMillis = jetzt,
            experimentAktiv = experimentAktiv
        )
        val ibiStatus = when (val status = SamsungHealthSensorSdkIbiQuelle().status()) {
            IbiQuelleStatus.Verfuegbar -> "verfügbar"
            is IbiQuelleStatus.NichtVerfuegbar -> status.grund
        }
        return SchlafStand(
            puls = puls,
            schrittIntervalle = schritte.size,
            fenster = fenster,
            sammelStatus = HeartRateSampleStore.status(context),
            plattform = HeartRateSampleStore.latestPlatformSleepState(context),
            plattformVerlauf = HeartRateSampleStore.platformSleepStates(context),
            hrv = hrv,
            schaetzung = schaetzung,
            ibiQuelleStatus = ibiStatus
        )
}

/** START-Blatt: das Zifferblatt der Schlafmessung; hoch/runter = Info-Ebene. */
@Composable
fun SchlafBlatt(aktiv: Boolean) {
    val context = LocalContext.current
    var experimentAktiv by remember(context) {
        mutableStateOf(SleepEstimatorSettings.isEnabled(context))
    }
    var abgleichStatus by remember { mutableStateOf("Noch kein Abgleich gesendet.") }
    val ebenen = rememberPagerState(pageCount = { 2 })
    VerticalPager(state = ebenen, modifier = Modifier.fillMaxSize()) { ebene ->
        if (ebene == 0) SchlafGesicht(experimentAktiv)
        else SchlafInfo(
            aktiv = aktiv && ebenen.currentPage == 1,
            experimentAktiv = experimentAktiv,
            abgleichStatus = abgleichStatus,
            onExperimentAendern = { neu ->
                experimentAktiv = neu
                SleepEstimatorSettings.setEnabled(context, neu)
            },
            onAbgleichSenden = {
                if (!experimentAktiv) {
                    abgleichStatus = "Zuerst das Experiment einschalten."
                } else {
                    val payload = runCatching {
                        SleepPredictionPayloadBuilder.build(context, enabled = true)
                    }
                    payload.onSuccess { json ->
                        abgleichStatus = "Sende abgeleitete Schätzungen …"
                        WearSleepPredictionSender.senden(context, json) { result ->
                            abgleichStatus = result.fold(
                                { "An das gekoppelte Smartphone gesendet." },
                                { "Nicht gesendet: ${it.message ?: it.javaClass.simpleName}" }
                            )
                        }
                    }.onFailure { error ->
                        abgleichStatus = "Nicht bereit: ${error.message ?: error.javaClass.simpleName}"
                    }
                }
            }
        )
    }
}

@Composable
private fun SchlafGesicht(experimentAktiv: Boolean) {
    val thema = LocalChanceThema.current
    val context = LocalContext.current
    var faehigkeit by remember { mutableStateOf<HeartRateCapability>(HeartRateCapability.Checking) }
    var schritteKanal by remember { mutableStateOf(false) }
    var schlafKanal by remember { mutableStateOf(false) }
    var rechteStand by remember { mutableIntStateOf(0) }
    var beschaeftigt by remember { mutableStateOf(false) }

    LaunchedEffect(context) {
        HealthServicesCapabilityProbe.check(context.applicationContext) { ergebnis, schritte, schlaf ->
            faehigkeit = ergebnis
            schritteKanal = schritte
            schlafKanal = schlaf
            DebugProtokoll.ereignis(
                context, "FAEHIG",
                "puls=${ergebnis.javaClass.simpleName} schritte=$schritte schlafstatus=$schlaf"
            )
        }
    }

    val fehlendesRecht = remember(rechteStand, schritteKanal, schlafKanal) {
        WearHealthPermissions.firstMissingPermission(context, needsActivityRecognition = schritteKanal || schlafKanal)
    }
    val rechteFrage = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { erteilt ->
        DebugProtokoll.ereignis(
            context, "RECHT",
            "${fehlendesRecht?.substringAfterLast('.') ?: "?"} ${if (erteilt) "erteilt" else "abgelehnt"}"
        )
        rechteStand += 1
    }

    val stand = rememberSchlafStand(context, experimentAktiv)
    val grob = stand.schaetzung.algorithmVersion == PulsBewegungsEstimator.ALGORITHM_VERSION
    val phasenText = if (stand.schaetzung.isUsable(nowEpochMillis = System.currentTimeMillis())) {
        val phase = when (stand.schaetzung.stage) {
            net.schanz.rejuvenationbed.watch.sleep.SleepStage.AWAKE -> "wach"
            net.schanz.rejuvenationbed.watch.sleep.SleepStage.LIGHT -> "leicht"
            net.schanz.rejuvenationbed.watch.sleep.SleepStage.DEEP -> "tief"
            net.schanz.rejuvenationbed.watch.sleep.SleepStage.REM -> "REM"
            net.schanz.rejuvenationbed.watch.sleep.SleepStage.UNKNOWN -> "unbekannt"
        }
        val kennzeichnung = if (grob) " · grobe Schätzung" else ""
        "Phase: $phase · ${(stand.schaetzung.confidence * 100).toInt()} %$kennzeichnung"
    } else {
        // Ziel C (#8): „unbekannt“ allein hilft niemandem — das Gesicht nennt
        // den Grund (Schalter AUS / keine IBI / zu wenige IBI / …).
        "Phase: unbekannt · ${stand.schaetzung.grund}"
    }
    LaunchedEffect(stand.misst) {
        if (stand.misst) NowBar.starten(context, NowBarText.puls(stand.puls.lastOrNull()?.beatsPerMinute))
    }

    val status = UhrRegel.schlafStatus(faehigkeit, fehlendesRecht != null, stand.sammelStatus, beschaeftigt)
    val knopf = UhrRegel.losKnopf(faehigkeit, fehlendesRecht != null, stand.sammelStatus, beschaeftigt)
    val juengster = stand.puls.lastOrNull()
    val held = juengster?.let { "${it.beatsPerMinute.toInt()} bpm" } ?: "— bpm"
    val unter = buildString {
        append("${stand.auswertbar}/${stand.fenster.size} Fenster")
        if (juengster != null) append(" · ${DebugText.uhrzeit(juengster.measuredAtEpochMillis)}")
    }
    val plattform = when {
        !schlafKanal -> null
        stand.plattform == null -> "Wear OS: —"
        else -> "Wear OS: ${stand.plattform.state.label}"
    }

    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Zifferblatt(
            anteil = GestaltRegel.ringAnteil(stand.auswertbar, stand.fenster.size),
            modifier = Modifier.fillMaxSize()
        )
        Column(
            modifier = Modifier.padding(horizontal = Raum.s5),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            StatusZeile(status)
            Spacer(Modifier.height(Raum.s1))
            BasicText(held, style = thema.held)
            BasicText(unter, style = thema.daten.copy(textAlign = TextAlign.Center))
            BasicText(phasenText, style = thema.daten.copy(textAlign = TextAlign.Center))
            if (plattform != null) {
                BasicText(plattform, style = thema.klein.copy(textAlign = TextAlign.Center))
            }
            Spacer(Modifier.height(Raum.s2))
            LosKnopf(knopf, aktiv = faehigkeit == HeartRateCapability.Supported && !beschaeftigt) {
                when {
                    stand.misst -> {
                        beschaeftigt = true
                        PassiveHeartRateRegistration.stop(context) {
                            beschaeftigt = false
                            NowBar.stoppen(context)
                            rechteStand += 1
                        }
                    }
                    fehlendesRecht != null -> rechteFrage.launch(fehlendesRecht)
                    else -> {
                        beschaeftigt = true
                        PassiveHeartRateRegistration.start(
                            context,
                            includeSteps = schritteKanal,
                            includeUserActivityInfo = schlafKanal
                        ) { ergebnis ->
                            beschaeftigt = false
                            if (ergebnis.isSuccess) NowBar.starten(context)
                            rechteStand += 1
                        }
                    }
                }
            }
            Spacer(Modifier.height(Raum.s1))
            BlattHinweis("THERMO", "DEBUG")
        }
    }
}

/** INFO-Ebene: die 30-Minuten-Fenster und der Plattform-Verlauf. */
@Composable
private fun SchlafInfo(
    aktiv: Boolean,
    experimentAktiv: Boolean,
    abgleichStatus: String,
    onExperimentAendern: (Boolean) -> Unit,
    onAbgleichSenden: () -> Unit
) {
    val thema = LocalChanceThema.current
    val context = LocalContext.current
    val stand = rememberSchlafStand(context, experimentAktiv)
    val rollen = rememberScrollState()
    // Die Lösch-Aktion ist nur erreichbar, wenn nicht gemessen wird (#7). Beginnt die
    // Messung, verfällt eine offene Rückfrage – die Uhr kommt nicht mit halb offener
    // Rückfrage in die Nacht.
    var loeschRueckfrage by remember { mutableStateOf(false) }
    LaunchedEffect(stand.misst) {
        if (stand.misst) loeschRueckfrage = false
    }
    // HA-Übertragung: Statuszeile frisch lesen, wenn die Warteschlange sich bewegt.
    var haSignal by remember { mutableIntStateOf(0) }
    DisposableEffect(context) {
        val einstellungen = context.getSharedPreferences("rejuvenation_bed_watch_ha", Context.MODE_PRIVATE)
        val horcher = SharedPreferences.OnSharedPreferenceChangeListener { _, _ -> haSignal += 1 }
        einstellungen.registerOnSharedPreferenceChangeListener(horcher)
        onDispose { einstellungen.unregisterOnSharedPreferenceChangeListener(horcher) }
    }
    val haStatus = remember(haSignal) { HaUebertragung.statusZeile(context) }
    val hatAdresse = remember(haSignal) { HaUebertragungsEinstellungen.hatAdresse(context) }
    // Der Umschalt-Hinweis: einmal deutlich zeigen, was bei „Gesamtdaten“ geht —
    // beim Umschalten selbst, nicht bei jedem Besuch der Ebene.
    var gesamtdatenHinweis by remember { mutableStateOf(false) }
    var adresseFeld by remember { mutableStateOf("") }
    var haSendenStatus by remember { mutableStateOf("Noch kein Nachtbericht gesendet.") }
    Column(
        modifier = Modifier
            .fillMaxSize()
            .kroneScrollt(rollen, aktiv)
            .verticalScroll(rollen)
            .padding(horizontal = Raum.s5, vertical = Raum.s6),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(Raum.s1)
    ) {
        Augenbraue("SCHLAFPHASEN · EXPERIMENT")
        BasicText(
            if (experimentAktiv) "Regeln v0.1 eingeschaltet · nicht validiert"
            else "Regeln v0.1 ausgeschaltet · Standard",
            style = thema.klein.copy(color = thema.grau2, textAlign = TextAlign.Center)
        )
        BasicText(
            if (experimentAktiv) "EXPERIMENT AUSSCHALTEN"
            else "EXPERIMENT EINSCHALTEN",
            style = thema.daten.copy(
                color = thema.text,
                textAlign = TextAlign.Center
            ),
            modifier = Modifier
                .clickable { onExperimentAendern(!experimentAktiv) }
                .padding(vertical = Raum.s1)
        )
        BasicText(
            "Schätzung: ${stand.schaetzung.stage.wireValue} · Konfidenz " +
                "${(stand.schaetzung.confidence * 100).toInt()} % · ${stand.schaetzung.algorithmVersion}",
            style = thema.daten.copy(textAlign = TextAlign.Center)
        )
        if (stand.schaetzung.stage == net.schanz.rejuvenationbed.watch.sleep.SleepStage.UNKNOWN) {
            // Ziel C (#8): deutlich und in Worten, warum keine Phase da ist.
            BasicText(
                "keine Phasen, weil: ${stand.schaetzung.grund}",
                style = thema.daten.copy(color = thema.text, textAlign = TextAlign.Center)
            )
        }
        BasicText(
            if (experimentAktiv) "ABGLEICH AM SMARTPHONE SENDEN"
            else "Zum Senden erst das Experiment einschalten",
            style = thema.daten.copy(color = thema.text, textAlign = TextAlign.Center),
            modifier = Modifier
                .clickable(enabled = experimentAktiv) { onAbgleichSenden() }
                .padding(vertical = Raum.s1)
        )
        BasicText(abgleichStatus, style = thema.klein.copy(color = thema.grau2, textAlign = TextAlign.Center))
        BasicText("IBI-Quelle: ${stand.ibiQuelleStatus}", style = thema.klein.copy(color = thema.grau2))
        BasicText(
            "IBI ${stand.hrv.acceptedIbiCount}/${stand.hrv.rawIbiCount} · " +
                "RMSSD ${stand.hrv.rmssdMillis?.let { String.format(Locale.GERMANY, "%.1f", it) } ?: "—"} ms · " +
                "SDNN ${stand.hrv.sdnnMillis?.let { String.format(Locale.GERMANY, "%.1f", it) } ?: "—"} ms",
            style = thema.daten.copy(textAlign = TextAlign.Center)
        )
        BasicText(
            "Abdeckung ${(stand.hrv.ibiCoverage * 100).toInt()} % · Bewegung ${(stand.hrv.movementCoverage * 100).toInt()} %",
            style = thema.klein.copy(color = thema.grau2, textAlign = TextAlign.Center)
        )
        Spacer(Modifier.height(Raum.s2))
        Augenbraue("FENSTER · 30 MIN")
        if (stand.fenster.isEmpty()) {
            BasicText("noch keine Daten", style = thema.klein.copy(color = thema.grau2))
        }
        stand.fenster.takeLast(10).reversed().forEach { f ->
            val mittel = f.heartRateMeanBpm?.let { String.format(Locale.GERMANY, "Ø%.0f", it) } ?: "Ø—"
            val streu = f.heartRateStdDevBpm?.let { String.format(Locale.GERMANY, "σ%.1f", it) } ?: "σ—"
            BasicText(
                "${DebugText.uhrzeit(f.startEpochMillis)} $mittel $streu ${f.stepsInWindow}S " +
                    "${f.heartRateOccupiedBuckets}/${f.heartRateBucketCount}",
                style = thema.daten.copy(
                    color = if (f.hasMinimumHeartRateFeatures) thema.text else thema.grau2
                )
            )
        }
        Spacer(Modifier.height(Raum.s2))
        Augenbraue("WEAR OS SCHLAF")
        if (stand.plattformVerlauf.isEmpty()) {
            BasicText("kein Statuswechsel", style = thema.klein.copy(color = thema.grau2))
        }
        stand.plattformVerlauf.takeLast(8).reversed().forEach { e ->
            BasicText("${DebugText.uhrzeit(e.changedAtEpochMillis)} ${e.state.label}", style = thema.daten)
        }
        Spacer(Modifier.height(Raum.s2))
        BasicText("Ø Puls · σ Streuung · S Schritte · Belegung", style = thema.klein.copy(color = thema.grau2, textAlign = TextAlign.Center))
        // Löschen ist eine ausdrückliche, eigene Aktion (#7, Prüfnotiz w15-ub an !16):
        // nie als Nebenwirkung von Stopp. Sichtbar nur ohne laufende Messung, mit
        // Rückfrage; Bestätigen ist nicht vorgewählt (UmrissKnopf, kein Hervor, kein Fokus).
        if (!stand.misst) {
            Spacer(Modifier.height(Raum.s2))
            Augenbraue("DATEN")
            if (loeschRueckfrage) {
                BasicText(
                    "Aufgezeichnete Daten löschen?",
                    style = thema.daten.copy(textAlign = TextAlign.Center)
                )
                Row(horizontalArrangement = Arrangement.spacedBy(Raum.s2)) {
                    UmrissKnopf("ABBRECHEN") { loeschRueckfrage = false }
                    UmrissKnopf("BESTÄTIGEN") {
                        loeschRueckfrage = false
                        HeartRateSampleStore.loeschen(context)
                        // Auch die HA-Warteschlange (Rohdaten-Kopien der Pakete) weg.
                        HaUebertragung.vergessen(context)
                        DebugProtokoll.ereignis(context, "REG", "Daten gelöscht (Nutzer)")
                    }
                }
            } else {
                BasicText(
                    "DATEN LÖSCHEN",
                    style = thema.daten.copy(color = thema.text, textAlign = TextAlign.Center),
                    modifier = Modifier
                        .clickable { loeschRueckfrage = true }
                        .padding(vertical = Raum.s1)
                )
                BasicText(
                    "löscht Puls, Schritte und Schlafstatus auf der Uhr",
                    style = thema.klein.copy(color = thema.grau2, textAlign = TextAlign.Center)
                )
            }
        }

        Spacer(Modifier.height(Raum.s2))
        Augenbraue("HA-ÜBERTRAGUNG")
        val modus = remember(haSignal) { HaUebertragungsEinstellungen.modus(context) }
        BasicText(
            "Stellung: ${modus.anzeige}",
            style = thema.daten.copy(textAlign = TextAlign.Center)
        )
        BasicText(
            modus.kurzeBeschreibung,
            style = thema.klein.copy(color = thema.grau2, textAlign = TextAlign.Center)
        )
        BasicText(
            if (modus == HaUebertragungModus.PHASE_ONLY) "▸ NUR SCHLAFPHASE · Standard" else "NUR SCHLAFPHASE",
            style = thema.daten.copy(
                color = if (modus == HaUebertragungModus.PHASE_ONLY) thema.text else thema.grau2,
                textAlign = TextAlign.Center
            ),
            modifier = Modifier
                .clickable {
                    if (modus != HaUebertragungModus.PHASE_ONLY) {
                        HaUebertragungsEinstellungen.setzeModus(context, HaUebertragungModus.PHASE_ONLY)
                        gesamtdatenHinweis = false
                        DebugProtokoll.ereignis(context, "HA", "Schalter: Nur Schlafphase")
                    }
                }
                .padding(vertical = Raum.s1)
        )
        BasicText(
            if (modus == HaUebertragungModus.GESAMTDATEN) "▸ GESAMTDATEN" else "GESAMTDATEN",
            style = thema.daten.copy(
                color = if (modus == HaUebertragungModus.GESAMTDATEN) thema.text else thema.grau2,
                textAlign = TextAlign.Center
            ),
            modifier = Modifier
                .clickable {
                    if (modus != HaUebertragungModus.GESAMTDATEN) {
                        HaUebertragungsEinstellungen.setzeModus(context, HaUebertragungModus.GESAMTDATEN)
                        // Beim Umschalten einmal deutlich zeigen, was übertragen wird.
                        gesamtdatenHinweis = true
                        DebugProtokoll.ereignis(context, "HA", "Schalter: Gesamtdaten")
                    }
                }
                .padding(vertical = Raum.s1)
        )
        if (gesamtdatenHinweis) {
            BasicText(
                "Beim Senden gehen an Home Assistant:",
                style = thema.daten.copy(color = thema.text, textAlign = TextAlign.Center)
            )
            modus.uebertrageneWerte.forEach { wert ->
                BasicText("· $wert", style = thema.klein.copy(color = thema.text, textAlign = TextAlign.Center))
            }
            BasicText(
                "Nicht übertragen:",
                style = thema.daten.copy(color = thema.text, textAlign = TextAlign.Center)
            )
            modus.nichtUebermittelt.forEach { wert ->
                BasicText("· $wert", style = thema.klein.copy(color = thema.grau2, textAlign = TextAlign.Center))
            }
            BasicText(
                "Nur über den lokalen Webhook der hier gespeicherten Adresse — " +
                    "nie Cloud, nie ein fremder Dienst. Messpunkte tragen ihren Zeitstempel; " +
                    "Wiederholungen erzeugen keine Doppelungen.",
                style = thema.klein.copy(color = thema.text, textAlign = TextAlign.Center)
            )
            UmrissKnopf("VERSTANDEN") { gesamtdatenHinweis = false }
        }
        BasicText(
            if (hatAdresse) "HA-Adresse: gesetzt" else "HA-Adresse: nicht gesetzt",
            style = thema.klein.copy(color = thema.grau2)
        )
        BasicTextField(
            value = adresseFeld,
            onValueChange = { adresseFeld = it },
            textStyle = thema.daten.copy(color = thema.text, textAlign = TextAlign.Center),
            decorationBox = { innen ->
                if (adresseFeld.isEmpty()) {
                    BasicText(
                        "Adresse der Nachtbericht-Annahme",
                        style = thema.klein.copy(color = thema.grau2, textAlign = TextAlign.Center)
                    )
                }
                innen()
            }
        )
        Row(horizontalArrangement = Arrangement.spacedBy(Raum.s2)) {
            UmrissKnopf("SPEICHERN") {
                HaUebertragungsEinstellungen.setzeAdresse(context, adresseFeld)
                adresseFeld = ""
                if (HaUebertragungsEinstellungen.hatAdresse(context)) {
                    DebugProtokoll.ereignis(context, "HA", "Adresse gesetzt")
                } else {
                    DebugProtokoll.ereignis(context, "HA", "leere Adresse — nichts geändert")
                }
            }
            UmrissKnopf("LEEREN") {
                HaUebertragungsEinstellungen.setzeAdresse(context, null)
                DebugProtokoll.ereignis(context, "HA", "Adresse entfernt")
            }
        }
        BasicText(
            "Pfad der Annahme: Attribut „annahme_pfad“ am Sensor „Bett Nachtbericht“",
            style = thema.klein.copy(color = thema.grau2, textAlign = TextAlign.Center)
        )
        BasicText(
            if (hatAdresse) "NACHTBERICHT AN HA SENDEN" else "Zum Senden erst die HA-Adresse setzen",
            style = thema.daten.copy(color = thema.text, textAlign = TextAlign.Center),
            modifier = Modifier
                .clickable(enabled = hatAdresse) {
                    haSendenStatus = "Sende …"
                    HaUebertragung.jetztSenden(context) { ergebnis -> haSendenStatus = ergebnis }
                }
                .padding(vertical = Raum.s1)
        )
        BasicText(haSendenStatus, style = thema.klein.copy(color = thema.grau2, textAlign = TextAlign.Center))
        BasicText(haStatus, style = thema.klein.copy(color = thema.grau2, textAlign = TextAlign.Center))
    }
}
