# 🛏️ Rejuvenation Bed

**Intelligente Wasserbett- & Heizmattensteuerung für Home Assistant**

[![HACS Badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![Version](https://img.shields.io/badge/version-0.3.2-blue.svg)](https://github.com/Chance-Konstruktion/ha-rejuvenation-bed/releases)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Verwandelt dein Wasserbett von einer simplen Heizung in eine selbstlernende Schlaf-KI. Biorhythmus-basierte Temperaturkurve, Solar-Nutzung als thermische Batterie, Präsenz-Erkennung durch Wassertemperatur-Varianz, Schwitz-Erkennung und Auto-Kalibrierung – alles aus echten Sensordaten.

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
- **Wecker-Integration** – Aufwachkurve passt sich an Handy-Wecker oder feste Zeit an
- **Saisonale Anpassung** – Sommer kühler, Winter wärmer (via Außentemperatur)
- **Dual-Zone** – Zwei getrennte Heizzonen für Partner mit unterschiedlichem Wärmeempfinden

### Energie-Management
- **Solar-Boost** – Kostenloser PV-Überschuss als thermische Batterie (400kg Wasser!)
- **Tarifmodus** – Bei hohen Strompreisen weniger heizen, bei niedrigen mehr
- **Energie-Tracking** – kWh heute/gesamt, Heizstunden, Ø-Tagesverbrauch
- **Ersparnis vs. Klassisch** – Prozentuale Ersparnis gegenüber Standard-Thermostat

### Sensorik & Intelligenz (v0.3.0+)
- **Präsenz-Erkennung** – Erkennt durch Wassertemperatur-Varianz ob jemand im Bett liegt (kein extra Sensor nötig!)
- **Auto-Kalibrierung** – Lernt in 3–5 Tagen die optimalen Schwellwerte für dein Bett
- **Isolations-Erkennung** – Erkennt ob das Bett zugedeckt ist (optional, mit SHT41)
- **Schwitz-Erkennung 2.0** – Kreuzkorrelation Temperatur × Feuchtigkeit
- **Schlaf-Score** – 0–100 Punkte basierend auf Temperaturstabilität, CO₂ und Timing

### Sicherheit
- **Überhitzungsschutz** – Hardware-Limit nie überschritten (max. 36°C)
- **Fail-Safe** – Bei Sensor-Ausfall: Heizung mit 30% Duty-Cycle weiter
- **Anti-Short-Cycle** – Verhindert schnelles Ein/Aus-Schalten (Relay-Schutz)
- **Leckage-Alarm** – Warnung bei dauerhaft hoher Feuchtigkeit (>3h)
- **Kondensationswarnung** – Warnt wenn Wassertemp unter 24°C fällt

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

Die Integration erstellt automatisch folgende Entities:

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
| `sensor.bett_o_tagesverbrauch` | Durchschnittlicher Tagesverbrauch |
| `sensor.bett_heizstunden` | Gesamte Heizstunden |
| `sensor.bett_ersparnis_vs_klassisch` | Prozent Ersparnis vs. Standard-Thermostat |
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
 ├── bed_intelligence.py ─────── Auto-Kalibrierung, Isolation, Schwitz 2.0
 ├── diagnostics_manager.py ──── Energie-Budget, persistenter Speicher
 ├── ramp_controller.py ──────── Aufheiz-Rampe (Wasserbett)
 ├── anti_short_cycle_manager.py Relay-Schutz
 └── sleep_score_calculator.py ─ Schlaf-Bewertung 0-100
```

22 Module · ~9.400 Zeilen Python · Bilingual (DE/EN) · HACS-kompatibel

---

## Sonder-Modi

| Modus | Aktivierung | Wirkung |
|-------|------------|---------|
| **Boost** | `switch.bett_boost` | Schnellheizen auf 32–34°C für 30 Min |
| **Krank** | Service `rejuvenation_bed.set_sick_mode` | Konstant 30–32°C für 1–14 Tage |
| **Urlaub** | Service `rejuvenation_bed.set_vacation` | Minimale 24°C Haltetemperatur |
| **Solar** | `switch.bett_solar_batterie` | PV-Überschuss als Wärme speichern |
| **Eco** | `switch.bett_eco_modus` | Bei teuerem Strom weniger heizen |

---

## Auto-Kalibrierung

Beim ersten Start geht die Integration in den **Lernmodus**. Sie misst automatisch:

- Wassertemperatur-Varianz bei leerem und belegtem Bett
- Feuchtigkeits-Baseline
- Temperatur-Delta zwischen Wasser und Oberfläche

Nach ~3–5 Tagen normaler Nutzung (ca. 300 Samples) sind die Schwellwerte kalibriert. Der Status ist im Sensor `sensor.bett_intelligence` sichtbar:

- `Lernphase (67%)` → Sammelt noch Daten
- `Kalibriert` → Schwellwerte optimiert

Die Kalibrierungsdaten überleben HA-Neustarts.

---

## FAQ

**Brauche ich einen Temperatursensor im Wasser?**  
Nein, aber empfohlen. Ohne Sensor läuft das System als intelligente Zeitschaltuhr (Level A). Mit Sensor gibt es Biorhythmus, Schlaf-Score und Präsenz-Erkennung.

**Welchen Temperatursensor?**  
DS18B20 wasserdicht (für IM Wasser) + optional SHT41 (für OBEN auf dem Kern).

**Funktioniert es auch mit Heizmatten?**  
Ja. Heizmatten reagieren schneller als Wasserbetten, die Rampen sind entsprechend kürzer.

**Was passiert bei HA-Absturz?**  
Die physische Sicherheitsgrenze des Hersteller-Thermostats greift. Die Integration empfiehlt, den Hardware-Regler auf Maximum zu stellen und die Begrenzung der Software zu überlassen.

**Resettet sich die Energie bei Neustarts?**  
Nein, seit v0.2.3 werden alle Zähler persistent gespeichert.

---

## Lizenz

MIT License – siehe [LICENSE](LICENSE)

---

*Gebaut mit echten Sensordaten aus einem 2×2m Dual-Kern Wasserbett. Kalibriert auf 126.771 Datenpunkte.*
