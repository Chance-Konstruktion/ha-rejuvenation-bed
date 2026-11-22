"""
Sensoren des Nachtberichts — die Schlafaufzeichnung der Uhr als Entities.

Aufbau (alles am Schlaf/Analyse-Gerät):

- `sensor.bett_schlafphase`            — die laufende Phase (awake/light/deep/rem/unknown);
                                         Automationen schalten das Bett danach statt zu raten.
- `sensor.bett_schlafdauer`            — Schlafdauer der letzten Nacht (h)
- `sensor.bett_tiefschlaf_anteil`      — Anteile je Phase der letzten Nacht (%)
- `sensor.bett_leichtschlaf_anteil`
- `sensor.bett_rem_anteil`
- `sensor.bett_wach_anteil`
- `sensor.bett_ruhepuls`               — Puls min/Ø/max (Ø als Zustand)
- `sensor.bett_hrv`                    — RMSSD aus IBI (ms); fehlt die Quelle, steht der Grund dabei
- `sensor.bett_schlafbeginn` / `…ende` — Beginn und Ende der Nacht
- `sensor.bett_schlafunterbrechungen`  — Anzahl der Unterbrechungen
- `sensor.bett_nachtguete`             — Güte der DATEN (0–100): war die Nacht gut gemessen?
- `sensor.bett_schritte`               — Schritte der Nacht; die Reihe (Fenster) nur bei „Gesamtdaten“
- `sensor.bett_atemfrequenz` / `…sauerstoffsaettigung` / `…hauttemperatur`
                                       — Kanäle, die die Uhr NUR sendet, wenn sie sie
                                         wirklich liefert; sonst „nicht verfügbar“ mit Grund
- `sensor.bett_nachtbericht`           — der ganze Bericht (Karte liest ihn von hier)

Ehrlichkeitsregel durchgezogen: Ohne Daten zeigt ein Sensor `unknown` und nennt
den Grund im Attribut — nichts wird aus der Puls-Kurve geraten oder platt
dupliziert. Die Schlafphase fällt nach 10 Minuten ohne Nachschub auf `unknown`
zurück (Vertrag in docs/SMARTWATCH_ARCHITECTURE.md), damit das Bett auf eine
alternde Schätzung nicht mehr reagiert. Kanäle, die das Gerät nicht bereitstellt,
zeigen „nicht verfügbar“ (unavailable) mit dem benannten Grund — es gibt für sie
keine Zahl aus einer anderen Quelle.
"""

import logging
from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import UnitOfTemperature

from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .device_info import get_sleep_device_info
from .nachtbericht import PHASEN, PHASEN_TEXTE, UNKNOWN

_LOGGER = logging.getLogger(__name__)

# Marker-Attribut: Die Karte findet den Bericht-Sensor damit von selbst —
# gleicher Weg wie bei der Nachttisch-Karte und `rejuvenation_nightstand`.
MARKER = "rejuvenation_nachtbericht"

PHASEN_ICONS = {
    "awake": "mdi:bed-outline",
    "light": "mdi:weather-night-partly-cloudy",
    "deep": "mdi:power-sleep",
    "rem": "mdi:eye-outline",
    UNKNOWN: "mdi:help-circle-outline",
}


class NachtberichtSensorBase(CoordinatorEntity, SensorEntity):
    """Grundlage: liest den Nachtbericht-Speicher vom Coordinator."""

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_device_info = get_sleep_device_info(coordinator)

    @property
    def _speicher(self):
        return getattr(self.coordinator, "nachtbericht", None)

    def _bericht(self):
        speicher = self._speicher
        if speicher is None:
            return None
        return speicher.letzte_nacht()


class BettSchlafphaseSensor(NachtberichtSensorBase):
    """Die laufende Schlafphase — der Sensor, den Automationen lesen.

    Zustände sind exakt die des SleepStageResolvers: awake, light, deep, rem,
    unknown. Veraltete Phasen fallen auf unknown zurück; Quelle und Güte
    stehen als Attribute dabei, „grobe Schätzung“ bleibt sichtbar.
    """

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Bett Schlafphase"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_nachtbericht_schlafphase"
        self._attr_icon = "mdi:sleep"

    @property
    def native_value(self):
        speicher = self._speicher
        if speicher is None:
            return UNKNOWN
        return speicher.aktuelle_phase().get("stage", UNKNOWN)

    @property
    def extra_state_attributes(self):
        speicher = self._speicher
        if speicher is None:
            return {"grund": "Nachtbericht nicht initialisiert"}
        phase = speicher.aktuelle_phase()
        attrs = {
            "phase_text": PHASEN_TEXTE.get(phase.get("stage"), PHASEN_TEXTE[UNKNOWN]),
            "quelle_text": phase.get("source_text") or quell_fallback(phase),
            "letzte_phase": phase.get("letzte_phase"),
        }
        for schluessel in ("confidence", "coverage", "measured_at", "algorithm", "alter_minuten", "grund"):
            if schluessel in phase:
                attrs[schluessel] = phase[schluessel]
        return attrs

    @property
    def icon(self):
        stufe = self.native_value
        return PHASEN_ICONS.get(stufe, "mdi:help-circle-outline")


