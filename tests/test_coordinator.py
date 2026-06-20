"""Tests für isolierte Coordinator-Logik (ohne Voll-Konstruktion).

Wir rufen einzelne Methoden als ungebundene Funktionen mit einem
schlanken Fake-`self` auf. Das deckt die neuen Fixes ab:
- #3 Urlaubs-Temp-Clamp (Wasserbett nie unter min_temp)
- #4/#5 TTL der manuellen Zieltemperatur
"""

import sys
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Die echte Klasse erbt von DataUpdateCoordinator, das in conftest gemockt ist.
# Ein Mock als Basisklasse macht die ganze Klasse zum Mock → echte Methoden
# wären unerreichbar. Wir setzen daher eine echte Basisklasse, bevor das
# Coordinator-Modul (frisch) importiert wird.
_uc = sys.modules["homeassistant.helpers.update_coordinator"]


class _RealBase:
    def __init__(self, *args, **kwargs):
        pass


_uc.DataUpdateCoordinator = _RealBase
_uc.UpdateFailed = type("UpdateFailed", (Exception,), {})
sys.modules.pop("custom_components.rejuvenation_bed.coordinator", None)

from custom_components.rejuvenation_bed.coordinator import (  # noqa: E402
    RejuvenationBedCoordinator,
)
from custom_components.rejuvenation_bed.const import (  # noqa: E402
    BED_TYPE_WATERBED,
    BED_TYPE_HEATING_PAD,
    WATERBED_CONFIG,
    HEATING_PAD_CONFIG,
    local_now,
)

BASE = datetime(2026, 6, 20, 22, 0, 0)


# ── #3 Urlaubs-Temp-Clamp ────────────────────────────────────────────────────


def _vacation_self(bed_type, override, bed_config):
    return SimpleNamespace(
        vacation_mode_enabled=True,
        vacation_until=None,
        vacation_temp_override=override,
        bed_type=bed_type,
        bed_config=bed_config,
        config_entry=MagicMock(options={}),
    )


@patch("custom_components.rejuvenation_bed.coordinator.local_now")
def test_vacation_temp_clamped_to_min_for_waterbed(mock_now):
    mock_now.return_value = BASE
    fake = _vacation_self(BED_TYPE_WATERBED, 20.0, WATERBED_CONFIG.copy())
    temp, mode, reason = RejuvenationBedCoordinator._apply_mode_adjustments(fake, 0, 27.0)
    assert mode == "vacation"
    assert temp >= WATERBED_CONFIG["min_temp"]
    assert temp == 24.0  # 20 wird auf 24 angehoben


@patch("custom_components.rejuvenation_bed.coordinator.local_now")
def test_vacation_temp_above_min_unchanged(mock_now):
    mock_now.return_value = BASE
    fake = _vacation_self(BED_TYPE_WATERBED, 26.0, WATERBED_CONFIG.copy())
    temp, mode, _ = RejuvenationBedCoordinator._apply_mode_adjustments(fake, 0, 27.0)
    assert mode == "vacation"
    assert temp == 26.0


@patch("custom_components.rejuvenation_bed.coordinator.local_now")
def test_vacation_heating_pad_turns_off(mock_now):
    mock_now.return_value = BASE
    fake = _vacation_self(BED_TYPE_HEATING_PAD, 20.0, HEATING_PAD_CONFIG.copy())
    temp, mode, _ = RejuvenationBedCoordinator._apply_mode_adjustments(fake, 0, 27.0)
    assert mode == "vacation"
    assert temp == 0.0  # Heizmatte darf komplett aus


# ── #4/#5 TTL der manuellen Zieltemperatur ───────────────────────────────────


@patch("custom_components.rejuvenation_bed.coordinator.local_now")
def test_manual_target_active_within_ttl(mock_now):
    mock_now.return_value = BASE
    fake = SimpleNamespace(
        manual_target_temp={0: 29.0},
        manual_target_until={0: BASE + timedelta(hours=8)},
    )
    result = RejuvenationBedCoordinator.get_active_manual_target(fake, 0)
    assert result == 29.0


