# Changelog

Alle Änderungen am Rejuvenation Bed Projekt.

## [Unreleased]

## [v260728] - 2026-07-28

### Dashboard
- **Nachttischwecker als echte Lovelace-Karte:** Die Integration liefert
  `custom:rejuvenation-nightstand` mit und meldet die Karte beim Start selbst im
  Frontend an — kein Kopieren nach `/config/www`, kein Ressourcen-Eintrag von
  Hand, kein Long-Lived Token und keine zweite Anmeldung. Die Karte spricht über
  das `hass`-Objekt mit Home Assistant, also über die Sitzung, in der man
  ohnehin angemeldet ist. Die frühere eigenständige HTML-Seite entfällt damit,
  ebenso die beiden alten Dashboard-Vorlagen (`premium_nightstand_dashboard.html`
  sowie der 1,5 MB große Export `Dashboard _claudedesign.html`). Beispiel-
  Dashboard: `dashboards/nightstand.yaml`, als `type: panel` bildschirmfüllend,
  mit Vollbild-Knopf in der Karte.
- **Drei Tasten wie am Bett:** Wasserbetttemperatur als ziehbarer
  Thermostat-Ring, Wecker (Stunde/Minute stellen, ausschalten) und
  Schlafzimmerlampe (Helligkeit, An/Aus, Nachtlicht mit 1 % bei 2000 K).
  Tiefschwarzer AMOLED-Hintergrund, Akzente ausschließlich in gedecktem
  Bernstein.
- **Vier Zifferblätter:** Kontur (Standard, nur Umriss ohne Leuchtschleier —
  eine ausgefüllte Ziffer strahlt neben dem Kopfkissen zu viel Fläche ab),
  7-Segment im Weckerradio-Stil der frühen 80er inklusive sichtbarer
  unbeleuchteter Segmente, 5×7-LED-Matrix der 90er und Klappanzeige. Umschalten
  per Tipp auf die Uhr, dazu ein eigener Helligkeitsregler. Beides gilt pro
  Gerät, ein Dashboard darf also auf jedem Bildschirm anders aussehen.
- **Mehrere Betten und Seiten:** Die Entities hängen an einem Bett-Eintrag der
  Kartenkonfiguration. Mehrere Betten im Haus — oder zwei Seiten desselben
  Betts — bekommen je einen Eintrag; jedes Gerät merkt sich seinen eigenen,
  sodass beide Seiten unabhängig vom jeweiligen Telefon bedient werden.
- **Nachtbetrieb:** Nach 45 Sekunden ohne Berührung blendet alles außer der Uhr
  aus, und die Ziffern wandern minütlich einige Pixel gegen Einbrennen auf
  OLED-Panels. Die erste Berührung weckt nur den Bildschirm und löst keine Taste
  aus.

### Anforderungen
- **Mindestversion auf Home Assistant 2024.7.0 angehoben:** Die Karte wird über
  `async_register_static_paths()` ausgeliefert, das es erst ab dieser Version
  gibt. Schlägt die Registrierung fehl, wird das protokolliert und das Setup
  läuft weiter — ohne Karte, aber mit voll funktionsfähiger Integration.

## [v260628] - 2026-06-28

### Dokumentation
- **Eigene `info.md` für den HACS-Store:** HACS rendert jetzt eine schlanke
  `info.md` (Pitch, Highlights, Quick-Start) mit prominentem Link auf die
  Editorial-Seite, statt die lange README. `hacs.json`: `render_readme → false`.

### Funktion / UX
- **Sommer-Modus klar kommuniziert + ehrlicher Status:** Im Options-Flow ist
  jetzt sauber getrennt, was eingestellt wird — die **Außentemperatur-Schwelle**
  (`summer_threshold`, ab wann der Sommer-Modus greift) und die neue, einstellbare
  **Bett-Haltetemperatur im Sommer** (`summer_temp`, vorher hart auf 25 °C). Die
  Beschreibungen erklären beides eindeutig und benennen den Solar-Boost als
  Übergangszeit-/Winter-Feature. Zudem behoben: Der Status zeigte „☀️ Solar-Boost
  aktiv", obwohl bei aktivem Sommer-Veto die Zieltemperatur auf die Sommer-
  Temperatur gedeckelt war und das Bett gar nicht hochheizte. Bei Sommer-Veto
  meldet der Status nun „☀️ Sommer aktiv – Heizung reduziert (X°C)" und
  `solar_active` wird nicht mehr fälschlich als aktiv gemeldet. Wasserbetten
  bleiben auf mind. 24 °C geklemmt (Kondensationsschutz).
  README (DE/EN) entsprechend ergänzt: Sommer-Schwelle vs. Sommer-Bett-
  Temperatur klar getrennt, Solar-Boost als Übergangszeit-/Winter-Feature.
