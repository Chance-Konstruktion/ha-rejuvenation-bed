"""K5/#11: Der services.yaml-Ausdruck hält sich an das Service-Schema.

K5: services.yaml bot für set_vacation_mode.temperature min=0 an, während das
Schema in __init__.py nur vol.Range(min=15, max=25) akzeptiert. Wer der
Doku folgte und 0-14 eintrug, erhielt einen Schema-Validierungsfehler.

#11: Die Dienste deklarierten ein target (Climate-Entity), das die Handler
nie gelesen haben -- der Dialog versprach eine Zielwahl, die es nicht gibt
(in HA 2026.2 scheitert ein Ziel-Aufruf sogar an der Schema-Validierung,
weil entity_id als Extra-Key gegen PREVENT_EXTRA läuft). Das Zielfeld ist
daher weg; die Dienste wirken auf das ganze Bett, Zonen-Steuerung läuft
über die Climate-Entities (Preset/Temperatur).
"""

import yaml

SERVICE_SCHEMA_MIN = 15.0  # vol.Range(min=15, max=25) in __init__.py

# Die Dienste, die früher ein (ignoriertes) target deklarierten. reset_energy_budget
# und clear_emergency hatten nie eines -- clear_emergency wählt per zone-Feld.
SERVICES_MIT_ZIELEINLADUNG = (
    "set_boost",
    "set_sick_mode",
    "set_vacation_mode",
    "cancel_special_mode",
    "preheat_bed",
)


def _vacation_temperature_selector():
    with open("custom_components/rejuvenation_bed/services.yaml", encoding="utf-8") as f:
        services = yaml.safe_load(f)
    return services["set_vacation_mode"]["fields"]["temperature"]


def _services():
    with open("custom_components/rejuvenation_bed/services.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_vacation_selector_min_matches_schema():
    selector = _vacation_temperature_selector()["selector"]["number"]
    assert selector["min"] == SERVICE_SCHEMA_MIN


def test_vacation_selector_max_matches_schema():
    selector = _vacation_temperature_selector()["selector"]["number"]
    assert selector["max"] == 25


def test_vacation_description_no_longer_promises_zero():
    description = _vacation_temperature_selector()["description"]
    assert "0°C" not in description


def test_dienste_deklarieren_kein_target_mehr():
    """#11: Kein Dienst verspricht mehr eine Zielwahl, die keiner liest."""
    services = _services()
    for name in SERVICES_MIT_ZIELEINLADUNG:
        assert "target" not in services[name], f"{name} deklariert noch ein target"


def test_boost_beschreibung_stimmt_zur_bettweiten_semantik():
    """#11: set_boost sagte 'für eine Zone' -- korrekt ist: alle Zonen."""
    description = _services()["set_boost"]["description"]
    assert "eine Zone" not in description
    assert "alle Zonen" in description