def quell_fallback(phase: dict) -> str:
    """Quelle für Phase-Updates, die sie nicht selbst mitgeschickt haben."""
    if phase.get("stage") in (UNKNOWN, None):
        return None
    return "unbekannte Quelle"


class BettNachtZahlSensor(NachtberichtSensorBase):
    """Gemeinsame Wurzel für Sensors der letzten Nacht mit Zahlenwert."""

    def __init__(self, coordinator, name, eindeutig, einheit, icon, dezimalstellen=1):
        super().__init__(coordinator)
        self._attr_name = name
        self._attr_unique_id = eindeutig
        self._attr_native_unit_of_measurement = einheit
        self._attr_icon = icon
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._dezimalstellen = dezimalstellen

    def _gerundet(self, wert):
        if wert is None:
            return None
        return round(wert, self._dezimalstellen)


class BettSchlafdauerSensor(BettNachtZahlSensor):
    """Schlafdauer der letzten Nacht in Stunden."""

    def __init__(self, coordinator):
        super().__init__(
            coordinator,
            "Bett Schlafdauer",
            f"{coordinator.config_entry.entry_id}_nachtbericht_dauer",
            "h",
            "mdi:sleep",
        )

    @property
    def native_value(self):
        bericht = self._bericht()
        if not bericht:
            return None
        return self._gerundet(bericht["dauer_minuten"] / 60.0)

    @property
    def extra_state_attributes(self):
        bericht = self._bericht()
        if not bericht:
            return {"status": "Noch keine Nacht übermittelt"}
        return {
            "nacht": bericht["nacht"],
            "start": bericht["start"],
            "end": bericht["end"],
            "dauer_minuten": bericht["dauer_minuten"],
            "luecken_minuten": bericht["luecken_minuten"],
        }


class BettPhasenAnteilSensor(BettNachtZahlSensor):
    """Anteil einer Schlafphase an der letzten Nacht (%)."""

    TEXTE = {
        "deep": ("Bett Tiefschlaf-Anteil", "mdi:power-sleep"),
        "light": ("Bett Leichtschlaf-Anteil", "mdi:weather-night-partly-cloudy"),
        "rem": ("Bett REM-Anteil", "mdi:eye-outline"),
        "awake": ("Bett Wach-Anteil", "mdi:bed-outline"),
    }

    def __init__(self, coordinator, stufe):
        name, icon = self.TEXTE[stufe]
        super().__init__(
            coordinator,
            name,
            f"{coordinator.config_entry.entry_id}_nachtbericht_anteil_{stufe}",
            "%",
            icon,
        )
        self.stufe = stufe

    @property
    def native_value(self):
        bericht = self._bericht()
        if not bericht:
            return None
        return bericht["phasen_anteile"][self.stufe]

    @property
    def extra_state_attributes(self):
        bericht = self._bericht()
        if not bericht:
            return {"status": "Noch keine Nacht übermittelt"}
        attrs = {
            "nacht": bericht["nacht"],
            "minuten": bericht["phasen_minuten"][self.stufe],
            "phase_text": PHASEN_TEXTE[self.stufe],
        }
        if bericht["ist_schaetzung"]:
            attrs["warnung"] = "Phasen sind grob geschätzt — Quellen im Nachtbericht"
        return attrs


class BettRuhepulsSensor(BettNachtZahlSensor):
    """Puls der Nacht: Ø als Zustand, min/max und Abdeckung als Attribute."""

    def __init__(self, coordinator):
        super().__init__(
            coordinator,
            "Bett Ruhepuls",
            f"{coordinator.config_entry.entry_id}_nachtbericht_ruhepuls",
            "bpm",
            "mdi:heart-pulse",
        )

    @property
    def native_value(self):
        bericht = self._bericht()
        if not bericht:
            return None
        puls = bericht.get("puls")
        if not puls:
            return None
        return self._gerundet(puls["mean"])

    @property
    def extra_state_attributes(self):
        bericht = self._bericht()
        if not bericht:
            return {"status": "Noch keine Nacht übermittelt"}
        puls = bericht.get("puls")
        if not puls:
            return {"status": "Keine Puls-Messwerte in dieser Nacht"}
        attrs = {
            "nacht": bericht["nacht"],
            "min": puls["min"],
            "max": puls["max"],
            "abdeckung": puls["coverage"],
            "sample_anzahl": puls["sample_anzahl"],
        }
        return attrs


