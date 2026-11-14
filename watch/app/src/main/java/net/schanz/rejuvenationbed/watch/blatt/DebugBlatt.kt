package net.schanz.rejuvenationbed.watch.blatt

import android.os.Build
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
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
import androidx.health.services.client.data.DataType
import kotlinx.coroutines.delay
import net.schanz.rejuvenationbed.watch.debug.DebugProtokoll
import net.schanz.rejuvenationbed.watch.debug.DebugText
import net.schanz.rejuvenationbed.watch.debug.KanalBericht
import net.schanz.rejuvenationbed.watch.debug.LivePuls
import net.schanz.rejuvenationbed.watch.debug.LiveStand
import net.schanz.rejuvenationbed.watch.debug.SensorDiagnose
import net.schanz.rejuvenationbed.watch.health.HeartRateSampleStore
import net.schanz.rejuvenationbed.watch.nowbar.NowBarDienst
import net.schanz.rejuvenationbed.watch.ui.Augenbraue
import net.schanz.rejuvenationbed.watch.ui.BlattHinweis
import net.schanz.rejuvenationbed.watch.ui.DatenZeile
import net.schanz.rejuvenationbed.watch.ui.Farbe
import net.schanz.rejuvenationbed.watch.ui.GestaltRegel
import net.schanz.rejuvenationbed.watch.ui.Karte
import net.schanz.rejuvenationbed.watch.ui.Raum
import net.schanz.rejuvenationbed.watch.ui.Schrift
import net.schanz.rejuvenationbed.watch.ui.StatusZeile
import net.schanz.rejuvenationbed.watch.ui.UmrissKnopf
import net.schanz.rejuvenationbed.watch.ui.kroneScrollt
import java.util.Locale

/**
 * DEBUG-Blatt (WERKZEUG): die ganze Sensor-Kette auf einen Blick –
 * Kanäle, Rechte, Registrierung, letzte Lieferungen, Plattform-Schlafstatus,
 * Live-Pulstest und das Protokoll. Aktualisiert sich alle 2 s, solange es
 * sichtbar ist; die Krone scrollt.
 */
