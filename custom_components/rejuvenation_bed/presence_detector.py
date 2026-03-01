"""
Presence-Detector v3 für das Rejuvenation Bed.

KERN-ERKENNTNIS (aus Messdaten Feb 2026):
  Bewegung im Wasserbett → Wasserwellen → DS18B20 schwankt
  Leeres Bett → Wasser ruhig → DS18B20 stabil (σ < 0.03°C)
  Person im Bett → Wasser unruhig → DS18B20 instabil (σ > 0.04°C)

PRIMÄR-INDIKATOR: Wassertemperatur-Varianz (σ über 20min)
  → Funktioniert mit NUR dem Wassertemp-Sensor!
  → 97.5% Precision, 74% Recall bei σ > 0.04°C

SEKUNDÄR (wenn verfügbar):
  - Luft-Temp-Varianz (SHT41): Verstärkt Signal
  - Feuchtigkeit: Nur für Leckage-Erkennung (NICHT für Präsenz!)

SCHWITZ-ERKENNUNG: Nur bei echtem Schwitzen (>75% absolut UND Anstieg)
"""

import logging
from collections import deque
from datetime import datetime, timedelta
from typing import Optional, Tuple
from dataclasses import dataclass

_LOGGER = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# KALIBRIERTE SCHWELLWERTE (Feb 2026, Doppelbett 2x2m, 1 Heizung aktiv)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class PresenceThresholds:
    """Kalibrierte Schwellwerte aus echten Messdaten."""

    # PRIMÄR: Wassertemp-Varianz (DS18B20)
    # Leeres Bett:  σ = 0.018 - 0.025°C (ruhiges Wasser)
    # Person drin:  σ = 0.050 - 0.200°C (Wasserwellen)
    water_variance_threshold: float = 0.040   # σ > 0.04 = Präsenz (97.5% Precision)

    # SEKUNDÄR: Luft-Temp-Varianz (SHT41 oben auf Kern)
    # Leeres Bett:  σ = 0.007 - 0.025°C
    # Person drin:  σ = 0.050 - 0.600°C (Körperwärme, Deckenbewegung)
    air_variance_threshold: float = 0.15      # σ > 0.15 = unterstützt Präsenz

    # Analyse-Fenster
    variance_window_minutes: int = 20         # Rollierendes Fenster für σ
    min_datapoints: int = 8                   # Minimum für Auswertung (bei ~30s Updates)

    # Hysterese (verhindert Flackern!)
    presence_enter_minutes: int = 5           # Muss 5 min stabil "da" sein
    presence_leave_minutes: int = 20          # Muss 20 min stabil "weg" sein
    # → Asymmetrisch! Schnell erkennen, langsam loslassen

    # SCHWITZ-ERKENNUNG (nach User-Feedback angepasst!)
    # Feuchtigkeit 50-80% ist NORMAL wenn jemand unter der Decke liegt!
    # Über 93% = richtig NASS (Schwitzen oder Leckage)
    sweat_humidity_abs: float = 93.0          # Absolut >93% = NASS/echtes Schwitzen
    sweat_humidity_rise: float = 35.0         # Anstieg >35% über Baseline
    sweat_confirm_minutes: int = 15           # Muss 15 min anhalten
    
    # Feuchtigkeit-Stufen (für Attribut-Anzeige, nicht für binary_sensor)
    # <50%  = trocken (leeres Bett)
    # 50-70% = normal (Person unter Decke)
    # 70-85% = feucht (warm, viel Decke)
    # 85-93% = sehr feucht (Achtung)
    # >93%  = nass (Schwitzen/Alarm)

    # LECKAGE (Sicherheit)
    leak_humidity_abs: float = 85.0           # >85% über 3h = Alarm
    leak_confirm_hours: float = 3.0


