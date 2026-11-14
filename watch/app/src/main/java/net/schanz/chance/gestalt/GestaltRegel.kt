// KOPIE aus chance-framework 0.1.0 (3500d1a) – hier nicht ändern, im Framework ändern und neu einbauen.
// Abweichung von 3500d1a (Fund w14-tp, hier an der Wurzel geheilt): die BETT-Tokens grau2 und ROT_BETT
// sind heller, weil beide im Bett als echte Schrift auftreten – jede Bett-Schrift hält ≥ 4,5:1.
package net.schanz.chance.gestalt

/**
 * Die Gesetze der Chance-Gestalt, JVM-pur (keine Android-Klassen) und in der
 * Suite geprüft. Die Zahlen stehen gleichlautend in tokens/chance-tokens.json
 * und web/chance-kern.css; tests/test_tokens.py wacht über den Gleichstand.
 *
 * Herkunft: ADL DESIGN.md („ein Stil für fünf Oberflächen“, A-191/A-210) und
 * der ADL-KERN v1 der Website (A-173).
 */
object GestaltRegel {
    const val VERSION = "0.1.0"

    /** Minuten-Striche des Zifferblatts; jeder fünfte ist lang. */
    const val STRICHE = 60

    /** Die Raum-Leiter (dp/px). Zwischenwerte gibt es nicht. */
    val RAUM_LEITER = intArrayOf(4, 8, 12, 16, 24, 40)

    /** Die vier Ecken; die Pille ist die einzige unendliche Ecke. */
    const val ECKE_S = 6
    const val ECKE_M = 10
    const val ECKE_L = 16
    const val ECKE_PILLE = 999

    const val KONTRAST_MINDESTENS = 4.5

    /** Bildschirm-Klassen (Schalen). */
    enum class Schale { UHR, KLEIN, NORMAL, BROWSER }

    /** Typo-Stufen einer Schale in sp/px; titel fehlt auf der Uhr. */
    data class Typo(val klein: Int, val text: Int, val titel: Int?, val held: Int, val buehne: Int? = null)

    fun typo(schale: Schale): Typo = when (schale) {
        Schale.UHR -> Typo(11, 14, null, 20, buehne = 30)
        Schale.KLEIN -> Typo(11, 13, 16, 20)
        Schale.NORMAL -> Typo(12, 14, 17, 22)
        Schale.BROWSER -> Typo(12, 14, 16, 18)
    }

    /** KLEIN: kurze Seite unter 480 dp UND fast quadratisch (ADL A-209). */
    const val KLEIN_KURZE_SEITE_DP = 480f
    const val KLEIN_VERHAELTNIS = 1.25f

    /**
     * Welche Schale eine Fläche trägt. Eine Uhr ist immer UHR; Flip-Außen
     * (≈ 427 × 411 dp) ist KLEIN; Telefon, Tablet, Fold innen und Fernseher
     * sind NORMAL.
     */
    fun schale(uhr: Boolean, breiteDp: Float, hoeheDp: Float): Schale {
        if (uhr) return Schale.UHR
        if (breiteDp <= 0f || hoeheDp <= 0f) return Schale.NORMAL
        val kurz = minOf(breiteDp, hoeheDp)
        val lang = maxOf(breiteDp, hoeheDp)
        return if (kurz < KLEIN_KURZE_SEITE_DP && lang / kurz < KLEIN_VERHAELTNIS) Schale.KLEIN else Schale.NORMAL
    }

    /**
     * AMOLED ist der Standard. BETT ist das Gesicht im Dunkeln (nur Bernstein, gedimmt, keine Vollflächen),
     * SOFA das Gesicht am Tag mit Kraft (warmes Weiß, kräftiger Bernstein, Vollflächen).
     */
    enum class Modus { AMOLED, NACHT, HELL, BETT, SOFA }

    /** Die zehn Rollen (plus „gedrückt“) als ARGB. */
    data class Rollen(
        val hintergrund: Int,
        val karte: Int,
        val gedrueckt: Int,
        val rand: Int,
        val vertieft: Int,
        val knopf: Int,
        val text: Int,
        val grau: Int,
        val grau2: Int,
        val akzent: Int,
        val textAufAkzent: Int
    ) {
        /**
         * Die Paarungen des Kontrast-Gesetzes, wie ADL sie prüft
         * (DesignRegel.kontrastGesetz): text, grau und akzent auf
         * hintergrund, karte und gedrückt, dazu text auf akzent.
         * grau2 ist Hinweis/Platzhalter und steht nicht im Gesetz.
         */
        fun schriftPaare(): List<Pair<Int, Int>> {
            val flaechen = listOf(hintergrund, karte, gedrueckt)
            return flaechen.flatMap { f -> listOf(text, grau, akzent).map { it to f } } +
                (textAufAkzent to akzent)
        }
    }

