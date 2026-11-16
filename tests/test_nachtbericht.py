"""Tests für den Nachtbericht — die Schlafaufzeichnung der Uhr in HA.

Synthetische Nacht (ausdrücklich keine echten Daten): 23:10 bis 07:42,
Phasen-Zeitleiste mit grober Schätzung, Puls-Verlauf, IBI für die HRV.
Alles, was die Ehrlichkeitsregeln des Moduls versprechen, wird hier
festgeklemmt: fehlende Quellen werden benannt, nie ersetzt; grobe Schätzung
bleibt sichtbar; unplausible Werte fliegen raus statt geraten zu werden.
"""

import statistics
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from custom_components.rejuvenation_bed.nachtbericht import (
    EVENT_NACHT_ABGESCHLOSSEN,
    MAX_NAECHTE,
    Nachtbericht,
    NachtberichtFehler,
    NachtberichtSpeicher,
    SCHEMA_KENNUNG,
    utc_naiv,
    baue_nachtbericht,
    hrv_aus_ibi,
    quell_kurz,
    quell_text,
)

NACHT = "2026-11-15"
START = "2026-11-15T23:10:00"
ENDE = "2026-11-16T07:42:00"


def synthetische_nacht(**anpassungen):
    """Die synthetische Nacht — wiederverwendbar, mit Anpass-Punkten."""
    payload = {
        "schema": SCHEMA_KENNUNG,
        "type": "night_report",
        "night": NACHT,
        "start": START,
        "end": ENDE,
        "device": "galaxy-watch-4",
        "phases": [
            {
                "stage": "awake",
                "start": "2026-11-15T23:10:00",
                "end": "2026-11-15T23:40:00",
                "source": "platform",
                "confidence": 0.9,
            },
            {
                "stage": "light",
                "start": "2026-11-15T23:40:00",
                "end": "2026-11-16T00:20:00",
                "source": "estimate",
                "confidence": 0.8,
            },
            {
                "stage": "deep",
                "start": "2026-11-16T00:20:00",
                "end": "2026-11-16T02:30:00",
                "source": "estimate",
                "confidence": 0.8,
            },
            {
                "stage": "rem",
                "start": "2026-11-16T02:30:00",
                "end": "2026-11-16T03:00:00",
                "source": "estimate",
                "confidence": 0.75,
            },
            {
                "stage": "light",
                "start": "2026-11-16T03:00:00",
                "end": "2026-11-16T05:30:00",
                "source": "estimate",
                "confidence": 0.8,
            },
            {
                "stage": "rem",
                "start": "2026-11-16T05:30:00",
                "end": "2026-11-16T06:10:00",
                "source": "estimate",
                "confidence": 0.75,
            },
            {
                "stage": "awake",
                "start": "2026-11-16T06:10:00",
                "end": "2026-11-16T06:40:00",
                "source": "estimate",
                "confidence": 0.85,
            },
            {
                "stage": "light",
                "start": "2026-11-16T06:40:00",
                "end": "2026-11-16T07:42:00",
                "source": "estimate",
                "confidence": 0.8,
            },
        ],
        "pulse": {"min": 48, "mean": 56, "max": 74, "coverage": 0.94},
    }
    payload.update(anpassungen)
    return payload


# ═══════════════════════════════════════════════════════════════════════════════
# SYNTHETISCHE NACHT — GRUNDKENNZAHLEN
# ═══════════════════════════════════════════════════════════════════════════════


def test_synthese_nacht_grundkennzahlen():
    bericht = baue_nachtbericht(synthetische_nacht())

    assert bericht.nacht == NACHT
    # 23:10 bis 07:42 = 8 h 32 min
    assert bericht.dauer_minuten == pytest.approx(512.0)
    assert bericht.geraet == "galaxy-watch-4"


def test_anteile_je_phase_aus_der_zeitleiste():
    bericht = baue_nachtbericht(synthetische_nacht())
    anteile = bericht.anteile_prozent

    # Tief: 00:20 bis 02:30 = 130 min von 512
    assert anteile["deep"] == pytest.approx(130 / 512 * 100, abs=0.1)
    # Wach: 30 + 30 = 60 min
    assert anteile["awake"] == pytest.approx(60 / 512 * 100, abs=0.1)
    # REM: 30 + 40 = 70 min
    assert anteile["rem"] == pytest.approx(70 / 512 * 100, abs=0.1)
    assert sum(anteile.values()) == pytest.approx(100.0, abs=0.2)


