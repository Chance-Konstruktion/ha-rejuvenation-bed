"""Tests für die Nachtbericht-Sensoren: ehrlich ohne Daten, präzise mit Daten.

Die Sensoren laufen am echten Coordinator-Schema mit — hier genügt ein
schlanker Doppelgänger, denn geprüft wird, was sie aus dem Nachtbericht-
Speicher lesen, nicht die Coordinator-Mechanik.
"""

import asyncio
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest


# Echte Basisklassen statt Mock, bevor nachtbericht_sensoren importiert wird
# (Muster aus test_sensor_state_class.py / test_nightstand_config.py: zwei
# MagicMocks als Basen werfen einen Metaclass-Konflikt).
class _FakeCoordinatorEntity:
    def __init__(self, coordinator, *args, **kwargs):
        self.coordinator = coordinator


sys.modules["homeassistant"].helpers.update_coordinator.CoordinatorEntity = _FakeCoordinatorEntity
sys.modules["homeassistant.helpers.update_coordinator"].CoordinatorEntity = _FakeCoordinatorEntity
sys.modules["homeassistant"].components.sensor.SensorEntity = type("SensorEntity", (), {})
sys.modules["homeassistant.components.sensor"].SensorEntity = sys.modules[
    "homeassistant"
].components.sensor.SensorEntity

from custom_components.rejuvenation_bed.nachtbericht import (  # noqa: E402
    NachtberichtSpeicher,
    SCHEMA_KENNUNG,
    utc_naiv,
)
from custom_components.rejuvenation_bed.nachtbericht_sensoren import (  # noqa: E402
    MARKER,
    baue_nachtbericht_sensoren,
)
from tests.test_nachtbericht import NACHT, SpeicherStub, synthetische_nacht  # noqa: E402


class PseudoCoordinator:
    """Was die Sensoren am Coordinator brauchen — nichts weiter."""

    def __init__(self, speicher=None):
        self.nachtbericht = speicher
        self.config_entry = types.SimpleNamespace(entry_id="test123")
        self.async_update_listeners = MagicMock()


def _speicher_mit_nacht(**anpassungen):
    stub = SpeicherStub()
    speicher = NachtberichtSpeicher(MagicMock(), store=stub)
    asyncio.run(speicher.async_nacht_annehmen(synthetische_nacht(**anpassungen)))
    return speicher


def _sensor_mit(speicher):
    """Alle Sensoren, gegliedert nach dem Teil nach `nachtbericht_` der ID."""
    coordinator = PseudoCoordinator(speicher)
    return {s._attr_unique_id.split("nachtbericht_")[1]: s for s in baue_nachtbericht_sensoren(coordinator)}


def test_ohne_daten_ist_alles_unknown_nicht_erfunden():
    coordinator = PseudoCoordinator(None)
    sensoren = baue_nachtbericht_sensoren(coordinator)

    for sensor in sensoren:
        if sensor._attr_unique_id.endswith("schlafphase"):
            continue  # die Phase darf ehrlich „unknown" sagen
        assert sensor.native_value is None, sensor._attr_unique_id


def test_ohne_speicher_faellt_phase_auf_unknown():
    coordinator = PseudoCoordinator(None)
    phase = _sensor_mit(None)["schlafphase"]

    assert phase.native_value == "unknown"
    assert "nicht initialisiert" in phase.extra_state_attributes["grund"]


def test_schlafdauer_in_stunden():
    sensoren = _sensor_mit(_speicher_mit_nacht())
    sensor = sensoren["dauer"]

    # 512 Minuten = 8,53 h
    assert sensor.native_value == pytest.approx(8.5, abs=0.1)
    attrs = sensor.extra_state_attributes
    assert attrs["nacht"] == "2026-11-15"
    assert attrs["dauer_minuten"] == pytest.approx(512.0)


def test_phasen_anteile_je_sensor():
    sensoren = _sensor_mit(_speicher_mit_nacht())

    tief = sensoren["anteil_deep"]
    assert tief.stufe == "deep"
    assert tief.native_value == pytest.approx(25.4, abs=0.2)
    assert tief.extra_state_attributes["minuten"] == pytest.approx(130.0)

    wach = sensoren["anteil_awake"]
    assert wach.native_value == pytest.approx(11.7, abs=0.2)


def test_schaetzung_wird_als_warnung_sichtbar():
    sensoren = _sensor_mit(_speicher_mit_nacht())

    anteil = sensoren["anteil_deep"]
    assert "grob geschätzt" in anteil.extra_state_attributes.get("warnung", "")
    guete = sensoren["guete"]
    assert guete.extra_state_attributes["ist_schaetzung"] is True


def test_ruhepuls_als_mittelwert_mit_spanne():
    sensoren = _sensor_mit(_speicher_mit_nacht())
    sensor = sensoren["ruhepuls"]

    assert sensor.native_value == 56
    attrs = sensor.extra_state_attributes
    assert attrs["min"] == 48
    assert attrs["max"] == 74


