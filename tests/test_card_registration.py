"""Tests für die Auslieferung der Lovelace-Karte.

Die Karte wird von der Integration selbst im Frontend angemeldet. Schlägt das
fehl, darf das Setup trotzdem nicht abbrechen — ohne Karte bleibt die
Integration voll funktionsfähig.
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.rejuvenation_bed import (
    CARD_FILENAME,
    CARD_REGISTERED,
    CARD_RESOURCE_URL,
    CARD_URL,
    _async_register_card,
)


def _hass():
    hass = MagicMock()
    hass.data = {}
    hass.http.async_register_static_paths = AsyncMock()
    return hass


def _resources(items=()):
    """Die Storage-Variante der Lovelace-Ressourcen."""
    res = MagicMock()
    res.loaded = True
    res.async_load = AsyncMock()
    res.async_items = MagicMock(return_value=list(items))
    res.async_create_item = AsyncMock()
    res.async_update_item = AsyncMock()
    return res


def _hass_mit_lovelace(items=()):
    hass = _hass()
    res = _resources(items)
    lovelace = MagicMock()
    lovelace.resources = res
    hass.data["lovelace"] = lovelace
    return hass, res


def test_card_datei_wird_ausgeliefert():
    """Die Karte liegt im Paket und wird nicht erst zur Laufzeit erzeugt."""
    card = Path("custom_components/rejuvenation_bed/frontend") / CARD_FILENAME
    assert card.is_file()
    inhalt = card.read_text(encoding="utf-8")
    assert 'customElements.define("rejuvenation-nightstand"' in inhalt


def test_manifest_deklariert_benutzte_komponenten():
    """hassfest besteht darauf, dass benutzte Komponenten im Manifest stehen."""
    import json

    manifest = json.loads(Path("custom_components/rejuvenation_bed/manifest.json").read_text(encoding="utf-8"))
    deps = manifest.get("dependencies", [])
    assert "http" in deps, "async_register_static_paths() braucht die http-Komponente"
    assert "frontend" in deps, "add_extra_js_url() braucht die frontend-Komponente"
    after = manifest.get("after_dependencies", [])
    assert "lovelace" in after, "die Ressource kann erst nach Lovelace eingetragen werden"


def test_karte_holt_fehlerkarten_zurueck():
    """Kommt das Skript zu spaet, muss die Fehlerkarte neu gebaut werden."""
    inhalt = _karte()
    assert "ll-rebuild" in inhalt
    assert "hui-error-card" in inhalt


def test_registriert_pfad_und_frontend_url():
    """Ohne Lovelace-Storage bleibt nur das Extra-Skript."""
    hass = _hass()
    with patch("custom_components.rejuvenation_bed.frontend") as frontend:
        asyncio.run(_async_register_card(hass))

    hass.http.async_register_static_paths.assert_awaited_once()
    frontend.add_extra_js_url.assert_called_once_with(hass, CARD_URL)
    assert hass.data[CARD_REGISTERED] is True


def test_karte_wird_lovelace_ressource():
    """Auf Ressourcen wartet das Dashboard — sonst "Konfigurationsfehler"."""
    hass, res = _hass_mit_lovelace()
    with patch("custom_components.rejuvenation_bed.frontend") as frontend:
        asyncio.run(_async_register_card(hass))

    res.async_create_item.assert_awaited_once_with({"res_type": "module", "url": CARD_RESOURCE_URL})
    frontend.add_extra_js_url.assert_not_called()
    assert hass.data[CARD_REGISTERED] is True


def test_ressource_wird_nicht_doppelt_angelegt():
    hass, res = _hass_mit_lovelace([{"id": "1", "url": CARD_RESOURCE_URL, "res_type": "module"}])
    with patch("custom_components.rejuvenation_bed.frontend"):
        asyncio.run(_async_register_card(hass))

    res.async_create_item.assert_not_awaited()
    res.async_update_item.assert_not_awaited()


def test_alter_ressourceneintrag_bekommt_neue_version():
    """Sonst laedt der Browser nach einem Update die alte Karte aus dem Cache."""
    hass, res = _hass_mit_lovelace([{"id": "1", "url": f"{CARD_URL}?v=250101", "res_type": "module"}])
    with patch("custom_components.rejuvenation_bed.frontend"):
        asyncio.run(_async_register_card(hass))

    res.async_update_item.assert_awaited_once_with("1", {"url": CARD_RESOURCE_URL})
    res.async_create_item.assert_not_awaited()


def test_ressourcen_werden_bei_bedarf_geladen():
    hass, res = _hass_mit_lovelace()
    res.loaded = False
    with patch("custom_components.rejuvenation_bed.frontend"):
        asyncio.run(_async_register_card(hass))

    res.async_load.assert_awaited_once()
    res.async_create_item.assert_awaited_once()


def test_yaml_modus_faellt_auf_extra_js_zurueck():
    """Im YAML-Modus kann die Sammlung nichts anlegen."""
    hass = _hass()
    lovelace = MagicMock()
    lovelace.resources = MagicMock(spec=["async_items"])  # kein async_create_item
    hass.data["lovelace"] = lovelace

    with patch("custom_components.rejuvenation_bed.frontend") as frontend:
        asyncio.run(_async_register_card(hass))

    frontend.add_extra_js_url.assert_called_once_with(hass, CARD_URL)


def test_registriert_nur_einmal():
    """Zwei Config-Entries dürfen die Karte nicht doppelt anmelden."""
    hass = _hass()
    with patch("custom_components.rejuvenation_bed.frontend") as frontend:
        asyncio.run(_async_register_card(hass))
        asyncio.run(_async_register_card(hass))

    assert hass.http.async_register_static_paths.await_count == 1
    assert frontend.add_extra_js_url.call_count == 1


def test_fehlende_datei_bricht_setup_nicht_ab():
    hass = _hass()
    with patch("custom_components.rejuvenation_bed.Path") as path_cls:
        path_cls.return_value.parent.__truediv__.return_value.__truediv__.return_value.is_file.return_value = False
        asyncio.run(_async_register_card(hass))

    hass.http.async_register_static_paths.assert_not_awaited()
    assert CARD_REGISTERED not in hass.data


def test_fehler_beim_registrieren_wird_geschluckt():
    """Ein kaputtes Frontend darf die Heizungssteuerung nicht mitreißen."""
    hass = _hass()
    hass.http.async_register_static_paths.side_effect = RuntimeError("kaputt")

    with patch("custom_components.rejuvenation_bed.frontend"):
        asyncio.run(_async_register_card(hass))  # darf nicht werfen

    assert CARD_REGISTERED not in hass.data


def _karte() -> str:
    return (Path("custom_components/rejuvenation_bed/frontend") / CARD_FILENAME).read_text(encoding="utf-8")


def test_karte_bringt_grafischen_editor_mit():
    """Entities werden ausgewählt, nicht als Entity-ID abgetippt."""
    inhalt = _karte()
    assert "static getConfigElement()" in inhalt
    assert 'customElements.define("rejuvenation-nightstand-editor"' in inhalt
    assert "function entityPicker(" in inhalt
    assert "include_entities" in inhalt, "es werden nur passende Entities vorgeschlagen"


def test_editor_filtert_weckzeit_auf_zeitstempel():
    """Unter sensor. liegt zu viel — als Weckzeit taugen nur Zeit-Entities."""
    inhalt = _karte()
    assert "has_time" in inhalt
    assert '"timestamp"' in inhalt


def test_nachtlicht_nutzt_gueltigen_dienstparameter():
    """light.turn_on kennt color_temp_kelvin; »kelvin« weist der Kern ab."""
    inhalt = _karte()
    assert "color_temp_kelvin" in inhalt
    assert "kelvin: 2000" not in inhalt


def test_karte_passt_auf_kleinstschirme():
    """Aussendisplay eines Falters: nichts darf unten abgeschnitten werden."""
    inhalt = _karte()
    assert "TINY_MAX_PX" in inhalt
    assert ".root.is-tiny" in inhalt
    assert "min-height: 0" in inhalt


def test_uhr_wechselt_nicht_mehr_per_tipp():
    """Das Zifferblatt gehört in die Einstellungen — nachts trifft man die Uhr zu leicht."""
    inhalt = _karte()
    assert "_cycleFace" not in inhalt
    assert '$("clock").addEventListener' not in inhalt


def test_layout_kennt_breitbild():
    inhalt = _karte()
    assert 'LAYOUTS = ["auto", "tall", "wide"]' in inhalt
    assert ".root.is-wide" in inhalt


@pytest.mark.parametrize("stelle", ["climate", "input_datetime", "input_boolean", "light"])
def test_karte_ruft_erwartete_dienste(stelle):
    """Die Karte spricht Dienste an, keine REST-Endpunkte mit Token."""
    inhalt = (Path("custom_components/rejuvenation_bed/frontend") / CARD_FILENAME).read_text(encoding="utf-8")
    assert f'"{stelle}"' in inhalt
    assert "Authorization" not in inhalt
    assert "Bearer" not in inhalt
