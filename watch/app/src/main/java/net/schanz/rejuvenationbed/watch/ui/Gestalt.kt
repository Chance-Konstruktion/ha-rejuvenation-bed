package net.schanz.rejuvenationbed.watch.ui

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
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
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

/** Die zehn Rollen im AMOLED-Modus (ADL DESIGN.md, Teil III). */
object Farbe {
    val Hintergrund = Color(GestaltRegel.HINTERGRUND)
    val Rand = Color(GestaltRegel.RAND)
    val Knopf = Color(GestaltRegel.KNOPF)
    val Text = Color(GestaltRegel.TEXT)
    val Grau = Color(GestaltRegel.GRAU)
    val Grau2 = Color(GestaltRegel.GRAU2)
    val Akzent = Color(GestaltRegel.AKZENT)
    val TextAufAkzent = Color(GestaltRegel.TEXT_AUF_AKZENT)

    fun status(art: GestaltRegel.StatusArt) = Color(GestaltRegel.statusFarbe(art))
}

/** Raum-Leiter als dp. */
object Raum {
    val s1 = GestaltRegel.raum(1).dp
    val s2 = GestaltRegel.raum(2).dp
    val s3 = GestaltRegel.raum(3).dp
    val s4 = GestaltRegel.raum(4).dp
    val s5 = GestaltRegel.raum(5).dp
    val s6 = GestaltRegel.raum(6).dp
}

object Schrift {
    private val sans = FontFamily.Default
    private val mono = FontFamily.Monospace

    val klein = TextStyle(fontFamily = mono, fontSize = GestaltRegel.TYPO_KLEIN.sp, color = Farbe.Grau)
    val text = TextStyle(fontFamily = sans, fontSize = GestaltRegel.TYPO_TEXT.sp, color = Farbe.Text)
    val held = TextStyle(
        fontFamily = sans, fontSize = GestaltRegel.TYPO_HELD.sp,
        fontWeight = FontWeight.Bold, color = Farbe.Text
    )
    val buehne = TextStyle(
        fontFamily = sans, fontSize = GestaltRegel.TYPO_BUEHNE.sp,
        fontWeight = FontWeight.Bold, color = Farbe.Text
    )
    val daten = TextStyle(fontFamily = mono, fontSize = GestaltRegel.TYPO_KLEIN.sp, color = Farbe.Text)
    val augenbraue = TextStyle(
        fontFamily = mono, fontSize = GestaltRegel.TYPO_KLEIN.sp,
        fontWeight = FontWeight.Bold, letterSpacing = 0.14.em, color = Farbe.Akzent
    )
}

/**
 * DAS ZIFFERBLATT: Spur in Rand-Farbe, Bernstein-Füllung, sechzig
 * Minuten-Striche in grau2 (jeder fünfte lang). Inhalt liegt darüber.
 * Mit [bogen] < 360 wird daraus der Thermostat-Ring (Lücke unten).
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
    Canvas(modifier = modifier) {
        val ring = ringDicke.toPx()
        val r = min(size.width, size.height) / 2f - ring / 2f - 2.dp.toPx()
        if (r <= ring) return@Canvas
        val mitte = center
        val obenLinks = Offset(mitte.x - r, mitte.y - r)
        val flaeche = Size(2f * r, 2f * r)
        drawArc(
            color = Farbe.Rand, startAngle = startWinkel, sweepAngle = bogen, useCenter = false,
            topLeft = obenLinks, size = flaeche, style = Stroke(width = ring, cap = StrokeCap.Round)
        )
        val a = anteil.coerceIn(0f, 1f)
        if (a > 0f) {
            drawArc(
                color = Farbe.Akzent, startAngle = startWinkel, sweepAngle = bogen * a, useCenter = false,
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
                color = Farbe.Grau2,
                start = Offset(mitte.x + c * innen, mitte.y + s * innen),
                end = Offset(mitte.x + c * (innen - laenge), mitte.y + s * (innen - laenge)),
                strokeWidth = dicke, cap = StrokeCap.Round
            )
        }
        if (griff) {
            val w = Math.toRadians((startWinkel + bogen * a).toDouble())
            val punkt = Offset(mitte.x + cos(w).toFloat() * r, mitte.y + sin(w).toFloat() * r)
            drawCircle(color = Farbe.Hintergrund, radius = ring * 1.3f, center = punkt)
            drawCircle(color = Farbe.Akzent, radius = ring * 0.9f, center = punkt)
        }
    }
}

/** STATUS-PUNKT: 8-dp-Punkt vor dem Wort, die Farbe folgt dem Wort. */
@Composable
fun StatusZeile(status: GestaltRegel.Status, modifier: Modifier = Modifier) {
    Row(modifier = modifier, verticalAlignment = Alignment.CenterVertically) {
        Box(
            Modifier
                .size(8.dp)
                .background(Farbe.status(status.art), CircleShape)
        )
        Spacer(Modifier.width(Raum.s2))
        BasicText(status.wort, style = Schrift.klein.copy(color = Farbe.Text))
    }
}

