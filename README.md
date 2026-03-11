# 🛏️ Rejuvenation Bed

**Intelligente Bett-Heizungssteuerung für Home Assistant**

[![HACS Badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![Version](https://img.shields.io/badge/version-0.5.0-blue.svg)](https://github.com/Chance-Konstruktion/ha-rejuvenation-bed/releases)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

🇬🇧 [English Version](README_EN.md)

Verwandelt jede Bett-Heizung in eine selbstlernende "Schlaf-KI". Biorhythmus-basierte Temperaturkurve, Solar-Nutzung als thermische Batterie, Präsenz-Erkennung und Auto-Kalibrierung. Funktioniert mit Wasserbetten, Heizmatten und beheizbaren Matratzenauflagen.

---

## Was macht die Integration?

Statt stumpf auf eine Temperatur zu heizen, passt Rejuvenation Bed die Temperatur über Nacht an deinen Schlafrhythmus an:

- **Einschlafphase** – Leicht erhöhte Temperatur für Komfort
- **Tiefschlaf** – Absenkung um 1–2°C für optimale Regeneration
- **Aufwachphase** – Sanftes Erwärmen vor dem Wecker
- **Tagsüber** – Standby, Solar-Überschuss als Wärme speichern

Das System lernt automatisch deine Einschlafzeit und die optimalen Schwellwerte für dein Bett.

---

## Features

**Kern-Funktionen** – Biorhythmus-Kurve mit Chronotyp-Anpassung (Lerche/Normal/Eule), Wecker-Integration (Handy-Alarm, feste Zeit oder Hybrid), saisonale Anpassung via Außentemperatur, Dual-Zone für Partner.

**Energie-Management** – Solar-Boost nutzt PV-Überschuss als thermische Batterie. Dynamische Strompreise (Tibber, aWATTar, ENTSO-E). Energie-Tracking mit kWh, Heizstunden und Ersparnis-Berechnung. Thermische Batterie als Prozent-Sensor.

**Intelligenz** – Präsenz-Erkennung durch Wassertemperatur-Varianz (kein extra Sensor nötig). Auto-Kalibrierung in 3–5 Tagen. Isolations-Erkennung (Bett zugedeckt?). Schwitz-Erkennung per Kreuzkorrelation. Schlaf-Score 0–100. Einschlafzeit-Vorhersage mit lernbasiertem Vorheizen.

**Sicherheit** – Überhitzungsschutz (max 36°C), Fail-Safe bei Sensor-Ausfall, Startup-Grace-Period, Anti-Short-Cycle, Ausreißer-Filter, Leckage-Alarm. Optionale Sensoren können jederzeit ausfallen ohne die Kernfunktion zu beeinträchtigen.

---

## Hardware-Level

| Level | Hardware | Funktionen |
|-------|----------|-----------|
| **A** | Smart-Plug | Zeitschaltuhr, Boost, Urlaub |
| **B** | + Temperatursensor | + Biorhythmus, Präsenz, Schlaf-Score |
| **C** | + Leistungssensor | + Energie-Tracking, bessere Präsenz |
| **D** | + SHT41 (Luft/Feuchte) | + Isolations-Check, Schwitzerkennung, Leckage |

Minimum: Ein Smart-Plug der die Heizung schaltet.

---

## Installation

### HACS (empfohlen)

1. HACS → Integrationen → ⋮ → Benutzerdefinierte Repositories
2. URL: `https://github.com/Chance-Konstruktion/ha-rejuvenation-bed`
3. Kategorie: Integration
4. Installieren → Home Assistant neu starten

### Manuell

`custom_components/rejuvenation_bed/` nach `config/custom_components/` kopieren, HA neu starten, Integration hinzufügen.

---

## Konfiguration

Der Setup-Assistent führt durch alle Schritte. Danach sind vier Bereiche über den Options-Flow erreichbar:

**🌐 Globale Einstellungen** – Aufgeteilt in Zeiten & Temperatur (Warmhalte-Fenster, Sommer-Schwelle, Offset, Bett-Volumen) und Sensoren & Strompreis (Solar, Preis-Sensor, Festtarif, CO₂).

**📡 Zonen-Sensoren** – Hardware pro Zone: Heizungsschalter (Pflicht), Temperatursensor, Leistungssensor, Präsenzsensor, Feuchtigkeitssensor, Oberflächentemperatur.

**🌡️ Schlaf-Profil** – Pro Zone: Wecker-Entity, Wochenend-Ausschlafen, Schlaf-Temperaturen (leer = saisonal automatisch), Wearable-Sensor.

**🎛️ Sondermodi** – Krank (Temperatur, Dauer), Boost (Offset), Urlaub (Haltetemperatur), Komfort (Ausschlafen-Offset).

---

## Geräte & Entities

Die Integration erstellt drei Geräte in Home Assistant:

### 🛏️ Rejuvenation Bed (Hauptgerät)

| Entity | Beschreibung |
|--------|-------------|
| `climate.rejuvenation_bed` | Thermostat mit Zieltemperatur und HVAC-Modus |
| `sensor.bett_zieltemperatur` | Berechnete Zieltemperatur |
| `sensor.bett_status` | Aktueller Modus und Entscheidungsgrund |
| `sensor.bett_thermal_summary` | Temperatur-Berechnung aufgeschlüsselt |
| `sensor.bett_rampe` | Aufheiz-Rampe Status |
| `binary_sensor.bett_prasenz` | Person im Bett |
| `binary_sensor.bett_isolation` | Bett zugedeckt (braucht SHT41) |
| `binary_sensor.bett_schwitzen` | Schwitz-/Nässe-Alarm |
| `switch.bett_boost` | Schnellheizen |
| `switch.bett_krank_modus` | Krank-Modus |
| `switch.bett_solar_batterie` | Thermische Batterie |
| `switch.bett_eco_modus` | Tarifmodus |

### ⚡ Bett Energie

| Entity | Beschreibung |
|--------|-------------|
| `sensor.bett_thermische_batterie` | Ladezustand des Wärmespeichers (%) |
| `sensor.bett_energie_heute` | Verbrauch heute (kWh) |
| `sensor.bett_gesamtleistung` | Aktuelle Leistung (W) |
| `sensor.bett_heizstunden` | Heizstunden heute |
| `sensor.bett_ersparnis` | Geschätzte Ersparnis (€) |
| `sensor.bett_solar_prozent` | Solar-Anteil am Verbrauch |
| `sensor.bett_strompreis_status` | Aktueller Tarif-Modus |

### 😴 Bett Schlaf

| Entity | Beschreibung |
|--------|-------------|
| `sensor.bett_schlaf_score` | Letzte Nacht (0–100) |
| `sensor.bett_schlaf_score_woche` | Wochendurchschnitt |
| `sensor.bett_intelligence` | Kalibrierung und Lernstatus |

---

## Sondermodi

| Modus | Aktivierung | Wirkung |
|-------|------------|---------|
| **Boost** | `switch.bett_boost` | Schnellheizen: Zieltemperatur + Offset für 60 Min |
| **Krank** | `switch.bett_krank_modus` | Konstante Temperatur für konfigurierbare Tage |
| **Urlaub** | HVAC-Modus "away" | Minimale 24°C Haltetemperatur |
| **Solar** | `switch.bett_solar_batterie` | PV-Überschuss als Wärme speichern |
| **Eco** | `switch.bett_eco_modus` | Bei teuerem Strom Temperatur senken |

---

## Architektur

```
coordinator.py ─── Zentraler 30s-Loop
 ├── safety_manager.py ──────── Überhitzungsschutz, Fail-Safe
 ├── temperature_calculator.py ─ Biorhythmus-Kurve, Zieltemperatur
 │   ├── biorhythmus_curve.py ── Schlafphasen-Kurve (Chronotyp)
 │   ├── wake_time_resolver.py ─ Wecker / Fest / Hybrid
 │   └── sleep_stage_resolver.py Wearable-Anbindung
 ├── energy_state_resolver.py ── Solar / Tarif / Normal-Modus
 ├── presence_detector.py ────── Varianz-basierte Präsenz
 ├── bed_intelligence.py ─────── Kalibrierung, Isolation, Schwitz, Bedtime Learning
 ├── diagnostics_manager.py ──── Energie-Budget, Thermal Summary
 ├── ramp_controller.py ──────── Aufheiz-Rampe (Vinyl-Schutz)
 ├── anti_short_cycle_manager.py Relay-Schutz
 └── sleep_score_calculator.py ─ Schlaf-Bewertung 0–100
```

22 Module · ~10.650 Zeilen Python · Bilingual (DE/EN) · HACS-kompatibel

---

## FAQ

**Funktioniert das nur mit Wasserbetten?**
Nein. Jede elektrische Bett-Heizung funktioniert: Wasserbett, Heizmatte, beheizbare Matratzenauflage. Das Biorhythmus-Prinzip ist universell.

**Brauche ich einen Temperatursensor?**
Empfohlen. Ohne Sensor läuft das System als intelligente Zeitschaltuhr (Level A). Mit Sensor: volle Biorhythmus-Kurve und Präsenz-Erkennung.

**Was passiert wenn ein Sensor ausfällt?**
Die Integration degradiert automatisch. Der SHT41 kann ausfallen ohne Auswirkung auf die Heizung. Selbst der Wasser-Temperatursensor hat einen Fail-Safe (30% Duty-Cycle).

**Welchen Temperatursensor?**
DS18B20 wasserdicht (IM Wasser) + optional SHT41 (OBEN auf dem Kern).

---

## Lizenz

MIT License – siehe [LICENSE](LICENSE)

---

*Gebaut mit echten Sensordaten aus einem 2×2m Dual-Kern Wasserbett. Kalibriert auf 126.771 Datenpunkte.*
