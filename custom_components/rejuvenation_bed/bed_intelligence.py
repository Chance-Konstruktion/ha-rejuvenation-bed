"""
Bed-Intelligence v1 für das Rejuvenation Bed.

Drei Features die das System von "Heizung" zu "Schlaf-KI" heben:

1. AUTO-KALIBRIERUNG
   - Lernt in den ersten 3-5 Tagen automatisch die Schwellwerte
   - Misst σ(Wasser) bei leer/belegt und setzt Präsenz-Schwelle
   - Misst Feuchtigkeit-Baseline und Δ(Wasser-Luft) bei offen/zugedeckt
   - Funktioniert für jedes Bett, nicht nur für ein spezifisches Setup

2. ISOLATIONS-ERKENNUNG (Decken-Check)
   - Benötigt: DS18B20 (unten) + SHT41 (oben) = zwei Temperaturpunkte
   - Bett zugedeckt: Δ(Wasser - Luft) < 2°C (Decke isoliert)
   - Bett offen: Δ(Wasser - Luft) > 5°C (Wärme verpufft)
   - Aktion: Heizung drosseln + Notification wenn >30min offen

3. SCHWITZ-ALGORITHMUS 2.0 (Kreuzkorrelation)
   - Temp↑ UND Feucht↑ = Schwitzen (Körperwärme + Transpiration)
   - NUR Feucht↑ (Temp konstant) = Leck oder Raum-Feuchtigkeit
   - Viel präziser als reine Feuchtigkeits-Schwellwerte

MODULARER ANSATZ:
  - DS18B20 (Pflicht) → Basistemperatur, Präsenz via Varianz
  - SHT41 Temp (Optional) → Isolations-Erkennung, Schwitz 2.0
  - SHT41 Feucht (Optional) → Schwitz-Erkennung, Leckage
  - Fehlt ein Sensor, wird das Feature einfach nicht berechnet
"""

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Dict

from homeassistant.helpers.storage import Store
from .const import local_now
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = "rejuvenation_bed_intelligence"


