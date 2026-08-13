"""Tests for EnergyStateResolver - the independent Solar-Boost triggers.

Solar-Boost has THREE independent OR-triggers. Each works on its own and
all of them work together:

  1. Solar threshold — current PV power >= threshold (classic behaviour).
  2. Battery SoC     — home battery SoC >= threshold (battery already full).
  3. PV forecast     — remaining-today forecast >= threshold (optional).

A single satisfied trigger is enough for boost. A sensor that is not
configured (or unavailable) simply does not contribute — it never blocks
the boost. So a solar-only setup behaves exactly as before, SoC works
independently of the solar threshold, and both combine when configured.

The cheap-grid-electricity path (< 15 ct/kWh) still triggers boost
independently of the PV triggers (it's grid energy, not PV surplus).
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.rejuvenation_bed.energy_state_resolver import (
    EnergyMode,
    EnergyStateResolver,
)


def _make_state(value):
    """Build a HA-state-like object with a .state attribute."""
    if value is None:
        return SimpleNamespace(state="unavailable")
    return SimpleNamespace(state=str(value))


def _make_resolver(
    *,
    solar_power=0.0,
    price=None,
    battery_soc=None,
    forecast_kwh=None,
    solar_sensor="sensor.solar",
    battery_sensor=None,
    forecast_sensor=None,
    options=None,
    solar_enabled=True,
):
    """Build a resolver with mocked hass states.

    Configures only the sensors that are passed (None = not configured).
    """
    opts = {}
    if solar_sensor:
        opts["solar_sensor"] = solar_sensor
    if battery_sensor:
        opts["battery_soc_sensor"] = battery_sensor
    if forecast_sensor:
        opts["forecast_sensor"] = forecast_sensor
    if options:
        opts.update(options)

    config_entry = SimpleNamespace(
        options=opts,
        data={"global": {}},
    )

    states = {}
    if solar_sensor:
        states[solar_sensor] = _make_state(solar_power)
    if battery_sensor:
        states[battery_sensor] = _make_state(battery_soc)
    if forecast_sensor:
        states[forecast_sensor] = _make_state(forecast_kwh)
    if price is not None:
        opts["price_sensor"] = "sensor.price"
        states["sensor.price"] = _make_state(price)

    hass = MagicMock()
    hass.states.get = lambda eid: states.get(eid)

    resolver = EnergyStateResolver(hass, config_entry)
    # Switches: solar on, eco off (defaults)
    resolver._coordinator = SimpleNamespace(
        thermal_battery_enabled=solar_enabled,
        eco_mode_enabled=False,
    )
    return resolver


class TestSolarOnly:
    """Only the solar sensor: classic threshold behaviour, unchanged."""

    def test_boost_fires_with_only_solar(self):
        r = _make_resolver(solar_power=1000)
        state = r.resolve()
        assert state["mode"] == EnergyMode.SOLAR_BOOST
        assert state["boost_available"] is True

    def test_no_boost_below_solar_threshold(self):
        r = _make_resolver(solar_power=300)
        state = r.resolve()
        assert state["mode"] == EnergyMode.NORMAL

    def test_custom_solar_threshold(self):
        r = _make_resolver(
            solar_power=350,
            options={"solar_boost_threshold": 300},
        )
        assert r.resolve()["mode"] == EnergyMode.SOLAR_BOOST


class TestSolarTriggerIndependentOfSoC:
    """The solar threshold triggers on its own — even when SoC is low.

    This is the v260619 change: SoC no longer gates the solar threshold.
    """

    def test_high_solar_boosts_even_if_battery_low(self):
        r = _make_resolver(
            solar_power=1000,
            battery_soc=70.0,
            battery_sensor="sensor.akku",
        )
        state = r.resolve()
        assert state["mode"] == EnergyMode.SOLAR_BOOST
        assert state["active_triggers"]["solar"] is True
        assert state["active_triggers"]["soc"] is False

    def test_low_solar_low_battery_no_boost(self):
        r = _make_resolver(
            solar_power=300,
            battery_soc=70.0,
            battery_sensor="sensor.akku",
        )
        assert r.resolve()["mode"] == EnergyMode.NORMAL


class TestSoCTriggerIndependentOfSolar:
    """The SoC threshold triggers on its own — even with no/low solar.

    SoC works independently of the solar threshold.
    """

    def test_full_battery_boosts_without_solar_sensor(self):
        r = _make_resolver(
            solar_sensor=None,
            battery_soc=95.0,
            battery_sensor="sensor.akku",
        )
        state = r.resolve()
        assert state["mode"] == EnergyMode.SOLAR_BOOST
        assert state["active_triggers"]["soc"] is True

    def test_full_battery_boosts_even_with_low_solar(self):
        r = _make_resolver(
            solar_power=200,
            battery_soc=95.0,
            battery_sensor="sensor.akku",
        )
        assert r.resolve()["mode"] == EnergyMode.SOLAR_BOOST

    def test_low_battery_no_solar_no_boost(self):
        r = _make_resolver(
            solar_sensor=None,
            battery_soc=70.0,
            battery_sensor="sensor.akku",
        )
        assert r.resolve()["mode"] == EnergyMode.NORMAL

    def test_soc_at_exact_threshold(self):
        r = _make_resolver(
            solar_power=0,
            battery_soc=90.0,
            battery_sensor="sensor.akku",
        )
        assert r.resolve()["mode"] == EnergyMode.SOLAR_BOOST

    def test_custom_soc_threshold(self):
        r = _make_resolver(
            solar_power=0,
            battery_soc=80.0,
            battery_sensor="sensor.akku",
            options={"bed_boost_soc_threshold": 75.0},
        )
        assert r.resolve()["mode"] == EnergyMode.SOLAR_BOOST


class TestForecastTriggerOptional:
    """The forecast sensor is a purely optional extra trigger."""

    def test_forecast_boosts_on_its_own(self):
        r = _make_resolver(
            solar_power=0,
            forecast_kwh=8.0,
            forecast_sensor="sensor.forecast",
        )
        state = r.resolve()
        assert state["mode"] == EnergyMode.SOLAR_BOOST
        assert state["active_triggers"]["forecast"] is True

    def test_low_forecast_no_solar_no_boost(self):
        r = _make_resolver(
            solar_power=0,
            forecast_kwh=1.0,
            forecast_sensor="sensor.forecast",
        )
        assert r.resolve()["mode"] == EnergyMode.NORMAL

    def test_without_forecast_sensor_solar_still_works(self):
        """Forecast is optional: absence must not change solar behaviour."""
        r = _make_resolver(solar_power=1000)
        assert r.resolve()["mode"] == EnergyMode.SOLAR_BOOST
        assert r.resolve()["active_triggers"]["forecast"] is None


class TestTriggersTogether:
    """All three configured: OR-logic, any single trigger fires the boost."""

    def test_solar_fires_when_others_low(self):
        r = _make_resolver(
            solar_power=1000,
            battery_soc=60.0,
            forecast_kwh=0.5,
            battery_sensor="sensor.akku",
            forecast_sensor="sensor.forecast",
        )
        assert r.resolve()["mode"] == EnergyMode.SOLAR_BOOST

    def test_soc_fires_when_others_low(self):
        r = _make_resolver(
            solar_power=100,
            battery_soc=95.0,
            forecast_kwh=0.5,
            battery_sensor="sensor.akku",
            forecast_sensor="sensor.forecast",
        )
        assert r.resolve()["mode"] == EnergyMode.SOLAR_BOOST

    def test_forecast_fires_when_others_low(self):
        r = _make_resolver(
            solar_power=100,
            battery_soc=60.0,
            forecast_kwh=8.0,
            battery_sensor="sensor.akku",
            forecast_sensor="sensor.forecast",
        )
        assert r.resolve()["mode"] == EnergyMode.SOLAR_BOOST

    def test_all_low_no_boost(self):
        r = _make_resolver(
            solar_power=100,
            battery_soc=60.0,
            forecast_kwh=1.0,
            battery_sensor="sensor.akku",
            forecast_sensor="sensor.forecast",
        )
        assert r.resolve()["mode"] == EnergyMode.NORMAL


class TestSensorUnavailable:
    """Configured-but-unavailable sensors must not block other triggers."""

    def test_unavailable_soc_does_not_block_solar(self):
        r = _make_resolver(
            solar_power=1000,
            battery_soc=None,
            battery_sensor="sensor.akku",
        )
        assert r.resolve()["mode"] == EnergyMode.SOLAR_BOOST

    def test_all_unavailable_and_low_solar_no_boost(self):
        r = _make_resolver(
            solar_power=200,
            battery_soc=None,
            forecast_kwh=None,
            battery_sensor="sensor.akku",
            forecast_sensor="sensor.forecast",
        )
        state = r.resolve()
        assert state["mode"] == EnergyMode.NORMAL
        assert state["boost_available"] is False

    def test_unavailable_soc_other_trigger_fires(self):
        r = _make_resolver(
            solar_power=100,
            battery_soc=None,
            forecast_kwh=8.0,
            battery_sensor="sensor.akku",
            forecast_sensor="sensor.forecast",
        )
        assert r.resolve()["mode"] == EnergyMode.SOLAR_BOOST


class TestHysteresis:
    """Each trigger keeps the boost on across a small dip."""

    def test_solar_hysteresis_keeps_boost_on(self):
        r = _make_resolver(solar_power=1000)
        assert r.resolve()["mode"] == EnergyMode.SOLAR_BOOST

        # Drop to 460W: above off-threshold (500 - 50 = 450)
        r.hass.states.get = lambda eid: {
            "sensor.solar": _make_state(460),
        }.get(eid)
        assert r.resolve()["mode"] == EnergyMode.SOLAR_BOOST

        # Drop to 400W: below off-threshold
        r.hass.states.get = lambda eid: {
            "sensor.solar": _make_state(400),
        }.get(eid)
        assert r.resolve()["mode"] == EnergyMode.NORMAL

    def test_soc_hysteresis_keeps_boost_on(self):
        r = _make_resolver(
            solar_sensor=None,
            battery_soc=92.0,
            battery_sensor="sensor.akku",
        )
        assert r.resolve()["mode"] == EnergyMode.SOLAR_BOOST

        # Drop SoC to 86%: still above hysteresis floor (90 - 5 = 85)
        r.hass.states.get = lambda eid: {
            "sensor.akku": _make_state(86.0),
        }.get(eid)
        assert r.resolve()["mode"] == EnergyMode.SOLAR_BOOST

    def test_soc_hysteresis_releases_boost_below_floor(self):
        r = _make_resolver(
            solar_sensor=None,
            battery_soc=92.0,
            battery_sensor="sensor.akku",
        )
        assert r.resolve()["mode"] == EnergyMode.SOLAR_BOOST

        # Drop to 80%: below hysteresis floor (85)
        r.hass.states.get = lambda eid: {
            "sensor.akku": _make_state(80.0),
        }.get(eid)
        assert r.resolve()["mode"] == EnergyMode.NORMAL

    def test_forecast_hysteresis(self):
        r = _make_resolver(
            solar_sensor=None,
            forecast_kwh=3.5,
            forecast_sensor="sensor.forecast",
        )
        assert r.resolve()["mode"] == EnergyMode.SOLAR_BOOST

        # Drop to 2.5 kWh: still above hysteresis floor (3 - 1 = 2)
        r.hass.states.get = lambda eid: {
            "sensor.forecast": _make_state(2.5),
        }.get(eid)
        assert r.resolve()["mode"] == EnergyMode.SOLAR_BOOST

        # Drop to 1.5: below floor (2.0)
        r.hass.states.get = lambda eid: {
            "sensor.forecast": _make_state(1.5),
        }.get(eid)
        assert r.resolve()["mode"] == EnergyMode.NORMAL


class TestCheapPriceBypass:
    """Cheap grid electricity triggers boost independently of PV triggers."""

    def test_cheap_price_triggers_boost(self):
        r = _make_resolver(
            solar_power=100,
            price=0.10,
            battery_soc=50.0,
            battery_sensor="sensor.akku",
        )
        # Solar below threshold and SoC low, but cheap price kicks boost.
        assert r.resolve()["mode"] == EnergyMode.SOLAR_BOOST


class TestReasonStrings:
    """The reason string surfaces the active triggers for the UI."""

    def test_reason_lists_solar_and_soc(self):
        r = _make_resolver(
            solar_power=1000,
            battery_soc=92.0,
            battery_sensor="sensor.akku",
        )
        state = r.resolve()
        assert "Solar-Boost" in state["reason"]
        assert "Überschuss" in state["reason"]
        assert "Akku 92" in state["reason"]

    def test_reason_soc_only(self):
        r = _make_resolver(
            solar_sensor=None,
            battery_soc=95.0,
            battery_sensor="sensor.akku",
        )
        state = r.resolve()
        assert "Akku 95" in state["reason"]

    def test_reason_normal_when_nothing_fires(self):
        r = _make_resolver(solar_power=100)
        assert r.resolve()["reason"] == "✅ Normal-Betrieb"


class TestSwitchInteraction:
    """The user's thermal_battery switch still blocks everything."""

    def test_switch_off_blocks_boost_even_with_triggers_green(self):
        r = _make_resolver(
            solar_power=1000,
            battery_soc=95.0,
            battery_sensor="sensor.akku",
            solar_enabled=False,
        )
        assert r.resolve()["mode"] == EnergyMode.NORMAL


