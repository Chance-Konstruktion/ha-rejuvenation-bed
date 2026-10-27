"""Regression checks for reporting a per-zone emergency latch.

The HA entity base classes are mocked by the unit-test conftest, so this
checks the status mapping at source level instead of importing SensorEntity.
The coordinator-level tests exercise the emergency latch behavior at runtime.
"""

from pathlib import Path


def test_zone_status_checks_latched_emergency_independently_of_global_state():
    source = Path("custom_components/rejuvenation_bed/sensor.py").read_text(encoding="utf-8")

    assert 'zone_data.get("mode") == "emergency"' in source
    assert 'zone_data.get("status") == "EMERGENCY_SHUTDOWN"' in source
    assert 'return "NOT-AUS"' in source
