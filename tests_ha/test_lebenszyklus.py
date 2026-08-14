"""Einrichten, Dienste, Entitaeten, Entladen -- in einem echten Kern.

Die Attrappen-Suite prueft, dass ``async_setup_entry`` durchlaeuft. Ob
Home Assistant danach vier Plattformen geladen, sechs Dienste registriert
und ein Geraet angelegt hat, kann sie nicht sagen -- dafuer braucht es die
echte Eintragsverwaltung.
"""

from __future__ import annotations

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from custom_components.rejuvenation_bed.const import DOMAIN

DIENSTE = [
    "set_boost",
    "set_sick_mode",
    "set_vacation_mode",
    "cancel_special_mode",
    "reset_energy_budget",
    "preheat_bed",
]


async def test_bett_laedt_in_einem_echten_home_assistant(
    hass: HomeAssistant, bett
) -> None:
    assert bett.state is ConfigEntryState.LOADED
    assert bett.entry_id in hass.data[DOMAIN]


async def test_alle_vier_plattformen_bringen_entitaeten_mit(
    hass: HomeAssistant, bett
) -> None:
    """climate, sensor, binary_sensor, switch -- jede muss etwas liefern.

    Eine Plattform, die still nichts anlegt, faellt sonst niemandem auf:
    die Integration gilt als geladen, und der Nutzer sucht vergeblich nach
    seinem Thermostat.
    """
    register = er.async_get(hass)
    eintraege = er.async_entries_for_config_entry(register, bett.entry_id)
    domains = {eintrag.entity_id.split(".", 1)[0] for eintrag in eintraege}

    for plattform in ("climate", "sensor", "binary_sensor", "switch"):
        assert plattform in domains, f"{plattform} hat keine Entitaet angelegt"


async def test_das_bett_ist_ein_geraet_in_home_assistant(
    hass: HomeAssistant, bett
) -> None:
    """Ohne Geraet haengen die Entitaeten lose im Raum.

    Sie liessen sich dann keinem Bereich zuordnen -- und damit auch nicht
    auf einem Grundriss zeichnen.
    """
    register = dr.async_get(hass)
    geraete = dr.async_entries_for_config_entry(register, bett.entry_id)
    assert geraete, "kein Geraet im Register"


async def test_alle_sechs_dienste_sind_da(hass: HomeAssistant, bett) -> None:
    """Was in services.yaml steht, muss auch registriert sein.

    Die Datei beschreibt nur die Oberflaeche. Ein Dienst, der dort steht
    und nie registriert wurde, erscheint in den Entwicklerwerkzeugen und
    scheitert beim Aufruf.
    """
    for dienst in DIENSTE:
        assert hass.services.has_service(DOMAIN, dienst), f"{dienst} fehlt"


async def test_entladen_nimmt_die_dienste_mit(hass: HomeAssistant, bett) -> None:
    """Ein Dienst ohne Coordinator dahinter ist eine Falle.

    Er steht weiter in der Oberflaeche, laesst sich aufrufen und tut
    nichts.
    """
    assert await hass.config_entries.async_unload(bett.entry_id)
    await hass.async_block_till_done()

    assert bett.state is ConfigEntryState.NOT_LOADED
    for dienst in DIENSTE:
        assert not hass.services.has_service(DOMAIN, dienst), f"{dienst} blieb stehen"


async def test_neu_laden_funktioniert_zweimal(hass: HomeAssistant, bett) -> None:
    """Ein Optionswechsel laedt die Integration neu -- das passiert oft.

    Beim zweiten Mal zeigt sich, ob beim ersten Entladen etwas liegen
    geblieben ist: ein doppelt registrierter Dienst, ein Zeitgeber, der
    weiterlaeuft, eine Entitaetskennung, die schon vergeben ist.
    """
    for durchgang in (1, 2):
        assert await hass.config_entries.async_reload(bett.entry_id), f"Durchgang {durchgang}"
        await hass.async_block_till_done()
        assert bett.state is ConfigEntryState.LOADED

    for dienst in DIENSTE:
        assert hass.services.has_service(DOMAIN, dienst)


async def test_die_nachttisch_karte_wird_ausgeliefert(
    hass: HomeAssistant, bett, hass_client
) -> None:
    """Die Karte kommt aus der Integration, nicht aus /config/www.

    Genau das ist der Komfort, den die Integration verspricht: kein
    Kopieren, kein Ressourcen-Eintrag von Hand. Ob der statische Pfad
    wirklich haengt, weiss nur ein echter HTTP-Aufruf.
    """
    from custom_components.rejuvenation_bed import CARD_URL

    client = await hass_client()
    antwort = await client.get(CARD_URL)
    assert antwort.status == 200

    inhalt = await antwort.text()
    assert "customElements.define" in inhalt or "class" in inhalt
