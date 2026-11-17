"""Tests für die Gesamtdaten-Annahme: night_data-Pakete, Schalterstellung, Kanäle.

Die Stellung „Gesamtdaten“ des Schalters „Was geht an Home Assistant“ schickt
die Messreihen der Nacht je 5 Minuten als Paket. Hier wird festgeklemmt:
dieselbe Reihe zweimal doppelt nicht (Zeitstempel als Schlüssel), die
Schalterstellung kommt in jeder Nutzlast mit, fehlende Kanäle werden benannt
statt erfunden, und das Protokoll zählt, es liest keine Werte.
"""

import asyncio
import logging
from unittest.mock import MagicMock

import pytest

from custom_components.rejuvenation_bed.nachtbericht import (
    MODUS_GESAMT,
    MODUS_PHASE,
    NachtberichtFehler,
    NachtberichtSpeicher,
    SCHEMA_KENNUNG,
)
from tests.test_nachtbericht import SpeicherStub, synthetische_nacht

NACHT = "2026-11-15"


def paket(**anpassungen):
    """Ein synthetisches 5-Minuten-Paket — wiederverwendbar."""
    basis = {
        "schema": SCHEMA_KENNUNG,
        "type": "night_data",
        "night": NACHT,
        "modus": MODUS_GESAMT,
        "pulse": {
            "samples": [
                {"t": "2026-11-15T23:10:30", "bpm": 57.3},
                {"t": "2026-11-15T23:12:30", "bpm": 61.1},
            ]
        },
        "ibi": [
            {"t": "2026-11-15T23:10:40", "interval_ms": 1020.0, "quality": 0.9},
        ],
        "movement": {
            "windows": [{"t": "2026-11-15T23:14:00", "steps": 7}],
        },
        "platform": [{"t": "2026-11-15T23:10:00", "state": "ASLEEP"}],
    }
    basis.update(anpassungen)
    return basis


def neuer_speicher():
    return NachtberichtSpeicher(MagicMock(), store=SpeicherStub())


# ── Annahme der Pakete ─────────────────────────────────────────────────────


def test_paket_wird_angenommen_und_gezaehlt():
    speicher = neuer_speicher()
    erg = asyncio.run(speicher.async_daten_annehmen(paket()))
    assert erg["nacht"] == NACHT
    assert erg["puls"] == 2
    assert erg["ibi"] == 1
    assert erg["bewegung"] == 1
    assert erg["plattform"] == 1
    reihe = speicher.messreihen[NACHT]
    assert len(reihe["pulse"]) == 2
    assert len(reihe["ibi"]) == 1
    assert len(reihe["movement"]) == 1
    assert len(reihe["platform"]) == 1


def test_gleiches_paket_doppelt_keine_doppelung():
    speicher = neuer_speicher()
    asyncio.run(speicher.async_daten_annehmen(paket()))
    erg = asyncio.run(speicher.async_daten_annehmen(paket()))
    # Wiederholung: nichts kommt dazu — der Zeitstempel ist der Schlüssel.
    assert erg["puls"] == 0 and erg["ibi"] == 0 and erg["bewegung"] == 0 and erg["plattform"] == 0
    assert len(speicher.messreihen[NACHT]["pulse"]) == 2


def test_weitere_punkte_erweitern_ohne_doppelung():
    speicher = neuer_speicher()
    asyncio.run(speicher.async_daten_annehmen(paket()))
    asyncio.run(
        speicher.async_daten_annehmen(
            paket(
                pulse={"samples": [{"t": "2026-11-15T23:16:30", "bpm": 54.9}]}, ibi=None, movement=None, platform=None
            )
        )
    )
    assert len(speicher.messreihen[NACHT]["pulse"]) == 3


def test_unplausibler_puls_bricht_mit_grund_wie_im_bericht():
    # Dieselbe fail-closed-Regel wie beim Nachtbericht: außerhalb des
    # plausiblen Bereichs wird das Paket abgelehnt, mit Grund an den Absender.
    speicher = neuer_speicher()
    with pytest.raises(NachtberichtFehler, match="plausib"):
        asyncio.run(
            speicher.async_daten_annehmen(
                paket(
                    pulse={"samples": [{"t": "2026-11-15T23:10:30", "bpm": 300.0}]},
                    ibi=None,
                    movement=None,
                    platform=None,
                )
            )
        )
    assert NACHT not in speicher.messreihen or len(speicher.messreihen.get(NACHT, {}).get("pulse", {})) == 0


