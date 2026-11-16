# Nachtbericht — die Schlafaufzeichnung der Uhr in Home Assistant

Die Galaxy-Watch-App (`watch/`) zeichnet die Nacht lokal auf: Puls, Bewegung,
Plattform-Schlafstatus und — wenn eine Quelle vorhanden ist — IBI. Der
Nachtbericht ist der Weg, mit dem diese Aufzeichnung vollständig in
Rejuvenation Bed ankommt: Sensoren für Automationen, ein Ereignis je Nacht und
eine Karte mit Hypnogramm, Pulskurve und 7-Nächte-Vergleich.

Hausregel, durchgezogen: **Gesundheitsdaten bleiben im Haus.** Keine Cloud,
kein fremder Dienst, kein Log-Eintrag mit Messwerten. Es gibt nur den lokalen
Annahme-Pfad und den Home-Assistant-Speicher.

## Wie die Daten ankommen

Die Integration registriert bei der Einrichtung einen Home-Assistant-Webhook —
**nur lokal erreichbar** (`local_only=True`). Wo der Endpunkt hängt, steht im
Sensor „Bett Nachtbericht“ als Attribut `annahme_pfad` — absichtlich als
relativer Pfad (`/api/webhook/…`) ohne Adresse; die eigene Home-Assistant-URL
setzt man davor. Der Absender postet JSON:

- `type: "night_report"` — eine abgeschlossene Nacht, vollständig.
- `type: "phase_update"` — die laufende Phase, während sie gemessen wird.

Ein Dauer-Bearer-Token gibt es bewusst nicht; das ist der lokale Vorläufer der
Pairing-Strecke aus M3 (`SMARTWATCH_ARCHITECTURE.md`), die den Endpunkt später
übernehmen kann, ohne dass sich hier etwas ändert. Der Sender auf der Uhr bzw.
dem Telefon ist ein eigener Schritt und Teil dieses MR nicht — bis dahin
zeigen die Sensoren `unknown`, was zutreffend ist: Es ist noch nichts
angekommen.

## Schema `rejuvenation-bed-night-report-v1`

```jsonc
{
  "schema": "rejuvenation-bed-night-report-v1",
  "type": "night_report",
  "night": "2026-11-15",                    // Nacht-Kennung, Datum des Beginns
  "start": "2026-11-15T23:10:00+01:00",     // Beginn der Nacht
  "end":   "2026-11-16T07:42:00+01:00",     // Ende der Nacht
  "device": "galaxy-watch-4",               // frei, nur Anzeige

  "phases": [                               // Phasen-Zeitleiste, optional
    {
      "stage": "deep",                      // awake | light | deep | rem
      "start": "…", "end": "…",
      "source": "estimate",                 // platform | estimate | estimate-ibi | external
      "confidence": 0.8,                    // 0..1, Güte der Schätzung
      "coverage": 0.9,                      // 0..1, Datenabdeckung des Segments
      "algorithm": "puls-bewegung-grob-0.1" // Version des Schätzers
    }
  ],

  "pulse": {                                // optional
    "min": 48, "mean": 56, "max": 74,       // fehlen die Aggregate, werden sie
                                            // aus den Samples zusammengefasst
    "coverage": 0.94,
    "samples": [ {"t": "…", "bpm": 55} ]    // HA verdichtet selbst auf ≤ 240 Punkte
  },

  "ibi": [ {"t": "…", "interval_ms": 1020, "quality": 0.9} ],  // optional, roh
  "hrv": { "rmssd": 42.5, "sdnn": 58.0, … },                   // optional, aggregiert

  "movement": {                             // optional
    "steps_total": 41,
    "windows": [ {"t": "…", "steps": 12} ],
    "variance": null
  },

  "interruptions": [ {"start": "…", "end": "…", "reason": "…"} ]  // optional
}
```

Regeln der Annahme:

- Fehlt eine Quelle, steht das **benannt** im Bericht (`fehlend`) — es wird
  nie ein Wert aus etwas anderem gerechnet. Insbesondere gilt: **HRV kommt nur
  aus IBI.** Aus dem Puls wird nichts abgeleitet.
- Rohe IBI (bevorzugt) werden hier mit denselben Grenzen gerechnet wie der
  Schätzer auf der Uhr (`SleepHrvExtractor`): 300–2000 ms plausibel,
  Signalqualität als Untergrenze, Artefakte gegen den Vorgänger verworfen. Erst
  ab 120 brauchbaren Intervallen heißt es „Wert“ — darunter „fehlt“, mit Grund.
  Kommen statt roher IBI nur aggregierte HRV-Werte, werden sie als
  „vom Absender gemeldet“ übernommen und so beschriftet.
- Phasen-Segmente werden gestutzt und überlappungsfrei geordnet; jede Nacht-
  minute zählt genau einmal. Was keine Phase abdeckt, ist **Lücke** — sie wird
  gezählt und im Hypnogramm als eigenes Band gezeigt, nie als Schlaf.
- Wurden keine Unterbrechungen gemeldet, werden die Wach-Segmente in der
  Nachtmitte als Unterbrechungen abgeleitet — Herkunft wird gekennzeichnet
  („aus der Phasen-Zeitleiste abgeleitet“), Rand-Wachphasen zählen als
  Ein- und Ausschlafen, nicht als Unterbrechung.
- `source: "estimate"` bleibt überall sichtbar: pro Segment, im Bericht, auf
  der Karte („grobe Schätzung“, gestrichelt im Hypnogramm).

### Laufende Phase

