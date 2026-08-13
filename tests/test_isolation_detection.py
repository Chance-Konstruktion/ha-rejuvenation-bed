"""Tests for isolation detection in BedIntelligence.

Validates against real CSV data (April 2026): user reported the sensor
was always showing "covered" because the code's water-air delta convention
assumed the air sensor sits in room air (cooler than water). With an
auflage_temperatur sensor (sits on top of the bed core, warmer than the
water), water-air becomes negative and the old `delta < 0.15` threshold
trivially matched, locking the sensor to "covered".
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

from custom_components.rejuvenation_bed.bed_intelligence import (
    BedIntelligence,
)


def _make_intelligence():
    config_entry = MagicMock()
    config_entry.entry_id = "test_entry"
    bi = BedIntelligence(hass=MagicMock(), config_entry=config_entry)
    bi._has_air_temp[0] = True
    return bi


def _feed(bi, zone, water, air, minutes_each=1, samples=35, start=None):
    """Push enough samples to fill the smoothing window with stable values."""
    t = start or datetime(2026, 4, 29, 6, 0)
    for _ in range(samples):
        bi._update_isolation(zone, water, air, is_present=False, now=t)
        t += timedelta(minutes=minutes_each)
    return t


def test_auflage_sensor_open_bed_detected_as_uncovered():
    """Bed open with auflage sensor → |Δ| ≈ 1.5°K → uncovered."""
    bi = _make_intelligence()
    _feed(bi, 0, water=28.5, air=30.0)  # |Δ| = 1.5
    iso = bi.get_isolation_status(0)
    assert iso.is_covered is False
    assert iso.level == "offen"


def test_auflage_sensor_covered_bed_detected_as_covered():
    """Bed covered with auflage sensor → |Δ| ≈ 2.5°K → covered."""
    bi = _make_intelligence()
    _feed(bi, 0, water=29.5, air=32.0)  # |Δ| = 2.5
    iso = bi.get_isolation_status(0)
    assert iso.is_covered is True
    assert iso.level in ("gut", "mäßig")


def test_room_air_sensor_setup_works_with_inverted_calibration():
    """Classic SHT41 room-air setup: covered_mean < uncovered_mean.

    Water 28°C, room 22°C → |Δ| ≈ 6 (open). With blanket the sensor
    catches more bed warmth → |Δ| ≈ 4 (covered).
    """
    bi = _make_intelligence()
    bi.calibration.delta_covered_mean = 4.0
    bi.calibration.delta_uncovered_mean = 6.0
    _feed(bi, 0, water=28.0, air=22.0)  # |Δ| = 6.0 → open
    assert bi.get_isolation_status(0).is_covered is False

    bi2 = _make_intelligence()
    bi2.calibration.delta_covered_mean = 4.0
    bi2.calibration.delta_uncovered_mean = 6.0
    _feed(bi2, 0, water=28.0, air=24.0)  # |Δ| = 4.0 → covered
    assert bi2.get_isolation_status(0).is_covered is True


def test_hysteresis_prevents_flicker_around_threshold():
    """A delta hovering around the boundary should not flicker each sample."""
    bi = _make_intelligence()
    # Settle in covered state at |Δ| = 2.0 (above default threshold 1.75)
    end = _feed(bi, 0, water=29.0, air=31.0)
    assert bi.get_isolation_status(0).is_covered is True

    # Drop to |Δ| = 1.7 — inside the hysteresis band, should stay covered
    _feed(bi, 0, water=29.0, air=30.7, samples=10, start=end)
    assert bi.get_isolation_status(0).is_covered is True

    # Drop further to |Δ| = 1.4 — clearly below, should switch to uncovered
    end = _feed(bi, 0, water=29.0, air=30.4, samples=35, start=end)
    assert bi.get_isolation_status(0).is_covered is False


def test_user_csv_april_2026_open_phase():
    """22:00–01:00 phase from real CSV: leer, offen → uncovered."""
    bi = _make_intelligence()
    _feed(bi, 0, water=28.5, air=29.85)  # |Δ| ≈ 1.35
    assert bi.get_isolation_status(0).is_covered is False


def test_user_csv_april_2026_covered_sleep_phase():
    """06:00–15:30 phase from real CSV: User im Bett, Decke → covered."""
    bi = _make_intelligence()
    _feed(bi, 0, water=29.7, air=32.2)  # |Δ| ≈ 2.5
    assert bi.get_isolation_status(0).is_covered is True


def test_uncovered_minutes_timer_runs_only_when_uncovered():
    bi = _make_intelligence()
    end = _feed(bi, 0, water=28.5, air=30.0)
    iso = bi.get_isolation_status(0)
    assert iso.is_covered is False
    assert iso.uncovered_minutes > 0

    # Cover it → timer resets
    _feed(bi, 0, water=29.5, air=32.0, samples=35, start=end)
    iso = bi.get_isolation_status(0)
    assert iso.is_covered is True
    assert iso.uncovered_minutes == 0


def test_returns_early_on_missing_temps():
    bi = _make_intelligence()
    # Neither call should raise
    bi._update_isolation(0, water_temp=None, air_temp=30.0, is_present=False, now=datetime.now())
    bi._update_isolation(0, water_temp=29.0, air_temp=None, is_present=False, now=datetime.now())
    # No status created
    assert 0 not in bi._isolation


def test_calibration_collects_absolute_deltas():
    """Auto-calibration must store |Δ|, not signed delta, to be sensor-agnostic."""
    bi = _make_intelligence()
    bi._update_calibration(
        zone_index=0,
        water_temp=28.5,
        air_temp=30.0,  # auflage sensor: air > water
        humidity=None,
        is_present=False,
        water_std=0.05,
        now=datetime.now(),
    )
    # |Δ| = 1.5, not -1.5
    assert all(d >= 0 for d in bi.calibration._empty_deltas)
    assert bi.calibration._empty_deltas[-1] == 1.5
