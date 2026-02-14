# Changelog

Alle Änderungen am Rejuvenation Bed Projekt.

## [0.3.2] - 2026-02-14

### Gefixt
- **Zeit-Parser Crash**: HA TimeSelector gibt `HH:MM:SS` zurück, Parser erwartete `HH:MM` → `too many values to unpack` behoben (temperature_calculator.py + coordinator.py)

### Verbessert
- Oberflächentemperatur-Sensor umbenannt: "Luft-/Oberflächentemperatur" → "Oberflächentemperatur (oben)"
- Beschreibung im Setup und Einstellungen einheitlich gestaltet (gleicher Stil mit Emoji + Feature-Liste)
- Alle Translations (DE/EN/strings.json) konsistent aktualisiert

## [0.3.1] - 2026-02-14

### Gefixt
- **Kalibrierung resettet bei HA-Restart**: Rohdaten (`_empty_water_stds`, etc.) wurden nicht gespeichert. `to_dict()` speichert jetzt Rohdaten während Lernphase, `from_dict()` stellt sie wieder her
- **Auto-Save während Lernphase**: Alle 50 Samples Zwischenspeicherung (max. 25 Min Datenverlust bei Crash)

### Hinzugefügt
- Neues Feld `air_temp_sensor` im Config-Flow und Options-Flow (Setup → Sensoren)
- SHT41 Luft-Temp kann jetzt direkt konfiguriert werden statt nur per Namensableitung
- Fallback auf alten Namenstrick (`feuchtigkeit` → `lufttemp`) bleibt bestehen

## [0.3.0] - 2026-02-14

### Hinzugefügt
- **`bed_intelligence.py`** – Neues Modul (635 Zeilen): Auto-Kalibrierung, Isolations-Erkennung, Schwitz 2.0
- **Auto-Kalibrierung**: Lernt in 3-5 Tagen automatisch Präsenz-Schwelle, Isolations-Delta, Feuchtigkeit-Baseline
- **Isolations-Erkennung (Decken-Check)**: Δ(Wasser - Luft) erkennt ob Bett zugedeckt ist. Warnung nach >60 Min offen
- **Schwitz-Algorithmus 2.0**: Kreuzkorrelation Temp × Feuchtigkeit. Unterscheidet: Schwitzen vs. Leck vs. Raum-Feuchtigkeit
- Neuer Binary-Sensor `binary_sensor.bett_isolation` (ON = offen/Problem)
- Neuer Sensor `sensor.bett_intelligence` (Lernphase X% / Kalibriert)
- Kalibrierte Schwellwerte werden automatisch an PresenceDetector übergeben
- Notification bei offener Decke >60 Min
- `humidity_level`, `sweat_cause`, `isolation_level`, `isolation_delta` als Zone-Attribute

### Architektur
- BedIntelligence wird im Coordinator initialisiert und bei jedem 30s-Update aufgerufen
- Persistent Storage für Kalibrierungsdaten (überlebt HA-Restart)
- DS18B20 = Pflicht, SHT41 = komplett optional (Features werden automatisch freigeschaltet)

## [0.2.3] - 2026-02-14

### Gefixt
- **Energie Gesamt / Heizstunden resettet bei HA-Restart**: `diagnostics_manager.async_load()` wurde nie aufgerufen. Jetzt beim ersten Update-Zyklus geladen
- **Gesamtleistung immer 0**: Sensor las `data["total_power"]` statt `data["global_state"]["energy"]["total_power"]`
- **Ersparnis vs. Klassisch immer 100%**: Sensor las `_energy_budget["total_kwh"]` (existiert nicht) statt `get_energy_budget()["total_kwh"]`
- **Ø Tagesverbrauch springt wild**: Division durch ~0 bei `days_since_reset`. Minimum auf 0.04 (~1h) gesetzt. `last_reset` wird nur beim allerersten Start gesetzt
- **Schwitzerkennung "NASS" obwohl trocken**: Schwelle von 75% auf 93% angehoben
- **Toilettengang startet Biorhythmus neu**: Kurze Unterbrechungen (<30 Min) werden ignoriert, Tracking läuft weiter

### Hinzugefügt
- `get_humidity_level()` Methode im PresenceDetector: trocken/normal/feucht/sehr feucht/nass
- `total_runtime_hours` in `get_energy_budget()` Return-Dict

## [0.2.2] - 2026-02-14

### Gefixt
- **Wecker-Bug**: `warm_from`/`warm_until` wurden nur aus `config_entry.data` gelesen, nicht aus `config_entry.options`. Options-Flow Änderungen hatten keine Wirkung
- Priority-Chain korrigiert: Options → Data → Hardcoded Default (an 2 Stellen in temperature_calculator.py)
- Versionen synchronisiert: manifest.json und const.py auf gleichen Stand

## [0.2.1] - 2026-02-14

### Hinzugefügt
- **Presence Detector v3**: Varianz-basierter Algorithmus (σ über 20min Rolling-Window)
- Kalibriert auf 126.771 echte Datenpunkte
- 97.5% Precision, 74% Recall bei σ > 0.04°C
- Asymmetrische Hysterese: 5 Min Enter, 20 Min Leave

## [0.2.0] - 2026-02-13

### Hinzugefügt
- Sensor-Kalibrierung aus 126.771 Datenpunkten (echte Messdaten Feb 2026)
- Verbesserte saisonale Temperatur-Anpassung

## [0.1.3] - 2026-02-13

### Gefixt
- Diverse Bugfixes: Tarifmodus, Energie-Zähler, Options-Flow Validierung

## [0.1.2] - 2026-02-11

### Gefixt
- Options-Flow Bugfix: Sensor-Felder konnten nicht geleert werden

## [0.1.1] - 2026-02-11

### Gefixt
- Hardware-Sync beim Start
- Mode-Auswertung (Boost, Krank, Eco, Urlaub)
- Fail-Safe bei Sensor-Ausfall

## [0.1.0] - 2026-02-11

### Erstveröffentlichung
- 22 Module, ~8.500 Zeilen Python
- Biorhythmus-Kurve mit Chronotyp-Anpassung
- Solar-Boost / Thermische Batterie
- Tarifmodus für dynamische Strompreise
- Dual-Zone Unterstützung
- Schlaf-Score (0-100)
- Bilingual (DE/EN)
- HACS-kompatibel
