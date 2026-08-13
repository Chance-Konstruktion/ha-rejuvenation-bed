<div align="center">

<img src="assets/banner.svg" alt="Rejuvenation Bed" width="100%">

# 🛏️ Rejuvenation Bed

**A self-learning sleep AI for any heated bed.**

Biorhythm-based temperature curve, learned bedtime prediction, solar surplus stored as heat, presence detection without extra sensors, and a fail-safe that survives every sensor it depends on. Works with waterbeds, heating pads and heated mattress toppers.

[![HACS](https://img.shields.io/badge/HACS-Default-E8A33D.svg?style=flat-square)](https://github.com/hacs/integration)
[![Version](https://img.shields.io/badge/version-v260728-B47326.svg?style=flat-square)](https://github.com/Chance-Konstruktion/ha-rejuvenation-bed/releases)
[![License](https://img.shields.io/badge/license-MIT-7BA968.svg?style=flat-square)](LICENSE)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.6+-41BDF5.svg?style=flat-square)](https://www.home-assistant.io/)

[Quick Start](#-quick-start) · [Highlights](#-highlights) · [Architecture](#-architecture) · [Entities](#-entities--services) · [FAQ](#-faq) · [🇩🇪 Deutsch](README_DE.md)

</div>

> ### 🌒 → [**Open the editorial reading room**](https://chance-konstruktion.github.io/ha-rejuvenation-bed/)
> The full dark editorial site with animated biorhythm curve — the whole story.
> *(Source: [`docs/index.html`](docs/index.html))*

---

## ✦ Why this exists

> Your bed has one job at night — and most heaters do it like a 1980s radiator: a single number, on or off, all night long.

A human body doesn't sleep at a constant temperature. It cools 1–2 °C on the way into deep sleep, warms again before the alarm, and reacts to season, partner, illness and a hundred small signals. A waterbed has the inertia of a thermal flywheel; a heating pad reacts in seconds. The same target temperature is wrong for both, and wrong for any one of them across a whole night.

<table>
<tr>
<td width="33%" valign="top">

### 🌙 Follows the rhythm
A chronotype-aware curve that warms for falling asleep, dips for deep sleep, and rises again before the alarm — instead of holding a fixed setpoint.

</td>
<td width="33%" valign="top">

### ☀️ Charges with the sun
PV surplus is parked in the water body as a thermal battery. The night you've already paid for in daylight is the night you sleep through.

</td>
<td width="33%" valign="top">

### 🛡️ Degrades gracefully
Every optional sensor — humidity, surface temp, power — can fail without taking the heater with it. Overheat protection, anti-short-cycle and leak alarm are non-negotiable.

</td>
</tr>
</table>

---

## ⌁ Highlights

<table>
<tr>
<td width="50%" valign="top">

**🕯️ Biorhythm curve** — Chronotype-aware sleep phase model (early bird / normal / night owl) with seasonal adjustment from outdoor temperature.

</td>
<td width="50%" valign="top">

**⏰ Alarm-aware wake** — Phone alarm, fixed time or hybrid. The bed warms _toward_ your wake time, not _at_ it.

</td>
</tr>
<tr>
<td valign="top">

**🌗 Dual-zone for partners** — Two sleep profiles, two curves, one bed. Different chronotypes welcome.

</td>
<td valign="top">

**🪫 Thermal battery** — Solar surplus is stored as heat (a transitional-season / winter feature; paused in summer). Tracked as a 0–100 % charge sensor.

</td>
</tr>
<tr>
<td valign="top">

**💶 Dynamic tariffs** — Tibber, Octopus, ENTSO-E or a fixed rate. Auto-reduces during expensive hours.

</td>
<td valign="top">

**👤 Sensor-less presence** — Detects you in bed via water temperature variance. No PIR, no mattress sensor.

</td>
</tr>
<tr>
<td valign="top">

**🎯 Auto-calibration** — Learns your bed and your bedtime in 3–5 days. No manual offset tuning.

</td>
<td valign="top">

**📊 Sleep score 0–100** — Per night, per week. Cross-correlation catches sweat, condensation and leak suspicion.

</td>
</tr>
</table>

---

## ☾ Architecture

```
                        coordinator.py
                        60-second loop
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
   safety_manager     temperature_calculator   energy_state_resolver
   overheat · grace      biorhythm curve        solar · tariff · normal
   fail-safe · cycle           │
                               │
                ┌──────────────┼──────────────┐
                │              │              │
        biorhythmus_curve  wake_time_     sleep_stage_
        chronotype model    resolver        resolver
                            (alarm /        (wearable)
                             fixed /
                             hybrid)

   presence_detector  ←  bed_intelligence  →  diagnostics_manager
   variance-based         calibration ·         energy budget ·
                          insulation ·          thermal summary
                          sweat · bedtime
                          learning

        ramp_controller     anti_short_cycle     sleep_score
        vinyl protection    relay protection     0–100 rating
```

<details>
<summary><b>22 modules · bilingual (DE/EN) · HACS-compatible</b></summary>

The coordinator is the only thing that talks to Home Assistant; every module below it is pure logic, unit-testable in isolation. Sensors are advisory — the safety manager has the final word on the heater switch.

</details>

---

## ⚙ Quick Start

### 1 · Install via HACS

Rejuvenation Bed is listed in the HACS default repository — no custom
repository needed.

```
HACS → Integrations → Search "Rejuvenation Bed" → Install
```

Then **Restart Home Assistant**.

### 2 · Add the integration

```
Settings → Devices & Services → Add Integration → Rejuvenation Bed
```

The setup wizard asks for your heater switch first. Everything else is optional — you can come back later via the options flow.

### 3 · Pick a hardware level

| Level | What you have                       | What you get |
| :---: | :---------------------------------- | :----------- |
| **A** | A smart plug                        | Timer · boost · vacation |
| **B** | + water/pad temperature sensor      | + biorhythm · presence · sleep score |
| **C** | + power sensor                      | + energy tracking · sharper presence |
| **D** | + SHT41 (air/humidity)              | + insulation check · sweat detection · leak alarm |

> 💡 **Not technical?** Level A is one smart plug and one screen. The integration upgrades itself as you add sensors — nothing to reconfigure.

---

## ✦ Configuration

The options flow is split into four panes — each one a single page, no nesting.

<details>
<summary><b>🌐 Global Settings</b> — times, temperatures, sensors, electricity price</summary>

<br>

Split into three cards:

- **Times & Temperature** — warm window, manual offset, bed water volume in litres, and the two summer settings: the **summer threshold** (the *outdoor* temperature at which summer mode kicks in) and the **summer bed temperature** (the value the bed is *held* at in summer instead of running the sleep curve). Waterbeds stay clamped to ≥ 24 °C for condensation protection.
- **Sensors & Electricity Price** — dynamic price sensor or fixed tariff (ct/kWh), grid CO₂ intensity.
- **Solar & Battery** — solar production sensor + threshold, optional home-battery SoC sensor + threshold, optional PV forecast sensor + threshold, and a *home battery priority* toggle. Solar threshold, SoC and forecast act as independent triggers — any one starts Solar Boost; turn on battery priority to make the solar threshold wait for a full battery / generous forecast. Solar Boost is paused while summer mode is active (a warm bed in summer is pointless) — it's mainly a transitional-season / winter feature, and the status reflects that honestly instead of claiming "Solar Boost" while the bed is held cool.

</details>

<details>
<summary><b>📡 Zone Sensors</b> — hardware per zone</summary>

<br>

Per zone (one zone for single beds, two for dual-core waterbeds):

| Field             | Required | Notes |
| :---------------- | :------: | :--- |
| Heater switch     |    ✓     | Any `switch` or `input_boolean` |
| Temperature       |          | DS18B20 in the water, or a thermistor on the pad |
| Power             |          | Smart plug with energy metering |
| Presence override |          | Falls back to variance-based detection if missing |
| Humidity          |          | SHT41 — enables sweat / leak / insulation logic |
| Surface temp      |          | SHT41 — enables condensation alarm |

</details>

<details>
<summary><b>🌡️ Sleep Profile</b> — per zone</summary>

<br>

- Alarm entity (phone or HA `input_datetime`)
- Weekend sleep-in offset
- Sleep temperatures — leave empty for seasonal automatic
- Wearable sensor (optional sleep stage feed)

</details>

<details>
<summary><b>🎛️ Special Modes</b> — sick, boost, vacation, comfort</summary>

<br>

- **Sick** — constant temperature for N days
- **Boost** — target + offset for 60 min
- **Vacation** — minimal 24 °C holding (frost / condensation protection)
- **Comfort** — sleep-in offset for weekends and off-days

</details>

---

## ⚡ Entities & Services

<details>
<summary><b>🛏️ Rejuvenation Bed</b> — main device</summary>

<br>

| Entity                              | Description |
| :---------------------------------- | :--- |
| `climate.rejuvenation_bed`          | Thermostat with target temperature and HVAC mode |
| `sensor.bett_zieltemperatur`        | Calculated target temperature |
| `sensor.bett_status`                | Current mode and decision reason |
| `sensor.bett_thermal_summary`       | Temperature calculation breakdown |
| `binary_sensor.bett_prasenz`        | Person in bed |
| `binary_sensor.bett_isolation`      | Bed covered (requires SHT41) |
| `switch.bett_boost`                 | Quick heat |
| `switch.bett_krank_modus`           | Sick mode |
| `switch.bett_tarifmodus`            | Tariff mode (reduces during expensive rates) |

</details>

<details>
<summary><b>⚡ Bed Energy</b></summary>

<br>

| Entity                              | Description |
| :---------------------------------- | :--- |
| `sensor.bett_leistung`              | Current power per zone (W) |
| `sensor.bett_gesamtleistung`        | Total power all zones (W) |
| `sensor.bett_thermische_batterie`   | Thermal storage charge level (%) |
| `sensor.bett_energie_heute`         | Consumption today (kWh) |
| `sensor.bett_heizstunden`           | Heating hours today |
| `sensor.bett_ersparnis`             | Estimated savings (€) |
| `sensor.bett_solar_prozent`         | Solar share of consumption |
| `sensor.bett_strompreis_status`     | Current tariff mode |
| `switch.bett_solar_batterie`        | Thermal battery |
| `switch.bett_urlaub_modus`          | Vacation mode |

</details>

<details>
<summary><b>😴 Bed Sleep / Analysis</b></summary>

<br>

| Entity                                 | Description |
| :------------------------------------- | :--- |
| `sensor.bett_schlaf_score`             | Last night (0–100) |
| `sensor.bett_schlaf_score_woche`       | Weekly average |
| `sensor.bett_rampe`                    | Heat-up ramp status |
| `sensor.bett_intelligence`             | Calibration and learning status |
| `binary_sensor.bett_degraded_mode`     | Degraded mode (sensor failure) |
| `binary_sensor.bett_kondensationsrisiko` | Condensation risk (< 24 °C) |
| `binary_sensor.bett_leckage_verdacht`  | Leak suspicion |
| `binary_sensor.bett_schwitzen`         | Sweat / moisture alarm |
| `binary_sensor.bett_system_status`     | System health |

</details>

<details>
<summary><b>🛠 Services</b></summary>

<br>

| Service                                | Description |
| :------------------------------------- | :--- |
| `rejuvenation_bed.set_boost`           | Activate quick heat (duration configurable) |
| `rejuvenation_bed.set_sick_mode`       | Sick mode (temperature + days) |
| `rejuvenation_bed.set_vacation_mode`   | Vacation mode (temperature + end date) |
| `rejuvenation_bed.cancel_special_mode` | Cancel all special modes |
| `rejuvenation_bed.preheat_bed`         | Preheat bed (temperature + duration) |
| `rejuvenation_bed.reset_energy_budget` | Reset energy statistics |

</details>

<details>
<summary><b>🎚 Special Modes</b> — activation cheat-sheet</summary>

<br>

| Mode         | Activation                                      | Effect |
| :----------- | :---------------------------------------------- | :--- |
| **Boost**    | `switch.bett_boost`                             | Target + offset for 60 min |
| **Sick**     | `switch.bett_krank_modus`                       | Constant temperature for N days |
| **Vacation** | `switch.bett_urlaub_modus` or service           | Minimal 24 °C holding temperature |
| **Solar**    | `switch.bett_solar_batterie`                    | Store PV surplus as heat |
| **Tariff**   | `switch.bett_tarifmodus`                        | Reduce during expensive rates |

</details>

---

## 🌒 Dashboards

The integration ships a Lovelace card, `custom:rejuvenation-nightstand`, and
registers it with the frontend itself — nothing to copy into `/config/www`, no
resource to add by hand, no token and no second login. It talks to Home
Assistant through the same session you are already signed in to.

An alarm-clock face for the tablet next to the bed: pure-black AMOLED
background with amber accents, a large clock, and exactly three keys —
waterbed temperature (a draggable thermostat ring), alarm and bedroom lamp.

> ⚠️ **Requirement:** the card only exists from version **260728** on. After
> updating in HACS, restart Home Assistant so the integration can register the
> card, then hard-reload the browser (Ctrl+Shift+R; on a tablet clear the app
> cache). Without that the dashboard reports `Custom element doesn't exist:
> rejuvenation-nightstand`.

Create a dashboard, open its raw configuration editor and paste
`dashboards/nightstand.yaml`, adjusting the entity IDs. The view uses
`type: panel` so the card fills the screen; the button in the card's corner
takes it to true fullscreen without browser chrome.

```yaml
views:
  - type: panel
    cards:
      - type: custom:rejuvenation-nightstand
        beds:
          - name: Bedroom · left
            climate: climate.thermostat_bed_left
            alarm: input_datetime.alarm_left
            alarm_switch: input_boolean.alarm_left_active
            light: light.bedroom
```

**Or configure nothing at all.** Whatever the card is missing, it takes from the
integration: each zone's status sensor carries thermostat, alarm time, alarm
switch and lamp as an attribute, and the card reads them from there. Pick the
alarm switch and the lamp once under **Settings → Devices & Services →
Rejuvenation Bed → Configure → 🌡️ Sleep Profile**, and the dashboard needs no
more than:

```yaml
views:
  - type: panel
    cards:
      - type: custom:rejuvenation-nightstand
```

Two zones produce two bed entries by themselves. Anything written in the card
always wins; fields left empty come from the integration. The gear icon shows
under **Entitäten** which entity currently sits behind each key and where it
came from.

Entity IDs belong to a bed entry rather than to the card, so several beds in
one house — or two sides of the same bed — each get their own. Every device
remembers which one is its own, so you and your partner control your own sides
from your own phones. With more than one entry the bed's name appears in the
header and switches between them.

The card has a visual editor: add it through **Add card → Rejuvenation
Nachttischwecker** and pick the entities from dropdowns — one block per bed,
with buttons to add and remove beds. No entity IDs to type, no YAML required;
the raw editor above stays available for anyone who prefers it. On a card that
already exists the same editor opens through **Edit → pencil icon**.

Only entities that actually fit are offered: for the alarm, date/time helpers
with a time and sensors carrying a timestamp; for the thermostat, climate
entities with a target temperature; for the lamp, lights or switches. Anything
already configured stays selectable even while its entity is unavailable.

**One tap, one slider.** The lamp no longer opens a menu: it unfolds a dimmer
right below the key, next to "An / Aus" and "Nachtlicht". A second tap closes it
again, and when the card falls into its night state any open slider closes by
itself.

The clock stays silent on a tap: its two brightness sliders (*Aktiv* for use,
*Ruhe* for the dimmed night state) appear only after holding it for a good half
second, and a swipe does not count as a hold. The same sliders also live behind
the gear icon.

Clock face, brightness and layout live in the gear icon in the card's corner.
Faces: outline (the default — a filled digit throws too much light next to a
pillow), 7-segment, 5x7 LED matrix and split-flap. The face still changes only
here — half asleep you hit the clock too easily. All three settings are per
device, so one dashboard can look different on every screen.

**Layout** is *Automatic* by default: on a wide screen the clock moves to the
left and the three keys line up beside it, on a portrait tablet everything
stays stacked. *Portrait* and *Widescreen* force one of the two. On a very small
screen — a foldable's cover display, a watch-sized tile, up to roughly 420 points
per edge — the card switches to a compact version without a minimum height, so
the three keys stay reachable instead of being clipped off the bottom.

**From a cover display to a desktop.** The card is built for the whole span:
from a Galaxy Z Flip 5's cover display (720 × 748 pixels, roughly 360 × 374
points to the card) through phones and tablets up to a 2K desktop monitor
(2560 × 1440). At the bottom end it
shrinks to the compact version, at the top the clock grows and the three keys
move beside it — same card, same configuration, no second dashboard for the
small screen.

After 45 seconds without a touch everything but the clock fades away, and the
digits drift a few pixels every minute so nothing burns into an OLED panel
overnight. The first touch only wakes the screen — it never triggers a key by
accident.

The alarm uses ordinary helpers (a date/time helper set to "time only" plus a
toggle), created under Settings -> Devices & Services -> Helpers. They are
deliberately not part of the integration so your existing wake-up automation
keeps working.

---

## ❓ FAQ

<details>
<summary><b>Does this only work with waterbeds?</b></summary>

<br>

No. Any electric bed heater works — waterbed, heating pad, heated mattress topper. The biorhythm principle is universal; only the presence-detection strategy differs.

</details>

<details>
<summary><b>Do I need a temperature sensor?</b></summary>

<br>

Recommended. Without one, the system runs as an intelligent timer (Level A). With one, the full biorhythm curve and presence detection unlock.

</details>

<details>
<summary><b>What happens if a sensor fails?</b></summary>

<br>

The integration degrades automatically. The SHT41 can fail without affecting heating. Even the water temperature sensor has a fail-safe — a 30 % duty cycle fallback that keeps the bed warm but safe.

</details>

<details>
<summary><b>How does presence detection work on a heating pad?</b></summary>

<br>

Waterbeds use variance analysis inside the water body. Heating pads use the **temperature trend**: if the heater is off and the surface keeps rising, a body is on it. This needs a pad-mounted thermistor. Without a sensor, presence detection is disabled and the system runs as a Level-A timer. After a ~3-minute settling time, detection is reliable, if a touch less precise than on a waterbed.

</details>

<details>
<summary><b>Which temperature sensors do you recommend?</b></summary>

<br>

DS18B20 waterproof — in the water — plus an optional SHT41 on top of the core for humidity / surface temperature / leak detection.

</details>

---

## 🤝 Contributing

Issues and PRs are welcome. The Python core is fully unit-tested; please run `pytest` before opening a PR. Bilingual contributions (DE/EN) are appreciated but not required.

## 📄 License

[MIT](LICENSE) — do what you like, attribution appreciated.

---

<div align="center">

<sub>Built with real sensor data from a 2 × 2 m dual-core waterbed.<br>Calibrated on 126,771 data points · slept on every night since.</sub>

</div>