    private fun argb(rgb: Long): Int = (0xFF000000 or rgb).toInt()

    fun rollen(modus: Modus): Rollen = when (modus) {
        Modus.AMOLED -> Rollen(
            argb(0x000000), argb(0x000000), argb(0x141414), argb(0x2A2420), argb(0x000000),
            argb(0x141414), argb(0xE8EAED), argb(0xB8C2CB), argb(0x8A8F96), argb(0xD99130), argb(0x1A1200)
        )
        Modus.NACHT -> Rollen(
            argb(0x000000), argb(0x14110B), argb(0x201B13), argb(0x332C22), argb(0x0D0B07),
            argb(0x1D1913), argb(0xE8EAED), argb(0xB8C2CB), argb(0x8A8F96), argb(0xD99130), argb(0x1A1200)
        )
        Modus.HELL -> Rollen(
            argb(0xF4F5F1), argb(0xFFFFFF), argb(0xE7E9E2), argb(0xD9DDE1), argb(0xECE5D8),
            argb(0xE6DFD0), argb(0x1A1D21), argb(0x59626C), argb(0x6E675C), argb(0x8F5400), argb(0xFFFFFF)
        )
        Modus.BETT -> Rollen(
            argb(0x000000), argb(0x000000), argb(0x120C05), argb(0x2B1D0C), argb(0x000000),
            argb(0x0E0904), argb(0xB68D56), argb(0xA97439), argb(0xA57233), argb(0xB47726), argb(0x000000)
        )
        Modus.SOFA -> Rollen(
            argb(0x000000), argb(0x1C1307), argb(0x33230D), argb(0x4A3417), argb(0x0E0904),
            argb(0x261A0A), argb(0xFFF4E2), argb(0xE2C9A4), argb(0xA88E6B), argb(0xF5A33A), argb(0x1A1000)
        )
    }

    /**
     * Der Schnitt eines Modus: Gewicht der Zahlen und Titel, Etiketten in Mono oder gesperrter Sans,
     * und ob aktive Knöpfe als Vollfläche leuchten dürfen (im Bett nicht).
     */
    data class Schnitt(
        val zahl: Int,
        val titel: Int,
        val etikettMono: Boolean,
        val sperrung: Float,
        val vollflaeche: Boolean
    )

    fun schnitt(modus: Modus): Schnitt = when (modus) {
        Modus.AMOLED, Modus.NACHT, Modus.HELL -> Schnitt(700, 700, etikettMono = true, sperrung = 0.14f, vollflaeche = true)
        Modus.BETT -> Schnitt(300, 400, etikettMono = false, sperrung = 0.22f, vollflaeche = false)
        Modus.SOFA -> Schnitt(800, 700, etikettMono = false, sperrung = 0.16f, vollflaeche = true)
    }

    /** Das Nachtfenster: von 21 Uhr bis 7 Uhr gilt BETT, sonst SOFA. Schlaf schaltet immer auf BETT. */
    const val NACHT_VON = 21
    const val NACHT_BIS = 7

    fun tagesModus(stunde: Int, schlaeft: Boolean = false, von: Int = NACHT_VON, bis: Int = NACHT_BIS): Modus {
        require(stunde in 0..23) { "Stunde 0..23" }
        val nacht = if (von <= bis) stunde in von until bis else stunde >= von || stunde < bis
        return if (schlaeft || nacht) Modus.BETT else Modus.SOFA
    }

    /** Status-Semantik: Farbe ist Bedeutung, und neben jeder Farbe steht ein Wort. */
    enum class StatusArt { BEREIT, LAEUFT, SCHAETZT, FEHLER, STILL }

    data class Status(val wort: String, val art: StatusArt) {
        init {
            require(wort.isNotBlank()) { "Ein Status braucht ein Wort (nie nur Farbe)" }
        }
    }

    const val GRUEN = 0xFF3FB950.toInt()
    const val GELB = 0xFFFBBF24.toInt()
    const val ROT = 0xFFF85149.toInt()

    /** Im Bett leuchtet nichts Grünes oder Gelbes; der Fehler bleibt rot, aber gedimmt (5,24:1 auf Schwarz). Das Wort trägt. */
    const val ROT_BETT = 0xFFE14A3B.toInt()

