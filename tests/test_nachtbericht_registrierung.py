"""Tests für die Annahme-Seite des Nachtberichts: Webhook, Karten, Aufbau.

Der Endpunkt ist der einzige Weg, mit dem die Schlafaufzeichnung ins Haus
kommt. Hier wird festgeklemmt: er ist nur lokal erreichbar, antwortet mit
Grund statt stillschweigend, und die Integration überlebt sein Fehlen.
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.rejuvenation_bed import (
    REPORT_CARD_FILENAME,
    REPORT_CARD_REGISTERED,
    REPORT_CARD_RESOURCE_URL,
    REPORT_CARD_URL,
    _async_register_report_card,
    _async_setup_nachtbericht,
)
from custom_components.rejuvenation_bed.nachtbericht_api import (
    TYPE_NACHT,
    TYPE_PHASE,
    richte_webhook_ab,
    richte_webhook_ein,
    verarbeite,
    webhook_pfad,
)
from tests.test_nachtbericht import SpeicherStub, synthetische_nacht

try:
    import aiohttp  # noqa: F401

    HAT_AIOHTTP = True
except ImportError:
    # Im Attrappen-Umfeld (CI pytest-Job) gibt es kein aiohttp — der echte
    # Weg läuft dort im tests_ha-Job gegen ein echtes Home Assistant.
    HAT_AIOHTTP = False


@pytest.fixture(autouse=True)
def webhook_mocks_frisch():
    """Das Modul-Mock aus conftest lebt zwischen Tests weiter — aufräumen."""
    from homeassistant.components import webhook as webhook_modul

    webhook_modul.reset_mock()
    yield
    webhook_modul.reset_mock()


def test_webhook_pfad_ist_relativ_ohne_adresse():
    pfad = webhook_pfad("abc123")
    assert pfad == "/api/webhook/abc123"
    assert "://" not in pfad
    # Keine Adresse, kein Hostname — der Nutzer ergänzt seine eigene URL.
    assert "http" not in pfad


def test_webhook_wird_nur_lokal_registriert():
    """Gesundheitsdaten bleiben im Haus: local_only ist nicht verhandelbar."""
    hass = MagicMock()
    speicher = MagicMock()
    speicher.webhook_id = "bestehend"

    asyncio.run(richte_webhook_ein(hass, speicher))

    from homeassistant.components import webhook as webhook_modul

    webhook_modul.async_register.assert_called_once()
    args, kwargs = webhook_modul.async_register.call_args
    assert args[1] == "rejuvenation_bed"
    assert callable(args[4])
    assert kwargs.get("local_only") is True


def test_webhook_id_bleibt_erhalten_wenn_schon_da():
    hass = MagicMock()
    speicher = MagicMock()
    speicher.webhook_id = "alte-id"

    from homeassistant.components import webhook as webhook_modul

    ergebnis = asyncio.run(richte_webhook_ein(hass, speicher))
    assert ergebnis == "alte-id"
    webhook_modul.async_generate_id.assert_not_called()


def test_webhook_id_wird_einmal_zeugt_und_gespeichert():
    hass = MagicMock()
    stub = SpeicherStub()
    from custom_components.rejuvenation_bed.nachtbericht import NachtberichtSpeicher

    speicher = NachtberichtSpeicher(hass, store=stub)
    from homeassistant.components import webhook as webhook_modul

    webhook_modul.async_generate_id.return_value = "neue-id"
    ergebnis = asyncio.run(richte_webhook_ein(hass, speicher))

    assert ergebnis == "neue-id"
    assert speicher.webhook_id == "neue-id"
    assert stub.gespeichert  # ID liegt dauerhaft im Store


def test_abmelden_gibt_den_endpunkt_frei():
    hass = MagicMock()
    richte_webhook_ab(hass, "weg-damit")

    from homeassistant.components import webhook as webhook_modul

    webhook_modul.async_unregister.assert_called_once_with(hass, "weg-damit")


def test_abmelden_ohne_id_tut_nichts():
    hass = MagicMock()
    richte_webhook_ab(hass, None)

    from homeassistant.components import webhook as webhook_modul

    webhook_modul.async_unregister.assert_not_called()


@pytest.mark.skipif(not HAT_AIOHTTP, reason="aiohttp kommt mit Home Assistant — der echte Weg läuft in tests_ha")
class TestVerarbeitung:
    """Der Handler antwortet begründet — der HA-Webhook schluckt sonst alles."""

    def _request(self, payload):
        request = MagicMock()
        request.json = AsyncMock(return_value=payload)
        return request

    def test_nacht_wird_angenommen(self):
        speicher = MagicMock()
        speicher.async_nacht_annehmen = AsyncMock()
        response = asyncio.run(verarbeite(self._request(synthetische_nacht()), speicher))

        assert response.status == 200
        speicher.async_nacht_annehmen.assert_awaited_once()

    def test_phase_wird_angenommen(self):
        speicher = MagicMock()
        speicher.async_phase_annehmen = AsyncMock()
        payload = {
            "schema": "rejuvenation-bed-night-report-v1",
            "type": TYPE_PHASE,
            "stage": "deep",
            "measured_at": "2026-11-16T01:00:00",
        }
        response = asyncio.run(verarbeite(self._request(payload), speicher))

        assert response.status == 200
        speicher.async_phase_annehmen.assert_awaited_once()

    def test_fehlerhafte_nacht_antwortet_mit_grund(self):
        from custom_components.rejuvenation_bed.nachtbericht import NachtberichtFehler

        speicher = MagicMock()
        speicher.async_nacht_annehmen = AsyncMock(
            side_effect=NachtberichtFehler("night: Datum der Nacht im Format YYYY-MM-DD fehlt")
        )
        response = asyncio.run(verarbeite(self._request({"type": TYPE_NACHT}), speicher))

        assert response.status == 400
        body = json.loads(response.text)
        assert body["ok"] is False
        assert "night" in body["error"]

    def test_unerwarteter_fehler_antwortet_mit_grund_statt_stille(self):
        """Der HA-Webhook schluckt Ausnahmen — der Absender darf nie ein stilles
        200 bekommen, wenn seine Nacht nicht angekommen ist."""
        speicher = MagicMock()
        speicher.async_nacht_annehmen = AsyncMock(side_effect=RuntimeError("kaputt"))
        response = asyncio.run(verarbeite(self._request(synthetische_nacht()), speicher))

        assert response.status == 500
        body = json.loads(response.text)
        assert body["ok"] is False
        assert "RuntimeError" in body["error"]

    def test_unbekannter_typ_wird_abgelehnt(self):
        speicher = MagicMock()
        response = asyncio.run(verarbeite(self._request({"type": "was-anderes"}), speicher))

        assert response.status == 400
        body = json.loads(response.text)
        assert "Unbekannter Typ" in body["error"]

    def test_kaputtes_json_antwortet_mit_grund(self):
        speicher = MagicMock()
        request = MagicMock()
        request.json = AsyncMock(side_effect=RuntimeError("kaputt"))
        response = asyncio.run(verarbeite(request, speicher))

        assert response.status == 400
        assert "kein lesbares JSON" in json.loads(response.text)["error"]

    def test_kein_objekt_wird_abgelehnt(self):
        speicher = MagicMock()
        response = asyncio.run(verarbeite(self._request([1, 2, 3]), speicher))

        assert response.status == 400
        assert "JSON-Objekt" in json.loads(response.text)["error"]


def test_setup_verdrahtet_speicher_mit_coordinator():
    hass = MagicMock()
    coordinator = MagicMock()
    entry = MagicMock()

    with patch("custom_components.rejuvenation_bed.NachtberichtSpeicher") as speicher_cls:
        instanz = speicher_cls.return_value
        instanz.async_laden = AsyncMock()
        asyncio.run(_async_setup_nachtbericht(hass, entry, coordinator))

    assert coordinator.nachtbericht is instanz
    instanz.async_laden.assert_awaited_once()
    assert instanz.benachrichtigen is coordinator.async_update_listeners


def test_setup_fehler_bricht_nichts_ab():
    hass = MagicMock()
    coordinator = MagicMock()
    entry = MagicMock()

    with patch("custom_components.rejuvenation_bed.NachtberichtSpeicher", side_effect=RuntimeError("kaputt")):
        asyncio.run(_async_setup_nachtbericht(hass, entry, coordinator))  # darf nicht werfen

    assert coordinator.nachtbericht is None


# ── Nachtbericht-Karte: Auslieferung wie bei der Nachttisch-Karte ─────────


def _hass():
    hass = MagicMock()
    hass.data = {}
    hass.http.async_register_static_paths = AsyncMock()
    return hass


def _resources(items=()):
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


def test_report_karte_liegt_im_paket():
    card = Path("custom_components/rejuvenation_bed/frontend") / REPORT_CARD_FILENAME
    assert card.is_file()


def test_report_karte_wird_lovelace_ressource():
    hass, res = _hass_mit_lovelace()
    with patch("custom_components.rejuvenation_bed.frontend") as frontend:
        asyncio.run(_async_register_report_card(hass))

    res.async_create_item.assert_awaited_once_with({"res_type": "module", "url": REPORT_CARD_RESOURCE_URL})
    frontend.add_extra_js_url.assert_not_called()
    assert hass.data[REPORT_CARD_REGISTERED] is True


def test_report_karte_yaml_modus_faellt_auf_extra_js():
    hass = _hass()
    with patch("custom_components.rejuvenation_bed.frontend") as frontend:
        asyncio.run(_async_register_report_card(hass))

    frontend.add_extra_js_url.assert_called_once_with(hass, REPORT_CARD_URL)


def test_report_karte_wird_nur_einmal_registriert():
    hass = _hass()
    with patch("custom_components.rejuvenation_bed.frontend") as frontend:
        asyncio.run(_async_register_report_card(hass))
        asyncio.run(_async_register_report_card(hass))

    assert hass.http.async_register_static_paths.await_count == 1
    assert frontend.add_extra_js_url.call_count == 1


def test_report_karte_alter_ressourceneintrag_bekommt_neue_version():
    hass, res = _hass_mit_lovelace([{"id": "1", "url": f"{REPORT_CARD_URL}?v=250101", "res_type": "module"}])
    with patch("custom_components.rejuvenation_bed.frontend"):
        asyncio.run(_async_register_report_card(hass))

    res.async_update_item.assert_awaited_once_with("1", {"url": REPORT_CARD_RESOURCE_URL})


def test_report_karte_fehlende_datei_bricht_nichts_ab():
    hass = _hass()
    with patch("custom_components.rejuvenation_bed.Path") as path_cls:
        path_cls.return_value.parent.__truediv__.return_value.__truediv__.return_value.is_file.return_value = False
        asyncio.run(_async_register_report_card(hass))

    hass.http.async_register_static_paths.assert_not_awaited()
    assert REPORT_CARD_REGISTERED not in hass.data