def test_hrv_zeigt_wert_mit_gueteangaben():
    mit_ibi = {
        "ibi": [
            {
                "t": (datetime(2026, 11, 16, 0, 0) + timedelta(seconds=i)).isoformat(timespec="seconds"),
                "interval_ms": 1000.0 - 20 if i % 2 == 0 else 1000.0 + 20,
            }
            for i in range(150)
        ]
    }
    sensoren = _sensor_mit(_speicher_mit_nacht(**mit_ibi))
    sensor = sensoren["hrv"]

    assert sensor.native_value == pytest.approx(40.0, abs=0.1)
    attrs = sensor.extra_state_attributes
    assert attrs["sdnn"] == pytest.approx(20.0, abs=0.1)
    assert attrs["quelle"].startswith("aus übermittelten IBI")


def test_hrv_ohne_daten_nennt_den_grund_statt_eine_zahl():
    sensoren = _sensor_mit(_speicher_mit_nacht())
    sensor = sensoren["hrv"]

    assert sensor.native_value is None
    attrs = sensor.extra_state_attributes
    assert attrs["status"] == "HRV fehlt"
    assert "keine IBI-Messwerte" in attrs["grund"]


def test_beginn_und_ende_als_zeitstempel():
    sensoren = _sensor_mit(_speicher_mit_nacht())

    beginn = sensoren["start"]
    wert = beginn.native_value
    # Naive Lokalzeit wird als lokale Zeit deklariert (tzinfo gesetzt).
    assert wert.tzinfo is not None
    assert (wert.hour, wert.minute) == (23, 10)
    assert beginn._attr_device_class is not None

    ende = sensoren["end"].native_value
    assert (ende.hour, ende.minute) == (7, 42)


def test_unterbrechungen_als_zaehler():
    sensoren = _sensor_mit(_speicher_mit_nacht())
    sensor = sensoren["unterbrechungen"]

    assert sensor.native_value == 1
    assert sensor.extra_state_attributes["minuten"] == pytest.approx(30.0)
    assert "abgeleitet" in sensor.extra_state_attributes["quelle"]


def test_guete_als_prozent_mit_fehlliste():
    sensoren = _sensor_mit(_speicher_mit_nacht())
    sensor = sensoren["guete"]

    assert 0 < sensor.native_value <= 100
    attrs = sensor.extra_state_attributes
    assert attrs["fehlend"]  # keine IBI → HRV fehlt, benannt
    assert any(f["quelle"] == "HRV" for f in attrs["fehlend"])


def test_bericht_sensor_traegt_markierung_und_annahmepfad():
    speicher = _speicher_mit_nacht()
    speicher.webhook_id = "test-hook-123"
    sensoren = _sensor_mit(speicher)
    sensor = sensoren["bericht"]

    assert sensor.native_value == "2026-11-15"
    attrs = sensor.extra_state_attributes
    assert attrs[MARKER] is True
    # Relativer Pfad — keine Adresse, kein Hostname.
    assert attrs["annahme_pfad"] == "/api/webhook/test-hook-123"
    assert "phasen_verlauf" in attrs
    assert "vergleich" in attrs
    assert "fehlend" in attrs


def test_bericht_sensor_ohne_nacht_nennt_still_den_weg():
    stub = SpeicherStub()
    speicher = NachtberichtSpeicher(MagicMock(), store=stub)
    speicher.webhook_id = "leer-hook"
    sensoren = _sensor_mit(speicher)
    sensor = sensoren["bericht"]

    assert sensor.native_value is None
    attrs = sensor.extra_state_attributes
    assert "Nacht" in attrs["status"]
    assert attrs["annahme_pfad"] == "/api/webhook/leer-hook"


def test_phase_sensor_zeigt_frische_phase():
    speicher = _speicher_mit_nacht()
    import asyncio as aio

    aio.run(
        speicher.async_phase_annehmen(
            {
                "schema": SCHEMA_KENNUNG,
                "type": "phase_update",
                "stage": "deep",
                "confidence": 0.8,
                "coverage": 0.9,
                "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source": "estimate",
                "algorithm": "puls-bewegung-grob-0.1",
            }
        )
    )
    sensor = _sensor_mit(speicher)["schlafphase"]

    assert sensor.native_value == "deep"
    attrs = sensor.extra_state_attributes
    assert attrs["algorithm"] == "puls-bewegung-grob-0.1"
    assert "grobe Schätzung" in attrs["quelle_text"]


def test_phase_sensor_faellt_nach_verfall_auf_unknown():
    speicher = _speicher_mit_nacht()
    import asyncio as aio

    alt = datetime.now(timezone.utc) - timedelta(minutes=30)
    aio.run(
        speicher.async_phase_annehmen(
            {
                "schema": SCHEMA_KENNUNG,
                "type": "phase_update",
                "stage": "rem",
                "measured_at": alt.isoformat(timespec="seconds"),
            }
        )
    )
    sensor = _sensor_mit(speicher)["schlafphase"]

    assert sensor.native_value == "unknown"
    assert "Minuten alt" in sensor.extra_state_attributes["grund"]


