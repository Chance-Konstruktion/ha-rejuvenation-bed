package net.schanz.rejuvenationbed.watch.ui

import net.schanz.chance.gestalt.GestaltRegel
import net.schanz.chance.gestalt.GestaltRegel.Status
import net.schanz.chance.gestalt.GestaltRegel.StatusArt
import net.schanz.rejuvenationbed.watch.health.HeartRateCapability
import net.schanz.rejuvenationbed.watch.health.PlatformSleepState

/**
 * Die Regeln, die nur diese Uhr-App kennt. Farben, Schrift, Raum und Bauteile
 * kommen aus dem eingebauten chance-framework (net.schanz.chance.gestalt).
 */
object UhrRegel {
    /** Welches Gesicht die Uhr zeigt: nach Uhrzeit und Schlaf, oder fest gewählt. */
    enum class GesichtWahl(val wort: String) { AUTO("auto"), BETT("bett"), SOFA("sofa");

        /** Durchschalten am Knopf: auto → bett → sofa → auto. */
        fun naechste(): GesichtWahl = entries[(ordinal + 1) % entries.size]

        companion object {
            fun aus(name: String?): GesichtWahl =
                entries.firstOrNull { it.name.equals(name?.trim(), ignoreCase = true) } ?: AUTO
        }
    }

    /** Der Modus des Gesichts: feste Wahl gewinnt, sonst Nachtfenster und Schlafzustand der Uhr. */
    fun gesicht(wahl: GesichtWahl, stunde: Int, schlaf: PlatformSleepState?): GestaltRegel.Modus = when (wahl) {
        GesichtWahl.BETT -> GestaltRegel.Modus.BETT
        GesichtWahl.SOFA -> GestaltRegel.Modus.SOFA
        GesichtWahl.AUTO -> GestaltRegel.tagesModus(stunde, schlaeft = schlaf == PlatformSleepState.ASLEEP)
    }

    /**
     * Status der Schlafmessung aus Sensor-Fähigkeit, Rechten und dem
     * gespeicherten Sammelstatus.
     */
    fun schlafStatus(
        faehigkeit: HeartRateCapability,
        rechtFehlt: Boolean,
        sammelStatus: String,
        beschaeftigt: Boolean
    ): Status = when {
        faehigkeit == HeartRateCapability.Checking -> Status("prüft", StatusArt.LAEUFT)
        faehigkeit is HeartRateCapability.Failed -> Status("fehler", StatusArt.FEHLER)
        faehigkeit == HeartRateCapability.Unsupported -> Status("kein sensor", StatusArt.STILL)
        beschaeftigt -> Status("startet", StatusArt.LAEUFT)
        sammelStatus == "permission_lost" -> Status("recht verloren", StatusArt.FEHLER)
        sammelStatus == "registration_failed" -> Status("fehler", StatusArt.FEHLER)
        sammelStatus == "stop_failed" -> Status("fehler", StatusArt.FEHLER)
        sammelStatus == "collecting" -> Status("misst", StatusArt.LAEUFT)
        sammelStatus == "registered" -> Status("wartet", StatusArt.LAEUFT)
        rechtFehlt -> Status("recht fehlt", StatusArt.STILL)
        else -> Status("bereit", StatusArt.BEREIT)
    }

    /** Text des EINEN Los-Knopfs zum selben Zustand. */
    fun losKnopf(
        faehigkeit: HeartRateCapability,
        rechtFehlt: Boolean,
        sammelStatus: String,
        beschaeftigt: Boolean
    ): String = when {
        faehigkeit != HeartRateCapability.Supported -> "—"
        beschaeftigt -> "…"
        sammelStatus == "registered" || sammelStatus == "collecting" -> "STOPP"
        rechtFehlt -> "ERLAUBEN"
        else -> "MESSEN"
    }
}
