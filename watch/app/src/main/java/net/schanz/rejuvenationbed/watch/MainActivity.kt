package net.schanz.rejuvenationbed.watch

import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import net.schanz.rejuvenationbed.watch.debug.DebugProtokoll

/**
 * Vorschau-Tür wie bei ADL: ein Blatt direkt öffnen, z. B.
 *   adb shell am start -n net.schanz.rejuvenationbed.watch/.MainActivity --es rbw.blatt DEBUG
 */
class MainActivity : ComponentActivity() {
    companion object {
        const val EXTRA_BLATT = "rbw.blatt"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val version = runCatching { packageManager.getPackageInfo(packageName, 0).versionName }.getOrNull()
        DebugProtokoll.ereignis(this, "APP", "Start $version · ${Build.MODEL} · API ${Build.VERSION.SDK_INT}")
        val start = Blatt.aus(intent?.getStringExtra(EXTRA_BLATT))
        setContent {
            UhrApp(start)
        }
    }
}
