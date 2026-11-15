package net.schanz.rejuvenationbed.watch

import android.content.Context
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import kotlinx.coroutines.delay
import net.schanz.chance.gestalt.ChanceGestalt
import net.schanz.chance.gestalt.ChanceThema
import net.schanz.chance.gestalt.GestaltRegel
import net.schanz.rejuvenationbed.watch.blatt.DebugBlatt
import net.schanz.rejuvenationbed.watch.blatt.SchlafBlatt
import net.schanz.rejuvenationbed.watch.blatt.ThermoBlatt
import net.schanz.rejuvenationbed.watch.health.HeartRateSampleStore
import net.schanz.rejuvenationbed.watch.ui.UhrRegel
import java.time.LocalTime

/** Die Blatt-Folge der Uhr: THERMO ‹ SCHLAF › DEBUG (SCHLAF ist START). */
enum class Blatt { THERMO, SCHLAF, DEBUG;

    companion object {
        fun aus(name: String?): Blatt =
            entries.firstOrNull { it.name.equals(name?.trim(), ignoreCase = true) } ?: SCHLAF
    }
}

private const val PREFS_UI = "rejuvenation_bed_watch_ui"
private const val KEY_GESICHT = "gesicht"

private fun gesichtLesen(context: Context): UhrRegel.GesichtWahl =
    UhrRegel.GesichtWahl.aus(context.getSharedPreferences(PREFS_UI, Context.MODE_PRIVATE).getString(KEY_GESICHT, null))

private fun gesichtSchreiben(context: Context, wahl: UhrRegel.GesichtWahl) {
    context.getSharedPreferences(PREFS_UI, Context.MODE_PRIVATE).edit().putString(KEY_GESICHT, wahl.name).apply()
}

/**
 * Die Uhr trägt zwei Gesichter aus dem chance-framework: BETT (gedimmter Bernstein im Dunkeln) und
 * SOFA (Tag, mit Kraft). AUTO wählt nach Nachtfenster und Schlafzustand; geprüft wird jede Minute.
 */
@Composable
fun UhrApp(start: Blatt) {
    val context = LocalContext.current
    var wahl by remember { mutableStateOf(gesichtLesen(context)) }
    var minute by remember { mutableIntStateOf(0) }
    LaunchedEffect(Unit) {
        while (true) {
            delay(60_000L)
            minute += 1
        }
    }
    val stunde = remember(minute) { LocalTime.now().hour }
    val schlaf = remember(minute) { HeartRateSampleStore.latestPlatformSleepState(context)?.state }
    val modus = UhrRegel.gesicht(wahl, stunde, schlaf)
    val thema = ChanceThema(modus, GestaltRegel.Schale.UHR)

    ChanceGestalt(thema) {
        val blaetter = rememberPagerState(initialPage = start.ordinal, pageCount = { Blatt.entries.size })
        HorizontalPager(
            state = blaetter,
            modifier = Modifier
                .fillMaxSize()
                .background(thema.hintergrund)
        ) { seite ->
            val aktiv = blaetter.currentPage == seite
            when (Blatt.entries[seite]) {
                Blatt.THERMO -> ThermoBlatt()
                Blatt.SCHLAF -> SchlafBlatt(aktiv)
                Blatt.DEBUG -> DebugBlatt(aktiv, wahl, modus) { neu ->
                    wahl = neu
                    gesichtSchreiben(context, neu)
                }
            }
        }
    }
}
