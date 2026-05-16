# Changelog

Alle Änderungen am Rejuvenation Bed Projekt.

## [Unreleased]

### Features
- **PV-Prioritäts-Kaskade für Solar-Boost** — Der Bett-Boost ist die
  langsamste Senke im Haushalt (große thermische Masse, ~0.3 °C/h). Bisher
  hat er los gefeuert, sobald `solar_power >= solar_boost_threshold` —
  unabhängig davon, ob der Hausakku gerade noch Kapazität für die nächste
  Lastspitze brauchen würde oder nicht.

  Neu: zwei optionale Sensoren in `📊 Sensoren & Strompreis`:
  - **`battery_soc_sensor`** — Hausakku-SoC (%). Default-Schwelle 90%.
  - **`forecast_sensor`** — PV-Prognose Rest-Tag in kWh (z.B. Solcast
    `sensor.solcast_pv_forecast_forecast_remaining_today`). Default 3 kWh.

  Logik (ODER): wenn mindestens einer der beiden Sensoren konfiguriert ist,
  startet der Bett-Boost nur wenn der Akku (fast) voll **oder** die
  Rest-Prognose üppig genug ist. Beispiel: Akku 85% bei wolkigem Forecast
  → Boost wartet (Strom geht in den Akku). Akku 85% bei "noch 6 kWh
  erwartet" → Boost startet (Akku wird ohnehin voll). Ohne diese Sensoren
  bleibt das klassische Verhalten unverändert (backwards compatible).

  Hysterese eingebaut, damit der Boost nicht flattert: 5 %SoC bzw.
  1 kWh Forecast — wer mit SoC 92% gestartet hat, bleibt bis 85% im Boost.

  Der Strompreis-Pfad ("günstiger Netzstrom < 15 ct/kWh = Boost") ist
  bewusst nicht von der Kaskade gegated: das ist Netzstrom, nicht
  PV-Überschuss; da konkurriert der Hausakku nicht mit dem Bett.

  Sichtbar in `state["reason"]`: aktiv → "☀️ Solar-Boost aktiv (1234W
  Überschuss) — Akku 92% · Forecast 5.2 kWh"; blockiert → "⏸ Boost
  wartet — Akku 73% < 90% · Forecast 1.4 < 3.0 kWh".

## [0.7.2] - 2026-05-15

### Bugfixes
- **Isolations-Sensor: Kalibrierung verwirft schwache Spreads** – Der
  Auto-Kalibrierungs-Pfad in `bed_intelligence._update_calibration` hat
  Samples bisher mit `is_present` als Proxy für „Decke drauf" gelabelt.
  Bei Nutzern, die ihre Decke auch tagsüber auf dem leeren Bett liegen
  lassen, landen die bedeckten Samples damit in `_empty_deltas`,
  `cov_mean` und `unc_mean` rücken zusammen, der Threshold rutscht über
  das tatsächliche Covered-Delta — Folge: Sensor meldet dauerhaft
  `on` / „Problem", obwohl die Decke auf dem Bett liegt (siehe Log
  vom 15.05.: |Δ| stabil ~2,1 °K, Defaults würden „covered" liefern,
  gelernte Werte aber „uncovered").

  Fix: gelernte `delta_covered_mean`/`delta_uncovered_mean` werden nur
  übernommen, wenn `|cov - unc| ≥ 0.4 °K`. Sonst bleiben die Defaults
  (cov=2.0, unc=1.5, threshold=1.75) aktiv. Beim Laden aus dem Storage
  werden bereits „verbrannte" Kalibrierungen mit zu kleinem Spread
  automatisch auf die Defaults zurückgesetzt — bestehende Installationen
  müssen also nichts manuell löschen.

## [0.7.1] - 2026-05-08

### ⚠️ Bekannte Probleme
- **Präsenz-Sensor** (`binary_sensor.bett_prasenz`) liefert in der Praxis
  weiterhin nicht zuverlässig korrekte Werte. Die v11-Heuristik ist gegen
  den Replay-Datensatz validiert, aber nicht final feldgetestet.
