package net.schanz.rejuvenationbed.watch.nowbar

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.wear.ongoing.OngoingActivity
import androidx.wear.ongoing.Status
import net.schanz.rejuvenationbed.watch.MainActivity
import net.schanz.rejuvenationbed.watch.R
import net.schanz.rejuvenationbed.watch.debug.DebugProtokoll
import net.schanz.rejuvenationbed.watch.health.WearHealthPermissions

/**
 * NOW BAR: Solange die Schlafmessung im Hintergrund läuft, zeigt die Uhr
 * eine laufende Aktivität (Wear OS Ongoing Activity). One UI Watch stellt
 * sie in der Now Bar auf dem Zifferblatt dar – je nach Einstellung
 * „Now Bar-Stil“ als „Nur Symbole“ oder „Symbole mit Text“.
 *
 * Gesetze (Chance-Gestalt):
 *  - Das Symbol trägt allein (Stil „Nur Symbole“): einfarbig, eigene Form.
 *  - Der Text ist kurz (höchstens [NowBarText.MAX_ZEICHEN] Zeichen), ein
 *    Wort oder eine Zahl mit Einheit (Stil „Symbole mit Text“).
 *  - Ein Tipp öffnet die App auf dem passenden Blatt.
 */
object NowBar {
    private const val KANAL = "rbw_messung"
    private const val ID = 4711

    fun starten(context: Context, text: String = "misst") {
        val app = context.applicationContext
        // Ohne Pulsrecht darf ein Health-Vordergrunddienst nicht starten.
        if (!WearHealthPermissions.isGranted(app, WearHealthPermissions.heartRatePermission())) {
            DebugProtokoll.ereignis(app, "NOWBAR", "nicht gestartet: Pulsrecht fehlt")
            return
        }
        val absicht = Intent(app, NowBarDienst::class.java).putExtra(NowBarDienst.EXTRA_TEXT, text)
        runCatching { app.startForegroundService(absicht) }
            .onFailure { DebugProtokoll.ereignis(app, "NOWBAR", "Start fehlgeschlagen: ${it.javaClass.simpleName}") }
    }

    fun stoppen(context: Context) {
        val app = context.applicationContext
        app.stopService(Intent(app, NowBarDienst::class.java))
    }

    /** Text in der Now Bar erneuern (nur wenn der Dienst läuft). */
    fun aktualisieren(context: Context, text: String) {
        val app = context.applicationContext
        if (!NowBarDienst.laeuft) return
        runCatching {
            app.getSystemService(NotificationManager::class.java)
                .notify(ID, benachrichtigung(app, text))
        }
    }

    internal fun benachrichtigung(context: Context, text: String): android.app.Notification {
        val kurz = NowBarText.kuerzen(text)
        val manager = context.getSystemService(NotificationManager::class.java)
        if (manager.getNotificationChannel(KANAL) == null) {
            manager.createNotificationChannel(
                NotificationChannel(KANAL, "Schlafmessung", NotificationManager.IMPORTANCE_LOW)
            )
        }
        val ziel = PendingIntent.getActivity(
            context, 0,
            Intent(context, MainActivity::class.java)
                .putExtra(MainActivity.EXTRA_BLATT, "SCHLAF")
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        val bauer = NotificationCompat.Builder(context, KANAL)
            .setSmallIcon(R.drawable.ic_nowbar_bett)
            .setContentTitle("Rejuvenation Bed")
            .setContentText("Schlaf: $kurz")
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setCategory(NotificationCompat.CATEGORY_STATUS)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .setContentIntent(ziel)
        OngoingActivity.Builder(context, ID, bauer)
            .setStaticIcon(R.drawable.ic_nowbar_bett)
            .setTouchIntent(ziel)
            .setStatus(Status.Builder().addTemplate(kurz).build())
            .build()
            .apply(context)
        return bauer.build()
    }

    internal const val NOTIFICATION_ID = ID
}

/** Reine Text-Regel der Now Bar (JVM-geprüft). */
object NowBarText {
    const val MAX_ZEICHEN = 10

    fun kuerzen(text: String): String {
        val t = text.trim().ifEmpty { "misst" }
        return if (t.length <= MAX_ZEICHEN) t else t.take(MAX_ZEICHEN - 1) + "…"
    }

    /** „62 bpm“ für einen Pulswert, sonst das Zustandswort. */
    fun puls(bpm: Double?): String =
        if (bpm == null || !bpm.isFinite()) "misst" else "${bpm.toInt()} bpm"
}

/** Vordergrunddienst, der nur die laufende Aktivität hält. Er misst nichts selbst. */
class NowBarDienst : Service() {
    companion object {
        const val EXTRA_TEXT = "text"
        @Volatile
        var laeuft = false
            private set
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val text = intent?.getStringExtra(EXTRA_TEXT) ?: "misst"
        try {
            val n = NowBar.benachrichtigung(this, text)
            if (Build.VERSION.SDK_INT >= 34) {
                startForeground(NowBar.NOTIFICATION_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_HEALTH)
            } else {
                startForeground(NowBar.NOTIFICATION_ID, n)
            }
            if (!laeuft) DebugProtokoll.ereignis(this, "NOWBAR", "an: $text")
            laeuft = true
        } catch (fehler: Exception) {
            DebugProtokoll.ereignis(this, "NOWBAR", "Vordergrund verweigert: ${fehler.javaClass.simpleName} ${fehler.message ?: ""}")
            stopSelf()
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        if (laeuft) DebugProtokoll.ereignis(this, "NOWBAR", "aus")
        laeuft = false
        super.onDestroy()
    }
}