# ═══════════════════════════════════════════════════════════════════════════════
# KALIBRIERUNGSDATEN
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class CalibrationData:
    """Gelernte Schwellwerte aus der Kalibrierungsphase."""

    # Status
    is_calibrated: bool = False
    calibration_started: Optional[str] = None    # ISO datetime
    calibration_completed: Optional[str] = None
    samples_collected: int = 0
    min_samples_required: int = 500  # ~4h bei 30s Updates

    # Gelernte Werte: Wassertemp-Varianz
    water_std_empty_mean: float = 0.022          # σ wenn Bett leer
    water_std_empty_max: float = 0.035           # Maximales σ bei leer
    water_std_occupied_min: float = 0.050        # Minimales σ bei belegt
    water_std_threshold: float = 0.040           # Berechnete Schwelle

    # Gelernte Werte: Isolations-Check (Δ Wasser-Luft)
    delta_covered_mean: float = 0.5              # Δ wenn zugedeckt
    delta_uncovered_mean: float = 3.0            # Δ wenn offen
    delta_isolation_threshold: float = 2.0        # Schwelle für "offen"

    # Gelernte Werte: Feuchtigkeit
    humidity_baseline: float = 40.0              # Leer-Bett Baseline
    humidity_occupied_normal: float = 60.0       # Normal unter Decke
    humidity_sweat_threshold: float = 93.0       # Ab hier = stark feucht

    # Roh-Daten für Kalibrierung (werden nach Abschluss gelöscht)
    _empty_water_stds: list = field(default_factory=list)
    _occupied_water_stds: list = field(default_factory=list)
    _empty_deltas: list = field(default_factory=list)
    _covered_deltas: list = field(default_factory=list)
    _empty_humidities: list = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialisiert für Storage (inklusive Rohdaten während Lernphase!)."""
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
        # Rohdaten mitspeichern wenn noch in Lernphase!
        if not self.is_calibrated:
            d["raw_empty_water_stds"] = self._empty_water_stds
            d["raw_occupied_water_stds"] = self._occupied_water_stds
            d["raw_empty_deltas"] = self._empty_deltas
            d["raw_covered_deltas"] = self._covered_deltas
            d["raw_empty_humidities"] = self._empty_humidities
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "CalibrationData":
        """Deserialisiert aus Storage (inklusive Rohdaten)."""
        cal = cls()
        for key, val in data.items():
            if key.startswith("raw_"):
                # Rohdaten wiederherstellen
                attr = f"_{key[4:]}"  # raw_empty_water_stds → _empty_water_stds
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
    is_covered: bool = True                      # Bett zugedeckt?
    delta_water_air: float = 0.0                 # Δ(Wasser - Luft) aktuell
    uncovered_since: Optional[datetime] = None   # Seit wann offen?
    uncovered_minutes: float = 0.0               # Wie lange offen?
    energy_waste_warning: bool = False            # >30min offen = Warnung
    level: str = "unbekannt"                      # gut / mäßig / schlecht / offen


# ═══════════════════════════════════════════════════════════════════════════════
# SCHWITZ-STATUS 2.0
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SweatStatus:
    """Detaillierter Schwitz-Status mit Kreuzkorrelation."""
    is_sweating: bool = False
    is_moist: bool = False                         # >93% = stark feucht (Schwitzen)
    humidity_level: str = "unbekannt"            # trocken/normal/feucht/...
    current_humidity: float = 0.0
    humidity_baseline: float = 40.0
    humidity_rise: float = 0.0
    cause: str = "normal"                        # normal/schwitzen/leck_verdacht/raum


# ═══════════════════════════════════════════════════════════════════════════════
# HAUPT-KLASSE
# ═══════════════════════════════════════════════════════════════════════════════

class BedIntelligence:
    """
    Zentrale Intelligenz-Engine für das Rejuvenation Bed.

    Modularer Ansatz:
    - DS18B20 (Pflicht) → Basis-Funktionen immer verfügbar
    - SHT41 Temp (Optional) → Isolations-Erkennung freigeschaltet
    - SHT41 Feucht (Optional) → Schwitz 2.0 freigeschaltet

    Lernt automatisch die optimalen Schwellwerte für jedes Bett.
    """

    def __init__(self, hass, config_entry):
        self.hass = hass
        self.config_entry = config_entry
        self._store = Store(
            hass, STORAGE_VERSION,
            f"{STORAGE_KEY}_{config_entry.entry_id}"
        )

        # Kalibrierungsdaten
        self.calibration = CalibrationData()

        # Rolling-Buffer (für Kreuzkorrelation und Trends)
        self._water_temps: Dict[int, deque] = {}
        self._air_temps: Dict[int, deque] = {}
        self._humidities: Dict[int, deque] = {}
        self._max_buffer = 720  # ~6h bei 30s

        # Aktueller Status pro Zone
        self._isolation: Dict[int, IsolationStatus] = {}
        self._sweat: Dict[int, SweatStatus] = {}

        # Isolation 2.0: Delta-History + Heizungs-Status
        self._delta_history: Dict[int, list] = {}      # [(datetime, delta)]
        self._heater_heating: Dict[int, bool] = {}     # Aktueller Heizungsstatus

        # Feature-Flags (basierend auf verfügbaren Sensoren)
        self._has_air_temp: Dict[int, bool] = {}
        self._has_humidity: Dict[int, bool] = {}

        self._loaded = False

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
            # Bedtime-History laden
            if data and "bedtime_history" in data:
                self._bedtime_history = data["bedtime_history"]
                # Keys von Strings zurück zu ints (JSON speichert Keys als Strings)
                self._bedtime_history = {
                    int(k): v for k, v in self._bedtime_history.items()
                }
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
            # Bedtime-History mitspeichern
            if hasattr(self, '_bedtime_history') and self._bedtime_history:
                save_data["bedtime_history"] = self._bedtime_history
            
            await self._store.async_save(save_data)
        except Exception as e:
            _LOGGER.error(f"BedIntelligence Save-Fehler: {e}")

    # ═══════════════════════════════════════════════════════════════════════
    # HAUPT-UPDATE (wird vom Coordinator aufgerufen)
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

        Args:
            zone_index: Zone (0 oder 1)
            water_temp: DS18B20 (Pflicht)
            air_temp: SHT41 Temp (Optional)
            humidity: SHT41 Feuchtigkeit (Optional)
            is_present: Aktueller Präsenz-Status
            water_std: Aktuelle Wassertemp-Varianz (vom PresenceDetector)
        """
        now = local_now()

        # Feature-Flags aktualisieren (bei Ausfall zurücksetzen!)
        if air_temp is not None:
            self._has_air_temp[zone_index] = True
        else:
            # Sensor ausgefallen → Flag zurücksetzen (graceful degradation)
            if self._has_air_temp.get(zone_index, False):
                _LOGGER.info(
                    f"Zone {zone_index}: Luft-Sensor nicht mehr verfügbar → "
                    f"Isolation/Schwitz deaktiviert (Kernfunktion läuft weiter)"
                )
            self._has_air_temp[zone_index] = False
            
        if humidity is not None:
            self._has_humidity[zone_index] = True
        else:
            if self._has_humidity.get(zone_index, False):
                _LOGGER.info(
                    f"Zone {zone_index}: Feuchte-Sensor nicht mehr verfügbar → "
                    f"Schwitz-Erkennung deaktiviert (Kernfunktion läuft weiter)"
                )
            self._has_humidity[zone_index] = False

        # Daten speichern
        self._store_reading(zone_index, water_temp, air_temp, humidity, now)

        # 1. Auto-Kalibrierung
        if not self.calibration.is_calibrated:
            self._update_calibration(zone_index, water_temp, air_temp,
                                     humidity, is_present, water_std, now)
        else:
            self._update_drift_correction(zone_index, water_temp, air_temp,
                                          humidity, is_present, water_std, now)

        # 2. Isolations-Erkennung (nur wenn BEIDE Werte vorhanden)
        if self._has_air_temp.get(zone_index, False) and water_temp is not None and air_temp is not None:
            self._update_isolation(zone_index, water_temp, air_temp, is_present, now)

        # 3. Schwitz-Algorithmus 2.0 (nur wenn BEIDE Werte vorhanden)
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
        """
        Sammelt Daten für die Auto-Kalibrierung.

        Strategie:
        - Sammle σ(Wasser) während "leer" und "belegt" Phasen
        - Sammle Δ(Wasser-Luft) während "offen" und "zugedeckt"
        - Nach genug Samples: Berechne optimale Schwellwerte
        """
        cal = self.calibration

        if cal.calibration_started is None:
            cal.calibration_started = now.isoformat()
            _LOGGER.info("🧠 Auto-Kalibrierung gestartet – sammle Daten...")

        # Nur valide Samples zählen
        if water_std <= 0 or water_temp is None:
            return
        
        # Ausreißer-Filter (ESP-Glitch, Sensor-Boot)
        if not (15.0 <= water_temp <= 40.0):
            _LOGGER.debug(f"Kalibrierung: Ausreißer water_temp={water_temp}°C ignoriert")
            return
        if air_temp is not None and not (10.0 <= air_temp <= 45.0):
            _LOGGER.debug(f"Kalibrierung: Ausreißer air_temp={air_temp}°C ignoriert")
            return

        cal.samples_collected += 1

        # Wasser-Varianz sammeln (getrennt nach Präsenz)
        if is_present:
            cal._occupied_water_stds.append(water_std)
        else:
            cal._empty_water_stds.append(water_std)

        # Feuchtigkeit bei leerem Bett (für Baseline)
        if not is_present and humidity is not None:
            cal._empty_humidities.append(humidity)

        # Delta (Wasser - Luft) sammeln
        if air_temp is not None and water_temp is not None:
            delta = water_temp - air_temp
            if is_present:
                cal._covered_deltas.append(delta)  # Unter Decke: Delta klein
            else:
                cal._empty_deltas.append(delta)     # Offen: Delta kann groß sein

        # Prüfe ob genug Daten für Kalibrierung
        # Brauchen mindestens: 200 empty + 100 occupied Samples
        if (len(cal._empty_water_stds) >= 200
                and len(cal._occupied_water_stds) >= 100):
            self._finalize_calibration(now)
        elif cal.samples_collected % 50 == 0:
            # Alle 50 Samples zwischenspeichern (überlebt HA-Restart!)
            if self.hass:
                self.hass.async_create_task(self.async_save())

    def _finalize_calibration(self, now: datetime):
        """Berechnet optimale Schwellwerte aus den gesammelten Daten."""
        cal = self.calibration

        # ─── Wasser-Varianz Schwellwert ───
        empty_stds = sorted(cal._empty_water_stds)
        occupied_stds = sorted(cal._occupied_water_stds)

        cal.water_std_empty_mean = sum(empty_stds) / len(empty_stds)
        cal.water_std_empty_max = empty_stds[int(len(empty_stds) * 0.95)]
        cal.water_std_occupied_min = occupied_stds[int(len(occupied_stds) * 0.10)]

        # Schwelle = Mitte zwischen Max-leer und Min-belegt
        cal.water_std_threshold = (
            cal.water_std_empty_max + cal.water_std_occupied_min
        ) / 2

        # Sicherheits-Check: Schwelle muss zwischen den Bereichen liegen
        if cal.water_std_threshold <= cal.water_std_empty_mean:
            cal.water_std_threshold = cal.water_std_empty_max * 1.2

        _LOGGER.info(
            f"🧠 Kalibriert: σ(leer)={cal.water_std_empty_mean:.4f}, "
            f"σ(belegt)={cal.water_std_occupied_min:.4f}, "
            f"Schwelle={cal.water_std_threshold:.4f}"
        )

        # ─── Isolations-Schwellwert ───
        if cal._covered_deltas and cal._empty_deltas:
            cal.delta_covered_mean = sum(cal._covered_deltas) / len(cal._covered_deltas)
            cal.delta_uncovered_mean = sum(cal._empty_deltas) / len(cal._empty_deltas)

            # Schwelle = wenn Delta deutlich über "zugedeckt" liegt
            cal.delta_isolation_threshold = cal.delta_covered_mean + (
                (cal.delta_uncovered_mean - cal.delta_covered_mean) * 0.4
            )

            # Minimum 1.5°C Differenz für "offen"
            cal.delta_isolation_threshold = max(1.5, cal.delta_isolation_threshold)

            _LOGGER.info(
                f"🧠 Isolation: Δ(zugedeckt)={cal.delta_covered_mean:.2f}°C, "
                f"Δ(offen)={cal.delta_uncovered_mean:.2f}°C, "
                f"Schwelle={cal.delta_isolation_threshold:.2f}°C"
            )

        # ─── Feuchtigkeit-Baseline ───
        if cal._empty_humidities:
            sorted_hum = sorted(cal._empty_humidities)
            cal.humidity_baseline = sorted_hum[int(len(sorted_hum) * 0.50)]
            _LOGGER.info(f"🧠 Feucht-Baseline: {cal.humidity_baseline:.1f}%")

        # Abschließen
        cal.is_calibrated = True
        cal.calibration_completed = now.isoformat()

        # Roh-Daten löschen (sparen Speicher)
        cal._empty_water_stds = []
        cal._occupied_water_stds = []
        cal._empty_deltas = []
        cal._covered_deltas = []
        cal._empty_humidities = []

        _LOGGER.info(
            f"✅ Auto-Kalibrierung abgeschlossen nach "
            f"{cal.samples_collected} Samples!"
        )

        # Asynchron speichern
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
        """
        Nachkalibrierung: Langsame Drift-Korrektur für saisonale Änderungen.
        
        Im Sommer sind die Baseline-Werte anders als im Winter.
        Statt die Kalibrierung komplett neu zu machen, passen wir
        die Schwellwerte alle ~500 Samples leicht an (EMA = Exponential Moving Average).
        
        Ausreißer-Schutz: Werte außerhalb plausibler Grenzen werden ignoriert.
        """
        cal = self.calibration
        
        # ─── Ausreißer-Filter ───
        # Plausible Bereiche für ein Wasserbett
        if water_temp is not None and not (15.0 <= water_temp <= 40.0):
            _LOGGER.debug(f"Ausreißer ignoriert: water_temp={water_temp}°C")
            return
        if air_temp is not None and not (10.0 <= air_temp <= 45.0):
            _LOGGER.debug(f"Ausreißer ignoriert: air_temp={air_temp}°C")
            return
        if humidity is not None and not (10.0 <= humidity <= 100.0):
            return
        if water_std <= 0 or water_temp is None:
            return

        # Drift-Counter hochzählen
        if not hasattr(cal, '_drift_counter'):
            cal._drift_counter = 0
            cal._drift_empty_stds = []
            cal._drift_occupied_stds = []
        
        cal._drift_counter += 1
        
        # Samples sammeln
        if is_present:
            cal._drift_occupied_stds.append(water_std)
            if len(cal._drift_occupied_stds) > 200:
                cal._drift_occupied_stds = cal._drift_occupied_stds[-200:]
        else:
            cal._drift_empty_stds.append(water_std)
            if len(cal._drift_empty_stds) > 200:
                cal._drift_empty_stds = cal._drift_empty_stds[-200:]
        
        # Alle 500 Samples: Schwellwerte sanft anpassen
        if cal._drift_counter >= 500:
            cal._drift_counter = 0
            alpha = 0.15  # Lernrate: 15% neue Daten, 85% alte Werte
            
            if len(cal._drift_empty_stds) >= 50 and len(cal._drift_occupied_stds) >= 30:
                new_empty = sorted(cal._drift_empty_stds)
                new_occupied = sorted(cal._drift_occupied_stds)
                
                new_empty_max = new_empty[int(len(new_empty) * 0.95)]
                new_occupied_min = new_occupied[int(len(new_occupied) * 0.10)]
                new_threshold = (new_empty_max + new_occupied_min) / 2
                
                old_threshold = cal.water_std_threshold
                cal.water_std_threshold = (1 - alpha) * old_threshold + alpha * new_threshold
                
                _LOGGER.info(
                    f"🔄 Drift-Korrektur: Schwelle {old_threshold:.4f} → "
                    f"{cal.water_std_threshold:.4f} (α={alpha})"
                )
                
                # Speichern
                if self.hass:
                    self.hass.async_create_task(self.async_save())

    # ═══════════════════════════════════════════════════════════════════════
    # 2. ISOLATIONS-ERKENNUNG (Decken-Check)
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

        KALIBRIERT auf 4.592 echte Messdaten (SHT41 OBEN auf Kern):
        
        ╔═══════════════════════════════════════════════════════╗
        ║  Δ = Wasser - Luft                                   ║
        ║                                                       ║
        ║  Decke + Person:    Δ ≈ -0.3°C (Körper heizt Luft)  ║
        ║  Decke + Leer:      Δ ≈  0.0°C (gleichen sich an)   ║
        ║  OFFEN + Heiz aus:  Δ ≈ +0.5°C (Luft kühlt weg)    ║
        ║  OFFEN + Heiz an:   Δ ≈ +0.5°C                      ║
        ║  Decke + Heiz an:   Δ ≈ +0.7°C ← FALLE!            ║
        ║                                                       ║
        ║  → Heizung VERZERRT das Delta nach oben!              ║
        ║  → Muss rausgerechnet werden                          ║
        ║  → Schwelle: Δ > +0.3°C = offen (heizkorrigiert)    ║
        ╚═══════════════════════════════════════════════════════╝
        """
        # Safety: Wenn air_temp doch None ist (Sensor zwischenzeitlich ausgefallen)
        if air_temp is None or water_temp is None:
            return
            
        if zone_index not in self._isolation:
            self._isolation[zone_index] = IsolationStatus()

        iso = self._isolation[zone_index]
        delta = water_temp - air_temp
        iso.delta_water_air = round(delta, 2)

        # ─── Heizungs-Korrektur ───
        # Wenn Heizung aktiv: Wasser wird von UNTEN geheizt, Delta steigt
        # um ca. +0.4°C auch MIT Decke drauf. Das müssen wir abziehen.
        heater_active = self._heater_heating.get(zone_index, False)
        heater_correction = 0.4 if heater_active else 0.0
        corrected_delta = delta - heater_correction

        # ─── Langzeit-Delta-Mittelwert (30min) für Stabilität ───
        delta_history = self._delta_history.get(zone_index, [])
        delta_history.append((now, corrected_delta))
        cutoff = now - timedelta(minutes=30)
        delta_history = [(t, v) for t, v in delta_history if t > cutoff]
        self._delta_history[zone_index] = delta_history

        if len(delta_history) >= 3:
            avg_delta = sum(v for _, v in delta_history) / len(delta_history)
        else:
            avg_delta = corrected_delta

        # ═══ ENTSCHEIDUNG basierend auf korrigiertem Langzeit-Delta ═══
        #
        # Echte Messdaten:
        #   Decke + Person:  avg_delta ≈ -0.3°C  
        #   Decke + Leer:    avg_delta ≈  0.0°C
        #   OFFEN:           avg_delta ≈ +0.5°C (nach Heizkorrektur)
        #
        # Schwelle bei +0.25°C mit Hysterese

        if avg_delta < 0.15:
            iso.level = "gut"
            iso.is_covered = True
        elif avg_delta < 0.25:
            iso.level = "mäßig"
            iso.is_covered = True
        elif avg_delta < 0.40:
            # Hysterese: Nur auf "offen" wechseln wenn vorher "gut"/"mäßig"
            # Bleibt auf "mäßig" wenn schon offen war (verhindert Flackern)
            if iso.is_covered:
                iso.level = "mäßig"
                iso.is_covered = True
            else:
                iso.level = "schlecht"
                iso.is_covered = False
        else:
            iso.level = "offen"
            iso.is_covered = False

        # Timer für offenes Bett
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
    # 3. SCHWITZ-ALGORITHMUS 2.0 (Kreuzkorrelation)
    # ═══════════════════════════════════════════════════════════════════════

    def _update_sweat(
        self,
        zone_index: int,
        air_temp: Optional[float],
        humidity: float,
        is_present: bool,
        now: datetime,
    ):
        """
        Schwitz-Erkennung mit Kreuzkorrelation Temperatur × Feuchtigkeit.

        Unterscheidet:
        1. Temp↑ UND Feucht↑ = Person schwitzt (Körperwärme + Transpiration)
        2. NUR Feucht↑ (Temp stabil) = Leck oder Raum-Feuchtigkeit
        3. Temp↑ ohne Feucht↑ = Nur warm, kein Schwitzen
        """
        # Safety: Wenn humidity doch None ist
        if humidity is None:
            return
            
        if zone_index not in self._sweat:
            self._sweat[zone_index] = SweatStatus()

        sweat = self._sweat[zone_index]
        sweat.current_humidity = round(humidity, 1)
        sweat.humidity_baseline = self.calibration.humidity_baseline

        # Feuchtigkeit-Level (immer berechnen)
        sweat.humidity_level = self._calc_humidity_level(humidity)

        # Feuchtigkeit-Anstieg über Baseline
        rise = humidity - self.calibration.humidity_baseline
        sweat.humidity_rise = round(rise, 1)

        # Reset wenn niemand im Bett
        if not is_present:
            sweat.is_sweating = False
            sweat.is_moist = False
            sweat.cause = "leer"
            return

        # ─── Kreuzkorrelation ───
        has_temp_rise = False
        has_humidity_rise = humidity > 70  # Deutlich erhöht

        if air_temp is not None and self._has_air_temp.get(zone_index):
            # Luft-Temp Trend der letzten 30 Min
            air_buf = self._air_temps.get(zone_index, deque())
            if len(air_buf) >= 10:
                cutoff = now - timedelta(minutes=30)
                recent = [v for ts, v in air_buf if ts > cutoff and v is not None]
                if len(recent) >= 5:
                    temp_change = recent[-1] - recent[0]
                    has_temp_rise = temp_change > 0.3  # >0.3°C in 30min

        # ─── Ursachen-Bestimmung ───
        if humidity > self.calibration.humidity_sweat_threshold:
            # >93%: Definitiv STARK FEUCHT
            sweat.is_moist = True
            if has_temp_rise:
                sweat.is_sweating = True
                sweat.cause = "schwitzen"
            else:
                sweat.is_sweating = False
                sweat.cause = "leck_verdacht"
        elif has_temp_rise and has_humidity_rise:
            # Temp steigt UND Feuchtigkeit erhöht → Schwitzen
            sweat.is_sweating = True
            sweat.is_moist = False
            sweat.cause = "schwitzen"
        elif has_humidity_rise and not has_temp_rise:
            # Nur Feuchtigkeit erhöht → wahrscheinlich Raum
            sweat.is_sweating = False
            sweat.is_moist = False
            sweat.cause = "raum_feuchtigkeit"
        else:
            # Alles normal
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
        progress = min(100, int(
            (min(empty_count, 200) + min(occupied_count, 100)) / 3
        ))

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
        bedtime_pred = self.predict_bedtime(zone_index)

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
                "level": iso.level,
                "uncovered_minutes": round(iso.uncovered_minutes, 1),
                "energy_waste_warning": iso.energy_waste_warning,
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
    # BEDTIME LEARNING: System lernt wann du typisch ins Bett gehst
    # ═══════════════════════════════════════════════════════════════════════
    
    _BEDTIME_HISTORY_DAYS = 28  # 4 Wochen Historie behalten
    _MIN_SAMPLES_FOR_PREDICTION = 3  # Mindestens 3 Nächte für Vorhersage

    def record_bedtime(self, zone_index: int, bedtime: datetime):
        """
        Speichert eine Einschlafzeit für das Lernmodell.
        
        Wird vom Coordinator aufgerufen wenn actual_bedtime erkannt wird.
        Speichert Wochentag + Uhrzeit für Muster-Erkennung.
        """
        if "bedtime_history" not in self.__dict__:
            self._bedtime_history = {}
        
        history = self._bedtime_history.setdefault(zone_index, [])
        
        # Uhrzeit in Minuten seit Mitternacht (mit Überlauf: 23:30 = 1410, 00:30 = 1470)
        minutes = bedtime.hour * 60 + bedtime.minute
        if minutes < 720:  # Vor 12:00 → gehört zur Vornacht (z.B. 00:30 = ging spät ins Bett)
            minutes += 1440  # +24h damit Sortierung stimmt
        
        # Session-Key: Datum + Tageszeit-Bereich
        # Wer nach Mitternacht einschläft, gehört zum Vortag (gleiche Schlaf-Session).
        # Wer um 14:00 einschläft (Schichtarbeiter), bekommt sein eigenes Datum.
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
        
        # Duplikat-Check (nur eine Einschlafzeit pro Session-Key)
        history = [h for h in history if h["date"] != session_key]
        history.append(entry)
        
        # Auf N Tage begrenzen
        cutoff = local_now() - timedelta(days=self._BEDTIME_HISTORY_DAYS)
        cutoff_str = cutoff.strftime("%Y-%m-%d")
        history = [h for h in history if h["date"] >= cutoff_str]
        
        self._bedtime_history[zone_index] = history
        
        _LOGGER.info(
            f"Zone {zone_index}: Einschlafzeit gelernt: {entry['time_str']} "
            f"({'Wochenende' if session_date.weekday() >= 4 else 'Wochentag'}) "
            f"[{len(history)} Nächte gespeichert]"
        )
        
        # Async speichern
        if self.hass and hasattr(self.hass, 'async_create_task'):
            self.hass.async_create_task(self.async_save())

    def predict_bedtime(self, zone_index: int) -> Optional[dict]:
        """
        Sagt die wahrscheinliche Einschlafzeit vorher.
        
        Unterscheidet Wochentage (Mo-Do) und Wochenende (Fr-So).
        Nutzt Median statt Durchschnitt (robust gegen Ausreißer).
        
        Returns:
            Dict mit predicted_time, confidence, basis oder None
        """
        if not hasattr(self, '_bedtime_history'):
            return None
            
        history = self._bedtime_history.get(zone_index, [])
        if len(history) < self._MIN_SAMPLES_FOR_PREDICTION:
            return None
        
        now = local_now()
        is_weekend = now.weekday() >= 4  # Fr, Sa, So
        
        # Einträge filtern: Wochentag vs. Wochenende
        if is_weekend:
            relevant = [h for h in history if h["weekday"] >= 4]
            day_type = "Wochenende"
        else:
            relevant = [h for h in history if h["weekday"] < 4]
            day_type = "Wochentag"
        
        # Fallback: Wenn für diesen Typ zu wenig Daten, alle nehmen
        if len(relevant) < self._MIN_SAMPLES_FOR_PREDICTION:
            relevant = history
            day_type = "Alle Tage"
        
        # Median berechnen (robust gegen "eine Nacht bis 3 Uhr wach")
        minutes_list = sorted([h["minutes"] for h in relevant])
        n = len(minutes_list)
        if n % 2 == 0:
            median_min = (minutes_list[n // 2 - 1] + minutes_list[n // 2]) / 2
        else:
            median_min = minutes_list[n // 2]
        
        # Zurück in Uhrzeit (Überlauf beachten: >1440 = nächster Tag)
        pred_min = int(median_min) % 1440
        pred_hour = pred_min // 60
        pred_minute = pred_min % 60
        
        # Streuung (IQR) für Konfidenz
        q1 = minutes_list[n // 4] if n >= 4 else minutes_list[0]
        q3 = minutes_list[3 * n // 4] if n >= 4 else minutes_list[-1]
        spread_min = q3 - q1  # Interquartilsabstand
        
        # Konfidenz: Je enger die Streuung, desto sicherer
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
        }

    def get_predicted_preheat_start(
        self,
        zone_index: int,
        preheat_hours: float = 3.0,
        configured_warm_from: Optional[str] = None
    ) -> Optional[str]:
        """
        Berechnet den optimalen Vorheiz-Start basierend auf gelernter Einschlafzeit.
        
        Args:
            zone_index: Zone
            preheat_hours: Vorlaufzeit zum Aufheizen
            configured_warm_from: Konfigurierte Fallback-Zeit (z.B. "22:00")
        
        Returns:
            Vorheiz-Startzeit als "HH:MM" String oder None (= konfigurierte Zeit nutzen)
        """
        prediction = self.predict_bedtime(zone_index)
        if prediction is None or prediction["confidence"] == "niedrig":
            return None  # Zu unsicher → konfigurierte Zeit nutzen
        
        pred_time = prediction["predicted_time"]
        pred_minutes = pred_time.hour * 60 + pred_time.minute
        
        # Vorheizstart = Einschlafzeit - Vorlauf - 30 Min Puffer
        preheat_start_min = pred_minutes - int(preheat_hours * 60) - 30
        
        # Konfigurierte warm_from als Sicherheits-Grenze
        if configured_warm_from:
            parts = configured_warm_from.split(":")
            config_min = int(parts[0]) * 60 + (int(parts[1]) if len(parts) > 1 else 0)
            # Nie SPÄTER vorheizen als konfiguriert (nur FRÜHER ist OK)
            preheat_start_min = min(preheat_start_min, config_min)
        
        # Normalisieren
        preheat_start_min = preheat_start_min % 1440
        start_h = preheat_start_min // 60
        start_m = preheat_start_min % 60
        
        _LOGGER.debug(
            f"Zone {zone_index}: Lernbasiertes Vorheizen ab {start_h:02d}:{start_m:02d} "
            f"(Einschlafzeit ~{prediction['predicted_str']}, "
            f"Vorlauf {preheat_hours}h + 30min Puffer)"
        )
        
        return f"{start_h:02d}:{start_m:02d}"

    def get_bedtime_diagnostics(self, zone_index: int) -> dict:
        """Debug-Info für Bedtime Learning."""
        if not hasattr(self, '_bedtime_history'):
            return {"status": "Keine Daten", "nights_recorded": 0}
        
        history = self._bedtime_history.get(zone_index, [])
        prediction = self.predict_bedtime(zone_index)
        
        result = {
            "nights_recorded": len(history),
            "min_required": self._MIN_SAMPLES_FOR_PREDICTION,
        }
        
        if history:
            recent = history[-5:]  # Letzte 5 Nächte
            result["recent_bedtimes"] = [
                f"{h['time_str']} ({'WE' if h['weekday'] >= 4 else 'WT'})"
                for h in recent
            ]
        
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