- **Isolations-Sensor** (`binary_sensor.bett_isolation`) arbeitet noch
  nicht stabil. Die gelernten Schwellen aus dem v0.7.0-Fix greifen nicht
  in allen Setups.

Fixes für beide Sensoren werden in den kommenden Tagen in einem Folge-
Release nachgereicht. Bis dahin: Werte dieser beiden Binary-Sensoren
mit Vorsicht in Automationen verwenden.

### Bugfixes
- **Präsenz-Detector v11 (Wasser-Only, heizungs-bewusst)** – Der bisherige
  Detector v10 hat bei aktivem Solar-Boost regelmäßig „Person im Bett"
  gemeldet, weil drei Probleme zusammenkamen:
  - σ-Schwellen lagen knapp über dem Quantisierungs-Floor des DS18B20
    (0.0625 °C/LSB → σ ≈ 0.031 °C auch bei leerem Bett),
  - eine positive Slope wurde uniform als „leer heizt auf" interpretiert,
    obwohl sie ohne Heizung das eindeutige Signal für Körperwärme ist,
  - `_apply_overrides` hat den Luft-Sensor als Hard-Trigger genutzt
    (`air_std > 2 × threshold` setzte `raw_present = True`).

  v11 fixt alle drei: σ-Schwellen sind quantisierungs-bewusst (chaos
  0.10 → 0.05, refresh 0.06 → 0.045), die Slope-Logik unterscheidet jetzt
  `heater_active=True/False`, und `_apply_overrides` ist aus dem Trigger-
  Pfad entfernt (bleibt für Backward-Compat existierend, wird aber nicht
  mehr aus `_determine_presence` aufgerufen). Hysterese leicht entschärft
  (5/20 → 8/25 Min) gegen Flackern bei Heizungs-Bursts und Toilettengängen.

  Replay gegen den echten Nacht-Datensatz `pres.csv`: 4 Flips über 22 h
  vs. 9 spurious Flips des originalen `binary_sensor.bett_prasenz`,
  insbesondere null Fehlauslösungen mehr in der Solar-Boost-Phase
  12:50–15:50.

  **Keine Breaking Changes** — `detect_presence()` und `get_diagnostics()`
  haben die identische Signatur und Felder wie v10.

### Dokumentation
- **`docs/presence_detector_v11.md`** – Ausführliche Begründung der
  Threshold-Änderungen, Entscheidungsbaum, Validierungs-Tabelle und
  Tuning-Hinweise.