- **Options-Flow mit Zurück-Navigation:** Der Einstellungs-Dialog beendet sich
  nicht mehr nach jeder gespeicherten Maske. Jede Eingabemaske kehrt nach dem
  Speichern zu ihrem übergeordneten Menü zurück, sodass jederzeit eine Seite
  zurück navigiert werden kann, ohne den kompletten Options-Flow neu starten zu
  müssen. Änderungen werden in einer Arbeitskopie gesammelt und erst über
  »💾 Speichern & Beenden« im Hauptmenü übernommen (genau ein Reload statt einem
  pro Maske). Das Untermenü »Globale Einstellungen« listet jetzt zusätzlich
  »☀️ Solar & Akku« sowie einen »⬅️ Zurück«-Eintrag.

### Sicherheit / Bugfix
- **Klebe-Relais-Fehlalarm im Sommer behoben:** Die Erkennung verglich die
  aktuelle Temperatur mit dem Messwert beim AUS-Befehl – über ein **unbegrenztes**
  Zeitfenster. Jede Drift >0.3 °C löste irgendwann Alarm aus, je länger alles
  in Ordnung war, desto wahrscheinlicher. Folge: nach 674 Min AUS reichten
  +0.4 °C aus Raum-/Körperwärme für eine „Relais-Verdacht"-Meldung.
  Jetzt **ratenbasiert** über ein gleitendes 30-Min-Fenster: gemeldet wird nur
  ein **anhaltender, schneller** Anstieg (≥0.8 °C/Fenster ≈ 1.6 °C/h), wie ihn
  ein dauerhaft heizendes Relais erzeugt. Langsame Sommer-/Körperwärme-Drift
  akkumuliert nicht mehr zu einem Fehlalarm.
- **Meldungstext entschärft:** nennt jetzt Körperwärme (Schläfer) und warmes
  Schlafzimmer als häufige harmlose Ursachen statt nur Defekt-Verdacht.

## [v260620] - 2026-06-20

