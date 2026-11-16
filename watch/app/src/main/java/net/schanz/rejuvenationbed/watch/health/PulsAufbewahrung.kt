package net.schanz.rejuvenationbed.watch.health

/**
 * Aufbewahrung des Puls-Speichers nach ZEIT statt nach Anzahl (#8, Ziel A).
 *
 * Bisher war `heart_rate_samples` ein JSON-Ring von 45.000 Werten — bei 1 Hz
 * waren die ersten ~28 min der Nacht 15./16.11. schon überschrieben. Der
 * neue Speicher behält alles innerhalb des Zeitfensters und räumt nach Zeit
 * auf: mindestens 36 Stunden bleiben liegen, ganz ohne Obergrenze der Anzahl
 * (36 h bei 1 Hz ≈ 130.000 Werte). Reine JVM-Logik, damit die Grenze geprüft
 * ist, ohne Android aufzurufen.
 */
object PulsAufbewahrung {
    /** Mindest-Aufbewahrung nach ZEIT: 36 Stunden. */
    const val RETENTION_MILLIS = 36L * 60L * 60L * 1000L

    /** Ältester noch aufbewahrter Zeitpunkt. */
    fun untergrenze(jetztEpochMillis: Long): Long = jetztEpochMillis - RETENTION_MILLIS

    /** Nur Werte im Zeitfenster behalten — bewusst ohne Anzahl-Grenze. */
    fun imZeitfenster(samples: List<HeartRateSample>, jetztEpochMillis: Long): List<HeartRateSample> {
        val untereGrenze = untergrenze(jetztEpochMillis)
        return samples.filter { it.measuredAtEpochMillis in untereGrenze..jetztEpochMillis }
    }
}
