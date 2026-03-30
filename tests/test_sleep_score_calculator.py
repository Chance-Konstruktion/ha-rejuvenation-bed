"""Tests for SleepScoreCalculator - sleep quality metrics."""

import pytest
from datetime import datetime, time
from unittest.mock import MagicMock, patch

from custom_components.rejuvenation_bed.sleep_score_calculator import (
    SleepScoreCalculator,
    NightData,
    SleepScore,
)


@pytest.fixture
def mock_hass():
    return MagicMock()


@pytest.fixture
def mock_config_entry():
    entry = MagicMock()
    entry.options = {}
    entry.data = {"global": {}}
    return entry


@pytest.fixture
def calculator(mock_hass, mock_config_entry):
    return SleepScoreCalculator(mock_hass, mock_config_entry)


class TestNightData:
    def test_default_values(self):
        night = NightData(
            date=datetime(2026, 3, 15), zone_index=0
        )
        assert night.heating_cycles == 0
        assert night.interruptions == 0
        assert night.co2_readings == []
        assert night.temp_readings == []


class TestScoreWeights:
    def test_weights_sum_to_one(self):
        total = (
            SleepScoreCalculator.WEIGHT_TEMPERATURE_STABILITY
            + SleepScoreCalculator.WEIGHT_CURVE_ADHERENCE
            + SleepScoreCalculator.WEIGHT_WARMUP
            + SleepScoreCalculator.WEIGHT_HEATING_EFFICIENCY
            + SleepScoreCalculator.WEIGHT_AIR_QUALITY
        )
        assert abs(total - 1.0) < 0.01


class TestTemperatureStability:
    def test_perfect_stability(self, calculator):
        night = NightData(date=datetime(2026, 3, 15), zone_index=0)
        night.temp_readings = [28.0] * 100  # Perfectly stable
        score = calculator._calc_temperature_stability(night)
        assert score == 100

    def test_poor_stability(self, calculator):
        night = NightData(date=datetime(2026, 3, 15), zone_index=0)
        # Very unstable: alternating between 26 and 30
        night.temp_readings = [26.0, 30.0] * 50
        score = calculator._calc_temperature_stability(night)
        assert score < 50

    def test_moderate_stability(self, calculator):
        night = NightData(date=datetime(2026, 3, 15), zone_index=0)
        import math
        # Moderate: +/- 0.4C
        night.temp_readings = [28.0 + 0.4 * math.sin(i * 0.1) for i in range(100)]
        score = calculator._calc_temperature_stability(night)
        assert 50 < score < 100

    def test_too_few_readings(self, calculator):
        night = NightData(date=datetime(2026, 3, 15), zone_index=0)
        night.temp_readings = [28.0]
        score = calculator._calc_temperature_stability(night)
        assert score == 50  # Neutral default


class TestCurveAdherence:
    def test_perfect_adherence(self, calculator):
        night = NightData(date=datetime(2026, 3, 15), zone_index=0)
        targets = [28.0 - i * 0.02 for i in range(100)]
        night.temp_readings = targets.copy()  # Exact match
        night.target_temps = targets
        score = calculator._calc_curve_adherence(night)
        assert score == 100

    def test_poor_adherence(self, calculator):
        night = NightData(date=datetime(2026, 3, 15), zone_index=0)
        night.target_temps = [28.0] * 100
        night.temp_readings = [26.0] * 100  # 2C off target
        score = calculator._calc_curve_adherence(night)
        assert score < 50

    def test_slight_deviation(self, calculator):
        night = NightData(date=datetime(2026, 3, 15), zone_index=0)
        night.target_temps = [28.0] * 100
        night.temp_readings = [28.2] * 100  # 0.2C off
        score = calculator._calc_curve_adherence(night)
        assert score >= 80


