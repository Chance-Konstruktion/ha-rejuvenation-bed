# 🛏️ Rejuvenation Bed

**Intelligente Wasserbett- & Heizmattensteuerung für Home Assistant**

[![HACS Badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![Version](https://img.shields.io/badge/version-0.1.0--rc-blue.svg)](https://github.com/Chance-Konstruktion/ha-rejuvenation-bed/releases)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

🇬🇧 [English Version](README_EN.md)

Verwandelt dein Wasserbett von einer simplen Heizung in eine selbstlernende Schlaf-KI. Biorhythmus-basierte Temperaturkurve, Solar-Nutzung als thermische Batterie, Präsenz-Erkennung durch Wassertemperatur-Varianz, Schwitz-Erkennung und Auto-Kalibrierung – alles kalibriert auf echte Sensordaten.

> ⚠️ **Release Candidate** – Diese Integration wird aktiv auf einem echten 2×2m Dual-Kern Wasserbett getestet. Grundfunktionen sind stabil, einige Features werden noch optimiert.

---

## Was macht die Integration?

Statt stumpf auf eine Temperatur zu heizen, passt Rejuvenation Bed die Wassertemperatur über Nacht an deinen Schlafrhythmus an:

- **Einschlafphase**: Leicht erhöhte Temperatur für Komfort
- **Tiefschlaf**: Absenkung um 1–2°C (fördert Regeneration)
- **Aufwachphase**: Sanftes Erwärmen vor dem Wecker
- **Tagsüber**: Nur Warmhalten wenn nötig, Solar-Überschuss als thermische Batterie nutzen

Das System lernt automatisch die optimalen Schwellwerte für dein spezifisches Bett.

---

## Features

### Kern-Funktionen
- **Biorhythmus-Kurve** – Temperatur folgt dem zirkadianen Rhythmus (Lerche/Normal/Eule)
- **Wecker-Integration** – Aufwachkurve passt sich an Handy-Wecker, feste Zeit oder Hybrid an
- **Saisonale Anpassung** – Sommer kühler, Winter wärmer (via Außentemperatur)
- **Dual-Zone** – Zwei getrennte Heizzonen für Partner mit unterschiedlichem Wärmeempfinden

### Energie-Management
- **Solar-Boost** – Kostenloser PV-Überschuss als thermische Batterie (400kg Wasser!)
- **Tarifmodus** – Bei hohen Strompreisen weniger heizen, bei niedrigen mehr
- **Energie-Tracking** – kWh heute/gesamt, Heizstunden, Ø-Tagesverbrauch
- **Ersparnis vs. Klassisch** – Prozentuale Ersparnis gegenüber Standard-Thermostat

### Sensorik & Intelligenz
- **Präsenz-Erkennung** – Erkennt durch Wassertemperatur-Varianz ob jemand im Bett liegt (kein extra Sensor nötig!)
- **Auto-Kalibrierung** – Lernt in 3–5 Tagen die optimalen Schwellwerte, passt sich saisonal nach
- **Isolations-Erkennung** – Erkennt ob das Bett zugedeckt ist, mit Heizungs-Korrektur (optional, SHT41)
- **Schwitz-Erkennung 2.0** – Kreuzkorrelation Temperatur × Feuchtigkeit
- **Schlaf-Score** – 0–100 Punkte basierend auf Temperaturstabilität, CO₂ und Timing

### Sicherheit
- **Überhitzungsschutz** – Hardware-Limit nie überschritten (max. 36°C)
- **Fail-Safe** – Bei Sensor-Ausfall: Heizung mit 30% Duty-Cycle weiter
- **Startup-Grace-Period** – 3 Minuten Geduld nach HA-Restart für ESP-Sensoren
- **Anti-Short-Cycle** – Verhindert schnelles Ein/Aus-Schalten (Relay-Schutz)
- **Ausreißer-Filter** – Ungültige Sensorwerte (ESP-Glitch) werden ignoriert
- **Leckage-Alarm** – Warnung bei dauerhaft hoher Feuchtigkeit (>3h)

---

## Hardware-Level

Die Integration funktioniert mit unterschiedlich viel Hardware:

| Level | Hardware | Funktionen |
|-------|----------|-----------|
| **A – Basic** | Nur Smart-Plug (Relay) | Zeitschaltuhr, Boost, Urlaub-Modus |
| **B – Smart** | + Leistungssensor | + Energie-Tracking, bessere Präsenz |
| **C – Voll** | + Temperatursensor (DS18B20) | + Biorhythmus, Schlaf-Score, Präsenz via Varianz |
| **C+** | + Feuchtigkeit/Luft-Temp (SHT41) | + Schwitz 2.0, Isolations-Erkennung, Leckage |

**Minimum**: Ein Smart-Plug der die Heizung schaltet. Alles andere ist optional.

---

## Installation

### HACS (empfohlen)

1. HACS öffnen → Integrationen → ⋮ Menü → **Benutzerdefinierte Repositories**
2. URL eintragen: `https://github.com/Chance-Konstruktion/ha-rejuvenation-bed`
3. Kategorie: **Integration**
4. Installieren und Home Assistant neu starten

### Manuell

1. Den Ordner `custom_components/rejuvenation_bed/` in dein HA `config/custom_components/` kopieren
2. Home Assistant neu starten
3. Einstellungen → Geräte & Dienste → Integration hinzufügen → "Rejuvenation Bed"

---

## Konfiguration

Der Setup-Assistent führt durch alle Schritte:

1. **Bett-Typ** – Wasserbett oder Heizmatte
2. **Zonen** – Mono (1 Heizung) oder Dual (2 getrennte Seiten)
3. **Sensoren pro Zone:**
   - Heizungsschalter (Pflicht)
   - Temperatursensor im Wasser (empfohlen, DS18B20)
   - Leistungssensor (optional, vom Smart-Plug)
   - Präsenzsensor (optional, Druckmatte/mmWave)
   - Feuchtigkeitssensor (optional, SHT41)
   - Oberflächentemperatur oben (optional, SHT41)
4. **Globale Einstellungen:**
   - Warm ab / Warm bis (Schlafenszeit)
   - Wecker-Entity (Handy-Alarm)
   - Chronotyp (Lerche/Normal/Eule)
   - Solar-/Strompreis-Sensor
   - Außentemperatur
5. **Energie-Tracking** – Verbrauch, Ersparnis, Vergleich mit Standard-Thermostat

Alle Einstellungen sind nachträglich über den Options-Flow änderbar.

---

## Entities

### Climate
| Entity | Beschreibung |
|--------|-------------|
| `climate.rejuvenation_bed` | Haupt-Thermostat (Zieltemperatur, HVAC-Modus) |

### Sensoren
| Entity | Beschreibung |
|--------|-------------|
| `sensor.bett_zieltemperatur` | Aktuelle berechnete Zieltemperatur |
| `sensor.bett_status` | Aktueller Modus und Entscheidungsgrund |
| `sensor.bett_gesamtleistung` | Aktuelle Leistung in Watt |
| `sensor.bett_energie_gesamt` | Gesamtenergie seit Installation (kWh) |
| `sensor.bett_energie_heute` | Heutiger Verbrauch (kWh) |
| `sensor.bett_thermal_summary` | Temperatur-Berechnung aufgeschlüsselt (Kurve + Offsets) |
| `sensor.bett_intelligence` | Kalibrierungsstatus (Lernphase X% / Kalibriert) |

### Binäre Sensoren
| Entity | Beschreibung |
|--------|-------------|
| `binary_sensor.bett_prasenz` | Person im Bett erkannt |
| `binary_sensor.bett_schwitzerkennung` | Schwitz-/Nässe-Alarm |
| `binary_sensor.bett_isolation` | Bett zugedeckt (braucht SHT41) |
| `binary_sensor.bett_system_status` | Systemgesundheit (Watchdog) |

### Schalter
| Entity | Beschreibung |
|--------|-------------|
| `switch.bett_boost` | Schnellheizen ein/aus |
| `switch.bett_krank_modus` | Krank-Modus ein/aus |
| `switch.bett_solar_batterie` | Thermische Batterie ein/aus |
| `switch.bett_eco_modus` | Tarifmodus ein/aus |

---

## Architektur

```
coordinator.py ─── Zentraler 30s-Loop
 ├── safety_manager.py ──────── Überhitzungsschutz, Fail-Safe
 ├── temperature_calculator.py ─ Biorhythmus-Kurve, Zieltemperatur
 │   ├── biorhythmus_curve.py ── Schlafphasen-Kurve (Chronotyp)
 │   ├── wake_time_resolver.py ─ Wecker/Fest/Hybrid
 │   └── sleep_stage_resolver.py Wearable-Anbindung
 ├── energy_state_resolver.py ── Solar/Tarif/Normal-Modus
 ├── energy_calculator.py ────── Verbrauchs-Berechnung
 ├── presence_detector.py ────── Varianz-basierte Präsenz
 ├── bed_intelligence.py ─────── Auto-Kalibrierung, Isolation 2.0, Schwitz 2.0
 ├── diagnostics_manager.py ──── Energie-Budget, Thermal Summary
 ├── ramp_controller.py ──────── Aufheiz-Rampe (Vinyl-Schutz)
 ├── anti_short_cycle_manager.py Relay-Schutz
 └── sleep_score_calculator.py ─ Schlaf-Bewertung 0-100
```

22 Module · ~9.500 Zeilen Python · Bilingual (DE/EN) · HACS-kompatibel

---

## Sonder-Modi

| Modus | Aktivierung | Wirkung |
|-------|------------|---------|
| **Boost** | `switch.bett_boost` | Schnellheizen auf 32–34°C für 60 Min (umgeht Anti-Short-Cycle) |
| **Krank** | `switch.bett_krank_modus` | Konstant 30–32°C für konfigurierbare Tage |
| **Urlaub** | Service `rejuvenation_bed.set_vacation` | Minimale 24°C Haltetemperatur |
| **Solar** | `switch.bett_solar_batterie` | PV-Überschuss als Wärme speichern |
| **Eco** | `switch.bett_eco_modus` | Bei teuerem Strom weniger heizen |

---

## Auto-Kalibrierung & Nachkalibrierung

Beim ersten Start geht die Integration in den **Lernmodus**:

- Sammelt Wassertemperatur-Varianz bei leerem und belegtem Bett
- Sammelt Feuchtigkeits-Baseline und Isolations-Delta
- Nach ~3–5 Tagen (300 Samples): Schwellwerte werden berechnet
- **Ausreißer-Filter**: ESP-Glitches und Sensor-Boot-Werte werden ignoriert

Nach der Erstkalibierung läuft die **Drift-Korrektur** weiter:
- Alle 500 Samples werden die Schwellwerte sanft angepasst (15% neue Daten)
- Passt sich automatisch an Sommer/Winter an
- Kein manuelles Rekalibrieren nötig

Status sichtbar im Sensor `sensor.bett_intelligence`.

---

## FAQ

**Brauche ich einen Temperatursensor im Wasser?**
Nein, aber empfohlen. Ohne Sensor läuft das System als intelligente Zeitschaltuhr (Level A).

**Welchen Temperatursensor?**
DS18B20 wasserdicht (für IM Wasser) + optional SHT41 (für OBEN auf dem Kern).

**Was passiert bei HA-Restart?**
3 Minuten Startup-Grace-Period – kein Fehlalarm während ESP-Sensoren booten. Kalibrierungsdaten und Energiezähler bleiben erhalten.

**Was zeigt der Thermal Summary Sensor?**
Die komplette Temperatur-Berechnung aufgebrochen: Basis-Kurve, Energie-Offset, Schlafphasen-Offset, aktive Phase, Boost-Status. Quasi "Warum ist die Zieltemperatur gerade X?"

---

## Lizenz

MIT License – siehe [LICENSE](LICENSE)

---

*Gebaut mit echten Sensordaten aus einem 2×2m Dual-Kern Wasserbett. Kalibriert auf 126.771 Datenpunkte.*
