package net.schanz.rejuvenationbed.watch

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import net.schanz.rejuvenationbed.watch.blatt.DebugBlatt
import net.schanz.rejuvenationbed.watch.blatt.SchlafBlatt
import net.schanz.rejuvenationbed.watch.blatt.ThermoBlatt
import net.schanz.rejuvenationbed.watch.ui.Farbe

/** Die Blatt-Folge der Uhr: THERMO ‹ SCHLAF › DEBUG (SCHLAF ist START). */
enum class Blatt { THERMO, SCHLAF, DEBUG;

    companion object {
        fun aus(name: String?): Blatt =
            entries.firstOrNull { it.name.equals(name?.trim(), ignoreCase = true) } ?: SCHLAF
    }
}

@Composable
fun UhrApp(start: Blatt) {
    val blaetter = rememberPagerState(initialPage = start.ordinal, pageCount = { Blatt.entries.size })
    HorizontalPager(
        state = blaetter,
        modifier = Modifier
            .fillMaxSize()
            .background(Farbe.Hintergrund)
    ) { seite ->
        val aktiv = blaetter.currentPage == seite
        when (Blatt.entries[seite]) {
            Blatt.THERMO -> ThermoBlatt()
            Blatt.SCHLAF -> SchlafBlatt(aktiv)
            Blatt.DEBUG -> DebugBlatt(aktiv)
        }
    }
}
