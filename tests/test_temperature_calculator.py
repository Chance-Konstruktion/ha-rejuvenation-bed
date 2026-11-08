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
from datetime import time

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


class TestSummerHoldTemp:
    """Sommer-Modus: konfigurierbare Bett-Haltetemperatur + ehrlicher Status."""

    @staticmethod
    def _calc(options=None, global_conf=None, bed=WATERBED_CONFIG):
        hass = MagicMock()
        config_entry = SimpleNamespace(
            options=options or {},
            data={"global": global_conf or {}, "zones": [{}]},
        )
        return TemperatureCalculator(hass, config_entry, bed.copy())

    def test_default_summer_hold_temp(self):
        calc = self._calc()
        assert calc.get_summer_hold_temp() == pytest.approx(25.0)

    def test_option_overrides_summer_hold_temp(self):
        calc = self._calc(options={"summer_temp": 24.5})
        assert calc.get_summer_hold_temp() == pytest.approx(24.5)

    def test_clamped_to_min_temp_for_waterbed(self):
        # 22 unter min_temp 24 → auf 24 angehoben (Kondensationsschutz)
        calc = self._calc(options={"summer_temp": 22.0})
        assert calc.get_summer_hold_temp() == pytest.approx(24.0)

    def test_summer_veto_returns_configured_temp(self):
        import asyncio

        calc = self._calc(options={"summer_temp": 24.5})
        temp = asyncio.run(calc.async_calculate_target(0, {}, {"is_summer": True}))
        assert temp == pytest.approx(24.5)

    def test_decision_reason_summer_beats_solar(self):
        import asyncio

        calc = self._calc()
        # Energie-Status meldet Solar-Boost, aber Sommer-Veto hat Vorrang.
        energy_state = {"mode": SimpleNamespace(value="solar_boost"), "reason": "☀️ Solar-Boost"}
        reason = asyncio.run(calc.async_get_decision_reason(0, 25.0, 25.0, False, energy_state, is_summer=True))
        assert "Sommer" in reason
        assert "Solar-Boost" not in reason

    def test_decision_reason_solar_when_not_summer(self):
        import asyncio

        calc = self._calc()
        energy_state = {"mode": SimpleNamespace(value="solar_boost"), "reason": "☀️ Solar-Boost"}
        reason = asyncio.run(calc.async_get_decision_reason(0, 28.0, 27.0, True, energy_state, is_summer=False))
        assert "Solar-Boost" in reason


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


class TestPreheatWindow:
    """M4: Das Vorheizfenster der Heizmatte ist 15 Minuten — nicht die
    180 Minuten des 3-h-Defaults, der griff, weil HEATING_PAD_CONFIG kein
    preheat_hours kannte."""

    @staticmethod
    def _make_calc_with_hass(bed_config):
        from types import SimpleNamespace as NS

        hass = MagicMock()
        hass.states.get = lambda entity_id: NS(state="on") if entity_id == "binary_sensor.workday" else None
        config_entry = NS(options={}, data={"global": {}, "zones": [{}]})
        return TemperatureCalculator(hass, config_entry, bed_config.copy())

    def _target_one_hour_before_warm_from(self, bed_config):
        import asyncio
        from datetime import datetime as dt
        from unittest.mock import patch

        calc = self._make_calc_with_hass(bed_config)
        with patch(
            "custom_components.rejuvenation_bed.temperature_calculator.local_now",
            return_value=dt(2026, 11, 8, 21, 0, 0),
        ):
            return asyncio.run(
                calc.async_calculate_target(0, {"temperature_offset": 0.0}, {}, has_presence_sensor=False)
            )

    def test_heating_pad_does_not_preheat_60_minutes_before(self):
        # 60 Min vor warm_from: Fenstergroesse 15 -> Standby (AUS), nicht Vorheizen
        assert self._target_one_hour_before_warm_from(HEATING_PAD_CONFIG) == pytest.approx(0.0)

    def test_waterbed_does_preheat_60_minutes_before(self):
        # Gegenprobe Wasserbett: 5-h-Fenster -> 60 Min vorher wird vorgeheizt
        assert self._target_one_hour_before_warm_from(WATERBED_CONFIG) == pytest.approx(28.0)