class PresenceDetector:
    """
    Varianz-basierte Präsenz-Erkennung für Wasserbetten.

    Funktioniert minimal mit NUR dem Wassertemp-Sensor.
    Nutzt zusätzliche Sensoren wenn verfügbar, braucht sie aber nicht.
    """

    def __init__(self, thresholds: Optional[PresenceThresholds] = None):
        self.thresholds = thresholds or PresenceThresholds()

        # Rolling-Buffer pro Zone (speichert Rohdaten)
        self._water_temps: dict[int, deque] = {}
        self._air_temps: dict[int, deque] = {}
        self._humidity: dict[int, deque] = {}
        self._max_buffer = 600  # ~5h bei 30s Updates

        # Zustand pro Zone
        self._is_present: dict[int, bool] = {}
        self._state_since: dict[int, datetime] = {}
        self._pending_state: dict[int, Optional[bool]] = {}
        self._pending_since: dict[int, Optional[datetime]] = {}

        # Diagnostics
        self._last_water_std: dict[int, float] = {}
        self._last_air_std: dict[int, float] = {}
        self._last_confidence: dict[int, float] = {}
        self._last_reason: dict[int, str] = {}

    # ═══════════════════════════════════════════════════════════════════════
    # HAUPTFUNKTION
    # ═══════════════════════════════════════════════════════════════════════

    def detect_presence(
        self,
        zone_index: int,
        water_temp: Optional[float] = None,
        air_temp: Optional[float] = None,
        humidity: Optional[float] = None,
        power_watts: Optional[float] = None,
        heater_active: bool = False,
        presence_sensor_state: Optional[bool] = None,
    ) -> Tuple[bool, float, str]:
        """
        Erkennt ob jemand im Bett liegt.

        Minimal-Setup: Nur water_temp reicht!
        Besser mit: water_temp + air_temp
        Optional: humidity (nur für Leckage, nicht für Präsenz)

        Returns:
            (is_present, confidence, reason)
        """
        now = datetime.now()

        # Daten speichern
        self._store(zone_index, water_temp, air_temp, humidity, now)

        # ─────────────────────────────────────────────────────────────
        # Priorität 1: Dedizierter Präsenz-Sensor überschreibt alles
        # ─────────────────────────────────────────────────────────────
        if presence_sensor_state is not None:
            self._set_state(zone_index, presence_sensor_state, 1.0,
                          "Präsenz-Sensor", now)
            return presence_sensor_state, 1.0, "Präsenz-Sensor"

        # ─────────────────────────────────────────────────────────────
        # PRIMÄR: Wassertemperatur-Varianz
        # ─────────────────────────────────────────────────────────────
        water_std = self._calc_std(
            self._water_temps.get(zone_index),
            self.thresholds.variance_window_minutes
        )

        # ─────────────────────────────────────────────────────────────
        # SEKUNDÄR: Luft-Temperatur-Varianz (wenn verfügbar)
        # ─────────────────────────────────────────────────────────────
        air_std = self._calc_std(
            self._air_temps.get(zone_index),
            self.thresholds.variance_window_minutes
        )

        # Diagnostics speichern
        self._last_water_std[zone_index] = water_std or 0.0
        self._last_air_std[zone_index] = air_std or 0.0

        # ─────────────────────────────────────────────────────────────
        # Entscheidungslogik
        # ─────────────────────────────────────────────────────────────
        if water_std is None:
            # Nicht genug Daten
            current = self._is_present.get(zone_index, False)
            return current, 0.0, "Sammle Daten..."

        raw_present = False
        confidence = 0.0
        reasons = []

        # Primär: Wasser-Varianz
        wt = self.thresholds.water_variance_threshold
        if water_std > wt * 2:
            confidence = 0.95
            raw_present = True
            reasons.append(f"σW={water_std:.3f}°C(stark)")
        elif water_std > wt:
            confidence = 0.75
            raw_present = True
            reasons.append(f"σW={water_std:.3f}°C")
        elif water_std > wt * 0.7:
            confidence = 0.40
            reasons.append(f"σW={water_std:.3f}°C(grenz)")
        else:
            confidence = 0.10
            reasons.append(f"σW={water_std:.3f}°C(ruhig)")

        # Sekundär: Luft-Varianz (nur verstärkend, nie allein entscheidend)
        if air_std is not None:
            at = self.thresholds.air_variance_threshold
            if air_std > at:
                confidence = min(1.0, confidence + 0.15)
                if not raw_present and air_std > at * 2:
                    raw_present = True  # Sehr starke Luft-Varianz kann überstimmen
                reasons.append(f"σL={air_std:.3f}°C")

        # ─────────────────────────────────────────────────────────────
        # Hysterese: Asymmetrisch (schnell rein, langsam raus)
        # ─────────────────────────────────────────────────────────────
        is_present = self._apply_hysteresis(zone_index, raw_present, now)

        reason = f"{'🛏️' if is_present else '○'} {', '.join(reasons)}"
        self._set_state(zone_index, is_present, confidence, reason, now)

        return is_present, round(confidence, 2), reason

    # ═══════════════════════════════════════════════════════════════════════
    # VARIANZ-BERECHNUNG
    # ═══════════════════════════════════════════════════════════════════════

    def _calc_std(
        self, buffer: Optional[deque], window_minutes: int
    ) -> Optional[float]:
        """Berechnet Standardabweichung über rollendes Zeitfenster."""
        if buffer is None or len(buffer) < self.thresholds.min_datapoints:
            return None

        cutoff = datetime.now() - timedelta(minutes=window_minutes)
        values = [val for ts, val in buffer if ts > cutoff and val is not None]

        if len(values) < self.thresholds.min_datapoints:
            return None

        # Numpy-freie Berechnung
        n = len(values)
        mean = sum(values) / n
        variance = sum((x - mean) ** 2 for x in values) / n
        return variance ** 0.5

    # ═══════════════════════════════════════════════════════════════════════
    # HYSTERESE (Anti-Flacker)
    # ═══════════════════════════════════════════════════════════════════════

    def _apply_hysteresis(
        self, zone_index: int, raw_present: bool, now: datetime
    ) -> bool:
        """
        Asymmetrische Hysterese:
        - Einsteigen: 5 Min konstant "da" → State wechselt zu ON
        - Aussteigen: 20 Min konstant "weg" → State wechselt zu OFF
        """
        current = self._is_present.get(zone_index, False)
        pending = self._pending_state.get(zone_index)
        pending_since = self._pending_since.get(zone_index)

        if raw_present == current:
            # Gleicher Zustand → Pending resetten
            self._pending_state[zone_index] = None
            self._pending_since[zone_index] = None
            return current

        # Neuer Zustand erkannt
        if pending != raw_present:
            # Erster Frame mit neuem Zustand → Timer starten
            self._pending_state[zone_index] = raw_present
            self._pending_since[zone_index] = now
            return current

        # Pending läuft → prüfe ob Wartezeit abgelaufen
        elapsed = (now - pending_since).total_seconds() / 60

        if raw_present:
            # Einsteigen: kurze Wartezeit
            required = self.thresholds.presence_enter_minutes
        else:
            # Aussteigen: lange Wartezeit
            required = self.thresholds.presence_leave_minutes

        if elapsed >= required:
            # Wartezeit abgelaufen → Zustand wechseln
            self._pending_state[zone_index] = None
            self._pending_since[zone_index] = None
            return raw_present

        return current  # Noch warten

    # ═══════════════════════════════════════════════════════════════════════
    # SCHWITZ-ERKENNUNG (konservativ!)
    # ═══════════════════════════════════════════════════════════════════════

    def is_sweating(self, zone_index: int) -> bool:
        """
        Erkennt ECHTES Schwitzen/Nässe – nicht einfach "Feuchtigkeit erhöht".

        Feuchtigkeit 50-85% ist NORMAL wenn jemand unter der Decke liegt!
        Erst ab 93% absolut UND >35% Anstieg über Baseline = NASS.
        Muss außerdem 15 Minuten anhalten.
        """
        buffer = self._humidity.get(zone_index)
        if not buffer or len(buffer) < self.thresholds.min_datapoints:
            return False

        now = datetime.now()

        # Letzte 15 Minuten
        recent_cutoff = now - timedelta(
            minutes=self.thresholds.sweat_confirm_minutes
        )
        recent = [val for ts, val in buffer if ts > recent_cutoff and val is not None]
        if len(recent) < 5:
            return False

        avg_recent = sum(recent) / len(recent)

        # Baseline: Minimum der letzten 6 Stunden
        baseline_cutoff = now - timedelta(hours=6)
        all_vals = [val for ts, val in buffer if ts > baseline_cutoff and val is not None]
        if not all_vals:
            return False

        baseline = min(all_vals)
        rise = avg_recent - baseline

        # BEIDE Bedingungen müssen erfüllt sein:
        # 1. Absoluter Wert über 75%
        # 2. Anstieg über 25% gegenüber Baseline
        return (
            avg_recent > self.thresholds.sweat_humidity_abs
            and rise > self.thresholds.sweat_humidity_rise
        )

    def get_humidity_level(self, zone_index: int) -> str:
        """
        Gibt die aktuelle Feuchtigkeitsstufe zurück.

        Stufen:
          <50%  = trocken
          50-70% = normal
          70-85% = feucht
          85-93% = sehr feucht
          >93%  = nass
        """
        buffer = self._humidity.get(zone_index)
        if not buffer or len(buffer) < 3:
            return "unbekannt"

        recent = [val for _, val in list(buffer)[-5:] if val is not None]
        if not recent:
            return "unbekannt"

        avg = sum(recent) / len(recent)

        if avg > 93:
            return "nass"
        elif avg > 85:
            return "sehr feucht"
        elif avg > 70:
            return "feucht"
        elif avg > 50:
            return "normal"
        else:
            return "trocken"

    # ═══════════════════════════════════════════════════════════════════════
    # LECKAGE-ERKENNUNG
    # ═══════════════════════════════════════════════════════════════════════

    def is_potential_leak(self, zone_index: int) -> bool:
        """
        Erkennt mögliche Leckage: Feuchtigkeit >85% über 3 Stunden.
        """
        buffer = self._humidity.get(zone_index)
        if not buffer:
            return False

        now = datetime.now()
        cutoff = now - timedelta(hours=self.thresholds.leak_confirm_hours)
        last_3h = [val for ts, val in buffer if ts > cutoff and val is not None]

        if len(last_3h) < 30:
            return False

        return all(v > self.thresholds.leak_humidity_abs for v in last_3h)

    # ═══════════════════════════════════════════════════════════════════════
    # HILFSFUNKTIONEN
    # ═══════════════════════════════════════════════════════════════════════

    def _store(
        self,
        zone_index: int,
        water_temp: Optional[float],
        air_temp: Optional[float],
        humidity: Optional[float],
        now: datetime,
    ):
        """Speichert Sensor-Werte in die Rolling-Buffer."""
        if zone_index not in self._water_temps:
            self._water_temps[zone_index] = deque(maxlen=self._max_buffer)
            self._air_temps[zone_index] = deque(maxlen=self._max_buffer)
            self._humidity[zone_index] = deque(maxlen=self._max_buffer)

        if water_temp is not None:
            self._water_temps[zone_index].append((now, water_temp))
        if air_temp is not None:
            self._air_temps[zone_index].append((now, air_temp))
        if humidity is not None:
            self._humidity[zone_index].append((now, humidity))

    def _set_state(
        self,
        zone_index: int,
        is_present: bool,
        confidence: float,
        reason: str,
        now: datetime,
    ):
        """Aktualisiert internen Zustand."""
        old = self._is_present.get(zone_index)
        if old != is_present:
            self._state_since[zone_index] = now
            if is_present:
                _LOGGER.info(f"🛏️ Zone {zone_index}: Präsenz erkannt ({reason})")
            else:
                _LOGGER.info(f"Zone {zone_index}: Bett leer ({reason})")

        self._is_present[zone_index] = is_present
        self._last_confidence[zone_index] = confidence
        self._last_reason[zone_index] = reason

    # ═══════════════════════════════════════════════════════════════════════
    # DIAGNOSTICS
    # ═══════════════════════════════════════════════════════════════════════

    def get_diagnostics(self, zone_index: int) -> dict:
        """Detaillierte Debug-Informationen."""
        is_present = self._is_present.get(zone_index, False)
        since = self._state_since.get(zone_index)
        w_std = self._last_water_std.get(zone_index, 0.0)
        a_std = self._last_air_std.get(zone_index, 0.0)

        # Aktuelle Feuchtigkeit
        hum_buf = self._humidity.get(zone_index)
        current_humidity = None
        if hum_buf and len(hum_buf) > 0:
            current_humidity = hum_buf[-1][1]

        return {
            "is_present": is_present,
            "confidence": self._last_confidence.get(zone_index, 0.0),
            "reason": self._last_reason.get(zone_index, "Keine Daten"),
            "state_since": since.isoformat() if since else None,
            "water_temp_std": round(w_std, 4),
            "air_temp_std": round(a_std, 4),
            "water_threshold": self.thresholds.water_variance_threshold,
            "humidity": round(current_humidity, 1) if current_humidity else None,
            "is_sweating": self.is_sweating(zone_index),
            "is_leak": self.is_potential_leak(zone_index),
            "buffer_sizes": {
                "water": len(self._water_temps.get(zone_index, [])),
                "air": len(self._air_temps.get(zone_index, [])),
                "humidity": len(self._humidity.get(zone_index, [])),
            },
            "pending_state": self._pending_state.get(zone_index),
            "hysteresis": {
                "enter_min": self.thresholds.presence_enter_minutes,
                "leave_min": self.thresholds.presence_leave_minutes,
            },
        }
