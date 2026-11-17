package net.schanz.rejuvenationbed.watch.ha

/**
 * Die zwei Stellungen des Schalters „Was geht an Home Assistant“.
 *
 * Beide Stellungen senden ausschließlich über den lokalen Webhook der eigenen
 * Home-Assistant-Instanz (`local_only`) — nie Cloud, nie ein fremder Dienst.
 * Der Unterschied ist nur die TIEFE:
 *
 * - [PHASE_ONLY] (Standard): die Rohdaten bleiben auf der Uhr; an HA geht das
 *   Ergebnis — die laufende Phase, die Phasen-Zeitleiste und die Zusammen-
 *   fassungen (Puls min/Ø/max, HRV aus IBI, Schritte gesamt).
 * - [GESAMTDATEN]: zusätzlich alle Messreihen der Nacht — Puls, IBI (wenn eine
 *   Quelle vorhanden ist), Bewegungsfenster und Plattform-Schlafstatus — je
 *   5 Minuten ein Paket, mit Wiederholung, ohne Doppelung (Zeitstempel als
 *   Schlüssel).
 *
 * Kanäle, die die Uhr nicht wirklich liefert, werden nie erfunden: Atemfrequenz,
 * SpO2 und Hauttemperatur stehen in keiner Stellung in der Nutzlast. HA kennt
 * diese Grenze und zeigt die Werte als „nicht verfügbar“ mit Grund.
 */
enum class HaUebertragungModus(
    val wireValue: String,
    val anzeige: String,
    val kurzeBeschreibung: String,
    /** Für den Umschalt-Hinweis: was bei dieser Stellung übertragen wird. */
    val uebertrageneWerte: List<String>,
    /** Ehrlich: was in dieser Stellung NICHT übertragen wird. */
    val nichtUebermittelt: List<String>
) {
    PHASE_ONLY(
        "phase_only",
        "Nur Schlafphase",
        "Rohdaten bleiben auf der Uhr — HA bekommt nur das Ergebnis.",
        listOf(
            "die laufende Phase während der Messung",
            "Phasen-Zeitleiste der Nacht mit Quelle je Segment",
            "Puls min/Ø/max und Abdeckung (Zusammenfassung)",
            "HRV-Kennzahlen aus IBI (Zusammenfassung) oder fehlt mit Grund",
            "Schritte gesamt"
        ),
        listOf(
            "Puls-Reihe (je Messpunkt)",
            "IBI-Reihe",
            "Bewegungsfenster",
            "Plattform-Schlafstatus-Reihe"
        )
    ),
    GESAMTDATEN(
        "gesamtdaten",
        "Gesamtdaten",
        "zusätzlich alle Messreihen der Nacht, je 5 Minuten ein Paket.",
        listOf(
            "alles aus „Nur Schlafphase“",
            "Puls-Reihe (je Messpunkt)",
            "IBI-Reihe, wenn eine Quelle vorhanden ist",
            "Bewegungsfenster (Schritte je Intervall)",
            "Plattform-Schlafstatus-Reihe"
        ),
        listOf(
            "Atemfrequenz, SpO2, Hauttemperatur — die Uhr stellt diese Kanäle nicht bereit"
        )
    );

    companion object {
        /** Standard ist bewusst die enge Stellung: nichts Neues ohne Antwort. */
        fun standard(): HaUebertragungModus = PHASE_ONLY

        /** Aus dem Nutzlast-Feld oder der Speicherung; Unbekanntes fällt zurück auf Standard. */
        fun aus(wireValue: String?): HaUebertragungModus =
            entries.firstOrNull { it.wireValue == wireValue } ?: standard()
    }
}
