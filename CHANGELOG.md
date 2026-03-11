# Changelog

Alle Änderungen am Rejuvenation Bed Projekt.

## [0.4.2] - 2026-03-06

### Neue Features
- **Thermische Batterie** – Neuer Sensor `sensor.bett_thermische_batterie` zeigt den Ladezustand des Wärmespeichers in Prozent und kWh. Basiert auf Wassertemperatur, Volumen und physikalischer Wärmekapazität.
- **Bett-Volumen** – Konfigurierbarer Slider (100–1200 L) unter Zeiten & Temperatur. Fließt in Batterie- und Aufheiz-Berechnung ein.
- **Drei Geräte** – Sensoren sind jetzt auf drei Devices aufgeteilt: Hauptgerät (Climate, Status, Schalter), Energie (Verbrauch, Solar, Ersparnis, Batterie) und Schlaf (Score, Vorhersage, Intelligenz).
- **Bedtime Learning** – System lernt wann du typisch einschläfst und passt die Vorheizzeit automatisch an. Unterscheidet Wochentag und Wochenende, nutzt Median statt Durchschnitt. Neuer Sensor `sensor.bett_einschlafzeit_vorhersage`.
- **Solar-Schwelle konfigurierbar** – Slider 100–2000 W statt fester 500 W. Bei Doppelbett mit 600 W Heizleistung auf 600 W oder höher einstellen.
- **Strompreis einstellbar** – Fester Tarif (5–80 ct/kWh) als Fallback und für Ersparnis-Berechnung. Dynamischer Preis-Sensor überschreibt ihn bei Verfügbarkeit.
- **Options-Reload** – Änderungen in den Einstellungen laden die Integration automatisch neu. CO₂-Sensor nachträglich hinzufügen erstellt jetzt sofort die Schlaf-Score-Sensoren.

### Bugfixes
- **Sensor-Recovery** – Fail-Safe und Degraded-Modus setzen jetzt `hvac_mode: heat`. Bei Sensor-Rückkehr wird `manual_hvac_mode` automatisch gelöscht.
- **Präsenz-Erkennung** – Heizungs-Zyklen erzeugten ±0.06°C Oszillation die als Präsenz gewertet wurde. Schwellwert wird jetzt bei aktiver Heizung um Faktor 1.8 angehoben.
- **Vorheizen mit Präsenz-Sensor** – Vorheizen fehlte im Präsenz-Pfad. Jetzt auch dort 3 Stunden vor dem Warmfenster.
- **Boost relativ** – Boost nutzt jetzt `base_temp + offset` statt absolutem Wert. Safety-Cap bei 36°C.
- **CO₂-Sensor** – Aus Zone-Sensoren nach Global verschoben. Rückwärtskompatibel: Zone → Options → Global.
- **Toilettengang-Timeout** – Vor Weckzeit kein Timeout mehr (Kurve läuft weiter). Nach Weckzeit 5 Minuten Timeout.
- **Abkühlrampe** – Keine Rampe mehr beim Abkühlen. Heizung geht sofort aus, Wasser kühlt durch Wärmeverlust von selbst. Rampe nur noch beim Aufheizen (Vinyl-Schutz).
- **Bedtime Learning** – Nacht-Datum statt Kalender-Datum (4:30 am 5.März = Nacht vom 4.März). Tagsüber-Präsenz wird nicht mehr aufgezeichnet.

### Sensor-Robustheit
- **Feature-Flag-Reset** – Wenn SHT41 ausfällt, wird `_has_air_temp` auf False zurückgesetzt. Isolation und Schwitz-Erkennung deaktivieren sich, Kernfunktion läuft weiter.
- **None-Guards** – Alle BedIntelligence-Funktionen prüfen am Anfang ihre Inputs.
- **try/except** – Präsenz-Erkennung, BedIntelligence und Leak-Check sind gewrappt. Ein Crash dort legt nie die Heizung lahm.

### Options-Flow überarbeitet
- Sub-Menü für Globale Einstellungen: Zeiten & Temperatur / Sensoren & Strompreis.
- Jeder Sensor hat eine ausführliche Beschreibung in der Step-Description.
- Keine verwaisten Translation-Keys mehr. DE, EN und strings.json synchron.
- Biorhythmus-Phasen optimiert: Einschlaf 15→8%, Tiefschlaf 50→55%.

## [0.1.0-rc] - 2026-02-21

### Erstveröffentlichung (Release Candidate)
Erster öffentlicher Release. 22 Module, ~9.500 Zeilen Python. Biorhythmus-Kurve, Solar-Boost, Präsenz-Erkennung, Auto-Kalibrierung, Schlaf-Score, Dual-Zone, bilingual (DE/EN).
