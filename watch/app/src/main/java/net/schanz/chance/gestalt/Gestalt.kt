// KOPIE aus chance-framework 0.1.0 (3500d1a) – hier nicht ändern, im Framework ändern und neu einbauen.
package net.schanz.chance.gestalt

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.ScrollState
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.focusable
import androidx.compose.foundation.gestures.scrollBy
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.rotary.onRotaryScrollEvent
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch
import kotlin.math.cos
import kotlin.math.min
import kotlin.math.sin

/**
 * Das Thema einer Fläche: Modus (AMOLED/NACHT/HELL/BETT/SOFA) und Schale
 * (UHR/KLEIN/NORMAL). Themenwechsel ist Daten, kein Re-Design: Farben aus
 * [GestaltRegel.rollen], Gewichte und Etiketten aus [GestaltRegel.schnitt].
 */
data class ChanceThema(
    val modus: GestaltRegel.Modus = GestaltRegel.Modus.AMOLED,
    val schale: GestaltRegel.Schale = GestaltRegel.Schale.NORMAL
) {
    private val r = GestaltRegel.rollen(modus)
    val hintergrund = Color(r.hintergrund)
    val karte = Color(r.karte)
    val gedrueckt = Color(r.gedrueckt)
    val rand = Color(r.rand)
    val vertieft = Color(r.vertieft)
    val knopf = Color(r.knopf)
    val text = Color(r.text)
    val grau = Color(r.grau)
    val grau2 = Color(r.grau2)
    val akzent = Color(r.akzent)
    val textAufAkzent = Color(r.textAufAkzent)

    fun status(art: GestaltRegel.StatusArt) = Color(GestaltRegel.statusFarbe(art, modus))

    private val t = GestaltRegel.typo(schale)
    /** Der Schnitt des Modus (Gewichte, Etiketten, Vollflächen). */
    val schnitt = GestaltRegel.schnitt(modus)
    private val sans = FontFamily.Default
    private val mono = FontFamily.Monospace
    private val etikett = if (schnitt.etikettMono) mono else sans
    private val zahlGewicht = FontWeight(schnitt.zahl)

    /** Hinweise, Etiketten, Status-Wort: klein, grau (Mono, in BETT/SOFA gesperrte Sans). */
    val klein = TextStyle(
        fontFamily = etikett, fontSize = t.klein.sp, color = grau,
        letterSpacing = if (schnitt.etikettMono) 0.em else (schnitt.sperrung / 2).em
    )
    /** Fließtext. */
    val fliess = TextStyle(fontFamily = sans, fontSize = t.text.sp, color = text)
    /** Karten-/Abschnittstitel (auf der Uhr = Fließtext). */
    val titel = TextStyle(fontFamily = sans, fontSize = (t.titel ?: t.text).sp, fontWeight = FontWeight(schnitt.titel), color = text)
    /** Zahl, Name, Bühne. */
    val held = TextStyle(fontFamily = sans, fontSize = t.held.sp, fontWeight = zahlGewicht, color = text)
    /** Bühnenzahl im Ring (nur UHR; sonst held). */
    val buehne = TextStyle(fontFamily = sans, fontSize = (t.buehne ?: t.held).sp, fontWeight = zahlGewicht, color = text)
    /** Messwerte: Ziffern gleich breit (Mono oder Sans mit Tabellenziffern). */
    val daten = TextStyle(fontFamily = etikett, fontSize = t.klein.sp, color = text, fontFeatureSettings = "tnum")
    /** Augenbraue: gesperrt, Bernstein (Mono fett; in BETT/SOFA Sans mittel). */
    val augenbraue = TextStyle(
        fontFamily = etikett, fontSize = t.klein.sp,
        fontWeight = if (schnitt.etikettMono) FontWeight.Bold else FontWeight.Medium,
        letterSpacing = schnitt.sperrung.em, color = akzent
    )

    companion object {
        val UHR = ChanceThema(GestaltRegel.Modus.AMOLED, GestaltRegel.Schale.UHR)
        /** Die Uhr im Dunkeln. */
        val UHR_BETT = ChanceThema(GestaltRegel.Modus.BETT, GestaltRegel.Schale.UHR)
        /** Die Uhr am Tag, mit Kraft. */
        val UHR_SOFA = ChanceThema(GestaltRegel.Modus.SOFA, GestaltRegel.Schale.UHR)

        /** Das passende Uhr-Thema zur Stunde (Nachtfenster) und zum Schlafzustand. */
        fun uhrZurStunde(stunde: Int, schlaeft: Boolean = false) =
            ChanceThema(GestaltRegel.tagesModus(stunde, schlaeft), GestaltRegel.Schale.UHR)
    }
}

val LocalChanceThema = staticCompositionLocalOf { ChanceThema() }

/** Setzt das Thema für alles darunter. */
@Composable
fun ChanceGestalt(thema: ChanceThema = ChanceThema(), inhalt: @Composable () -> Unit) {
    CompositionLocalProvider(LocalChanceThema provides thema, content = inhalt)
}

