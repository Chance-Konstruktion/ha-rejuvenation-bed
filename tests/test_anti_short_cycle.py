"""Tests for AntiShortCycleManager - relay protection."""

import pytest
from datetime import datetime, timedelta

from custom_components.rejuvenation_bed.anti_short_cycle_manager import (
    AntiShortCycleManager,
)


@pytest.fixture
def manager():
    m = AntiShortCycleManager()
    # Skip grace period for tests
    m._startup_time = datetime.now() - timedelta(minutes=10)
    return m


class TestGracePeriod:
    def test_grace_period_allows_switching(self):
        """During grace period, switching should be allowed."""
        m = AntiShortCycleManager()  # Fresh, in grace period
        allowed, reason = m.can_switch("switch.heater", False, True, 26.0, 28.0)
        # Grace period should allow the switch
        assert "Grace" in reason

    def test_grace_period_expires(self):
        m = AntiShortCycleManager()
        m._startup_time = datetime.now() - timedelta(minutes=10)
        assert not m._is_in_grace_period()


class TestFirstDecision:
    def test_first_switch_always_allowed(self, manager):
        allowed, reason = manager.can_switch("switch.heater", False, True, 26.0, 28.0)
        assert allowed
        assert "Erste" in reason


class TestMinRunTime:
    def test_cannot_turn_off_too_quickly(self, manager):
        """After turning ON, must stay on for MIN_RUN_TIME."""
        # First decision initializes history
        manager.can_switch("switch.heater", False, True, 26.0, 28.0)
        # Set last_on_time to "just now" to simulate a recent turn-on
        manager._state_history["switch.heater"]["last_on_time"] = datetime.now()

        # Try to turn off immediately - blocked by min run time
        allowed, reason = manager.can_switch("switch.heater", True, False, 29.0, 28.0)
        assert not allowed
        assert "ON-Zeit" in reason

    def test_can_turn_off_after_min_time(self, manager):
        """After MIN_RUN_TIME, can turn off."""
        # Turn on
        manager.can_switch("switch.heater", False, True, 26.0, 28.0)

        # Fast-forward past min run time
        manager._state_history["switch.heater"]["last_on_time"] = datetime.now() - timedelta(seconds=700)

        allowed, reason = manager.can_switch("switch.heater", True, False, 28.5, 28.0)
        assert allowed


class TestMinOffTime:
    def test_cannot_turn_on_too_quickly(self, manager):
        """After turning OFF, must stay off for MIN_OFF_TIME."""
        # First turn on then off
        manager.can_switch("switch.heater", False, True, 26.0, 28.0)
        manager._state_history["switch.heater"]["last_on_time"] = datetime.now() - timedelta(seconds=700)
        manager.can_switch("switch.heater", True, False, 28.5, 28.0)

        # Try to turn on again immediately
        allowed, reason = manager.can_switch("switch.heater", False, True, 27.5, 28.0)
        assert not allowed
        assert "OFF-Zeit" in reason


class TestHysteresis:
    def test_no_turn_on_above_threshold(self, manager):
        """Don't turn on if only slightly below target."""
        # First register the heater
        manager.can_switch("switch.heater", False, True, 26.0, 28.0)
        manager._state_history["switch.heater"]["last_on_time"] = datetime.now() - timedelta(seconds=700)
        manager.can_switch("switch.heater", True, False, 28.5, 28.0)
        manager._state_history["switch.heater"]["last_off_time"] = datetime.now() - timedelta(seconds=400)

        # Try to turn on at 27.9 (only 0.1 below target of 28.0)
        allowed, reason = manager.can_switch("switch.heater", False, True, 27.9, 28.0)
        assert not allowed
        assert "Hysterese" in reason

    def test_turn_on_well_below_threshold(self, manager):
        """Turn on if significantly below target."""
        manager.can_switch("switch.heater", False, True, 26.0, 28.0)
        manager._state_history["switch.heater"]["last_on_time"] = datetime.now() - timedelta(seconds=700)
        manager.can_switch("switch.heater", True, False, 28.5, 28.0)
        manager._state_history["switch.heater"]["last_off_time"] = datetime.now() - timedelta(seconds=400)

        # Turn on at 27.5 (0.5 below target, exceeds 0.3 hysteresis)
        allowed, reason = manager.can_switch("switch.heater", False, True, 27.5, 28.0)
        assert allowed


class TestNoChange:
    def test_same_state_always_ok(self, manager):
        """No change needed = always allowed."""
        manager.can_switch("switch.heater", False, True, 26.0, 28.0)
        allowed, reason = manager.can_switch("switch.heater", True, True, 27.0, 28.0)
        assert allowed
        assert "Keine Änderung" in reason


class TestHardwareSync:
    def test_sync_updates_state(self, manager):
        manager.sync_with_hardware("switch.heater", True)
        assert manager._state_history["switch.heater"]["current_state"] is True

    def test_sync_allows_immediate_switching(self, manager):
        """After sync, should allow switching (fake 'long ago')."""
        manager.sync_with_hardware("switch.heater", True)
        # Should be able to turn off immediately (last_on_time was set to 30min ago)
        allowed, reason = manager.can_switch("switch.heater", True, False, 28.5, 28.0)
        assert allowed


class TestForceOverride:
    def test_force_allows_next_switch(self, manager):
        # Turn on
        manager.can_switch("switch.heater", False, True, 26.0, 28.0)
        # Force override
        manager.force_allow_switch("switch.heater")
        # Should now be able to turn off immediately
        allowed, reason = manager.can_switch("switch.heater", True, False, 28.5, 28.0)
        assert allowed


class TestDiagnostics:
    def test_diagnostics_structure(self, manager):
        diag = manager.get_diagnostics()
        assert "total_decisions" in diag
        assert "blocked_switches" in diag
        assert "blocked_percentage" in diag
        assert "grace_period_active" in diag
        assert "active_heaters" in diag
        assert "heater_states" in diag

    def test_blocked_count(self, manager):
        # Turn on and set last_on_time to now (simulating recent turn-on)
        manager.can_switch("switch.heater", False, True, 26.0, 28.0)
        manager._state_history["switch.heater"]["last_on_time"] = datetime.now()
        # Try turning off too quick (blocked by min run time)
        manager.can_switch("switch.heater", True, False, 29.0, 28.0)

        diag = manager.get_diagnostics()
        assert diag["blocked_switches"] >= 1
