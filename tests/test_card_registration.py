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
    CARD_URL,
    _async_register_card,
)


def _hass():
    hass = MagicMock()
    hass.data = {}
    hass.http.async_register_static_paths = AsyncMock()
    return hass


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


def test_registriert_pfad_und_frontend_url():
    hass = _hass()
    with patch("custom_components.rejuvenation_bed.frontend") as frontend:
        asyncio.run(_async_register_card(hass))

    hass.http.async_register_static_paths.assert_awaited_once()
    frontend.add_extra_js_url.assert_called_once_with(hass, CARD_URL)
    assert hass.data[CARD_REGISTERED] is True


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
    assert 'selector: { entity: { domain: "climate" } }' in inhalt


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
