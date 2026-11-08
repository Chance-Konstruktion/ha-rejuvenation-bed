"""K5: Der Vacation-Selector hält sich an die Grenzen des Service-Schemas.

services.yaml bot für set_vacation_mode.temperature min=0 an, während das
Schema in __init__.py nur vol.Range(min=15, max=25) akzeptiert. Wer der
Doku folgte und 0-14 eintrug, erhielt einen Schema-Validierungsfehler.
"""

import yaml

SERVICE_SCHEMA_MIN = 15.0  # vol.Range(min=15, max=25) in __init__.py


def _vacation_temperature_selector():
    with open("custom_components/rejuvenation_bed/services.yaml", encoding="utf-8") as f:
        services = yaml.safe_load(f)
    return services["set_vacation_mode"]["fields"]["temperature"]


def test_vacation_selector_min_matches_schema():
    selector = _vacation_temperature_selector()["selector"]["number"]
    assert selector["min"] == SERVICE_SCHEMA_MIN


def test_vacation_selector_max_matches_schema():
    selector = _vacation_temperature_selector()["selector"]["number"]
    assert selector["max"] == 25


def test_vacation_description_no_longer_promises_zero():
    description = _vacation_temperature_selector()["description"]
    assert "0°C" not in description
