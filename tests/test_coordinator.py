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
