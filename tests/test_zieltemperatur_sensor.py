"""#12: Der Zieltemperatur-Sensor liefert keinen Text als Temperatur.

Der Coordinator hinterlegt bei Not-Aus 'unknown' als Anzeige-Platzhalter im
Zonen-Ergebnis (coordinator.py, Not-Aus-Zweig). BedTemperatureSensor gibt
den Wert unverändert als native_value zurück -- für die Geräteklasse
TEMPERATURE ist das ein ungültiger Zustand, den HA pro Update verwirft.
Nur eine Zahl ist ein Zustand; sonst None (→ unavailable).
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

from custom_components.rejuvenation_bed.sensor import BedTemperatureSensor  # noqa: E402


def _sensor(target):
    coordinator = MagicMock()
    coordinator.data = {"zones": {"Zone 1": {"target": target}}}
    coordinator.config_entry.data = {"zones": []}
    coordinator.config_entry.entry_id = "abc123"
    return BedTemperatureSensor(coordinator, 0, " Links")


def test_unknown_platzhalter_ist_kein_temperaturzustand():
    """#12: 'unknown' (Not-Aus) → None → unavailable, kein invalid State."""
    assert _sensor("unknown").native_value is None


def test_zahl_bleibt_temperaturzustand():
    """#12: Normale Zieltemperatur kommt unverändert durch."""
    assert _sensor(28.5).native_value == 28.5


def test_ohne_wert_bleibt_none():
    assert _sensor(None).native_value is None