class BettHrvSensor(BettNachtZahlSensor):
    """HRV aus IBI (RMSSD, ms) — nur wenn genug brauchbare Intervalle da sind."""

    def __init__(self, coordinator):
        super().__init__(
            coordinator,
            "Bett HRV",
            f"{coordinator.config_entry.entry_id}_nachtbericht_hrv",
            "ms",
            "mdi:heart-flash",
        )

    @property
    def native_value(self):
        bericht = self._bericht()
        if not bericht:
            return None
        hrv = bericht.get("hrv")
        if not hrv or hrv.get("rmssd") is None:
            return None
        return self._gerundet(hrv["rmssd"])

    @property
    def extra_state_attributes(self):
        bericht = self._bericht()
        if not bericht:
            return {"status": "Noch keine Nacht übermittelt"}
        hrv = bericht.get("hrv")
        if not hrv:
            return {"status": "HRV fehlt", "grund": bericht.get("hrv_grund") or "keine IBI-Messwerte übermittelt"}
        attrs = {
            "nacht": bericht["nacht"],
            "sdnn": hrv.get("sdnn"),
            "mean_ibi": hrv.get("mean_ibi"),
            "accepted": hrv.get("accepted"),
            "rejected": hrv.get("rejected"),
            "abdeckung": hrv.get("coverage"),
            "signalqualitaet": hrv.get("signal_quality"),
            "quelle": hrv.get("quelle"),
        }
        return {k: v for k, v in attrs.items() if v is not None}


class BettSchritteSensor(BettNachtZahlSensor):
    """Schritte der Nacht — Bewegung als grober Indikator, nie als Roh-Actigraphie.

    Der Wert ist `movement.steps_total` aus dem Nachtbericht. Die Reihe je
    Intervall (die Bewegungsfenster) kommt nur in der Stellung „Gesamtdaten“
    und steht als Attribut-Zählung im Bericht (`messreihen`).
    """

    def __init__(self, coordinator):
        super().__init__(
            coordinator,
            "Bett Schritte",
            f"{coordinator.config_entry.entry_id}_nachtbericht_schritte",
            "Schritte",
            "mdi:shoe-print",
            dezimalstellen=0,
        )

    @property
    def native_value(self):
        bericht = self._bericht()
        if not bericht:
            return None
        bewegung = bericht.get("bewegung")
        if not bewegung or bewegung.get("steps_total") is None:
            return None
        return bewegung["steps_total"]

    @property
    def extra_state_attributes(self):
        bericht = self._bericht()
        if not bericht:
            return {"status": "Noch keine Nacht übermittelt"}
        bewegung = bericht.get("bewegung")
        if not bewegung:
            return {"status": "Keine Bewegungsdaten in dieser Nacht"}
        attrs = {
            "nacht": bericht["nacht"],
            "variance": bewegung.get("variance"),
            "quelle": bewegung.get("quelle"),
        }
        messreihen = bericht.get("messreihen")
        if messreihen:
            attrs["messreihen_bewegung"] = messreihen.get("bewegung")
        return {k: v for k, v in attrs.items() if v is not None}