### Sicherheit
- **Software-Safety-Engine verdrahtet (#1):** `async_check_zone_safety` wird
  jetzt pro Zone ausgewertet (Klebe-Relais, Sensor-Defekt, Übertemperatur).
  Bei >36 °C greift ein Emergency-Latch (Heizung bleibt AUS bis manueller Reset).
- **Fail-Safe je Bett-Typ (#2):** Wasserbett heizt bei Sensor-Ausfall weiter,
  aber mit Max-ON-Timeout (90 min → 30 % Degraded-Duty); Heizmatte schaltet AUS.
- **Urlaubs-Temperatur (#3):** für Wasserbetten auf `min_temp` (24 °C) geklemmt.

### Funktion / UX
- **Manuelle Zieltemperatur mit TTL (#4/#5):** Slider/Service verfällt nach 8 h
  zurück zur Kurve; Vorheizen (`preheat_bed`) verfällt nach seiner Dauer.
- **Services & Multi-Instanz (#6):** `single_config_entry`, Services einmalig
  global registriert, Coordinator zur Laufzeit aufgelöst.
- **Tarif-Status korrekt (#7):** Resolver liefert echte `solar_active` /
  `price_status` (cheap/expensive/normal).
- **Boost vereinheitlicht (#8/#11):** feste `boost_target_temp` (Option → Zone →
  34 °C), kein Offset-Stapeln; tote DRY/COMFORT-Presets entfernt.

### Refactor / Qualität
- **#9** Coordinator-Monolith zerlegt (`_process_zone`, `_async_sync_hardware_once`,
  `_finalize_energy`) + erste Coordinator-Integrationstests.
- **#10** Zeitzonen über `local_now()` (HA-Zeit) vereinheitlicht.
- **#12** Hardware-Level-Erkennung dedupliziert (`device_info.detect_hardware_level`).
- **O1** BedIntelligence-Saves entprellt; **O2** Sensor-Warnungen gedrosselt;
  **O3** Magic Numbers → const; **O5** Solar-Hysterese relativ (10 %);
  **O9** totes `comfort_offset` entfernt.
- CI: Black auf `custom_components/` erweitert. Test-Suite 178 → 225.

## [v260619] - 2026-06-19

### Bugfixes
- **Solar-Boost schaltete tagsüber die Heizung (Smartplug) nicht ein.**
  Der Energie-Offset (Solar-Boost +1.5 °C) wurde nur im Warmhalte-Fenster
  (nachts) auf die Biorhythmus-Kurve addiert — also genau dann NICHT, wenn
  PV-Überschuss da ist. Tagsüber lief der Standby-Zweig in ein frühes
  `return standby_temp` ohne Offset, das Ziel blieb auf Normaltemperatur und
  die Heizung sprang nie an. Solar-Boost soll den Überschuss aber als
  thermische Batterie ins Bett laden. Fix: neuer `_charge_standby_temp` hebt
  das Tages-Standby-Ziel um den Solar-Offset an (gedeckelt auf
  `solar_boost_max`, nur für Betten mit Wärmespeicher, nur positiver Offset).
- **Präsenz v11.1 — Stale-Cooldown-Release (Sensor hing ~12 h auf "belegt").**
  An einem echten Tag-Schlaf-Datensatz (Nutzer lag 06:00–14:00 CEST, jetzt
  inkl. Heizungs-Switch-Historie) blieb `binary_sensor.…_bett_prasenz` nach
  dem Aufstehen ~12 h fälschlich ON. Ursache: das warme, leere Bett kühlt nur
  mit ~0.06–0.16 °C/h aus (flacher als `slope_cooling_threshold` = −0.10) und
  sein σ60-Rauschen (~0.045–0.05) lag genau auf `chaos_refresh_threshold` —
  der Chaos-Lock frischte sich endlos selbst auf und schloss die heizungs-
  bewusste Slope-Logik kurz. `heat_ratio` trennt hier nicht (Heizung war in
  beiden Phasen aus). Fix:
  - `chaos_threshold` 0.05 → **0.055** (über dem Leer-σ-Floor dieses Setups).
  - NEU `slope_cooldown_release` (−0.05 °C/h) + `cooldown_release_minutes` (90):
    Heizung aus + anhaltende Auskühlung + seit N min kein echter Bewegungs-Burst
    ⇒ Bett leer, der Chaos-Lock wird gebrochen.
  - NEU `_empty_confirmed`: ein bestätigt leeres Bett wird nicht durch
    σ60-Rauschen oder einen kurzen Heiz-Burst wiederbelebt — nur ein echter
    Burst, Körperwärme-Anstieg oder rise→stable setzt es zurück.
  Replay-validiert: Ausstieg jetzt 13:52 CEST (≈ Ground-Truth 14:00) statt nie;
  `pres.csv` bleibt unverändert sauber. Drei neue Regressions-Tests.

### Features
- **Solar-Boost: Akku-SoC und Solar-Schwelle als unabhängige Trigger.**
  Der Bett-Boost kennt jetzt drei **eigenständige** Auslöser, die mit
  **ODER** verknüpft sind — jeder funktioniert allein, alle wirken auch
  zusammen:
  - **Solar-Schwelle** — aktuelle PV-Leistung ≥ `solar_boost_threshold`
    (klassisches Verhalten).
  - **Akku-SoC** — Hausakku-SoC ≥ Schwelle (Default 90%). Löst jetzt
    **unabhängig** von der Solar-Schwelle aus: voller Akku → Überschuss
    fürs Bett nutzen, auch wenn die Momentan-Leistung gerade unter der
    Solar-Schwelle liegt.
  - **PV-Forecast** — Rest-Tags-Prognose ≥ Schwelle (Default 3 kWh).
    **Rein optional** — ohne Sensor ändert sich nichts.

  Vorher gateten Akku/Forecast die Solar-Schwelle (UND-Logik): der Boost
  startete *nur* wenn zusätzlich genug PV-Leistung anlag. Jetzt genügt
  ein einziger erfüllter Trigger. Nur konfigurierte Sensoren zählen;
  fehlende Sensoren blockieren nicht. Solar-only-Setups verhalten sich
  damit exakt wie früher.

  Jeder Trigger hat eine eigene Hysterese, damit nichts flattert:
  50 W (Solar), 5 %SoC, 1 kWh Forecast.

  Neu: optionales Häkchen **Akku-Vorrang** (`battery_priority`, Default
  AUS) in `📊 Sensoren & Strompreis`. AN stellt das klassische Gating
  wieder her: die Solar-Schwelle löst dann nur aus, wenn der Akku (fast)
  voll **oder** die Forecast üppig ist — so bekommen Akku/Boiler Vorrang
  auf den PV-Überschuss. Ohne Akku-/Forecast-Sensor wirkungslos. Im
  Wartezustand: "⏸ Boost wartet (Akku-Vorrang) — Akku 73% < 90%".

  Der Strompreis-Pfad ("günstiger Netzstrom < 15 ct/kWh = Boost") bleibt
  ein weiterer unabhängiger Auslöser (Netzstrom, kein PV-Überschuss).

  Sichtbar in `state["reason"]`, z.B. "☀️ Solar-Boost aktiv — 1234W
  Überschuss · Akku 92% · Forecast 5.2 kWh". Die aktiven Trigger stehen
  zusätzlich in `state["active_triggers"]` (Diagnose).

- **Options-Flow aufgeräumt.** Solar/Akku-Felder aus „📊 Sensoren &
  Strompreis" in einen eigenen Bereich **„☀️ Solar & Akku"** ausgelagert
  (kürzere Formulare). Neuer **„⬅️ Zurück"**-Eintrag im Untermenü
  „🌐 Globale Einstellungen".

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
