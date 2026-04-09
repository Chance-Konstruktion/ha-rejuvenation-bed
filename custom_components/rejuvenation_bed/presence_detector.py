"""
Presence-Detector v4 für das Rejuvenation Bed.

KERN-ERKENNTNIS (aus Messdaten Apr 2026):
  Bett heizt allein  → Temperatur steigt GLEICHMÄSSIG (+0.0625°C/6-10min)
                      → Niedrige Varianz, hohe Trend-Konsistenz
  Person liegt drin   → Temperatur schwankt CHAOTISCH (Körperwärme, Bewegung)
                      → Hohe Varianz, niedrige Trend-Konsistenz

PRIMÄR-INDIKATOR: Kombination aus Varianz UND Trend-Konsistenz (30min Fenster)
  → Varianz allein reicht NICHT (Sensor-Rauschen ±0.0625°C triggert Fehlalarme)
  → Trend-Konsistenz unterscheidet monotones Heizen von chaotischer Präsenz

SEKUNDÄR (wenn verfügbar):
  - Luft-Temp-Varianz (SHT41): Verstärkt Signal
  - Auflagen-Temperatur: Schnelle Körperkontakt-Erkennung
  - Feuchtigkeit: Nur für Leckage-Erkennung (NICHT für Präsenz!)

SCHWITZ-ERKENNUNG: Nur bei echtem Schwitzen (>93% absolut UND Anstieg >35%)
"""

import logging
from collections import deque
from datetime import datetime, timedelta
from typing import Optional, Tuple
from dataclasses import dataclass

from .const import (
    PRESENCE_HISTORY_MINUTES,
    PRESENCE_VARIANCE_LOW,
    PRESENCE_VARIANCE_HIGH,
    PRESENCE_TREND_THRESHOLD,
    PRESENCE_TREND_CHAOTIC,
    PRESENCE_MIN_SAMPLES,
    PRESENCE_DEBOUNCE_MINUTES,
    PRESENCE_BODY_TEMP_DIFF,
)

_LOGGER = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# KALIBRIERTE SCHWELLWERTE (Apr 2026, Doppelbett 2x2m, 1 Heizung aktiv)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class PresenceThresholds:
    """Kalibrierte Schwellwerte aus echten Messdaten."""

    # PRIMÄR: Varianz-basierte Erkennung (30min Fenster)
    # Leeres Bett (Heizung):  Varianz < 0.02, Trend-Konsistenz > 0.85
    # Person drin:            Varianz > 0.08, Trend-Konsistenz < 0.6
    variance_low: float = PRESENCE_VARIANCE_LOW  # σ² darunter = Heizung
    variance_high: float = PRESENCE_VARIANCE_HIGH  # σ² darüber = Person
    trend_threshold: float = PRESENCE_TREND_THRESHOLD  # Konsistenz darüber = monoton
    trend_chaotic: float = PRESENCE_TREND_CHAOTIC  # Konsistenz darunter = chaotisch

    # Analyse-Fenster
    history_window_minutes: int = PRESENCE_HISTORY_MINUTES  # 30min
    min_samples: int = PRESENCE_MIN_SAMPLES  # Mindestens 20

    # Debounce (verhindert Flackern!)
    debounce_minutes: int = PRESENCE_DEBOUNCE_MINUTES  # 15min zwischen Wechseln

    # Legacy-Kompatibilität: wird von BedIntelligence-Kalibrierung gesetzt
    water_variance_threshold: float = 0.040

    # SEKUNDÄR: Luft-Temp-Varianz (SHT41 oben auf Kern)
    air_variance_threshold: float = 0.15

    # Auflagen-Temperatur (Körperkontakt)
    body_temp_diff: float = PRESENCE_BODY_TEMP_DIFF  # °C Diff Auflage-Wasser

    # SCHWITZ-ERKENNUNG (nach User-Feedback angepasst!)
    sweat_humidity_abs: float = 93.0  # Absolut >93% = STARK FEUCHT
    sweat_humidity_rise: float = 35.0  # Anstieg >35% über Baseline
    sweat_confirm_minutes: int = 15  # Muss 15 min anhalten

    # LECKAGE (Sicherheit)
    leak_humidity_abs: float = 85.0  # >85% über 3h = Alarm
    leak_confirm_hours: float = 3.0

    # Hysterese (Legacy, für Heizmatte)
    presence_enter_minutes: int = 5
    presence_leave_minutes: int = 20


