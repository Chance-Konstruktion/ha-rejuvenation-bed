"""
Bed-Intelligence v3 für das Rejuvenation Bed.

FIX (Apr 2026):
  - Isolations-Erkennung sensor-agnostisch (Auflagen- ODER Raumluft-Sensor)
  - Verwendet Auto-Kalibrierungs-Schwellen statt hardcoded Werten
  - Glättung gegen Sensor-Rauschen
  - Hysterese-Band um den gelernten Threshold

Drei Features die das System von "Heizung" zu "selbstlernender Schlafautomation" heben:

1. AUTO-KALIBRIERUNG
   - Lernt in den ersten 3-5 Tagen automatisch die Schwellwerte

2. ISOLATIONS-ERKENNUNG (Decken-Check)
   - Benötigt: zwei Temperaturpunkte (Wasser unten + Sensor oben).
   - Funktioniert mit beiden Konfigurationen:
     • SHT41 in Raumluft  → air < water, Decke schließt Wärme ein
                            → |Δ| sinkt unter Decke (covered_mean < uncovered_mean)
     • Auflagen-Sensor    → air > water (Auflage liegt warm auf dem Wasserkern),
                            Decke fängt Wärmeabstrahlung ab
                            → |Δ| steigt unter Decke (covered_mean > uncovered_mean)
   - Wir nutzen |water - air| und lernen die Richtung aus der Auto-Kalibrierung.
   - Defaults sind auf Auflagen-Sensor-Werte gestimmt (offen ≈ 1.5°K, zu ≈ 2.0°K).

3. SCHWITZ-ALGORITHMUS 2.0 (Kreuzkorrelation)
   - Temp↑ UND Feucht↑ = Schwitzen
   - NUR Feucht↑ (Temp konstant) = Leck oder Raum-Feuchtigkeit
"""

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Dict

from homeassistant.helpers.storage import Store
from .const import local_now

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = "rejuvenation_bed_intelligence"

# Sensor-Rauschen Schwellwert (DS18B20 = 0.0625°C Auflösung)
SENSOR_NOISE_THRESHOLD = 0.07


