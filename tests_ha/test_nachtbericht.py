"""Nachtbericht gegen ein echtes Home Assistant.

Der Weg, der zählt: synthetische Nacht als JSON an den lokalen Webhook
posten — danach stehen die Sensoren im Zustandspeicher, das Ereignis ist
gefeuert, und die Karte hat ihre Daten. Alles synthetisch; es fließen keine
echten Gesundheitsdaten.
"""

from datetime import datetime, timedelta

from homeassistant.components import webhook
from homeassistant.core import Event
from homeassistant.util import dt as dt_util

from custom_components.rejuvenation_bed.const import DOMAIN
from custom_components.rejuvenation_bed.nachtbericht import (
    EVENT_NACHT_ABGESCHLOSSEN,
    SCHEMA_KENNUNG,
)

from tests_ha.conftest import FUEHLER

NACHT = "2026-11-15"


def synthetische_nacht():
    """Die synthetische Nacht: 23:10 bis 07:42, grob geschätzte Phasen, Puls, IBI."""
    start = f"{NACHT}T23:10:00"
    return {
        "schema": SCHEMA_KENNUNG,
        "type": "night_report",
        "night": NACHT,
        "start": start,
        "end": "2026-11-16T07:42:00",
        "device": "galaxy-watch-4",
        "phases": [
            {"stage": "awake", "start": "2026-11-15T23:10:00", "end": "2026-11-15T23:40:00", "source": "platform", "confidence": 0.9},
            {"stage": "light", "start": "2026-11-15T23:40:00", "end": "2026-11-16T00:20:00", "source": "estimate", "confidence": 0.8},
            {"stage": "deep", "start": "2026-11-16T00:20:00", "end": "2026-11-16T02:30:00", "source": "estimate", "confidence": 0.8},
            {"stage": "rem", "start": "2026-11-16T02:30:00", "end": "2026-11-16T03:00:00", "source": "estimate", "confidence": 0.75},
            {"stage": "light", "start": "2026-11-16T03:00:00", "end": "2026-11-16T05:30:00", "source": "estimate", "confidence": 0.8},
            {"stage": "rem", "start": "2026-11-16T05:30:00", "end": "2026-11-16T06:10:00", "source": "estimate", "confidence": 0.75},
            {"stage": "awake", "start": "2026-11-16T06:10:00", "end": "2026-11-16T06:40:00", "source": "estimate", "confidence": 0.85},
            {"stage": "light", "start": "2026-11-16T06:40:00", "end": "2026-11-16T07:42:00", "source": "estimate", "confidence": 0.8},
        ],
        "pulse": {
            "min": 48,
            "mean": 56,
            "max": 74,
            "coverage": 0.94,
            "samples": [
                {"t": (datetime(2026, 11, 15, 23, 10) + timedelta(minutes=10 * i)).isoformat(timespec="seconds"), "bpm": 50 + (i % 18)}
                for i in range(32)
            ],
        },
        "ibi": [
            {
                "t": (datetime(2026, 11, 16, 0, 0) + timedelta(seconds=i)).isoformat(timespec="seconds"),
                "interval_ms": 980.0 if i % 2 == 0 else 1020.0,
            }
            for i in range(150)
        ],
        "movement": {"steps_total": 41},
    }


async def _webhook_id(hass, entry) -> str:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    return coordinator.nachtbericht.webhook_id


async def test_synthetiche_nacht_kommt_vollstaendig_an(hass, bett, hass_client):
    """POST an den lokalen Webhook → Sensoren, Ereignis, Bericht. Alles echt."""
    gefeuert = []

    def _hoere(ereignis: Event) -> None:
        gefeuert.append(ereignis)

    hass.bus.async_listen(EVENT_NACHT_ABGESCHLOSSEN, _hoere)

    client = await hass_client()
    webhook_id = await _webhook_id(hass, bett)
    response = await client.post(f"/api/webhook/{webhook_id}", json=synthetische_nacht())
    assert response.status == 200
    assert (await response.json())["ok"] is True

    await hass.async_block_till_done()

    # Die Sensoren stehen im Zustandspeicher — nicht behauptet, sondern da.
    dauer = hass.states.get("sensor.bett_schlafdauer")
    assert dauer is not None
    assert float(dauer.state) == 8.5
    assert dauer.attributes["nacht"] == NACHT

    tief = hass.states.get("sensor.bett_tiefschlaf_anteil")
    assert tief is not None
    assert float(tief.state) == 25.4

    ruhepuls = hass.states.get("sensor.bett_ruhepuls")
    assert ruhepuls is not None
    assert float(ruhepuls.state) == 56
    assert ruhepuls.attributes["min"] == 48

    hrv = hass.states.get("sensor.bett_hrv")
    assert hrv is not None
    assert float(hrv.state) == 40.0  # aus den 150 synthetischen IBI gerechnet
    assert hrv.attributes["sdnn"] == 20.0

    unterbrechungen = hass.states.get("sensor.bett_schlafunterbrechungen")
    assert unterbrechungen is not None
    assert float(unterbrechungen.state) == 1.0

    guete = hass.states.get("sensor.bett_nachtgute")
    assert guete is not None
    assert 0 < float(guete.state) <= 100
    assert guete.attributes["ist_schaetzung"] is True

    beginn = hass.states.get("sensor.bett_schlafbeginn")
    assert beginn is not None

    bericht = hass.states.get("sensor.bett_nachtbericht")
    assert bericht is not None
    assert bericht.state == NACHT
    assert bericht.attributes["rejuvenation_nachtbericht"] is True
    assert bericht.attributes["annahme_pfad"] == f"/api/webhook/{webhook_id}"
    assert len(bericht.attributes["phasen_verlauf"]) == 8

    # Das Ereignis „Nacht abgeschlossen" wurde auf dem echten Bus gefeuert.
    assert len(gefeuert) == 1
    assert gefeuert[0].event_type == EVENT_NACHT_ABGESCHLOSSEN
    assert gefeuert[0].data["nacht"] == NACHT
    assert gefeuert[0].data["ist_schaetzung"] is True


