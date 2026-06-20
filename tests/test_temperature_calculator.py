"""Tests for TemperatureCalculator's daytime Solar-Boost charging.

Regression: Solar-Boost is meant to park PV surplus in the bed as a
thermal battery during the day. The energy offset used to be applied only
in the night-time warm window, so the daytime standby target never rose
and the heater (smart plug) never switched on. `_charge_standby_temp`
applies the boost to the standby target for beds that can store heat.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.rejuvenation_bed.const import (
    WATERBED_CONFIG,
    HEATING_PAD_CONFIG,
)
from custom_components.rejuvenation_bed.temperature_calculator import (
    TemperatureCalculator,
)


def _make_calc(bed_config):
    hass = MagicMock()
    config_entry = SimpleNamespace(options={}, data={"global": {}})
    return TemperatureCalculator(hass, config_entry, bed_config.copy())


class TestChargeStandbyTemp:
    def test_solar_boost_raises_waterbed_standby(self):
        calc = _make_calc(WATERBED_CONFIG)
        # standby 26 + solar offset 1.5 = 27.5 (below cap 28.5)
        result = calc._charge_standby_temp(26.0, {"temperature_offset": 1.5}, 0)
        assert result == pytest.approx(27.5)

    def test_capped_at_solar_boost_max(self):
        calc = _make_calc(WATERBED_CONFIG)
        # 28 + 1.5 = 29.5, but capped at solar_boost_max 28.5
        result = calc._charge_standby_temp(28.0, {"temperature_offset": 1.5}, 0)
        assert result == pytest.approx(28.5)

    def test_no_offset_returns_standby(self):
        calc = _make_calc(WATERBED_CONFIG)
        result = calc._charge_standby_temp(26.0, {"temperature_offset": 0.0}, 0)
        assert result == pytest.approx(26.0)

    def test_eco_offset_does_not_lower_standby(self):
        calc = _make_calc(WATERBED_CONFIG)
        # negative (eco) offset must not pull standby down here
        result = calc._charge_standby_temp(26.0, {"temperature_offset": -2.0}, 0)
        assert result == pytest.approx(26.0)

    def test_below_min_temp_is_lifted_first(self):
        calc = _make_calc(WATERBED_CONFIG)
        # base 20 → max(20, min_temp 24) = 24, then +1.5 = 25.5
        result = calc._charge_standby_temp(20.0, {"temperature_offset": 1.5}, 0)
        assert result == pytest.approx(25.5)

    def test_heating_pad_has_no_thermal_battery(self):
        calc = _make_calc(HEATING_PAD_CONFIG)
        # heating pad cannot store heat → boost ignored, standby unchanged
        result = calc._charge_standby_temp(0.0, {"temperature_offset": 1.5}, 0)
        assert result == pytest.approx(max(0.0, calc.min_temp))

    def test_none_energy_state_safe(self):
        calc = _make_calc(WATERBED_CONFIG)
        result = calc._charge_standby_temp(26.0, None, 0)
        assert result == pytest.approx(26.0)


class TestBoostTargetTemp:
    """#11: Boost = feste Zieltemperatur (absolut), Vorrang Option → Zone → 34."""

    @staticmethod
    def _boost_calc(options, zone_boost):
        hass = MagicMock()
        config_entry = SimpleNamespace(
            options=options,
            data={"global": {}, "zones": [{"boost_target_temp": zone_boost}]},
        )
        return TemperatureCalculator(hass, config_entry, WATERBED_CONFIG.copy())

    @staticmethod
    def _coord():
        return SimpleNamespace(manual_boost={0: True}, manual_target_temp={}, sick_mode_until={})

    def test_boost_uses_zone_target_when_no_option(self):
        import asyncio

        calc = self._boost_calc(options={}, zone_boost=34)
        temp = asyncio.run(calc.async_calculate_target(0, {}, {}, coordinator=self._coord()))
        assert temp == 34.0

    def test_option_overrides_zone_target(self):
        import asyncio

        calc = self._boost_calc(options={"boost_target_temp": 30.0}, zone_boost=34)
        temp = asyncio.run(calc.async_calculate_target(0, {}, {}, coordinator=self._coord()))
        assert temp == 30.0