@Composable
fun DebugBlatt(aktiv: Boolean) {
    val context = LocalContext.current
    val rollen = rememberScrollState()
    var takt by remember { mutableIntStateOf(0) }
    var kanaele by remember { mutableStateOf<KanalBericht?>(null) }
    var live by remember { mutableStateOf(LiveStand()) }
    val livePuls = remember { LivePuls(context) { live = it } }

    LaunchedEffect(aktiv) {
        if (!aktiv) return@LaunchedEffect
        if (kanaele == null) SensorDiagnose.kanaele(context) { kanaele = it }
        while (true) {
            takt += 1
            delay(2_000L)
        }
    }
    DisposableEffect(aktiv) {
        onDispose { livePuls.stoppen() }
    }
    LaunchedEffect(aktiv) {
        if (!aktiv) livePuls.stoppen()
    }

    // Bei jedem Takt neu gelesen (billig: SharedPreferences + kleine Datei).
    val jetzt = remember(takt) { System.currentTimeMillis() }
    val puls = remember(takt) { HeartRateSampleStore.heartRateSamples(context) }
    val register = remember(takt) { HeartRateSampleStore.diagnose(context) }
    val plattform = remember(takt) { HeartRateSampleStore.platformSleepStates(context).lastOrNull() }
    val rechte = remember(takt) { SensorDiagnose.rechte(context) }
    val protokoll = remember(takt) { DebugProtokoll.letzte(context, 14) }
    val letzteLieferung = remember(takt) { DebugProtokoll.zuletzt(context, "DATEN") }
    val lieferungen = remember(takt) { DebugProtokoll.anzahl(context, "DATEN") }

    val status = when {
        register.firstOrNull { it.first == "status" }?.second == "collecting" ->
            GestaltRegel.Status("misst", GestaltRegel.StatusArt.LAEUFT)
        register.firstOrNull { it.first == "status" }?.second == "registered" ->
            GestaltRegel.Status("wartet auf Daten", GestaltRegel.StatusArt.LAEUFT)
        rechte.any { !it.second } -> GestaltRegel.Status("recht fehlt", GestaltRegel.StatusArt.STILL)
        else -> GestaltRegel.Status("bereit", GestaltRegel.StatusArt.BEREIT)
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .kroneScrollt(rollen, aktiv)
            .verticalScroll(rollen)
            .padding(horizontal = Raum.s4, vertical = Raum.s6),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(Raum.s2)
    ) {
        Augenbraue("~/uhr \$ debug")
        StatusZeile(status)

        Karte {
            Augenbraue("KANÄLE")
            val k = kanaele
            if (k == null) {
                BasicText("prüft …", style = Schrift.klein)
            } else {
                janein("Puls passiv", DataType.HEART_RATE_BPM.name in k.passiv)
                janein("Schritte", DataType.STEPS.name in k.passiv)
                janein("Schlafstatus", k.aktivitaetsZustaende.any { "ASLEEP" in it.uppercase(Locale.ROOT) })
                janein("Puls live", DataType.HEART_RATE_BPM.name in k.live)
                if (k.fehler != null) DatenZeile("fehler", k.fehler, Farbe.status(GestaltRegel.StatusArt.FEHLER))
            }
        }

        Karte {
            Augenbraue("RECHTE")
            rechte.forEach { (name, ok) -> janein(name.lowercase(Locale.ROOT).replace('_', ' '), ok) }
        }

        Karte {
            Augenbraue("MESSUNG")
            register.forEach { (k, v) -> DatenZeile(k, v) }
            DatenZeile("now bar", if (NowBarDienst.laeuft) "an" else "aus")
            DatenZeile("pulswerte", "${puls.size}")
            DatenZeile(
                "jüngster",
                puls.lastOrNull()?.let { "${it.beatsPerMinute.toInt()} bpm · ${DebugText.alter(jetzt - it.measuredAtEpochMillis)}" } ?: "—"
            )
            DatenZeile("lieferungen", "$lieferungen")
            DatenZeile("letzte", letzteLieferung?.let { "vor ${DebugText.alter(jetzt - it)}" } ?: "—")
            DatenZeile(
                "plattform",
                plattform?.let { "${it.state.label} · ${DebugText.uhrzeit(it.changedAtEpochMillis)}" } ?: "—"
            )
        }

        Karte {
            Augenbraue("LIVE-PULS")
            DatenZeile("lauf", if (live.laeuft) "läuft" else "aus")
            DatenZeile("verfügbar", live.verfuegbarkeit.take(28))
            DatenZeile("wert", live.bpm?.let { "${it.toInt()} bpm" } ?: "—")
            DatenZeile("werte", "${live.werte}")
            DatenZeile("erster nach", live.ersterWertNachMs?.let { DebugText.alter(it) } ?: "—")
            if (live.fehler != null) DatenZeile("fehler", live.fehler!!, Farbe.status(GestaltRegel.StatusArt.FEHLER))
            UmrissKnopf(if (live.laeuft) "LIVE STOPP" else "LIVE START", hervor = live.laeuft) {
                if (live.laeuft) livePuls.stoppen() else livePuls.starten()
            }
        }

        Augenbraue("PROTOKOLL")
        if (protokoll.isEmpty()) {
            BasicText("leer", style = Schrift.klein.copy(color = Farbe.Grau2))
        }
        protokoll.reversed().forEach { zeile ->
            BasicText(zeile, style = Schrift.daten.copy(color = Farbe.Grau))
        }
        Row(horizontalArrangement = Arrangement.spacedBy(Raum.s2)) {
            UmrissKnopf("SENSOREN") {
                SensorDiagnose.sensorenProtokollieren(context)
                takt += 1
            }
            UmrissKnopf("LEEREN") {
                DebugProtokoll.loeschen(context)
                takt += 1
            }
        }
        BasicText(
            "${Build.MODEL} · API ${Build.VERSION.SDK_INT}\nadb shell run-as net.schanz.rejuvenationbed.watch cat files/debug/protokoll.txt",
            style = Schrift.klein.copy(color = Farbe.Grau2, textAlign = TextAlign.Center)
        )
        Spacer(Modifier.height(Raum.s2))
        BlattHinweis("SCHLAF", null)
    }
}

@Composable
private fun janein(schluessel: String, ja: Boolean) {
    DatenZeile(
        schluessel,
        if (ja) "ja" else "nein",
        Farbe.status(if (ja) GestaltRegel.StatusArt.BEREIT else GestaltRegel.StatusArt.FEHLER)
    )
}
