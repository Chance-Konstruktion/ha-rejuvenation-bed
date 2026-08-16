"""Das Thermostat, wie der Nutzer es bedient -- in einem echten Kern.

Die Attrappen-Suite prueft die Rechenwege: welche Temperatur die Kurve
zu welcher Stunde vorschlaegt, wie die Rampe faehrt. Was sie nicht sagen
kann: was passiert, wenn jemand in der Oberflaeche am Rad dreht. Dieser
Weg laeuft ueber Home Assistants Klima-Dienste, ueber deren Pruefungen
und erst dann in unseren Code -- und genau dazwischen entscheidet sich,
ob eine Eingabe ankommt, abgewiesen wird oder still danebengeht.

Bei einer Bettheizung ist das keine Kosmetik. Die Zone hier hat
``hardware_max = 36``; darueber liegt nur noch die absolute Grenze der
Integration. Was ein Bedienfeld an Zieltemperatur durchlaesst, liegt
danach am Koerper eines schlafenden Menschen an.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    DOMAIN as CLIMATE_DOMAIN,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_TEMPERATURE,
    HVACMode,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.rejuvenation_bed.const import ABSOLUTE_MAX_TEMP


async def regelkreis_drehen(hass: HomeAssistant) -> None:
    """Warten, bis der Koordinator wirklich neu gerechnet hat.

    ``async_set_temperature`` legt den Wunsch am Koordinator ab und ruft
    ``async_request_refresh``. Das ist ENTPRELLT: Home Assistant sammelt
    Anfragen und dreht den Regelkreis erst nach einer Ruhezeit -- sonst
    rechnete eine Integration bei jedem Schieberegler-Zucken neu.

    ``async_block_till_done`` bewegt die Uhr nicht, wartet also auf etwas,
    das erst spaeter faellig wird. Genau daran sind meine ersten drei
    Tests gescheitert -- am Test, nicht an der Integration. Die Uhr muss
    weitergestellt werden, und danach ist das Ergebnis echt.
    """
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=30))
    await hass.async_block_till_done()


def _thermostat(hass: HomeAssistant, bett) -> str:
    """Die eine Klima-Entitaet dieses Bettes.

    Gesucht statt eingetragen: Der Entitaets-Name haengt am Titel des
    Eintrags, und ein fester String hier waere beim naechsten
    Umbenennen falsch -- und zwar auf die stille Art, weil der Test dann
    einfach nichts findet.
    """
    register = er.async_get(hass)
    klima = [
        e.entity_id
        for e in er.async_entries_for_config_entry(register, bett.entry_id)
        if e.entity_id.startswith("climate.")
    ]
    assert klima, "Das Bett hat keine Klima-Entitaet angelegt"
    return klima[0]


# ── Was das Thermostat ueber sich sagt ────────────────────────────────


async def test_das_thermostat_meldet_seine_grenzen(hass: HomeAssistant, bett) -> None:
    """min_temp und max_temp sind das, woran sich jede Oberflaeche haelt.

    Der Schieberegler in der App, die Sprachassistenz, jede Automatisierung:
    Sie alle lesen diese beiden Zahlen. Stehen sie falsch, ist jede weitere
    Sicherung eine Stufe zu spaet.
    """
    zustand = hass.states.get(_thermostat(hass, bett))
    assert zustand is not None
    assert zustand.attributes["min_temp"] >= 15, "unplausibel niedrig"
    assert zustand.attributes["max_temp"] <= ABSOLUTE_MAX_TEMP, (
        f"Das Thermostat bietet {zustand.attributes['max_temp']} °C an, "
        f"die Integration erlaubt hoechstens {ABSOLUTE_MAX_TEMP} °C"
    )


async def test_das_thermostat_hat_eine_eigene_kennung(
    hass: HomeAssistant, bett
) -> None:
    """Ohne unique_id kann der Nutzer die Entitaet nicht umbenennen, keinem
    Bereich zuordnen und nicht in einer Automatisierung stabil ansprechen --
    nach jedem Neustart waere sie eine andere."""
    register = er.async_get(hass)
    eintrag = register.async_get(_thermostat(hass, bett))
    assert eintrag is not None and eintrag.unique_id


# ── Was ankommt, wenn jemand am Rad dreht ─────────────────────────────


async def test_eine_zieltemperatur_kommt_wirklich_an(
    hass: HomeAssistant, bett
) -> None:
    """Der ganze Weg: Dienstaufruf, Home Assistants Pruefung, unser Code,
    zurueck in den Zustandsspeicher. In der Attrappen-Suite endet er nach
    dem zweiten Schritt."""
    entitaet = _thermostat(hass, bett)
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: entitaet, ATTR_TEMPERATURE: 30.0},
        blocking=True,
    )
    await regelkreis_drehen(hass)

    zustand = hass.states.get(entitaet)
    assert zustand.attributes.get("temperature") == 30.0, (
        "Die gesetzte Zieltemperatur steht nicht am Thermostat -- der "
        "Nutzer dreht am Rad und nichts passiert"
    )


async def test_ueber_der_grenze_kommt_nichts_an(hass: HomeAssistant, bett) -> None:
    """Der Fall, auf den es bei einer Bettheizung ankommt.

    Ein Wert oberhalb von ``max_temp`` darf nicht als Ziel stehenbleiben --
    egal ob Home Assistant ihn abweist oder unser Code ihn deckelt. Beides
    ist in Ordnung; nur durchreichen ist es nicht. Deshalb prueft dieser
    Test das ERGEBNIS und nicht den Weg dorthin: Er bleibt richtig, auch
    wenn eine kuenftige Home-Assistant-Version die Pruefung verschiebt.
    """
    entitaet = _thermostat(hass, bett)
    grenze = hass.states.get(entitaet).attributes["max_temp"]
    zu_heiss = grenze + 10

    try:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: entitaet, ATTR_TEMPERATURE: zu_heiss},
            blocking=True,
        )
        await regelkreis_drehen(hass)
    except (ServiceValidationError, ValueError):
        # Home Assistant hat abgewiesen. Das ist der saubere Ausgang.
        pass

    ziel = hass.states.get(entitaet).attributes.get("temperature")
    assert ziel is None or ziel <= grenze, (
        f"{zu_heiss} °C stehen als Ziel am Thermostat, obwohl die Grenze "
        f"bei {grenze} °C liegt. Das liegt danach am Koerper an."
    )


async def test_ausschalten_schaltet_die_heizung_wirklich_ab(
    hass: HomeAssistant, bett
) -> None:
    """HVACMode.OFF ist kein Anzeigezustand.

    Wer das Thermostat ausschaltet, erwartet, dass der Schaltaktor faellt.
    Geprueft wird deshalb der echte ``input_boolean`` und nicht das
    Attribut, das die Integration ueber sich selbst behauptet.
    """
    from .conftest import HEIZUNG, temperatur_melden

    entitaet = _thermostat(hass, bett)

    # Erst heizen lassen: kalt genug, damit ueberhaupt eingeschaltet wird.
    await hass.services.async_call(
        CLIMATE_DOMAIN, SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: entitaet, ATTR_HVAC_MODE: HVACMode.HEAT}, blocking=True)
    await temperatur_melden(hass, 20.0)
    await regelkreis_drehen(hass)

    await hass.services.async_call(
        CLIMATE_DOMAIN, SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: entitaet, ATTR_HVAC_MODE: HVACMode.OFF}, blocking=True)
    await regelkreis_drehen(hass)
    await temperatur_melden(hass, 20.0)
    await regelkreis_drehen(hass)

    assert hass.states.get(HEIZUNG).state == "off", (
        "Das Thermostat steht auf Aus, der Schaltaktor aber auf An"
    )
    assert hass.states.get(entitaet).state == HVACMode.OFF


async def test_wiederholtes_setzen_bleibt_ruhig(hass: HomeAssistant, bett) -> None:
    """Dreimal dieselbe Temperatur darf nicht dreimal etwas anderes
    ergeben. Ein Zustand, der beim zweiten Aufruf anders gelesen als
    geschrieben wird, faellt im Betrieb erst nach Stunden auf."""
    entitaet = _thermostat(hass, bett)
    for _ in range(3):
        await hass.services.async_call(
            CLIMATE_DOMAIN, SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: entitaet, ATTR_TEMPERATURE: 29.0}, blocking=True)
        await regelkreis_drehen(hass)
    assert hass.states.get(entitaet).attributes.get("temperature") == 29.0