def test_luecke_wird_gezaehlt_nicht_ausgefuellt():
    ohne_tief = synthetische_nacht()
    ohne_tief["phases"] = [s for s in ohne_tief["phases"] if s["stage"] != "deep"]
    bericht = baue_nachtbericht(ohne_tief)

    assert bericht.luecken_minuten == pytest.approx(130.0)
    assert bericht.anteile_prozent["deep"] == 0.0


def test_guete_liegt_mit_konfidenz_und_abdeckung():
    bericht = baue_nachtbericht(synthetische_nacht())
    assert 0.0 <= bericht.guete <= 100.0
    # Konfidenzen um 0.8 → Güte unter 100, aber über „unbrauchbar“.
    assert 50.0 < bericht.guete < 95.0


def test_guete_ohne_phasen_ist_null():
    ohne_phasen = synthetische_nacht(phases=[])
    bericht = baue_nachtbericht(ohne_phasen)

    assert bericht.guete == 0.0
    assert any(f["quelle"] == "Schlafphasen" for f in bericht.fehlend)


# ═══════════════════════════════════════════════════════════════════════════════
# EHRLICHKEIT: QUELLEN UND FEHLENDE WERTE
# ═══════════════════════════════════════════════════════════════════════════════


def test_grobe_schaetzung_bleibt_sichtbar():
    bericht = baue_nachtbericht(synthetische_nacht())

    assert bericht.ist_schaetzung is True
    assert any("grobe Schätzung" in q for q in bericht.quellen)
    assert quell_kurz("estimate") == "grobe Schätzung"
    assert quell_text("platform") == "Plattform-Schlafstatus (schläft/wach)"


def test_bericht_traegt_quelle_pro_segment():
    bericht = baue_nachtbericht(synthetische_nacht())
    erster = bericht.bericht()["phasen_verlauf"][0]

    assert erster["quelle"] == "platform"
    assert erster["quelle_text"] == "Plattform-Schlafstatus (schläft/wach)"
    assert erster["confidence"] == 0.9


def test_ohne_ibi_steht_die_hrv_als_fehlend_da():
    bericht = baue_nachtbericht(synthetische_nacht())

    assert bericht.hrv is None
    assert "wird nicht gerechnet, nicht geraten" in bericht.hrv_grund
    assert any(f["quelle"] == "HRV" for f in bericht.fehlend)
    ausgabe = bericht.bericht()
    assert ausgabe["hrv_grund"] == bericht.hrv_grund


def test_ohne_puls_und_ohne_bewegung_bleibt_es_beim_benennen():
    nackter = synthetische_nacht(pulse=None, movement=None)
    bericht = baue_nachtbericht(nackter)

    fehlende_quellen = [f["quelle"] for f in bericht.fehlend]
    assert "Puls" in fehlende_quellen
    assert "Bewegung" in fehlende_quellen
    assert bericht.puls is None


def test_geringe_puls_abdeckung_wird_genannt():
    duenn = synthetische_nacht(pulse={"min": 50, "mean": 55, "max": 60, "coverage": 0.3})
    bericht = baue_nachtbericht(duenn)

    assert any(f["quelle"] == "Puls-Abdeckung" for f in bericht.fehlend)


# ═══════════════════════════════════════════════════════════════════════════════
# PULS
# ═══════════════════════════════════════════════════════════════════════════════


def test_puls_aggregate_werden_aus_samples_zusammengefasst():
    basis = datetime(2026, 11, 15, 23, 0)
    samples = [
        {"t": (basis + timedelta(minutes=10 * i)).isoformat(timespec="seconds"), "bpm": 50 + (i % 20)}
        for i in range(24)
    ]
    nur_samples = synthetische_nacht(pulse={"samples": samples})
    bericht = baue_nachtbericht(nur_samples)

    werte = [s["bpm"] for s in samples]
    assert bericht.puls["min"] == min(werte)
    assert bericht.puls["max"] == max(werte)
    assert bericht.puls["mean"] == pytest.approx(sum(werte) / len(werte), abs=0.1)


