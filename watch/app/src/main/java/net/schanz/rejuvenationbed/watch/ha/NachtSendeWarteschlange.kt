package net.schanz.rejuvenationbed.watch.ha

import org.json.JSONArray
import org.json.JSONObject

/** Ein Sendung in der Warteschlange — mit Versuchszähler für die Wiederholung. */
data class SendeEintrag(
    val schluessel: String,
    val art: String,
    val json: String,
    val versuche: Int,
    val zuletztEpochMillis: Long
)

/**
 * Warteschlange für Sendungen an den lokalen Home-Assistant-Webhook.
 *
 * Zwei Versprechen des Auftrags stecken hier drin:
 *
 * - **Wiederholung, wenn HA nicht erreichbar war** — eine fehlgeschlagene
 *   Sendung bleibt stehen (Versuchszähler hoch) und wird beim nächsten
 *   Abholen wieder versucht.
 * - **Ohne Doppelungen (Zeitstempel als Schlüssel)** — jeder Eintrag trägt
 *   einen Schlüssel aus Zeitstempeln bzw. der Nacht-Kennung; stellt man
 *   denselben Schlüssel erneut an (gleicher Block, gleiche Nacht, gleiche
 *   Phase), ersetzt er den alten Eintrag, statt daneben zu liegen. HA fasst
 *   einzelne Messpunkte zusätzlich über ihren Zeitstempel zusammen.
 *
 * Reine Logik, ohne Android-Zugriff; die dauerhafte Ablage schreibt nur die
 * JSON-Form dieser Klasse ([alsJson]/[ausJson]) in eine App-private Taste.
 */
class NachtSendeWarteschlange(private val maximaleGroesse: Int = 96) {

    private val eintraege = LinkedHashMap<String, SendeEintrag>()

    /**
     * Sendung anstellen. Ein schon vorhandener Schlüssel ersetzt den Inhalt,
     * behält aber Platz und Versuchszähler — das ist die No-Doppelung. Liefert
     * die Anzahl der ältesten Einträge, die bei voller Warteschlange weichen
     * mussten (Rohdaten-Kopien dürfen nicht unbegrenzt auf der Uhr liegen).
     */
    fun anstellen(art: String, schluessel: String, json: String, jetztEpochMillis: Long): Int {
        if (art.isBlank() || schluessel.isBlank()) return 0
        var verworfen = 0
        if (schluessel !in eintraege && eintraege.size >= maximaleGroesse) {
            val aeltester = eintraege.keys.firstOrNull() ?: return 0
            eintraege.remove(aeltester)
            verworfen = 1
        }
        val vorhanden = eintraege[schluessel]
        eintraege[schluessel] = SendeEintrag(
            schluessel = schluessel,
            art = art,
            json = json,
            versuche = vorhanden?.versuche ?: 0,
            zuletztEpochMillis = vorhanden?.zuletztEpochMillis ?: jetztEpochMillis
        )
        return verworfen
    }

    /** Ältester Eintrag oder null, wenn leer. */
    fun naechster(): SendeEintrag? = eintraege.values.firstOrNull()

    fun alsErledigt(schluessel: String) {
        eintraege.remove(schluessel)
    }

    /**
     * Endgültig abgewiesene Adresse (nicht im Heimnetz): die ganze Schlange
     * weicht — nichts bleibt für eine Adresse hängen, an die nie gesendet
     * wird (sonst Endlos-Wiederholung bei jedem Abholen).
     */
    fun leeren() {
        eintraege.clear()
    }

    /** Fehlgeschlagen: Eintrag bleibt, Versuchszähler steigt — die Wiederholung. */
    fun alsFehlgeschlagen(schluessel: String, jetztEpochMillis: Long) {
        val vorhanden = eintraege[schluessel] ?: return
        eintraege[schluessel] = vorhanden.copy(
            versuche = vorhanden.versuche + 1,
            zuletztEpochMillis = jetztEpochMillis
        )
    }

    fun umfasst(): Int = eintraege.size

    fun istLeer(): Boolean = eintraege.isEmpty()

    fun enthaelt(schluessel: String): Boolean = schluessel in eintraege

    fun alle(): List<SendeEintrag> = eintraege.values.toList()

    /** JSON-Form für die dauerhafte Ablage (App-private Taste, bleibt auf der Uhr). */
    fun alsJson(): String = JSONArray().apply {
        alle().forEach { eintrag ->
            put(
                JSONObject()
                    .put("schluessel", eintrag.schluessel)
                    .put("art", eintrag.art)
                    .put("json", eintrag.json)
                    .put("versuche", eintrag.versuche)
                    .put("zuletzt", eintrag.zuletztEpochMillis)
            )
        }
    }.toString()

    companion object {
        /** Aus der Ablage lesen; Unlesbares ergibt eine leere Warteschlange. */
        fun ausJson(text: String?): NachtSendeWarteschlange {
            val warte = NachtSendeWarteschlange()
            if (text.isNullOrBlank()) return warte
            runCatching {
                val feld = JSONArray(text)
                for (i in 0 until feld.length()) {
                    val roh = feld.getJSONObject(i)
                    val schluessel = roh.optString("schluessel")
                    val art = roh.optString("art")
                    val json = roh.optString("json")
                    val zuletzt = roh.optLong("zuletzt")
                    val versuche = roh.optInt("versuche").coerceAtLeast(0)
                    if (schluessel.isBlank() || art.isBlank() || json.isBlank()) continue
                    warte.eintraege[schluessel] = SendeEintrag(
                        schluessel = schluessel,
                        art = art,
                        json = json,
                        versuche = versuche,
                        zuletztEpochMillis = zuletzt
                    )
                }
            }
            return warte
        }
    }
}
