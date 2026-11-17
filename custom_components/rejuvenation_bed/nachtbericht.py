"""
Nachtbericht — die Schlafaufzeichnung der Uhr, vollständig in Home Assistant.

Die Uhr (Galaxy Watch, `watch/`) zeichnet die Nacht lokal auf: Puls, Bewegung,
Plattform-Schlafstatus und — wenn eine Quelle vorhanden ist — IBI. Der
Nachtbericht ist der Vertrag, mit dem diese Aufzeichnung hier ankommt und aus
dem die Integration Sensoren, ein „Nacht abgeschlossen“-Ereignis und die
Nachtbericht-Karte speist.

Hausregeln dieses Moduls:

- **Nie Werte erfinden.** Fehlt eine Quelle (keine IBI, kein Puls, keine
  Phasen), steht das mit Grund im Bericht (`fehlend`) — gerechnet wird nur mit
  übermittelten Werten.
- **Grobe Schätzung bleibt grobe Schätzung.** Phasen, die aus Puls + Bewegung
  geschätzt wurden (`source: "estimate"`), tragen diese Quelle in jedem
  Segment und im Bericht weiter; die Karte beschriftet sie sichtbar.
- **Fail-closed.** Zu wenige, unplausible oder veraltete Daten liefern
  `unknown` bzw. `None`, nie eine geratene Zahl. Die HRV wird nur aus IBI
  berechnet und nur, wenn genug brauchbare Intervalle übrig bleiben.
- **Alles bleibt im Haus.** Es gibt keinen Cloud-Weg; die Daten liegen im
  Home-Assistant-Speicher (`.storage/`) und in den Sensoren.

Das Modul ist reine Logik — keine Home-Assistant-Imports — und so wie die
übrigen Module unterhalb des Coordinators einzeln prüfbar.
"""

import logging
import statistics
from datetime import datetime, timezone
from typing import Any, Optional

_LOGGER = logging.getLogger(__name__)

# Schema-Kennung des Übertrags. Eine neue Feldbedeutung = neue Kennung.
SCHEMA_KENNUNG = "rejuvenation-bed-night-report-v1"

# Stellung des Schalters „Was geht an Home Assistant“ auf der Uhr:
# - phase_only (Standard): Ergebnis — laufende Phase, Phasen-Zeitleiste,
#   Zusammenfassungen (Puls min/Ø/max, HRV aus IBI, Schritte gesamt); die
#   Rohdaten bleiben auf der Uhr.
# - gesamtdaten: zusätzlich alle Messreihen der Nacht, je 5 Minuten ein
#   night_data-Paket. Die Stellung kommt in jeder Nutzlast mit (Feld `modus`);
#   fehlt es, gilt die enge Stellung.
MODUS_PHASE = "phase_only"
MODUS_GESAMT = "gesamtdaten"
MODUS_WERTE = (MODUS_PHASE, MODUS_GESAMT)
MODUS_STANDARD = MODUS_PHASE

# Messreihen-Pakete (type night_data) — kommen nur in der Stellung
# „gesamtdaten“ und werden hier je Nacht über den Zeitstempel zusammengeführt
# (Schlüssel der Einzelpunkte ist ihr Zeitstempel — Wiederholungen doppeln nicht).
TYPE_DATEN = "night_data"

# Plattform-Schlafstatus, wie die Uhr ihn meldet (grob schläft/wach, !19).
PLATTFORM_ZUSTAENDE = ("ASLEEP", "AWAKE", "UNKNOWN")

# Ereignis, wenn eine Nacht vollständig angenommen wurde.
EVENT_NACHT_ABGESCHLOSSEN = "rejuvenation_bed_nacht_abgeschlossen"

# Wie viele Nächte der Speicher behält: der 7-Nächte-Vergleich der Karte plus
# Puffer, damit ein versäumtes Senden den Vergleich nicht gleich bricht.
MAX_NAECHTE = 14
VERGLEICH_NAECHTE = 7

# Verdichteter Pulsverlauf für die Karte — 240 Punkte reichen für 12 Stunden.
MAX_PULS_PUNKTE = 240

# Die aktuelle Phase gilt so lange, danach fällt der Sensor auf `unknown`
# zurück (gleiche Grenze wie SleepPredictionWire.MAX_PREDICTION_AGE_MILLIS).
PHASE_VERFALL_MINUTEN = 10

# Phasen-Werte: exakt die Zustände, die auch SleepStageResolver versteht.
PHASEN = ("awake", "light", "deep", "rem")
UNKNOWN = "unknown"

PHASEN_TEXTE = {
    "awake": "wach",
    "light": "leicht",
    "deep": "tief",
    "rem": "REM",
    UNKNOWN: "unbekannt",
}

QUELLE_TEXTE = {
    "platform": "Plattform-Schlafstatus (schläft/wach)",
    "estimate": "grobe Schätzung aus Puls und Bewegung",
    "estimate-ibi": "Schätzung aus IBI, Puls und Bewegung",
    "external": "externe Quelle",
}

# Plausibilitäts-Grenzen. Werte außerhalb werden verworfen, nicht geraten.
PULS_MIN_BPM = 20
PULS_MAX_BPM = 250

# HRV aus IBI — dieselben Grenzen wie der Schätzer auf der Uhr
# (SleepHrvExtractor): physiologisch plausible Intervalle, Artefakte raus,
# und erst ab genug brauchbaren Intervallen heißt es „Wert“, sonst „fehlt“.
IBI_MIN_MS = 300.0
IBI_MAX_MS = 2000.0
IBI_ARTEFAKT_RELATIV = 0.20
IBI_ARTEFAKT_ABSOLUT_MS = 250.0
IBI_QUALITAET_MINIMUM = 0.50
IBI_MINIMUM_ANZAHL = 120

MIN_PLAUSIBLE_IBI_MS = 100.0
MAX_PLAUSIBLE_IBI_MS = 3000.0


class NachtberichtFehler(ValueError):
    """Der Übertrag passt nicht zum Schema — klar benennen, nichts raten."""


# ═══════════════════════════════════════════════════════════════════════════════
# HILFSFUNKTIONEN
# ═══════════════════════════════════════════════════════════════════════════════


def ohne_offset(zeit: Optional[datetime]) -> Optional[datetime]:
    """Zeit ohne Offset — die Wanduhrzeit, wie der Absender sie geschickt hat.

    Bewusst KEINE Umrechnung: Differenzen (Dauer, Anteile) stimmen so
    unabhängig von der Zone, und die Hauszeit hängt nicht an der Maschine,
    auf der HA gerade läuft. Zeitstempel, bei denen der absolute Moment
    zählt (laufende Phase), müssen mit Offset kommen und werden separat
    über UTC behandelt — siehe async_phase_annehmen.
    """
    if zeit is None:
        return None
    if zeit.tzinfo is not None:
        return zeit.replace(tzinfo=None)
    return zeit