async def test_laufende_phase_landet_im_sensor_fuer_automationen(hass, bett, hass_client):
    """phase_update → sensor.bett_schlafphase trägt die Phase samt Quelle."""
    client = await hass_client()
    webhook_id = await _webhook_id(hass, bett)

    payload = {
        "schema": SCHEMA_KENNUNG,
        "type": "phase_update",
        "stage": "deep",
        "confidence": 0.8,
        "coverage": 0.9,
        "measured_at": dt_util.now().isoformat(timespec="seconds"),
        "source": "estimate",
        "algorithm": "puls-bewegung-grob-0.1",
    }
    response = await client.post(f"/api/webhook/{webhook_id}", json=payload)
    assert response.status == 200
    await hass.async_block_till_done()

    phase = hass.states.get("sensor.bett_schlafphase")
    assert phase is not None
    assert phase.state == "deep"
    assert phase.attributes["algorithm"] == "puls-bewegung-grob-0.1"
    assert "grobe Schätzung" in phase.attributes["quelle_text"]


async def test_veraltete_phase_faellt_auf_unknown(hass, bett, hass_client):
    """Ohne Nachschub verschwindet die Phase — das Bett schaltet dann nach Kurve."""
    client = await hass_client()
    webhook_id = await _webhook_id(hass, bett)

    alt = dt_util.now() - timedelta(minutes=45)
    payload = {
        "schema": SCHEMA_KENNUNG,
        "type": "phase_update",
        "stage": "rem",
        "measured_at": alt.isoformat(timespec="seconds"),
    }
    await client.post(f"/api/webhook/{webhook_id}", json=payload)
    await hass.async_block_till_done()

    phase = hass.states.get("sensor.bett_schlafphase")
    assert phase is not None
    assert phase.state == "unknown"


async def test_fehlerhafte_nacht_wird_mit_grund_abgelehnt(hass, bett, hass_client):
    """Ein kaputter Übertrag bekommt eine begründete 400 — nichts wird still geschluckt."""
    client = await hass_client()
    webhook_id = await _webhook_id(hass, bett)

    kaputt = synthetische_nacht()
    kaputt["night"] = "15.11.2026"
    response = await client.post(f"/api/webhook/{webhook_id}", json=kaputt)
    assert response.status == 400
    body = await response.json()
    assert body["ok"] is False
    assert "night" in body["error"]

    # Nichts angekommen: Der Zustand bleibt unknown, kein halber Bericht.
    dauer = hass.states.get("sensor.bett_schlafdauer")
    assert dauer is not None
    assert dauer.state == "unknown"


async def test_zweite_nacht_baut_den_vergleich(hass, bett, hass_client):
    """Nach zwei Nächten trägt der Bericht den Vergleich — Karte hat ihr 7-Tage-Feld."""
    client = await hass_client()
    webhook_id = await _webhook_id(hass, bett)

    zweite = synthetische_nacht()
    zweite["night"] = "2026-11-16"
    zweite["start"] = "2026-11-16T23:05:00"
    zweite["end"] = "2026-11-17T07:30:00"

    await client.post(f"/api/webhook/{webhook_id}", json=synthetische_nacht())
    await hass.async_block_till_done()
    await client.post(f"/api/webhook/{webhook_id}", json=zweite)
    await hass.async_block_till_done()

    bericht = hass.states.get("sensor.bett_nachtbericht")
    assert bericht.state == "2026-11-16"
    vergleich = bericht.attributes["vergleich"]
    assert len(vergleich) == 1
    assert vergleich[0]["nacht"] == NACHT
