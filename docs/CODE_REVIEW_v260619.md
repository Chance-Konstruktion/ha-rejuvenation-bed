# Code-Review v260619 — Fix-Plan (Handoff)

> Wasserbett-Setup, Smartplug. Seit 4 Monaten täglich produktiv.
> Hardware-Thermostat ist physisch im Kreis = primäre Schutzschicht.
> Dieses Dokument ist die Arbeitsliste für die Umsetzung aller Review-Findings.
> Reihenfolge = empfohlene PR-Batches. Jede Zeile: Befund → Ursache → Fix → Test.

## Status-Checkliste
- [x] Tier 1 — Safety (#1 #2 #3) ✅ PR A
- [x] Tier 2 — UX/Funktions-Bugs (#4 #5 ✅ PR A · #7 #8 ✅ PR B)
- [x] Tier 3 — Multi-Instanz/Targeting (#6) + manifest ✅ PR B
- [ ] Tier 4 — CI härten
- [~] Tier 5 — Refactor/Optimierung: #10 ✅ #11 ✅ #12 ✅ · #9 teilweise ✅ · O7 ✅ — offen: #9-Kern, O1–O6, O8, O9
- [ ] Release-Tag `v260619` setzen

> **Erledigt (PR C):** #12 `detect_hardware_level` als einzige Quelle in
> `device_info.py` (3× Duplikat entfernt). #10 Zeitzonen: `datetime.now()`
> → `local_now()` in presence_detector, anti_short_cycle, ramp_controller,
> heating_state_machine; Biorhythmus-Kurve bleibt HA-frei und bekommt die
> Zeit vom Aufrufer. #9 (teilweise): `_async_sync_hardware_once` +
> `_finalize_energy` aus dem Monolithen ausgelagert. conftest aktiviert
> `local_now()` als echte Uhr im Test.
>
> **#9-Kern (Zonenschleife) bewusst zurückgestellt:** Die ~400-Zeilen-
> Per-Zone-Logik in `_async_update_data` hat KEINE Integrationstests. Eine
> Blind-Extraktion auf sicherheitskritischem Pfad ist riskant → zuerst
> einen Coordinator-Integrationstest (`_async_update_data` Smoke) bauen,
> dann `_process_zone` extrahieren.
>
> **#11 (Boost-Dopplung) erledigt:** Dopplung entfernt — Boost nutzt jetzt
> EINE feste Zieltemperatur (`boost_target_temp`), kein Offset-Aufaddieren
> mehr. Neue globale Option `boost_target_temp` (28–34 °C, Vorrang Option →
> Zone-Config → 34). `boost_offset` aus dem Options-Flow + Übersetzungen
> entfernt. Konsumenten (temperature_calculator, coordinator,
> diagnostics_manager) auf dieselbe Quelle/Reihenfolge vereinheitlicht.
> Tests: +2 in test_temperature_calculator.py.

> **Erledigt (PR A):** #1 Safety-Engine verdrahtet (Emergency-Latch +
> Zonen-Safety nach Heiz-Entscheidung), #2 Fail-Safe je Bett-Typ +
> Max-ON-Timeout (90 min → Degraded-Duty), #3 Urlaubs-Temp-Clamp,
> #4 manual_target TTL (8 h + Clear bei AUTO/Cancel), #5 totes
> `preheat_until` durch gemeinsame TTL ersetzt. Tests:
> `tests/test_safety_manager.py` (10), `tests/test_coordinator.py` (7).
>
> **Erledigt (PR B):** #6 Services global+einmalig registriert, Coordinator
> zur Laufzeit aufgelöst, `single_config_entry: true`, Unload entfernt
> Services erst beim letzten Entry. #7 Resolver liefert echte
> `solar_active`/`price_status` (Tarif-Status korrekt). #8 nicht-funktionale
> DRY/COMFORT-Presets entfernt (Krank läuft über Service). O7 irreführender
> Unload-Kommentar korrigiert. Tests: +6 in `test_energy_state_resolver.py`.
> Gesamt 215 grün.

---

## TIER 1 — Safety (1 PR)

### #1 Tote Safety-Engine verdrahten
- **Datei:** `safety_manager.py:129` `async_check_zone_safety()` (+ `clear_emergency`, `get_safety_status`) werden NIE aufgerufen.
- **Folge:** Klebe-Relais-Erkennung, Sensor-Defekt-Abschaltung (3 h/<0,5 °C), 34 °C-Kritisch inaktiv.
- **Fix:** Im Coordinator-Loop pro Zone NACH `should_heat`-Entscheidung aufrufen:
  `is_safe, status, notif = await self.safety_manager.async_check_zone_safety(zone_index, current_temp, target_temp, should_heat)`.
  Bei `is_safe=False` → `should_heat=False`, Heizung aus, `notif` via `_async_send_notification`. Emergency-Latch respektieren (`is_emergency_shutdown`); Reset nur über `clear_emergency` (z.B. neuer Service oder bei Sensor-Recovery).
- **Test:** neue `tests/test_safety_manager.py` — stuck-relay, sensor-defect, overheat-Stufen, spam-throttle.

### #2 Fail-Safe je Bett-Typ + Timeout
- **Datei:** `coordinator.py:271` `_async_handle_sensor_failure`, `:874` Zonen-Except, `:922` 3×-Fehler.
- **Wasserbett:** Fail-Safe-AN bleibt korrekt. **Heizmatte:** auf AUS drehen.
- **Fix:** Richtung an `self.is_waterbed` koppeln; zusätzlich **Max-ON-Timeout** für Fail-Safe-AN (z.B. 90 min ohne Sensor → auf Degraded-Duty 30 % zurückfallen statt Dauer-Volllast). Konstante in `const.py`.
- **Test:** Heizmatte→AUS, Wasserbett→AN, Timeout greift.

### #3 Urlaubs-Temp clampen
- **Datei:** `coordinator.py:227` (`away_temp` ohne `min_temp`-Clamp); `services.yaml:94` erlaubt min 0.
- **Fix:** Für Wasserbett `away_temp = max(away_temp, self.bed_config["min_temp"])`. `services.yaml` min auf 15 (Heizmatte) — oder Clamp rein im Code lassen und Doku ergänzen.
- **Test:** vacation_temp=20 + Wasserbett → Ziel ≥ 24.

---

## TIER 2 — UX / Funktions-Bugs (1 PR)

### #4 Manuelle Zieltemperatur = permanenter Auto-Stopp
- **Datei:** `climate.py:232` setzt `manual_target_temp`; `temperature_calculator.py:134` gibt es bedingungslos zurück; `__init__.py:202` `cancel_special_mode` löscht es NICHT.
- **Fix (Option A, empfohlen):** TTL einführen — `manual_target_until[zone]` (z.B. via Service-Dauer / Default 8 h). In `temperature_calculator` nur honorieren wenn nicht abgelaufen, sonst Key löschen.
  **Zusätzlich:** `cancel_special_mode` + HVAC-Wechsel auf AUTO löschen `manual_target_temp[zone]`. Climate: `async_set_hvac_mode(AUTO)` → `manual_target_temp.pop(zone)`.
- **Test:** Slider setzen → nach TTL zurück auf Kurve; cancel_special_mode löscht.

### #5 `preheat_until` ist tot
- **Datei:** `__init__.py:241` setzt `preheat_until`, wird nie gelesen.
- **Fix:** Im selben TTL-Mechanismus wie #4 nutzen (`manual_target_until`). `preheat_bed` setzt `manual_target_until = now + duration`.
- **Test:** preheat 30 min → nach 30 min Auto.

### #7 Falsche Energie-Keys
- **Datei:** `coordinator.py:890-891` `energy_state.get("solar_active")` / `"price_status")` existieren nicht.
- **Folge:** `global_state.energy.solar_active` immer False; `switch.py:344` Tarif-Status immer „Normal".
- **Fix:** Aus `mode` ableiten: `solar_active = mode == EnergyMode.SOLAR_BOOST`; `price_status` aus `current_price`/Schwellen (cheap/expensive/normal) oder Resolver um diese Keys erweitern. Konsumenten prüfen (`switch.py`, `binary_sensor.py`, `sensor.py`).
- **Test:** Resolver-Output-Keys + Switch-Attribut.

### #8 DRY/COMFORT-Presets ohne Funktion
- **Datei:** `climate.py:66-79` bewirbt `HVACMode.DRY` (Krank) + `PRESET_COMFORT`; DRY löst keinen Krank-Modus aus, COMFORT wird in `_adjust_modes_for_hardware` entfernt.
- **Fix:** Entweder verdrahten (DRY→sick, COMFORT→comfort_offset) ODER aus `_attr_hvac_modes`/`_attr_preset_modes` entfernen. Empfehlung: entfernen (weniger Fläche), Krank/Komfort laufen über Switch/Service.

---

## TIER 3 — Multi-Instanz / Targeting (klein)

### #6 Services ignorieren Ziel-Entity + global registriert
- **Datei:** `__init__.py:147-267`, `services.yaml` (`target: entity`).
- **Problem:** Handler lesen `call.data[ATTR_ENTITY_ID]` nie; wirken auf alle Zonen der Closure-`entry`; Services global → 2. Bett überschreibt Handler, Unload entfernt global.
- **Fix (pragmatisch):** `manifest.json` → `"single_config_entry": true` (nur 1 Bett). Services einmalig registrieren (nicht pro Entry), Handler holt Coordinator über das einzige Entry. Optional Entity-Targeting auf Zonen mappen (entity→zone_index).
- **Test:** Service mit/ohne target.

---

## TIER 4 — CI härten (klein)

- `.github/workflows/lint.yml:31` Black prüft nur `tests/` → auf `custom_components/` ausweiten (Code ist bereits black-konform halten).
- Ruff-Select erweitern (mind. `E,F,W`; `I` für Imports) — schrittweise, sonst Flut.
- Optional `mypy` (lax) + Coverage-Gate (z.B. `--cov-fail-under=70`).
- **Achtung HACS:** `hacs.json zip_release:true` → jedes Release MUSS das ZIP-Asset haben (`release.yml` deckt `v*`-Tags ab). Nicht versehentlich Release ohne Tag erzeugen.

---

## TIER 5 — Refactor / Optimierung

### #9 `_async_update_data` Monolith (~600 Zeilen, coordinator.py:307-915)
- In private Schritte zerlegen: `_sync_hardware_once`, `_resolve_zone_inputs`, `_track_sleep_session`, `_decide_and_switch`, `_update_intelligence`. Ermöglicht `tests/test_coordinator.py`.

### #10 Zeitzonen-Inkonsistenz
- `datetime.now()` (System-TZ) in `presence_detector`, `biorhythmus_curve`, `anti_short_cycle_manager`, `ramp_controller`, `heating_state_machine` → auf `local_now()` (HA-TZ) vereinheitlichen. Sonst versetzte Kurve/Präsenz bei Container-TZ ≠ HA-TZ.

### #11 Doppelte Boost-Logik
- Absolut in `temperature_calculator.py:144` (`boost_target_temp`) + Offset in `coordinator.py:245`. Auf EINE Quelle reduzieren.

### #12 Hardware-Level-Erkennung 3× dupliziert
- `config_flow._detect_hardware_level`, `options_flow._detect_hardware_level`, `climate._detect_hardware_level` → in `const.py` (oder `device_info.py`) als eine Funktion.

### Zusätzliches Optimierungspotenzial (neu)
- **O1 Save-Storms:** `bed_intelligence`/`diagnostics_manager` rufen oft `hass.async_create_task(self.async_save())`. → `Store.async_delay_save(...)` (Debounce) statt sofort pro Update.
- **O2 Log-Spam:** `_safe_get_sensor_value` (`coordinator.py:173`) loggt WARNING pro Zyklus bei fehlendem Sensor (alle 60 s). → Pro Entity throttlen/einmalig.
- **O3 Magic Numbers → const.py:** `past_wake < 14:00` (`coordinator.py:564`), `startup_grace 180`, Efficiency `2700s`/`0.2°C`, `gone_min 60`, session `2h`.
- **O4 `decision["zones"]` per String-Key `"Zone N"`** (coordinator + alle Entities) — fragil. Auf `zone_index` als Key umstellen oder Konstante/Hilfsfunktion `zone_key(i)`.
- **O5 Resolver-Hysterese:** `solar_boost_off_w = on_w - 50` fix (energy_state_resolver) — bei kleinen Schwellen (z.B. 150 W) wird daraus 100 W; relativ (z.B. 10 %) wäre robuster.
- **O6 Tests fehlen** für `coordinator`, `safety_manager`, `temperature_calculator` (nur Helper getestet). Bei Tier-1/2-Fixes gleich mitschreiben.
- **O7 `async_unload_entry`** (`__init__.py:270`) Kommentar „schalte Heizungen aus" tut nichts. Für Wasserbett bewusst NICHT ausschalten — Kommentar korrigieren statt Logik ändern.
- **O8 Typing/Docs:** viele Methoden ohne Rückgabe-Typ; `Dict`/`Optional` aus `typing` teils ungenutzt.
- **O9 `manual_preset` COMFORT** nie gesetzt; `comfort_offset` (Option) wird nirgends angewandt — Feature unvollständig (mit #8 klären).

---

## Reihenfolge-Empfehlung
1. **PR A (Tier 1 Safety):** #1 #2 #3 + `test_safety_manager.py`.
2. **PR B (Tier 2):** #4 #5 #7 #8 + Tests.
3. **PR C:** #6 + manifest `single_config_entry`.
4. **PR D:** CI (Tier 4).
5. **PR E+:** Refactor #9 zuerst (entsperrt Coordinator-Tests), dann #10-#12 + O1-O9.

## Nächste Sitzung: Daten vom Nutzer
- Sensorwerte (Wasser-Temp, Solar-W, Akku-SoC, Forecast-kWh, Strompreis) + Historien → echte Schwellen für Solar-Boost/Präsenz tunen, jetzt wo Sommer/PV aktiv ist.