### Test-Sandbox
- Standalone Test-Fassung der reduzierten Wasser-Only-Logik liegt unter
  [`openclawde/rejuvenation-bed-presence-test/`](https://github.com/Chance-Konstruktion/openclawde/tree/main/rejuvenation-bed-presence-test)
  inklusive CSV-Replay-Script (Wide-Format und HA Long-Export).

## [0.7.0] - 2026-03-30

### Code & Architektur
- **Unit-Tests** – Pytest-Suite für `biorhythmus_curve`, `presence_detector`, `ramp_controller`, `sleep_score_calculator`, `anti_short_cycle_manager` und `const` (6 Test-Dateien, 116 Tests, >80% Core-Coverage).
- **CI/CD** – Neuer Workflow `.github/workflows/lint.yml` mit Ruff, Black und pytest als Pflicht-Checks bei jedem Push/PR.
- **Config-Modelle** – `BedTypeConfig` Dataclass (frozen, validated) in `const.py`. Ersetzt lose Dicts durch typsichere, immutable Konfiguration.
- **HeatingStateMachine** – Neue Klasse vereint `AntiShortCycleManager` + `RampController` in einer State Machine (IDLE → RAMPING → HEATING → COOLDOWN → HOLDING). Weniger State-Checks pro Loop.

### Bugfixes
- **Hardware-Level Erkennung** – Setup-Flow zeigte "Vollausstattung" (Level C) auch ohne Power-Sensor. Neues Level B+ für Temp-Only-Setups (Schalter + Temp-Sensor). Erkennung in `config_flow.py`, `climate.py`, `options_flow.py` und `coordinator.py` synchronisiert.
  - A = Nur Schalter (Basic/Zeitschaltuhr)
  - B = + Power-Sensor (Smart/Energie)
  - B+ = + Temp-Sensor ohne Power (Kurve ja, Energie nein)
  - C = + Temp + Power (Vollausstattung)
  - D = + Luft oder Feuchte (Erweitert)
  - E = + Luft und Feuchte (Premium)
- **Doppelte Dict-Keys** – Fitbit-Mappings in `sleep_stage_resolver.py` hatten duplizierte Keys (`deep`, `rem`), behoben.

### Intelligenz & Features
- **Bedtime-Learning v2** – EWMA (Exponential Weighted Moving Average) + Median Hybrid statt reinem Median. 60% EWMA + 40% Median reagiert in 2-3 Nächten auf Schichtwechsel oder Urlaub.
- **Thermische Batterie** – Physik-Formel mit realer Wärmekapazität: Wasser (4.186 kJ/kg·K) + Vinyl-Hülle (1.5 kJ/kg·K, 10kg) + Schaumrahmen (1.3 kJ/kg·K, 6kg). Verlustfaktor 0.85 für reale Bedingungen.
- **Vorheizzeit** – `ramp_controller.calculate_preheat_time()` nutzt jetzt die gleiche Physik-Formel mit allen Materialien.

### Performance & Logging
- **Logging** – DEBUG nur bei Offsets oder Phasenwechseln. Normale Zyklen loggen kompakt auf INFO. Emoji-freie Log-Messages für bessere Parsbarkeit.

### Manifest & HACS
- **hacs.json** – Erweitert um `zip_release`, `filename`, `hide_default_branch`.
- **services.yaml** – Alle 6 Services vollständig dokumentiert mit `example`, `mode: slider`, detaillierten Beschreibungen.

### Dokumentation
- **Architektur-Diagramm** – Mermaid-Diagramme in `docs/architecture.md`: Systemübersicht, Datenfluss-Sequenz, Bett-Typ-Entscheidungsbaum, Entity-Tabelle.
- **.gitignore** – Erweitert um `*.log`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, IDE-Dateien.

## [0.6.1] - 2026-03-23

### Bugfixes
- **Urlaub-Temperatur** – Vacation mode override temperature was ignored; now correctly applied.
- **Fitbit-Mappings** – Restored Fitbit sleep stage mappings that were accidentally removed.
- **Hassfest-Validierung** – Manifest keys sorted alphabetically, invalid `platforms` key removed, `integration_type` added.

### Dokumentation
- **Dashboard-Vorlagen** – Premium Nightstand Dashboard (React/HTML) und Lovelace YAML Cockpit dokumentiert.
- **Services** – Alle 6 Services (`set_boost`, `set_sick_mode`, `set_vacation_mode`, `cancel_special_mode`, `preheat_bed`, `reset_energy_budget`) in README dokumentiert.
- **README überarbeitet** – Sondermodi-Tabelle, Dashboard-Sektion, Architektur auf 60s-Loop aktualisiert. HACS-Badge auf "Default" gesetzt.
- **README_EN.md** – Englische Version vollständig synchronisiert (Services, Dashboards, Special Modes, Architecture).

## [0.6.0] - 2026-03-15

### Neue Features
- **Entity-Reorganisation** – Geräte aufgeräumt und neu gruppiert in drei Devices (Hauptgerät, Energie, Schlaf/Analyse).
- **Premium Dashboard** – Eigenständiges React/HTML Nightstand Dashboard mit Mini-Ansicht (< 800px) und Home Assistant Embedding Guide.
- **Lovelace Dashboard** – YAML-Vorlage für Mobile/Tablet-freundliches Nightstand Cockpit.
- **Service-Übersetzungen** – Fehlende Übersetzungen für alle Services ergänzt.

### Bugfixes
- **Toten Code entfernt** – Unbenutzte Code-Pfade bereinigt.
- **Merge-Konflikte** – Konflikte mit main-Branch sauber aufgelöst.
- **.gitignore** – `__pycache__` Ordner ausgeschlossen.

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