class BettKanalSensor(NachtberichtSensorBase):
    """Ein Kanal, den die Uhr NUR sendet, wenn sie ihn wirklich liefert.

    Atemfrequenz, SpO2 und Hauttemperatur stehen nicht in jeder Nacht — die
    Galaxy Watch 4 der Uhr-App stellt keinen davon bereit. Solange nichts
    geliefert wird, zeigt der Sensor „nicht verfügbar“ (unavailable) mit dem
    benannten Grund im Attribut: nie eine Zahl aus dem Puls oder der Bewegung
    abgeleitet, nie erfunden. Kommt der Kanal doch (eine künftige Uhr, die ihn
    messen kann), ist er ein normaler Messwert mit state_class measurement und
    fließt in die Langzeitstatistik.
    """

    def __init__(self, coordinator, kanal: str, name: str, einheit, icon, device_class=None):
        super().__init__(coordinator)
        self.kanal = kanal
        self._attr_name = name
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_nachtbericht_kanal_{kanal}"
        self._attr_native_unit_of_measurement = einheit
        self._attr_icon = icon
        self._attr_state_class = SensorStateClass.MEASUREMENT
        if device_class is not None:
            self._attr_device_class = device_class

    def _kanal(self):
        bericht = self._bericht()
        if not bericht:
            return None
        return (bericht.get("kanale") or {}).get(self.kanal)

    def _fehlt_grund(self):
        """Der benannte Grund, warum dieser Kanal gerade keine Zahl hat."""
        kanal = self._kanal()
        if kanal is None:
            if self._bericht() is None:
                return "die Uhr hat diesen Kanal bislang nicht gemeldet"
            return f"der Nachtbericht nennt den Kanal '{self.kanal}' nicht"
        if not kanal.get("provided"):
            return kanal.get("grund") or "die Uhr liefert diesen Kanal nicht"
        if kanal.get("mean") is None:
            return "als geliefert gemeldet, aber ohne Mittelwert"
        return None

    @property
    def available(self):
        """Kein erfundener Ersatzwert: ohne gelieferten Kanal keine Zahl."""
        return self._fehlt_grund() is None

    @property
    def native_value(self):
        kanal = self._kanal()
        if not kanal or kanal.get("mean") is None:
            return None
        return round(kanal["mean"], 1)

    @property
    def extra_state_attributes(self):
        attrs: dict = {"kanal": self.kanal}
        grund = self._fehlt_grund()
        if grund:
            attrs["grund"] = grund
        kanal = self._kanal()
        if kanal:
            attrs["quelle"] = kanal.get("quelle")
            attrs["min"] = kanal.get("min")
            attrs["max"] = kanal.get("max")
            bericht = self._bericht()
            if bericht:
                attrs["nacht"] = bericht["nacht"]
        return attrs


def baue_nachtbericht_kanal_sensoren(coordinator) -> list:
    """Die drei Kanäle des Auftrags — nur einer davon hat heute eine Quelle.

    Hauttemperatur trägt die Temperatur-Klasse (Einheit °C), für Atemfrequenz
    und SpO2 gibt es in Home Assistant keine Geräteklassen — sie bleiben
    ehrlich ohne, mit Einheit und Messwert-Klasse.
    """
    return [
        BettKanalSensor(
            coordinator,
            "respiratory_rate",
            "Bett Atemfrequenz",
            "Atemzüge/min",
            "mdi:lungs",
        ),
        BettKanalSensor(
            coordinator,
            "spo2",
            "Bett Sauerstoffsättigung",
            "%",
            "mdi:air-filter",
        ),
        BettKanalSensor(
            coordinator,
            "skin_temperature",
            "Bett Hauttemperatur",
            UnitOfTemperature.CELSIUS,
            "mdi:thermometer",
            device_class=SensorDeviceClass.TEMPERATURE,
        ),
    ]


class BettSchlafgrenzSensor(NachtberichtSensorBase):
    """Beginn oder Ende der Nacht als Zeitstempel-Sensor."""

    def __init__(self, coordinator, stufe):
        super().__init__(coordinator)
        name = "Bett Schlafbeginn" if stufe == "start" else "Bett Schlafende"
        icon = "mdi:moon-star" if stufe == "start" else "mdi:sun-clock"
        self._attr_name = name
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_nachtbericht_{stufe}"
        self._attr_icon = icon
        self._attr_device_class = SensorDeviceClass.TIMESTAMP
        self.stufe = stufe

    @property
    def native_value(self):
        bericht = self._bericht()
        if not bericht:
            return None
        wert = bericht.get(self.stufe)
        if not wert:
            return None
        # Naive Hauszeit → bewusst die in HA konfigurierte Zeitzone
        # ansetzen, nicht die des Host-Betriebssystems: astimezone() liest
        # time.localtime, und in einem Container mit abweichender
        # System-Zone zeigen „Bett Schlafbeginn" und „Bett Schlafende"
        # um genau diese Differenz verschobene Uhrzeiten. Die Hauszeit
        # hängt nicht an der Maschine, auf der HA läuft (siehe
        # ohne_offset in nachtbericht.py) -- hier gilt dasselbe.
        return datetime.fromisoformat(wert).replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)

    @property
    def extra_state_attributes(self):
        bericht = self._bericht()
        if not bericht:
            return {"status": "Noch keine Nacht übermittelt"}
        return {"nacht": bericht["nacht"]}


