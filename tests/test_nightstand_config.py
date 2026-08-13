"""Die Entities für die Nachttisch-Karte am Status-Sensor.

Die Lovelace-Karte kennt die Integration nicht — sie sieht nur Zustände.
Darum trägt der Status-Sensor jeder Zone Thermostat, Weckzeit, Wecker-Schalter
und Lampe als Attribut bei sich; die Karte liest sie dort aus, statt in jedem
Dashboard erneut mit denselben Entity-IDs gefüttert zu werden.
"""

import sys
from unittest.mock import MagicMock


# ── Echte Basisklassen statt Mocks, bevor sensor.py importiert wird ──
# Zwei MagicMock-Basen hätten unvereinbare Metaklassen; die Entity-Klasse
# ließe sich gar nicht erst definieren.
class _FakeCoordinatorEntity:
    def __init__(self, coordinator, *args, **kwargs):
        self.coordinator = coordinator


class _FakeSensorEntity:
    pass


sys.modules["homeassistant"].helpers.update_coordinator.CoordinatorEntity = _FakeCoordinatorEntity
sys.modules["homeassistant.helpers.update_coordinator"].CoordinatorEntity = _FakeCoordinatorEntity
sys.modules["homeassistant"].components.sensor.SensorEntity = _FakeSensorEntity
sys.modules["homeassistant.components.sensor"].SensorEntity = _FakeSensorEntity

from custom_components.rejuvenation_bed.sensor import BedStatusSensor  # noqa: E402


def _sensor(zone_idx=0, display_name="", options=None, climate="climate.thermostat"):
    coordinator = MagicMock()
    coordinator.config_entry.entry_id = "abc123"
    coordinator.config_entry.options = options or {}

    sensor = BedStatusSensor(coordinator, zone_idx, display_name)
    sensor.hass = MagicMock()
    sensor._climate_entity_id = lambda: climate
    return sensor


def test_attribut_enthaelt_die_entities_der_zone():
    sensor = _sensor(
        zone_idx=1,
        display_name=" Rechts",
        options={
            "zone_1_alarm_entity": "input_datetime.wecker_rechts",
            "zone_1_alarm_switch_entity": "input_boolean.wecker_rechts_aktiv",
            "zone_1_light_entity": "light.schlafzimmer",
        },
    )

    config = sensor.extra_state_attributes["rejuvenation_nightstand"]
    assert config["zone"] == 1
    assert config["name"] == "Bett Rechts"
    assert config["climate"] == "climate.thermostat"
    assert config["alarm"] == "input_datetime.wecker_rechts"
    assert config["alarm_switch"] == "input_boolean.wecker_rechts_aktiv"
    assert config["light"] == "light.schlafzimmer"


def test_zonenwert_schlaegt_globalen_wert():
    sensor = _sensor(options={"alarm_entity": "sensor.global_alarm", "zone_0_alarm_entity": "sensor.zone_alarm"})
    config = sensor.extra_state_attributes["rejuvenation_nightstand"]
    assert config["alarm"] == "sensor.zone_alarm"


def test_globaler_wert_gilt_ohne_zoneneintrag():
    sensor = _sensor(options={"alarm_entity": "sensor.global_alarm"})
    config = sensor.extra_state_attributes["rejuvenation_nightstand"]
    assert config["alarm"] == "sensor.global_alarm"


def test_nicht_gesetztes_bleibt_weg():
    """Leere Schlüssel würden in der Karte als »konfiguriert« durchgehen."""
    sensor = _sensor(options={"zone_0_light_entity": ""}, climate=None)
    config = sensor.extra_state_attributes["rejuvenation_nightstand"]
    assert "light" not in config
    assert "climate" not in config
    assert "alarm" not in config


def test_attribut_landet_nicht_in_der_datenbank():
    assert "rejuvenation_nightstand" in BedStatusSensor._unrecorded_attributes
