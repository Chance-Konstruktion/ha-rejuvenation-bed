# Präsenz-Detector v11 — Wasser-Only, heizungs-bewusst

> Status: **aktiv** seit 0.7.1 — ersetzt v10.
> Datei: `custom_components/rejuvenation_bed/presence_detector.py`
> Test-Fassung: [`openclawde/rejuvenation-bed-presence-test/`](https://github.com/Chance-Konstruktion/openclawde/tree/main/rejuvenation-bed-presence-test)

## Problem in v10

v10 hat bei aktivem Solar-Boost regelmäßig "Person im Bett" gemeldet, während
das Bett leer war. Drei zusammenwirkende Ursachen:

1. **Quantisierungs-Rauschen wurde ignoriert.** Der DS18B20-Wassertemperatur-
   sensor hat 12-bit Auflösung = `0.0625 °C / LSB`. Daraus entsteht eine
   konstante Streuung σ ≈ 0.031 °C auch bei vollständig stillem, leerem Bett —
   nur durch das ±0.5-LSB-Wackeln zwischen zwei Quantisierungs-Stufen. Die
   alten Schwellen `chaos_threshold = 0.10` und `chaos_refresh_threshold = 0.06`
   liegen knapp über diesem Floor und werden bereits durch normale Heizungs-
   Bursts überschritten.
2. **Slope-Logik war nicht heizungs-bewusst.** Eine positive Slope (+0.20 °C/h)
   wurde uniform als "leer heizt auf" interpretiert. Bei aktivem Solar-Boost
   *und* leerem Bett stimmt das — bei Heizung *aus* dagegen ist eine positive
   Slope das eindeutige Signal für Körperwärme. v10 konnte beides nicht
   unterscheiden.
3. **`_apply_overrides` hat sekundäre Sensoren als Hard-Trigger benutzt.**
   `air_std > 2 × air_variance_threshold` setzte `raw_present = True`, auch
   wenn alle Wasser-Signale auf "leer" standen. Mit einem unzuverlässigen
   Luft-Sensor in der Nachbarschaft (Lüftung, offenes Fenster) war das eine
   sichere False-Positive-Quelle.

## Was v11 ändert

Die Änderungen sind **chirurgisch** auf die Entscheidungslogik beschränkt.
Alle Buffer-, Diagnose- und Hilfsfunktionen (`is_sweating`,
`is_potential_leak`, `_calculate_slope_per_hour`, `get_diagnostics` etc.)
bleiben bit-identisch. Externe Aufrufer in `coordinator.py`,
`bed_intelligence.py`, `binary_sensor.py` brauchen **keine** Anpassung.

### Threshold-Diff

| Konstante | v10 | v11 | Begründung |
|---|---|---|---|
| `chaos_threshold` | 0.10 | **0.05** | über Quantisierungs-Floor (~0.031) |
| `chaos_refresh_threshold` | 0.06 | **0.045** | analog, frischt Lock auf |
| `chaos_lock_minutes` | 30 | **25** | symmetrisch zu `presence_leave_minutes` |
| `slope_heating_threshold` | 0.20 | **0.40** | strenger, da nur bei `heater_active=True` aktiv |
| `slope_body_warming` | — | **0.25** | NEU: nur bei `heater_active=False` |
| `slope_cooling_threshold` | -0.10 | -0.10 | unverändert |
| `slope_stable_band` | 0.10 | **0.08** | enger, weniger Drift-Falsche |
| `slope_rise_threshold` | 0.15 | **0.20** | Person-erkennung erst nach klarem Anstieg |
| `presence_enter_minutes` | 5 | **8** | kein Flackern bei Heizungs-Bursts |
| `presence_leave_minutes` | 20 | **25** | keine Fehlausstiege bei Toilettengängen |

### Entscheidungslogik (v11, in Reihenfolge)

```
1) presence_sensor_state ist gesetzt          → übersteuert alles (unverändert)
2) is_heating_pad                             → Heizmatten-Pfad (unverändert)
   [v11.1] heater off + slope < -0.05 + stale → STALE-COOLDOWN: not present (bricht Lock)
3) σ_d_long > chaos_refresh_threshold         → Chaos-Lock auffrischen (NICHT wenn _empty_confirmed)
4) σ_d > chaos_threshold (0.055)              → CHAOS = present, Lock auffrischen
5) Chaos-Lock noch aktiv (<25 min)            → halte present (NICHT wenn _empty_confirmed)
6) slope is None                              → halte alten Status

7) heater_active == True:
   slope > slope_heating_threshold (0.40)     → leer heizt auf → not present
   |slope| < stable_band UND prev > rise_thr  → Person eingestiegen → present

8) heater_active == False:
   slope > slope_body_warming (0.25)          → Körperwärme → present
   slope < slope_cooling_threshold (-0.10)    → leer kühlt aus → not present
   |slope| < stable_band UND prev > rise_thr  → Person eingestiegen → present

9) sonst                                      → halte alten Status
```

### Was rausgeflogen ist aus dem Trigger-Pfad

`_apply_overrides()` ist **nicht mehr aufgerufen** vom Entscheidungsbaum.
Sie ist als Methode noch da (Tests / externe Aufrufer könnten sie direkt
aufrufen), hat aber keinen Einfluss mehr auf die `is_present`-Entscheidung
des Detectors:

- `air_std` (Luft-Temperatur-Streuung)
- `surface_temp - water_temp` (Auflage-Differenz / Körperkontakt-Δ)
- `air_variance_threshold * 2` Hard-Override

Diese Werte bleiben in den Diagnose-Buffern und in `get_diagnostics()` unter
`air_temp_std` sichtbar — sie werden nur nicht mehr als Präsenz-Signal
interpretiert.

## Validierung

Replay gegen den echten Nacht-Datensatz `pres.csv` (2026-04-28 22:00 UTC bis
2026-04-29 20:00 UTC, 1 037 Wasser-Samples bei 30-s Intervall):

| | Original `binary_sensor.bett_prasenz` | v11 |
|---|---|---|
| Flips über 22 h | 9 | **4** |
| Solar-Boost Phase (12:50–15:50) | 6 spurious Flips | 0 Flips |
| Frühe Heiz-Phase (03:00–04:30) | als Präsenz erkannt | als Präsenz erkannt |
| Spätes Cooldown (18:22+) | korrekt OFF | korrekt OFF |

Die 85 % "Accuracy" gegen den ursprünglichen Sensor ist **unter**\-bewertet,
weil die Labels selbst der zu-fixende Sensor sind. Echte Tests gegen Schlaf-
ground-truth (Fitbit, manuell) erfordern ein paar Nächte Laufzeit.

## Wie weiter tunen?

Der eingerichtete Test-Sandbox unter
`openclawde/rejuvenation-bed-presence-test/` enthält eine standalone Kopie
der gleichen Logik plus ein CSV-Replay-Skript:

```bash
python3 rejuvenation-bed-presence-test/scripts/replay_presence_csv.py \
    pres.csv --interval-seconds 30
```

Das Skript akzeptiert sowohl die Wide-CSV-Form
(`timestamp,water_temp,heater_active,actual_present`) als auch das HA Long-
Export-Format (`entity_id,state,last_changed`) mit Forward-Fill.

Falls die Schwellen für ein anderes Sensor-Modell justiert werden müssen,
geschieht das über `PresenceThresholds(...)` beim Detector-Konstruktor —
ohne Code-Änderung. Beispiel im Coordinator-Setup:

```python
from .presence_detector import PresenceDetector, PresenceThresholds

detector = PresenceDetector(
    PresenceThresholds(
        chaos_threshold=0.04,        # höher-aufgelöster Sensor
        chaos_refresh_threshold=0.035,
        slope_body_warming=0.30,     # trägeres Bett
    )
)
```

## v11.1 — Stale-Cooldown-Release

> Status: **aktiv**. Behebt einen ~12-Stunden-Hänger, der erst mit echter
> Heizungs-Historie sichtbar wurde.

### Problem in v11

Validierungs-Datensatz: ein **Tag-Schlaf** (Nutzer lag 06:00–14:00 CEST) mit
Wassertemperatur **und** Heizungs-Switch (`switch.plug_fibaro_1`). Die Heizung
war die **gesamte** Belegzeit aus — das Bett hielt sich allein über Körperwärme
+ thermische Masse warm.

Beobachtung nach dem Aufstehen (14:00 CEST):

1. **Auskühlung flacher als die Schwelle.** Das warme, leere Bett verliert nur
   ~0.06–0.16 °C/h — `slope_cooling_threshold` (−0.10) wird nur kurz touchiert,
   meist nicht erreicht. Die „leer kühlt aus"-Regel feuert also nicht zuverlässig.
2. **σ60-Rauschen ≈ Refresh-Schwelle.** Das leere Bett erzeugt über 60 min ein
   detrendetes σ von ~0.045–0.05 — exakt auf `chaos_refresh_threshold` (0.045).
   Der Chaos-Lock frischt sich dadurch alle paar Minuten selbst auf und hält ON.
3. **Folge:** die heizungs-bewusste Slope-Logik wird vom Lock kurzgeschlossen,
   bevor sie überhaupt ausgewertet wird → Sensor blieb ~12 h fälschlich „belegt".

Wichtig: `heat_ratio` trennt hier **nicht** belegt/leer — der Heizungs-Duty war
in **beiden** Phasen 0 %. Der saubere Trenner ist die Kombination *Heizung aus +
anhaltende Auskühlung + keine echten Bewegungs-Bursts*.

### Was v11.1 ändert

| Konstante | v11 | v11.1 | Begründung |
|---|---|---|---|
| `chaos_threshold` | 0.05 | **0.055** | über dem Leer-σ-Floor dieses Setups (Spitzen ~0.051) |
| `slope_cooldown_release` | — | **−0.05** | NEU: sanfte, *anhaltende* Auskühlung = leer |
| `cooldown_release_minutes` | — | **90** | NEU: so lange kein echter Burst ⇒ Person ist raus |

Neue Logik (greift **vor** dem Chaos-Lock):

```
0) Heizung AUS  UND  slope < slope_cooldown_release (−0.05)
   UND  seit cooldown_release_minutes kein echter Burst (σ_d > chaos_threshold)
   → STALE-COOLDOWN: not present, bricht den Lock, setzt _empty_confirmed
```

- **`_empty_confirmed`**: einmal als leer bestätigt, ignoriert der Detector den
  σ60-Refresh **und** den Lock-Hold, bis ECHTE Wiedereinstiegs-Evidenz kommt
  (Bewegungs-Burst, Körperwärme-Anstieg oder rise→stable). Verhindert, dass ein
  kurzer Heiz-Burst das leere Bett wieder „aufweckt" (Nachmittags-Blip).
- **`_last_burst_time`**: echte Bursts werden getrennt vom σ60-Lock-Refresh
  getrackt — nur sie setzen den Stale-Timer zurück.

### Validierung

Replay des echten Detectors gegen beide Nacht-Datensätze (mit Heizungs-Forward-Fill):

| | Tag-Schlaf (history2) | `pres.csv` |
|---|---|---|
| ON (Einstieg) | 05:29 CEST — deckt sich mit dem realen Sensor (`03:29:06 UTC`) | 05:14 CEST |
| OFF (Ausstieg) | **13:52 CEST** (≈ Ground-Truth 14:00) statt *nie* | 20:05 CEST (abends, keine Spurious-Flips) |
| Flips gesamt | 2 (statt 1 + 12 h Hänger) | 2 (unverändert sauber) |

Die 39 Presence-Unit-Tests bleiben grün; drei neue Regressions-Tests
(`TestStaleCooldownRelease`) sichern Release, Blip-Schutz und Wiedereinstieg ab.

## Migrations-Hinweise

- **Keine Breaking Changes** in der Public-API. `detect_presence()` und
  `get_diagnostics()` haben dieselbe Signatur und Felder wie v10.
- **v11.1:** `chaos_threshold` ist jetzt 0.055; neu sind `slope_cooldown_release`
  und `cooldown_release_minutes`. Wer `PresenceThresholds` per Custom-Init
  überschreibt, erbt die neuen Defaults automatisch.
- **Tuning-Werte** in `PresenceThresholds` haben neue Defaults. Wer das per
  Custom-Init überschrieben hatte, sollte einmal kurz prüfen ob die alten
  Werte (`chaos_threshold = 0.10`) immer noch gewollt sind — die alten
  Werte sind in **diesem** Sensor-Setup nachweislich problematisch.
- **`get_diagnostics()`** liefert jetzt zusätzlich die Reason-Tags
  `heat=on/off` und `heat%=...%` für einfacheres Debuggen im Dashboard.
