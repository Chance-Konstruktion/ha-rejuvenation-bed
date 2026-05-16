"""Tests for EnergyStateResolver - in particular the PV priority cascade.

The cascade gates Solar-Boost on home battery SoC and/or PV forecast.
Logic (OR):
  - Neither sensor configured → no gating (classic behaviour).
  - At least one configured → boost allowed when (SoC >= threshold) OR
    (forecast >= threshold).
  - Boost only takes the price-fallback path (cheap electricity) when
    the price drops below the cheap threshold; cascade does NOT gate
    that path (it's grid energy, not PV surplus).
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


class TestCascadeInactive:
    """Without battery/forecast sensors the cascade is inactive."""

    def test_boost_fires_with_only_solar(self):
        r = _make_resolver(solar_power=1000)
        state = r.resolve()
        assert state["mode"] == EnergyMode.SOLAR_BOOST
        assert state["cascade_allows_boost"] is True

    def test_no_boost_below_solar_threshold(self):
        r = _make_resolver(solar_power=300)
        state = r.resolve()
        assert state["mode"] == EnergyMode.NORMAL


class TestCascadeBatteryOnly:
    """Only the battery sensor configured: SoC gates the boost."""

    def test_boost_blocked_when_battery_low(self):
        r = _make_resolver(
            solar_power=1000,
            battery_soc=70.0,
            battery_sensor="sensor.akku",
        )
        state = r.resolve()
        assert state["mode"] == EnergyMode.NORMAL
        assert state["cascade_allows_boost"] is False
        assert "70" in state["reason"] or "70" in state["cascade_reason"]

    def test_boost_allowed_when_battery_full(self):
        r = _make_resolver(
            solar_power=1000,
            battery_soc=95.0,
            battery_sensor="sensor.akku",
        )
        state = r.resolve()
        assert state["mode"] == EnergyMode.SOLAR_BOOST
        assert state["cascade_allows_boost"] is True

    def test_boost_at_exact_threshold(self):
        """SoC == threshold should allow boost (>= semantics)."""
        r = _make_resolver(
            solar_power=1000,
            battery_soc=90.0,
            battery_sensor="sensor.akku",
        )
        assert r.resolve()["mode"] == EnergyMode.SOLAR_BOOST

    def test_custom_threshold(self):
        r = _make_resolver(
            solar_power=1000,
            battery_soc=80.0,
            battery_sensor="sensor.akku",
            options={"bed_boost_soc_threshold": 75.0},
        )
        assert r.resolve()["mode"] == EnergyMode.SOLAR_BOOST


class TestCascadeForecastOnly:
    """Only the forecast sensor configured: remaining kWh gates the boost."""

    def test_boost_blocked_when_forecast_low(self):
        r = _make_resolver(
            solar_power=1000,
            forecast_kwh=1.0,
            forecast_sensor="sensor.forecast",
        )
        state = r.resolve()
        assert state["mode"] == EnergyMode.NORMAL
        assert "1.0" in state["cascade_reason"]

    def test_boost_allowed_when_forecast_generous(self):
        r = _make_resolver(
            solar_power=1000,
            forecast_kwh=8.0,
            forecast_sensor="sensor.forecast",
        )
        assert r.resolve()["mode"] == EnergyMode.SOLAR_BOOST


class TestCascadeBothSensors:
    """Both sensors: OR-logic, either condition unblocks the boost."""

    def test_battery_full_unblocks_even_if_forecast_low(self):
        r = _make_resolver(
            solar_power=1000,
            battery_soc=95.0,
            forecast_kwh=0.5,
            battery_sensor="sensor.akku",
            forecast_sensor="sensor.forecast",
        )
        assert r.resolve()["mode"] == EnergyMode.SOLAR_BOOST

    def test_forecast_generous_unblocks_even_if_battery_low(self):
        r = _make_resolver(
            solar_power=1000,
            battery_soc=60.0,
            forecast_kwh=8.0,
            battery_sensor="sensor.akku",
            forecast_sensor="sensor.forecast",
        )
        assert r.resolve()["mode"] == EnergyMode.SOLAR_BOOST

    def test_both_low_blocks_boost(self):
        r = _make_resolver(
            solar_power=1000,
            battery_soc=60.0,
            forecast_kwh=1.0,
            battery_sensor="sensor.akku",
            forecast_sensor="sensor.forecast",
        )
        assert r.resolve()["mode"] == EnergyMode.NORMAL


class TestSensorUnavailable:
    """Sensor configured but state is unavailable / non-numeric."""

    def test_both_unavailable_blocks_boost(self):
        """If both sensors are configured but unavailable, default to safe (block).

        Rationale: if user wired up the cascade, respect the intent —
        rather wait than push the bed past unknown battery state.
        """
        r = _make_resolver(
            solar_power=1000,
            battery_soc=None,
            forecast_kwh=None,
            battery_sensor="sensor.akku",
            forecast_sensor="sensor.forecast",
        )
        state = r.resolve()
        assert state["mode"] == EnergyMode.NORMAL
        assert state["cascade_allows_boost"] is False

    def test_one_unavailable_other_ok_allows_boost(self):
        """One sensor unavailable, the other green → OR still passes."""
        r = _make_resolver(
            solar_power=1000,
            battery_soc=None,
            forecast_kwh=8.0,
            battery_sensor="sensor.akku",
            forecast_sensor="sensor.forecast",
        )
        assert r.resolve()["mode"] == EnergyMode.SOLAR_BOOST


class TestHysteresis:
    """Once cascade allows boost, it stays allowed across a small dip."""

    def test_soc_hysteresis_keeps_boost_on(self):
        r = _make_resolver(
            solar_power=1000,
            battery_soc=92.0,
            battery_sensor="sensor.akku",
        )
        # First call: above threshold → cascade allows
        assert r.resolve()["mode"] == EnergyMode.SOLAR_BOOST
        assert r._cascade_allows is True

        # Drop SoC to 86%: still above hysteresis floor (90 - 5 = 85)
        r.hass.states.get = lambda eid: {
            "sensor.solar": _make_state(1000),
            "sensor.akku": _make_state(86.0),
        }.get(eid)
        assert r.resolve()["mode"] == EnergyMode.SOLAR_BOOST

    def test_soc_hysteresis_releases_boost_below_floor(self):
        r = _make_resolver(
            solar_power=1000,
            battery_soc=92.0,
            battery_sensor="sensor.akku",
        )
        assert r.resolve()["mode"] == EnergyMode.SOLAR_BOOST

        # Drop to 80%: below hysteresis floor (85)
        r.hass.states.get = lambda eid: {
            "sensor.solar": _make_state(1000),
            "sensor.akku": _make_state(80.0),
        }.get(eid)
        assert r.resolve()["mode"] == EnergyMode.NORMAL

    def test_forecast_hysteresis(self):
        r = _make_resolver(
            solar_power=1000,
            forecast_kwh=3.5,
            forecast_sensor="sensor.forecast",
        )
        assert r.resolve()["mode"] == EnergyMode.SOLAR_BOOST

        # Drop to 2.5 kWh: still above hysteresis floor (3 - 1 = 2)
        r.hass.states.get = lambda eid: {
            "sensor.solar": _make_state(1000),
            "sensor.forecast": _make_state(2.5),
        }.get(eid)
        assert r.resolve()["mode"] == EnergyMode.SOLAR_BOOST

        # Drop to 1.5: below floor (2.0)
        r.hass.states.get = lambda eid: {
            "sensor.solar": _make_state(1000),
            "sensor.forecast": _make_state(1.5),
        }.get(eid)
        assert r.resolve()["mode"] == EnergyMode.NORMAL


class TestCheapPriceBypass:
    """Cheap grid electricity must still trigger boost — cascade only gates PV."""

    def test_cheap_price_bypasses_cascade(self):
        r = _make_resolver(
            solar_power=100,
            price=0.10,
            battery_soc=50.0,
            battery_sensor="sensor.akku",
        )
        # Solar is below the W-threshold and cascade would block,
        # but the cheap price kicks SOLAR_BOOST anyway (grid path).
        assert r.resolve()["mode"] == EnergyMode.SOLAR_BOOST


class TestReasonStrings:
    """The reason string surfaces cascade context for the UI."""

    def test_reason_when_boost_active_includes_cascade(self):
        r = _make_resolver(
            solar_power=1000,
            battery_soc=92.0,
            battery_sensor="sensor.akku",
        )
        state = r.resolve()
        assert "Solar-Boost" in state["reason"]
        assert "Akku 92" in state["reason"]

    def test_reason_when_blocked_explains_why(self):
        r = _make_resolver(
            solar_power=1000,
            battery_soc=60.0,
            battery_sensor="sensor.akku",
        )
        state = r.resolve()
        assert "wartet" in state["reason"]
        assert "60" in state["reason"]

    def test_reason_normal_without_solar(self):
        r = _make_resolver(solar_power=100)
        assert r.resolve()["reason"] == "✅ Normal-Betrieb"


class TestSwitchInteraction:
    """The user's thermal_battery switch still blocks everything."""

    def test_switch_off_blocks_boost_even_with_cascade_green(self):
        r = _make_resolver(
            solar_power=1000,
            battery_soc=95.0,
            battery_sensor="sensor.akku",
            solar_enabled=False,
        )
        assert r.resolve()["mode"] == EnergyMode.NORMAL


class TestDiagnostics:
    """Diagnostics dict exposes the cascade state for debugging."""

    def test_diagnostics_includes_cascade_keys(self):
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
        assert diag["cascade_allows_boost"] is True
        assert diag["thresholds"]["bed_boost_soc_threshold"] == 90.0
        assert diag["thresholds"]["bed_boost_min_forecast_kwh"] == 3.0
