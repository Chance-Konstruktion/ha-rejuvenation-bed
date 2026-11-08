"""K7: Die Thermische-Batterie-Skala folgt solar_boost_max des Bett-Typs.

100 % war auf 32 °C gelegt; ladbar ist das Wasserbett über Standby 26 °C
aber nur bis solar_boost_max 28,5 °C — der Prozentwert konnte im Betrieb
nie über ~42 % steigen.
"""

import sys
from unittest.mock import MagicMock

# Echte Basisklassen statt Mock, bevor sensor.py importiert wird (Muster aus
# test_nightstand_config.py: zwei MagicMocks als Basen werfen einen
# Metaclass-Konflikt).
class _FakeCoordinatorEntity:
    def __init__(self, coordinator, *args, **kwargs):
        self.coordinator = coordinator


sys.modules["homeassistant"].helpers.update_coordinator.CoordinatorEntity = _FakeCoordinatorEntity
sys.modules["homeassistant.helpers.update_coordinator"].CoordinatorEntity = _FakeCoordinatorEntity
sys.modules["homeassistant"].components.sensor.SensorEntity = type("SensorEntity", (), {})
sys.modules["homeassistant.components.sensor"].SensorEntity = sys.modules[
    "homeassistant"
].components.sensor.SensorEntity

from custom_components.rejuvenation_bed.const import WATERBED_CONFIG  # noqa: E402
from custom_components.rejuvenation_bed.sensor import BedThermalBatterySensor  # noqa: E402


def _sensor(water_temp):
    coordinator = MagicMock()
    coordinator.bed_config = WATERBED_CONFIG.copy()
    coordinator.data = {"zones": {"Zone 1": {"current": water_temp}}}
    coordinator.config_entry.entry_id = "abc123"
    return BedThermalBatterySensor(coordinator)


def test_solar_boost_max_reads_100_percent():
    assert _sensor(28.5).native_value == 100.0


def test_standby_reads_0_percent():
    assert _sensor(26.0).native_value == 0.0


def test_midway_temperature_scales_between():
    # 27,25 °C liegt genau zwischen 26 und 28,5 → 50 %
    assert _sensor(27.25).native_value == 50.0
