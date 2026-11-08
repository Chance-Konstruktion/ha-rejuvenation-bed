"""M5: Die Heater-Auswahl darf keine number-Entities anbieten.

Der Coordinator schaltet die Heizung per hass.services.async_call(domain,
turn_on/turn_off) — genau die beiden Dienste besitzt eine number-Entity
nicht. Wer dort eine number wählte, bekam eine "Heizung", die nie schaltet.

Die Flows werden hier nicht gegen einen echten Kern gefahren (das kann nur
tests_ha), sondern die Form-Schritte mit frischen Selector-Mocks ausgeführt;
geprüft wird, welche Domains der EntitySelector für "heater" bekommt.
"""

import asyncio
import sys
from unittest.mock import MagicMock

import pytest

# Echte Basisklassen statt Mock, bevor die Flows importiert werden (Muster aus
# test_options_flow.py: Subclassing über einen MagicMock würde die echten
# async_step_*-Methoden verschlucken).
sys.modules["homeassistant"].config_entries.ConfigFlow = type("ConfigFlow", (), {"__init_subclass__": classmethod(
    lambda cls, **kwargs: None)})
sys.modules["homeassistant.config_entries"].ConfigFlow = sys.modules["homeassistant"].config_entries.ConfigFlow
sys.modules["homeassistant"].config_entries.OptionsFlow = type("OptionsFlow", (), {})
sys.modules["homeassistant.config_entries"].OptionsFlow = sys.modules["homeassistant"].config_entries.OptionsFlow

from custom_components.rejuvenation_bed import config_flow as config_flow_module  # noqa: E402
from custom_components.rejuvenation_bed import options_flow as options_flow_module  # noqa: E402


def _heater_domains_from(calls):
    """Die Domain-Liste aller EntitySelectorConfig-Aufrufe, deren domain eine Liste ist."""
    domains = []
    for call in calls:
        domain = call.kwargs.get("domain")
        if isinstance(domain, list):
            domains.append(domain)
    return domains


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture
def fresh_selector(monkeypatch):
    """Frische Selector-Mocks, damit die Aufruf-Argumente des Form-Schritts lesbar sind."""
    fresh = MagicMock()
    monkeypatch.setattr(config_flow_module.selector, "EntitySelector", fresh.EntitySelector, raising=True)
    monkeypatch.setattr(config_flow_module.selector, "EntitySelectorConfig", fresh.EntitySelectorConfig, raising=True)
    monkeypatch.setattr(options_flow_module.selector, "EntitySelector", fresh.EntitySelector, raising=True)
    monkeypatch.setattr(options_flow_module.selector, "EntitySelectorConfig", fresh.EntitySelectorConfig, raising=True)
    return fresh


class TestHeaterSelectorDomains:
    def test_config_flow_offers_no_number(self, fresh_selector):
        flow = config_flow_module.RejuvenationBedConfigFlow()
        flow.hass = MagicMock()
        flow.async_show_form = lambda **k: {"type": "form", "step_id": k["step_id"]}
        flow.async_show_menu = lambda **k: {"type": "menu", "step_id": k["step_id"]}

        _run(flow.async_step_zone_config(None))

        domains = _heater_domains_from(fresh_selector.EntitySelectorConfig.call_args_list)
        assert domains, "Der Zonen-Schritt hat keinen EntitySelector mit Domain-Liste gebaut"
        for domain in domains:
            assert "number" not in domain

    def test_options_flow_offers_no_number(self, fresh_selector):
        entry = MagicMock()
        entry.options = {}
        entry.data = {"global": {}, "zones": [{"heater": "switch.a"}]}
        flow = options_flow_module.RejuvenationBedOptionsFlow(entry)
        flow.hass = MagicMock()
        flow.async_show_form = lambda **k: {"type": "form", "step_id": k["step_id"]}
        flow.async_show_menu = lambda **k: {"type": "menu", "step_id": k["step_id"]}
        flow.async_abort = lambda **k: {"type": "abort", "reason": k.get("reason")}
        flow._editing_zone_index = 0

        _run(flow.async_step_edit_zone_sensors(None))

        domains = _heater_domains_from(fresh_selector.EntitySelectorConfig.call_args_list)
        assert domains, "Der Zonen-Schritt hat keinen EntitySelector mit Domain-Liste gebaut"
        for domain in domains:
            assert "number" not in domain
            assert "switch" in domain