/** Raum-Leiter als dp (4er-Takt). */
object Raum {
    val s1 = GestaltRegel.raum(1).dp
    val s2 = GestaltRegel.raum(2).dp
    val s3 = GestaltRegel.raum(3).dp
    val s4 = GestaltRegel.raum(4).dp
    val s5 = GestaltRegel.raum(5).dp
    val s6 = GestaltRegel.raum(6).dp
}

/** Die vier Ecken. */
object Ecke {
    val s = RoundedCornerShape(GestaltRegel.ECKE_S.dp)
    val m = RoundedCornerShape(GestaltRegel.ECKE_M.dp)
    val l = RoundedCornerShape(GestaltRegel.ECKE_L.dp)
    val pille = RoundedCornerShape(percent = 50)
}

/**
 * DAS ZIFFERBLATT: Spur in Rand-Farbe, Bernstein-Füllung, sechzig
 * Minuten-Striche in grau2 (jeder fünfte lang). Inhalt liegt darüber.
 * Mit [bogen] < 360 wird daraus ein Regler-Ring (z. B. 270°, Lücke unten).
 */
@Composable
fun Zifferblatt(
    anteil: Float,
    modifier: Modifier = Modifier,
    startWinkel: Float = -90f,
    bogen: Float = 360f,
    ringDicke: Dp = 6.dp,
    griff: Boolean = false
) {
    val thema = LocalChanceThema.current
    Canvas(modifier = modifier) {
        val ring = ringDicke.toPx()
        val r = min(size.width, size.height) / 2f - ring / 2f - 2.dp.toPx()
        if (r <= ring) return@Canvas
        val mitte = center
        val obenLinks = Offset(mitte.x - r, mitte.y - r)
        val flaeche = Size(2f * r, 2f * r)
        drawArc(
            color = thema.rand, startAngle = startWinkel, sweepAngle = bogen, useCenter = false,
            topLeft = obenLinks, size = flaeche, style = Stroke(width = ring, cap = StrokeCap.Round)
        )
        val a = anteil.coerceIn(0f, 1f)
        if (a > 0f) {
            drawArc(
                color = thema.akzent, startAngle = startWinkel, sweepAngle = bogen * a, useCenter = false,
                topLeft = obenLinks, size = flaeche, style = Stroke(width = ring, cap = StrokeCap.Round)
            )
        }
        val innen = r - ring / 2f - 5.dp.toPx()
        for (i in 0 until GestaltRegel.STRICHE) {
            val lang = GestaltRegel.strichLang(i)
            val laenge = (if (lang) 7 else 3).dp.toPx()
            val dicke = maxOf(1f, (if (lang) 2 else 1).dp.toPx())
            val w = Math.toRadians(GestaltRegel.strichWinkel(i))
            val c = cos(w).toFloat()
            val s = sin(w).toFloat()
            drawLine(
                color = thema.grau2,
                start = Offset(mitte.x + c * innen, mitte.y + s * innen),
                end = Offset(mitte.x + c * (innen - laenge), mitte.y + s * (innen - laenge)),
                strokeWidth = dicke, cap = StrokeCap.Round
            )
        }
        if (griff) {
            val w = Math.toRadians((startWinkel + bogen * a).toDouble())
            val punkt = Offset(mitte.x + cos(w).toFloat() * r, mitte.y + sin(w).toFloat() * r)
            drawCircle(color = thema.hintergrund, radius = ring * 1.3f, center = punkt)
            drawCircle(color = thema.akzent, radius = ring * 0.9f, center = punkt)
        }
    }
}

/** STATUS-PUNKT: 8-dp-Punkt vor dem Wort; die Farbe folgt dem Wort. */
@Composable
fun StatusZeile(status: GestaltRegel.Status, modifier: Modifier = Modifier) {
    val thema = LocalChanceThema.current
    Row(modifier = modifier, verticalAlignment = Alignment.CenterVertically) {
        Box(
            Modifier
                .size(8.dp)
                .background(thema.status(status.art), CircleShape)
        )
        Spacer(Modifier.width(Raum.s2))
        BasicText(status.wort, style = thema.klein.copy(color = thema.text))
    }
}

/** AUGENBRAUE: Abschnitts-Kennung über einer Gruppe. */
@Composable
fun Augenbraue(text: String, modifier: Modifier = Modifier) {
    BasicText(text, modifier = modifier, style = LocalChanceThema.current.augenbraue, maxLines = 1)
}

