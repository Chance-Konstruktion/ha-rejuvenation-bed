# 🛏️ Rejuvenation Bed

**Intelligent bed heating controller for Home Assistant**

[![HACS Badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/integration)
[![Version](https://img.shields.io/badge/version-0.7.1-blue.svg)](https://github.com/Chance-Konstruktion/ha-rejuvenation-bed/releases)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

🇩🇪 [Deutsche Version](README_DE.md)

Transforms any bed heater into a self-learning sleep AI. Biorhythm-based temperature curve, bedtime prediction, solar energy as thermal battery, presence detection and auto-calibration. Works with waterbeds, heating pads and heated mattress toppers.

---

## What does it do?

Instead of heating to a fixed temperature, Rejuvenation Bed adjusts the temperature throughout the night based on your sleep rhythm:

- **Falling asleep** – Slightly elevated temperature for comfort
- **Deep sleep** – 1–2°C reduction for optimal recovery
- **Waking up** – Gentle warming before your alarm
- **Daytime** – Standby, solar surplus stored as heat

The system automatically learns your bedtime and the optimal thresholds for your specific bed.

---

## Features

**Core functions** – Biorhythm curve with chronotype adjustment (early bird/normal/night owl), alarm integration (phone alarm, fixed time or hybrid), seasonal adjustment via outdoor temperature, dual-zone for partners.

**Energy management** – Solar boost uses PV surplus as thermal battery. Dynamic electricity prices (Tibber, Octopus, ENTSO-E). Energy tracking with kWh, heating hours and savings calculation. Thermal battery as percentage sensor.

**Intelligence** – Presence detection through water temperature variance (no extra sensor needed). Auto-calibration in 3–5 days. Insulation detection (blanket on/off). Sweat detection via cross-correlation. Sleep score 0–100. Learning-based preheating.

**Safety** – Overheat protection (max 36°C), fail-safe on sensor failure, startup grace period, anti-short-cycle, outlier filter, leak alarm. Optional sensors can fail at any time without affecting core functionality.

---

## Hardware Levels

| Level | Hardware | Features |
|-------|----------|----------|
| **A** | Smart plug | Timer, boost, vacation |
| **B** | + Temperature sensor | + Biorhythm, presence, sleep score |
| **C** | + Power sensor | + Energy tracking, better presence |
| **D** | + SHT41 (air/humidity) | + Insulation check, sweat detection, leak alarm |

Minimum: A smart plug that switches the heater.

---

## Installation

### HACS (recommended)

1. HACS → Integrations → ⋮ → Custom Repositories
2. URL: `https://github.com/Chance-Konstruktion/ha-rejuvenation-bed`
3. Category: Integration
4. Install → Restart Home Assistant

### Manual

Copy `custom_components/rejuvenation_bed/` to `config/custom_components/`, restart HA, add integration.

---

## Configuration

The setup wizard guides through all steps. Afterwards, four areas are accessible via options flow:

**🌐 Global Settings** – Split into Times & Temperature (warm window, summer threshold, offset, bed volume) and Sensors & Electricity Price (solar, price sensor, fixed tariff, CO₂).

**📡 Zone Sensors** – Hardware per zone: heater switch (required), temperature, power, presence, humidity, surface temperature.

**🌡️ Sleep Profile** – Per zone: alarm entity, weekend sleep-in, sleep temperatures (empty = seasonal automatic), wearable sensor.

**🎛️ Special Modes** – Sick (temperature, duration), boost (offset), vacation (holding temperature), comfort (sleep-in offset).

---

## Devices & Entities

The integration creates three devices in Home Assistant:

### 🛏️ Rejuvenation Bed (main device)

| Entity | Description |
|--------|------------|
| `climate.rejuvenation_bed` | Thermostat with target temperature and HVAC mode |
| `sensor.bett_zieltemperatur` | Calculated target temperature |
| `sensor.bett_status` | Current mode and decision reason |
| `sensor.bett_thermal_summary` | Temperature calculation breakdown |
| `binary_sensor.bett_prasenz` | Person in bed |
| `binary_sensor.bett_isolation` | Bed covered (requires SHT41) |
| `switch.bett_boost` | Quick heat |
| `switch.bett_krank_modus` | Sick mode |
| `switch.bett_tarifmodus` | Tariff mode (reduce temperature during expensive rates) |

### ⚡ Bed Energy

| Entity | Description |
|--------|------------|
| `sensor.bett_leistung` | Current power per zone (W) |
| `sensor.bett_gesamtleistung` | Total power all zones (W) |
| `sensor.bett_thermische_batterie` | Thermal storage charge level (%) |
| `sensor.bett_energie_heute` | Consumption today (kWh) |
| `sensor.bett_heizstunden` | Heating hours today |
| `sensor.bett_ersparnis` | Estimated savings (€) |
| `sensor.bett_solar_prozent` | Solar share of consumption |
| `sensor.bett_strompreis_status` | Current tariff mode |
| `switch.bett_solar_batterie` | Thermal battery |
| `switch.bett_urlaub_modus` | Vacation mode |

### 😴 Bed Sleep/Analysis

| Entity | Description |
|--------|------------|
| `sensor.bett_schlaf_score` | Last night (0–100) |
| `sensor.bett_schlaf_score_woche` | Weekly average |
| `sensor.bett_rampe` | Heat-up ramp status |
| `sensor.bett_intelligence` | Calibration and learning status |
| `binary_sensor.bett_degraded_mode` | Degraded mode (sensor failure) |
| `binary_sensor.bett_kondensationsrisiko` | Condensation risk (< 24°C) |
| `binary_sensor.bett_leckage_verdacht` | Leak suspicion |
| `binary_sensor.bett_schwitzen` | Sweat/moisture alarm |
| `binary_sensor.bett_system_status` | System health |

---

## Services

| Service | Description |
|---------|------------|
| `rejuvenation_bed.set_boost` | Activate quick heat (duration configurable) |
| `rejuvenation_bed.set_sick_mode` | Sick mode (temperature + days) |
| `rejuvenation_bed.set_vacation_mode` | Vacation mode with optional temperature and end date |
| `rejuvenation_bed.cancel_special_mode` | Cancel all special modes |
| `rejuvenation_bed.preheat_bed` | Preheat bed (temperature + duration) |
| `rejuvenation_bed.reset_energy_budget` | Reset energy statistics |

---

## Special Modes

| Mode | Activation | Effect |
|------|-----------|--------|
| **Boost** | `switch.bett_boost` | Quick heat: target temperature + offset for 60 min |
| **Sick** | `switch.bett_krank_modus` | Constant temperature for configurable days |
| **Vacation** | `switch.bett_urlaub_modus` or service | Minimal 24°C holding temperature (with optional temperature) |
| **Solar** | `switch.bett_solar_batterie` | Store PV surplus as heat |
| **Tariff** | `switch.bett_tarifmodus` | Reduce temperature during expensive rates |

---

## Dashboard Templates

Two ready-made dashboard templates in the `dashboards/` folder:

### Lovelace YAML (Nightstand Cockpit)

`dashboards/rejuvenation_bed_nightstand_cockpit.yaml` — Mobile/tablet-friendly Lovelace template. Adjust entity IDs to your installation.

### Standalone HTML (Premium Dashboard)

`dashboards/premium_nightstand_dashboard.html` — Standalone React/HTML dashboard with mini view (< 800px).

**Embed as panel:**

```yaml
panel_iframe:
  waterbed_cockpit:
    title: Waterbed Cockpit
    icon: mdi:bed-outline
    url: /local/rejuvenation_bed/premium_nightstand_dashboard.html
```

**Or as iframe card:**

```yaml
type: iframe
url: /local/rejuvenation_bed/premium_nightstand_dashboard.html
aspect_ratio: 100%
```

Copy file to `/config/www/rejuvenation_bed/`.

---

## Architecture

```
coordinator.py ─── Central 60s loop
 ├── safety_manager.py ──────── Overheat protection, fail-safe
 ├── temperature_calculator.py ─ Biorhythm curve, target temperature
 │   ├── biorhythmus_curve.py ── Sleep phase curve (chronotype)
 │   ├── wake_time_resolver.py ─ Alarm / fixed / hybrid
 │   └── sleep_stage_resolver.py Wearable integration
 ├── energy_state_resolver.py ── Solar / tariff / normal mode
 ├── presence_detector.py ────── Variance-based presence
 ├── bed_intelligence.py ─────── Calibration, insulation, sweat, bedtime learning
 ├── diagnostics_manager.py ──── Energy budget, thermal summary
 ├── ramp_controller.py ──────── Heat-up ramp (vinyl protection)
 ├── anti_short_cycle_manager.py Relay protection
 └── sleep_score_calculator.py ─ Sleep rating 0–100
```

22 modules · ~10,650 lines Python · Bilingual (DE/EN) · HACS compatible

---

## FAQ

**Does this only work with waterbeds?**
No. Any electric bed heater works: waterbed, heating pad, heated mattress topper. The biorhythm principle is universal.

**Do I need a temperature sensor?**
Recommended. Without a sensor, the system runs as an intelligent timer (Level A). With a sensor: full biorhythm curve and presence detection.

**What happens if a sensor fails?**
The integration degrades automatically. The SHT41 can fail without affecting heating. Even the water temperature sensor has a fail-safe (30% duty cycle).

**How does presence detection work with heating pads?**
Unlike waterbeds (variance analysis in the water body), heating pad detection uses the **temperature trend**: if the heater is off and the temperature still rises, someone is lying on it (body heat). This requires a temperature sensor on the pad. Without a sensor, presence detection is not available — the system runs as a timer (Level A). Detection is less precise than with waterbeds but works reliably after a short settling time (~3 min).

**Which temperature sensor?**
DS18B20 waterproof (IN the water) + optional SHT41 (ON TOP of the core).

---

## License

MIT License — see [LICENSE](LICENSE)

---

*Built with real sensor data from a 2×2m dual-core waterbed. Calibrated on 126,771 data points.*
