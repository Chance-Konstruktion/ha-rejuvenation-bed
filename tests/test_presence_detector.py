"""Tests for PresenceDetector - variance-based presence detection."""

import pytest
from datetime import datetime, timedelta

from custom_components.rejuvenation_bed.presence_detector import (
    PresenceDetector,
    PresenceThresholds,
)


@pytest.fixture
def detector():
    return PresenceDetector()


@pytest.fixture
def fast_detector():
    """Detector with short hysteresis for testing."""
    thresholds = PresenceThresholds(
        presence_enter_minutes=0,
        presence_leave_minutes=0,
        variance_window_minutes=5,
        min_datapoints=3,
    )
    return PresenceDetector(thresholds=thresholds)


class TestPresenceDetectorInit:
    def test_default_thresholds(self, detector):
        assert detector.thresholds.water_variance_threshold == 0.040
        assert detector.thresholds.presence_enter_minutes == 5
        assert detector.thresholds.presence_leave_minutes == 20

    def test_custom_thresholds(self):
        custom = PresenceThresholds(water_variance_threshold=0.06)
        det = PresenceDetector(thresholds=custom)
        assert det.thresholds.water_variance_threshold == 0.06


class TestPresenceSensorOverride:
    def test_dedicated_sensor_overrides(self, detector):
        """Dedicated presence sensor always wins."""
        is_present, conf, reason = detector.detect_presence(
            zone_index=0,
            water_temp=28.0,
            presence_sensor_state=True,
        )
        assert is_present is True
        assert conf == 1.0
        assert "Sensor" in reason

    def test_dedicated_sensor_absent(self, detector):
        is_present, conf, reason = detector.detect_presence(
            zone_index=0,
            water_temp=28.0,
            presence_sensor_state=False,
        )
        assert is_present is False
        assert conf == 1.0


class TestWaterbedVariance:
    def test_initial_collecting_data(self, detector):
        """First few readings should return 'collecting data'."""
        is_present, conf, reason = detector.detect_presence(
            zone_index=0, water_temp=28.0
        )
        assert conf == 0.0
        assert "Daten" in reason

    def test_stable_temps_no_presence(self, fast_detector):
        """Stable water temps = empty bed."""
        now = datetime(2026, 3, 15, 23, 0)
        for i in range(20):
            t = now + timedelta(seconds=i * 30)
            # Very stable: 28.00 +/- 0.01
            temp = 28.0 + (0.01 if i % 2 == 0 else -0.01)
            fast_detector._store(0, temp, None, None, t)

        is_present, conf, reason = fast_detector.detect_presence(
            zone_index=0, water_temp=28.0
        )
        assert conf < 0.5  # Low confidence = likely empty

    def test_variable_temps_presence(self, fast_detector):
        """Variable water temps = someone in bed."""
        now = datetime(2026, 3, 15, 23, 0)
        import math

        for i in range(20):
            t = now + timedelta(seconds=i * 30)
            # Significant variance: simulates water movement
            temp = 28.0 + 0.15 * math.sin(i * 0.5)
            fast_detector._store(0, temp, None, None, t)

        is_present, conf, reason = fast_detector.detect_presence(
            zone_index=0, water_temp=28.0
        )
        assert conf > 0.5

    def test_heater_active_raises_threshold(self, fast_detector):
        """When heater is active, threshold is raised to ignore heating noise."""
        now = datetime(2026, 3, 15, 23, 0)
        for i in range(20):
            t = now + timedelta(seconds=i * 30)
            # Moderate variance (could be heating noise)
            temp = 28.0 + 0.05 * (1 if i % 3 == 0 else -1)
            fast_detector._store(0, temp, None, None, t)

        # Without heater: might detect presence
        result_no_heat = fast_detector.detect_presence(
            zone_index=0, water_temp=28.0, heater_active=False
        )

        # Reset
        fast_detector2 = PresenceDetector(
            PresenceThresholds(
                presence_enter_minutes=0,
                presence_leave_minutes=0,
                variance_window_minutes=5,
                min_datapoints=3,
            )
        )
        for i in range(20):
            t = now + timedelta(seconds=i * 30)
            temp = 28.0 + 0.05 * (1 if i % 3 == 0 else -1)
            fast_detector2._store(0, temp, None, None, t)

        # With heater: should have higher threshold
        result_heat = fast_detector2.detect_presence(
            zone_index=0, water_temp=28.0, heater_active=True
        )
        # Heater active should result in lower confidence
        assert result_heat[1] <= result_no_heat[1]


class TestHeatingPadPresence:
    def test_body_heat_detected(self, fast_detector):
        """Rising temp without heater = body heat = presence."""
        now = datetime(2026, 3, 15, 23, 0)
        for i in range(20):
            t = now + timedelta(seconds=i * 30)
            # Temperature rising: body heat
            temp = 25.0 + i * 0.05
            fast_detector._store(0, temp, None, None, t)

        is_present, conf, reason = fast_detector.detect_presence(
            zone_index=0,
            water_temp=26.0,
            heater_active=False,
            is_heating_pad=True,
        )
        assert conf > 0.3


class TestSweatDetection:
    def test_no_sweat_normal_humidity(self, detector):
        """Normal humidity (50-70%) is not sweating."""
        now = datetime(2026, 3, 15, 23, 0)
        for i in range(60):
            t = now + timedelta(seconds=i * 30)
            detector._store(0, 28.0, None, 60.0, t)

        assert detector.is_sweating(0) is False

    def test_sweat_high_humidity_with_rise(self, detector):
        """Very high humidity with significant rise = sweating."""
        now = datetime(2026, 3, 15, 23, 0)
        # First: establish low baseline
        for i in range(200):
            t = now + timedelta(seconds=i * 30)
            detector._store(0, 28.0, None, 50.0, t)
        # Then: spike to 95%
        for i in range(40):
            t = now + timedelta(seconds=(200 + i) * 30)
            detector._store(0, 28.0, None, 95.0, t)

        assert detector.is_sweating(0) is True

    def test_humidity_levels(self, detector):
        now = datetime(2026, 3, 15, 23, 0)
        for i in range(10):
            t = now + timedelta(seconds=i * 30)
            detector._store(0, 28.0, None, 45.0, t)
        assert detector.get_humidity_level(0) == "trocken"


class TestLeakDetection:
    def test_no_leak_normal(self, detector):
        """Normal conditions = no leak."""
        assert detector.is_potential_leak(0) is False

    def test_leak_sustained_high_humidity(self, detector):
        """3+ hours of >85% humidity = potential leak."""
        now = datetime(2026, 3, 15, 23, 0)
        for i in range(400):  # ~3.3 hours at 30s
            t = now + timedelta(seconds=i * 30)
            detector._store(0, 28.0, None, 90.0, t)

        assert detector.is_potential_leak(0) is True


class TestHysteresis:
    def test_asymmetric_hysteresis(self, detector):
        """Enter fast (5min), leave slow (20min)."""
        assert detector.thresholds.presence_enter_minutes == 5
        assert detector.thresholds.presence_leave_minutes == 20


class TestDiagnostics:
    def test_diagnostics_structure(self, detector):
        diag = detector.get_diagnostics(0)
        assert "is_present" in diag
        assert "confidence" in diag
        assert "reason" in diag
        assert "water_temp_std" in diag
        assert "buffer_sizes" in diag
        assert "hysteresis" in diag
