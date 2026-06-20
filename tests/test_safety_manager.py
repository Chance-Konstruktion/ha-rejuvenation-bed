"""Tests für den SafetyManager (zweite Verteidigungslinie).

Deckt die jetzt verdrahteten Checks ab (#1):
- Übertemperatur (Warnung / Kritisch / Emergency-Latch)
- Klebe-Relais-Erkennung
- Sensor-Defekt-Erkennung
- Spam-Throttle der Warnungen
- Degraded-Duty-Cycle
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from custom_components.rejuvenation_bed.safety_manager import (
    SafetyManager,
    OVERHEAT_WARNING_TEMP,
    OVERHEAT_CRITICAL_TEMP,
    OVERHEAT_EMERGENCY_TEMP,
)

BASE = datetime(2026, 6, 20, 22, 0, 0)


def _run(coro):
    """Führt eine Coroutine in einem frischen Event-Loop aus."""
    return asyncio.run(coro)


@pytest.fixture
def manager(waterbed_config):
    hass = MagicMock()
    entry = MagicMock()
    return SafetyManager(hass, entry, waterbed_config)


def _check(manager, zone, current, target, heater_on):
    return _run(manager.async_check_zone_safety(zone, current, target, heater_on))


# ── Übertemperatur ──────────────────────────────────────────────────────────


@patch("custom_components.rejuvenation_bed.safety_manager.local_now")
def test_overheat_warning_does_not_block(mock_now, manager):
    mock_now.return_value = BASE
    is_safe, status, notif = _check(manager, 0, OVERHEAT_WARNING_TEMP + 0.5, 28.0, True)
    assert is_safe is True
    assert "OVERHEAT_WARNING" in status
    assert notif is None


@patch("custom_components.rejuvenation_bed.safety_manager.local_now")
def test_overheat_critical_blocks_heating(mock_now, manager):
    mock_now.return_value = BASE
    is_safe, status, notif = _check(manager, 0, OVERHEAT_CRITICAL_TEMP + 0.2, 28.0, True)
    assert is_safe is False
    assert "OVERHEAT_CRITICAL" in status
    assert notif is not None
    # Kritisch ist noch KEIN Latch
    assert manager.is_emergency_shutdown(0) is False


@patch("custom_components.rejuvenation_bed.safety_manager.local_now")
def test_overheat_emergency_latches(mock_now, manager):
    mock_now.return_value = BASE
    is_safe, status, notif = _check(manager, 0, OVERHEAT_EMERGENCY_TEMP + 0.1, 28.0, True)
    assert is_safe is False
    assert status == "EMERGENCY_SHUTDOWN"
    assert notif is not None
    assert manager.is_emergency_shutdown(0) is True
    assert manager.get_emergency_reason(0) is not None

    # Latch bleibt unabhängig von der Zone-Anzahl bestehen
    manager.clear_emergency(0)
    assert manager.is_emergency_shutdown(0) is False
    assert manager.get_emergency_reason(0) is None


@patch("custom_components.rejuvenation_bed.safety_manager.local_now")
def test_normal_temperature_is_ok(mock_now, manager):
    mock_now.return_value = BASE
    is_safe, status, notif = _check(manager, 0, 27.0, 28.0, False)
    assert is_safe is True
    assert status == "OK"
    assert notif is None


# ── Klebe-Relais ────────────────────────────────────────────────────────────


@patch("custom_components.rejuvenation_bed.safety_manager.local_now")
def test_stuck_relay_detected(mock_now, manager):
    # 1. Zyklus: Heizung AUS befohlen, Temp 27.0 → Referenz merken
    mock_now.return_value = BASE
    is_safe, status, notif = _check(manager, 0, 27.0, 28.0, False)
    assert is_safe is True
    assert status == "OK"

    # 2. Zyklus: 11 Min später, Temp gestiegen obwohl AUS befohlen
    mock_now.return_value = BASE + timedelta(minutes=11)
    is_safe, status, notif = _check(manager, 0, 27.6, 28.0, False)
    assert is_safe is True  # Warnung, aber kein harter Stopp
    assert "STUCK_RELAY_SUSPECTED" in status
    assert notif is not None


@patch("custom_components.rejuvenation_bed.safety_manager.local_now")
def test_stuck_relay_cleared_when_heating_commanded(mock_now, manager):
    mock_now.return_value = BASE
    _check(manager, 0, 27.0, 28.0, False)  # AUS → Referenz gesetzt
    # Heizung wird wieder AN befohlen → Tracking zurückgesetzt
    mock_now.return_value = BASE + timedelta(minutes=5)
    _check(manager, 0, 27.2, 28.0, True)
    assert 0 not in manager._off_command_time


# ── Sensor-Defekt ───────────────────────────────────────────────────────────


@patch("custom_components.rejuvenation_bed.safety_manager.local_now")
def test_sensor_defect_detected_after_long_heating(mock_now, manager):
    # 1. Zyklus: Heizung AN bei 26.0 → Startzeit/-temp merken
    mock_now.return_value = BASE
    _check(manager, 0, 26.0, 29.0, True)

    # 2. Zyklus: 3.1h später nur +0.1°C trotz Dauerheizen
    mock_now.return_value = BASE + timedelta(hours=3, minutes=6)
    is_safe, status, notif = _check(manager, 0, 26.1, 29.0, True)
    assert is_safe is False
    assert status == "SENSOR_DEFECT_SUSPECTED"
    assert notif is not None


@patch("custom_components.rejuvenation_bed.safety_manager.local_now")
def test_sensor_ok_when_temperature_rises(mock_now, manager):
    mock_now.return_value = BASE
    _check(manager, 0, 26.0, 29.0, True)
    mock_now.return_value = BASE + timedelta(hours=3, minutes=6)
    is_safe, status, notif = _check(manager, 0, 28.0, 29.0, True)  # +2°C ist gesund
    assert is_safe is True
    assert status == "OK"


# ── Spam-Throttle ───────────────────────────────────────────────────────────


@patch("custom_components.rejuvenation_bed.safety_manager.local_now")
def test_warning_throttled_within_hour(mock_now, manager):
    # Erster Stuck-Relay-Trigger → Notification
    mock_now.return_value = BASE
    _check(manager, 0, 27.0, 28.0, False)
    mock_now.return_value = BASE + timedelta(minutes=11)
    _, _, notif1 = _check(manager, 0, 27.6, 28.0, False)
    assert notif1 is not None

    # Weiterer Trigger 5 Min später → innerhalb der Stunde unterdrückt
    mock_now.return_value = BASE + timedelta(minutes=16)
    _, _, notif2 = _check(manager, 0, 28.0, 28.0, False)
    assert notif2 is None


# ── Degraded-Duty-Cycle ─────────────────────────────────────────────────────


@patch("custom_components.rejuvenation_bed.safety_manager.local_now")
def test_degraded_duty_cycle(mock_now, manager):
    # Anfang des Zyklus → heizt (innerhalb der 30%-AN-Phase)
    mock_now.return_value = BASE
    assert manager.should_heat_in_degraded_mode(0) is True

    # 5 Min in den 10-Min-Zyklus → außerhalb der 3-Min-AN-Phase → Pause
    mock_now.return_value = BASE + timedelta(minutes=5)
    assert manager.should_heat_in_degraded_mode(0) is False
