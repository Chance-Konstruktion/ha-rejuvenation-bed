# 🛏️ Rejuvenation Bed

**Intelligent waterbed & heating pad controller for Home Assistant**

[![HACS Badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![Version](https://img.shields.io/badge/version-0.3.2-blue.svg)](https://github.com/Chance-Konstruktion/ha-rejuvenation-bed/releases)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

🇩🇪 [Deutsche Version](README.md)

Transforms your waterbed from a simple heater into a self-learning sleep AI. Biorhythm-based temperature curve, solar energy as thermal battery, presence detection through water temperature variance, sweat detection and auto-calibration — all from real sensor data.

---

## What does it do?

Instead of heating to a fixed temperature, Rejuvenation Bed adjusts the water temperature throughout the night based on your sleep rhythm:

- **Falling asleep**: Slightly elevated temperature for comfort
- **Deep sleep**: 1–2°C reduction (promotes regeneration)
- **Waking up**: Gentle warming before your alarm
- **Daytime**: Minimal maintenance heating, use solar surplus as thermal battery

The system automatically learns the optimal thresholds for your specific bed.

---

## Features

### Core
- **Biorhythm curve** — Temperature follows circadian rhythm (early bird / normal / night owl)
- **Alarm integration** — Wake-up curve adapts to phone alarm or fixed time
- **Seasonal adjustment** — Cooler in summer, warmer in winter (via outdoor temperature)
- **Dual-zone** — Two separate heating zones for partners with different warmth preferences

### Energy Management
- **Solar boost** — Free PV surplus stored as heat (400kg water = thermal battery!)
- **Dynamic tariff** — Heat less at high prices, more at low prices
- **Energy tracking** — kWh today/total, heating hours, daily average
- **Savings vs. legacy** — Percentage saved compared to standard thermostat

### Intelligence (v0.3.0+)
- **Presence detection** — Detects occupancy through water temperature variance (no extra sensor needed!)
- **Auto-calibration** — Learns optimal thresholds in 3–5 days
- **Insulation detection** — Detects whether bed is covered (optional, with SHT41)
- **Sweat detection 2.0** — Cross-correlation temperature × humidity
- **Sleep score** — 0–100 points based on temperature stability, CO₂ and timing

### Safety
- **Overheat protection** — Hardware limit never exceeded (max 36°C)
- **Fail-safe** — On sensor failure: heater continues at 30% duty cycle
- **Anti-short-cycle** — Prevents rapid on/off switching (relay protection)
- **Leak alarm** — Warning on persistently high humidity (>3h)
- **Condensation warning** — Alert when water temp drops below 24°C

---

## Hardware Levels

The integration works with varying amounts of hardware:

| Level | Hardware | Features |
|-------|----------|----------|
| **A — Basic** | Smart plug only | Timer, boost, vacation mode |
| **B — Smart** | + Power sensor | + Energy tracking, better presence |
| **C — Full** | + Temperature sensor (DS18B20) | + Biorhythm, sleep score, variance-based presence |
| **C+** | + Humidity / air temp (SHT41) | + Sweat 2.0, insulation detection, leak alarm |

**Minimum**: A smart plug that switches the heater. Everything else is optional.

---

## Installation

### HACS (recommended)

1. Open HACS → Integrations → ⋮ Menu → **Custom Repositories**
2. Enter URL: `https://github.com/Chance-Konstruktion/ha-rejuvenation-bed`
3. Category: **Integration**
4. Install and restart Home Assistant

### Manual

1. Copy the `custom_components/rejuvenation_bed/` folder into your HA `config/custom_components/`
2. Restart Home Assistant
3. Settings → Devices & Services → Add Integration → "Rejuvenation Bed"

---

## Configuration

The setup wizard guides you through all steps:

1. **Bed type** — Waterbed or heating pad
2. **Zones** — Mono (1 heater) or dual (2 separate sides)
3. **Sensors per zone:**
   - Heater switch (required)
   - Water temperature sensor (recommended, DS18B20)
   - Power sensor (optional, from smart plug)
   - Presence sensor (optional, pressure mat / mmWave)
   - Humidity sensor (optional, SHT41)
   - Surface temperature top (optional, SHT41)
4. **Global settings:**
   - Warm from / warm until (bedtime)
   - Alarm entity (phone alarm)
   - Chronotype (early bird / normal / night owl)
   - Solar / electricity price sensor
   - Outdoor temperature
5. **Energy tracking** — Consumption, savings, comparison with standard thermostat

All settings can be changed afterwards via the options flow.

---

## Entities

The integration automatically creates the following entities:

### Climate
| Entity | Description |
|--------|------------|
| `climate.rejuvenation_bed` | Main thermostat (target temp, HVAC mode) |

### Sensors
| Entity | Description |
|--------|------------|
| `sensor.bett_zieltemperatur` | Current calculated target temperature |
| `sensor.bett_status` | Current mode and decision reason |
| `sensor.bett_gesamtleistung` | Current power in watts |
| `sensor.bett_energie_gesamt` | Total energy since installation (kWh) |
| `sensor.bett_energie_heute` | Today's consumption (kWh) |
| `sensor.bett_intelligence` | Calibration status (learning X% / calibrated) |

### Binary Sensors
| Entity | Description |
|--------|------------|
| `binary_sensor.bett_prasenz` | Person in bed detected |
| `binary_sensor.bett_schwitzerkennung` | Sweat / wetness alarm |
| `binary_sensor.bett_isolation` | Bed covered (requires SHT41) |
| `binary_sensor.bett_system_status` | System health (watchdog) |

### Switches
| Entity | Description |
|--------|------------|
| `switch.bett_boost` | Quick heat on/off |
| `switch.bett_solar_batterie` | Thermal battery on/off |
| `switch.bett_eco_modus` | Tariff mode on/off |

---

## Architecture

```
coordinator.py ─── Central 30s loop
 ├── safety_manager.py ──────── Overheat protection, fail-safe
 ├── temperature_calculator.py ─ Biorhythm curve, target temperature
 │   ├── biorhythmus_curve.py ── Sleep phase curve (chronotype)
 │   ├── wake_time_resolver.py ─ Alarm / fixed / hybrid
 │   └── sleep_stage_resolver.py Wearable integration
 ├── energy_state_resolver.py ── Solar / tariff / normal mode
 ├── energy_calculator.py ────── Consumption calculation
 ├── presence_detector.py ────── Variance-based presence
 ├── bed_intelligence.py ─────── Auto-calibration, insulation, sweat 2.0
 ├── diagnostics_manager.py ──── Energy budget, persistent storage
 ├── ramp_controller.py ──────── Heat-up ramp (waterbed)
 ├── anti_short_cycle_manager.py Relay protection
 └── sleep_score_calculator.py ─ Sleep rating 0-100
```

22 modules · ~9,400 lines Python · Bilingual (DE/EN) · HACS compatible

---

## Auto-Calibration

On first start, the integration enters **learning mode**. It automatically measures:

- Water temperature variance when bed is empty vs. occupied
- Humidity baseline
- Temperature delta between water and surface

After ~3–5 days of normal use (~300 samples), thresholds are calibrated. Status is visible in `sensor.bett_intelligence`:

- `Lernphase (67%)` → Still collecting data
- `Kalibriert` → Thresholds optimized

Calibration data survives HA restarts.

---

## License

MIT License — see [LICENSE](LICENSE)

---

*Built with real sensor data from a 2×2m dual-core waterbed. Calibrated on 126,771 data points.*
