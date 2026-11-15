package net.schanz.rejuvenationbed.watch.blatt

import android.content.Context
import android.content.SharedPreferences
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
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
import net.schanz.rejuvenationbed.watch.sleep.SleepEstimatorSettings
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
import net.schanz.rejuvenationbed.watch.nowbar.NowBar
import net.schanz.rejuvenationbed.watch.nowbar.NowBarText
import net.schanz.rejuvenationbed.watch.ui.UhrRegel
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
    return remember(stand, experimentAktiv) {
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
        val schaetzung = SleepStageEstimator.estimate(hrv, jetzt, enabled = experimentAktiv)
        val ibiStatus = when (val status = SamsungHealthSensorSdkIbiQuelle().status()) {
            IbiQuelleStatus.Verfuegbar -> "verfügbar"
            is IbiQuelleStatus.NichtVerfuegbar -> status.grund
        }
        SchlafStand(
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
    val phasenText = if (stand.schaetzung.isUsable(nowEpochMillis = System.currentTimeMillis())) {
        val phase = when (stand.schaetzung.stage) {
            net.schanz.rejuvenationbed.watch.sleep.SleepStage.AWAKE -> "wach"
            net.schanz.rejuvenationbed.watch.sleep.SleepStage.LIGHT -> "leicht"
            net.schanz.rejuvenationbed.watch.sleep.SleepStage.DEEP -> "tief"
            net.schanz.rejuvenationbed.watch.sleep.SleepStage.REM -> "REM"
            net.schanz.rejuvenationbed.watch.sleep.SleepStage.UNKNOWN -> "unbekannt"
        }
        "Phase: $phase · ${(stand.schaetzung.confidence * 100).toInt()} %"
    } else {
        "Phase: unbekannt"
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
                "${(stand.schaetzung.confidence * 100).toInt()} %",
            style = thema.daten.copy(textAlign = TextAlign.Center)
        )
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
    }
}
