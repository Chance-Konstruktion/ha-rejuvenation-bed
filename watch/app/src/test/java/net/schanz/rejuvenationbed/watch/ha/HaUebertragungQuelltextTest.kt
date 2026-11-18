package net.schanz.rejuvenationbed.watch.ha

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.file.Files
import java.nio.file.Path

/**
 * Wache über die Hausregeln der HA-Übertragung — die kritischen Stellen sind
 * Compose-/Android-Code und laufen nicht in der JVM, darum liest dieser Test
 * den Quelltext und pinnt:
 *
 * - Kein Messwert und keine Adresse im Protokoll: Die HA-Zeilen nennen
 *   Nacht-Datum, Anzahlen und Gründe — nie bpm, RMSSD, Intervalle, URL.
 * - Die Nutzlast trägt die Schalterstellung (`modus`) mit.
 * - Beim Umschalten auf „Gesamtdaten“ zeigt das Schlaf-Blatt einmal deutlich,
 *   welche Werte übertragen werden (mit „nie Cloud“ und den fehlenden Kanälen).
 * - Die HA-Adresse steht nur in der App-privaten Einstellungstaste, nie in
 *   einer Nutzlast, nie im Protokoll.
 */
class HaUebertragungQuelltextTest {

    private fun quelle(relativ: String, alternativ: String = "watch/app/$relativ"): String {
        var ort: Path? = Path.of(System.getProperty("user.dir"))
        repeat(8) {
            ort?.let { basis ->
                listOf(relativ, alternativ).forEach { kandidat ->
                    val datei = basis.resolve(kandidat)
                    if (Files.isRegularFile(datei)) return Files.readString(datei)
                }
            }
            ort = ort?.parent
        }
        throw AssertionError("$relativ nicht gefunden")
    }

    private fun haQuelle(name: String): String =
        quelle("src/main/java/net/schanz/rejuvenationbed/watch/ha/$name")

    /** Zeilen mit Protokoll-Ereignissen — dort stehen die Antworten, sonst nichts. */
    private fun protokollZeilen(text: String): List<String> =
        text.lines().filter { "DebugProtokoll.ereignis(" in it }

    @Test
    fun dieNutztlastTraegtDieSchalterstellung() {
        val bauer = haQuelle("NachtBerichtBauer.kt")
        assertTrue("phase_update trägt modus", "modus" in bauer)
        assertTrue("Bericht trägt modus", "\"modus\", modus.wireValue" in bauer)
        assertTrue("Pakete tragen modus", "put(\"modus\", modus.wireValue)" in bauer)
    }

    @Test
    fun keineMesswerteImProtokollDerUebertragung() {
        val steuerung = haQuelle("HaUebertragung.kt")
        val zeilen = protokollZeilen(steuerung)
        assertTrue("es gibt HA-Protokollzeilen zu pinnen", zeilen.isNotEmpty())
        val verboten = listOf(".bpm", "beatsPerMinute", "rmssd", "sdnn", "intervalMillis", "interval_ms", "signalQuality")
        zeilen.forEach { zeile ->
            verboten.forEach { wert ->
                assertFalse(
                    "Protokollzeile enthält einen Messwert ($wert): $zeile",
                    wert in zeile
                )
            }
        }
    }

    @Test
    fun dieAdresseStehtNirgendsImProtokoll() {
        // Der Sender importiert das Protokoll gar nicht; die Steuerung nennt
        // nur, dass die Adresse gesetzt/entfernt wurde — nie den Wert.
        val sender = haQuelle("HaWebhookSender.kt")
        assertFalse("der Sender protokolliert nicht", "DebugProtokoll" in sender)
        val zeilen = protokollZeilen(haQuelle("HaUebertragung.kt"))
        assertFalse(
            "keine Protokollzeile trägt eine URL (://)",
            zeilen.any { "://" in it }
        )
        val blatt = quelle("src/main/java/net/schanz/rejuvenationbed/watch/blatt/SchlafBlatt.kt")
        assertFalse(
            "auch das Schlaf-Blatt protokolliert keine URL",
            protokollZeilen(blatt).any { "://" in it }
        )
        val einstellungen = haQuelle("HaUebertragungsEinstellungen.kt")
        assertTrue("die Adresse liegt in einer eigenen Taste", "KEY_ADRESSE" in einstellungen)
    }

