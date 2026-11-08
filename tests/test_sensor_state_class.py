"""K8: Die Prozent-Sensoren tragen eine state_class für Langzeitstatistik.

BedSolarPercentageSensor und BedLegacyComparisonSensor hatten keine
state_class, der vergleichbare BedThermalBatterySensor setzt MEASUREMENT.
"""

import sys


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

from custom_components.rejuvenation_bed.sensor import (  # noqa: E402
    BedLegacyComparisonSensor,
    BedSolarPercentageSensor,
    BedThermalBatterySensor,
)


def test_solar_percentage_has_state_class():
    assert hasattr(BedSolarPercentageSensor, "_attr_state_class")


def test_legacy_comparison_has_state_class():
    assert hasattr(BedLegacyComparisonSensor, "_attr_state_class")


def test_thermal_battery_keeps_its_state_class():
    # Vergleichsanker: dieses Muster ist im Projekt bereits etabliert
    assert hasattr(BedThermalBatterySensor, "_attr_state_class")
