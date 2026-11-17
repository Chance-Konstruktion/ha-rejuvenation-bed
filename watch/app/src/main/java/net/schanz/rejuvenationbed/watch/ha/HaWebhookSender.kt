package net.schanz.rejuvenationbed.watch.ha

import java.net.HttpURLConnection
import java.net.Inet6Address
import java.net.InetAddress
import java.net.URI
import java.net.URL

/** Ergebnis einer Sendung — Grund ohne Messwerte und ohne Adresse. */
data class HaSendeErgebnis(
    val erfolgreich: Boolean,
    val grund: String,
    /**
     * Wiederholt sich diese Sendung später? Ein Verbindungsfehler oder eine
     * HA-Ablehnung (HTTP) wiederholen sich — die Schlange hält den Eintrag.
     * Eine abgewiesene Adresse (nicht im Heimnetz) wiederholt sich NIE:
     * [wiederholen] ist dann false, der Eintrag bleibt NICHT in der
     * Warteschlange hängen (sonst Endlos-Wiederholung).
     */
    val wiederholen: Boolean = true
)

/**
 * POST an den lokalen Nachtbericht-Webhook der eigenen Home-Assistant-Instanz.
 *
 * Hausregeln, durchgezogen:
 * - Es gibt genau diesen einen Weg: den hier gesetzten Endpunkt, im Heimnetz.
 *   Umleitungen werden bewusst NICHT gefolgt — ein 3xx würde die Nutzlast an
 *   eine andere Adresse schicken, und genau das ist „ein fremder Dienst“.
 * - GESUNDHEITSDATEN VERLASSEN DAS HAUS NIE: der Host der Adresse wird vor
 *   jedem Senden aufgelöst und gewogen, EHE irgendein Byte die Leitung
 *   berührt. Erlaubt sind nur private und Link-Local-Adressen (RFC 1918:
 *   10/8, 172.16/12, 192.168/16; 169.254/16; 127/8; fc00::/7; fe80::/10)
 *   und Namen auf .local (das mDNS des Heimnetzes). Alles andere — Nabu-Casa-
 *   URL, Tippfehler, ein öffentlicher Name — wird ABGEWIESEN, bevor gesendet
 *   wird ([HEIMNETZ_GRUND]); fail-closed: auch ein nicht auflösbarer Host ist
 *   nicht bewiesen im Heimnetz und wird nicht gesendet.
 * - Kein Log, kein Protokoll, keine Ausgabe berührt die Adresse oder Werte;
 *   die Gründe hier sind Sätze, keine Daten.
 *
 * Die eigentliche Verbindung liegt hinter [Verbindung], die Auflösung des
 * Hosts hinter [AdressLoesung] — damit die Logik ohne Netz in JVM-Unit-Tests
 * geprüft werden kann.
 */
object HaWebhookSender {

    /** Abgewiesen, weil die Adresse nicht im Heimnetz liegt — nichts gesendet. */
    const val HEIMNETZ_GRUND = "Adresse liegt nicht im Heimnetz – nichts gesendet"

    interface Verbindung {
        /** Führt den POST aus und liefert HTTP-Code und Körper — oder einen Verbindungsfehler. */
        fun verbinden(url: String, json: String, timeoutMillis: Int): Antwort
    }

    /**
     * Auflösung eines Host-Namens in Adressen — leer bei Fehlschlag. Liegt
     * hinter dem eigenen Interface, damit die JVM-Tests ohne Netz prüfen
     * können; die Standard-Instanz fragt das Betriebssystem.
     */
    interface AdressLoesung {
        fun loese(host: String): List<InetAddress>
    }

    object StandardLoesung : AdressLoesung {
        override fun loese(host: String): List<InetAddress> = try {
            InetAddress.getAllByName(host).toList()
        } catch (fehler: Exception) {
            emptyList()
        }
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
        timeoutMillis: Int = 10_000,
        adressLoesung: AdressLoesung = StandardLoesung
    ): HaSendeErgebnis {
        if (url.isBlank()) {
            return HaSendeErgebnis(false, "keine HA-Adresse gesetzt")
        }
        if (!url.startsWith("http://") && !url.startsWith("https://")) {
            return HaSendeErgebnis(false, "HA-Adresse beginnt nicht mit http:// oder https://")
        }
        // HAUSREGEL „Gesundheitsdaten verlassen das Haus nie“ — die Woge EHE
        // irgendein Byte die Leitung berührt. EINE abgewiesene Adresse wird
        // endgültig abgewiesen (wiederholen=false): nichts geht hinaus und
        // nichts bleibt dafür in der Warteschlange hängen.
        if (!adresseLiegtImHeimnetz(url, adressLoesung)) {
            return HaSendeErgebnis(false, HEIMNETZ_GRUND, wiederholen = false)
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

    /**
     * Liegt der Host dieser Adresse im Heimnetz? Für die Statuszeile des
     * Schlaf-Blatts und für [senden] dieselbe Woge: .local-Namen reiten ohne
     * Auflösung (mDNS des Heimnetzes), jeder andere Host wird aufgelöst —
     * JEDE aufgelöste Adresse muss privat oder Link-Local sein (eine öffentliche
     * unter mehreren vergiftet die ganze Adresse); nicht auflösbar heißt
     * nicht bewiesen im Heimnetz — fail-closed.
     */
    fun adresseLiegtImHeimnetz(url: String, adressLoesung: AdressLoesung = StandardLoesung): Boolean {
        val host = try {
            URI(url).host
        } catch (fehler: Exception) {
            null
        } ?: return false
        return hostIstImHeimnetz(host, adressLoesung)
    }

    private fun hostIstImHeimnetz(host: String, loesung: AdressLoesung): Boolean {
        // IPv6-Literale reisen in URL-Klammern — die Woge will das nackte Wort.
        val name = host.trim().lowercase().removePrefix("[").removeSuffix("]")
        if (name.isEmpty()) return false
        if (name.endsWith(".local")) return true
        val adressen = loesung.loese(name)
        if (adressen.isEmpty()) return false
        return adressen.all { adresseIstImHeimnetz(it) }
    }

    /** Private und Link-Local-Bereiche — der Rahmen des Auftrags, sonst nichts. */
    private fun adresseIstImHeimnetz(adresse: InetAddress): Boolean {
        if (adresse.isLoopbackAddress) return true    // 127/8 und ::1
        if (adresse.isLinkLocalAddress) return true  // 169.254/16 und fe80::/10
        if (adresse.isSiteLocalAddress) return true   // RFC 1918: 10/8, 172.16/12, 192.168/16
        if (adresse is Inet6Address) {
            val erstesByte = adresse.address.firstOrNull()?.toInt()?.and(0xFF) ?: return false
            if ((erstesByte and 0xFE) == 0xFC) return true  // fc00::/7 — einzig lokaler Bereich (ULA)
        }
        return false
    }
}
