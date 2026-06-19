# 🛏️ Rejuvenation Bed

**Intelligente Bett-Heizungssteuerung für Home Assistant**

[![HACS Badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/integration)
[![Version](https://img.shields.io/badge/version-v260619-blue.svg)](https://github.com/Chance-Konstruktion/ha-rejuvenation-bed/releases)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

> ### → [**Zur gerenderten Editorial-README**](https://chance-konstruktion.github.io/ha-rejuvenation-bed/)
> Animierte Biorhythmus-Kurve, dunkles Editorial-Layout, die ganze Geschichte.
> *(Quelle: [`docs/index.html`](docs/index.html))*

🇬🇧 [English Version](README.md)

Verwandelt jede Bett-Heizung in eine selbstlernende Schlafautomation. Biorhythmus-basierte Temperaturkurve, Solar-Nutzung als thermische Batterie, Präsenz-Erkennung und Auto-Kalibrierung. Funktioniert mit Wasserbetten, Heizmatten und beheizbaren Matratzenauflagen.

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

**Intelligenz** – Präsenz-Erkennung durch Wassertemperatur-Varianz (kein extra Sensor nötig). Auto-Kalibrierung in 3–5 Tagen. Isolations-Erkennung (Bett zugedeckt?). Schwitz-Erkennung per Kreuzkorrelation. Schlaf-Score 0–100. Lernbasiertes Vorheizen.

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

**🌐 Globale Einstellungen** – Aufgeteilt in *Temperatur & Bett* (Warmhalte-Fenster, Sommer-Schwelle, Offset, Bett-Volumen), *Sensoren & Strompreis* (Preis-Sensor, Festtarif, CO₂) und *Solar & Akku* (Solar-Sensor + Schwelle, optionaler Hausakku-SoC + Schwelle, optionale PV-Forecast + Schwelle, Akku-Vorrang-Häkchen). Solar-Schwelle, SoC und Forecast sind unabhängige Trigger – jeder startet Solar-Boost; Akku-Vorrang lässt die Solar-Schwelle auf vollen Akku / üppige Forecast warten.

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
| `binary_sensor.bett_prasenz` | Person im Bett |
| `binary_sensor.bett_isolation` | Bett zugedeckt (braucht SHT41) |
| `switch.bett_boost` | Schnellheizen |
| `switch.bett_krank_modus` | Krank-Modus |
| `switch.bett_tarifmodus` | Tarifmodus (bei teuerem Strom Temperatur senken) |

### ⚡ Bett Energie

| Entity | Beschreibung |
|--------|-------------|
| `sensor.bett_leistung` | Aktuelle Leistung pro Zone (W) |
| `sensor.bett_gesamtleistung` | Gesamtleistung aller Zonen (W) |
| `sensor.bett_thermische_batterie` | Ladezustand des Wärmespeichers (%) |
| `sensor.bett_energie_heute` | Verbrauch heute (kWh) |
| `sensor.bett_heizstunden` | Heizstunden heute |
| `sensor.bett_ersparnis` | Geschätzte Ersparnis (€) |
| `sensor.bett_solar_prozent` | Solar-Anteil am Verbrauch |
| `sensor.bett_strompreis_status` | Aktueller Tarif-Modus |
| `switch.bett_solar_batterie` | Thermische Batterie |
| `switch.bett_urlaub_modus` | Urlaub-Modus |

### 😴 Bett Schlaf/Analyse

| Entity | Beschreibung |
|--------|-------------|
| `sensor.bett_schlaf_score` | Letzte Nacht (0–100) |
| `sensor.bett_schlaf_score_woche` | Wochendurchschnitt |
| `sensor.bett_rampe` | Aufheiz-Rampe Status |
| `sensor.bett_intelligence` | Kalibrierung und Lernstatus |
| `binary_sensor.bett_degraded_mode` | Degraded Mode (Sensor-Ausfall) |
| `binary_sensor.bett_kondensationsrisiko` | Kondensationsrisiko (< 24°C) |
| `binary_sensor.bett_leckage_verdacht` | Leckage-Verdacht |
| `binary_sensor.bett_schwitzen` | Schwitz-/Nässe-Alarm |
| `binary_sensor.bett_system_status` | System-Gesundheit |

---

## Services

| Service | Beschreibung |
|---------|-------------|
| `rejuvenation_bed.set_boost` | Schnellheizen aktivieren (Dauer konfigurierbar) |
| `rejuvenation_bed.set_sick_mode` | Krank-Modus (Temperatur + Tage) |
| `rejuvenation_bed.set_vacation_mode` | Urlaub-Modus mit optionaler Temperatur und Enddatum |
| `rejuvenation_bed.cancel_special_mode` | Alle Sondermodi beenden |
| `rejuvenation_bed.preheat_bed` | Bett vorheizen (Temperatur + Dauer) |
| `rejuvenation_bed.reset_energy_budget` | Energiestatistiken zurücksetzen |

---

## Sondermodi

| Modus | Aktivierung | Wirkung |
|-------|------------|---------|
| **Boost** | `switch.bett_boost` | Schnellheizen: Zieltemperatur + Offset für 60 Min |
| **Krank** | `switch.bett_krank_modus` | Konstante Temperatur für konfigurierbare Tage |
| **Urlaub** | `switch.bett_urlaub_modus` oder Service | Minimale 24°C Haltetemperatur (mit optionaler Temperatur) |
| **Solar** | `switch.bett_solar_batterie` | PV-Überschuss als Wärme speichern |
| **Tarif** | `switch.bett_tarifmodus` | Bei teuerem Strom Temperatur senken |

---

## Dashboard-Vorlagen

Zwei fertige Dashboard-Vorlagen im `dashboards/`-Ordner:

### Lovelace YAML (Nightstand Cockpit)

`dashboards/rejuvenation_bed_nightstand_cockpit.yaml` — Mobile/Tablet-freundliche Lovelace-Vorlage. Entity-IDs an deine Installation anpassen.

### Standalone HTML (Premium Dashboard)

`dashboards/premium_nightstand_dashboard.html` — Eigenständiges React/HTML-Dashboard mit Mini-Ansicht (< 800px).

**Einbindung als Panel:**

```yaml
panel_iframe:
  waterbed_cockpit:
    title: Wasserbett Cockpit
    icon: mdi:bed-outline
    url: /local/rejuvenation_bed/premium_nightstand_dashboard.html
```

**Oder als iframe-Card:**

```yaml
type: iframe
url: /local/rejuvenation_bed/premium_nightstand_dashboard.html
aspect_ratio: 100%
```

Datei nach `/config/www/rejuvenation_bed/` kopieren.

---

## Architektur

```
coordinator.py ─── Zentraler 60s-Loop
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

**Wie funktioniert die Präsenz-Erkennung bei Heizmatten?**
Anders als beim Wasserbett (Varianz-Analyse im Wasserkörper) nutzt die Heizmatten-Erkennung den **Temperatur-Trend**: Wenn die Heizung aus ist und die Temperatur trotzdem steigt, liegt jemand drauf (Körperwärme). Voraussetzung ist ein Temperatursensor an der Matte. Ohne Sensor ist keine Präsenz-Erkennung möglich — das System läuft dann als Zeitschaltuhr (Level A). Die Erkennung ist weniger präzise als beim Wasserbett, funktioniert aber zuverlässig nach einer kurzen Einliegezeit (~3 Min).

**Welchen Temperatursensor?**
DS18B20 wasserdicht (IM Wasser) + optional SHT41 (OBEN auf dem Kern).

---

## Lizenz

MIT License – siehe [LICENSE](LICENSE)

---

*Gebaut für Menschen, die nachts schlafen wollen — und morgens aufwachen, nicht hochschrecken.*
