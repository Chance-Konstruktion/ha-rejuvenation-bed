package net.schanz.rejuvenationbed.watch.ha

import android.content.Context

/**
 * Persistente Einstellungen der HA-Übertragung, App-privat auf der Uhr.
 *
 * Die Adresse der eigenen Home-Assistant-Instanz steht hier als einziger
 * Stelle — nie im Protokoll, nie in einer Nutzlast, nie im Log. Der Schalter
 * steht ab Werk auf „Nur Schlafphase“ ([HaUebertragungModus.standard]).
 */
object HaUebertragungsEinstellungen {
    private const val PREFERENCES = "rejuvenation_bed_watch_ha"
    private const val KEY_MODUS = "ha_uebertragung_modus"
    private const val KEY_ADRESSE = "ha_nachtbericht_adresse"
    private const val KEY_WARTESCHLANGE = "ha_warteschlange"
    private const val KEY_STATUS = "ha_letzte_antwort"
    private const val KEY_MESSUNG_START = "ha_messung_start"

    fun modus(context: Context): HaUebertragungModus {
        val roh = prefs(context).getString(KEY_MODUS, null)
        return HaUebertragungModus.aus(roh)
    }

    fun setzeModus(context: Context, modus: HaUebertragungModus) {
        prefs(context).edit().putString(KEY_MODUS, modus.wireValue).apply()
    }

    /** Die Adresse des eigenen Home Assistant — nur im Gerät, nie in Ausgaben. */
    fun adresse(context: Context): String? =
        prefs(context).getString(KEY_ADRESSE, null)?.trim()?.takeIf { it.isNotEmpty() }

    fun hatAdresse(context: Context): Boolean = adresse(context) != null

    fun setzeAdresse(context: Context, adresse: String?) {
        val bereinigt = adresse?.trim()?.takeIf { it.isNotEmpty() }
        prefs(context).edit().putString(KEY_ADRESSE, bereinigt).apply()
    }

    /** Beginn der laufenden Messung — Anker für Nacht-Kennung und Zeitleiste. */
    fun messungStart(context: Context): Long? {
        val wert = prefs(context).getLong(KEY_MESSUNG_START, -1L)
        return if (wert > 0L) wert else null
    }

    fun setzeMessungStart(context: Context, epochMillis: Long) {
        prefs(context).edit().putLong(KEY_MESSUNG_START, epochMillis).apply()
    }

    fun loescheMessungStart(context: Context) {
        prefs(context).edit().putLong(KEY_MESSUNG_START, -1L).apply()
    }

    fun warteschlange(context: Context): NachtSendeWarteschlange =
        NachtSendeWarteschlange.ausJson(prefs(context).getString(KEY_WARTESCHLANGE, null))

    fun sichereWarteschlange(context: Context, warte: NachtSendeWarteschlange) {
        prefs(context).edit().putString(KEY_WARTESCHLANGE, warte.alsJson()).apply()
    }

    /** Letzter Sendungs-Ausgang in Worten — für die Statuszeile, ohne Werte. */
    fun letzteAntwort(context: Context): String? = prefs(context).getString(KEY_STATUS, null)

    fun setzeLetzteAntwort(context: Context, text: String) {
        prefs(context).edit().putString(KEY_STATUS, text).apply()
    }

    fun leere(context: Context) {
        prefs(context).edit()
            .remove(KEY_WARTESCHLANGE)
            .putString(KEY_STATUS, "Warteschlange geleert")
            .apply()
    }

    private fun prefs(context: Context) =
        context.applicationContext.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
}
