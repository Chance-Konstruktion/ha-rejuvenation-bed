"""Die Sicherheitskette, von der Messung bis zum geschalteten Relais.

Der Safety-Manager traegt oben im Quelltext "KRITISCHE
SICHERHEITSKOMPONENTE". Seine bisherigen Tests laufen gegen Attrappen und
pruefen, welchen *Text* er zurueckgibt. Was sie nicht pruefen koennen --
und was als einziges zaehlt, wenn jemand darin schlaeft -- ist, ob am Ende
der Kette der Strom wirklich weg ist.

Diese Datei prueft genau das: Fuehler meldet zu heiss, Regelkreis dreht
sich einmal, Heizung ist aus. Ueber echte Dienstaufrufe, an einer echten
Entitaet, in einem echten Zustandsspeicher.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant

from custom_components.rejuvenation_bed.const import DOMAIN
from custom_components.rejuvenation_bed.safety_manager import (
    OVERHEAT_CRITICAL_TEMP,
    OVERHEAT_EMERGENCY_TEMP,
)

from conftest import FUEHLER, HEIZUNG, temperatur_melden


def _koordinator(hass: HomeAssistant, eintrag):
    return hass.data[DOMAIN][eintrag.entry_id]


async def _heizung_an(hass: HomeAssistant) -> None:
    await hass.services.async_call(
        "input_boolean", "turn_on", {"entity_id": HEIZUNG}, blocking=True
    )
    assert hass.states.get(HEIZUNG).state == "on"


async def test_ueberhitzung_schaltet_die_heizung_wirklich_ab(
    hass: HomeAssistant, bett
) -> None:
    """Der wichtigste Test des ganzen Projekts.

    Ueber der Hardware-Grenze muss der Strom weg sein. Nicht "der Manager
    gibt is_safe=False zurueck", nicht "eine Nachricht wurde erzeugt" --
    der Schalter steht auf aus. Alles davor ist Buchhaltung.
    """
    await _heizung_an(hass)

    await temperatur_melden(hass, 37.0)
    await _koordinator(hass, bett).async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(HEIZUNG).state == "off", "die Heizung lief bei 37 °C weiter"


async def test_notaus_haelt_auch_wenn_es_wieder_kuehl_wird(
    hass: HomeAssistant, bett
) -> None:
    """Ein Not-Aus, der sich selbst aufhebt, hat nichts geschuetzt.

    Genau das ist der Verlauf bei einem klebenden Relais: die Heizung
    laeuft weiter, der Fuehler meldet einen Ausreisser nach oben, dann
    misst er wieder plausibel -- und wuerde die Verriegelung von selbst
    fallen, liefe die Anlage in dieselbe Ueberhitzung zurueck, diesmal
    ohne dass jemand hinsieht.

    Dieser Test hat den Fehler gefunden (Issue #1): die Verriegelung war
    unerreichbar, weil ``hardware_max`` und ``OVERHEAT_EMERGENCY_TEMP``
    beide auf 36 stehen und die globale Pruefung deshalb immer zuerst
    zurueckkehrte.
    """
    koordinator = _koordinator(hass, bett)
    await _heizung_an(hass)

    await temperatur_melden(hass, OVERHEAT_EMERGENCY_TEMP + 1)
    await koordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(HEIZUNG).state == "off"

    # Zurueck auf einen voellig unauffaelligen Wert.
    await temperatur_melden(hass, 26.0)
    await koordinator.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(HEIZUNG).state == "off", "der Not-Aus hat sich selbst aufgehoben"


async def test_freigabe_hebt_den_notaus_auf(hass: HomeAssistant, bett) -> None:
    """Die Gegenseite: nach der Pruefung muss das Bett wieder anlaufen.

    Eine Verriegelung ohne Freigabe waere kein Schutz, sondern ein
    Totalausfall bis zum naechsten Neustart -- und beim Wasserbett heisst
    das Auskuehlen und Kondenswasser. Genau diese Luecke bestand, bevor es
    den Dienst gab: ``SafetyManager.clear_emergency()`` existierte, hatte
    aber im ganzen Projekt keinen Aufrufer.
    """
    koordinator = _koordinator(hass, bett)
    await _heizung_an(hass)

    await temperatur_melden(hass, OVERHEAT_EMERGENCY_TEMP + 1)
    await koordinator.async_refresh()
    await hass.async_block_till_done()
    assert koordinator.safety_manager.emergency_zones() == [0]

    await temperatur_melden(hass, 26.0)
    await hass.services.async_call(DOMAIN, "clear_emergency", {}, blocking=True)
    await hass.async_block_till_done()

    assert koordinator.safety_manager.emergency_zones() == []
    assert koordinator.safety_manager.is_emergency_shutdown(0) is False


async def test_notaus_meldet_sich_beim_nutzer(hass: HomeAssistant, bett) -> None:
    """Stufe 3 der Sicherheitshierarchie: der Mensch muss es erfahren.

    Der Kopf von safety_manager.py nennt die Nutzer-Benachrichtigung
    ausdruecklich. Bis Issue #1 schrieb die eigentliche Abschaltung nur
    eine Protokollzeile -- gesehen haette das niemand, der nicht ohnehin
    schon gesucht hat.
    """
    koordinator = _koordinator(hass, bett)
    await _heizung_an(hass)

    await temperatur_melden(hass, OVERHEAT_EMERGENCY_TEMP + 1)
    await koordinator.async_refresh()
    await hass.async_block_till_done()

    # Persistente Meldungen sind seit 2022 keine Entitaeten mehr -- sie
    # stehen nicht im Zustandsspeicher, sondern in einer eigenen Ablage.
    # Home Assistants eigene Tests greifen genauso darauf zu.
    from homeassistant.components import persistent_notification as pn

    meldungen = pn._async_get_or_create_notifications(hass)
    assert "rejuvenation_bed_emergency_0" in meldungen, (
        f"keine Meldung fuer die verriegelte Zone; vorhanden: {sorted(meldungen)}"
    )
    text = meldungen["rejuvenation_bed_emergency_0"]["message"]
    # Der Nutzer muss zwei Dinge erfahren: dass es aus bleibt, und wie er
    # es wieder anbekommt.
    assert "bleibt aus" in text
    assert "clear_emergency" in text


async def test_freigabe_raeumt_die_meldung_weg(hass: HomeAssistant, bett) -> None:
    """Eine Warnung, die nach der Freigabe stehen bleibt, erzieht zum Wegklicken.

    Wer sich daran gewoehnt, Meldungen dieser Integration ungelesen
    wegzuwischen, uebersieht die naechste echte.
    """
    from homeassistant.components import persistent_notification as pn

    koordinator = _koordinator(hass, bett)
    await _heizung_an(hass)

    await temperatur_melden(hass, OVERHEAT_EMERGENCY_TEMP + 1)
    await koordinator.async_refresh()
    await hass.async_block_till_done()
    assert "rejuvenation_bed_emergency_0" in pn._async_get_or_create_notifications(hass)

    await temperatur_melden(hass, 26.0)
    await hass.services.async_call(DOMAIN, "clear_emergency", {}, blocking=True)
    await hass.async_block_till_done()

    assert "rejuvenation_bed_emergency_0" not in pn._async_get_or_create_notifications(hass)


async def test_ausgefallener_fuehler_schaltet_das_wasserbett_nicht_hart_ab(
    hass: HomeAssistant, bett
) -> None:
    """Beim Wasserbett ist Auskuehlen das groessere Risiko.

    Ein Wasserbett unter 24 °C schlaegt Kondenswasser an und wird
    unbenutzbar; deshalb faellt es bei einem Fuehlerausfall in einen
    gedrosselten Takt statt in ein hartes Aus. Der Unterschied zur
    Heizmatte ist eine bewusste Entscheidung im Quelltext, und ohne einen
    echten Zustandsspeicher laesst sich "der Fuehler ist weg" gar nicht
    herstellen.
    """
    koordinator = _koordinator(hass, bett)

    hass.states.async_set(FUEHLER, "unavailable")
    await hass.async_block_till_done()
    await koordinator.async_refresh()
    await hass.async_block_till_done()

    zustand = koordinator.data.get("global_state", {}).get("status")
    assert zustand == "DEGRADED_MODE", f"Status war {zustand!r}"


async def test_unlesbarer_fuehlerwert_wirft_den_regelkreis_nicht(
    hass: HomeAssistant, bett
) -> None:
    """Ein Fuehler darf Unsinn melden, ohne die Steuerung anzuhalten.

    Ein abgestuerzter Coordinator schaltet nichts mehr -- weder ein noch
    aus. Die Heizung bliebe im letzten Zustand stehen, und das ist bei
    einer Heizung der schlechteste aller Ausgaenge.
    """
    koordinator = _koordinator(hass, bett)

    hass.states.async_set(FUEHLER, "kaputt")
    await hass.async_block_till_done()
    await koordinator.async_refresh()
    await hass.async_block_till_done()

    assert koordinator.last_update_success is True
    assert koordinator.data is not None


async def test_kritische_temperatur_verhindert_das_einschalten(
    hass: HomeAssistant, bett
) -> None:
    """Zwischen kritisch und Not-Aus darf nicht geheizt werden.

    34 °C sind noch keine Verriegelung, aber sicher kein Zustand, in dem
    die Software zuheizen darf.
    """
    koordinator = _koordinator(hass, bett)

    await temperatur_melden(hass, OVERHEAT_CRITICAL_TEMP + 0.5)
    await koordinator.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(HEIZUNG).state == "off"