class TestWakeAndOutdoorRefresh:
    """M1: Weckzeit und Außentemperatur frieren beim ersten Update nicht ein.

    Vorher löste der Calculator die Aufwachzeit genau einmal je
    Coordinator-Leben auf und las die Außentemperatur nur beim ersten
    Initialisieren — ein Handy-Wecker, der erst abends gestellt wird,
    erreichte die laufende Kurve nie.
    """

    @staticmethod
    def _make_calc(bed_config, states, zones=None, options=None, data_global=None):
        from types import SimpleNamespace as NS

        hass = MagicMock()
        hass.states.get = lambda entity_id: states.get(entity_id)
        config_entry = NS(
            options=options or {},
            data={"global": data_global or {}, "zones": zones or [{}]},
        )
        return TemperatureCalculator(hass, config_entry, bed_config.copy())

    @staticmethod
    def _state(value):
        from types import SimpleNamespace as NS

        return NS(state=value, domain="sensor", attributes={})

    def _calculate(self, calc):
        import asyncio
        from datetime import datetime as dt
        from unittest.mock import patch

        with patch(
            "custom_components.rejuvenation_bed.temperature_calculator.local_now",
            return_value=dt(2026, 11, 8, 21, 0, 0),
        ):
            return asyncio.run(calc.async_calculate_target(0, {"temperature_offset": 0.0}, {}, has_presence_sensor=False))

    def test_wake_time_follows_later_alarm(self, monkeypatch):
        from datetime import datetime, time
        from types import SimpleNamespace as NS
        import sys

        # Echtes ISO-Parsing an der dt-Attrappe. Der Resolver hat dt_util
        # beim Import als Attribut des Parent-Mocks gebunden
        # (homeassistant.util.dt) — genau dieses Objekt wird gepatcht.
        dt_mod = sys.modules["homeassistant.util"].dt
        monkeypatch.setattr(dt_mod, "parse_datetime", datetime.fromisoformat, raising=False)
        monkeypatch.setattr(dt_mod, "as_local", lambda d: d, raising=False)

        states = {
            "binary_sensor.workday": NS(state="on", domain="binary_sensor", attributes={}),
            "sensor.alarm": self._state("2026-11-08T06:30:00"),
        }
        calc = self._make_calc(WATERBED_CONFIG, states, zones=[{"alarm_entity": "sensor.alarm"}])

        self._calculate(calc)
        assert calc._curves[0].wake_time == time(6, 30)

        # Abends wird der Wecker auf später gestellt
        states["sensor.alarm"] = self._state("2026-11-08T09:00:00")
        self._calculate(calc)
        assert calc._curves[0].wake_time == time(9, 0)

    def test_outdoor_temp_refresh_keeps_user_sleep_temp(self):
        from types import SimpleNamespace as NS

        states = {
            "binary_sensor.workday": NS(state="on", domain="binary_sensor", attributes={}),
            "sensor.outside": self._state("5.0"),  # Winter-Profil
        }
        calc = self._make_calc(
            WATERBED_CONFIG,
            states,
            options={"zone_0_sleep_temp": 28.5},  # Nutzer-Vorgabe
            data_global={"outdoor_sensor": "sensor.outside"},
        )

        self._calculate(calc)
        curve = calc._curves[0]
        assert curve.deep_sleep_temp == 27.5  # Winter
        assert curve.sleep_temp == 28.5  # Nutzer-Vorgabe

        states["sensor.outside"] = self._state("25.0")  # Sommer-Profil
        self._calculate(calc)
        curve = calc._curves[0]
        assert curve.deep_sleep_temp == 26.0  # saisonal nachgezogen
        assert curve.sleep_temp == 28.5  # Nutzer-Vorgabe bleibt stehen

    def test_update_outdoor_temp_without_user_temps_stays_seasonal(self):
        # Direkt an der Kurve: ohne Nutzer-Vorgaben wandert alles mit (altes Verhalten)
        from custom_components.rejuvenation_bed.biorhythmus_curve import BiorhythmusCurve

        curve = BiorhythmusCurve(bedtime=time(23, 0), wake_time=time(7, 0), outdoor_temp=5.0)
        curve.update_outdoor_temp(25.0)
        assert curve.sleep_temp == 27.0
        assert curve.deep_sleep_temp == 26.0
        assert curve.wake_temp == 28.0
