package net.schanz.rejuvenationbed.watch.blatt

import android.content.Context
import android.content.SharedPreferences
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
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
import net.schanz.rejuvenationbed.watch.analysis.SleepFeatureExtractor
import net.schanz.rejuvenationbed.watch.analysis.SleepFeatureWindow
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
import net.schanz.rejuvenationbed.watch.ui.Augenbraue
import net.schanz.rejuvenationbed.watch.ui.BlattHinweis
import net.schanz.rejuvenationbed.watch.ui.Farbe
import net.schanz.rejuvenationbed.watch.ui.GestaltRegel
import net.schanz.rejuvenationbed.watch.ui.LosKnopf
import net.schanz.rejuvenationbed.watch.ui.Raum
import net.schanz.rejuvenationbed.watch.ui.Schrift
import net.schanz.rejuvenationbed.watch.ui.StatusZeile
import net.schanz.rejuvenationbed.watch.ui.Zifferblatt
import net.schanz.rejuvenationbed.watch.ui.kroneScrollt
import java.util.Locale

/** Lokaler Stand der Schlafdaten, neu gelesen bei jeder Änderung im Speicher. */
data class SchlafStand(
    val puls: List<HeartRateSample>,
    val schrittIntervalle: Int,
    val fenster: List<SleepFeatureWindow>,
    val sammelStatus: String,
    val plattform: PlatformSleepStateEvent?,
    val plattformVerlauf: List<PlatformSleepStateEvent>
) {
    val auswertbar: Int get() = fenster.count { it.hasMinimumHeartRateFeatures }
    val misst: Boolean get() = sammelStatus == "registered" || sammelStatus == "collecting"
}

@Composable
fun rememberSchlafStand(context: Context): SchlafStand {
    val einstellungen = remember(context) {
        context.getSharedPreferences("rejuvenation_bed_watch_health", Context.MODE_PRIVATE)
    }
    var stand by remember { mutableIntStateOf(0) }
    DisposableEffect(einstellungen) {
        val horcher = SharedPreferences.OnSharedPreferenceChangeListener { _, _ -> stand += 1 }
        einstellungen.registerOnSharedPreferenceChangeListener(horcher)
        onDispose { einstellungen.unregisterOnSharedPreferenceChangeListener(horcher) }
    }
    return remember(stand) {
        val puls = HeartRateSampleStore.heartRateSamples(context)
        val schritte = HeartRateSampleStore.stepIntervals(context)
        SchlafStand(
            puls = puls,
            schrittIntervalle = schritte.size,
            fenster = SleepFeatureExtractor.extract(
                heartRateSamples = puls,
                stepIntervals = schritte,
                nowEpochMillis = System.currentTimeMillis()
            ),
            sammelStatus = HeartRateSampleStore.status(context),
            plattform = HeartRateSampleStore.latestPlatformSleepState(context),
            plattformVerlauf = HeartRateSampleStore.platformSleepStates(context)
        )
    }
}

/** START-Blatt: das Zifferblatt der Schlafmessung; hoch/runter = Info-Ebene. */
@Composable
fun SchlafBlatt(aktiv: Boolean) {
    val ebenen = rememberPagerState(pageCount = { 2 })
    VerticalPager(state = ebenen, modifier = Modifier.fillMaxSize()) { ebene ->
        if (ebene == 0) SchlafGesicht() else SchlafInfo(aktiv = aktiv && ebenen.currentPage == 1)
    }
}

@Composable
private fun SchlafGesicht() {
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

    val stand = rememberSchlafStand(context)
    LaunchedEffect(stand.misst) {
        if (stand.misst) NowBar.starten(context, NowBarText.puls(stand.puls.lastOrNull()?.beatsPerMinute))
    }

    val status = GestaltRegel.schlafStatus(faehigkeit, fehlendesRecht != null, stand.sammelStatus, beschaeftigt)
    val knopf = GestaltRegel.losKnopf(faehigkeit, fehlendesRecht != null, stand.sammelStatus, beschaeftigt)
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
            BasicText(held, style = Schrift.held)
            BasicText(unter, style = Schrift.daten.copy(textAlign = TextAlign.Center))
            if (plattform != null) {
                BasicText(plattform, style = Schrift.klein.copy(textAlign = TextAlign.Center))
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
private fun SchlafInfo(aktiv: Boolean) {
    val context = LocalContext.current
    val stand = rememberSchlafStand(context)
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
        Augenbraue("FENSTER · 30 MIN")
        if (stand.fenster.isEmpty()) {
            BasicText("noch keine Daten", style = Schrift.klein.copy(color = Farbe.Grau2))
        }
        stand.fenster.takeLast(10).reversed().forEach { f ->
            val mittel = f.heartRateMeanBpm?.let { String.format(Locale.GERMANY, "Ø%.0f", it) } ?: "Ø—"
            val streu = f.heartRateStdDevBpm?.let { String.format(Locale.GERMANY, "σ%.1f", it) } ?: "σ—"
            BasicText(
                "${DebugText.uhrzeit(f.startEpochMillis)} $mittel $streu ${f.stepsInWindow}S " +
                    "${f.heartRateOccupiedBuckets}/${f.heartRateBucketCount}",
                style = Schrift.daten.copy(
                    color = if (f.hasMinimumHeartRateFeatures) Farbe.Text else Farbe.Grau2
                )
            )
        }
        Spacer(Modifier.height(Raum.s2))
        Augenbraue("WEAR OS SCHLAF")
        if (stand.plattformVerlauf.isEmpty()) {
            BasicText("kein Statuswechsel", style = Schrift.klein.copy(color = Farbe.Grau2))
        }
        stand.plattformVerlauf.takeLast(8).reversed().forEach { e ->
            BasicText("${DebugText.uhrzeit(e.changedAtEpochMillis)} ${e.state.label}", style = Schrift.daten)
        }
        Spacer(Modifier.height(Raum.s2))
        BasicText("Ø Puls · σ Streuung · S Schritte · Belegung", style = Schrift.klein.copy(color = Farbe.Grau2, textAlign = TextAlign.Center))
    }
}
