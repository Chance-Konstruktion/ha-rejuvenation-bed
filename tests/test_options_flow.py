"""Tests für den Options-Flow — insbesondere die Zurück-Navigation.

Die Test-Harness (conftest.py) ersetzt ``homeassistant`` komplett durch
MagicMocks. Dadurch wäre die ``OptionsFlow``-Basisklasse ein Mock und ein
Subclassing würde die echten ``async_step_*``-Methoden verschlucken. Deshalb
ersetzen wir die Basisklasse VOR dem Import durch eine echte, leere Klasse —
dann behält ``RejuvenationBedOptionsFlow`` seinen echten Code und wir können
die Navigation direkt durchspielen.

Abgesichert wird das Verhalten, das den ursprünglichen Bug behoben hat:
Jede Eingabemaske kehrt nach dem Speichern zu ihrem Elternmenü zurück
(statt den Flow mit ``async_create_entry`` zu beenden), Änderungen landen in
einer Arbeitskopie, ``entry.data`` bleibt bis zum finalen Speichern
unangetastet, und erst »Speichern & Beenden« committet.
"""

import sys
import asyncio
from unittest.mock import MagicMock

import pytest


# ── Echte Basisklasse statt Mock, bevor options_flow importiert wird ──
class _FakeOptionsFlow:
    pass


# Beim Subclassing greift Python auf das Attribut des homeassistant-Mocks zu
# (nicht auf sys.modules["homeassistant.config_entries"]), daher beide setzen.
sys.modules["homeassistant"].config_entries.OptionsFlow = _FakeOptionsFlow
sys.modules["homeassistant.config_entries"].OptionsFlow = _FakeOptionsFlow

from custom_components.rejuvenation_bed.options_flow import (  # noqa: E402
    RejuvenationBedOptionsFlow,
)


def _make_flow(zones):
    """Erzeugt einen Flow mit gefälschten async_show_*/create_entry-Helfern."""
    entry = MagicMock()
    entry.options = {}
    entry.data = {"global": {}, "zones": [dict(z) for z in zones]}

    flow = RejuvenationBedOptionsFlow(entry)
    flow.hass = MagicMock()
    flow.async_show_menu = lambda **k: {"type": "menu", "step_id": k["step_id"]}
    flow.async_show_form = lambda **k: {"type": "form", "step_id": k["step_id"]}
    flow.async_create_entry = lambda **k: {"type": "create", "data": k.get("data")}
    return flow, entry


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class TestGlobalFormsReturnToMenu:
    """Globale Masken kehren nach dem Speichern ins Untermenü zurück."""

    def test_global_times_returns_to_submenu(self):
        flow, _ = _make_flow([{"heater": "switch.a"}])
        result = _run(flow.async_step_global_times({"summer_threshold": 26}))
        assert result["type"] == "menu"
        assert result["step_id"] == "global_settings"
        # Wert in der Arbeitskopie, nicht im Entry committet.
        assert flow._options["summer_threshold"] == 26

    def test_global_sensors_drops_empty_optionals(self):
        flow, _ = _make_flow([{"heater": "switch.a"}])
        flow._options["co2_sensor"] = "sensor.old"
        result = _run(
            flow.async_step_global_sensors(
                {"electricity_price": 28.0, "co2_sensor": "", "price_sensor": "sensor.tibber"}
            )
        )
        assert result["step_id"] == "global_settings"
        assert flow._options["electricity_price"] == 28.0
        assert flow._options["price_sensor"] == "sensor.tibber"
        # Leerer optionaler Sensor wird entfernt.
        assert "co2_sensor" not in flow._options

    def test_global_solar_returns_to_submenu(self):
        flow, _ = _make_flow([{"heater": "switch.a"}])
        result = _run(flow.async_step_global_solar({"solar_boost_threshold": 600}))
        assert result["step_id"] == "global_settings"
        assert flow._options["solar_boost_threshold"] == 600


class TestModeSettingsReturnToMenu:
    def test_mode_settings_returns_to_init(self):
        flow, _ = _make_flow([{"heater": "switch.a"}])
        result = _run(flow.async_step_mode_settings({"sick_mode_temp": 31.0}))
        assert result["type"] == "menu"
        assert result["step_id"] == "init"
        assert flow._options["sick_mode_temp"] == 31.0