class PresenceDetector:
    """
    Varianz + Trend-basierte Präsenz-Erkennung für Wasserbetten.

    Erkennt Präsenz basierend auf Temperatur-VARIANZ und TREND-KONSISTENZ:
    - NIEDRIGE Varianz + HOHE Konsistenz = Heizung läuft = NIEMAND drin
    - HOHE Varianz ODER NIEDRIGE Konsistenz = chaotisch = PERSON liegt drin

    Funktioniert minimal mit NUR dem Wassertemp-Sensor.
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
        self._last_state_change: dict[int, Optional[datetime]] = {}

        # Diagnostics
        self._last_water_variance: dict[int, float] = {}
        self._last_trend_consistency: dict[int, float] = {}
        self._last_water_std: dict[int, float] = (
            {}
        )  # Kompatibilität mit BedIntelligence
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
        is_heating_pad: bool = False,
        surface_temp: Optional[float] = None,
    ) -> Tuple[bool, float, str]:
        """
        Erkennt ob jemand im Bett liegt.

        Zwei Algorithmen:
        - Wasserbett: Varianz + Trend-Konsistenz (v4)
        - Heizmatte: Trend-basiert (Körperwärme)

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
            self._set_state(
                zone_index, presence_sensor_state, 1.0, "Präsenz-Sensor", now
            )
            return presence_sensor_state, 1.0, "Präsenz-Sensor"

        # ─────────────────────────────────────────────────────────────
        # Heizmatte: Trend-basierte Erkennung (Körperwärme)
        # ─────────────────────────────────────────────────────────────
        if is_heating_pad:
            return self._detect_presence_heating_pad(
                zone_index, water_temp, heater_active, now
            )

        # ─────────────────────────────────────────────────────────────
        # WASSERBETT v4: Varianz + Trend-Konsistenz
        # ─────────────────────────────────────────────────────────────
        buffer = self._water_temps.get(zone_index)
        if buffer is None or len(buffer) < self.thresholds.min_samples:
            current = self._is_present.get(zone_index, False)
            return current, 0.0, "Sammle Daten..."

        # Varianz berechnen (σ²)
        variance = self._calculate_variance(zone_index)

        # Trend-Konsistenz berechnen (0.0 = chaotisch, 1.0 = monoton steigend)
        trend_consistency = self._calculate_trend_consistency(zone_index)

        # Kompatibilität: water_std für BedIntelligence
        self._last_water_std[zone_index] = variance**0.5
        self._last_water_variance[zone_index] = variance
        self._last_trend_consistency[zone_index] = trend_consistency

        # Luft-Varianz (sekundär)
        air_std = self._calc_std(
            self._air_temps.get(zone_index), self.thresholds.history_window_minutes
        )
        self._last_air_std[zone_index] = air_std or 0.0

        # ─────────────────────────────────────────────────────────────
        # Entscheidungslogik: Varianz + Trend-Konsistenz
        # ─────────────────────────────────────────────────────────────
        raw_present, confidence, reasons = self._determine_presence(
            variance,
            trend_consistency,
            air_std,
            heater_active,
            water_temp,
            surface_temp,
        )

        # ─────────────────────────────────────────────────────────────
        # Debounce: Mindestens 15 Minuten zwischen Statuswechseln
        # ─────────────────────────────────────────────────────────────
        is_present = self._apply_debounce(zone_index, raw_present, now)

        reason = f"{'🛏️' if is_present else '○'} {', '.join(reasons)}"
        self._set_state(zone_index, is_present, confidence, reason, now)

        return is_present, round(confidence, 2), reason

    # ═══════════════════════════════════════════════════════════════════════
    # VARIANZ-BERECHNUNG (σ² über Analysefenster)
    # ═══════════════════════════════════════════════════════════════════════

    def _calculate_variance(self, zone_index: int) -> float:
        """
        Berechnet die Varianz (σ²) der Temperaturwerte im Analysefenster.

        Niedrige Varianz = gleichmäßiges Heizen (monotoner Anstieg)
        Hohe Varianz = chaotische Schwankungen (Person im Bett)
        """
        buffer = self._water_temps.get(zone_index)
        if not buffer:
            return 0.0

        cutoff = datetime.now() - timedelta(
            minutes=self.thresholds.history_window_minutes
        )
        temps = [val for ts, val in buffer if ts > cutoff and val is not None]

        if len(temps) < 2:
            return 0.0

        mean = sum(temps) / len(temps)
        variance = sum((t - mean) ** 2 for t in temps) / len(temps)
        return variance

    # ═══════════════════════════════════════════════════════════════════════
    # TREND-KONSISTENZ (Monotonie-Messung)
    # ═══════════════════════════════════════════════════════════════════════

    def _calculate_trend_consistency(self, zone_index: int) -> float:
        """
        Misst wie konsistent der Temperaturverlauf ist.

        1.0 = perfekt monoton steigend (Heizung allein)
        0.5 = zufällig (chaotisch)
        0.0 = perfekt monoton fallend

        Methode: Anteil der aufeinanderfolgenden Werte die in die
        gleiche Richtung (steigend) gehen.

        Heizung allein: Fast alle Schritte positiv → ~0.95
        Person drin: Hoch und runter → ~0.4-0.6
        """
        buffer = self._water_temps.get(zone_index)
        if not buffer:
            return 0.5

        cutoff = datetime.now() - timedelta(
            minutes=self.thresholds.history_window_minutes
        )
        temps = [val for ts, val in buffer if ts > cutoff and val is not None]

        if len(temps) < 3:
            return 0.5

        # Berechne Differenzen zwischen aufeinanderfolgenden Werten
        diffs = [temps[i + 1] - temps[i] for i in range(len(temps) - 1)]

        # Zähle nicht-negative Differenzen (Temperatur steigt oder gleich)
        positive_count = sum(1 for d in diffs if d >= 0)

        # Konsistenz = Anteil der positiven/gleichen Differenzen
        consistency = positive_count / len(diffs)

        return consistency

    # ═══════════════════════════════════════════════════════════════════════
    # ENTSCHEIDUNGSLOGIK (Varianz + Trend + Optional: Auflagen-Temp)
    # ═══════════════════════════════════════════════════════════════════════

    def _determine_presence(
        self,
        variance: float,
        trend_consistency: float,
        air_std: Optional[float],
        heater_active: bool,
        water_temp: Optional[float],
        surface_temp: Optional[float],
    ) -> Tuple[bool, float, list]:
        """
        Entscheidet ob jemand im Bett liegt.

        HEIZUNG (niemand): Niedrige Varianz UND Hohe Konsistenz (monoton)
        PERSON:           Hohe Varianz ODER Niedrige Konsistenz (chaotisch)

        Returns:
            (raw_present, confidence, reasons)
        """
        raw_present = False
        confidence = 0.0
        reasons = []

        vl = self.thresholds.variance_low
        vh = self.thresholds.variance_high
        tt = self.thresholds.trend_threshold
        tc = self.thresholds.trend_chaotic

        if heater_active:
            reasons.append("⚡Heiz")

        reasons.append(f"σ²={variance:.4f}")
        reasons.append(f"T={trend_consistency:.2f}")

        # ─── Definitiv Heizung: Sehr niedrige Varianz UND monotoner Anstieg ──
        if variance < vl and trend_consistency > tt:
            confidence = 0.05
            reasons.append("→ruhig+monoton")
            return False, confidence, reasons

        # ─── Definitiv Person: Hohe Varianz ──────────────────────────────────
        if variance > vh:
            confidence = 0.95
            raw_present = True
            reasons.append("→Varianz hoch!")
            # Luft-Varianz verstärkt
            if air_std is not None and air_std > self.thresholds.air_variance_threshold:
                confidence = min(1.0, confidence + 0.05)
                reasons.append(f"σL={air_std:.3f}")
            return raw_present, confidence, reasons

        # ─── Definitiv Person: Chaotischer Verlauf ──────────────────────────
        if trend_consistency < tc:
            confidence = 0.85
            raw_present = True
            reasons.append("→chaotisch!")
            return raw_present, confidence, reasons

        # ─── Grauzone: Varianz zwischen LOW und HIGH ────────────────────────
        # Nutze Zusatzsignale für die Entscheidung

        # Auflagen-Temperatur: Schneller Körperkontakt-Check
        if surface_temp is not None and water_temp is not None:
            diff = surface_temp - water_temp
            if diff > self.thresholds.body_temp_diff:
                confidence = 0.80
                raw_present = True
                reasons.append(f"Körper(Δ={diff:.1f}°C)")
                return raw_present, confidence, reasons

        # Luft-Varianz als Tiebreaker
        if air_std is not None and air_std > self.thresholds.air_variance_threshold * 2:
            confidence = 0.70
            raw_present = True
            reasons.append(f"σL={air_std:.3f}(stark)")
            return raw_present, confidence, reasons

        # Keine klare Entscheidung → aktuellen Zustand beibehalten
        confidence = 0.30
        reasons.append("→Grauzone")
        return raw_present, confidence, reasons

    # ═══════════════════════════════════════════════════════════════════════
    # DEBOUNCE (Anti-Flacker)
    # ═══════════════════════════════════════════════════════════════════════

    def _apply_debounce(
        self, zone_index: int, raw_present: bool, now: datetime
    ) -> bool:
        """
        Debounce: Mindestens PRESENCE_DEBOUNCE_MINUTES zwischen Statuswechseln.

        Verhindert schnelles Flackern durch kurze Störungen.
        """
        current = self._is_present.get(zone_index, False)

        if raw_present == current:
            return current

        # Prüfe ob genug Zeit seit letztem Wechsel vergangen
        last_change = self._last_state_change.get(zone_index)
        if last_change is not None:
            elapsed = (now - last_change).total_seconds() / 60
            if elapsed < self.thresholds.debounce_minutes:
                return current  # Noch warten

        # Wechsel erlaubt
        self._last_state_change[zone_index] = now
        return raw_present

    # ═══════════════════════════════════════════════════════════════════════
    # HEIZMATTE: TREND-BASIERTE PRÄSENZ (Körperwärme-Erkennung)
    # ═══════════════════════════════════════════════════════════════════════

    def _detect_presence_heating_pad(
        self,
        zone_index: int,
        temp: Optional[float],
        heater_active: bool,
        now: datetime,
    ) -> Tuple[bool, float, str]:
        """
        Erkennt Präsenz auf einer Heizmatte über Temperatur-Trend.

        Logik:
        - Heizung AUS + Temp steigt → Körperwärme → Person liegt drauf
        - Heizung AUS + Temp fällt → Bett kühlt ab → niemand da
        - Heizung AN → Trend-Steigung prüfen (Körperwärme > erwartete Heizrate)
        """
        buffer = self._water_temps.get(zone_index)
        if buffer is None or len(buffer) < 6:
            current = self._is_present.get(zone_index, False)
            return current, 0.0, "Sammle Daten..."

        # Trend der letzten 3 Minuten
        cutoff = now - timedelta(minutes=3)
        recent = [val for ts, val in buffer if ts > cutoff and val is not None]

        if len(recent) < 4:
            current = self._is_present.get(zone_index, False)
            return current, 0.0, "Sammle Daten..."

        trend = recent[-1] - recent[0]  # Positiv = steigend
        raw_present = False
        confidence = 0.0
        reasons = []

        if not heater_active:
            if trend > 0.2:
                raw_present = True
                confidence = 0.85
                reasons.append(f"Körperwärme +{trend:.2f}°C/3min")
            elif trend > 0.05:
                raw_present = True
                confidence = 0.50
                reasons.append(f"Leichter Anstieg +{trend:.2f}°C")
            else:
                confidence = 0.10
                reasons.append(f"Trend {trend:+.2f}°C (kühlt)")
        else:
            expected_rise = 0.25
            excess = trend - expected_rise
            if excess > 0.1:
                raw_present = True
                confidence = 0.70
                reasons.append(
                    f"⚡+Körper ({trend:.2f}°C, erwartet {expected_rise:.2f})"
                )
            else:
                confidence = 0.15
                reasons.append(f"⚡Heizen ({trend:.2f}°C)")

        # Hysterese (asymmetrisch für Heizmatte)
        is_present = self._apply_hysteresis_heating_pad(zone_index, raw_present, now)

        reason = f"{'🛏️' if is_present else '○'} {', '.join(reasons)}"
        self._set_state(zone_index, is_present, confidence, reason, now)

        return is_present, round(confidence, 2), reason

    def _apply_hysteresis_heating_pad(
        self, zone_index: int, raw_present: bool, now: datetime
    ) -> bool:
        """Asymmetrische Hysterese für Heizmatte (schnell rein, langsam raus)."""
        current = self._is_present.get(zone_index, False)

        if raw_present == current:
            return current

        last_change = self._last_state_change.get(zone_index)
        if last_change is None:
            self._last_state_change[zone_index] = now
            return raw_present

        elapsed = (now - last_change).total_seconds() / 60

        if raw_present:
            required = self.thresholds.presence_enter_minutes
        else:
            required = self.thresholds.presence_leave_minutes

        if elapsed >= required:
            self._last_state_change[zone_index] = now
            return raw_present

        return current

    # ═══════════════════════════════════════════════════════════════════════
    # LEGACY: Standard-Abweichung (für Luft-Temp und Kompatibilität)
    # ═══════════════════════════════════════════════════════════════════════

    def _calc_std(
        self, buffer: Optional[deque], window_minutes: int
    ) -> Optional[float]:
        """Berechnet Standardabweichung über rollendes Zeitfenster."""
        if buffer is None or len(buffer) < self.thresholds.min_samples:
            return None

        cutoff = datetime.now() - timedelta(minutes=window_minutes)
        values = [val for ts, val in buffer if ts > cutoff and val is not None]

        if len(values) < self.thresholds.min_samples:
            return None

        n = len(values)
        mean = sum(values) / n
        variance = sum((x - mean) ** 2 for x in values) / n
        return variance**0.5

    # ═══════════════════════════════════════════════════════════════════════
    # SCHWITZ-ERKENNUNG (konservativ!)
    # ═══════════════════════════════════════════════════════════════════════

    def is_sweating(self, zone_index: int) -> bool:
        """
        Erkennt ECHTES Schwitzen/Feuchtigkeit – nicht einfach "Feuchtigkeit erhöht".

        Feuchtigkeit 50-85% ist NORMAL wenn jemand unter der Decke liegt!
        Erst ab 93% absolut UND >35% Anstieg über Baseline = STARK FEUCHT.
        Muss außerdem 15 Minuten anhalten.
        """
        buffer = self._humidity.get(zone_index)
        if not buffer or len(buffer) < self.thresholds.min_samples:
            return False

        now = datetime.now()

        # Letzte 15 Minuten
        recent_cutoff = now - timedelta(minutes=self.thresholds.sweat_confirm_minutes)
        recent = [val for ts, val in buffer if ts > recent_cutoff and val is not None]
        if len(recent) < 5:
            return False

        avg_recent = sum(recent) / len(recent)

        # Baseline: Minimum der letzten 6 Stunden
        baseline_cutoff = now - timedelta(hours=6)
        all_vals = [
            val for ts, val in buffer if ts > baseline_cutoff and val is not None
        ]
        if not all_vals:
            return False

        baseline = min(all_vals)
        rise = avg_recent - baseline

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
          >93%  = stark feucht
        """
        buffer = self._humidity.get(zone_index)
        if not buffer or len(buffer) < 3:
            return "unbekannt"

        recent = [val for _, val in list(buffer)[-5:] if val is not None]
        if not recent:
            return "unbekannt"

        avg = sum(recent) / len(recent)

        if avg > 93:
            return "stark feucht"
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
            _LOGGER.info(
                "Zone %d: %s (%s)",
                zone_index,
                "Präsenz erkannt" if is_present else "Bett leer",
                reason,
            )

        self._is_present[zone_index] = is_present
        self._last_confidence[zone_index] = confidence
        self._last_reason[zone_index] = reason

    # ═══════════════════════════════════════════════════════════════════════
    # DIAGNOSTICS
    # ═══════════════════════════════════════════════════════════════════════

    def get_diagnostics(self, zone_index: int) -> dict:
        """Detaillierte Debug-Informationen."""
        is_present = self._is_present.get(zone_index, False)
        last_change = self._last_state_change.get(zone_index)
        variance = self._last_water_variance.get(zone_index, 0.0)
        trend = self._last_trend_consistency.get(zone_index, 0.0)
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
            "last_state_change": last_change.isoformat() if last_change else None,
            "water_variance": round(variance, 6),
            "trend_consistency": round(trend, 3),
            "water_temp_std": round(w_std, 4),
            "air_temp_std": round(a_std, 4),
            "thresholds": {
                "variance_low": self.thresholds.variance_low,
                "variance_high": self.thresholds.variance_high,
                "trend_threshold": self.thresholds.trend_threshold,
                "trend_chaotic": self.thresholds.trend_chaotic,
            },
            "humidity": round(current_humidity, 1) if current_humidity else None,
            "is_sweating": self.is_sweating(zone_index),
            "is_leak": self.is_potential_leak(zone_index),
            "buffer_sizes": {
                "water": len(self._water_temps.get(zone_index, [])),
                "air": len(self._air_temps.get(zone_index, [])),
                "humidity": len(self._humidity.get(zone_index, [])),
            },
            "debounce_minutes": self.thresholds.debounce_minutes,
        }