```jsonc
{
  "schema": "rejuvenation-bed-night-report-v1",
  "type": "phase_update",
  "stage": "deep",
  "confidence": 0.8, "coverage": 0.9,
  "measured_at": "2026-11-16T01:30:00+01:00",  // MUSS mit Offset kommen
  "source": "estimate",
  "algorithm": "puls-bewegung-grob-0.1"
}
```

Ohne Offset wird die Annahme abgelehnt: „veraltet“ ist ohne Zone nicht
entscheidbar. Nach 10 Minuten ohne Nachschub fällt der Phase-Sensor auf
`unknown` zurück — dieselbe Grenze wie `SleepPredictionWire` auf der Uhr.
Automationen, die das Bett schalten, lesen dann `unknown` und die Kurve läuft
weiter, statt auf eine alternde Schätzung zu reagieren.

## Sensoren

| Entity | Inhalt |
| :--- | :--- |
| `sensor.bett_schlafphase` | Lauffende Phase (`awake/light/deep/rem/unknown`) mit Quelle, Konfidenz, Algorithmus — der Sensor für Automationen |
| `sensor.bett_schlafdauer` | Dauer der letzten Nacht (h) |
| `sensor.bett_tiefschlaf_anteil`, `…_leichtschlaf_anteil`, `…_rem_anteil`, `…_wach_anteil` | Anteile je Phase (%) |
| `sensor.bett_ruhepuls` | Puls-Ø der Nacht (bpm), min/max/Abdeckung als Attribute |
| `sensor.bett_hrv` | RMSSD aus IBI (ms); fehlt die Quelle: `unknown` + Grund im Attribut |
| `sensor.bett_schlafbeginn`, `sensor.bett_schlafende` | Zeitstempel der Nacht |
| `sensor.bett_schlafunterbrechungen` | Anzahl; Minuten und Herkunft als Attribute |
| `sensor.bett_nachtgute` | Güte der **Messung** (0–100): Abdeckung × Konfidenz — nicht der Schlaf-Score |
| `sensor.bett_nachtbericht` | der ganze Bericht (Karte liest ihn hier) mit 7-Nächte-Vergleich und `annahme_pfad` |

Alle Sensoren hängen am Gerät „Bett Schlaf/Analyse“ und existieren ab Einrichtung
— ohne Daten zeigen sie `unknown` statt zu fehlen, damit man am Zustand sieht,
dass noch nichts angekommen ist.

## Ereignis

Je angenommener Nacht feuert die Integration das Ereignis
`rejuvenation_bed_nacht_abgeschlossen` mit einer Kurzfassung: Nacht, Dauer,
Güte, Tief-/REM-Anteil, Ruhepuls, HRV, Quellen, `ist_schaetzung` und die
Fehlliste. Automationen können darauf reagieren (z. B. morgens eine Zusammen-
fassung schicken) — ohne dass die Messwerte im Log landen.

## Karte

`custom:rejuvenation-night-report` wird von der Integration selbst ausgeliefert
und registriert — kein Kopieren nach `/config/www`, keine Ressource von Hand.
Sie findet den Bericht-Sensor selbst (Attribut-Marker) und bietet, wie in der
Hausregel für Karten, **Tabs oben** („Übersicht“ / „Verlauf“) — auf kleinen
Schirmen wandern sie unter den Inhalt.

```yaml
views:
  - type: panel
    cards:
      - type: custom:rejuvenation-night-report
```

Inhalt:

- **Übersicht** — Kennzahlen (Dauer, Beginn/Ende, Puls min/Ø/max, HRV oder
  „fehlt: …“, Unterbrechungen, Bewegung), Phasen-Anteile als Balken,
  **Hypnogramm** (SVG; grob geschätzte Segmente gestrichelt umrandet),
  **Pulskurve** (SVG, verdichtet), Hinweise zu Quellen und fehlenden Werten.
- **Verlauf** — Schlafdauer und Messgüte der letzten Nächte (bis 7), Nächte
  aus der groben Schätzung markiert.

Fehlt eine Quelle, steht es als eigener Kasten im Bericht — nie eine Ersatzzahl.
Empty state: „Noch keine Nacht übermittelt“ samt Annahme-Pfad.

## Datenschutz

- Der Webhook ist `local_only` — Anfragen aus dem Internet bleiben ohne Wirkung.
- Messwerte liegen im Home-Assistant-Speicher (`.storage/`) und in den
  Sensoren; die gespeicherten Nächte sind auf 14 begrenzt (7 für den Vergleich,
  Puffer für versäumtes Senden).
- Kein Log schreibt Messwerte. Die Protokollzeilen nennen Nacht-Datum, Dauer,
  Güte und Quellen — keine Puls-, IBI- oder HRV-Werte.
- Die Uhr selbst behält ihre Rohdaten lokal (`watch/README.md`); der Nacht-
  bericht ist die einzige Kopie, und sie bleibt im Haus.

## Grenzen (ehrlich)

- Der Sender (Uhr/Telefon → HA) ist noch nicht gebaut — M2/M3 liegen bei der
  Watch-App; bis dahin liefern nur Tests und ein eigener Aufruf Daten.
- Die Güte misst die **Messung**, nicht den Schlaf. Ein Schlaf-Score aus den
  Uhrdaten wäre Raten; das bleibt den bewährten temperaturbasierten
  Schlaf-Score-Sensoren vorbehalten.
- Phasen aus der groben Schätzung sind Hypothesen mit Ansage — die Karte
  schreibt das dazu, die Automation-Logik (Temperatur-Modifikator) bleibt im
  bestehenden `SleepStageResolver` und seinen Grenzen.