class TestZoneSettingsNavigation:
    def test_dual_zone_returns_to_selection_menu(self):
        flow, _ = _make_flow([{"heater": "switch.a"}, {"heater": "switch.b"}])
        _run(flow.async_step_zone_settings_left())
        result = _run(flow.async_step_edit_zone_settings({"warm_from": "21:00", "chronotype": "eule"}))
        assert result["type"] == "menu"
        assert result["step_id"] == "zone_settings"
        assert flow._options["zone_0_warm_from"] == "21:00"
        assert flow._options["zone_0_chronotype"] == "eule"

    def test_single_zone_returns_to_init(self):
        flow, _ = _make_flow([{"heater": "switch.a"}])
        _run(flow.async_step_zone_settings_left())
        result = _run(flow.async_step_edit_zone_settings({"warm_from": "22:30"}))
        assert result["step_id"] == "init"
        assert flow._options["zone_0_warm_from"] == "22:30"

    def test_nightstand_entities_land_in_zone_options(self):
        """Wecker-Schalter und Lampe für die Nachttisch-Karte, pro Bettseite."""
        flow, _ = _make_flow([{"heater": "switch.a"}, {"heater": "switch.b"}])
        _run(flow.async_step_zone_settings_right())
        _run(
            flow.async_step_edit_zone_settings(
                {
                    "warm_from": "22:00",
                    "alarm_entity": "input_datetime.wecker_rechts",
                    "alarm_switch_entity": "input_boolean.wecker_rechts_aktiv",
                    "light_entity": "light.schlafzimmer",
                }
            )
        )
        assert flow._options["zone_1_alarm_switch_entity"] == "input_boolean.wecker_rechts_aktiv"
        assert flow._options["zone_1_light_entity"] == "light.schlafzimmer"

    def test_nightstand_entities_can_be_cleared(self):
        flow, _ = _make_flow([{"heater": "switch.a"}])
        flow._options["zone_0_light_entity"] = "light.alt"
        _run(flow.async_step_zone_settings_left())
        _run(flow.async_step_edit_zone_settings({"warm_from": "22:00", "light_entity": ""}))
        assert "zone_0_light_entity" not in flow._options


class TestZoneSensorsWorkingCopy:
    def test_zone_sensors_saved_to_working_copy_not_entry(self):
        flow, entry = _make_flow([{"heater": "switch.a"}, {"heater": "switch.b"}])
        _run(flow.async_step_zone_sensors_right())
        result = _run(flow.async_step_edit_zone_sensors({"heater": "switch.new"}))
        assert result["type"] == "menu"
        assert result["step_id"] == "zone_sensors"
        # Arbeitskopie geändert ...
        assert flow._zones[1]["heater"] == "switch.new"
        # ... aber entry.data bleibt bis zum Speichern unangetastet.
        assert entry.data["zones"][1]["heater"] == "switch.b"
        assert not flow.hass.config_entries.async_update_entry.called


class TestSaveCommits:
    def test_save_commits_options_and_changed_zones(self):
        flow, entry = _make_flow([{"heater": "switch.a"}])
        flow._options["summer_threshold"] = 27
        flow._zones[0]["heater"] = "switch.changed"

        result = _run(flow.async_step_save())

        assert result["type"] == "create"
        assert result["data"]["summer_threshold"] == 27
        # Geänderte Zonen werden in entry.data geschrieben.
        assert flow.hass.config_entries.async_update_entry.called

    def test_save_skips_data_write_when_zones_unchanged(self):
        flow, entry = _make_flow([{"heater": "switch.a"}])
        flow._options["summer_threshold"] = 27  # nur Options geändert

        result = _run(flow.async_step_save())

        assert result["type"] == "create"
        # Keine Zonen-Änderung → kein überflüssiger data-Write (kein Extra-Reload).
        assert not flow.hass.config_entries.async_update_entry.called


class TestNoCreateEntryDuringNavigation:
    """Während der Navigation darf keine Maske den Flow beenden."""

    def test_forms_never_create_entry_before_save(self):
        flow, _ = _make_flow([{"heater": "switch.a"}, {"heater": "switch.b"}])
        created = []
        flow.async_create_entry = lambda **k: created.append(k) or {"type": "create"}

        _run(flow.async_step_global_times({"summer_threshold": 26}))
        _run(flow.async_step_mode_settings({"sick_mode_temp": 31.0}))
        _run(flow.async_step_zone_settings_left())
        _run(flow.async_step_edit_zone_settings({"warm_from": "21:00"}))
        _run(flow.async_step_zone_sensors_right())
        _run(flow.async_step_edit_zone_sensors({"heater": "switch.x"}))

        assert created == []  # erst »Speichern & Beenden« beendet den Flow


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