@Composable
fun Augenbraue(text: String, modifier: Modifier = Modifier) {
    BasicText(text, modifier = modifier, style = Schrift.augenbraue, maxLines = 1)
}

/** Der EINE Vollkörper in Bernstein. */
@Composable
fun LosKnopf(text: String, aktiv: Boolean, modifier: Modifier = Modifier, onClick: () -> Unit) {
    Box(
        modifier = modifier
            .widthIn(min = 112.dp)
            .height(44.dp)
            .background(if (aktiv) Farbe.Akzent else Farbe.Knopf, RoundedCornerShape(percent = 50))
            .border(1.dp, if (aktiv) Farbe.Akzent else Farbe.Rand, RoundedCornerShape(percent = 50))
            .clickable(enabled = aktiv, onClick = onClick)
            .padding(horizontal = Raum.s4),
        contentAlignment = Alignment.Center
    ) {
        BasicText(
            text,
            style = Schrift.held.copy(color = if (aktiv) Farbe.TextAufAkzent else Farbe.Grau2)
        )
    }
}

/** Umriss-Knopf: Knopf-Grund, Rand, Ecke s; aktiv = Bernstein-Rand. */
@Composable
fun UmrissKnopf(text: String, modifier: Modifier = Modifier, hervor: Boolean = false, onClick: () -> Unit) {
    Box(
        modifier = modifier
            .height(36.dp)
            .background(Farbe.Knopf, RoundedCornerShape(GestaltRegel.ECKE_S.dp))
            .border(1.dp, if (hervor) Farbe.Akzent else Farbe.Rand, RoundedCornerShape(GestaltRegel.ECKE_S.dp))
            .clickable(onClick = onClick)
            .padding(horizontal = Raum.s3),
        contentAlignment = Alignment.Center
    ) {
        BasicText(text, style = Schrift.klein.copy(color = if (hervor) Farbe.Akzent else Farbe.Text))
    }
}

/** Blatt-Folge unten: „‹ LINKS · RECHTS ›“. */
@Composable
fun BlattHinweis(links: String?, rechts: String?, modifier: Modifier = Modifier) {
    val text = listOfNotNull(links?.let { "‹ $it" }, rechts?.let { "$it ›" }).joinToString(" · ")
    BasicText(text, modifier = modifier, style = Schrift.klein.copy(color = Farbe.Grau2, textAlign = TextAlign.Center))
}

/** KARTE: 1-px-Rand, Ecke m, Fläche bleibt AMOLED-schwarz. */
@Composable
fun Karte(modifier: Modifier = Modifier, inhalt: @Composable () -> Unit) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .border(1.dp, Farbe.Rand, RoundedCornerShape(GestaltRegel.ECKE_M.dp))
            .padding(horizontal = Raum.s3, vertical = Raum.s2),
        verticalArrangement = Arrangement.spacedBy(Raum.s1)
    ) {
        inhalt()
    }
}

/** Zeile in einer Karte: Schlüssel grau, Wert in Mono. */
@Composable
fun DatenZeile(schluessel: String, wert: String, wertFarbe: Color = Farbe.Text) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        BasicText(schluessel, style = Schrift.klein)
        Spacer(Modifier.width(Raum.s2))
        BasicText(wert, style = Schrift.daten.copy(color = wertFarbe, textAlign = TextAlign.End))
    }
}

/** Die Krone scrollt: Drehereignisse an einen [ScrollState]. */
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