    /** LAEUFT trägt den Akzent, STILL das grau2 der Fläche. */
    fun statusFarbe(art: StatusArt, modus: Modus = Modus.AMOLED): Int {
        val r = rollen(modus)
        if (modus == Modus.BETT) return when (art) {
            StatusArt.BEREIT -> r.grau
            StatusArt.LAEUFT, StatusArt.SCHAETZT -> r.akzent
            StatusArt.FEHLER -> ROT_BETT
            StatusArt.STILL -> r.grau2
        }
        return when (art) {
            StatusArt.BEREIT -> GRUEN
            StatusArt.LAEUFT -> r.akzent
            StatusArt.SCHAETZT -> GELB
            StatusArt.FEHLER -> ROT
            StatusArt.STILL -> r.grau2
        }
    }

    fun raum(stufe: Int): Int {
        require(stufe in 1..RAUM_LEITER.size) { "Raum-Stufe $stufe liegt nicht auf der Leiter" }
        return RAUM_LEITER[stufe - 1]
    }

    fun strichLang(index: Int): Boolean = index % 5 == 0

    /** Winkel in Grad, 0 = rechts; Strich 0 steht oben (12 Uhr). */
    fun strichWinkel(index: Int): Double = index * (360.0 / STRICHE) - 90.0

    /** Gefüllter Anteil eines Rings: gültige von allen Einheiten, 0–1. */
    fun ringAnteil(gueltig: Int, gesamt: Int): Float =
        if (gesamt <= 0) 0f else (gueltig.toFloat() / gesamt).coerceIn(0f, 1f)

    /** Relative WCAG-Leuchtdichte eines ARGB-Werts. */
    fun leuchtdichte(argb: Int): Double {
        fun kanal(wert: Int): Double {
            val c = wert / 255.0
            return if (c <= 0.03928) c / 12.92 else Math.pow((c + 0.055) / 1.055, 2.4)
        }
        return 0.2126 * kanal((argb shr 16) and 0xFF) +
            0.7152 * kanal((argb shr 8) and 0xFF) +
            0.0722 * kanal(argb and 0xFF)
    }

    fun kontrast(vorne: Int, hinten: Int): Double {
        val a = leuchtdichte(vorne)
        val b = leuchtdichte(hinten)
        return (maxOf(a, b) + 0.05) / (minOf(a, b) + 0.05)
    }

    /** Jede Schrift gegen jede Fläche ≥ 4,5:1 – in jedem Modus. */
    fun kontrastGesetz(modus: Modus): Boolean =
        rollen(modus).schriftPaare().all { (vorne, hinten) -> kontrast(vorne, hinten) >= KONTRAST_MINDESTENS }

    /** Höchster Kontrast der Bett-Schrift gegen Schwarz: dezent, nicht grell. */
    const val BETT_TEXT_HOECHSTENS = 7.5

    /**
     * Das Bett ist warm und gedimmt: jede Rolle hat Rot ≥ Grün ≥ Blau (kein Weiß, kein Blaustich),
     * und jede Bett-Schrift ist nicht heller als [BETT_TEXT_HOECHSTENS] gegen Schwarz. Jede
     * Bett-Schrift hält ≥ 4,5:1 auf jeder Bett-Fläche – grau2 und ROT_BETT eingeschlossen, denn
     * beide treten im Bett als echte Schrift auf (Fund w14-tp).
     */
    fun bettIstWarmUndGedimmt(): Boolean {
        val r = rollen(Modus.BETT)
        val alle = listOf(r.hintergrund, r.karte, r.gedrueckt, r.rand, r.vertieft, r.knopf,
            r.text, r.grau, r.grau2, r.akzent, r.textAufAkzent, ROT_BETT)
        val warm = alle.all { c ->
            val rot = (c shr 16) and 0xFF
            val gruen = (c shr 8) and 0xFF
            val blau = c and 0xFF
            rot >= gruen && gruen >= blau
        }
        val schwarz = argb(0x000000)
        val schriften = listOf(r.text, r.grau, r.grau2, r.akzent, ROT_BETT)
        val flaechen = listOf(r.hintergrund, r.karte, r.gedrueckt, r.knopf)
        val lesbar = schriften.all { s -> flaechen.all { f -> kontrast(s, f) >= KONTRAST_MINDESTENS } }
        val gedimmt = schriften.all { kontrast(it, schwarz) <= BETT_TEXT_HOECHSTENS }
        return warm && lesbar && gedimmt
    }

    /** AMOLED ist ehrlich: Hintergrund UND Karte sind echtes Schwarz. */
    fun amoledIstEhrlich(): Boolean = rollen(Modus.AMOLED).let {
        it.hintergrund == argb(0x000000) && it.karte == argb(0x000000)
    }
}
