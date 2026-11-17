package net.schanz.rejuvenationbed.watch.ha

import java.net.HttpURLConnection
import java.net.URL

/** Ergebnis einer Sendung — Grund ohne Messwerte und ohne Adresse. */
data class HaSendeErgebnis(
    val erfolgreich: Boolean,
    val grund: String
)

/**
 * POST an den lokalen Nachtbericht-Webhook der eigenen Home-Assistant-Instanz.
 *
 * Hausregeln, durchgezogen:
 * - Es gibt genau diesen einen Weg: den hier gesetzten Endpunkt, im Heimnetz.
 *   Umleitungen werden bewusst NICHT gefolgt — ein 3xx würde die Nutzlast an
 *   eine andere Adresse schicken, und genau das ist „ein fremder Dienst“.
 * - Kein Log, kein Protokoll, keine Ausgabe berührt die Adresse oder Werte;
 *   die Gründe hier sind Sätze, keine Daten.
 *
 * Die eigentliche Verbindung liegt hinter [Verbindung], damit die Logik ohne
 * Netz in JVM-Unit-Tests geprüft werden kann.
 */
object HaWebhookSender {

    interface Verbindung {
        /** Führt den POST aus und liefert HTTP-Code und Körper — oder einen Verbindungsfehler. */
        fun verbinden(url: String, json: String, timeoutMillis: Int): Antwort
    }

    data class Antwort(val code: Int, val koerper: String?, val fehler: String?)

    object StandardVerbindung : Verbindung {
        override fun verbinden(url: String, json: String, timeoutMillis: Int): Antwort {
            return try {
                val verbindung = URL(url).openConnection() as HttpURLConnection
                verbindung.requestMethod = "POST"
                verbindung.connectTimeout = timeoutMillis
                verbindung.readTimeout = timeoutMillis
                verbindung.doOutput = true
                // Kein Umleitungsfollow: Die Nutzlast geht nur an die gesetzte Adresse.
                verbindung.instanceFollowRedirects = false
                verbindung.setRequestProperty("Content-Type", "application/json")
                verbindung.outputStream.use { out -> out.write(json.toByteArray(Charsets.UTF_8)) }
                val code = verbindung.responseCode
                val koerper = runCatching { verbindung.errorStream?.bufferedReader()?.use { it.readText() } }
                    .getOrNull() ?: runCatching { verbindung.inputStream.bufferedReader().use { it.readText() } }.getOrNull()
                verbindung.disconnect()
                Antwort(code, koerper, fehler = null)
            } catch (fehler: Exception) {
                Antwort(code = -1, koerper = null, fehler = fehler.javaClass.simpleName)
            }
        }
    }

    fun senden(
        url: String,
        json: String,
        verbindung: Verbindung = StandardVerbindung,
        timeoutMillis: Int = 10_000
    ): HaSendeErgebnis {
        if (url.isBlank()) {
            return HaSendeErgebnis(false, "keine HA-Adresse gesetzt")
        }
        if (!url.startsWith("http://") && !url.startsWith("https://")) {
            return HaSendeErgebnis(false, "HA-Adresse beginnt nicht mit http:// oder https://")
        }
        val antwort = verbindung.verbinden(url, json, timeoutMillis)
        antwort.fehler?.let { fehlertext ->
            return HaSendeErgebnis(false, "Verbindung fehlgeschlagen ($fehlertext) — Wiederholung bleibt in der Warteschlange")
        }
        if (antwort.code in 300..399) {
            return HaSendeErgebnis(false, "HA hat umgeleitet — Sendung abgebrochen, nichts an eine andere Adresse geschickt")
        }
        if (antwort.code == 200) {
            return HaSendeErgebnis(true, "angenommen")
        }
        return HaSendeErgebnis(false, "HA lehnte ab (HTTP ${antwort.code}) — Wiederholung bleibt in der Warteschlange")
    }
}