class TestBatteryPriority:
    """Optional battery_priority gates the solar threshold behind SoC/forecast.

    On: solar threshold only fires when the battery/forecast also release it
    (the classic AND gating). Off (default): independent OR-triggers.
    """

    def test_high_solar_low_battery_blocked_when_priority_on(self):
        r = _make_resolver(
            solar_power=1000,
            battery_soc=70.0,
            battery_sensor="sensor.akku",
            options={"battery_priority": True},
        )
        state = r.resolve()
        assert state["mode"] == EnergyMode.NORMAL
        assert state["boost_waiting"] is True
        assert "wartet" in state["reason"]
        assert "70" in state["reason"]

    def test_high_solar_full_battery_boosts_when_priority_on(self):
        r = _make_resolver(
            solar_power=1000,
            battery_soc=95.0,
            battery_sensor="sensor.akku",
            options={"battery_priority": True},
        )
        assert r.resolve()["mode"] == EnergyMode.SOLAR_BOOST

    def test_soc_alone_does_not_boost_when_priority_on(self):
        """With priority on, a full battery but low solar must NOT boost."""
        r = _make_resolver(
            solar_power=200,
            battery_soc=95.0,
            battery_sensor="sensor.akku",
            options={"battery_priority": True},
        )
        assert r.resolve()["mode"] == EnergyMode.NORMAL

    def test_forecast_generous_unblocks_when_priority_on(self):
        r = _make_resolver(
            solar_power=1000,
            battery_soc=60.0,
            forecast_kwh=8.0,
            battery_sensor="sensor.akku",
            forecast_sensor="sensor.forecast",
            options={"battery_priority": True},
        )
        assert r.resolve()["mode"] == EnergyMode.SOLAR_BOOST

    def test_priority_on_without_reserve_sensor_is_classic_solar(self):
        """No battery/forecast sensor → priority has no effect (classic)."""
        r = _make_resolver(
            solar_power=1000,
            options={"battery_priority": True},
        )
        assert r.resolve()["mode"] == EnergyMode.SOLAR_BOOST

    def test_default_is_independent_or(self):
        """Without the option, high solar + low battery still boosts."""
        r = _make_resolver(
            solar_power=1000,
            battery_soc=70.0,
            battery_sensor="sensor.akku",
        )
        assert r.resolve()["mode"] == EnergyMode.SOLAR_BOOST

    def test_cheap_price_bypasses_priority_gate(self):
        r = _make_resolver(
            solar_power=100,
            price=0.10,
            battery_soc=50.0,
            battery_sensor="sensor.akku",
            options={"battery_priority": True},
        )
        assert r.resolve()["mode"] == EnergyMode.SOLAR_BOOST