def utc_naiv() -> datetime:
    """Jetzt in UTC, ohne tzinfo — für Verfall-Rechnungen ohne Zonenfalle."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def bis_utc_naiv(zeit: datetime) -> datetime:
    """Aware-Zeit nach UTC, Offset abgestreift — für Vergleiche in einer Zone."""
    if zeit.tzinfo is None:
        # Ohne Offset ist der absolute Moment nicht bestimmbar; der Aufrufer
        # muss das vorher prüfen (async_phase_annehmen erzwingt Offset).
        raise NachtberichtFehler("Zeitstempel ohne Zeitzone kann nicht in UTC überführt werden")
    return zeit.astimezone(timezone.utc).replace(tzinfo=None)


def _parse_ts(wert: Any, feld: str) -> datetime:
    """ISO-Zeitstempel einlesen — mit klarem Fehler statt stiller None."""
    if not isinstance(wert, str) or not wert.strip():
        raise NachtberichtFehler(f"{feld}: Zeitstempel fehlt oder ist kein Text")
    try:
        gelesen = datetime.fromisoformat(wert.replace("Z", "+00:00"))
    except ValueError as err:
        raise NachtberichtFehler(f"{feld}: kein lesbarer ISO-Zeitstempel ({wert!r})") from err
    return gelesen


def _zahl(wert: Any, feld: str, minimum: float, maximum: float, wofuer: str) -> Optional[float]:
    """Optionale Zahl mit Plausibilitätsfenster — außerhalb heißt: verworfen."""
    if wert is None:
        return None
    if isinstance(wert, bool) or not isinstance(wert, (int, float)):
        raise NachtberichtFehler(f"{wofuer}: Feld '{feld}' muss eine Zahl sein")
    wert = float(wert)
    if wert < minimum or wert > maximum:
        raise NachtberichtFehler(
            f"{wofuer}: Feld '{feld}'={wert} liegt außerhalb des plausiblen Bereichs {minimum}–{maximum}"
        )
    return wert


def _anteil(wert: Any, feld: str, wofuer: str) -> Optional[float]:
    """Zahl zwischen 0 und 1 (Konfidenz, Abdeckung) oder None."""
    if wert is None:
        return None
    geprueft = _zahl(wert, feld, 0.0, 1.0, wofuer)
    return geprueft


def quell_text(source: Optional[str]) -> str:
    """Menschliche Quelle einer Phase — „grobe Schätzung“ bleibt sichtbar."""
    return QUELLE_TEXTE.get(source, "unbekannte Quelle")


def quell_kurz(source: Optional[str]) -> str:
    """Kurzform der Quelle für knappe Tabellen."""
    if source == "platform":
        return "Plattform"
    if source in ("estimate", "estimate-ibi"):
        return "grobe Schätzung"
    if source == "external":
        return "extern"
    return "unbekannt"


# ═══════════════════════════════════════════════════════════════════════════════
# PHASEN-ZEITLEISTE
# ═══════════════════════════════════════════════════════════════════════════════


def _lese_phasen(payload: dict, start: datetime, ende: datetime) -> list[dict]:
    """Phasen-Segmente lesen, clippen und überlappungsfrei ordnen.

    Nach außen ragende oder überlappende Segmente werden gestutzt, nicht
    verworfen — die Zeitleiste deckt danach genau [start, ende] ab, soweit der
    Absender Daten geliefert hat. Was lückig bleibt, zählt als Lücke und wird
    im Bericht genannt.
    """
    roh = payload.get("phases")
    if roh is None:
        return []
    if not isinstance(roh, list):
        raise NachtberichtFehler("phases: muss eine Liste sein")

    segmente: list[dict] = []
    for i, eintrag in enumerate(roh):
        if not isinstance(eintrag, dict):
            raise NachtberichtFehler(f"phases[{i}]: muss ein Objekt sein")
        stufe = eintrag.get("stage")
        if stufe not in PHASEN:
            raise NachtberichtFehler(f"phases[{i}].stage: unbekannte Phase {stufe!r} — erlaubt sind {PHASEN}")
        seg_start = ohne_offset(_parse_ts(eintrag.get("start"), f"phases[{i}].start"))
        seg_ende = ohne_offset(_parse_ts(eintrag.get("end"), f"phases[{i}].end"))
        quelle = eintrag.get("source")
        if quelle is not None and not isinstance(quelle, str):
            raise NachtberichtFehler(f"phases[{i}].source: muss ein Text sein")
        seg = {
            "stage": stufe,
            "start": max(seg_start, start),
            "end": min(seg_ende, ende),
            "source": quelle,
            "quelle_text": quell_text(quelle),
            "confidence": _anteil(eintrag.get("confidence"), f"phases[{i}].confidence", "Phasen-Segment"),
            "coverage": _anteil(eintrag.get("coverage"), f"phases[{i}].coverage", "Phasen-Segment"),
            "algorithm": eintrag.get("algorithm") if isinstance(eintrag.get("algorithm"), str) else None,
        }
        if seg["start"] < seg["end"]:
            segmente.append(seg)

    # Sortieren und Überlappungen schneiden: Der spätere Abschnitt gewinnt
    # nicht die Länge des vorherigen — jede Minute zählt genau einmal.
    segmente.sort(key=lambda s: s["start"])
    aufgeräumt: list[dict] = []
    grenze = None
    for seg in segmente:
        if grenze is not None and seg["start"] < grenze:
            seg = {**seg, "start": grenze}
        if seg["start"] < seg["end"]:
            aufgeräumt.append(seg)
            grenze = seg["end"]
    return aufgeräumt


def _phasen_minuten(segmente: list[dict], start: datetime, ende: datetime) -> tuple[dict[str, float], float]:
    """Minuten je Phase und die Lücke, die keine Phase abdeckt."""
    minuten = {stufe: 0.0 for stufe in PHASEN}
    abgedeckt = 0.0
    for seg in segmente:
        dauer = (seg["end"] - seg["start"]).total_seconds() / 60.0
        if dauer > 0:
            minuten[seg["stage"]] += dauer
            abgedeckt += dauer
    luecke = max(0.0, (ende - start).total_seconds() / 60.0 - abgedeckt)
    return minuten, luecke


def _ableitungen_unterbrechungen(segmente: list[dict], start: datetime, ende: datetime) -> list[dict]:
    """Wach-Segmente als Unterbrechungen ableiten — Zusammenfassung, kein Erfinden.

    Wird nur benutzt, wenn der Absender selbst keine Unterbrechungen gemeldet
    hat; der Bericht kennzeichnet die Herkunft.
    """
    abgeleitet: list[dict] = []
    for seg in segmente:
        if seg["stage"] != "awake":
            continue
        if seg["start"] <= start or seg["end"] >= ende:
            continue  # Rand-Wachphasen sind Beginn/Ende der Nacht, keine Unterbrechung
        abgeleitet.append(
            {
                "start": seg["start"].isoformat(timespec="seconds"),
                "end": seg["end"].isoformat(timespec="seconds"),
                "quelle": "aus der Phasen-Zeitleiste abgeleitet",
            }
        )
    return abgeleitet


# ═══════════════════════════════════════════════════════════════════════════════
# KANÄLE — nur, wenn die Uhr sie wirklich liefert
# ═══════════════════════════════════════════════════════════════════════════════

# Die drei Kanäle, die der Auftrag nennt. Die Galaxy Watch 4 der Uhr-App
# stellt keinen davon über den bestehenden Kanal bereit — der Absender meldet
# sie daher „provided: false“ mit Grund. Die Sensoren zeigen dann
# „nicht verfügbar“ mit eben diesem Grund; nichts wird aus dem Puls oder der
# Bewegung abgeleitet.
KANAL_NAMEN = ("respiratory_rate", "spo2", "skin_temperature")

KANAL_GRENZEN = {
    "respiratory_rate": (4.0, 60.0),
    "spo2": (50.0, 100.0),
    "skin_temperature": (20.0, 45.0),
}


def _lese_kanale(payload: dict) -> dict:
    """Kanal-Blöcke lesen — provided/reason, bei Geliefertsein Mittel/Min/Max."""
    roh = payload.get("channels")
    if roh is None:
        return {}
    if not isinstance(roh, dict):
        raise NachtberichtFehler("channels: muss ein Objekt sein")
    kanale: dict[str, dict] = {}
    for name in KANAL_NAMEN:
        if name not in roh:
            continue
        eintrag = roh[name]
        if not isinstance(eintrag, dict):
            raise NachtberichtFehler(f"channels.{name}: muss ein Objekt sein")
        geliefert = eintrag.get("provided")
        if not isinstance(geliefert, bool):
            raise NachtberichtFehler(f"channels.{name}.provided: muss wahr oder falsch sein")
        kanal: dict[str, Any] = {"provided": geliefert}
        grund = eintrag.get("reason")
        if grund is not None:
            if not isinstance(grund, str) or not grund.strip():
                raise NachtberichtFehler(f"channels.{name}.reason: muss ein Text sein")
            kanal["grund"] = grund
        minimum, maximum = KANAL_GRENZEN[name]
        if geliefert:
            mittel = _zahl(eintrag.get("mean"), f"channels.{name}.mean", minimum, maximum, f"Kanal {name}")
            if mittel is None:
                raise NachtberichtFehler(f"channels.{name}: als geliefert gemeldet, aber kein Mittelwert")
            kanal["mean"] = mittel
            kanal["min"] = _zahl(eintrag.get("min"), f"channels.{name}.min", minimum, maximum, f"Kanal {name}")
            kanal["max"] = _zahl(eintrag.get("max"), f"channels.{name}.max", minimum, maximum, f"Kanal {name}")
            quelle = eintrag.get("source")
            if quelle is not None and not isinstance(quelle, str):
                raise NachtberichtFehler(f"channels.{name}.source: muss ein Text sein")
            kanal["quelle"] = quelle or "echt"
        if not geliefert and not kanal.get("grund"):
            raise NachtberichtFehler(f"channels.{name}: nicht geliefert, aber ohne benannten Grund")
        kanale[name] = kanal
    return kanale


# ═══════════════════════════════════════════════════════════════════════════════
# PULS
# ═══════════════════════════════════════════════════════════════════════════════


def _lese_puls(payload: dict, wofuer: str) -> Optional[dict]:
    """Puls lesen: Min/Mittel/Max plus verdichteter Verlauf für die Karte.

    Aggregierte Werte und Samples werden geprüft; fehlen die Aggregate, werden
    sie aus den Samples berechnet — Zusammenfassung, kein Erfinden. Beides
    fehlt: None.
    """
    roh = payload.get("pulse")
    if roh is None:
        return None
    if not isinstance(roh, dict):
        raise NachtberichtFehler("pulse: muss ein Objekt sein")

    samples_roh = roh.get("samples")
    samples: list[dict] = []
    if samples_roh is not None:
        if not isinstance(samples_roh, list):
            raise NachtberichtFehler("pulse.samples: muss eine Liste sein")
        for i, punkt in enumerate(samples_roh):
            if not isinstance(punkt, dict):
                raise NachtberichtFehler(f"pulse.samples[{i}]: muss ein Objekt sein")
            zeit = ohne_offset(_parse_ts(punkt.get("t"), f"pulse.samples[{i}].t"))
            bpm = _zahl(punkt.get("bpm"), f"pulse.samples[{i}].bpm", PULS_MIN_BPM, PULS_MAX_BPM, "Puls-Sample")
            if bpm is not None:
                samples.append({"t": zeit, "bpm": bpm})

    min_puls = _zahl(roh.get("min"), "pulse.min", PULS_MIN_BPM, PULS_MAX_BPM, "Puls")
    mittel = _zahl(roh.get("mean"), "pulse.mean", PULS_MIN_BPM, PULS_MAX_BPM, "Puls")
    max_puls = _zahl(roh.get("max"), "pulse.max", PULS_MIN_BPM, PULS_MAX_BPM, "Puls")
    abdeckung = _anteil(roh.get("coverage"), "pulse.coverage", "Puls")

    if min_puls is None or mittel is None or max_puls is None:
        if not samples:
            if any(k in roh for k in ("min", "mean", "max", "samples")):
                raise NachtberichtFehler(
                    "pulse: Aggregate unvollständig und keine Samples zum Zusammenfassen — Puls bleibt ungenannt"
                )
            return None
        werte = [s["bpm"] for s in samples]
        if min_puls is None:
            min_puls = min(werte)
        if max_puls is None:
            max_puls = max(werte)
        if mittel is None:
            mittel = sum(werte) / len(werte)

    if min_puls > max_puls:
        raise NachtberichtFehler("pulse: min ist größer als max — passt nicht zusammen")

    return {
        "min": min_puls,
        "mean": mittel,
        "max": max_puls,
        "coverage": abdeckung,
        "punkte": _verdichte_puls(samples),
        "sample_anzahl": len(samples),
    }


def _verdichte_puls(samples: list[dict]) -> list[dict]:
    """Puls-Samples für die Karte verdichten (gleiche Stufenbreite, gemittelt).

    Übersteigt die Sample-Anzahl MAX_PULS_PUNKTE, werden gleiche Blöcke
    gebildet und je Block Mittelwert und Mitte der Zeit gemeldet. Nichts wird
    hinzugedichtet: Blöcke ohne Samples entfallen.
    """
    if len(samples) <= MAX_PULS_PUNKTE:
        return [{"t": s["t"].isoformat(timespec="seconds"), "bpm": round(s["bpm"], 1)} for s in samples]
    block_groesse = -(-len(samples) // MAX_PULS_PUNKTE)
    punkte: list[dict] = []
    for i in range(0, len(samples), block_groesse):
        block = samples[i : i + block_groesse]
        mitte = block[len(block) // 2]
        punkte.append(
            {
                "t": mitte["t"].isoformat(timespec="seconds"),
                "bpm": round(sum(s["bpm"] for s in block) / len(block), 1),
            }
        )
    return punkte


# ═══════════════════════════════════════════════════════════════════════════════
# HRV AUS IBI
# ═══════════════════════════════════════════════════════════════════════════════


def _lese_ibi(payload: dict, wofuer: str) -> list[dict]:
    """Rohe IBI-Segmente lesen (t, Intervall in ms, optionale Signalqualität)."""
    roh = payload.get("ibi")
    if roh is None:
        return []
    if not isinstance(roh, list):
        raise NachtberichtFehler("ibi: muss eine Liste sein")
    punkte: list[dict] = []
    for i, eintrag in enumerate(roh):
        if not isinstance(eintrag, dict):
            raise NachtberichtFehler(f"ibi[{i}]: muss ein Objekt sein")
        zeit = ohne_offset(_parse_ts(eintrag.get("t"), f"ibi[{i}].t"))
        intervall = _zahl(
            eintrag.get("interval_ms"),
            f"ibi[{i}].interval_ms",
            MIN_PLAUSIBLE_IBI_MS,
            MAX_PLAUSIBLE_IBI_MS,
            "IBI-Sample",
        )
        qualitaet = _anteil(eintrag.get("quality"), f"ibi[{i}].quality", "IBI-Sample")
        if intervall is not None:
            punkte.append({"t": zeit, "interval_ms": intervall, "quality": qualitaet})
    punkte.sort(key=lambda p: p["t"])
    return punkte


def hrv_aus_ibi(ibi_punkte: list[dict], start: datetime, ende: datetime) -> tuple[Optional[dict], str]:
    """HRV-Kennzahlen aus rohen IBI-Segumenten — mit den Uhr-Grenzen gerechnet.

    Gleiche Regeln wie SleepHrvExtractor auf der Uhr: physiologisch plausible
    Intervalle (300–2000 ms), Signalqualität des Geräts als Unter-Grenze,
    Artefakte gegen den Vorgänger verworfen. Erst ab IBI_MINIMUM_ANZAHL
    brauchbaren Intervallen entsteht ein Wert — darunter gilt die Quelle als
    fehlend, mit Grund. RMSSD über die Differenzen aufeinanderfolgender
    brauchbarer Intervalle, SDNN über die brauchbaren Intervalle (Population).
    """
    brauchbar: list[float] = []
    roh_anzahl = len(ibi_punkte)
    verworfen_plausibel = 0
    verworfen_qualitaet = 0
    verworfen_artefakt = 0
    vorgaenger: Optional[float] = None

    for punkt in ibi_punkte:
        intervall = punkt.get("interval_ms")
        if intervall is None or intervall < IBI_MIN_MS or intervall > IBI_MAX_MS:
            verworfen_plausibel += 1
            vorgaenger = None
            continue
        qualitaet = punkt.get("quality")
        if qualitaet is not None and qualitaet < IBI_QUALITAET_MINIMUM:
            verworfen_qualitaet += 1
            vorgaenger = None
            continue
        if vorgaenger is not None:
            abweichung = abs(intervall - vorgaenger)
            if abweichung > max(vorgaenger * IBI_ARTEFAKT_RELATIV, IBI_ARTEFAKT_ABSOLUT_MS):
                verworfen_artefakt += 1
                vorgaenger = None
                continue
        brauchbar.append(intervall)
        vorgaenger = intervall

    if len(brauchbar) < IBI_MINIMUM_ANZAHL:
        grund = (
            f"zu wenige brauchbare IBI-Intervalle ({len(brauchbar)} von mindestens {IBI_MINIMUM_ANZAHL}) — "
            f"roh geliefert: {roh_anzahl}"
        )
        return None, grund

    mittel_ibi = sum(brauchbar) / len(brauchbar)
    d = [b - a for a, b in zip(brauchbar, brauchbar[1:])]
    rmssd = (sum(x * x for x in d) / len(d)) ** 0.5 if d else None
    sdnn = statistics.pstdev(brauchbar)

    dauer_minuten = max((ende - start).total_seconds() / 60.0, 0.0001)
    erwartete = dauer_minuten * 60_000.0 / mittel_ibi
    abdeckung = max(0.0, min(1.0, len(brauchbar) / erwartete))
    signalqualitaet = len(brauchbar) / roh_anzahl if roh_anzahl else None

    return (
        {
            "rmssd": round(rmssd, 1) if rmssd is not None else None,
            "sdnn": round(sdnn, 1),
            "mean_ibi": round(mittel_ibi, 1),
            "accepted": len(brauchbar),
            "rejected": verworfen_plausibel + verworfen_qualitaet + verworfen_artefakt,
            "coverage": round(abdeckung, 3),
            "signal_quality": round(signalqualitaet, 3) if signalqualitaet is not None else None,
            "quelle": "aus übermittelten IBI-Intervallen berechnet",
        },
        "",
    )


def _lese_hrv(payload: dict, ibi_punkte: list[dict], start: datetime, ende: datetime) -> tuple[Optional[dict], str]:
    """HRV lesen: vorrangig selbst aus IBI rechnen, sonst aggregierte Werte.

    Ein_agg-Wert vom Absender wird übernommen, nur wenn keine rohen IBI
    kommen — dann ist die Quelle das Gerät, und das steht im Bericht. Beides
    fehlt: keine HRV, mit Grund.
    """
    if ibi_punkte:
        werte, grund = hrv_aus_ibi(ibi_punkte, start, ende)
        if werte is not None:
            return werte, ""
        # Rohe IBI da, aber zu wenig Brauchbares — der Grund zählt mehr als
        # eine vorgekaute Zahl, die wir nicht nachprüfen könnten.
        agg = payload.get("hrv")
        if isinstance(agg, dict):
            uebernommen, agg_grund = _hrg_aggregate(agg, "hrv")
            if uebernommen is not None:
                uebernommen["quelle"] = "vom Absender gemeldet (geringe eigene Prüfbarkeit)"
                return uebernommen, ""
            return None, f"{grund}; Aggregat: {agg_grund}"
        return None, grund

    agg = payload.get("hrv")
    if agg is None:
        # Die Uhr kennt die Grenze ihrer IBI-Quelle genau (Schätzer-Kette, !19) —
        # wenn sie einen Grund mitschickt, steht der da, sonst der eigene Satz.
        grund = payload.get("hrv_grund")
        if isinstance(grund, str) and grund.strip():
            return None, grund
        return None, "keine IBI-Messwerte übermittelt — HRV wird nicht gerechnet, nicht geraten"
    if not isinstance(agg, dict):
        raise NachtberichtFehler("hrv: muss ein Objekt sein")
    return _hrg_aggregate(agg, "hrv")


def _hrg_aggregate(agg: dict, wofuer: str) -> tuple[Optional[dict], str]:
    """Aggregierte HRV-Werte vom Absender prüfen und übernehmen."""
    rmssd = _zahl(agg.get("rmssd"), "hrv.rmssd", 1.0, 400.0, wofuer)
    sdnn = _zahl(agg.get("sdnn"), "hrv.sdnn", 1.0, 400.0, wofuer)
    if rmssd is None and sdnn is None:
        return None, "keine brauchbaren HRV-Werte enthalten"
    return (
        {
            "rmssd": round(rmssd, 1) if rmssd is not None else None,
            "sdnn": round(sdnn, 1) if sdnn is not None else None,
            "mean_ibi": _zahl(agg.get("mean_ibi"), "hrv.mean_ibi", 300.0, 2000.0, wofuer),
            "accepted": agg.get("accepted") if isinstance(agg.get("accepted"), int) else None,
            "rejected": agg.get("rejected") if isinstance(agg.get("rejected"), int) else None,
            "coverage": _anteil(agg.get("coverage"), "hrv.coverage", wofuer),
            "signal_quality": _anteil(agg.get("signal_quality"), "hrv.signal_quality", wofuer),
            "quelle": "vom Absender gemeldet",
        },
        "",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# NACHTBERICHT
# ═══════════════════════════════════════════════════════════════════════════════


class Nachtbericht:
    """Eine ausgewertete Nacht — Grundlage für Sensoren, Ereignis und Karte."""

    def __init__(self, payload: dict):
        if payload.get("schema") != SCHEMA_KENNUNG:
            raise NachtberichtFehler(f"schema: erwartet {SCHEMA_KENNUNG}, erhalten {payload.get('schema')!r}")

        nacht = payload.get("night")
        if not isinstance(nacht, str) or len(nacht) != 10 or nacht[4] != "-" or nacht[7] != "-":
            raise NachtberichtFehler("night: Datum der Nacht im Format YYYY-MM-DD fehlt")
        try:
            datetime.strptime(nacht, "%Y-%m-%d")
        except ValueError as err:
            raise NachtberichtFehler(f"night: kein gültiges Datum ({nacht!r})") from err

        self.nacht = nacht
        self.start = ohne_offset(_parse_ts(payload.get("start"), "start"))
        self.ende = ohne_offset(_parse_ts(payload.get("end"), "end"))
        if self.ende <= self.start:
            raise NachtberichtFehler("end: liegt vor oder genau auf start — eine Nacht dauert länger")

        geraet = payload.get("device")
        if geraet is not None and not isinstance(geraet, str):
            raise NachtberichtFehler("device: muss ein Text sein")
        self.geraet = geraet or "Uhr"

        modus = payload.get("modus", MODUS_STANDARD)
        if modus not in MODUS_WERTE:
            raise NachtberichtFehler(f"modus: unbekannte Schalterstellung {modus!r} — erlaubt sind {MODUS_WERTE}")
        self.modus = modus

        self.segmente = _lese_phasen(payload, self.start, self.ende)
        self._phasen_minuten, self.luecken_minuten = _phasen_minuten(self.segmente, self.start, self.ende)

        self.puls = _lese_puls(payload, "Puls")
        ibi_punkte = _lese_ibi(payload, "IBI")
        self.hrv, self.hrv_grund = _lese_hrv(payload, ibi_punkte, self.start, self.ende)
        self.kanale = _lese_kanale(payload)

        self.bewegung = self._lese_bewegung(payload)

        unterbrechungen_roh = payload.get("interruptions")
        if unterbrechungen_roh is None:
            self.unterbrechungen = _ableitungen_unterbrechungen(self.segmente, self.start, self.ende)
            self.unterbrechungen_quelle = "aus der Phasen-Zeitleiste abgeleitet"
        elif isinstance(unterbrechungen_roh, list):
            self.unterbrechungen = []
            for i, eintrag in enumerate(unterbrechungen_roh):
                if not isinstance(eintrag, dict):
                    raise NachtberichtFehler(f"interruptions[{i}]: muss ein Objekt sein")
                u_start = ohne_offset(_parse_ts(eintrag.get("start"), f"interruptions[{i}].start"))
                u_ende = ohne_offset(_parse_ts(eintrag.get("end"), f"interruptions[{i}].end"))
                if u_ende <= u_start:
                    continue
                self.unterbrechungen.append(
                    {
                        "start": u_start.isoformat(timespec="seconds"),
                        "end": u_ende.isoformat(timespec="seconds"),
                        "grund": eintrag.get("reason") if isinstance(eintrag.get("reason"), str) else None,
                    }
                )
            self.unterbrechungen_quelle = "vom Absender gemeldet"
        else:
            raise NachtberichtFehler("interruptions: muss eine Liste sein")

        self.fehlend = self._sammle_fehlend(payload)
        self.guete = self._rechne_guete()

    # ── Lesen ──────────────────────────────────────────────────────────────

    @property
    def dauer_minuten(self) -> float:
        return (self.ende - self.start).total_seconds() / 60.0

    @property
    def phasen_minuten(self) -> dict[str, float]:
        return dict(self._phasen_minuten)

    @property
    def anteile_prozent(self) -> dict[str, float]:
        """Anteile je Phase in Prozent der Nacht — Basis: abgedeckte Zeit."""
        dauer = self.dauer_minuten
        if dauer <= 0:
            return {stufe: 0.0 for stufe in PHASEN}
        return {stufe: round(self._phasen_minuten[stufe] / dauer * 100.0, 1) for stufe in PHASEN}

    @property
    def ist_schaetzung(self) -> bool:
        """True, wenn mindestens ein Segment aus der groben Schätzung stammt."""
        return any(seg.get("source") in ("estimate", "estimate-ibi") for seg in self.segmente)

    @property
    def quellen(self) -> list[str]:
        """Menschlich lesbare Quellen der Phasen — für Bericht und Karte."""
        gefunden: list[str] = []
        for seg in self.segmente:
            text = seg["quelle_text"]
            if text not in gefunden:
                gefunden.append(text)
        return gefunden

    @property
    def unterbrechungen_anzahl(self) -> int:
        return len(self.unterbrechungen)

    @property
    def unterbrechungen_minuten(self) -> float:
        gesamt = 0.0
        for u in self.unterbrechungen:
            start = ohne_offset(datetime.fromisoformat(u["start"]))
            ende = ohne_offset(datetime.fromisoformat(u["end"]))
            gesamt += max(0.0, (ende - start).total_seconds() / 60.0)
        return round(gesamt, 1)

    @property
    def schritte_gesamt(self) -> Optional[int]:
        if self.bewegung is None:
            return None
        return self.bewegung.get("steps_total")

    def zusammenfassung(self) -> dict:
        """Kurze Form für das Ereignis „Nacht abgeschlossen“."""
        anteile = self.anteile_prozent
        return {
            "nacht": self.nacht,
            "dauer_minuten": round(self.dauer_minuten, 1),
            "guete": self.guete,
            "tief_anteil": anteile["deep"],
            "rem_anteil": anteile["rem"],
            "ruhepuls_mittel": round(self.puls["mean"], 1) if self.puls else None,
            "hrv_rmssd": self.hrv.get("rmssd") if self.hrv else None,
            "schlafphase_quellen": self.quellen,
            "ist_schaetzung": self.ist_schaetzung,
            "fehlend": [f["quelle"] for f in self.fehlend],
        }

    def bericht(self, vergleich: Optional[list[dict]] = None) -> dict:
        """Vollständige Form für den Nachtbericht-Sensor und die Karte."""
        anteile = self.anteile_prozent
        return {
            "schema": SCHEMA_KENNUNG,
            "nacht": self.nacht,
            "geraet": self.geraet,
            "start": self.start.isoformat(timespec="seconds"),
            "end": self.ende.isoformat(timespec="seconds"),
            "dauer_minuten": round(self.dauer_minuten, 1),
            "modus": self.modus,
            "phasen_anteile": anteile,
            "phasen_minuten": {k: round(v, 1) for k, v in self._phasen_minuten.items()},
            "phasen_verlauf": [self._segment_fuer_karte(seg) for seg in self.segmente],
            "luecken_minuten": round(self.luecken_minuten, 1),
            "puls": self._puls_fuer_karte(),
            "hrv": self.hrv,
            "hrv_grund": self.hrv_grund or None,
            "bewegung": self.bewegung,
            "kanale": self.kanale,
            "unterbrechungen": {
                "anzahl": self.unterbrechungen_anzahl,
                "minuten": self.unterbrechungen_minuten,
                "quelle": self.unterbrechungen_quelle,
                "liste": self.unterbrechungen,
            },
            "guete": self.guete,
            "quellen": self.quellen,
            "ist_schaetzung": self.ist_schaetzung,
            "fehlend": self.fehlend,
            "vergleich": vergleich or [],
        }

    # ── Aufbau ─────────────────────────────────────────────────────────────

    def _segment_fuer_karte(self, seg: dict) -> dict:
        return {
            "stage": seg["stage"],
            "start": seg["start"].isoformat(timespec="seconds"),
            "end": seg["end"].isoformat(timespec="seconds"),
            "quelle": seg.get("source"),
            "quelle_text": seg.get("quelle_text"),
            "confidence": seg.get("confidence"),
            "coverage": seg.get("coverage"),
            "algorithm": seg.get("algorithm"),
        }

    def _puls_fuer_karte(self) -> Optional[dict]:
        if self.puls is None:
            return None
        return {
            "min": round(self.puls["min"], 1),
            "mean": round(self.puls["mean"], 1),
            "max": round(self.puls["max"], 1),
            "coverage": self.puls["coverage"],
            "punkte": self.puls["punkte"],
            "sample_anzahl": self.puls["sample_anzahl"],
        }

    def _lese_bewegung(self, payload: dict) -> Optional[dict]:
        roh = payload.get("movement")
        if roh is None:
            return None
        if not isinstance(roh, dict):
            raise NachtberichtFehler("movement: muss ein Objekt sein")
        schritte = roh.get("steps_total")
        if schritte is not None and (isinstance(schritte, bool) or not isinstance(schritte, int) or schritte < 0):
            raise NachtberichtFehler("movement.steps_total: muss eine nicht-negative Zahl sein")
        fenster = roh.get("windows")
        if fenster is not None:
            if not isinstance(fenster, list):
                raise NachtberichtFehler("movement.windows: muss eine Liste sein")
            geprueft: list[dict] = []
            for i, f in enumerate(fenster):
                if not isinstance(f, dict):
                    raise NachtberichtFehler(f"movement.windows[{i}]: muss ein Objekt sein")
                zeit = ohne_offset(_parse_ts(f.get("t"), f"movement.windows[{i}].t"))
                schritte_f = f.get("steps")
                if schritte_f is not None and (
                    isinstance(schritte_f, bool) or not isinstance(schritte_f, (int, float)) or schritte_f < 0
                ):
                    raise NachtberichtFehler(f"movement.windows[{i}].steps: muss eine nicht-negative Zahl sein")
                geprueft.append({"t": zeit.isoformat(timespec="seconds"), "steps": schritte_f})
            fenster = geprueft
        varianz = roh.get("variance")
        if varianz is not None and (isinstance(varianz, bool) or not isinstance(varianz, (int, float))):
            raise NachtberichtFehler("movement.variance: muss eine Zahl sein")
        return {"steps_total": schritte, "windows": fenster, "variance": varianz}

    def _sammle_fehlend(self, payload: dict) -> list[dict]:
        """Alles, was der Absender nicht geliefert hat — benannt, nicht ersetzt."""
        fehlend: list[dict] = []
        if not self.segmente:
            fehlend.append(
                {
                    "quelle": "Schlafphasen",
                    "grund": "keine Phasen-Zeitleiste übermittelt",
                }
            )
        if self.hrv is None:
            fehlend.append({"quelle": "HRV", "grund": self.hrv_grund})
        if self.puls is None:
            fehlend.append({"quelle": "Puls", "grund": "keine Puls-Messwerte übermittelt"})
        elif self.puls.get("coverage") is not None and self.puls["coverage"] < 0.5:
            fehlend.append(
                {
                    "quelle": "Puls-Abdeckung",
                    "grund": f"nur {round(self.puls['coverage'] * 100)} % der Nacht mit Puls-Werten",
                }
            )
        if self.bewegung is None:
            fehlend.append({"quelle": "Bewegung", "grund": "keine Bewegungsdaten übermittelt"})
        return fehlend

    def _rechne_guete(self) -> float:
        """Güte der DATEN (0–100) — Abdeckung und Konfidenz der Phasen.

        Nicht der Schlaf-Score: Hier steht, wie gut die Nacht *gemessen* war.
        Ohne Phasen gilt die Nacht als ungemessen (Güte 0), mit grober
        Schätzung als das, was sie ist: niedrigere Konfidenz.
        """
        if not self.segmente:
            return 0.0
        dauer = self.dauer_minuten
        if dauer <= 0:
            return 0.0
        abgedeckt = 0.0
        gewichtet = 0.0
        for seg in self.segmente:
            dauer_seg = (seg["end"] - seg["start"]).total_seconds() / 60.0
            konfidenz = seg["confidence"]
            abdeckung = seg["coverage"]
            if konfidenz is None:
                konfidenz = 0.0
            if abdeckung is None:
                abdeckung = 1.0
            abgedeckt += dauer_seg
            gewichtet += dauer_seg * konfidenz * abdeckung
        if abgedeckt <= 0:
            return 0.0
        return round(gewichtet / abgedeckt * 100.0, 1)


# ═══════════════════════════════════════════════════════════════════════════════
# MESSREIHEN (night_data-Pakete)
# ═══════════════════════════════════════════════════════════════════════════════


def _daten_reihen(payload: dict, reihe: dict) -> dict[str, int]:
    """Die Reihen eines night_data-Pakets lesen und per Zeitstempel einweben.

    Der Schlüssel ist der Zeitstempel (naive Lokalzeit, Sekundenauflösung) —
    derselbe Punkt wird nicht doppelt gezählt. Geprüft werden dieselben
    Grenzen wie im Nachtbericht; unplausible Werte fliegen raus statt zu
    landen. Liefert, wie viele Punkte JE Reihe neu sind (Protokoll zählt,
    es liest keine Werte).
    """
    neu = {"puls": 0, "ibi": 0, "bewegung": 0, "plattform": 0}

    pulse = payload.get("pulse")
    if pulse is not None:
        if not isinstance(pulse, dict):
            raise NachtberichtFehler("pulse: muss ein Objekt sein")
        samples = pulse.get("samples")
        if samples is not None:
            if not isinstance(samples, list):
                raise NachtberichtFehler("pulse.samples: muss eine Liste sein")
            for i, punkt in enumerate(samples):
                if not isinstance(punkt, dict):
                    raise NachtberichtFehler(f"pulse.samples[{i}]: muss ein Objekt sein")
                zeit = ohne_offset(_parse_ts(punkt.get("t"), f"pulse.samples[{i}].t"))
                bpm = _zahl(punkt.get("bpm"), f"pulse.samples[{i}].bpm", PULS_MIN_BPM, PULS_MAX_BPM, "Puls-Sample")
                if bpm is None:
                    continue
                schluessel = zeit.isoformat(timespec="seconds")
                if schluessel not in reihe["pulse"]:
                    neu["puls"] += 1
                reihe["pulse"][schluessel] = {"bpm": bpm}

    ibi = payload.get("ibi")
    if ibi is not None:
        if not isinstance(ibi, list):
            raise NachtberichtFehler("ibi: muss eine Liste sein")
        for i, punkt in enumerate(ibi):
            if not isinstance(punkt, dict):
                raise NachtberichtFehler(f"ibi[{i}]: muss ein Objekt sein")
            zeit = ohne_offset(_parse_ts(punkt.get("t"), f"ibi[{i}].t"))
            intervall = _zahl(
                punkt.get("interval_ms"),
                f"ibi[{i}].interval_ms",
                MIN_PLAUSIBLE_IBI_MS,
                MAX_PLAUSIBLE_IBI_MS,
                "IBI-Sample",
            )
            qualitaet = _anteil(punkt.get("quality"), f"ibi[{i}].quality", "IBI-Sample")
            if intervall is None:
                continue
            schluessel = zeit.isoformat(timespec="seconds")
            if schluessel not in reihe["ibi"]:
                neu["ibi"] += 1
            reihe["ibi"][schluessel] = {"interval_ms": intervall, "quality": qualitaet}

    bewegung = payload.get("movement")
    if bewegung is not None:
        if not isinstance(bewegung, dict):
            raise NachtberichtFehler("movement: muss ein Objekt sein")
        fenster = bewegung.get("windows")
        if fenster is not None:
            if not isinstance(fenster, list):
                raise NachtberichtFehler("movement.windows: muss eine Liste sein")
            for i, f in enumerate(fenster):
                if not isinstance(f, dict):
                    raise NachtberichtFehler(f"movement.windows[{i}]: muss ein Objekt sein")
                zeit = ohne_offset(_parse_ts(f.get("t"), f"movement.windows[{i}].t"))
                schritte = f.get("steps")
                if schritte is not None and (
                    isinstance(schritte, bool) or not isinstance(schritte, (int, float)) or schritte < 0
                ):
                    raise NachtberichtFehler(f"movement.windows[{i}].steps: muss eine nicht-negative Zahl sein")
                if schritte is None:
                    continue
                schluessel = zeit.isoformat(timespec="seconds")
                if schluessel not in reihe["movement"]:
                    neu["bewegung"] += 1
                reihe["movement"][schluessel] = {"steps": schritte}

    plattform = payload.get("platform")
    if plattform is not None:
        if not isinstance(plattform, list):
            raise NachtberichtFehler("platform: muss eine Liste sein")
        for i, wechsel in enumerate(plattform):
            if not isinstance(wechsel, dict):
                raise NachtberichtFehler(f"platform[{i}]: muss ein Objekt sein")
            zeit = ohne_offset(_parse_ts(wechsel.get("t"), f"platform[{i}].t"))
            zustand = wechsel.get("state")
            if zustand not in PLATTFORM_ZUSTAENDE:
                raise NachtberichtFehler(
                    f"platform[{i}].state: unbekannter Zustand {zustand!r} — erlaubt sind {PLATTFORM_ZUSTAENDE}"
                )
            schluessel = zeit.isoformat(timespec="seconds")
            if schluessel not in reihe["platform"]:
                neu["plattform"] += 1
            reihe["platform"][schluessel] = {"state": zustand}

    if not any(reihe.values()):
        fehlen = [k for k in ("pulse", "ibi", "movement", "platform") if k in payload]
        if not fehlen:
            raise NachtberichtFehler("night_data: keine Reihen enthalten — erwartet pulse, ibi, movement oder platform")
    return neu


# ═══════════════════════════════════════════════════════════════════════════════
# SPEICHER
# ═══════════════════════════════════════════════════════════════════════════════


class NachtberichtSpeicher:
    """Hält die letzten Nächte und die laufende Phase; Persistenz über Store.

    Im Haus gebliebene Daten: Der Store schreibt nach `.storage/` der eigenen
    Home-Assistant-Instanz — kein Cloud-Weg, kein fremder Dienst.
    """

    STORAGE_SCHLUESSEL = "rejuvenation_bed_nachtbericht"
    STORAGE_VERSION = 1

    def __init__(self, hass, store=None):
        self.hass = hass
        self._store = store
        if self._store is None:
            from homeassistant.helpers.storage import Store

            self._store = Store(hass, self.STORAGE_VERSION, self.STORAGE_SCHLUESSEL)
        self.naechte: dict[str, dict] = {}
        self.phase: Optional[dict] = None
        # Messreihen aus night_data-Paketen, je Nacht; die Einzelpunkte hängen
        # an ihrem Zeitstempel (ISO-String) — Wiederholungen doppeln nicht.
        # Im Haus geblieben: dieser Speicher schreibt nach `.storage/`.
        self.messreihen: dict[str, dict] = {}
        self.webhook_id: Optional[str] = None
        self._geladen = False
        # Wird nach jeder Annahme gerufen, damit die Nachtbericht-Sensoren
        # sofort neu schreiben — nicht erst am nächsten 60-Sekunden-Takt.
        # Die Integration verdrahtet das mit coordinator.async_update_listeners.
        self.benachrichtigen = None

    async def async_laden(self) -> None:
        """Gespeicherte Nächte, Messreihen und Phase lesen — nach einem Neustart weiter da."""
        daten = await self._store.async_load()
        if isinstance(daten, dict):
            self.naechte = daten.get("naechte", {})
            self.phase = daten.get("phase")
            self.messreihen = daten.get("messreihen", {})
            self.webhook_id = daten.get("webhook_id")
        self._geladen = True

    async def async_speichern(self) -> None:
        await self._store.async_save(
            {
                "naechte": self.naechte,
                "phase": self.phase,
                "messreihen": self.messreihen,
                "webhook_id": self.webhook_id,
            }
        )

    async def async_nacht_annehmen(self, payload: dict) -> dict:
        """Eine Nacht annehmen: prüfen, berechnen, behalten, melden."""
        bericht = Nachtbericht(payload)
        if bericht.nacht in self.naechte:
            _LOGGER.info("Nachtbericht %s wird ersetzt — der Absender hat neu übertragen", bericht.nacht)
        neu = bericht.bericht(self.vergleich(bericht.nacht))
        self.naechte[bericht.nacht] = neu
        self._kuerzen()
        # Sind für die Nacht schon night_data-Pakete da (gesamtdaten), mischen
        # sie sich jetzt in den Bericht — der Pulskurve der Karte, nichts sonst.
        self._verknuepfe_messreihen(bericht.nacht)
        # Auch die anderen Nächte tragen den frischen Vergleich weiter.
        for nacht, daten in self.naechte.items():
            daten["vergleich"] = self.vergleich(nacht)
        await self.async_speichern()
        if self.hass is not None:
            self.hass.bus.async_fire(EVENT_NACHT_ABGESCHLOSSEN, bericht.zusammenfassung())
        self._sensoren_anstupsen()
        _LOGGER.info(
            "Nacht %s angenommen: %.0f min, Güte %.0f, Quellen: %s",
            bericht.nacht,
            bericht.dauer_minuten,
            bericht.guete,
            ", ".join(bericht.quellen) or "keine Phasen",
        )
        # Eine späte, alte Nacht kann vom Kürzen herausgefallen sein — dann
        # geht die frisch berechnete Form zurück, der Inhalt ist derselbe.
        return self.naechte.get(bericht.nacht, neu)

    async def async_phase_annehmen(self, payload: dict) -> dict:
        """Die laufende Phase annehmen — der Sensor, den Automationen lesen."""
        if payload.get("schema") != SCHEMA_KENNUNG:
            raise NachtberichtFehler(f"schema: erwartet {SCHEMA_KENNUNG}, erhalten {payload.get('schema')!r}")
        if payload.get("type") != "phase_update":
            raise NachtberichtFehler("type: erwartet 'phase_update'")
        stufe = payload.get("stage")
        if stufe not in PHASEN and stufe != UNKNOWN:
            raise NachtberichtFehler(f"stage: unbekannte Phase {stufe!r} — erlaubt sind {PHASEN} und {UNKNOWN!r}")
        gemessen = _parse_ts(payload.get("measured_at"), "measured_at")
        if gemessen.tzinfo is None:
            # Ohne Offset ist „veraltet“ nicht entscheidbar — die laufende
            # Phase ist der eine Ort, wo der absolute Moment zählt.
            raise NachtberichtFehler("measured_at: Zeitstempel ohne Zeitzone — bitte ISO mit Offset senden")
        quelle = payload.get("source")
        if quelle is not None and not isinstance(quelle, str):
            raise NachtberichtFehler("source: muss ein Text sein")
        algorithmus = payload.get("algorithm")
        if algorithmus is not None and not isinstance(algorithmus, str):
            raise NachtberichtFehler("algorithm: muss ein Text sein")
        modus = payload.get("modus", MODUS_STANDARD)
        if modus not in MODUS_WERTE:
            raise NachtberichtFehler(f"modus: unbekannte Schalterstellung {modus!r} — erlaubt sind {MODUS_WERTE}")
        self.phase = {
            "stage": stufe,
            "confidence": _anteil(payload.get("confidence"), "confidence", "Phase-Update"),
            "coverage": _anteil(payload.get("coverage"), "coverage", "Phase-Update"),
            "measured_at": gemessen.isoformat(timespec="seconds"),
            "gemessen_utc": bis_utc_naiv(gemessen).isoformat(timespec="seconds"),
            "source": quelle,
            "source_text": quell_text(quelle),
            "algorithm": algorithmus,
            "modus": modus,
        }
        await self.async_speichern()
        self._sensoren_anstupsen()
        return dict(self.phase)

    async def async_daten_annehmen(self, payload: dict) -> dict:
        """Messreihen-Pakete (type night_data) annehmen — nur aus „gesamtdaten“.

        Die Pakete kommen während bzw. nach der Nacht, bevor (oder ohne) der
        eigentliche Nachtbericht da ist. Jede Reihe wird über den Zeitstempel
        eingewebt: derselbe Punkt zweimal — etwa weil die Uhr wiederholt —
        füllt nichts auf. Gerechnet wird hier nichts; die Pakete sind der
        Rohstoff, die Zusammenfassungen liefert der Nachtbericht.
        """
        if payload.get("schema") != SCHEMA_KENNUNG:
            raise NachtberichtFehler(f"schema: erwartet {SCHEMA_KENNUNG}, erhalten {payload.get('schema')!r}")
        if payload.get("type") != TYPE_DATEN:
            raise NachtberichtFehler("type: erwartet 'night_data'")
        nacht = payload.get("night")
        if not isinstance(nacht, str) or len(nacht) != 10 or nacht[4] != "-" or nacht[7] != "-":
            raise NachtberichtFehler("night: Datum der Nacht im Format YYYY-MM-DD fehlt")
        try:
            datetime.strptime(nacht, "%Y-%m-%d")
        except ValueError as err:
            raise NachtberichtFehler(f"night: kein gültiges Datum ({nacht!r})") from err
        modus = payload.get("modus", MODUS_GESAMT)
        if modus not in MODUS_WERTE:
            raise NachtberichtFehler(f"modus: unbekannte Schalterstellung {modus!r} — erlaubt sind {MODUS_WERTE}")
        block = payload.get("block")
        if block is not None:
            if not isinstance(block, dict):
                raise NachtberichtFehler("block: muss ein Objekt sein")
            block_start = ohne_offset(_parse_ts(block.get("start"), "block.start"))
            block_ende = ohne_offset(_parse_ts(block.get("end"), "block.end"))
            if block_ende <= block_start:
                raise NachtberichtFehler("block: end liegt vor oder genau auf start")

        reihe = self.messreihen.setdefault(nacht, {"pulse": {}, "ibi": {}, "movement": {}, "platform": {}})
        neu = _daten_reihen(payload, reihe)
        if sum(neu.values()) == 0 and not any(reihe.values()):
            raise NachtberichtFehler("night_data: keine Reihen enthalten — es gab nichts zu übernehmen")
        self._kuerzen()
        self._verknuepfe_messreihen(nacht)
        await self.async_speichern()
        self._sensoren_anstupsen()
        # Zählungen, keine Werte — das Protokoll kennt keine Messpunkte.
        _LOGGER.info(
            "Messreihen Nacht %s: Puls %d (%d neu), IBI %d (%d neu), Bewegung %d (%d neu), Plattform %d (%d neu)",
            nacht,
            len(reihe["pulse"]),
            neu["puls"],
            len(reihe["ibi"]),
            neu["ibi"],
            len(reihe["movement"]),
            neu["bewegung"],
            len(reihe["platform"]),
            neu["plattform"],
        )
        return {"nacht": nacht, "modus": modus, **neu}

    def _verknuepfe_messreihen(self, nacht: str) -> None:
        """Messreihen in den Nachtbericht einweben — Pulskurve für die Karte.

        Der Bericht selbst bleibt Quelle der Zusammenfassungen; aus den Paketen
        kommt nur, was er nicht haben kann: der verdichtete Verlauf. Fehlt im
        Bericht auch die Zusammenfassung, entsteht sie aus den Paketen —
        Zusammenfassung aus übermittelten Werten, kein Erfinden.
        """
        reihe = self.messreihen.get(nacht)
        bericht = self.naechte.get(nacht)
        if not reihe or not bericht:
            return
        pulspunkte = [
            {
                "t": datetime.fromisoformat(schluessel),
                "bpm": wert["bpm"],
            }
            for schluessel, wert in sorted(reihe.get("pulse", {}).items())
        ]
        if pulspunkte:
            if bericht.get("puls") is None:
                werte = [p["bpm"] for p in pulspunkte]
                start = datetime.fromisoformat(bericht["start"])
                ende = datetime.fromisoformat(bericht["end"])
                dauer_minuten = max((ende - start).total_seconds() / 60.0, 0.0001)
                block_anzahl = max(1, int(dauer_minuten // 5.0) + (1 if dauer_minuten % 5.0 > 0 else 0))
                # Belegte 5-Minuten-Blöcke, relativ zum Nachtbeginn — ohne
                # Zeitzone-Falle (die Punkte sind naive Lokalzeit des Hauses).
                belegt = len({(p["t"] - start).total_seconds() // 300.0 for p in pulspunkte})
                bericht["puls"] = {
                    "min": round(min(werte), 1),
                    "mean": round(sum(werte) / len(werte), 1),
                    "max": round(max(werte), 1),
                    "coverage": round(min(1.0, belegt / block_anzahl), 3),
                    "punkte": _verdichte_puls(pulspunkte),
                    "sample_anzahl": len(pulspunkte),
                }
            elif not bericht["puls"].get("punkte"):
                bericht["puls"]["punkte"] = _verdichte_puls(pulspunkte)
                bericht["puls"]["sample_anzahl"] = len(pulspunkte)
                bericht["puls"]["punkte_quelle"] = "aus den übermittelten Gesamtdaten-Paketen"
        bericht["messreihen"] = {
            "puls": len(reihe.get("pulse", {})),
            "ibi": len(reihe.get("ibi", {})),
            "bewegung": len(reihe.get("movement", {})),
            "plattform": len(reihe.get("platform", {})),
            "modus": bericht.get("modus", MODUS_STANDARD),
        }

    def _sensoren_anstupsen(self) -> None:
        """Die Entities neu schreiben lassen — sofort, nicht erst im Takt."""
        if self.benachrichtigen is None:
            return
        try:
            self.benachrichtigen()
        except Exception as err:  # pragma: no cover - defensiv, nie fatal
            _LOGGER.debug("Sensoren konnten nicht angestoßen werden: %s", err)

    def _kuerzen(self) -> None:
        """Nur die letzten MAX_NAECHTE Nächte behalten — Berichte wie Messreihen.

        Nacht-Kennung und Beginn sind vertragsmäßig dasselbe Datum, darum
        reicht das ISO-Datum als Ordnung; Nächte, deren Bericht noch fehlt
        (Pakete sind zuerst da), zählen mit und altern genauso heraus.
        """
        uebrig = sorted(set(self.naechte) | set(self.messreihen), reverse=True)[:MAX_NAECHTE]
        self.naechte = {nacht: self.naechte[nacht] for nacht in uebrig if nacht in self.naechte}
        self.messreihen = {nacht: self.messreihen[nacht] for nacht in uebrig if nacht in self.messreihen}

    def letzte_nacht(self) -> Optional[dict]:
        """Der aktuellste Nachtbericht oder None."""
        if not self.naechte:
            return None
        neueste = max(self.naechte, key=lambda n: self.naechte[n]["start"])
        return self.naechte[neueste]

    def vergleich(self, bis_auf: Optional[str] = None) -> list[dict]:
        """Die letzten VERGLEICH_NAECHTE Nächte für den Karten-Vergleich.

        Neueste zuerst, ohne die Nacht selbst (`bis_auf`) — die steht oben
        und braucht sich nicht selbst zum Maßstab zu nehmen.
        """
        geordnet = sorted(self.naechte, key=lambda n: self.naechte[n]["start"], reverse=True)
        zeilen: list[dict] = []
        for nacht in geordnet:
            if nacht == bis_auf:
                continue
            daten = self.naechte[nacht]
            zeilen.append(
                {
                    "nacht": nacht,
                    "dauer_minuten": daten["dauer_minuten"],
                    "guete": daten["guete"],
                    "tief_anteil": daten["phasen_anteile"]["deep"],
                    "leicht_anteil": daten["phasen_anteile"]["light"],
                    "rem_anteil": daten["phasen_anteile"]["rem"],
                    "wach_anteil": daten["phasen_anteile"]["awake"],
                    "ruhepuls_mittel": (daten.get("puls") or {}).get("mean"),
                    "hrv_rmssd": (daten.get("hrv") or {}).get("rmssd"),
                    "ist_schaetzung": daten["ist_schaetzung"],
                }
            )
            if len(zeilen) >= VERGLEICH_NAECHTE:
                break
        return zeilen

    def aktuelle_phase(self, jetzt: Optional[datetime] = None) -> dict:
        """Die laufende Phase — oder ehrlich `unknown`, wenn sie veraltet ist.

        Der Vertrag verlangt: Bei veralteten Messwerten fällt der Sensor auf
        `unknown` zurück, damit das Bett weiter nach Kurve läuft statt auf
        eine alternde Schätzung zu reagieren.
        """
        if self.phase is None:
            return {"stage": UNKNOWN, "grund": "noch keine Phase übermittelt"}
        gemessen = datetime.fromisoformat(self.phase["gemessen_utc"])
        jetzt = jetzt or utc_naiv()
        alter_minuten = (jetzt - gemessen).total_seconds() / 60.0
        if alter_minuten > PHASE_VERFALL_MINUTEN:
            return {
                "stage": UNKNOWN,
                "grund": f"letzte Phase ist {round(alter_minuten)} Minuten alt (Verfall {PHASE_VERFALL_MINUTEN} Minuten)",
                "letzte_phase": self.phase,
            }
        return {**self.phase, "alter_minuten": round(alter_minuten, 1)}


def baue_nachtbericht(payload: dict) -> Nachtbericht:
    """Einstiegspunkt für die Annahme: prüfen und auswerten."""
    return Nachtbericht(payload)