/** Der LOS-KNOPF: der EINE Vollkörper in Bernstein je Fläche. */
@Composable
fun LosKnopf(text: String, aktiv: Boolean, modifier: Modifier = Modifier, onClick: () -> Unit) {
    val thema = LocalChanceThema.current
    Box(
        modifier = modifier
            .widthIn(min = 112.dp)
            .height(44.dp)
            .background(if (aktiv && thema.schnitt.vollflaeche) thema.akzent else thema.knopf, Ecke.pille)
            .border(1.dp, if (aktiv) thema.akzent else thema.rand, Ecke.pille)
            .clickable(enabled = aktiv, onClick = onClick)
            .padding(horizontal = Raum.s4),
        contentAlignment = Alignment.Center
    ) {
        val schrift = when {
            !aktiv -> thema.grau2
            thema.schnitt.vollflaeche -> thema.textAufAkzent
            else -> thema.akzent
        }
        BasicText(text, style = thema.held.copy(color = schrift))
    }
}

/** KNOPF (Umriss): Knopf-Grund, Rand, Ecke s; hervorgehoben = Bernstein-Rand. */
@Composable
fun UmrissKnopf(text: String, modifier: Modifier = Modifier, hervor: Boolean = false, onClick: () -> Unit) {
    val thema = LocalChanceThema.current
    Box(
        modifier = modifier
            .height(36.dp)
            .background(thema.knopf, Ecke.s)
            .border(1.dp, if (hervor) thema.akzent else thema.rand, Ecke.s)
            .clickable(onClick = onClick)
            .padding(horizontal = Raum.s3),
        contentAlignment = Alignment.Center
    ) {
        BasicText(text, style = thema.klein.copy(color = if (hervor) thema.akzent else thema.text))
    }
}

/** PILLE: Zustands-Chip; aktiv = Akzent-Rand + Akzent-Text, sonst Rand. */
@Composable
fun Pille(text: String, aktiv: Boolean, modifier: Modifier = Modifier, onClick: (() -> Unit)? = null) {
    val thema = LocalChanceThema.current
    Box(
        modifier = modifier
            .border(1.dp, if (aktiv) thema.akzent else thema.rand, Ecke.pille)
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
            .padding(horizontal = Raum.s3, vertical = Raum.s1),
        contentAlignment = Alignment.Center
    ) {
        BasicText(text, style = thema.klein.copy(color = if (aktiv) thema.akzent else thema.grau))
    }
}

/** BLATT-FOLGE: „‹ LINKS · RECHTS ›“ am Fuß einer Uhr-/Außenfläche. */
@Composable
fun BlattHinweis(links: String?, rechts: String?, modifier: Modifier = Modifier) {
    val thema = LocalChanceThema.current
    val text = listOfNotNull(links?.let { "‹ $it" }, rechts?.let { "$it ›" }).joinToString(" · ")
    BasicText(text, modifier = modifier, style = thema.klein.copy(color = thema.grau2, textAlign = TextAlign.Center))
}

/** KARTE: Kartenfläche + 1-px-Rand, Ecke m. */
@Composable
fun Karte(modifier: Modifier = Modifier, inhalt: @Composable () -> Unit) {
    val thema = LocalChanceThema.current
    Column(
        modifier = modifier
            .fillMaxWidth()
            .background(thema.karte, Ecke.m)
            .border(1.dp, thema.rand, Ecke.m)
            .padding(horizontal = Raum.s3, vertical = Raum.s2),
        verticalArrangement = Arrangement.spacedBy(Raum.s1)
    ) {
        inhalt()
    }
}

/** DATEN-ZEILE: Schlüssel grau links, Wert in Mono rechts. */
@Composable
fun DatenZeile(schluessel: String, wert: String, wertFarbe: Color? = null) {
    val thema = LocalChanceThema.current
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        BasicText(schluessel, style = thema.klein, modifier = Modifier.weight(1f))
        Spacer(Modifier.width(Raum.s2))
        BasicText(wert, style = thema.daten.copy(color = wertFarbe ?: thema.text, textAlign = TextAlign.End), maxLines = 1, softWrap = false)
    }
}

/** KENNZAHLEN-LEISTE: Wert (Mono, fett) über Etikett (klein, grau2). */
@Composable
fun KennzahlenLeiste(zahlen: List<Pair<String, String>>, modifier: Modifier = Modifier) {
    val thema = LocalChanceThema.current
    Row(modifier = modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
        zahlen.forEach { (wert, etikett) ->
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                BasicText(wert.ifBlank { "—" }, style = thema.daten.copy(fontWeight = FontWeight.Bold))
                BasicText(etikett, style = thema.klein.copy(color = thema.grau2, letterSpacing = 0.1.em))
            }
        }
    }
}

/** Die Krone (Uhr) bzw. das Drehrad scrollt einen [ScrollState]. */
@Composable
fun Modifier.kroneScrollt(zustand: ScrollState, aktiv: Boolean): Modifier {
    val fokus = remember { FocusRequester() }
    val scope = rememberCoroutineScope()
    LaunchedEffect(aktiv) {
        if (aktiv) runCatching { fokus.requestFocus() }
    }
    return this
        .onRotaryScrollEvent { ereignis ->
            scope.launch { zustand.scrollBy(ereignis.verticalScrollPixels) }
            true
        }
        .focusRequester(fokus)
        .focusable()
}
