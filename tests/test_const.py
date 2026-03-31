"""Tests for constants and configuration models."""

from custom_components.rejuvenation_bed.const import (
    DOMAIN,
    ABSOLUTE_MAX_TEMP,
    BED_TYPE_WATERBED,
    BED_TYPE_HEATING_PAD,
    WATERBED_CONFIG,
    HEATING_PAD_CONFIG,
    get_bed_config,
)


class TestConstants:
    def test_domain(self):
        assert DOMAIN == "rejuvenation_bed"

    def test_absolute_max_temp(self):
        assert ABSOLUTE_MAX_TEMP == 38


class TestBedConfigs:
    def test_waterbed_never_below_24(self):
        """Waterbed min temp must be 24C for condensation protection."""
        assert WATERBED_CONFIG["min_temp"] >= 24.0

    def test_waterbed_cannot_turn_off(self):
        """Waterbed eco mode must never turn off completely."""
        assert WATERBED_CONFIG["eco_can_turn_off"] is False

    def test_waterbed_has_ramp(self):
        """Waterbed must use ramp for vinyl protection."""
        assert WATERBED_CONFIG["ramp_enabled"] is True

    def test_waterbed_max_change_per_hour(self):
        """Waterbed should change max 1C/h."""
        assert WATERBED_CONFIG["max_change_per_hour"] <= 1.0

    def test_heating_pad_can_be_off(self):
        """Heating pad can be completely off."""
        assert HEATING_PAD_CONFIG["eco_can_turn_off"] is True
        assert HEATING_PAD_CONFIG["min_temp"] == 0.0

    def test_heating_pad_no_ramp(self):
        assert HEATING_PAD_CONFIG["ramp_enabled"] is False

    def test_heating_pad_fast_heating(self):
        """Heating pad should heat much faster than waterbed."""
        assert HEATING_PAD_CONFIG["heating_rate"] > WATERBED_CONFIG["heating_rate"] * 5


class TestGetBedConfig:
    def test_waterbed_type(self):
        config = get_bed_config(BED_TYPE_WATERBED)
        assert config["min_temp"] == 24.0
        assert config["ramp_enabled"] is True

    def test_heating_pad_type(self):
        config = get_bed_config(BED_TYPE_HEATING_PAD)
        assert config["min_temp"] == 0.0
        assert config["ramp_enabled"] is False

    def test_unknown_type_defaults_waterbed(self):
        """Unknown bed type should default to waterbed (safer)."""
        config = get_bed_config("unknown")
        assert config["min_temp"] == 24.0

    def test_returns_copy(self):
        """Should return a copy, not the original dict."""
        config1 = get_bed_config(BED_TYPE_WATERBED)
        config2 = get_bed_config(BED_TYPE_WATERBED)
        config1["min_temp"] = 999
        assert config2["min_temp"] == 24.0


class TestConfigConsistency:
    def test_waterbed_temps_consistent(self):
        """Waterbed temps should be logically consistent."""
        c = WATERBED_CONFIG
        assert c["min_temp"] <= c["standby_temp"]
        assert c["standby_temp"] <= c["max_temp"]
        assert c["away_temp"] >= c["min_temp"]

    def test_heating_pad_temps_consistent(self):
        c = HEATING_PAD_CONFIG
        assert c["min_temp"] <= c["max_temp"]

    def test_all_required_keys_present(self):
        """Both configs should have the same keys."""
        waterbed_keys = set(WATERBED_CONFIG.keys())
        pad_keys = set(HEATING_PAD_CONFIG.keys())
        # Some keys may differ (preheat_hours vs preheat_minutes)
        common = {
            "min_temp",
            "max_temp",
            "standby_temp",
            "away_temp",
            "max_change_per_hour",
            "ramp_enabled",
            "thermal_battery",
            "leak_detection",
            "condensation_risk",
            "solar_boost_max",
            "solar_boost_enabled",
            "eco_reduction_max",
            "eco_can_turn_off",
        }
        assert common.issubset(waterbed_keys)
        assert common.issubset(pad_keys)
