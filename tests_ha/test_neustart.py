"""Was einen Neustart ueberleben muss -- gegen echte Registries.

Home Assistant merkt sich Entitaeten in einer Registry: den Namen, den
der Nutzer vergeben hat, den Bereich, in dem sie haengt, ob sie
abgeschaltet wurde. Der Schluessel dazu ist die ``unique_id``. Aendert
sie sich zwischen zwei Starts, legt Home Assistant eine NEUE Entitaet an
-- und die alte bleibt als Leiche stehen: Automatisierungen zeigen ins
Leere, der Verlauf bricht ab, der eigene Name ist weg.

Nachbauen laesst sich das nicht. Eine Attrappen-Registry vergisst beim
Entladen alles und stimmt danach immer mit sich selbst ueberein. Erst
die echte behaelt etwas -- und nur dort kann dieser Fehler auffallen.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er


def _kennungen(hass: HomeAssistant, bett) -> dict[str, str]:
    register = er.async_get(hass)
    return {
        e.entity_id: e.unique_id
        for e in er.async_entries_for_config_entry(register, bett.entry_id)
    }


async def test_die_kennungen_ueberleben_das_neuladen(
    hass: HomeAssistant, bett
) -> None:
    """Dieselben Entitaeten, dieselben Kennungen -- keine einzige neue.

    Eine Kennung, die sich beim Laden aus etwas Wechselndem zusammensetzt
    (einer Uhrzeit, einer Zaehlnummer, einer Reihenfolge aus einem Set),
    faellt genau hier auf und sonst nirgends.
    """
    vorher = _kennungen(hass, bett)
    assert vorher, "Das Bett hat gar keine Entitaeten angelegt"

    await hass.config_entries.async_reload(bett.entry_id)
    await hass.async_block_till_done()
    assert bett.state is ConfigEntryState.LOADED

    nachher = _kennungen(hass, bett)
    neu = set(nachher) - set(vorher)
    verschwunden = set(vorher) - set(nachher)

    assert not neu, (
        "Nach dem Neuladen sind Entitaeten dazugekommen: "
        f"{sorted(neu)}. Das heisst, ihre unique_id hat sich geaendert -- "
        "die alten bleiben als Leichen stehen."
    )
    assert not verschwunden, f"Nach dem Neuladen fehlen: {sorted(verschwunden)}"
    assert nachher == vorher


async def test_ein_eigener_name_bleibt_stehen(hass: HomeAssistant, bett) -> None:
    """Wer seine Entitaet umbenennt, will das nicht nach jedem Neustart
    wieder tun. Der Name haengt an der Registry, nicht an unserem Code --
    aber nur, solange die Kennung dieselbe bleibt."""
    register = er.async_get(hass)
    entitaeten = er.async_entries_for_config_entry(register, bett.entry_id)
    eine = next(e for e in entitaeten if e.entity_id.startswith("climate."))

    register.async_update_entity(eine.entity_id, name="Meine Bettseite")

    await hass.config_entries.async_reload(bett.entry_id)
    await hass.async_block_till_done()

    danach = er.async_get(hass).async_get(eine.entity_id)
    assert danach is not None, "Die umbenannte Entitaet gibt es nicht mehr"
    assert danach.name == "Meine Bettseite"


async def test_eine_abgeschaltete_entitaet_bleibt_abgeschaltet(
    hass: HomeAssistant, bett
) -> None:
    """Wer eine Entitaet abschaltet, hat einen Grund. Kommt sie beim
    naechsten Start von selbst wieder, ist das kein Komfort, sondern ein
    Fehler -- besonders bei einer Heizung."""
    register = er.async_get(hass)
    entitaeten = er.async_entries_for_config_entry(register, bett.entry_id)
    eine = next(e for e in entitaeten if e.entity_id.startswith("sensor."))

    register.async_update_entity(eine.entity_id, disabled_by=er.RegistryEntryDisabler.USER)

    await hass.config_entries.async_reload(bett.entry_id)
    await hass.async_block_till_done()

    danach = er.async_get(hass).async_get(eine.entity_id)
    assert danach is not None
    assert danach.disabled_by is er.RegistryEntryDisabler.USER, (
        "Die abgeschaltete Entitaet ist von selbst wiedergekommen"
    )


async def test_entladen_laesst_keine_entitaet_im_zustandsspeicher(
    hass: HomeAssistant, bett
) -> None:
    """Nach dem Entladen darf nichts mehr Zustaende melden.

    Eine Entitaet, die nach dem Entfernen der Integration weiterhin einen
    Wert anzeigt, ist die unangenehmste Sorte Geist: Sie sieht aus wie
    eine Messung und ist eine Erinnerung von vorhin. Bei einer
    Betttemperatur heisst das, dass jemand einer Zahl glaubt, die
    niemand mehr misst.
    """
    entitaeten = list(_kennungen(hass, bett))

    assert await hass.config_entries.async_unload(bett.entry_id)
    await hass.async_block_till_done()

    noch_da = [
        e for e in entitaeten
        if (z := hass.states.get(e)) is not None and z.state != "unavailable"
    ]
    assert not noch_da, f"Diese melden nach dem Entladen noch Werte: {noch_da}"
