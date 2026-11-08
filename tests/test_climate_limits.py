"""K4: Das Klima-Slider-Maximum folgt dem Comfort-Limit der Bett-Konfiguration.

Der Wasserbett-Slider bot bislang ABSOLUTE_MAX_TEMP (38°C) an, obwohl das
Bett laut Konfiguration bei 30°C liegt und die Software erst ab 34°C
(OVERHEAT_CRITICAL) eingreift. Die Heizmatten-Anzeige bleibt unverändert:
deren Config-Maximum (40) liegt über der Hardware-Grenze, es gilt
weiterhin ABSOLUTE_MAX_TEMP.
"""

import sys
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock


# Echte Basisklassen statt Mock, bevor climate.py importiert wird (Muster aus
# test_nightstand_config.py: zwei MagicMocks als Basen werfen einen
# Metaclass-Konflikt).
class _FakeCoordinatorEntity:
    def __init__(self, coordinator, *args, **kwargs):
        self.coordinator = coordinator


sys.modules["homeassistant"].helpers.update_coordinator.CoordinatorEntity = _FakeCoordinatorEntity
sys.modules["homeassistant.helpers.update_coordinator"].CoordinatorEntity = _FakeCoordinatorEntity
sys.modules["homeassistant"].components.climate.ClimateEntity = type("ClimateEntity", (), {})
sys.modules["homeassistant.components.climate"].ClimateEntity = sys.modules[
    "homeassistant"
].components.climate.ClimateEntity

from custom_components.rejuvenation_bed.climate import RejuvenationBedClimate  # noqa: E402
from custom_components.rejuvenation_bed.const import (  # noqa: E402
    ABSOLUTE_MAX_TEMP,
    HEATING_PAD_CONFIG,
    WATERBED_CONFIG,
    local_now,
)


def _climate(bed_config):
    coordinator = MagicMock()
    coordinator.bed_config = bed_config.copy()
    coordinator.config_entry = MagicMock(data={"zones": [{}]})
    return RejuvenationBedClimate(coordinator, 0, "")


def test_waterbed_slider_max_is_configured_comfort_limit():
    assert _climate(WATERBED_CONFIG)._attr_max_temp == WATERBED_CONFIG["max_temp"]
    assert _climate(WATERBED_CONFIG)._attr_max_temp == 30.0


def test_pad_slider_max_stays_at_hardware_limit():
    # Config-Maximum 40 liegt über ABSOLUTE_MAX_TEMP — Slider bleibt bei 38
    assert _climate(HEATING_PAD_CONFIG)._attr_max_temp == ABSOLUTE_MAX_TEMP


class TestAwayPresetActivatesVacation:
    """K11: Der AWAY-Preset aktiviert den Urlaub (Frostschutz), wie der
    Vacation-Switch; PRESET_NONE beendet ihn wieder."""

    @staticmethod
    def _run(coro):
        import asyncio

        return asyncio.run(coro)

    def test_away_preset_turns_vacation_on(self):
        import asyncio

        coordinator = MagicMock()
        coordinator.bed_config = WATERBED_CONFIG.copy()
        coordinator.config_entry = MagicMock(data={"zones": [{}]})
        coordinator.async_request_refresh = AsyncMock()
        entity = RejuvenationBedClimate(coordinator, 0, "")

        preset_away = sys.modules["homeassistant.components.climate"].PRESET_AWAY
        asyncio.run(entity.async_set_preset_mode(preset_away))

        assert coordinator.vacation_mode_enabled is True

    def test_none_preset_turns_vacation_off(self):
        """Fund (pc-au): PRESET_NONE räumt auch den Temperatur-Override
        ab, wie der Vacation-Switch, cancel_special_mode und der
        Auto-Ablauf — sonst schaltet der nächste Urlaub wieder auf die
        alte Override-Temperatur."""
        import asyncio

        coordinator = MagicMock()
        coordinator.bed_config = WATERBED_CONFIG.copy()
        coordinator.config_entry = MagicMock(data={"zones": [{}]})
        coordinator.async_request_refresh = AsyncMock()
        coordinator.vacation_mode_enabled = True
        coordinator.vacation_temp_override = 30.0
        entity = RejuvenationBedClimate(coordinator, 0, "")

        preset_none = sys.modules["homeassistant.components.climate"].PRESET_NONE
        asyncio.run(entity.async_set_preset_mode(preset_none))

        assert coordinator.vacation_mode_enabled is False
        assert coordinator.vacation_temp_override is None

    def test_away_renews_expired_vacation_until(self):
        """Fund (pc-ap): AWAY erneuert ein alt-abgelaufenes vacation_until.

        Wer vorher per Schalter oder Dienst im Urlaub war, hat ein
        abgelaufenes Datum stehen (der Auto-Ablauf im Coordinator löscht
        nur die Flagge, nie das Datum). Ohne Erneuerung schaltet der
        nächste Update-Lauf den soeben per Preset aktivierten Urlaub
        sofort wieder ab — AWAY setzt das Datum deshalb wie der
        Vacation-Switch (14 Tage).
        """
        import asyncio

        coordinator = MagicMock()
        coordinator.bed_config = WATERBED_CONFIG.copy()
        coordinator.config_entry = MagicMock(data={"zones": [{}]})
        coordinator.async_request_refresh = AsyncMock()
        coordinator.vacation_mode_enabled = False
        coordinator.vacation_until = local_now() - timedelta(days=1)
        entity = RejuvenationBedClimate(coordinator, 0, "")

        preset_away = sys.modules["homeassistant.components.climate"].PRESET_AWAY
        asyncio.run(entity.async_set_preset_mode(preset_away))

        assert coordinator.vacation_mode_enabled is True
        assert coordinator.vacation_until > local_now()

    def test_none_preset_clears_vacation_until(self):
        """Fund (pc-ap): PRESET_NONE räumt auch das Datum ab, wie der
        Vacation-Switch beim Abschalten — es bleibt kein altes
        Ablaufdatum liegen."""
        import asyncio

        coordinator = MagicMock()
        coordinator.bed_config = WATERBED_CONFIG.copy()
        coordinator.config_entry = MagicMock(data={"zones": [{}]})
        coordinator.async_request_refresh = AsyncMock()
        coordinator.vacation_mode_enabled = True
        coordinator.vacation_until = local_now() + timedelta(days=14)
        entity = RejuvenationBedClimate(coordinator, 0, "")

        preset_none = sys.modules["homeassistant.components.climate"].PRESET_NONE
        asyncio.run(entity.async_set_preset_mode(preset_none))

        assert coordinator.vacation_mode_enabled is False
        assert coordinator.vacation_until is None
