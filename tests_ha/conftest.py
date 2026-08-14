"""Vorrichtungen fuer die Tests gegen ein echtes Home Assistant.

Der Unterschied zu ``tests/`` ist der ganze Zweck dieses Ordners: dort
ersetzt die conftest.py das Paket ``homeassistant`` in ``sys.modules``
durch Attrappen. Das reicht, um Rechenlogik zu pruefen -- die
Biorhythmus-Kurve, den Sleep-Score, die Rampe. Es reicht nicht fuer die
Frage, auf die es bei einer Bettheizung ankommt: schaltet die Heizung
wirklich ab.

Hier laeuft deshalb ein echtes Home Assistant, und die Heizung ist ein
echtes ``input_boolean``. Ruft die Integration ``turn_off``, geht der
Zustand im Zustandsspeicher wirklich auf ``off`` -- oder eben nicht.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.rejuvenation_bed.const import DOMAIN

HEIZUNG = "input_boolean.bett_heizung"
FUEHLER = "sensor.bett_temperatur"


@pytest.fixture(autouse=True)
def eigene_integrationen(enable_custom_integrations):
    """Ohne das findet Home Assistant custom_components/ gar nicht erst."""
    yield


@pytest.fixture
async def hardware(hass: HomeAssistant) -> None:
    """Die Hardware, die das Bett schaltet -- echt, nicht behauptet.

    ``input_boolean`` ist im Einrichtungsassistenten ausdruecklich als
    Heizungs-Domain erlaubt, laesst sich im Test ohne Geraet aufsetzen und
    reagiert auf dieselben ``turn_on``/``turn_off``-Dienste wie ein
    Schaltaktor. Damit ist der Weg vom Sicherheitsbefehl bis zum
    geschalteten Zustand derselbe wie im Wohnzimmer.
    """
    assert await async_setup_component(
        hass, "input_boolean", {"input_boolean": {"bett_heizung": {"name": "Bett Heizung"}}}
    )
    await hass.async_block_till_done()


def zonen_konfiguration() -> dict:
    """Ein Wasserbett mit einer Zone -- die kleinste sinnvolle Anlage."""
    return {
        "zones": [
            {
                "heater": HEIZUNG,
                "temp_sensor": FUEHLER,
                "hardware_max": 36,
                "boost_target_temp": 34,
                "power_rating": 250,
                "hardware_level": "A",
            }
        ],
        "global": {
            "bed_type": "wasserbett",
            "warm_from": "22:00",
            "warm_until": "07:00",
            "chronotype": "normal",
        },
        "energy": {"enable_tracking": True, "total_power_rating": 250},
    }


@pytest.fixture
async def bett(hass: HomeAssistant, hardware) -> MockConfigEntry:
    """Ein eingerichtetes Bett bei unauffaelliger Temperatur."""
    hass.states.async_set(FUEHLER, "28.0", {"device_class": "temperature",
                                            "unit_of_measurement": "°C"})
    await hass.async_block_till_done()

    eintrag = MockConfigEntry(
        domain=DOMAIN,
        title="Rejuvenation Bed",
        data=zonen_konfiguration(),
        version=2,
    )
    eintrag.add_to_hass(hass)
    assert await hass.config_entries.async_setup(eintrag.entry_id)
    await hass.async_block_till_done()
    return eintrag


async def temperatur_melden(hass: HomeAssistant, grad: float) -> None:
    """Den Fuehler etwas melden lassen und den Regelkreis einmal drehen."""
    hass.states.async_set(FUEHLER, str(grad), {"device_class": "temperature",
                                               "unit_of_measurement": "°C"})
    await hass.async_block_till_done()
