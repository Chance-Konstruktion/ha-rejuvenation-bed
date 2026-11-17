package net.schanz.rejuvenationbed.watch.ha

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Der lokale Webhook ist der einzige Weg; Umleitungen und Ablehnungen werden benannt. */
class HaWebhookSenderTest {

    private fun verbindung(code: Int, koerper: String? = null, fehler: String? = null) =
        object : HaWebhookSender.Verbindung {
            override fun verbinden(url: String, json: String, timeoutMillis: Int): HaWebhookSender.Antwort =
                HaWebhookSender.Antwort(code, koerper, fehler)
        }

    @Test
    fun angenommeneSendungErfolgreich() {
        val ergebnis = HaWebhookSender.senden("http://ha-lokal/api/webhook/x", "{}", verbindung(200, "{\"ok\":true}"))
        assertTrue(ergebnis.erfolgreich)
    }

    @Test
    fun ablehnungBenenntDenHttpStatus() {
        val ergebnis = HaWebhookSender.senden("http://ha-lokal/api/webhook/x", "{}", verbindung(400, "{\"error\":\"schema\"}"))
        assertFalse(ergebnis.erfolgreich)
        assertTrue(ergebnis.grund.contains("HTTP 400"))
        assertTrue("die Wiederholung wird benannt", ergebnis.grund.contains("Warteschlange"))
    }

    @Test
    fun verbindungsfehlerBleibtBenanntOhneWerte() {
        val ergebnis = HaWebhookSender.senden("http://ha-lokal/api/webhook/x", "{}", verbindung(-1, fehler = "ConnectException"))
        assertFalse(ergebnis.erfolgreich)
        assertTrue(ergebnis.grund.contains("Verbindung fehlgeschlagen"))
    }

    @Test
    fun umleitungWirdNichtGefolgt() {
        // „nie ein fremder Dienst": ein 3xx würde die Nutzlast an eine andere
        // Adresse schicken — genau das bricht die Sendung ab.
        val ergebnis = HaWebhookSender.senden("http://ha-lokal/api/webhook/x", "{}", verbindung(302))
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
