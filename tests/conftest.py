"""Shared fixtures for Rejuvenation Bed tests."""

import pytest
from datetime import time


@pytest.fixture
def waterbed_config():
    """Standard waterbed configuration for tests."""
    return {
        "min_temp": 24.0,
        "max_temp": 30.0,
        "standby_temp": 26.0,
        "away_temp": 24.0,
        "eco_min_temp": 26.0,
        "max_change_per_hour": 1.0,
        "ramp_enabled": True,
        "heating_rate": 0.3,
        "cooling_rate": 0.1,
        "preheat_hours": 5.0,
        "thermal_battery": True,
        "leak_detection": True,
        "condensation_risk": True,
        "solar_boost_max": 28.5,
        "solar_boost_enabled": True,
        "eco_reduction_max": 2.0,
        "eco_can_turn_off": False,
    }


@pytest.fixture
def heating_pad_config():
    """Standard heating pad configuration for tests."""
    return {
        "min_temp": 0.0,
        "max_temp": 40.0,
        "standby_temp": 0.0,
        "away_temp": 0.0,
        "eco_min_temp": 0.0,
        "max_change_per_hour": 10.0,
        "ramp_enabled": False,
        "heating_rate": 5.0,
        "cooling_rate": 3.0,
        "preheat_minutes": 15,
        "thermal_battery": False,
        "leak_detection": False,
        "condensation_risk": False,
        "solar_boost_max": 35.0,
        "solar_boost_enabled": False,
        "eco_reduction_max": 100.0,
        "eco_can_turn_off": True,
    }


@pytest.fixture
def default_bedtime():
    return time(23, 0)


@pytest.fixture
def default_wake_time():
    return time(7, 0)