def test_unbekannter_plattform_zustand_wird_abgelehnt():
    speicher = neuer_speicher()
    with pytest.raises(NachtberichtFehler, match="unbekannter Zustand"):
        asyncio.run(
            speicher.async_daten_annehmen(
                paket(pulse=None, ibi=None, movement=None, platform=[{"t": "2026-11-15T23:10:00", "state": "TRÄUMT"}])
            )
        )


def test_leeres_paket_bricht_mit_grund():
    speicher = neuer_speicher()
    with pytest.raises(NachtberichtFehler, match="keine Reihen"):
        asyncio.run(speicher.async_daten_annehmen(paket(pulse=None, ibi=None, movement=None, platform=None)))


def test_falscher_typ_und_falsches_datum_brechen():
    speicher = neuer_speicher()
    with pytest.raises(NachtberichtFehler, match="night_data"):
        asyncio.run(speicher.async_daten_annehmen(paket(type="night_report")))
    with pytest.raises(NachtberichtFehler, match="night"):
        asyncio.run(speicher.async_daten_annehmen(paket(night="15.11.2026")))


def test_unbekannter_modus_bricht():
    speicher = neuer_speicher()
    with pytest.raises(NachtberichtFehler, match="modus"):
        asyncio.run(speicher.async_daten_annehmen(paket(modus="alles")))


# ── Zusammenspiel mit dem Nachtbericht ─────────────────────────────────────


def test_bericht_nach_paketen_bekommt_pulskurve():
    speicher = neuer_speicher()
    asyncio.run(speicher.async_daten_annehmen(paket()))
    asyncio.run(speicher.async_nacht_annehmen(synthetische_nacht()))
    bericht = speicher.letzte_nacht()
    # Der Bericht trägt seine eigenen Samples; die Pakete liefern die Kurve
    # nur, wenn der Bericht selbst keine hat — hier hat er welche.
    assert bericht["puls"]["punkte"], "die Bericht-Samples bleiben die Kurve"


def test_pulskurve_aus_paketen_wenn_bericht_keine_hat():
    speicher = neuer_speicher()
    ohne_samples = synthetische_nacht()
    ohne_samples["pulse"] = {"min": 48, "mean": 56, "max": 74}
    asyncio.run(speicher.async_daten_annehmen(paket()))
    asyncio.run(speicher.async_nacht_annehmen(ohne_samples))
    bericht = speicher.letzte_nacht()
    assert bericht["puls"]["punkte"], "die Kurve kommt aus den Paketen"
    assert bericht["puls"]["punkte_quelle"] == "aus den übermittelten Gesamtdaten-Paketen"
    assert bericht["puls"]["mean"] == 56  # die Zusammenfassung des Absenders bleibt


def test_paket_nach_bericht_ergaenzt_kurve():
    speicher = neuer_speicher()
    ohne_samples = synthetische_nacht()
    ohne_samples["pulse"] = {"min": 48, "mean": 56, "max": 74}
    asyncio.run(speicher.async_nacht_annehmen(ohne_samples))
    asyncio.run(speicher.async_daten_annehmen(paket()))
    bericht = speicher.letzte_nacht()
    assert bericht["puls"]["punkte"]
    assert bericht["messreihen"]["puls"] == 2


def test_messreihen_summary_stellt_transparenz_bereit():
    speicher = neuer_speicher()
    asyncio.run(speicher.async_daten_annehmen(paket()))
    asyncio.run(speicher.async_nacht_annehmen(synthetische_nacht()))
    bericht = speicher.letzte_nacht()
    assert bericht["messreihen"] == {"puls": 2, "ibi": 1, "bewegung": 1, "plattform": 1, "modus": MODUS_PHASE}


# ── Schalterstellung in jeder Nutzlast ─────────────────────────────────────


def test_modus_im_nachtbericht_wird_gespeichert():
    speicher = neuer_speicher()
    nacht = synthetische_nacht()
    nacht["modus"] = MODUS_GESAMT
    asyncio.run(speicher.async_nacht_annehmen(nacht))
    assert speicher.letzte_nacht()["modus"] == MODUS_GESAMT


def test_modus_fehlt_heisst_enge_stellung():
    speicher = neuer_speicher()
    nacht = synthetische_nacht()
    nacht.pop("modus", None)
    asyncio.run(speicher.async_nacht_annehmen(nacht))
    assert speicher.letzte_nacht()["modus"] == MODUS_PHASE


