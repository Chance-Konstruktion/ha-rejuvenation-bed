"""Tests for BiorhythmusCurve - pure math, no HA dependency."""

import pytest
from datetime import datetime, time, timedelta

from custom_components.rejuvenation_bed.biorhythmus_curve import (
    BiorhythmusCurve,
    CHRONOTYPE_NADIR_OFFSETS,
)


class TestBiorhythmusCurveInit:
    """Test curve initialization with various parameters."""

    def test_default_temps_no_outdoor(self):
        """Without outdoor sensor, use ganzjahres defaults."""
        curve = BiorhythmusCurve(bedtime=time(23, 0), wake_time=time(7, 0))
        assert curve.sleep_temp == 28.0
        assert curve.deep_sleep_temp == 27.0
        assert curve.wake_temp == 29.0

    def test_summer_profile(self):
        """Outdoor >20C triggers summer temps."""
        curve = BiorhythmusCurve(bedtime=time(23, 0), wake_time=time(7, 0), outdoor_temp=25.0)
        assert curve.sleep_temp == 27.0
        assert curve.deep_sleep_temp == 26.0
        assert curve.wake_temp == 28.0

    def test_winter_profile(self):
        """Outdoor <15C triggers winter temps."""
        curve = BiorhythmusCurve(bedtime=time(23, 0), wake_time=time(7, 0), outdoor_temp=10.0)
        assert curve.sleep_temp == 29.0
        assert curve.deep_sleep_temp == 27.5
        assert curve.wake_temp == 30.0

    def test_transition_profile(self):
        """Between 15-20C linearly interpolates."""
        curve = BiorhythmusCurve(bedtime=time(23, 0), wake_time=time(7, 0), outdoor_temp=17.5)
        # 17.5 is midpoint: 50% summer + 50% winter
        assert 27.5 < curve.sleep_temp < 28.5
        assert 26.5 < curve.deep_sleep_temp < 27.5

    def test_user_offset_applied(self):
        """User offset shifts all temperatures."""
        curve = BiorhythmusCurve(bedtime=time(23, 0), wake_time=time(7, 0), user_offset=1.5)
        assert curve.sleep_temp == 28.0 + 1.5
        assert curve.deep_sleep_temp == 27.0 + 1.5
        assert curve.wake_temp == 29.0 + 1.5

    def test_manual_temps_override_seasonal(self):
        """Explicit temps override seasonal calculation."""
        curve = BiorhythmusCurve(
            bedtime=time(23, 0),
            wake_time=time(7, 0),
            sleep_temp=30.0,
            deep_sleep_temp=28.0,
            wake_temp=31.0,
            outdoor_temp=25.0,  # Would be summer, but manual overrides
        )
        assert curve.sleep_temp == 30.0
        assert curve.deep_sleep_temp == 28.0
        assert curve.wake_temp == 31.0

    def test_chronotype_offsets(self):
        """Chronotypes have correct nadir offsets."""
        assert CHRONOTYPE_NADIR_OFFSETS["lerche"] == -1.5
        assert CHRONOTYPE_NADIR_OFFSETS["normal"] == 0.0
        assert CHRONOTYPE_NADIR_OFFSETS["eule"] == 1.5


class TestBiorhythmusCurveTemperature:
    """Test temperature calculation at various times."""

    @pytest.fixture
    def standard_curve(self):
        return BiorhythmusCurve(
            bedtime=time(23, 0),
            wake_time=time(7, 0),
            sleep_temp=28.5,
            deep_sleep_temp=27.0,
            wake_temp=29.0,
        )

    def test_at_bedtime_returns_sleep_temp(self, standard_curve):
        """At bedtime, temperature should be near sleep_temp."""
        t = datetime(2026, 3, 15, 23, 0)
        temp = standard_curve.get_target_temperature(t)
        assert abs(temp - 28.5) < 0.1

    def test_deep_sleep_phase_constant(self, standard_curve):
        """During deep sleep phase, temp should be at deep_sleep_temp."""
        # Deep sleep is roughly 0.08-0.63 of the cycle
        # 8h sleep: 0.08*8=0.64h after bedtime to 0.63*8=5.04h
        # So ~23:38 to ~04:02
        t = datetime(2026, 3, 16, 2, 0)  # Middle of deep sleep
        temp = standard_curve.get_target_temperature(t)
        assert abs(temp - 27.0) < 0.1

    def test_wake_phase_approaches_wake_temp(self, standard_curve):
        """Near wake time, temperature should approach wake_temp."""
        t = datetime(2026, 3, 16, 6, 55)  # 5 min before wake
        temp = standard_curve.get_target_temperature(t)
        assert abs(temp - 29.0) < 0.5

    def test_temperature_monotonic_in_landing(self, standard_curve):
        """During landing phase, temp should decrease monotonically."""
        base = datetime(2026, 3, 15, 23, 0)
        temps = []
        for i in range(8):  # First ~30 min (landing phase)
            t = base + timedelta(minutes=i * 4)
            temps.append(standard_curve.get_target_temperature(t))
        # Should be decreasing (or at least not increasing significantly)
        for i in range(1, len(temps)):
            assert temps[i] <= temps[i - 1] + 0.05

    def test_temperature_in_valid_range(self, standard_curve):
        """All temperatures should be between deep_sleep and wake temps."""
        base = datetime(2026, 3, 15, 23, 0)
        for i in range(96):  # Every 5 min for 8 hours
            t = base + timedelta(minutes=i * 5)
            temp = standard_curve.get_target_temperature(t)
            assert 26.5 <= temp <= 29.5, f"Temp {temp} at {t} out of range"

    def test_smooth_no_jumps(self, standard_curve):
        """Temperature changes should be smooth (no jumps > 0.5C per 5min)."""
        base = datetime(2026, 3, 15, 23, 0)
        prev_temp = standard_curve.get_target_temperature(base)
        for i in range(1, 96):
            t = base + timedelta(minutes=i * 5)
            temp = standard_curve.get_target_temperature(t)
            delta = abs(temp - prev_temp)
            assert delta < 0.5, f"Jump of {delta}C at {t}"
            prev_temp = temp