def test_puls_verdichtet_auf_maximal_240_punkte():
    basis = datetime(2026, 11, 15, 23, 0)
    samples = [
        {"t": (basis + timedelta(seconds=30 * i)).isoformat(timespec="seconds"), "bpm": 50 + (i % 15)}
        for i in range(400)
    ]
    payload = synthetische_nacht(pulse={"samples": samples})
    bericht = baue_nachtbericht(payload)

    assert len(bericht.puls["punkte"]) <= 240
    # Nichts hinzugedichtet: Verdichtet wird durch Block-Mittelwert, die
    # Anzahl der zugrunde liegenden Samples bleibt benannt.
    assert bericht.puls["sample_anzahl"] == 400


def test_plausibler_pulsrahmen_wird_durchgesetzt():
    unmöglich = synthetische_nacht(pulse={"min": 10, "mean": 56, "max": 300})
    with pytest.raises(NachtberichtFehler, match="plausiblen Bereich"):
        baue_nachtbericht(unmöglich)


def test_min_uber_max_wird_abgelehnt():
    verdreht = synthetische_nacht(pulse={"min": 60, "mean": 56, "max": 50})
    with pytest.raises(NachtberichtFehler, match="min ist größer als max"):
        baue_nachtbericht(verdreht)


# ═══════════════════════════════════════════════════════════════════════════════
# HRV AUS IBI
# ═══════════════════════════════════════════════════════════════════════════════


def _ibi_wechselnd(anzahl=200, basis_ms=1000.0, start="2026-11-16T00:00:00"):
    """Deterministische IBI-Folge: 980/1020 ms im Wechsel → RMSSD 40, SDNN 20."""
    punkte = []
    zeit = datetime.fromisoformat(start)
    for i in range(anzahl):
        punkte.append(
            {
                "t": (zeit + timedelta(seconds=1.0 * i)).isoformat(timespec="seconds"),
                "interval_ms": basis_ms - 20 if i % 2 == 0 else basis_ms + 20,
            }
        )
    return punkte


def test_hrv_aus_ibi_ist_deterministisch():
    punkte = _ibi_wechselnd()
    start = datetime.fromisoformat("2026-11-16T00:00:00")
    ende = start + timedelta(minutes=8)

    hrv, grund = hrv_aus_ibi(punkte, start, ende)

    assert grund == ""
    assert hrv["rmssd"] == pytest.approx(40.0, abs=0.1)
    assert hrv["sdnn"] == pytest.approx(20.0, abs=0.1)
    assert hrv["accepted"] == 200
    assert hrv["rejected"] == 0
    assert hrv["signal_quality"] == pytest.approx(1.0)


def test_hrv_testet_formeln_gleichlautend_mit_den_grenzen():
    """Die Rechnung muss dieselben Grenzen ziehen wie der Schätzer auf der Uhr."""
    punkte = _ibi_wechselnd(anzahl=150)
    # Ein echtes Artefakt einstreuen: Sprung weit über das relative Limit
    # (0,2 × 1020 ms ≈ 204, mindestens aber 250 ms).
    punkte[50]["interval_ms"] = 1400.0
    start = datetime.fromisoformat("2026-11-16T00:00:00")
    ende = start + timedelta(minutes=6)

    hrv, grund = hrv_aus_ibi(punkte, start, ende)

    assert grund == ""
    assert hrv["rejected"] == 1
    brauchbar = [p["interval_ms"] for i, p in enumerate(punkte) if i != 50]
    d = [b - a for a, b in zip(brauchbar, brauchbar[1:])]
    erwartet_rmssd = (sum(x * x for x in d) / len(d)) ** 0.5
    assert hrv["rmssd"] == pytest.approx(erwartet_rmssd, abs=0.1)
    assert hrv["sdnn"] == pytest.approx(statistics.pstdev(brauchbar), abs=0.1)


def test_hrv_feht_bei_zu_wenigen_brauchbaren_intervallen():
    punkte = _ibi_wechselnd(anzahl=100)
    start = datetime.fromisoformat("2026-11-16T00:00:00")
    ende = start + timedelta(minutes=8)

    hrv, grund = hrv_aus_ibi(punkte, start, ende)

    assert hrv is None
    assert "zu wenige brauchbare IBI" in grund
    assert "100 von mindestens 120" in grund