class TestDiagnostics:
    """Diagnostics dict exposes the trigger state for debugging."""

    def test_diagnostics_includes_trigger_keys(self):
        r = _make_resolver(
            solar_power=1000,
            battery_soc=92.0,
            forecast_kwh=5.0,
            battery_sensor="sensor.akku",
            forecast_sensor="sensor.forecast",
        )
        diag = r.get_diagnostics()
        assert diag["battery_soc"] == pytest.approx(92.0)
        assert diag["forecast_remaining_kwh"] == pytest.approx(5.0)
        assert diag["boost_available"] is True
        assert diag["battery_priority"] is False
        assert diag["active_triggers"]["solar"] is True
        assert diag["active_triggers"]["soc"] is True
        assert diag["active_triggers"]["forecast"] is True
        assert diag["thresholds"]["bed_boost_soc_threshold"] == 90.0
        assert diag["thresholds"]["bed_boost_min_forecast_kwh"] == 3.0


class TestDerivedStatusKeys:
    """#7: resolve() liefert solar_active + price_status für Coordinator/Switch/Sensor."""

    def test_solar_active_true_on_boost(self):
        r = _make_resolver(solar_power=1000)
        state = r.resolve()
        assert state["solar_active"] is True

    def test_solar_active_false_without_boost(self):
        r = _make_resolver(solar_power=300)
        state = r.resolve()
        assert state["solar_active"] is False

    def test_price_status_cheap(self):
        r = _make_resolver(solar_power=0, price=0.10)
        state = r.resolve()
        assert state["price_status"] == "cheap"
        # Günstiger Strom löst zugleich Solar-Boost aus
        assert state["solar_active"] is True

    def test_price_status_expensive(self):
        r = _make_resolver(solar_power=0, price=0.40)
        state = r.resolve()
        assert state["price_status"] == "expensive"

    def test_price_status_normal(self):
        r = _make_resolver(solar_power=0, price=0.25)
        state = r.resolve()
        assert state["price_status"] == "normal"

    def test_price_status_normal_without_price_sensor(self):
        # Ohne dynamischen Preis-Sensor → immer "normal" (kein Fehl-"Günstig")
        r = _make_resolver(solar_power=1000)
        state = r.resolve()
        assert state["price_status"] == "normal"


class TestRelativeHysteresis:
    """O5: Solar-Aus-Schwelle ist 10% relativ statt fix -50W."""

    def test_off_threshold_is_ten_percent_below(self):
        r = _make_resolver(solar_power=0, options={"solar_boost_threshold": 500})
        assert r.solar_boost_on_w == 500.0
        assert r.solar_boost_off_w == pytest.approx(450.0)  # 10% unter 500

    def test_off_threshold_tighter_for_small_threshold(self):
        r = _make_resolver(solar_power=0, options={"solar_boost_threshold": 150})
        # relativ: 135W statt der alten fixen 100W
        assert r.solar_boost_off_w == pytest.approx(135.0)