# ═══════════════════════════════════════════════════════════════════════════════
# KALIBRIERUNGSDATEN
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class CalibrationData:
    """Gelernte Schwellwerte aus der Kalibrierungsphase."""

    # Status
    is_calibrated: bool = False
    calibration_started: Optional[str] = None
    calibration_completed: Optional[str] = None
    samples_collected: int = 0
    min_samples_required: int = 500

    # Gelernte Werte: Wassertemp-Varianz
    water_std_empty_mean: float = 0.022
    water_std_empty_max: float = 0.035
    water_std_occupied_min: float = 0.050
    water_std_threshold: float = 0.040

    # Gelernte Werte: Isolations-Check (|Δ Wasser-Luft|, sensor-agnostisch)
    # Defaults für Auflagen-Sensor-Setup (CSV April 2026: offen ≈ 1.5°K, zu ≈ 2.0°K).
    # Bei Raumluft-Sensor liefert die Auto-Kalibrierung andere Werte (covered < uncovered).
    delta_covered_mean: float = 2.0
    delta_uncovered_mean: float = 1.5
    delta_isolation_threshold: float = 1.75

    # Gelernte Werte: Feuchtigkeit
    humidity_baseline: float = 40.0
    humidity_occupied_normal: float = 60.0
    humidity_sweat_threshold: float = 93.0

    # Roh-Daten für Kalibrierung
    _empty_water_stds: list = field(default_factory=list)
    _occupied_water_stds: list = field(default_factory=list)
    _empty_deltas: list = field(default_factory=list)
    _covered_deltas: list = field(default_factory=list)
    _empty_humidities: list = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialisiert für Storage."""
        d = {
            "is_calibrated": self.is_calibrated,
            "calibration_started": self.calibration_started,
            "calibration_completed": self.calibration_completed,
            "samples_collected": self.samples_collected,
            "water_std_empty_mean": self.water_std_empty_mean,
            "water_std_empty_max": self.water_std_empty_max,
            "water_std_occupied_min": self.water_std_occupied_min,
            "water_std_threshold": self.water_std_threshold,
            "delta_covered_mean": self.delta_covered_mean,
            "delta_uncovered_mean": self.delta_uncovered_mean,
            "delta_isolation_threshold": self.delta_isolation_threshold,
            "humidity_baseline": self.humidity_baseline,
            "humidity_occupied_normal": self.humidity_occupied_normal,
            "humidity_sweat_threshold": self.humidity_sweat_threshold,
        }
        if not self.is_calibrated:
            d["raw_empty_water_stds"] = self._empty_water_stds
            d["raw_occupied_water_stds"] = self._occupied_water_stds
            d["raw_empty_deltas"] = self._empty_deltas
            d["raw_covered_deltas"] = self._covered_deltas
            d["raw_empty_humidities"] = self._empty_humidities
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "CalibrationData":
        """Deserialisiert aus Storage."""
        cal = cls()
        for key, val in data.items():
            if key.startswith("raw_"):
                attr = f"_{key[4:]}"
                if hasattr(cal, attr) and isinstance(val, list):
                    setattr(cal, attr, val)
            elif hasattr(cal, key):
                setattr(cal, key, val)
        return cal


# ═══════════════════════════════════════════════════════════════════════════════
# ISOLATIONS-STATUS
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class IsolationStatus:
    """Aktueller Isolations-Zustand des Betts."""

    is_covered: bool = True
    delta_water_air: float = 0.0
    delta_smoothed: float = 0.0  # NEU: Geglättetes Delta
    uncovered_since: Optional[datetime] = None
    uncovered_minutes: float = 0.0
    energy_waste_warning: bool = False
    level: str = "unbekannt"
    heater_detected: bool = False  # NEU: Auto-erkannte Heizung


# ═══════════════════════════════════════════════════════════════════════════════
# SCHWITZ-STATUS 2.0
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class SweatStatus:
    """Detaillierter Schwitz-Status mit Kreuzkorrelation."""

    is_sweating: bool = False
    is_moist: bool = False
    humidity_level: str = "unbekannt"
    current_humidity: float = 0.0
    humidity_baseline: float = 40.0
    humidity_rise: float = 0.0
    cause: str = "normal"


# ═══════════════════════════════════════════════════════════════════════════════
# HAUPT-KLASSE
# ═══════════════════════════════════════════════════════════════════════════════


class BedIntelligence:
    """
    Zentrale Intelligenz-Engine für das Rejuvenation Bed.

    v2: Mit korrekter Heizungserkennung und Rausch-Immunität!
    """

    def __init__(self, hass, config_entry):
        self.hass = hass
        self.config_entry = config_entry
        self._store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}_{config_entry.entry_id}")

        # Kalibrierungsdaten
        self.calibration = CalibrationData()

        # Rolling-Buffer
        self._water_temps: Dict[int, deque] = {}
        self._air_temps: Dict[int, deque] = {}
        self._humidities: Dict[int, deque] = {}
        self._max_buffer = 720

        # Aktueller Status pro Zone
        self._isolation: Dict[int, IsolationStatus] = {}
        self._sweat: Dict[int, SweatStatus] = {}

        # Isolation 2.0: Delta-History + Heizungs-Status
        self._delta_history: Dict[int, deque] = {}  # NEU: deque statt list
        self._heater_heating: Dict[int, bool] = {}

        # NEU: Für automatische Heizungserkennung
        self._last_water_temps: Dict[int, deque] = {}  # Letzte 10 Minuten

        # Feature-Flags
        self._has_air_temp: Dict[int, bool] = {}
        self._has_humidity: Dict[int, bool] = {}

        self._loaded = False
        self._bedtime_history: Dict[int, list] = {}

    # ═══════════════════════════════════════════════════════════════════════
    # NEU: HEIZUNGS-STATUS SETZEN
    # ═══════════════════════════════════════════════════════════════════════

    def set_heater_status(self, zone_index: int, is_heating: bool):
        """
        Setzt den Heizungsstatus für eine Zone.

        MUSS vom Coordinator aufgerufen werden wenn sich der Heizungsstatus ändert!
        Ohne diesen Aufruf funktioniert die Isolation-Erkennung nicht korrekt.
        """
        old_status = self._heater_heating.get(zone_index, False)
        self._heater_heating[zone_index] = is_heating

        if old_status != is_heating:
            _LOGGER.debug(f"Zone {zone_index}: Heizungsstatus → {'AN' if is_heating else 'AUS'}")

    # ═══════════════════════════════════════════════════════════════════════
    # STORAGE
    # ═══════════════════════════════════════════════════════════════════════

    async def async_load(self):
        """Lädt Kalibrierungsdaten aus Storage."""
        if self._loaded:
            return

        try:
            data = await self._store.async_load()
            if data and "calibration" in data:
                self.calibration = CalibrationData.from_dict(data["calibration"])
                _LOGGER.info(
                    f"BedIntelligence geladen: "
                    f"{'kalibriert' if self.calibration.is_calibrated else 'Lernphase'}, "
                    f"{self.calibration.samples_collected} Samples"
                )
                # Gelernte Delta-Schwellen verwerfen, wenn cov/unc zu nah beieinander
                # liegen (Nutzer mit Tagesdecke → is_present-Label unbrauchbar).
                cov = self.calibration.delta_covered_mean
                unc = self.calibration.delta_uncovered_mean
                if abs(cov - unc) < 0.4:
                    _LOGGER.warning(
                        "Isolation-Kalibrierung unzuverlässig (cov=%.2f, unc=%.2f) — "
                        "setze auf Defaults zurück.", cov, unc,
                    )
                    self.calibration.delta_covered_mean = 2.0
                    self.calibration.delta_uncovered_mean = 1.5
                    self.calibration.delta_isolation_threshold = 1.75
            if data and "bedtime_history" in data:
                self._bedtime_history = data["bedtime_history"]
                self._bedtime_history = {int(k): v for k, v in self._bedtime_history.items()}
                total = sum(len(v) for v in self._bedtime_history.values())
                _LOGGER.info(f"Bedtime-Learning geladen: {total} Nächte")
            else:
                self._bedtime_history = {}
        except Exception as e:
            _LOGGER.error(f"BedIntelligence Load-Fehler: {e}")
            self._bedtime_history = {}

        self._loaded = True

    async def async_save(self):
        """Speichert Kalibrierungsdaten."""
        try:
            save_data = {
                "calibration": self.calibration.to_dict(),
            }
            if hasattr(self, "_bedtime_history") and self._bedtime_history:
                save_data["bedtime_history"] = self._bedtime_history

            await self._store.async_save(save_data)
        except Exception as e:
            _LOGGER.error(f"BedIntelligence Save-Fehler: {e}")

    # ═══════════════════════════════════════════════════════════════════════
    # HAUPT-UPDATE
    # ═══════════════════════════════════════════════════════════════════════

    def update(
        self,
        zone_index: int,
        water_temp: Optional[float],
        air_temp: Optional[float] = None,
        humidity: Optional[float] = None,
        is_present: bool = False,
        water_std: float = 0.0,
    ):
        """
        Aktualisiert alle Intelligence-Features.
        """
        now = local_now()

        # Feature-Flags aktualisieren
        if air_temp is not None:
            self._has_air_temp[zone_index] = True
        else:
            if self._has_air_temp.get(zone_index, False):
                _LOGGER.info(f"Zone {zone_index}: Luft-Sensor nicht mehr verfügbar")
            self._has_air_temp[zone_index] = False

        if humidity is not None:
            self._has_humidity[zone_index] = True
        else:
            if self._has_humidity.get(zone_index, False):
                _LOGGER.info(f"Zone {zone_index}: Feuchte-Sensor nicht mehr verfügbar")
            self._has_humidity[zone_index] = False

        # Daten speichern
        self._store_reading(zone_index, water_temp, air_temp, humidity, now)

        # NEU: Wassertemperatur für Heizungserkennung speichern
        if water_temp is not None:
            if zone_index not in self._last_water_temps:
                self._last_water_temps[zone_index] = deque(maxlen=30)  # 10 Min bei 30s
            self._last_water_temps[zone_index].append((now, water_temp))

        # 1. Auto-Kalibrierung
        if not self.calibration.is_calibrated:
            self._update_calibration(zone_index, water_temp, air_temp, humidity, is_present, water_std, now)
        else:
            self._update_drift_correction(zone_index, water_temp, air_temp, humidity, is_present, water_std, now)

        # 2. Isolations-Erkennung
        if self._has_air_temp.get(zone_index, False) and water_temp is not None and air_temp is not None:
            self._update_isolation(zone_index, water_temp, air_temp, is_present, now)

        # 3. Schwitz-Algorithmus 2.0
        if self._has_humidity.get(zone_index, False) and humidity is not None:
            self._update_sweat(zone_index, air_temp, humidity, is_present, now)

    # ═══════════════════════════════════════════════════════════════════════
    # 1. AUTO-KALIBRIERUNG
    # ═══════════════════════════════════════════════════════════════════════

    def _update_calibration(
        self,
        zone_index: int,
        water_temp: Optional[float],
        air_temp: Optional[float],
        humidity: Optional[float],
        is_present: bool,
        water_std: float,
        now: datetime,
    ):
        """Sammelt Daten für die Auto-Kalibrierung."""
        cal = self.calibration

        if cal.calibration_started is None:
            cal.calibration_started = now.isoformat()
            _LOGGER.info("🧠 Auto-Kalibrierung gestartet – sammle Daten...")

        if water_std <= 0 or water_temp is None:
            return

        # Ausreißer-Filter
        if not (15.0 <= water_temp <= 40.0):
            return
        if air_temp is not None and not (10.0 <= air_temp <= 45.0):
            return

        cal.samples_collected += 1

        if is_present:
            cal._occupied_water_stds.append(water_std)
        else:
            cal._empty_water_stds.append(water_std)

        if not is_present and humidity is not None:
            cal._empty_humidities.append(humidity)

        if air_temp is not None and water_temp is not None:
            delta = abs(water_temp - air_temp)
            if is_present:
                cal._covered_deltas.append(delta)
            else:
                cal._empty_deltas.append(delta)

        if len(cal._empty_water_stds) >= 200 and len(cal._occupied_water_stds) >= 100:
            self._finalize_calibration(now)
        elif cal.samples_collected % 50 == 0:
            if self.hass:
                self.hass.async_create_task(self.async_save())

    def _finalize_calibration(self, now: datetime):
        """Berechnet optimale Schwellwerte aus den gesammelten Daten."""
        cal = self.calibration

        empty_stds = sorted(cal._empty_water_stds)
        occupied_stds = sorted(cal._occupied_water_stds)

        cal.water_std_empty_mean = sum(empty_stds) / len(empty_stds)
        cal.water_std_empty_max = empty_stds[int(len(empty_stds) * 0.95)]
        cal.water_std_occupied_min = occupied_stds[int(len(occupied_stds) * 0.10)]

        gap = cal.water_std_occupied_min - cal.water_std_empty_max
        if gap > 0.005:
            cal.water_std_threshold = cal.water_std_empty_max + gap * 0.4
        else:
            cal.water_std_threshold = (cal.water_std_empty_max + cal.water_std_occupied_min) / 2

        # Delta-Werte — nur übernehmen, wenn die beiden Klassen sich deutlich
        # unterscheiden. `is_present` ist nur ein schwacher Proxy für „Decke
        # drauf" (Nutzer mit Tagesdecke verfälschen die Verteilung), deshalb
        # behalten wir die Defaults, wenn der Spread klein ist.
        MIN_DELTA_SPREAD = 0.4  # °K
        if cal._covered_deltas and cal._empty_deltas:
            cov = sum(cal._covered_deltas) / len(cal._covered_deltas)
            unc = sum(cal._empty_deltas) / len(cal._empty_deltas)
            if abs(cov - unc) >= MIN_DELTA_SPREAD:
                cal.delta_covered_mean = cov
                cal.delta_uncovered_mean = unc
                cal.delta_isolation_threshold = (cov + unc) / 2
            else:
                _LOGGER.info(
                    "Isolation-Kalibrierung verworfen: Spread |%.2f - %.2f| < %.2f — "
                    "behalte Defaults (cov=%.2f, unc=%.2f).",
                    cov, unc, MIN_DELTA_SPREAD,
                    cal.delta_covered_mean, cal.delta_uncovered_mean,
                )

        # Feuchtigkeit
        if cal._empty_humidities:
            cal.humidity_baseline = sum(cal._empty_humidities) / len(cal._empty_humidities)

        cal.is_calibrated = True
        cal.calibration_completed = now.isoformat()

        # Rohdaten löschen
        cal._empty_water_stds = []
        cal._occupied_water_stds = []
        cal._empty_deltas = []
        cal._covered_deltas = []
        cal._empty_humidities = []

        _LOGGER.info(f"✅ Auto-Kalibrierung abgeschlossen nach " f"{cal.samples_collected} Samples!")

        if self.hass:
            self.hass.async_create_task(self.async_save())

    def _update_drift_correction(
        self,
        zone_index: int,
        water_temp: Optional[float],
        air_temp: Optional[float],
        humidity: Optional[float],
        is_present: bool,
        water_std: float,
        now: datetime,
    ):
        """Nachkalibrierung für saisonale Änderungen."""
        cal = self.calibration

        if water_temp is not None and not (15.0 <= water_temp <= 40.0):
            return
        if air_temp is not None and not (10.0 <= air_temp <= 45.0):
            return
        if humidity is not None and not (10.0 <= humidity <= 100.0):
            return
        if water_std <= 0 or water_temp is None:
            return

        if not hasattr(cal, "_drift_counter"):
            cal._drift_counter = 0
            cal._drift_empty_stds = []
            cal._drift_occupied_stds = []

        cal._drift_counter += 1

        if is_present:
            cal._drift_occupied_stds.append(water_std)
            if len(cal._drift_occupied_stds) > 200:
                cal._drift_occupied_stds = cal._drift_occupied_stds[-200:]
        else:
            cal._drift_empty_stds.append(water_std)
            if len(cal._drift_empty_stds) > 200:
                cal._drift_empty_stds = cal._drift_empty_stds[-200:]

        if cal._drift_counter >= 500:
            cal._drift_counter = 0
            alpha = 0.15

            if len(cal._drift_empty_stds) >= 50 and len(cal._drift_occupied_stds) >= 30:
                new_empty = sorted(cal._drift_empty_stds)
                new_occupied = sorted(cal._drift_occupied_stds)

                new_empty_max = new_empty[int(len(new_empty) * 0.95)]
                new_occupied_min = new_occupied[int(len(new_occupied) * 0.10)]
                new_threshold = (new_empty_max + new_occupied_min) / 2

                old_threshold = cal.water_std_threshold
                cal.water_std_threshold = (1 - alpha) * old_threshold + alpha * new_threshold

                _LOGGER.info(f"🔄 Drift-Korrektur: Schwelle {old_threshold:.4f} → " f"{cal.water_std_threshold:.4f}")

                if self.hass:
                    self.hass.async_create_task(self.async_save())

    # ═══════════════════════════════════════════════════════════════════════
    # 2. ISOLATIONS-ERKENNUNG (sensor-agnostisch, kalibrations-basiert)
    # ═══════════════════════════════════════════════════════════════════════

    def _update_isolation(
        self,
        zone_index: int,
        water_temp: float,
        air_temp: float,
        is_present: bool,
        now: datetime,
    ):
        """
        Prüft ob das Bett gut isoliert (zugedeckt) ist.

        Funktioniert für beide Sensor-Konfigurationen:
          • SHT41 in Raumluft  → air_temp < water_temp, Decke schließt Wärme ein
                                 → |Δ| sinkt unter Decke
          • Auflagen-Sensor    → air_temp > water_temp (Auflage liegt direkt
                                 auf dem Wasserkern, oben warm), Decke fängt
                                 die Wärmeabstrahlung ab → |Δ| steigt unter Decke

        Wir benutzen |water - air| und unterscheiden die Richtung anhand der
        gelernten Mittelwerte: ist `delta_covered_mean > delta_uncovered_mean`,
        gilt „höheres Δ = zugedeckt" (Auflagen-Setup); sonst umgekehrt.

        Schwellen kommen aus der Auto-Kalibrierung; vor Kalibrierung greifen
        Defaults, die auf typische Auflagen-Sensor-Werte angepasst sind
        (CSV April 2026: offen ≈ 1.5°K, zu ≈ 2.0°K).
        """
        if air_temp is None or water_temp is None:
            return

        if zone_index not in self._isolation:
            self._isolation[zone_index] = IsolationStatus()

        iso = self._isolation[zone_index]
        delta = abs(water_temp - air_temp)
        iso.delta_water_air = round(delta, 2)

        # Glättung über 30 min gegen Sensor-Rauschen und Heizungsbursts
        if zone_index not in self._delta_history:
            self._delta_history[zone_index] = deque(maxlen=60)
        self._delta_history[zone_index].append((now, delta))
        cutoff = now - timedelta(minutes=30)
        recent = [v for t, v in self._delta_history[zone_index] if t > cutoff]
        avg = sum(recent) / len(recent) if len(recent) >= 5 else delta
        iso.delta_smoothed = round(avg, 3)

        # Schwellen aus Kalibrierung — Defaults greifen vor erstem Lernen
        cal = self.calibration
        cov_mean = cal.delta_covered_mean
        unc_mean = cal.delta_uncovered_mean
        threshold = (cov_mean + unc_mean) / 2
        spread = abs(cov_mean - unc_mean)
        # Hysterese-Band: 25 % des Spreads, mindestens 0.1°K
        band = max(spread * 0.25, 0.1)

        # Richtung: ist „covered" = höheres oder niedrigeres |Δ|?
        covered_is_higher = cov_mean > unc_mean

        # Hysterese: wenn schon covered, braucht es weniger zum Bleiben
        if covered_is_higher:
            cross = threshold - band if iso.is_covered else threshold + band
            new_covered = avg >= cross
        else:
            cross = threshold + band if iso.is_covered else threshold - band
            new_covered = avg <= cross

        iso.is_covered = new_covered

        # Level-Klassifikation (nur Anzeige)
        good_cutoff = threshold + spread * 0.3 if covered_is_higher else threshold - spread * 0.3
        if covered_is_higher:
            if avg >= good_cutoff:
                iso.level = "gut"
            elif iso.is_covered:
                iso.level = "mäßig"
            else:
                iso.level = "offen"
        else:
            if avg <= good_cutoff:
                iso.level = "gut"
            elif iso.is_covered:
                iso.level = "mäßig"
            else:
                iso.level = "offen"

        # Timer + Energie-Warnung
        if not iso.is_covered:
            if iso.uncovered_since is None:
                iso.uncovered_since = now
            iso.uncovered_minutes = (now - iso.uncovered_since).total_seconds() / 60
            iso.energy_waste_warning = iso.uncovered_minutes > 60
        else:
            iso.uncovered_since = None
            iso.uncovered_minutes = 0
            iso.energy_waste_warning = False

    def get_isolation_status(self, zone_index: int) -> IsolationStatus:
        """Gibt den aktuellen Isolations-Status zurück."""
        return self._isolation.get(zone_index, IsolationStatus())

    # ═══════════════════════════════════════════════════════════════════════
    # 3. SCHWITZ-ALGORITHMUS 2.0
    # ═══════════════════════════════════════════════════════════════════════

    def _update_sweat(
        self,
        zone_index: int,
        air_temp: Optional[float],
        humidity: float,
        is_present: bool,
        now: datetime,
    ):
        """Schwitz-Erkennung mit Kreuzkorrelation."""
        if humidity is None:
            return

        if zone_index not in self._sweat:
            self._sweat[zone_index] = SweatStatus()

        sweat = self._sweat[zone_index]
        sweat.current_humidity = round(humidity, 1)
        sweat.humidity_baseline = self.calibration.humidity_baseline

        sweat.humidity_level = self._calc_humidity_level(humidity)

        rise = humidity - self.calibration.humidity_baseline
        sweat.humidity_rise = round(rise, 1)

        if not is_present:
            sweat.is_sweating = False
            sweat.is_moist = False
            sweat.cause = "leer"
            return

        # Kreuzkorrelation
        has_temp_rise = False
        has_humidity_rise = humidity > 70

        if air_temp is not None and self._has_air_temp.get(zone_index):
            air_buf = self._air_temps.get(zone_index, deque())
            if len(air_buf) >= 10:
                cutoff = now - timedelta(minutes=30)
                recent = [v for ts, v in air_buf if ts > cutoff and v is not None]
                if len(recent) >= 5:
                    temp_change = recent[-1] - recent[0]
                    has_temp_rise = temp_change > 0.3

        # Ursachen-Bestimmung
        if humidity > self.calibration.humidity_sweat_threshold:
            sweat.is_moist = True
            if has_temp_rise:
                sweat.is_sweating = True
                sweat.cause = "schwitzen"
            else:
                sweat.is_sweating = False
                sweat.cause = "leck_verdacht"
        elif has_temp_rise and has_humidity_rise:
            sweat.is_sweating = True
            sweat.is_moist = False
            sweat.cause = "schwitzen"
        elif has_humidity_rise and not has_temp_rise:
            sweat.is_sweating = False
            sweat.is_moist = False
            sweat.cause = "raum_feuchtigkeit"
        else:
            sweat.is_sweating = False
            sweat.is_moist = False
            sweat.cause = "normal"

    def get_sweat_status(self, zone_index: int) -> SweatStatus:
        """Gibt den aktuellen Schwitz-Status zurück."""
        return self._sweat.get(zone_index, SweatStatus())

    def _calc_humidity_level(self, humidity: float) -> str:
        """Berechnet die Feuchtigkeitsstufe."""
        if humidity > 93:
            return "stark feucht"
        elif humidity > 85:
            return "sehr feucht"
        elif humidity > 70:
            return "feucht"
        elif humidity > 50:
            return "normal"
        else:
            return "trocken"

    # ═══════════════════════════════════════════════════════════════════════
    # HILFSFUNKTIONEN
    # ═══════════════════════════════════════════════════════════════════════

    def _store_reading(
        self,
        zone_index: int,
        water_temp: Optional[float],
        air_temp: Optional[float],
        humidity: Optional[float],
        now: datetime,
    ):
        """Speichert Sensor-Werte in Rolling-Buffer."""
        if zone_index not in self._water_temps:
            self._water_temps[zone_index] = deque(maxlen=self._max_buffer)
            self._air_temps[zone_index] = deque(maxlen=self._max_buffer)
            self._humidities[zone_index] = deque(maxlen=self._max_buffer)

        if water_temp is not None:
            self._water_temps[zone_index].append((now, water_temp))
        if air_temp is not None:
            self._air_temps[zone_index].append((now, air_temp))
        if humidity is not None:
            self._humidities[zone_index].append((now, humidity))

    def get_calibration_progress(self) -> dict:
        """Gibt den Kalibrierungsfortschritt zurück."""
        cal = self.calibration
        if cal.is_calibrated:
            return {
                "status": "kalibriert",
                "completed": cal.calibration_completed,
                "water_threshold": round(cal.water_std_threshold, 4),
                "isolation_threshold": round(cal.delta_isolation_threshold, 2),
                "humidity_baseline": round(cal.humidity_baseline, 1),
            }

        empty_count = len(cal._empty_water_stds)
        occupied_count = len(cal._occupied_water_stds)
        progress = min(100, int((min(empty_count, 200) + min(occupied_count, 100)) / 3))

        return {
            "status": "lernphase",
            "progress_percent": progress,
            "samples_total": cal.samples_collected,
            "samples_empty": empty_count,
            "samples_occupied": occupied_count,
            "min_empty_needed": max(0, 200 - empty_count),
            "min_occupied_needed": max(0, 100 - occupied_count),
            "hint": (
                "Bitte das Bett normal nutzen (schlafen + tagsüber leer). "
                "Kalibrierung braucht Daten von beiden Zuständen."
            ),
        }

    def get_diagnostics(self, zone_index: int) -> dict:
        """Umfassende Diagnostics für Debug und Dashboard."""
        iso = self.get_isolation_status(zone_index)
        sweat = self.get_sweat_status(zone_index)
        return {
            "calibration": self.get_calibration_progress(),
            "features": {
                "has_air_temp": self._has_air_temp.get(zone_index, False),
                "has_humidity": self._has_humidity.get(zone_index, False),
                "isolation_available": self._has_air_temp.get(zone_index, False),
                "sweat_v2_available": self._has_humidity.get(zone_index, False),
            },
            "isolation": {
                "is_covered": iso.is_covered,
                "delta_water_air": iso.delta_water_air,
                "delta_smoothed": iso.delta_smoothed,
                "level": iso.level,
                "uncovered_minutes": round(iso.uncovered_minutes, 1),
                "energy_waste_warning": iso.energy_waste_warning,
                "heater_detected": iso.heater_detected,
                "heater_explicit": self._heater_heating.get(zone_index, None),
            },
            "sweat": {
                "is_sweating": sweat.is_sweating,
                "is_moist": sweat.is_moist,
                "humidity_level": sweat.humidity_level,
                "humidity": sweat.current_humidity,
                "humidity_rise": sweat.humidity_rise,
                "cause": sweat.cause,
            },
            "bedtime_learning": self.get_bedtime_diagnostics(zone_index),
        }

    # ═══════════════════════════════════════════════════════════════════════
    # BEDTIME LEARNING
    # ═══════════════════════════════════════════════════════════════════════

    _BEDTIME_HISTORY_DAYS = 28
    _MIN_SAMPLES_FOR_PREDICTION = 3

    def record_bedtime(self, zone_index: int, bedtime: datetime):
        """Speichert eine Einschlafzeit für das Lernmodell."""
        if not hasattr(self, "_bedtime_history"):
            self._bedtime_history = {}

        history = self._bedtime_history.setdefault(zone_index, [])

        minutes = bedtime.hour * 60 + bedtime.minute
        if minutes < 720:
            minutes += 1440

        session_date = bedtime.date()
        if bedtime.hour < 12:
            session_date = session_date - timedelta(days=1)

        session_key = session_date.strftime("%Y-%m-%d")

        entry = {
            "date": session_key,
            "weekday": session_date.weekday(),
            "minutes": minutes,
            "time_str": bedtime.strftime("%H:%M"),
        }

        history = [h for h in history if h["date"] != session_key]
        history.append(entry)

        cutoff = local_now() - timedelta(days=self._BEDTIME_HISTORY_DAYS)
        cutoff_str = cutoff.strftime("%Y-%m-%d")
        history = [h for h in history if h["date"] >= cutoff_str]

        self._bedtime_history[zone_index] = history

        _LOGGER.info(
            f"Zone {zone_index}: Einschlafzeit gelernt: {entry['time_str']} "
            f"({'Wochenende' if session_date.weekday() >= 4 else 'Wochentag'}) "
            f"[{len(history)} Nächte gespeichert]"
        )

        if self.hass and hasattr(self.hass, "async_create_task"):
            self.hass.async_create_task(self.async_save())

    def predict_bedtime(self, zone_index: int) -> Optional[dict]:
        """Sagt die wahrscheinliche Einschlafzeit vorher."""
        if not hasattr(self, "_bedtime_history"):
            return None

        history = self._bedtime_history.get(zone_index, [])
        if len(history) < self._MIN_SAMPLES_FOR_PREDICTION:
            return None

        now = local_now()
        is_weekend = now.weekday() >= 4

        if is_weekend:
            relevant = [h for h in history if h["weekday"] >= 4]
            day_type = "Wochenende"
        else:
            relevant = [h for h in history if h["weekday"] < 4]
            day_type = "Wochentag"

        if len(relevant) < self._MIN_SAMPLES_FOR_PREDICTION:
            relevant = history
            day_type = "Alle Tage"

        relevant_sorted = sorted(relevant, key=lambda h: h["date"])
        minutes_list = [h["minutes"] for h in relevant_sorted]

        # Median
        sorted_mins = sorted(minutes_list)
        n = len(sorted_mins)
        if n % 2 == 0:
            median_min = (sorted_mins[n // 2 - 1] + sorted_mins[n // 2]) / 2
        else:
            median_min = sorted_mins[n // 2]

        # EWMA
        alpha = 0.3
        ewma = minutes_list[0]
        for m in minutes_list[1:]:
            ewma = alpha * m + (1 - alpha) * ewma

        # Hybrid
        predicted_min = 0.6 * ewma + 0.4 * median_min

        pred_min = int(predicted_min) % 1440
        pred_hour = pred_min // 60
        pred_minute = pred_min % 60

        # Streuung
        q1 = sorted_mins[n // 4] if n >= 4 else sorted_mins[0]
        q3 = sorted_mins[3 * n // 4] if n >= 4 else sorted_mins[-1]
        spread_min = q3 - q1

        if spread_min < 30:
            confidence = "hoch"
        elif spread_min < 60:
            confidence = "mittel"
        else:
            confidence = "niedrig"

        from datetime import time as dt_time

        return {
            "predicted_time": dt_time(pred_hour, pred_minute),
            "predicted_str": f"{pred_hour:02d}:{pred_minute:02d}",
            "confidence": confidence,
            "spread_minutes": round(spread_min),
            "basis": day_type,
            "sample_count": len(relevant),
            "method": "EWMA+Median",
            "ewma_minutes": round(ewma),
            "median_minutes": round(median_min),
        }

    def get_predicted_preheat_start(
        self, zone_index: int, preheat_hours: float = 3.0, configured_warm_from: Optional[str] = None
    ) -> Optional[str]:
        """Berechnet den optimalen Vorheiz-Start."""
        prediction = self.predict_bedtime(zone_index)
        if prediction is None or prediction["confidence"] == "niedrig":
            return None

        pred_time = prediction["predicted_time"]
        pred_minutes = pred_time.hour * 60 + pred_time.minute

        preheat_start_min = pred_minutes - int(preheat_hours * 60) - 30

        if configured_warm_from:
            parts = configured_warm_from.split(":")
            config_min = int(parts[0]) * 60 + (int(parts[1]) if len(parts) > 1 else 0)
            preheat_start_min = min(preheat_start_min, config_min)

        preheat_start_min = preheat_start_min % 1440
        start_h = preheat_start_min // 60
        start_m = preheat_start_min % 60

        return f"{start_h:02d}:{start_m:02d}"

    def get_bedtime_diagnostics(self, zone_index: int) -> dict:
        """Debug-Info für Bedtime Learning."""
        if not hasattr(self, "_bedtime_history"):
            return {"status": "Keine Daten", "nights_recorded": 0}

        history = self._bedtime_history.get(zone_index, [])
        prediction = self.predict_bedtime(zone_index)

        result = {
            "nights_recorded": len(history),
            "min_required": self._MIN_SAMPLES_FOR_PREDICTION,
        }

        if history:
            recent = history[-5:]
            result["recent_bedtimes"] = [f"{h['time_str']} ({'WE' if h['weekday'] >= 4 else 'WT'})" for h in recent]

        if prediction:
            result["prediction"] = prediction["predicted_str"]
            result["confidence"] = prediction["confidence"]
            result["spread_minutes"] = prediction["spread_minutes"]
            result["basis"] = prediction["basis"]

            preheat = self.get_predicted_preheat_start(zone_index)
            if preheat:
                result["predicted_preheat_start"] = preheat
        else:
            result["prediction"] = "Noch nicht genug Daten"

        return result