def test_unphysiologische_ibi_passieren_den_transport_und_verderben_nichts():
    """120 ms IBI ist Unsinn — der Transport nimmt es an, die HRV bleibt aus.

    Die Annahme darf Rohdaten nicht silently wegwerfen; die HRV-Grenzen
    (dieselben wie auf der Uhr) werfen sie heraus, und reichen die Reste
    nicht, entsteht kein Wert — Grund im Bericht, statt Rate.
    """
    punkte = _ibi_wechselnd(anzahl=130)
    for i in range(12):
        punkte[i]["interval_ms"] = 120.0
    start = datetime.fromisoformat("2026-11-16T00:00:00")
    ende = start + timedelta(minutes=8)

    hrv, grund = hrv_aus_ibi(punkte, start, ende)

    assert hrv is None
    assert "118 von mindestens 120" in grund


def test_hrv_aggregat_vom_absender_wird_ohne_ibi_uebernommen():
    mit_agg = synthetische_nacht(hrv={"rmssd": 42.5, "sdnn": 58.0, "coverage": 0.81})
    bericht = baue_nachtbericht(mit_agg)

    assert bericht.hrv["rmssd"] == 42.5
    assert "vom Absender gemeldet" in bericht.hrv["quelle"]
    assert bericht.fehlend == [] or all(f["quelle"] != "HRV" for f in bericht.fehlend)


def test_hrv_aus_rohen_ibi_geht_vor_dem_aggregat():
    mit_beidem = synthetische_nacht(ibi=_ibi_wechselnd(), hrv={"rmssd": 99.0})
    bericht = baue_nachtbericht(mit_beidem)

    # Selbst gerechnet, nicht die vorgekaute Zahl übernommen.
    assert bericht.hrv["rmssd"] == pytest.approx(40.0, abs=0.1)


# ═══════════════════════════════════════════════════════════════════════════════
# UNTERBRECHUNGEN
# ═══════════════════════════════════════════════════════════════════════════════


def test_unterbrechungen_werden_aus_zeitleiste_abgeleitet():
    bericht = baue_nachtbericht(synthetische_nacht())

    # Die zweite Wachphase (06:10–06:40) liegt mitten in der Nacht — die
    # Anfangs-Wachphase vor dem Einschlafen zählt nicht als Unterbrechung.
    assert bericht.unterbrechungen_anzahl == 1
    assert bericht.unterbrechungen_minuten == pytest.approx(30.0)
    assert "abgeleitet" in bericht.unterbrechungen_quelle


def test_unterbrechungen_vom_absender_gehen_vor():
    gemeldet = synthetische_nacht(
        interruptions=[{"start": "2026-11-16T04:00:00", "end": "2026-11-16T04:25:00", "reason": "Wasserumfüllung"}]
    )
    bericht = baue_nachtbericht(gemeldet)

    assert bericht.unterbrechungen_anzahl == 1
    assert bericht.unterbrechungen_minuten == pytest.approx(25.0)
    assert "vom Absender gemeldet" in bericht.unterbrechungen_quelle
    assert bericht.unterbrechungen[0]["grund"] == "Wasserumfüllung"


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEMA-PRÜFUNG — KLAR NEIN SAGEN
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "anpassung, muster",
    [
        ({"schema": "andere-v9"}, "schema: erwartet"),
        ({"night": "15.11.2026"}, "night:"),
        ({"night": "2026-13-40"}, "kein gültiges Datum"),
        ({"start": "kein Zeitpunkt"}, "kein lesbarer ISO-Zeitstempel"),
        ({"end": "2026-11-15T20:00:00"}, "liegt vor oder genau auf start"),
        ({"phases": [{"stage": "falsch", "start": START, "end": "2026-11-15T23:40:00"}]}, "unbekannte Phase"),
        ({"phases": "alle"}, "muss eine Liste sein"),
        ({"ibi": [{"t": "2026-11-16T00:00:00", "interval_ms": 50}]}, "plausiblen Bereich"),
        ({"ibi": [{"t": "2026-11-16T00:00:00", "interval_ms": "viel"}]}, "muss eine Zahl sein"),
        ({"pulse": {"samples": [{"t": "2026-11-15T23:00:00", "bpm": 400}]}}, "plausiblen Bereich"),
    ],
)
def test_schema_fehler_benennen_den_grund(anpassung, muster):
    with pytest.raises(NachtberichtFehler, match=muster):
        baue_nachtbericht(synthetische_nacht(**anpassung))


