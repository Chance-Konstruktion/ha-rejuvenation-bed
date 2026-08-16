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
from custom_components.rejuvenation_bed.const import ABSOLUTE_MAX_TEMP, DOMAIN


async def regelkreis_drehen(hass: HomeAssistant, bett) -> None:
    """Den Koordinator wirklich einmal rechnen lassen.

    ``async_set_temperature`` legt den Wunsch am Koordinator ab und ruft
    ``async_request_refresh``. Das ist ENTPRELLT: Home Assistant sammelt
    Anfragen und rechnet erst nach einer Ruhezeit neu -- sonst rechnete
    eine Integration bei jedem Zucken des Schiebereglers.

    Zwei Anlaeufe habe ich hier gebraucht, und der erste war lehrreich:
    ``async_block_till_done`` bewegt die Uhr nicht, also wartete der Test
    auf etwas, das noch nicht faellig war. Die Uhr vorzustellen
    (``async_fire_time_changed``) half aber auch nicht -- der Debouncer
    haengt an der Laufzeit-Uhr der Ereignisschleife, und die stellt kein
    Test um. Ein Test, der auf zehn echte Sekunden wartet, ist keine
    Loesung, sondern eine Wette.

    Also direkt: den Koordinator holen und rechnen lassen. Was danach am
    Thermostat steht, ist echt gerechnet und nicht abgewartet.
    """
    koordinator = hass.data[DOMAIN][bett.entry_id]
    await koordinator.async_refresh()
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


async def test_der_wunsch_kommt_am_regler_an(hass: HomeAssistant, bett) -> None:
    """Der ganze Weg: Dienstaufruf, Home Assistants Pruefung, unser Code.

    Geprueft wird der WUNSCH, nicht die Anzeige -- die beiden sind bei
    diesem Bett absichtlich verschieden, siehe den naechsten Test.
    """
    entitaet = _thermostat(hass, bett)
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: entitaet, ATTR_TEMPERATURE: 30.0},
        blocking=True,
    )
    await regelkreis_drehen(hass, bett)

    koordinator = hass.data[DOMAIN][bett.entry_id]
    assert koordinator.get_active_manual_target(0) == 30.0, (
        "Der Wunsch des Nutzers ist am Koordinator nicht angekommen -- "
        "dann dreht er am Rad und es passiert wirklich nichts"
    )


async def test_die_anzeige_ist_die_rampe_und_nicht_der_wunsch(
    hass: HomeAssistant, bett
) -> None:
    """Was das Thermostat zeigt, ist der GERAMPTE Sollwert.

    Das ist Absicht: Ein Wasserbett vertraegt keine Temperatursprunge, der
    RampController faehrt den Sollwert deshalb mit begrenzter Rate von der
    Ist-Temperatur zum Wunsch. Solange die Rampe laeuft, steht am
    Thermostat also weniger, als der Nutzer eingestellt hat.

    Dieser Test haelt genau das fest -- und zwar als Zusage, nicht als
    Entschuldigung: Die Anzeige darf zwischen Ist und Wunsch liegen, aber
    NIE darueber. Ein Sollwert oberhalb des Wunsches waere ein Ueberschwinger,
    und der liegt bei einer Bettheizung an einem Koerper an.

    (Fuer den Nutzer bleibt das trotzdem verwirrend: Er stellt 30 ein und
    liest 28. Ob die Integration den Wunsch als `target_temperature` zeigen
    und die Rampe intern fahren sollte, ist eine Entscheidung fuer Chris --
    dieser Test schreibt sie nicht fest, er beschreibt nur, was heute gilt.)
    """
    entitaet = _thermostat(hass, bett)
    ist = hass.states.get(entitaet).attributes.get("current_temperature")
    await hass.services.async_call(
        CLIMATE_DOMAIN, SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: entitaet, ATTR_TEMPERATURE: 30.0}, blocking=True)
    await regelkreis_drehen(hass, bett)

    gezeigt = hass.states.get(entitaet).attributes.get("temperature")
    assert gezeigt is not None
    assert gezeigt <= 30.0, (
        f"Der Sollwert {gezeigt} liegt UEBER dem Wunsch 30.0 -- ein "
        "Ueberschwinger, der an einem Koerper anliegt"
    )
    if ist is not None:
        assert gezeigt >= min(ist, 30.0) - 0.1, (
            f"Der Sollwert {gezeigt} liegt unter der Ist-Temperatur {ist} "
            "und unter dem Wunsch -- die Rampe faehrt in die falsche Richtung"
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
        await regelkreis_drehen(hass, bett)
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
    from conftest import HEIZUNG, temperatur_melden

    entitaet = _thermostat(hass, bett)

    # Erst heizen lassen: kalt genug, damit ueberhaupt eingeschaltet wird.
    await hass.services.async_call(
        CLIMATE_DOMAIN, SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: entitaet, ATTR_HVAC_MODE: HVACMode.HEAT}, blocking=True)
    await temperatur_melden(hass, 20.0)
    await regelkreis_drehen(hass, bett)

    await hass.services.async_call(
        CLIMATE_DOMAIN, SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: entitaet, ATTR_HVAC_MODE: HVACMode.OFF}, blocking=True)
    await regelkreis_drehen(hass, bett)
    await temperatur_melden(hass, 20.0)
    await regelkreis_drehen(hass, bett)

    assert hass.states.get(HEIZUNG).state == "off", (
        "Das Thermostat steht auf Aus, der Schaltaktor aber auf An"
    )
    assert hass.states.get(entitaet).state == HVACMode.OFF


async def test_wiederholtes_setzen_bleibt_ruhig(hass: HomeAssistant, bett) -> None:
    """Dreimal derselbe Wunsch darf nicht dreimal etwas anderes ergeben.

    Ein Zustand, der beim zweiten Aufruf anders gelesen als geschrieben
    wird, faellt im Betrieb erst nach Stunden auf -- und dann nachts.
    """
    entitaet = _thermostat(hass, bett)
    koordinator = hass.data[DOMAIN][bett.entry_id]
    for _ in range(3):
        await hass.services.async_call(
            CLIMATE_DOMAIN, SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: entitaet, ATTR_TEMPERATURE: 29.0}, blocking=True)
        await regelkreis_drehen(hass, bett)
        assert koordinator.get_active_manual_target(0) == 29.0
