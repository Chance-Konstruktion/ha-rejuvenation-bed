"""Shared fixtures for Rejuvenation Bed tests.

Mocks homeassistant before any component imports to allow
testing without a full HA installation.
"""

import sys
from unittest.mock import MagicMock
from datetime import time

import pytest

# ── Mock homeassistant and all submodules before any component imports ──
# We need to register ALL possible submodules so Python's import system
# treats them as packages (i.e., can import sub-sub-modules from them).

# Gather all homeassistant submodules referenced by the codebase
_HA_SUBMODULES = [
    "homeassistant",
    "homeassistant.config_entries",
    "homeassistant.core",
    "homeassistant.const",
    "homeassistant.exceptions",
    "homeassistant.data_entry_flow",
    "homeassistant.util",
    "homeassistant.util.dt",
    "homeassistant.helpers",
    "homeassistant.helpers.storage",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.helpers.entity",
    "homeassistant.helpers.config_validation",
    "homeassistant.helpers.selector",
    "homeassistant.helpers.device_registry",
    "homeassistant.helpers.event",
    "homeassistant.helpers.restore_state",
    "homeassistant.components",
    "homeassistant.components.climate",
    "homeassistant.components.climate.const",
    "homeassistant.components.sensor",
    "homeassistant.components.binary_sensor",
    "homeassistant.components.switch",
    "homeassistant.components.persistent_notification",
    "voluptuous",
    "voluptuous.humanize",
]

# Create a single root mock - all sub-attributes auto-create as MagicMock
_ha_root = MagicMock()

for mod_name in _HA_SUBMODULES:
    if mod_name not in sys.modules:
        # Each module gets its own MagicMock so import X from Y works
        sys.modules[mod_name] = MagicMock()

# const.local_now() does `from homeassistant.util import dt as dt_util` and
# calls dt_util.now(). With the mocked package, dt_util resolves to the child
# attribute `homeassistant.util.dt`, so we point its .now() at a real clock.
# This lets modules that route time through local_now() behave like the old
# datetime.now() in tests (naive local time), without every test patching it.
import datetime as _datetime  # noqa: E402

sys.modules["homeassistant.util"].dt.now = lambda: _datetime.datetime.now()


# ── Fixtures ──


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