def test_unbekannte_zeitstempel_ohne_offset_bleiben_lokal():
    """Naive Stempel vom Absender werden nicht umgerechnet, Offset-Zeiten schon."""
    bericht = baue_nachtbericht(synthetische_nacht())
    assert bericht.start == datetime(2026, 11, 15, 23, 10)


def test_bericht_fuer_die_karte_traegt_alles_davon():
    mit_ibi = synthetische_nacht(ibi=_ibi_wechselnd())
    bericht = baue_nachtbericht(mit_ibi)
    ausgabe = bericht.bericht(vergleich=[{"nacht": "2026-11-14", "guete": 70}])

    assert ausgabe["schema"] == SCHEMA_KENNUNG
    assert ausgabe["vergleich"] == [{"nacht": "2026-11-14", "guete": 70}]
    assert len(ausgabe["phasen_verlauf"]) == 8
    assert ausgabe["hrv"]["rmssd"] == pytest.approx(40.0, abs=0.1)
    assert ausgabe["unterbrechungen"]["anzahl"] == 1


def test_zusammenfassung_fuer_das_ereignis():
    bericht = baue_nachtbericht(synthetische_nacht())
    kurz = bericht.zusammenfassung()

    assert kurz["nacht"] == NACHT
    assert kurz["dauer_minuten"] == pytest.approx(512.0)
    assert kurz["ist_schaetzung"] is True
    assert kurz["ruhepuls_mittel"] == 56
    assert kurz["hrv_rmssd"] is None  # keine IBI → keine erfundene HRV


# ═══════════════════════════════════════════════════════════════════════════════
# SPEICHER: ANNEHMEN, BEHALTEN, VERGLEICHEN, MELDEN
# ═══════════════════════════════════════════════════════════════════════════════


class SpeicherStub:
    """Steht im Test für den HA-Store — nimmt auf, was gespeichert wird."""

    def __init__(self):
        self.gespeichert = []
        self.daten = None

    async def async_load(self):
        return self.daten

    async def async_save(self, daten):
        self.gespeichert.append(daten)
        self.daten = daten


def _speicher_mit_nacht(anzahl=1):
    stub = SpeicherStub()
    hass = MagicMock()
    speicher = NachtberichtSpeicher(hass, store=stub)
    for i in range(anzahl):
        nacht = (datetime(2026, 11, 15) - timedelta(days=i)).date().isoformat()
        start = f"{nacht}T23:00:00"
        ende = ((datetime(2026, 11, 15) - timedelta(days=i - 1)).date().isoformat()) + "T07:00:00"
        payload = synthetische_nacht(night=nacht, start=start, end=ende)
        import asyncio

        asyncio.run(speicher.async_nacht_annehmen(payload))
    return speicher, hass, stub


def test_annehmen_feuert_das_ereignis_nacht_abgeschlossen():
    speicher, hass, _ = _speicher_mit_nacht()

    hass.bus.async_fire.assert_called()
    ereignis, daten = hass.bus.async_fire.call_args[0]
    assert ereignis == EVENT_NACHT_ABGESCHLOSSEN
    assert daten["nacht"] == NACHT
    assert daten["ist_schaetzung"] is True


def test_annehmen_stoesst_die_sensoren_an():
    speicher, _, _ = _speicher_mit_nacht()
    speicher.benachrichtigen = MagicMock()

    import asyncio

    asyncio.run(speicher.async_nacht_annehmen(synthetische_nacht()))
    speicher.benachrichtigen.assert_called_once()


def test_speicher_behaelt_hoechstens_die_letzten_naechte():
    speicher, _, _ = _speicher_mit_nacht(anzahl=MAX_NAECHTE + 2)

    assert len(speicher.naechte) == MAX_NAECHTE
    # Die ältesten fielen heraus, die neuesten blieben.
    assert "2026-11-15" in speicher.naechte
    assert "2026-10-31" not in speicher.naechte
    assert "2026-11-01" not in speicher.naechte


def test_vergleich_gibt_die_letzten_sieben_nights_ohne_die_eigene():
    speicher, _, _ = _speicher_mit_nacht(anzahl=9)

    zeilen = speicher.vergleich("2026-11-15")
    assert len(zeilen) == 7
    assert all(z["nacht"] != "2026-11-15" for z in zeilen)
    # Neueste zuerst.
    assert zeilen[0]["nacht"] == "2026-11-14"
    assert zeilen[-1]["nacht"] == "2026-11-08"


