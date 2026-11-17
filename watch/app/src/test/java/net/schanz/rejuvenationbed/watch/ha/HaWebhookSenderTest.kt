package net.schanz.rejuvenationbed.watch.ha

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.InetAddress

/**
 * Der lokale Webhook ist der einzige Weg; Umleitungen und Ablehnungen werden benannt.
 *
 * Dazu die Hausregel „Gesundheitsdaten verlassen das Haus nie“ (Heilung des
 * Funds 40477, Claude 17.11.): die Adresse wird vor dem Senden gewogen — der
 * Host wird hinter [HaWebhookSender.AdressLoesung] aufgelöst (in den Tests
 * eine Attrappe mit Dokumentations-Adressen, RFC 5737/3849 — keine echten
 * Adressen), nur private/Link-Local-Adressen und .local-Namen reiten; alles
 * andere wird ABGEWIESEN, bevor irgendein Byte die Leitung berührt, und die
 * Sendung bleibt NICHT in der Warteschlange hängen (kein Wiederholen).
 */
class HaWebhookSenderTest {

    private fun verbindung(code: Int, koerper: String? = null, fehler: String? = null) =
        object : HaWebhookSender.Verbindung {
            override fun verbinden(url: String, json: String, timeoutMillis: Int): HaWebhookSender.Antwort =
                HaWebhookSender.Antwort(code, koerper, fehler)
        }

    /** Attrappe der Auflösung — Dokumentations-Adressen (RFC 5737), niemals echte. */
    private class LoesungAttrappe(
        private val karte: Map<String, List<String>> = emptyMap(),
        var gerufen: Boolean = false
    ) : HaWebhookSender.AdressLoesung {
        override fun loese(host: String): List<InetAddress> {
            gerufen = true
            return (karte[host] ?: emptyList()).map { InetAddress.getByName(it) }
        }
    }

    /** Der Heimnetz-Rechner der bestehenden Tests: ha-lokal ist privat. */
    private fun heimnetz() = LoesungAttrappe(
        mapOf("ha-lokal" to listOf("192.168.1.247"))
    )

    // ── Die Hausregel: die Woge vor jedem Senden ────────────────────────────

    @Test
    fun oeffentlicheIpWirdAbgewiesen() {
        // RFC 5737 TEST-NET-3: als öffentlich gewogen — nichts geht hinaus.
        val loesung = LoesungAttrappe(mapOf("203.0.113.10" to listOf("203.0.113.10")))
        val ergebnis = HaWebhookSender.senden("http://203.0.113.10/api/webhook/x", "{}", verbindung(200), adressLoesung = loesung)
        assertFalse(ergebnis.erfolgreich)
        assertEquals(HaWebhookSender.HEIMNETZ_GRUND, ergebnis.grund)
        assertFalse("nichts bleibt für die öffentliche Adresse in der Warteschlange hängen", ergebnis.wiederholen)
        assertTrue("die Auflösung wurde gefragt", loesung.gerufen)
    }

    @Test
    fun oeffentlicherNameWirdAbgewiesen() {
        // example.com ist ein Dokumentations-Name (RFC 2606); die Attrappe
        // löst ihn auf eine öffentliche Dokumentations-Adresse auf.
        val loesung = LoesungAttrappe(mapOf("example.com" to listOf("203.0.113.7")))
        val ergebnis = HaWebhookSender.senden("https://example.com/api/webhook/x", "{}", verbindung(200), adressLoesung = loesung)
        assertFalse(ergebnis.erfolgreich)
        assertEquals(HaWebhookSender.HEIMNETZ_GRUND, ergebnis.grund)
        assertFalse(ergebnis.wiederholen)
    }

    @Test
    fun eineOeffentlicheUnterMehrerenVergiftetDieAdresse() {
        // Eine öffentliche Adresse unter mehreren aufgelösten genügt: alles
        // andere wäre eine Tür nach draußen mit Gesundheitsdaten.
        val loesung = LoesungAttrappe(
            mapOf("zwillingsname" to listOf("192.168.1.247", "203.0.113.9"))
        )
        val ergebnis = HaWebhookSender.senden("http://zwillingsname/api/webhook/x", "{}", verbindung(200), adressLoesung = loesung)
        assertFalse(ergebnis.erfolgreich)
        assertEquals(HaWebhookSender.HEIMNETZ_GRUND, ergebnis.grund)
    }

    @Test
    fun unloesbarerNameWirdAbgewiesen() {
        // Fail-closed: nicht auflösbar heißt nicht bewiesen im Heimnetz.
        val loesung = LoesungAttrappe()
        val ergebnis = HaWebhookSender.senden("http://nirgendwohn/api/webhook/x", "{}", verbindung(200), adressLoesung = loesung)
        assertFalse(ergebnis.erfolgreich)
        assertEquals(HaWebhookSender.HEIMNETZ_GRUND, ergebnis.grund)
        assertFalse(ergebnis.wiederholen)
    }

    @Test
    fun privatenAdressenReitenRfc1918() {
        val faelle = listOf("192.168.1.247", "10.1.2.3", "172.16.0.5")
        for (adresse in faelle) {
            val loesung = LoesungAttrappe(mapOf(adresse to listOf(adresse)))
            val ergebnis = HaWebhookSender.senden(
                "http://$adresse/api/webhook/x", "{}", verbindung(200), adressLoesung = loesung
            )
            assertTrue("private Adresse $adresse reitet", ergebnis.erfolgreich)
        }
    }

