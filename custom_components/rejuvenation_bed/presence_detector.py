"""
Presence-Detector v6 für das Rejuvenation Bed.

FIX (Apr 2026): Zurück zur sensitiven v3-Erkennung (σ-basiert) plus v5
Heizungs-Schutz. v5 war zu konservativ und hat Präsenz NIE mehr erkannt.

KERN-ERKENNTNIS:
  Bewegung im Wasserbett → Wasserwellen → DS18B20 schwankt
  Leeres Bett            → Wasser ruhig → DS18B20 stabil (σ < 0.03°C)
  Person im Bett         → Wasser unruhig → DS18B20 instabil (σ > 0.04°C)

PRIMÄRER INDIKATOR: Rohe Standardabweichung σ der Wassertemperatur
  • σ > 0.08°C (2× threshold)  → Präsenz sehr sicher (conf 0.95)
  • σ > 0.04°C (1× threshold)  → Präsenz wahrscheinlich (conf 0.75)
  • σ > 0.028°C (0.7×)         → Grenzfall (Luftsensor entscheidet)
  • σ ≤ 0.028°C                → Wasser ruhig → leer

HEIZUNGS-SCHUTZ (gegen False-Positives):
  Wenn σ² sehr niedrig UND Trend-Konsistenz sehr hoch
  UND kaum signifikante Änderungen → reines Heizen, kein Mensch.
  DS18B20-Rauschen (±0.0625°C) wird dabei ignoriert.

HYSTERESE (asymmetrisch, wie v3):
  Einsteigen: 5 min konstant "da"  → schnelle Reaktion
  Aussteigen: 20 min konstant "weg" → keine Fehlausstiege bei kurzen Pausen
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
# KRITISCH: Sensor-Rauschen Schwellwert
# ═══════════════════════════════════════════════════════════════════════════════
# DS18B20 hat 12-bit Auflösung = 0.0625°C pro Schritt
# Alles darunter ist RAUSCHEN und muss ignoriert werden!
SENSOR_NOISE_THRESHOLD = 0.07  # Leicht über 0.0625 für Sicherheit


@dataclass
class PresenceThresholds:
    """Kalibrierte Schwellwerte aus echten Messdaten."""

    # PRIMÄR: Varianz-basierte Erkennung (30min Fenster)
    variance_low: float = PRESENCE_VARIANCE_LOW  # σ² darunter = Heizung
    variance_high: float = PRESENCE_VARIANCE_HIGH  # σ² darüber = Person
    trend_threshold: float = PRESENCE_TREND_THRESHOLD  # Konsistenz darüber = monoton
    trend_chaotic: float = PRESENCE_TREND_CHAOTIC  # Konsistenz darunter = chaotisch

    # Analyse-Fenster
    history_window_minutes: int = PRESENCE_HISTORY_MINUTES  # 30min
    min_samples: int = PRESENCE_MIN_SAMPLES  # Mindestens 20

    # Debounce (verhindert Flackern!)
    debounce_minutes: int = PRESENCE_DEBOUNCE_MINUTES  # 15min zwischen Wechseln

    # Legacy-Kompatibilität
    water_variance_threshold: float = 0.040

    # SEKUNDÄR: Luft-Temp-Varianz (SHT41)
    air_variance_threshold: float = 0.15

    # Auflagen-Temperatur (Körperkontakt)
    body_temp_diff: float = PRESENCE_BODY_TEMP_DIFF

    # SCHWITZ-ERKENNUNG
    sweat_humidity_abs: float = 93.0
    sweat_humidity_rise: float = 35.0
    sweat_confirm_minutes: int = 15

    # LECKAGE
    leak_humidity_abs: float = 85.0
    leak_confirm_hours: float = 3.0

    # Hysterese (Legacy)
    presence_enter_minutes: int = 5
    presence_leave_minutes: int = 20


class PresenceDetector:
    """
    Varianz + Trend-basierte Präsenz-Erkennung für Wasserbetten.
    
    v5: Mit Rausch-Immunität für DS18B20 Sensoren!
    """

    def __init__(self, thresholds: Optional[PresenceThresholds] = None):
        self.thresholds = thresholds or PresenceThresholds()

        # Rolling-Buffer pro Zone
        self._water_temps: dict[int, deque] = {}
        self._air_temps: dict[int, deque] = {}
        self._humidity: dict[int, deque] = {}
        self._max_buffer = 600  # ~5h bei 30s Updates

        # Zustand pro Zone
        self._is_present: dict[int, bool] = {}
        self._last_state_change: dict[int, Optional[datetime]] = {}

        # Asymmetrische Hysterese (pending = noch nicht bestätigter Wechsel)
        self._pending_state: dict[int, Optional[bool]] = {}
        self._pending_since: dict[int, Optional[datetime]] = {}

        # Diagnostics
        self._last_water_variance: dict[int, float] = {}
        self._last_trend_consistency: dict[int, float] = {}
        self._last_water_std: dict[int, float] = {}
        self._last_air_std: dict[int, float] = {}
        self._last_confidence: dict[int, float] = {}
        self._last_reason: dict[int, str] = {}
        self._last_significant_changes: dict[int, int] = {}  # NEU: Debug

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
        # Heizmatte: Trend-basierte Erkennung
        # ─────────────────────────────────────────────────────────────
        if is_heating_pad:
            return self._detect_presence_heating_pad(
                zone_index, water_temp, heater_active, now
            )

        # ─────────────────────────────────────────────────────────────
        # WASSERBETT v6: σ (v3) als Primär-Signal + v5 Heizungs-Schutz
        # ─────────────────────────────────────────────────────────────
        buffer = self._water_temps.get(zone_index)
        if buffer is None or len(buffer) < self.thresholds.min_samples:
            current = self._is_present.get(zone_index, False)
            return current, 0.0, "Sammle Daten..."

        # Rohe σ (Standardabweichung) — wie v3. Das ist das Primär-Signal.
        water_std = (
            self._calc_std(buffer, self.thresholds.history_window_minutes) or 0.0
        )

        # Zusatz-Signale nur zur Absicherung gegen Heizungs-False-Positives:
        smoothed_variance = self._calculate_variance_smoothed(zone_index)
        trend_consistency, significant_changes = (
            self._calculate_trend_consistency_noise_immune(zone_index)
        )

        # Diagnostics speichern
        self._last_water_std[zone_index] = water_std
        self._last_water_variance[zone_index] = smoothed_variance
        self._last_trend_consistency[zone_index] = trend_consistency
        self._last_significant_changes[zone_index] = significant_changes

        # Luft-Varianz (sekundär, unterstützend)
        air_std = self._calc_std(
            self._air_temps.get(zone_index), self.thresholds.history_window_minutes
        )
        self._last_air_std[zone_index] = air_std or 0.0

        # ─────────────────────────────────────────────────────────────
        # Entscheidungslogik
        # ─────────────────────────────────────────────────────────────
        raw_present, confidence, reasons = self._determine_presence(
            water_std,
            smoothed_variance,
            trend_consistency,
            significant_changes,
            air_std,
            heater_active,
            water_temp,
            surface_temp,
            zone_index,
        )

        # ─────────────────────────────────────────────────────────────
        # Hysterese (asymmetrisch: schnell rein, langsam raus)
        # ─────────────────────────────────────────────────────────────
        is_present = self._apply_debounce(zone_index, raw_present, now)

        reason = f"{'🛏️' if is_present else '○'} {', '.join(reasons)}"
        self._set_state(zone_index, is_present, confidence, reason, now)

        return is_present, round(confidence, 2), reason

    # ═══════════════════════════════════════════════════════════════════════
    # ROHE VARIANZ (ohne Glättung) - für Tests & Diagnose
    # ═══════════════════════════════════════════════════════════════════════

    def _calculate_variance(self, zone_index: int) -> float:
        """
        Berechnet die rohe Varianz über das Analyse-Fenster (ohne Glättung).

        Wird von Tests verwendet, um die direkte Schwankungsbreite zu messen.
        Die Entscheidungslogik nutzt weiterhin _calculate_variance_smoothed().
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
        return sum((t - mean) ** 2 for t in temps) / len(temps)

    def _calculate_trend_consistency(self, zone_index: int) -> float:
        """
        Gibt die Rausch-immune Trend-Konsistenz zurück (ohne Zähler).

        Thin Wrapper um _calculate_trend_consistency_noise_immune() für Tests
        und Aufrufer, die nur den Konsistenz-Wert brauchen.
        """
        consistency, _ = self._calculate_trend_consistency_noise_immune(zone_index)
        return consistency

    # ═══════════════════════════════════════════════════════════════════════
    # NEU v5: VARIANZ MIT GLÄTTUNG (gegen Sensor-Rauschen)
    # ═══════════════════════════════════════════════════════════════════════

    def _calculate_variance_smoothed(self, zone_index: int) -> float:
        """
        Berechnet Varianz MIT Glättung gegen Sensor-Rauschen.
        
        Methode: Moving Average über 5 Werte, dann Varianz berechnen.
        Das filtert das ±0.0625°C Rauschen effektiv heraus!
        """
        buffer = self._water_temps.get(zone_index)
        if not buffer:
            return 0.0

        cutoff = datetime.now() - timedelta(
            minutes=self.thresholds.history_window_minutes
        )
        temps = [val for ts, val in buffer if ts > cutoff and val is not None]

        if len(temps) < 10:
            return 0.0

        # ═══ GLÄTTUNG: Moving Average über 5 Werte ═══
        window_size = 5
        smoothed = []
        for i in range(len(temps) - window_size + 1):
            window = temps[i:i + window_size]
            smoothed.append(sum(window) / window_size)

        if len(smoothed) < 2:
            return 0.0

        # Varianz der geglätteten Werte
        mean = sum(smoothed) / len(smoothed)
        variance = sum((t - mean) ** 2 for t in smoothed) / len(smoothed)
        
        return variance

    # ═══════════════════════════════════════════════════════════════════════
    # NEU v5: TREND-KONSISTENZ MIT RAUSCH-IMMUNITÄT
    # ═══════════════════════════════════════════════════════════════════════

    def _calculate_trend_consistency_noise_immune(self, zone_index: int) -> Tuple[float, int]:
        """
        Misst Trend-Konsistenz, IGNORIERT aber Sensor-Rauschen!
        
        KRITISCHER FIX:
        Der DS18B20 springt ständig ±0.0625°C hin und her.
        Das ist KEIN echter Temperaturwechsel!
        
        Wir ignorieren alle Differenzen ≤ SENSOR_NOISE_THRESHOLD.
        Nur ECHTE Änderungen (>0.07°C) werden gezählt.
        
        Returns:
            (consistency, significant_changes_count)
        """
        buffer = self._water_temps.get(zone_index)
        if not buffer:
            return 0.5, 0

        cutoff = datetime.now() - timedelta(
            minutes=self.thresholds.history_window_minutes
        )
        temps = [val for ts, val in buffer if ts > cutoff and val is not None]

        if len(temps) < 3:
            return 0.5, 0

        # ═══ RAUSCH-FILTERUNG: Nur signifikante Änderungen zählen ═══
        significant_positive = 0
        significant_negative = 0
        total_significant = 0

        for i in range(len(temps) - 1):
            diff = temps[i + 1] - temps[i]
            
            # Ignoriere Rauschen!
            if abs(diff) <= SENSOR_NOISE_THRESHOLD:
                continue
            
            total_significant += 1
            if diff > 0:
                significant_positive += 1
            else:
                significant_negative += 1

        # ═══ ENTSCHEIDUNG basierend auf signifikanten Änderungen ═══
        
        # Fall 1: Kaum signifikante Änderungen → Temperatur ist STABIL
        # Das bedeutet: Heizung hält konstant ODER Bett kühlt langsam ab
        # → Definitiv KEINE Person (Person würde Schwankungen verursachen)
        if total_significant < 3:
            return 0.98, total_significant  # Sehr monoton = leer
        
        # Fall 2: Wenige signifikante Änderungen, aber alle in eine Richtung
        # → Heizung heizt hoch ODER Bett kühlt ab = monoton = leer
        if total_significant < 10:
            if significant_positive >= total_significant * 0.8:
                return 0.95, total_significant  # Fast nur steigend = Heizung
            if significant_negative >= total_significant * 0.8:
                return 0.90, total_significant  # Fast nur fallend = Abkühlen
        
        # Fall 3: Normale Auswertung
        consistency = significant_positive / total_significant if total_significant > 0 else 0.5
        
        return consistency, total_significant

    # ═══════════════════════════════════════════════════════════════════════
    # ENTSCHEIDUNGSLOGIK (angepasst für v5)
    # ═══════════════════════════════════════════════════════════════════════

    def _determine_presence(
        self,
        water_std: float,
        smoothed_variance: float,
        trend_consistency: float,
        significant_changes: int,
        air_std: Optional[float],
        heater_active: bool,
        water_temp: Optional[float],
        surface_temp: Optional[float],
        zone_index: int,
    ) -> Tuple[bool, float, list]:
        """
        Entscheidet ob jemand im Bett liegt.

        v6: σ (v3-Stil) als Primär-Signal, mit v5 Heizungs-Schutz als Guard.
        """
        reasons = []

        if heater_active:
            reasons.append("⚡Heiz")

        reasons.append(f"σ={water_std:.3f}")
        reasons.append(f"T={trend_consistency:.2f}")
        reasons.append(f"Δ={significant_changes}")

        wt = self.thresholds.water_variance_threshold  # σ-Schwelle, default 0.040
        vl = self.thresholds.variance_low  # σ²-Guard
        tt = self.thresholds.trend_threshold
        tc = self.thresholds.trend_chaotic

        # ─── Guard 1: reines Heizen (monoton) ──────────────────────────
        # Sehr hohe Trend-Konsistenz + kaum echte Sprünge (Rauschfilter!)
        # → reine Temperatur-Rampe, kein Mensch. σ kann dabei durchaus
        # hoch sein (wenn Bett stark heizt), aber ein Mensch würde
        # Rauf-Runter-Schwankungen verursachen.
        if trend_consistency > tt and significant_changes <= 2:
            reasons.append("→Heizung(monoton)")
            return False, 0.05, reasons

        # ─── Guard 2: Wasser komplett ruhig ────────────────────────────
        # Wenn σ² unter vl UND kaum echte Änderungen → stabiles leeres Bett
        if smoothed_variance < vl and significant_changes <= 2:
            reasons.append("→stabil(leer)")
            return False, 0.05, reasons

        # ─── Primär: σ-basierte Stufen (v3-Stil) ──────────────────────
        raw_present = False
        if water_std > wt * 2:
            confidence = 0.95
            raw_present = True
            reasons.append("→σ hoch")
        elif water_std > wt:
            confidence = 0.75
            raw_present = True
            reasons.append("→Präsenz")
        elif water_std > wt * 0.7:
            confidence = 0.40
            reasons.append("→Grenzbereich")
        else:
            confidence = 0.10
            reasons.append("→Wasser ruhig")

        # ─── Chaotischer Verlauf bestätigt Präsenz ────────────────────
        # Wenn Temperatur chaotisch springt, ist das ein starker Mensch-Indikator.
        if trend_consistency < tc and significant_changes >= 5:
            raw_present = True
            confidence = max(confidence, 0.80)
            reasons.append("→chaotisch")

        # ─── Luft-Varianz als Verstärker ──────────────────────────────
        if air_std is not None:
            at = self.thresholds.air_variance_threshold
            if air_std > at:
                confidence = min(1.0, confidence + 0.15)
                if not raw_present and air_std > at * 2:
                    raw_present = True
                reasons.append(f"σL={air_std:.3f}")

        # ─── Auflagen-Temperatur (Körperkontakt) ──────────────────────
        if surface_temp is not None and water_temp is not None:
            diff = surface_temp - water_temp
            if diff > self.thresholds.body_temp_diff:
                raw_present = True
                confidence = max(confidence, 0.80)
                reasons.append(f"Körper(Δ={diff:.1f}°C)")

        # ─── Grauzone: aktuellen Zustand halten ───────────────────────
        # Nicht erzwungen OFF (das war v5 Fehler). Lieber Status quo,
        # damit Hysterese stabil bleibt und kein unnötiger Ausstieg passiert.
        if not raw_present and confidence >= 0.30:
            raw_present = self._is_present.get(zone_index, False)
            reasons.append("→halte Status")

        return raw_present, confidence, reasons

    # ═══════════════════════════════════════════════════════════════════════
    # DEBOUNCE
    # ═══════════════════════════════════════════════════════════════════════

    def _apply_debounce(
        self, zone_index: int, raw_present: bool, now: datetime
    ) -> bool:
        """
        Asymmetrische Hysterese (v3-Stil, schnell rein / langsam raus):
        • Einsteigen (OFF→ON): presence_enter_minutes konstant "da" (default 5)
        • Aussteigen (ON→OFF): presence_leave_minutes konstant "weg" (default 20)

        Verhindert sowohl Flackern als auch verpasste Einstiege.
        """
        current = self._is_present.get(zone_index, False)

        # Gleicher Zustand → Pending resetten, halten
        if raw_present == current:
            self._pending_state[zone_index] = None
            self._pending_since[zone_index] = None
            return current

        pending = self._pending_state.get(zone_index)
        pending_since = self._pending_since.get(zone_index)

        # Neuer Wechsel-Kandidat → Timer (neu) starten
        if pending != raw_present or pending_since is None:
            self._pending_state[zone_index] = raw_present
            self._pending_since[zone_index] = now
            pending_since = now

        # Prüfen ob Wartezeit abgelaufen (funktioniert auch bei required=0)
        elapsed = (now - pending_since).total_seconds() / 60
        required = (
            self.thresholds.presence_enter_minutes
            if raw_present
            else self.thresholds.presence_leave_minutes
        )

        if elapsed >= required:
            self._pending_state[zone_index] = None
            self._pending_since[zone_index] = None
            self._last_state_change[zone_index] = now
            self._is_present[zone_index] = raw_present
            return raw_present

        return current

    # ═══════════════════════════════════════════════════════════════════════
    # HEIZMATTE (unverändert)
    # ═══════════════════════════════════════════════════════════════════════

    def _detect_presence_heating_pad(
        self,
        zone_index: int,
        water_temp: Optional[float],
        heater_active: bool,
        now: datetime,
    ) -> Tuple[bool, float, str]:
        """Heizmatte: Körperwärme-Erkennung."""
        buffer = self._water_temps.get(zone_index)
        if buffer is None or len(buffer) < self.thresholds.min_samples:
            current = self._is_present.get(zone_index, False)
            return current, 0.0, "Sammle Daten..."

        # Bei Heizmatten: Steigende Temperatur OHNE aktive Heizung = Person
        if not heater_active and water_temp is not None:
            # Vergleiche mit Temperatur vor 10 Minuten
            cutoff = now - timedelta(minutes=10)
            old_temps = [val for ts, val in buffer if ts < cutoff and val is not None]
            
            if old_temps:
                old_avg = sum(old_temps[-5:]) / min(5, len(old_temps))
                temp_rise = water_temp - old_avg
                
                if temp_rise > 0.5:  # Temperatur steigt ohne Heizung
                    is_present = True
                    confidence = min(0.95, 0.7 + temp_rise * 0.1)
                    reason = f"🛏️ Körperwärme(+{temp_rise:.1f}°C)"
                    self._set_state(zone_index, is_present, confidence, reason, now)
                    return is_present, confidence, reason

        # Fallback: Trend-Konsistenz
        _, significant_changes = self._calculate_trend_consistency_noise_immune(zone_index)
        variance = self._calculate_variance_smoothed(zone_index)
        
        if variance > self.thresholds.variance_high:
            is_present = True
            confidence = 0.8
            reason = f"🛏️ Varianz hoch(σ²={variance:.4f})"
        else:
            is_present = False
            confidence = 0.3
            reason = f"○ Ruhig(σ²={variance:.4f})"
        
        is_present = self._apply_debounce(zone_index, is_present, now)
        self._set_state(zone_index, is_present, confidence, reason, now)
        return is_present, confidence, reason

    # ═══════════════════════════════════════════════════════════════════════
    # LEGACY: Standard-Abweichung
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
    # SCHWITZ-ERKENNUNG
    # ═══════════════════════════════════════════════════════════════════════

    def is_sweating(self, zone_index: int) -> bool:
        """Erkennt echtes Schwitzen (>93% absolut UND >35% Anstieg)."""
        buffer = self._humidity.get(zone_index)
        if not buffer or len(buffer) < self.thresholds.min_samples:
            return False

        now = datetime.now()

        recent_cutoff = now - timedelta(minutes=self.thresholds.sweat_confirm_minutes)
        recent = [val for ts, val in buffer if ts > recent_cutoff and val is not None]
        if len(recent) < 5:
            return False

        avg_recent = sum(recent) / len(recent)

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
        """Gibt Feuchtigkeitsstufe zurück."""
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
        """Erkennt mögliche Leckage: Feuchtigkeit >85% über 3 Stunden."""
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
        sig_changes = self._last_significant_changes.get(zone_index, 0)

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
            "significant_changes": sig_changes,  # NEU
            "water_temp_std": round(w_std, 4),
            "air_temp_std": round(a_std, 4),
            "noise_threshold": SENSOR_NOISE_THRESHOLD,  # NEU
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
