<div align="center">

<img src="https://raw.githubusercontent.com/Chance-Konstruktion/ha-rejuvenation-bed/main/assets/banner.svg" alt="Rejuvenation Bed" width="100%">

# 🛏️ Rejuvenation Bed

**A self-learning sleep AI for any heated bed.**

Biorhythm-based temperature curve, learned bedtime prediction, solar surplus stored as heat, presence detection without extra sensors — and a fail-safe that survives every sensor it depends on. Works with waterbeds, heating pads and heated mattress toppers.

### 🌒 → [**Open the editorial reading room**](https://chance-konstruktion.github.io/ha-rejuvenation-bed/)

*The full dark editorial site with animated biorhythm curve — the whole story.*

</div>

---

## ✦ Why this exists

A human body doesn't sleep at a constant temperature. It cools 1–2 °C on the way into deep sleep, warms again before the alarm, and reacts to season, partner, illness and a hundred small signals. Most bed heaters do it like a 1980s radiator: a single number, on or off, all night long.

Rejuvenation Bed follows the rhythm instead.

## ⌁ Highlights

- **🕯️ Biorhythm curve** — Chronotype-aware sleep-phase model (early bird / normal / night owl) with seasonal adjustment from outdoor temperature.
- **⏰ Alarm-aware wake** — Phone alarm, fixed time or hybrid. The bed warms *toward* your wake time, not *at* it.
- **🌗 Dual-zone for partners** — Two sleep profiles, two curves, one bed. Different chronotypes welcome.
- **🪫 Thermal battery** — Solar surplus is stored as heat, tracked as a 0–100 % charge sensor.
- **💶 Dynamic tariffs** — Tibber, Octopus, ENTSO-E or a fixed rate. Auto-reduces during expensive hours.
- **👤 Sensor-less presence** — Detects you in bed via water-temperature variance. No PIR, no mattress sensor required.
- **🛡️ Fail-safe first** — Overheat protection, anti-short-cycle and leak alarm are non-negotiable. Every optional sensor can fail without taking the heater with it.

## ⚙ Quick Start

1. Install via HACS (you're here 🎉), then restart Home Assistant.
2. **Settings → Devices & Services → Add Integration → "Rejuvenation Bed"**.
3. Pick your hardware level — from a bare switch to a fully sensored dual-zone bed. The flow adapts to what you have.

> 💡 Set your bed heater's physical thermostat to **maximum** so Home Assistant can regulate precisely. The hardware thermostat stays in the circuit as a safety backup.

## 📖 Full documentation

- **[Editorial site](https://chance-konstruktion.github.io/ha-rejuvenation-bed/)** — the visual story, animated curve and deep dive.
- **[README](https://github.com/Chance-Konstruktion/ha-rejuvenation-bed#readme)** — architecture, entities, services, FAQ.
- **[🇩🇪 Deutsch](https://github.com/Chance-Konstruktion/ha-rejuvenation-bed/blob/main/README_DE.md)** — deutsche Anleitung.

---

<div align="center">

Made for people who take sleep seriously. · [MIT License](https://github.com/Chance-Konstruktion/ha-rejuvenation-bed/blob/main/LICENSE)

</div>
