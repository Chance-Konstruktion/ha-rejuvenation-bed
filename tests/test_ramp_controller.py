"""Tests for RampController - vinyl protection through gradual changes."""

import pytest
from datetime import datetime, timedelta

from custom_components.rejuvenation_bed.ramp_controller import (
    RampController,
    RampState,
)


@pytest.fixture
def controller():
    return RampController(max_change_per_hour=1.0, heating_rate=0.3)


class TestRampControllerInit:
    def test_default_values(self, controller):
        assert controller.max_change_per_hour == 1.0
        assert controller.heating_rate == 0.3

    def test_custom_values(self):
        c = RampController(max_change_per_hour=2.0, heating_rate=0.5)
        assert c.max_change_per_hour == 2.0
        assert c.heating_rate == 0.5


class TestRampedSetpoint:
    def test_first_call_returns_current(self, controller):
        """First call initializes with current temp."""
        setpoint, state = controller.calculate_ramped_setpoint(
            zone_index=0, desired_temp=29.0, current_temp=26.0
        )
        # First call: should be close to current temp (start of ramp)
        assert setpoint >= 26.0

    def test_heating_ramp_limits_change(self, controller):
        """Heating should be limited to max_change_per_hour."""
        # Initialize
        controller.calculate_ramped_setpoint(0, 29.0, 26.0)

        # Simulate 30 minutes passing
        controller._last_update[0] = datetime.now() - timedelta(minutes=30)
        setpoint, state = controller.calculate_ramped_setpoint(0, 29.0, 26.5)

        # In 30 min with 1C/h max: should allow max 0.5C change
        assert state.ramp_active
        assert state.ramp_direction == "heating"

    def test_cooling_is_immediate(self, controller):
        """Cooling should be immediate (no ramp needed)."""
        # Initialize at 29C
        controller._last_setpoint[0] = 29.0
        controller._last_update[0] = datetime.now()

        setpoint, state = controller.calculate_ramped_setpoint(0, 26.0, 29.0)

        # Cooling: should go directly to target
        assert setpoint == 26.0
        assert not state.ramp_active
        assert state.ramp_direction == "cooling"

    def test_target_reached_stable(self, controller):
        """When at target, state should be stable."""
        controller._last_setpoint[0] = 28.0
        controller._last_update[0] = datetime.now()

        setpoint, state = controller.calculate_ramped_setpoint(0, 28.0, 28.0)

        assert setpoint == 28.0
        assert not state.ramp_active
        assert state.ramp_direction == "stable"

    def test_small_diff_snaps_to_target(self, controller):
        """Differences < 0.1C should snap to target."""
        controller._last_setpoint[0] = 27.95
        controller._last_update[0] = datetime.now()

        setpoint, state = controller.calculate_ramped_setpoint(0, 28.0, 27.95)

        assert setpoint == 28.0
        assert not state.ramp_active


class TestPreheatCalculation:
    def test_no_preheat_already_warm(self, controller):
        """No preheat needed if already at target."""
        duration = controller.calculate_preheat_time(28.0, 28.0)
        assert duration.total_seconds() == 0

    def test_preheat_time_positive(self, controller):
        """Preheat time should be positive when below target."""
        duration = controller.calculate_preheat_time(26.0, 28.0, 300, 350)
        assert duration.total_seconds() > 0

    def test_more_water_longer_preheat(self, controller):
        """More water = longer preheat time."""
        small = controller.calculate_preheat_time(26.0, 28.0, 300, 200)
        large = controller.calculate_preheat_time(26.0, 28.0, 300, 600)
        assert large > small

    def test_more_power_shorter_preheat(self, controller):
        """More power = shorter preheat time."""
        weak = controller.calculate_preheat_time(26.0, 28.0, 200, 350)
        strong = controller.calculate_preheat_time(26.0, 28.0, 600, 350)
        assert strong < weak

    def test_preheat_respects_ramp_limit(self, controller):
        """Preheat time must respect the ramp limit (1C/h)."""
        duration = controller.calculate_preheat_time(24.0, 28.0, 1000, 100)
        hours = duration.total_seconds() / 3600
        # 4C at 1C/h = 4h minimum + buffer
        assert hours >= 4.0


class TestShouldStartPreheat:
    def test_before_optimal_start(self, controller):
        """Should not start if too early."""
        bedtime = datetime.now() + timedelta(hours=12)
        should, reason = controller.should_start_preheat(
            26.0, 28.0, bedtime, 300, 350
        )
        assert not should

    def test_at_optimal_start(self, controller):
        """Should start when it's time."""
        # Calculate how long preheat takes
        duration = controller.calculate_preheat_time(26.0, 28.0, 300, 350)
        # Set bedtime to exactly duration from now
        bedtime = datetime.now() + duration - timedelta(minutes=1)
        should, reason = controller.should_start_preheat(
            26.0, 28.0, bedtime, 300, 350
        )
        assert should

    def test_past_bedtime(self, controller):
        """Should not start if bedtime already passed."""
        bedtime = datetime.now() - timedelta(hours=1)
        should, reason = controller.should_start_preheat(
            26.0, 28.0, bedtime, 300, 350
        )
        assert not should


class TestForceSetpoint:
    def test_force_bypasses_ramp(self, controller):
        """Force setpoint should skip ramp limits."""
        controller._last_setpoint[0] = 26.0
        controller._last_update[0] = datetime.now()
        controller._target_temp[0] = 26.0

        controller.force_setpoint(0, 30.0)

        assert controller._last_setpoint[0] == 30.0
        assert controller._target_temp[0] == 30.0


class TestRampState:
    def test_get_ramp_state_uninitialized(self, controller):
        assert controller.get_ramp_state(0) is None

    def test_get_ramp_state_after_use(self, controller):
        controller.calculate_ramped_setpoint(0, 29.0, 26.0)
        state = controller.get_ramp_state(0)
        assert state is not None
        assert isinstance(state, RampState)


class TestPersistence:
    def test_export_state(self, controller):
        controller.calculate_ramped_setpoint(0, 29.0, 26.0)
        data = controller.get_state_for_storage()
        assert "last_setpoint" in data
        assert "target_temp" in data
        assert "saved_at" in data

    def test_restore_recent_state(self, controller):
        controller.calculate_ramped_setpoint(0, 29.0, 26.0)
        data = controller.get_state_for_storage()

        new_controller = RampController()
        new_controller.restore_state_from_storage(data)
        assert 0 in new_controller._last_setpoint

    def test_reject_old_state(self, controller):
        data = {
            "saved_at": (datetime.now() - timedelta(hours=1)).isoformat(),
            "last_setpoint": {"0": 28.0},
        }
        controller.restore_state_from_storage(data)
        assert 0 not in controller._last_setpoint  # Should be rejected (>30min)