class TestBiorhythmusCurveValidation:
    """Test parameter validation."""

    def test_valid_params(self):
        curve = BiorhythmusCurve(
            bedtime=time(23, 0),
            wake_time=time(7, 0),
            sleep_temp=28.5,
            deep_sleep_temp=27.0,
            wake_temp=29.0,
        )
        valid, msg = curve.validate_parameters()
        assert valid
        assert "OK" in msg

    def test_deep_higher_than_sleep_flagged(self):
        curve = BiorhythmusCurve(
            bedtime=time(23, 0),
            wake_time=time(7, 0),
            sleep_temp=27.0,
            deep_sleep_temp=28.0,  # Higher than sleep!
            wake_temp=29.0,
        )
        valid, msg = curve.validate_parameters()
        assert not valid

    def test_short_sleep_flagged(self):
        curve = BiorhythmusCurve(
            bedtime=time(2, 0),
            wake_time=time(4, 0),  # Only 2h
            sleep_temp=28.0,
            deep_sleep_temp=27.0,
            wake_temp=29.0,
        )
        valid, msg = curve.validate_parameters()
        assert not valid
        assert "kurz" in msg

    def test_long_sleep_flagged(self):
        curve = BiorhythmusCurve(
            bedtime=time(20, 0),
            wake_time=time(10, 0),  # 14h
            sleep_temp=28.0,
            deep_sleep_temp=27.0,
            wake_temp=29.0,
        )
        valid, msg = curve.validate_parameters()
        assert not valid
        assert "lang" in msg


class TestBiorhythmusCurveCurveInfo:
    """Test curve info/diagnostics."""

    def test_phases_have_correct_names(self):
        curve = BiorhythmusCurve(bedtime=time(23, 0), wake_time=time(7, 0))
        # At bedtime -> Landing
        info = curve.get_curve_info(datetime(2026, 3, 15, 23, 5))
        assert info["phase"] == "Landing"

        # Deep sleep
        info = curve.get_curve_info(datetime(2026, 3, 16, 2, 0))
        assert info["phase"] == "Tiefschlaf"

        # Near wake
        info = curve.get_curve_info(datetime(2026, 3, 16, 6, 50))
        assert info["phase"] == "Aufwachen"

    def test_curve_info_contains_expected_keys(self):
        curve = BiorhythmusCurve(bedtime=time(23, 0), wake_time=time(7, 0))
        info = curve.get_curve_info(datetime(2026, 3, 16, 2, 0))
        assert "normalized_time" in info
        assert "target_temperature" in info
        assert "phase" in info
        assert "phase_progress" in info
        assert "bedtime" in info
        assert "wake_time" in info


class TestBiorhythmusCurveSeasonalUpdate:
    """Test outdoor temperature updates."""

    def test_update_outdoor_temp(self):
        curve = BiorhythmusCurve(bedtime=time(23, 0), wake_time=time(7, 0), outdoor_temp=10.0)
        assert curve.deep_sleep_temp == 27.5  # Winter

        curve.update_outdoor_temp(25.0)
        assert curve.deep_sleep_temp == 26.0  # Summer

    def test_no_change_on_same_temp(self):
        curve = BiorhythmusCurve(bedtime=time(23, 0), wake_time=time(7, 0), outdoor_temp=10.0)
        old_deep = curve.deep_sleep_temp
        curve.update_outdoor_temp(10.0)
        assert curve.deep_sleep_temp == old_deep


class TestSmoothCos:
    """Test the smooth cosine function."""

    def test_boundaries(self):
        assert BiorhythmusCurve._smooth_cos(0.0) == pytest.approx(0.0, abs=1e-10)
        assert BiorhythmusCurve._smooth_cos(1.0) == pytest.approx(1.0, abs=1e-10)

    def test_midpoint(self):
        assert BiorhythmusCurve._smooth_cos(0.5) == pytest.approx(0.5, abs=1e-10)

    def test_monotonic(self):
        prev = 0.0
        for i in range(1, 101):
            x = i / 100
            val = BiorhythmusCurve._smooth_cos(x)
            assert val >= prev
            prev = val
