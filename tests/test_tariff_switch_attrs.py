"""K3: Das Tarifmodus-Attribut min_temperatur nennt die echte Klemme.

Der Code klemmt den Eco-Offset an min_temp des Bett-Typs (Wasserbett 24°C,
Anti-Kalt-Garantie im TemperatureCalculator); eco_min_temp (26) wird
nirgends gelesen. Das Attribut versprach "26°C" — 2°C mehr, als je
erreicht wird.
"""

import sys
from unittest.mock import MagicMock

# Echte Basisklassen statt Mock, bevor switch.py importiert wird (Muster aus
# test_nightstand_config.py: zwei MagicMocks als Basen werfen einen
# Metaclass-Konflikt).
class _FakeCoordinatorEntity:
    def __init__(self, coordinator, *args, **kwargs):
        self.coordinator = coordinator


sys.modules["homeassistant"].helpers.update_coordinator.CoordinatorEntity = _FakeCoordinatorEntity
sys.modules["homeassistant.helpers.update_coordinator"].CoordinatorEntity = _FakeCoordinatorEntity
sys.modules["homeassistant"].components.switch.SwitchEntity = type("SwitchEntity", (), {})
sys.modules["homeassistant.components.switch"].SwitchEntity = sys.modules[
    "homeassistant"
].components.switch.SwitchEntity

from custom_components.rejuvenation_bed.const import WATERBED_CONFIG, HEATING_PAD_CONFIG  # noqa: E402
from custom_components.rejuvenation_bed.switch import BedTariffModeSwitch  # noqa: E402


def test_waterbed_attribute_matches_effective_floor():
    switch = BedTariffModeSwitch(MagicMock(), True)
    attrs = switch.extra_state_attributes
    assert attrs["min_temperatur"] == f"{WATERBED_CONFIG['min_temp']:.0f}°C"


def test_pad_attribute_unchanged():
    switch = BedTariffModeSwitch(MagicMock(), False)
    attrs = switch.extra_state_attributes
    assert attrs["min_temperatur"] == f"{HEATING_PAD_CONFIG['min_temp']:.0f}°C"