    @Test
    fun linkLokaleUndLokaleAdressenReiten() {
        // 169.254/16 (Link-Local), 127/8 (Loopback), fe80::/10, fc00::/7 (ULA).
        val faelle = listOf(
            "http://169.254.1.5/api/webhook/x" to "169.254.1.5",
            "http://127.0.0.1/api/webhook/x" to "127.0.0.1",
            "http://[fe80::1]/api/webhook/x" to "fe80::1",
            "http://[fd00::1]/api/webhook/x" to "fd00::1"
        )
        for ((url, literal) in faelle) {
            val loesung = LoesungAttrappe(mapOf(literal to listOf(literal)))
            val ergebnis = HaWebhookSender.senden(url, "{}", verbindung(200), adressLoesung = loesung)
            assertTrue("Link-Local/Loopback/ULA reitet: $literal", ergebnis.erfolgreich)
        }
    }

    @Test
    fun localNameReitetOhneAufloesung() {
        // .local ist das mDNS des Heimnetzes — die Woge fragt nicht einmal
        // nach (eine Attrappe ohne Einträge; gerufen bleibt false).
        val loesung = LoesungAttrappe()
        val ergebnis = HaWebhookSender.senden(
            "https://haustuer.local/api/webhook/x", "{}", verbindung(200), adressLoesung = loesung
        )
        assertTrue(ergebnis.erfolgreich)
        assertFalse("der .local-Name reitet ohne Auflösung", loesung.gerufen)
    }

    @Test
    fun dieWogeGiltAuchFuerDieStatuszeile() {
        // Dieselbe Woge trägt den Speichern-Hinweis des Schlaf-Blatts —
        // dieselbe Attrappen-Welt, dasselbe Urteil.
        assertFalse(
            "öffentlich aufgelöst ist nicht im Heimnetz",
            HaWebhookSender.adresseLiegtImHeimnetz(
                "http://203.0.113.10/x",
                LoesungAttrappe(mapOf("203.0.113.10" to listOf("203.0.113.10")))
            )
        )
        assertFalse(
            "unauflösbar heißt nicht bewiesen im Heimnetz (fail-closed)",
            HaWebhookSender.adresseLiegtImHeimnetz("http://203.0.113.10/x", LoesungAttrappe())
        )
        assertTrue(
            HaWebhookSender.adresseLiegtImHeimnetz("http://haustuer.local/x", LoesungAttrappe())
        )
        assertFalse(
            HaWebhookSender.adresseLiegtImHeimnetz("http://ha-lokal/x", LoesungAttrappe())
        )
    }

    // ── Die bestehenden Wachen (mit der Heimnetz-Attrappe) ──────────────────

    @Test
    fun angenommeneSendungErfolgreich() {
        val ergebnis = HaWebhookSender.senden(
            "http://ha-lokal/api/webhook/x", "{}", verbindung(200, "{\"ok\":true}"),
            adressLoesung = heimnetz()
        )
        assertTrue(ergebnis.erfolgreich)
    }

    @Test
    fun ablehnungBenenntDenHttpStatus() {
        val ergebnis = HaWebhookSender.senden(
            "http://ha-lokal/api/webhook/x", "{}", verbindung(400, "{\"error\":\"schema\"}"),
            adressLoesung = heimnetz()
        )
        assertFalse(ergebnis.erfolgreich)
        assertTrue(ergebnis.grund.contains("HTTP 400"))
        assertTrue("die Wiederholung wird benannt", ergebnis.grund.contains("Warteschlange"))
        assertTrue("HA-Ablehnungen wiederholen sich", ergebnis.wiederholen)
    }

    @Test
    fun verbindungsfehlerBleibtBenanntOhneWerte() {
        val ergebnis = HaWebhookSender.senden(
            "http://ha-lokal/api/webhook/x", "{}", verbindung(-1, fehler = "ConnectException"),
            adressLoesung = heimnetz()
        )
        assertFalse(ergebnis.erfolgreich)
        assertTrue(ergebnis.grund.contains("Verbindung fehlgeschlagen"))
        assertTrue("Verbindungsfehler wiederholen sich", ergebnis.wiederholen)
    }

    @Test
    fun umleitungWirdNichtGefolgt() {
        // „nie ein fremder Dienst": ein 3xx würde die Nutzlast an eine andere
        // Adresse schicken — genau das bricht die Sendung ab.
        val ergebnis = HaWebhookSender.senden(
            "http://ha-lokal/api/webhook/x", "{}", verbindung(302),
            adressLoesung = heimnetz()
        )
        assertFalse(ergebnis.erfolgreich)
        assertTrue(ergebnis.grund.contains("umgeleitet"))
    }

    @Test
    fun fehlendeAdresseWirdOhneNetzBenannt() {
        val ergebnis = HaWebhookSender.senden("", "{}", verbindung(200))
        assertFalse(ergebnis.erfolgreich)
        assertTrue(ergebnis.grund.contains("keine HA-Adresse"))
    }

    @Test
    fun nichtHttpAdressenWerdenAbgelehnt() {
        val ergebnis = HaWebhookSender.senden("file:///etc/passwd", "{}", verbindung(200))
        assertFalse(ergebnis.erfolgreich)
        assertTrue(ergebnis.grund.contains("http"))
    }

    @Test
    fun dieStandardVerbindungFolgtKeinenUmleitungen() {
        // Prüfbar am Quelltext: die echte Verbindung schaltet das Redirect-Follow aus,
        // damit die Nutzlast nur an die gesetzte lokale Adresse geht.
        val quelle = java.nio.file.Files.readString(
            java.nio.file.Path.of("src/main/java/net/schanz/rejuvenationbed/watch/ha/HaWebhookSender.kt")
        )
        assertTrue("instanceFollowRedirects = false muss gesetzt sein", "instanceFollowRedirects = false" in quelle)
    }
}