def test_modus_phase_update_wird_geprueft():
    speicher = neuer_speicher()
    payload = {
        "schema": SCHEMA_KENNUNG,
        "type": "phase_update",
        "stage": "deep",
        "measured_at": "2026-11-16T01:30:00+01:00",
        "modus": "murks",
    }
    with pytest.raises(NachtberichtFehler, match="modus"):
        asyncio.run(speicher.async_phase_annehmen(payload))


# ── Kanäle: nur, wenn die Uhr sie wirklich liefert ─────────────────────────


def test_kanale_ohne_lieferung_sind_benannt():
    speicher = neuer_speicher()
    nacht = synthetische_nacht()
    nacht["channels"] = {
        "respiratory_rate": {"provided": False, "reason": "die Uhr stellt keinen Atemfrequenz-Kanal bereit"},
        "spo2": {"provided": False, "reason": "die Uhr stellt keinen SpO2-Kanal bereit"},
        "skin_temperature": {"provided": False, "reason": "die Uhr stellt keinen Hauttemperatur-Kanal bereit"},
    }
    asyncio.run(speicher.async_nacht_annehmen(nacht))
    kanale = speicher.letzte_nacht()["kanale"]
    assert kanale["spo2"]["provided"] is False
    assert "SpO2" in kanale["spo2"]["grund"]


def test_kanal_ohne_grund_bricht():
    speicher = neuer_speicher()
    nacht = synthetische_nacht()
    nacht["channels"] = {"spo2": {"provided": False}}
    with pytest.raises(NachtberichtFehler, match="Grund"):
        asyncio.run(speicher.async_nacht_annehmen(nacht))


def test_gelieferter_kanal_wird_geprueft():
    speicher = neuer_speicher()
    nacht = synthetische_nacht()
    nacht["channels"] = {"spo2": {"provided": True, "mean": 97.4, "min": 95.0, "max": 99.0, "source": "echt"}}
    asyncio.run(speicher.async_nacht_annehmen(nacht))
    kanal = speicher.letzte_nacht()["kanale"]["spo2"]
    assert kanal["mean"] == 97.4
    assert kanal["quelle"] == "echt"


def test_gelieferter_kanal_ohne_mittelwert_bricht():
    speicher = neuer_speicher()
    nacht = synthetische_nacht()
    nacht["channels"] = {"spo2": {"provided": True}}
    with pytest.raises(NachtberichtFehler, match="Mittelwert"):
        asyncio.run(speicher.async_nacht_annehmen(nacht))


def test_wert_auserhalb_der_plausibilitaet_bricht():
    speicher = neuer_speicher()
    nacht = synthetische_nacht()
    nacht["channels"] = {"spo2": {"provided": True, "mean": 42.0}}
    with pytest.raises(NachtberichtFehler, match="plausib"):
        asyncio.run(speicher.async_nacht_annehmen(nacht))


# ── HRV-Grund des Absenders ────────────────────────────────────────────────


def test_hrv_grund_des_absenders_steht_im_bericht():
    speicher = neuer_speicher()
    nacht = synthetische_nacht()
    nacht.pop("ibi", None)
    nacht.pop("hrv", None)
    nacht["hrv_grund"] = "zu wenige brauchbare IBI (42 von mindestens 120)"
    asyncio.run(speicher.async_nacht_annehmen(nacht))
    assert speicher.letzte_nacht()["hrv_grund"] == "zu wenige brauchbare IBI (42 von mindestens 120)"
    fehlend = [f for f in speicher.letzte_nacht()["fehlend"] if f["quelle"] == "HRV"]
    assert fehlend and "42" in fehlend[0]["grund"]


# ── Protokoll zählt, liest keine Werte ─────────────────────────────────────


def test_protokoll_zaehlt_ohne_werte(caplog):
    speicher = neuer_speicher()
    with caplog.at_level(logging.INFO, logger="custom_components.rejuvenation_bed.nachtbericht"):
        asyncio.run(speicher.async_daten_annehmen(paket()))
    zeilen = [r.getMessage() for r in caplog.records]
    assert any("Messreihen Nacht" in z for z in zeilen)
    for zeile in zeilen:
        # Synthetische Werte mit unverkennbaren Nachkommastellen dürfen nie im
        # Protokoll stehen — die Zeile zählt, sie liest nichts.
        assert "57.3" not in zeile
        assert "61.1" not in zeile
        assert "1020.0" not in zeile