def test_gespeicherte_naechte_ueberleben_den_neustart():
    speicher, _, stub = _speicher_mit_nacht(anzahl=2)

    wieder = NachtberichtSpeicher(MagicMock(), store=SpeicherStub())
    wieder._store.daten = stub.daten
    import asyncio

    asyncio.run(wieder.async_laden())
    assert set(wieder.naechte) == set(speicher.naechte)
    assert wieder.letzte_nacht()["nacht"] == "2026-11-15"


def test_nacht_wird_bei_neuer_uebertragung_ersetzt():
    speicher, hass, _ = _speicher_mit_nacht()
    rufe_vorher = hass.bus.async_fire.call_count

    import asyncio

    asyncio.run(speicher.async_nacht_annehmen(synthetische_nacht(pulse={"min": 40, "mean": 50, "max": 66})))

    assert hass.bus.async_fire.call_count == rufe_vorher + 1
    assert speicher.letzte_nacht()["puls"]["mean"] == 50


# ═══════════════════════════════════════════════════════════════════════════════
# LAUFENDE PHASE — DER SENSOR FÜR DIE AUTOMATIONEN
# ═══════════════════════════════════════════════════════════════════════════════


def test_phase_update_wird_angenommen_und_laeuft_ab():
    speicher, _, _ = _speicher_mit_nacht()
    jetzt = utc_naiv()
    import asyncio

    asyncio.run(
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
    phase = speicher.aktuelle_phase(jetzt=jetzt + timedelta(minutes=1))
    assert phase["stage"] == "deep"
    assert "grobe Schätzung" in phase["source_text"]


def test_veraltete_phase_faellt_auf_unknown_zuruck():
    speicher, _, _ = _speicher_mit_nacht()
    vor_langer_zeit = datetime.now(timezone.utc) - timedelta(minutes=45)
    import asyncio

    asyncio.run(
        speicher.async_phase_annehmen(
            {
                "schema": SCHEMA_KENNUNG,
                "type": "phase_update",
                "stage": "rem",
                "measured_at": vor_langer_zeit.isoformat(timespec="seconds"),
            }
        )
    )
    phase = speicher.aktuelle_phase(jetzt=utc_naiv())

    assert phase["stage"] == "unknown"
    assert "Minuten alt" in phase["grund"]
    assert phase["letzte_phase"]["stage"] == "rem"


def test_phase_update_ohne_zeitstempel_wird_abgelehnt():
    speicher, _, _ = _speicher_mit_nacht()
    import asyncio

    with pytest.raises(NachtberichtFehler, match="measured_at"):
        asyncio.run(speicher.async_phase_annehmen({"schema": SCHEMA_KENNUNG, "type": "phase_update", "stage": "deep"}))


def test_phase_update_mit_falscher_stufe_wird_abgelehnt():
    speicher, _, _ = _speicher_mit_nacht()
    import asyncio

    with pytest.raises(NachtberichtFehler, match="unbekannte Phase"):
        asyncio.run(
            speicher.async_phase_annehmen(
                {
                    "schema": SCHEMA_KENNUNG,
                    "type": "phase_update",
                    "stage": "traumlos",
                    "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                }
            )
        )


def test_phase_ohne_zeitzone_wird_abgelehnt():
    """Ohne Offset ist „veraltet“ nicht entscheidbar — klar sagen, was fehlt."""
    speicher, _, _ = _speicher_mit_nacht()
    import asyncio

    with pytest.raises(NachtberichtFehler, match="ohne Zeitzone"):
        asyncio.run(
            speicher.async_phase_annehmen(
                {
                    "schema": SCHEMA_KENNUNG,
                    "type": "phase_update",
                    "stage": "light",
                    "measured_at": "2026-11-16T01:00:00",
                }
            )
        )


def test_ohne_phase_gibt_es_ehrlich_unknown():
    stub = SpeicherStub()
    speicher = NachtberichtSpeicher(MagicMock(), store=stub)

    phase = speicher.aktuelle_phase()
    assert phase["stage"] == "unknown"
    assert "noch keine Phase" in phase["grund"]
