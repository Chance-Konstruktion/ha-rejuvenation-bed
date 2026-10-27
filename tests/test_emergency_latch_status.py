"""Regression tests for reporting a per-zone emergency latch."""

from types import SimpleNamespace

from custom_components.rejuvenation_bed.sensor import BedStatusSensor


def test_zone_status_reports_latched_emergency_after_global_status_clears():
    """A zone latch remains important even when the global overheat has cleared."""
    sensor = SimpleNamespace(
        coordinator=SimpleNamespace(
            data={
                "global_state": {"status": "OK"},
                "zones": {
                    "Zone 1": {
                        "mode": "emergency",
                        "status": "EMERGENCY_SHUTDOWN",
                        "active": False,
                        "reason": "NOT-AUS aktiv: Test-Notfall",
                    }
                },
            }
        ),
        internal_zone_name="Zone 1",
    )

    assert BedStatusSensor.native_value.fget(sensor) == "NOT-AUS"