@patch("custom_components.rejuvenation_bed.coordinator.local_now")
def test_manual_target_expires_after_ttl(mock_now):
    fake = SimpleNamespace(
        manual_target_temp={0: 29.0},
        manual_target_until={0: BASE + timedelta(hours=8)},
    )
    # Nach Ablauf der TTL
    mock_now.return_value = BASE + timedelta(hours=9)
    result = RejuvenationBedCoordinator.get_active_manual_target(fake, 0)
    assert result is None
    # Wert wurde aufgeräumt
    assert 0 not in fake.manual_target_temp
    assert 0 not in fake.manual_target_until


@patch("custom_components.rejuvenation_bed.coordinator.local_now")
def test_manual_target_none_when_unset(mock_now):
    mock_now.return_value = BASE
    fake = SimpleNamespace(manual_target_temp={}, manual_target_until={})
    assert RejuvenationBedCoordinator.get_active_manual_target(fake, 0) is None


def test_clear_manual_target():
    fake = SimpleNamespace(
        manual_target_temp={0: 29.0, 1: 30.0},
        manual_target_until={0: BASE, 1: BASE},
    )
    RejuvenationBedCoordinator.clear_manual_target(fake, 0)
    assert 0 not in fake.manual_target_temp
    assert 0 not in fake.manual_target_until
    # Andere Zone bleibt unberührt
    assert fake.manual_target_temp[1] == 30.0


# ── #9/O6: Integrations-Smoke-Test des Haupt-Loops ──────────────────────────
# Konstruiert einen echten Coordinator (Basisklasse via _RealBase ersetzt) und
# fährt EINEN _async_update_data-Zyklus. Blatt-Kollaborateure werden gestubbt,
# damit die ORCHESTRIERUNG (Sensor-Lesen, Mode, Rampe, Hysterese, Safety,
# Schaltung, Decision-Aufbau) als echte Coordinator-Logik durchläuft.
# Dient als Sicherheitsnetz für die _process_zone-Extraktion (#9).

import asyncio  # noqa: E402
from unittest.mock import AsyncMock  # noqa: E402


def _build_coordinator(current_temp="24.0", heater_state="off"):
    hass = MagicMock()
    states = {
        "sensor.temp": SimpleNamespace(state=str(current_temp)),
        "switch.heater": SimpleNamespace(state=heater_state),
    }
    hass.states.get = lambda eid: states.get(eid)
    hass.services.async_call = AsyncMock()

    entry = SimpleNamespace(
        entry_id="test_entry",
        data={
            "global": {"bed_type": "wasserbett"},
            "zones": [{"heater": "switch.heater", "temp_sensor": "sensor.temp"}],
            "energy": {},
        },
        options={},
    )

    coord = RejuvenationBedCoordinator(hass, entry)
    coord._hardware_synced = True  # Hardware-Sync (mit async_load) überspringen

    # Blatt-Kollaborateure stubben (nicht Teil der Loop-Orchestrierung)
    coord.temperature_calculator.update_trend_data = MagicMock()
    coord.temperature_calculator.async_calculate_target = AsyncMock(return_value=28.0)
    coord.temperature_calculator.async_get_decision_reason = AsyncMock(return_value="reason")
    coord.presence_detector.detect_presence = MagicMock(return_value=(False, 0.0, "test"))
    coord.presence_detector.is_potential_leak = MagicMock(return_value=False)
    coord.ramp_controller.calculate_ramped_setpoint = MagicMock(return_value=(28.0, SimpleNamespace(ramp_active=False)))
    coord.anti_short_cycle_manager.can_switch = MagicMock(return_value=(True, "test"))
    coord.bed_intelligence.calibration = SimpleNamespace(is_calibrated=False)
    coord.bed_intelligence.update = MagicMock()
    coord.bed_intelligence.get_sweat_status = MagicMock(
        return_value=SimpleNamespace(is_sweating=False, is_moist=False, humidity_level=None, cause=None)
    )
    coord.bed_intelligence.get_isolation_status = MagicMock(
        return_value=SimpleNamespace(energy_waste_warning=False, level=None, delta_water_air=None, uncovered_minutes=0)
    )
    coord._async_update_sleep_tracking = AsyncMock()
    coord.diagnostics_manager.update_energy_usage = MagicMock()
    return coord, hass