class BettSchlafunterbrechungenSensor(BettNachtZahlSensor):
    """Unterbrechungen der Nacht — Anzahl; Minuten und Herkunft als Attribute."""

    def __init__(self, coordinator):
        super().__init__(
            coordinator,
            "Bett Schlafunterbrechungen",
            f"{coordinator.config_entry.entry_id}_nachtbericht_unterbrechungen",
            None,
            "mdi:alert-octagon-outline",
        )

    @property
    def native_value(self):
        bericht = self._bericht()
        if not bericht:
            return None
        return bericht["unterbrechungen"]["anzahl"]

    @property
    def extra_state_attributes(self):
        bericht = self._bericht()
        if not bericht:
            return {"status": "Noch keine Nacht übermittelt"}
        unter = bericht["unterbrechungen"]
        return {
            "nacht": bericht["nacht"],
            "minuten": unter["minuten"],
            "quelle": unter["quelle"],
            "liste": unter["liste"],
        }


class BettNachtgueteSensor(BettNachtZahlSensor):
    """Güte der MESSUNG (0–100): war die Nacht gut gemessen?

    Nicht der Schlaf-Score — hier steht Abdeckung und Konfidenz der Quellen.
    Eine Nacht ohne Phasen ist ungemessen (0), eine Nacht aus der groben
    Schätzung trägt das als niedrigere Güte und Warnung.
    """

    def __init__(self, coordinator):
        super().__init__(
            coordinator,
            "Bett Nachtgüte",
            f"{coordinator.config_entry.entry_id}_nachtbericht_guete",
            "%",
            "mdi:check-decagram-outline",
        )

    @property
    def native_value(self):
        bericht = self._bericht()
        if not bericht:
            return None
        return bericht["guete"]

    @property
    def extra_state_attributes(self):
        bericht = self._bericht()
        if not bericht:
            return {"status": "Noch keine Nacht übermittelt"}
        return {
            "nacht": bericht["nacht"],
            "ist_schaetzung": bericht["ist_schaetzung"],
            "quellen": bericht["quellen"],
            "fehlend": bericht["fehlend"],
            "luecken_minuten": bericht["luecken_minuten"],
        }


class BettNachtberichtSensor(NachtberichtSensorBase):
    """Der ganze Nachtbericht — die Karte liest ihn von hier."""

    _attr_icon = "mdi:text-box-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Bett Nachtbericht"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_nachtbericht_bericht"

    @property
    def native_value(self):
        bericht = self._bericht()
        if not bericht:
            return None
        return bericht["nacht"]

    @property
    def extra_state_attributes(self):
        speicher = self._speicher
        bericht = self._bericht()
        if not bericht:
            attrs = {"status": "Noch keine Nacht übermittelt"}
            if speicher is not None and speicher.webhook_id:
                attrs["annahme_pfad"] = _annahme_pfad(speicher)
            return attrs
        attrs = dict(bericht)
        attrs[MARKER] = True
        if speicher is not None and speicher.webhook_id:
            # Relativer Pfad — ohne Host, ohne Adresse (Hausregel). Der
            # Nutzer ergänzt seine eigene Home-Assistant-Adresse davor.
            attrs["annahme_pfad"] = _annahme_pfad(speicher)
        return attrs


def _annahme_pfad(speicher) -> str:
    from .nachtbericht_api import webhook_pfad

    return webhook_pfad(speicher.webhook_id)


def baue_nachtbericht_sensoren(coordinator) -> list:
    """Alle Nachtbericht-Sensoren — unabhängig von Bett-Hardware, immer da.

    Ohne Übertrag zeigen die Sensoren `unknown`; die Integration ist damit
    ehrlich über den Zustand („noch nichts angekommen“), statt den Sensor
    wegzulassen und den Nutzer im Ungewissen zu lassen. Die Kanäle, die die
    Uhr nicht liefert, zeigen von Anfang an „nicht verfügbar“ mit Grund.
    """
    return [
        BettSchlafphaseSensor(coordinator),
        BettSchlafdauerSensor(coordinator),
        *(BettPhasenAnteilSensor(coordinator, stufe) for stufe in PHASEN),
        BettRuhepulsSensor(coordinator),
        BettHrvSensor(coordinator),
        BettSchlafgrenzSensor(coordinator, "start"),
        BettSchlafgrenzSensor(coordinator, "end"),
        BettSchlafunterbrechungenSensor(coordinator),
        BettNachtgueteSensor(coordinator),
        BettSchritteSensor(coordinator),
        *baue_nachtbericht_kanal_sensoren(coordinator),
        BettNachtberichtSensor(coordinator),
    ]
