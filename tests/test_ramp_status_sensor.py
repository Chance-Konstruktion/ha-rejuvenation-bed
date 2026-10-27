"""Regression tests for the ramp status sensor on hardware without a ramp."""

from types import SimpleNamespace

from custom_components.rejuvenation_bed.sensor import BedRampStatusSensor


def _sensor(controller):
    # The tested properties only need these fields; this avoids setting up a
    # complete Home Assistant entity lifecycle for simple state formatting.
    return SimpleNamespace(
        coordinator=SimpleNamespace(ramp_controller=controller),
        zone_idx=0,
    )


def test_heating_pad_without_ramp_controller_is_supported():
    """Heating pads deliberately have no RampController."""
    sensor = _sensor(None)

    assert BedRampStatusSensor.native_value.fget(sensor) == "Nicht anwendbar"
    assert BedRampStatusSensor.icon.fget(sensor) == "mdi:minus"
    assert BedRampStatusSensor.extra_state_attributes.fget(sensor) == {}


def test_ramp_sensor_keeps_initializing_state_when_controller_has_no_state():
    sensor = _sensor(SimpleNamespace(get_ramp_state=lambda _zone: None))

    assert BedRampStatusSensor.native_value.fget(sensor) == "Initialisierung..."
    assert BedRampStatusSensor.icon.fget(sensor) == "mdi:minus"
    assert BedRampStatusSensor.extra_state_attributes.fget(sensor) == {}


def test_active_ramp_state_is_still_reported():
    ramp_state = SimpleNamespace(
        ramp_active=True,
        ramp_direction="heating",
        target_temp=28.0,
        current_setpoint=27.0,
        reason="Materialschutz",
        estimated_completion=None,
    )
    controller = SimpleNamespace(get_ramp_state=lambda _zone: ramp_state)
    sensor = _sensor(controller)

    assert BedRampStatusSensor.native_value.fget(sensor) == "Aufheizen"
    assert BedRampStatusSensor.icon.fget(sensor) == "mdi:trending-up"
    assert BedRampStatusSensor.extra_state_attributes.fget(sensor) == {
        "ziel_temperatur": "28.0°C",
        "aktueller_setpoint": "27.0°C",
        "rampe_aktiv": True,
        "richtung": "heating",
        "grund": "Materialschutz",
        "max_aenderung": "1.0°C/h (Materialschutz)",
    }