class TestHeatingEfficiency:
    def test_no_heating_perfect(self, calculator):
        night = NightData(date=datetime(2026, 3, 15), zone_index=0)
        night.heating_cycles = 0
        score = calculator._calc_heating_efficiency(night)
        assert score == 100

    def test_long_cycles_good(self, calculator):
        night = NightData(date=datetime(2026, 3, 15), zone_index=0)
        night.heating_cycles = 4
        night.total_heating_minutes = 80  # 20 min avg
        score = calculator._calc_heating_efficiency(night)
        assert score >= 80

    def test_short_cycles_bad(self, calculator):
        night = NightData(date=datetime(2026, 3, 15), zone_index=0)
        night.heating_cycles = 20
        night.total_heating_minutes = 40  # 2 min avg
        score = calculator._calc_heating_efficiency(night)
        assert score < 50

    def test_prevented_cycles_bonus(self, calculator):
        night = NightData(date=datetime(2026, 3, 15), zone_index=0)
        night.heating_cycles = 5
        night.total_heating_minutes = 50  # 10 min avg = score ~80

        # Without bonus
        score_without = calculator._calc_heating_efficiency(night)

        night.short_cycles_prevented = 5
        score_with = calculator._calc_heating_efficiency(night)
        assert score_with >= score_without


class TestAirQuality:
    def test_no_co2_data(self, calculator):
        night = NightData(date=datetime(2026, 3, 15), zone_index=0)
        score, has_data = calculator._calc_air_quality(night)
        assert not has_data
        assert score == 0

    def test_excellent_air(self, calculator):
        night = NightData(date=datetime(2026, 3, 15), zone_index=0)
        night.co2_readings = [500] * 50
        score, has_data = calculator._calc_air_quality(night)
        assert has_data
        assert score == 100

    def test_poor_air(self, calculator):
        night = NightData(date=datetime(2026, 3, 15), zone_index=0)
        night.co2_readings = [1800] * 50
        score, has_data = calculator._calc_air_quality(night)
        assert has_data
        assert score < 40


class TestInterruptionPenalty:
    def test_no_interruptions(self, calculator):
        night = NightData(date=datetime(2026, 3, 15), zone_index=0)
        night.temp_readings = [28.0] * 100
        night.target_temps = [28.0] * 100
        score = calculator._calculate_score(night)
        base_score = score.total_score

        # Score should be high with perfect conditions
        assert base_score > 80

    def test_interruptions_reduce_score(self, calculator):
        night = NightData(date=datetime(2026, 3, 15), zone_index=0)
        night.temp_readings = [28.0] * 100
        night.target_temps = [28.0] * 100
        night.interruptions = 3
        night.total_interruption_minutes = 30
        score = calculator._calculate_score(night)

        # 3+ interruptions = -12 penalty
        assert score.total_score < 90


class TestTips:
    def test_good_score_positive_tip(self, calculator):
        tips = calculator._generate_tips(90, 95, 100, 90, 90, True)
        assert any("Exzellent" in t or "Gute" in t for t in tips)

    def test_poor_co2_tip(self, calculator):
        tips = calculator._generate_tips(90, 90, 100, 90, 40, True)
        assert any("CO2" in t for t in tips)

    def test_poor_efficiency_tip(self, calculator):
        tips = calculator._generate_tips(90, 90, 100, 40, 90, True)
        assert any("Heizzyklen" in t for t in tips)


class TestTrend:
    def test_no_history_neutral(self, calculator):
        trend, value = calculator._calculate_trend(0)
        assert trend == "→"
        assert value == 0

    @patch("custom_components.rejuvenation_bed.sleep_score_calculator.local_now")
    def test_tracking_lifecycle(self, mock_now, calculator):
        """Test start, record, end tracking flow."""
        mock_now.return_value = datetime(2026, 3, 16, 7, 0)

        calculator.start_night_tracking(
            0,
            planned_bedtime=datetime(2026, 3, 15, 23, 0),
            planned_wake=datetime(2026, 3, 16, 7, 0),
        )

        # Record data
        for i in range(30):
            calculator.record_temperature(0, 28.0 + 0.1, 28.0)

        score = calculator.end_night_tracking(0)
        assert score is not None
        assert 0 <= score.total_score <= 100


class TestWeeklyAverage:
    def test_no_data(self, calculator):
        assert calculator.get_weekly_average(0) is None

    def test_last_score(self, calculator):
        assert calculator.get_last_score(0) is None