    @Test
    fun dieUmschaltungZeigtDieUebertragenenWerte() {
        val blatt = quelle("src/main/java/net/schanz/rejuvenationbed/watch/blatt/SchlafBlatt.kt")
        assertTrue(
            "beim Umschalten auf Gesamtdaten geht der Hinweis an",
            "gesamtdatenHinweis = true" in blatt
        )
        assertTrue(
            "der Hinweis listet die übertragenen Werte",
            "uebertrageneWerte" in blatt
        )
        assertTrue(
            "der Hinweis nennt die Grenze: nie Cloud",
            "nie Cloud" in blatt
        )
        assertTrue(
            "der Hinweis nennt die Doppelungs-Regel",
            "keine Doppelungen" in blatt
        )
        assertTrue(
            "der Hinweis kann abgewiesen werden",
            "VERSTANDEN" in blatt
        )
    }

    @Test
    fun dieLoeschAktionVergisstAuchDieWarteschlange() {
        val blatt = quelle("src/main/java/net/schanz/rejuvenationbed/watch/blatt/SchlafBlatt.kt")
        assertTrue(
            "nach dem Daten-Löschen wird auch die HA-Warteschlange geleert (Rohdaten-Kopien)",
            "HaUebertragung.vergessen(" in blatt
        )
        val steuerung = haQuelle("HaUebertragung.kt")
        assertTrue(
            "vergessen() leert die Warteschlange und den Messungs-Anker",
            "HaUebertragungsEinstellungen.leere(" in steuerung &&
                "HaUebertragungsEinstellungen.loescheMessungStart(" in steuerung
        )
    }

    @Test
    fun dieSteuerungSendetImHintergrundNichtImMessweg() {
        val steuerung = haQuelle("HaUebertragung.kt")
        assertTrue(
            "eigener Arbeitsfaden für alle Sendungen",
            "Executors.newSingleThreadExecutor" in steuerung
        )
    }

    @Test
    fun dieSendungGehtNurUeberDenLokalenWebhook() {
        val steuerung = haQuelle("HaUebertragung.kt")
        assertTrue("alle Sendungen laufen über HaWebhookSender", "HaWebhookSender.senden(" in steuerung)
        // Es gibt keinen zweiten Netzweg im ha-Paket (kein Retrofit/OkHttp/Wear-Datenweg hier).
        assertFalse(
            "kein zusätzliches HTTP-Framework",
            "OkHttp" in steuerung || "Retrofit" in steuerung || "Wearable" in steuerung
        )
    }

    /**
     * 18.11.: SPEICHERN mit leerem Feld hat die gespeicherte Adresse gelöscht
     * und dabei „leere Adresse — nichts geändert“ protokolliert. Seitdem gilt:
     * im SPEICHERN-Knopf wird erst auf ein nicht-leeres Feld geprüft, dann
     * gesetzt; entfernt wird nur über LEEREN.
     */
    @Test
    fun leeresSpeichernLoeschtDieAdresseNicht() {
        val blatt = quelle("src/main/java/net/schanz/rejuvenationbed/watch/blatt/SchlafBlatt.kt")
        val anfang = blatt.indexOf("UmrissKnopf(\"SPEICHERN\")")
        val ende = blatt.indexOf("UmrissKnopf(\"LEEREN\")")
        assertTrue("SPEICHERN- und LEEREN-Knopf gefunden", anfang in 0 until ende)
        val speichern = blatt.substring(anfang, ende)
        val pruefung = speichern.indexOf("isNotBlank()")
        val setzen = speichern.indexOf("setzeAdresse(")
        assertTrue("SPEICHERN prüft das Feld auf Inhalt", pruefung >= 0)
        assertTrue("SPEICHERN setzt die Adresse", setzen >= 0)
        assertTrue("erst prüfen, dann setzen", pruefung < setzen)
        assertFalse("SPEICHERN löscht nie", "setzeAdresse(context, null)" in speichern)
    }
}
