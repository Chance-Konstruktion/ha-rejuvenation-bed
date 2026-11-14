package net.schanz.rejuvenationbed.watch.blatt

import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.style.TextAlign
import net.schanz.rejuvenationbed.watch.dial.TemperatureDialScale
import net.schanz.rejuvenationbed.watch.ui.Augenbraue
import net.schanz.rejuvenationbed.watch.ui.BlattHinweis
import net.schanz.rejuvenationbed.watch.ui.Farbe
import net.schanz.rejuvenationbed.watch.ui.GestaltRegel
import net.schanz.rejuvenationbed.watch.ui.Raum
import net.schanz.rejuvenationbed.watch.ui.Schrift
import net.schanz.rejuvenationbed.watch.ui.StatusZeile
import net.schanz.rejuvenationbed.watch.ui.Zifferblatt
import java.util.Locale
import kotlin.math.min
import kotlin.math.sqrt

private const val MIN_BETT = 24.0f
private const val MAX_BETT = 36.0f

/**
 * THERMO-Blatt: das Zifferblatt als 270°-Ring (Lücke unten), Griff am
 * Bernstein-Ende. Gezogen wird nur am Ring; in der Mitte wischt man weiter.
 * Noch Vorschau: es geht kein Befehl an Home Assistant.
 */
@Composable
fun ThermoBlatt() {
    var ziel by remember { mutableFloatStateOf(29.0f) }
    val anteil = ((ziel - MIN_BETT) / (MAX_BETT - MIN_BETT)).coerceIn(0f, 1f)

    Box(
        modifier = Modifier
            .fillMaxSize()
            .pointerInput(Unit) {
                awaitEachGesture {
                    val unten = awaitFirstDown(requireUnconsumed = false)
                    val breite = size.width.toFloat()
                    val hoehe = size.height.toFloat()
                    fun wert(x: Float, y: Float) = TemperatureDialScale.fromPosition(
                        x = x, y = y, width = breite, height = hoehe, minimum = MIN_BETT, maximum = MAX_BETT
                    )
                    val dx = unten.position.x - breite / 2f
                    val dy = unten.position.y - hoehe / 2f
                    val amRing = sqrt(dx * dx + dy * dy) >= min(breite, hoehe) / 2f * 0.62f
                    if (!amRing) return@awaitEachGesture
                    unten.consume()
                    wert(unten.position.x, unten.position.y)?.let { ziel = it }
                    while (true) {
                        val ereignis = awaitPointerEvent()
                        val finger = ereignis.changes.firstOrNull() ?: break
                        if (!finger.pressed) break
                        finger.consume()
                        wert(finger.position.x, finger.position.y)?.let { ziel = it }
                    }
                }
            },
        contentAlignment = Alignment.Center
    ) {
        Zifferblatt(
            anteil = anteil,
            modifier = Modifier.fillMaxSize(),
            startWinkel = 135f,
            bogen = 270f,
            griff = true
        )
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            StatusZeile(GestaltRegel.Status("vorschau", GestaltRegel.StatusArt.STILL))
            Spacer(Modifier.height(Raum.s2))
            Augenbraue("ZIEL")
            BasicText(String.format(Locale.GERMANY, "%.1f°", ziel), style = Schrift.buehne)
            BasicText(
                "nicht verbunden",
                style = Schrift.klein.copy(color = Farbe.Grau2, textAlign = TextAlign.Center)
            )
        }
        BlattHinweis(
            null, "SCHLAF",
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .padding(bottom = Raum.s5)
        )
    }
}
