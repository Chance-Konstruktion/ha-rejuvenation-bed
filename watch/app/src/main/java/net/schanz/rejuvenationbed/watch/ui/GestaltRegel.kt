package net.schanz.rejuvenationbed.watch.ui

import net.schanz.rejuvenationbed.watch.health.HeartRateCapability

/**
 * Die Gesetze der Gestalt, JVM-pur und in der Suite geprüft.
 *
 * Vorbild ist das Designbuch von ADL (`co-work/android-device-lab`, DESIGN.md,
 * „ein Stil für fünf Oberflächen“): AMOLED als Standard, EIN Bernstein-Akzent,
 * Raum im 4er-Takt, vier Ecken, Status-Farbe nie ohne Wort.
 */
object GestaltRegel {
    /** Minuten-Striche des Zifferblatts; jeder fünfte ist lang. */
    const val STRICHE = 60

    /** Die Raum-Leiter (dp). Zwischenwerte gibt es nicht. */
    val RAUM_LEITER = intArrayOf(4, 8, 12, 16, 24, 40)

    /** Die vier Ecken (dp); die Pille ist die einzige unendliche Ecke. */
    const val ECKE_S = 6
    const val ECKE_M = 10
    const val ECKE_L = 16

    /** Typo-Skala der Klasse UHR (sp): klein, text, held, Bühnenzahl. */
    const val TYPO_KLEIN = 11
    const val TYPO_TEXT = 14
    const val TYPO_HELD = 20
    const val TYPO_BUEHNE = 30

    /** Farben als ARGB, damit die Suite sie ohne Compose prüfen kann. */
    const val HINTERGRUND = 0xFF000000.toInt()
    const val RAND = 0xFF2A2420.toInt()
    const val KNOPF = 0xFF141414.toInt()
    const val TEXT = 0xFFE8EAED.toInt()
    const val GRAU = 0xFFB8C2CB.toInt()
    const val GRAU2 = 0xFF8A8F96.toInt()
    const val AKZENT = 0xFFD99130.toInt()
    const val TEXT_AUF_AKZENT = 0xFF1A1200.toInt()
    const val GRUEN = 0xFF3FB950.toInt()
    const val GELB = 0xFFFBBF24.toInt()
    const val ROT = 0xFFF85149.toInt()

    fun raum(stufe: Int): Int {
        require(stufe in 1..RAUM_LEITER.size) { "Raum-Stufe $stufe liegt nicht auf der Leiter" }
        return RAUM_LEITER[stufe - 1]
    }

    fun strichLang(index: Int): Boolean = index % 5 == 0

    /** Winkel in Grad, 0 = rechts, Strich 0 steht oben (12 Uhr). */
    fun strichWinkel(index: Int): Double = index * (360.0 / STRICHE) - 90.0

    /** Gefüllter Anteil des Rings: gültige von allen Einheiten, 0–1. */
    fun ringAnteil(gueltig: Int, gesamt: Int): Float =
        if (gesamt <= 0) 0f else (gueltig.toFloat() / gesamt).coerceIn(0f, 1f)

    enum class StatusArt { BEREIT, LAEUFT, FEHLER, STILL }

    /** Ein Status ist immer Farbe UND Wort (nie nur Farbe). */
    data class Status(val wort: String, val art: StatusArt)

    fun statusFarbe(art: StatusArt): Int = when (art) {
        StatusArt.BEREIT -> GRUEN
        StatusArt.LAEUFT -> AKZENT
        StatusArt.FEHLER -> ROT
        StatusArt.STILL -> GRAU2
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

    /** Relative WCAG-Leuchtdichte eines ARGB-Werts. */
    fun leuchtdichte(argb: Int): Double {
        fun kanal(wert: Int): Double {
            val c = wert / 255.0
            return if (c <= 0.03928) c / 12.92 else Math.pow((c + 0.055) / 1.055, 2.4)
        }
        val r = kanal((argb shr 16) and 0xFF)
        val g = kanal((argb shr 8) and 0xFF)
        val b = kanal(argb and 0xFF)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    }

    fun kontrast(vorne: Int, hinten: Int): Double {
        val a = leuchtdichte(vorne)
        val b = leuchtdichte(hinten)
        return (maxOf(a, b) + 0.05) / (minOf(a, b) + 0.05)
    }
}
