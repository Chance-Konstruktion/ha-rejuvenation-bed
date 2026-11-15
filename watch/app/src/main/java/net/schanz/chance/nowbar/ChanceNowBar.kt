// KOPIE aus chance-framework 0.1.0 (3500d1a) – hier nicht ändern, im Framework ändern und neu einbauen.
package net.schanz.chance.nowbar

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import androidx.annotation.DrawableRes
import androidx.core.app.NotificationCompat
import androidx.wear.ongoing.OngoingActivity
import androidx.wear.ongoing.Status

/**
 * NOW BAR (One UI Watch, Wear OS): Eine App, die im Hintergrund etwas tut
 * (Messung, Timer, Lauf), zeigt das als laufende Aktivität (Ongoing
 * Activity). One UI Watch stellt sie in der Now Bar auf dem Zifferblatt
 * dar, je nach Einstellung „Now Bar-Stil“:
 *
 *  - „Nur Symbole“: allein das [NowBarAnzeige.symbol] – es muss ohne Text
 *    verständlich sein (einfarbig weiß, eigene Form, keine Schrift im Bild).
 *  - „Symbole mit Text“: Symbol + [NowBarAnzeige.text], höchstens
 *    [NowBarText.MAX_ZEICHEN] Zeichen (ein Wort oder Zahl + Einheit).
 *
 * Ein Tipp führt über [NowBarAnzeige.ziel] auf das passende Blatt.
 * Der Aufrufer hält die Benachrichtigung in einem Vordergrunddienst
 * (startForeground) und baut sie für neue Texte mit derselben id neu.
 */
data class NowBarAnzeige(
    val kanalId: String,
    val kanalName: String,
    val id: Int,
    @DrawableRes val symbol: Int,
    val titel: String,
    val text: String,
    val ziel: PendingIntent,
    val kategorie: String = NotificationCompat.CATEGORY_STATUS
)

object ChanceNowBar {
    /** Baut die Benachrichtigung samt laufender Aktivität. */
    fun benachrichtigung(context: Context, anzeige: NowBarAnzeige): Notification {
        val kurz = NowBarText.kuerzen(anzeige.text)
        val manager = context.getSystemService(NotificationManager::class.java)
        if (manager.getNotificationChannel(anzeige.kanalId) == null) {
            manager.createNotificationChannel(
                NotificationChannel(anzeige.kanalId, anzeige.kanalName, NotificationManager.IMPORTANCE_LOW)
            )
        }
        val bauer = NotificationCompat.Builder(context, anzeige.kanalId)
            .setSmallIcon(anzeige.symbol)
            .setContentTitle(anzeige.titel)
            .setContentText(kurz)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setCategory(anzeige.kategorie)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .setContentIntent(anzeige.ziel)
        OngoingActivity.Builder(context, anzeige.id, bauer)
            .setStaticIcon(anzeige.symbol)
            .setTouchIntent(anzeige.ziel)
            .setStatus(Status.Builder().addTemplate(kurz).build())
            .build()
            .apply(context)
        return bauer.build()
    }

    /** Neuer Text, solange der Vordergrunddienst die Anzeige hält. */
    fun erneuern(context: Context, anzeige: NowBarAnzeige) {
        runCatching {
            context.getSystemService(NotificationManager::class.java)
                .notify(anzeige.id, benachrichtigung(context, anzeige))
        }
    }
}

/** Die Text-Regel der Now Bar (JVM-pur, geprüft). */
object NowBarText {
    const val MAX_ZEICHEN = 10

    fun kuerzen(text: String, ersatz: String = "läuft"): String {
        val t = text.trim().ifEmpty { ersatz }
        return if (t.length <= MAX_ZEICHEN) t else t.take(MAX_ZEICHEN - 1) + "…"
    }

    /** „62 bpm“, „29,5°“ – Zahl + Einheit, sonst das Ersatzwort. */
    fun zahl(wert: Double?, einheit: String, ersatz: String = "läuft"): String =
        if (wert == null || !wert.isFinite()) ersatz else kuerzen("${wert.toInt()} $einheit".trim(), ersatz)
}