def test_update_cycle_produces_zone_decision_and_switches_heater():
    coord, hass = _build_coordinator(current_temp="24.0", heater_state="off")

    result = asyncio.run(coord._async_update_data())

    # Loop lief sauber durch und lieferte eine wohlgeformte Zonen-Entscheidung
    assert "Zone 1" in result["zones"]
    zone = result["zones"]["Zone 1"]
    assert zone.get("status") != "ERROR", f"Zone lief in Fail-Safe: {zone}"
    assert "target" in zone and "active" in zone
    # 24°C ist deutlich unter Ziel (28°C) → Heizung muss eingeschaltet werden
    assert zone["active"] is True
    hass.services.async_call.assert_awaited()
    args = hass.services.async_call.await_args
    assert args.args[1] == "turn_on"


def test_update_cycle_emergency_latch_forces_off():
    coord, hass = _build_coordinator(current_temp="24.0", heater_state="on")
    # Not-Aus-Latch für Zone 0 setzen → Heizung muss AUS bleiben
    coord.safety_manager._emergency_shutdown[0] = True
    coord.safety_manager._emergency_reason[0] = "Test-Notfall"

    result = asyncio.run(coord._async_update_data())

    zone = result["zones"]["Zone 1"]
    assert zone["active"] is False
    assert "NOT-AUS" in zone["reason"]


def test_update_cycle_sensor_failure_failsafe_on():
    # Temp-Sensor unavailable + Startup-Grace abgelaufen → Wasserbett heizt blind
    coord, hass = _build_coordinator(current_temp="unavailable", heater_state="off")
    coord._startup_time = local_now() - timedelta(hours=1)

    result = asyncio.run(coord._async_update_data())

    zone = result["zones"]["Zone 1"]
    assert zone["status"] == "FAIL_SAFE"
    assert zone["active"] is True
    args = hass.services.async_call.await_args
    assert args.args[1] == "turn_on"


def test_update_cycle_startup_wait():
    # Temp-Sensor unavailable, aber noch in der Startup-Grace → warten, nicht schalten
    coord, hass = _build_coordinator(current_temp="unavailable", heater_state="off")
    coord._startup_time = local_now()  # gerade gestartet

    result = asyncio.run(coord._async_update_data())

    zone = result["zones"]["Zone 1"]
    assert zone["status"] == "STARTUP_WAIT"
    hass.services.async_call.assert_not_awaited()


def test_update_cycle_hvac_off_forces_off():
    from homeassistant.components.climate.const import HVACMode

    coord, hass = _build_coordinator(current_temp="24.0", heater_state="on")
    coord.manual_hvac_mode[0] = HVACMode.OFF

    result = asyncio.run(coord._async_update_data())

    zone = result["zones"]["Zone 1"]
    assert zone["active"] is False
    args = hass.services.async_call.await_args
    assert args.args[1] == "turn_off"


@patch("custom_components.rejuvenation_bed.coordinator.local_now")
def test_sensor_warning_throttled(mock_now):
    """O2: Sensor-Warnung höchstens 1×/Stunde je Entity."""
    fake = SimpleNamespace(_sensor_warn_at={})

    mock_now.return_value = BASE
    RejuvenationBedCoordinator._warn_sensor_throttled(fake, "sensor.x", "weg")
    first = fake._sensor_warn_at["sensor.x"]
    assert first == BASE

    # Innerhalb der Stunde → kein erneutes WARNING (Zeitstempel bleibt)
    mock_now.return_value = BASE + timedelta(minutes=30)
    RejuvenationBedCoordinator._warn_sensor_throttled(fake, "sensor.x", "weg")
    assert fake._sensor_warn_at["sensor.x"] == first

    # Nach über einer Stunde → erneut WARNING (Zeitstempel aktualisiert)
    later = BASE + timedelta(hours=2)
    mock_now.return_value = later
    RejuvenationBedCoordinator._warn_sensor_throttled(fake, "sensor.x", "weg")
    assert fake._sensor_warn_at["sensor.x"] == later