def test_siebzehn_sensoren_kommen_alle_zuruck():
    coordinator = PseudoCoordinator()
    sensoren = baue_nachtbericht_sensoren(coordinator)

    namen = [s._attr_name for s in sensoren]
    # 1 Phase + 1 Dauer + 4 Anteile + 1 Puls + 1 HRV + 2 Grenzen
    # + 1 Unterbrechungen + 1 Güte + 1 Schritte + 3 Kanäle + 1 Bericht
    assert len(sensoren) == 17
    assert "Bett Schlafphase" in namen
    assert "Bett Nachtbericht" in namen
    for name in ("Bett Tiefschlaf-Anteil", "Bett Leichtschlaf-Anteil", "Bett REM-Anteil", "Bett Wach-Anteil"):
        assert name in namen
    # Neu mit dem Schalter „Was geht an Home Assistant“: Schritte und die drei
    # Kanäle, die die Uhr nur sendet, wenn sie sie wirklich liefert.
    for name in ("Bett Schritte", "Bett Atemfrequenz", "Bett Sauerstoffsättigung", "Bett Hauttemperatur"):
        assert name in namen
    # Alle hängen am Schlaf/Analyse-Gerät und haben eine feste Entity-ID.
    for s in sensoren:
        assert s._attr_unique_id.startswith("test123_nachtbericht_")


# ── Schritte und die drei Kanäle (Schalter „Was geht an Home Assistant“) ────


def test_schritte_lesen_den_bericht():
    # Die Grund-Nacht der Mock-Suite bringt keine Bewegung mit — hier geht sie
    # ausdrücklich hinein (synthetisch, wie alles in dieser Suite).
    sensoren = _sensor_mit(_speicher_mit_nacht(movement={"steps_total": 41}))
    sensor = sensoren["schritte"]

    # Die synthetische Nacht meldet steps_total 41.
    assert sensor.native_value == 41
    attrs = sensor.extra_state_attributes
    assert attrs["nacht"] == NACHT


def test_schritte_ohne_bewegung_sind_unknown_nicht_null():
    speicher = _speicher_mit_nacht(movement=None)
    nacht = speicher.letzte_nacht()
    nacht["bewegung"] = None
    sensor = _sensor_mit(speicher)["schritte"]

    assert sensor.native_value is None
    assert "Keine Bewegungsdaten" in sensor.extra_state_attributes["status"]


def test_kanale_sind_unverfuegbar_mit_grund_solang_nichts_kommt():
    # Vor der ersten Nacht: der Kanal ist ehrlich nicht verfügbar, der Grund
    # benannt — nie eine Zahl aus dem Puls abgeleitet.
    sensoren = _sensor_mit(None)
    for schluessel in ("kanal_respiratory_rate", "kanal_spo2", "kanal_skin_temperature"):
        sensor = sensoren[schluessel]
        assert sensor.available is False, schluessel
        assert sensor.native_value is None, schluessel
        assert sensor.extra_state_attributes["grund"], schluessel


def test_kanale_bekommen_den_grund_vom_absender():
    speicher = _speicher_mit_nacht(
        channels={
            "respiratory_rate": {"provided": False, "reason": "die Uhr stellt keinen Atemfrequenz-Kanal bereit"},
            "spo2": {"provided": False, "reason": "die Uhr stellt keinen SpO2-Kanal bereit"},
            "skin_temperature": {"provided": False, "reason": "die Uhr stellt keinen Hauttemperatur-Kanal bereit"},
        }
    )
    sensoren = _sensor_mit(speicher)

    spo2 = sensoren["kanal_spo2"]
    assert spo2.available is False
    assert "SpO2-Kanal" in spo2.extra_state_attributes["grund"]

    atem = sensoren["kanal_respiratory_rate"]
    assert "Atemfrequenz-Kanal" in atem.extra_state_attributes["grund"]


def test_gelieferter_kanal_ist_ein_normaler_messwert():
    speicher = _speicher_mit_nacht(
        channels={"spo2": {"provided": True, "mean": 97.4, "min": 95.0, "max": 99.0, "source": "echt"}}
    )
    sensoren = _sensor_mit(speicher)

    spo2 = sensoren["kanal_spo2"]
    assert spo2.available is True
    assert spo2.native_value == pytest.approx(97.4)
    assert spo2.extra_state_attributes["quelle"] == "echt"
    assert spo2.extra_state_attributes["min"] == 95.0


def test_hauttemperatur_traegt_die_temperaturklasse():
    from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
    from homeassistant.const import UnitOfTemperature

    sensoren = _sensor_mit(None)
    haut = sensoren["kanal_skin_temperature"]
    assert haut._attr_device_class == SensorDeviceClass.TEMPERATURE
    assert haut._attr_state_class == SensorStateClass.MEASUREMENT
    assert haut._attr_native_unit_of_measurement == UnitOfTemperature.CELSIUS


def test_kanalsensoren_haben_feste_ids():
    sensoren = _sensor_mit(None)
    assert sensoren["kanal_respiratory_rate"]._attr_unique_id.endswith("kanal_respiratory_rate")
    assert sensoren["kanal_spo2"]._attr_unique_id.endswith("kanal_spo2")
    assert sensoren["kanal_skin_temperature"]._attr_unique_id.endswith("kanal_skin_temperature")
