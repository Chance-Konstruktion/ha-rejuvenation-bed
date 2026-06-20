"""
Presence-Detector v11 für das Rejuvenation Bed — Wasser-Only, heizungs-bewusst.

Siehe ``docs/presence_detector_v11.md`` für die ausführliche Begründung.

v11.1 — Stale-Cooldown-Release (gegen den "12 h hängen geblieben"-Fehler):
  Validiert an einem echten Tag-Schlaf-Datensatz MIT Heizungs-Historie
  (Nutzer lag 06:00–14:00 CEST, Heizung die ganze Zeit aus). Befund: nach
  dem Aufstehen kühlt das warme, leere Bett nur mit ~0.06–0.16 °C/h aus —
  flacher als ``slope_cooling_threshold`` (−0.10) — und sein σ60-Rauschen
  (~0.045–0.05) lag genau auf ``chaos_refresh_threshold``. Dadurch hat der
  Chaos-Lock sich stundenlang selbst aufgefrischt und die heizungs-bewusste
  Slope-Logik nie zum Zug kommen lassen → Sensor blieb ~12 h fälschlich ON.
  Fixe:
    1) ``chaos_threshold`` 0.05 → 0.055 (über dem Leer-σ-Floor dieses Setups;
       eliminiert vereinzelte Falsch-Bursts auf dem leeren warmen Bett).
    2) NEU ``slope_cooldown_release`` (−0.05 °C/h) + ``cooldown_release_minutes``
       (90): Heizung AUS + anhaltende Auskühlung + seit N Minuten kein ECHTER
       Bewegungs-Burst ⇒ Bett ist leer, der Chaos-Lock wird gebrochen.
    3) NEU ``_empty_confirmed``-Flag: ist das Bett einmal als leer bestätigt,
       darf der σ60-Refresh (oder ein kurzer Heiz-Burst) den Lock NICHT
       wiederbeleben. Nur ECHTE Wiedereinstiegs-Evidenz (Bewegungs-Burst,
       Körperwärme-Anstieg, rise→stable) setzt das Flag zurück.
  Echte Bewegungs-Bursts (σ_d kurz > chaos_threshold) werden separat in
  ``_last_burst_time`` getrackt — der σ60-Lock-Refresh zählt NICHT als Burst.

Warum v11?
  v10 (CSV-validiert auf einem einzelnen Nacht-Datensatz) hat bei aktivem
  Solar-Boost regelmäßig „Person im Bett" gemeldet, während das Bett leer
  war: jeder Heizungs-Burst lieferte σ_d ≈ 0.05–0.08 °C, was über der alten
  ``chaos_threshold = 0.10`` zwar nicht reichte — aber kombiniert mit dem
  σ_d_60-Refresh (0.06) und dem ``_apply_overrides``-Bump aus der Luft-
  varianz wurde das Bett dauerhaft im ON-Lock gehalten. Außerdem hat der
  DS18B20 nur 0.0625 °C Auflösung; der Quantisierungs-Floor σ ≈ 0.031 °C
  liegt zu nah an den alten Schwellen.

Was v11 anders macht:
  1) σ-Schwellen quantisierungs-bewusst:
       chaos_threshold:        0.10 → 0.05  °C
       chaos_refresh_threshold: 0.06 → 0.045 °C
     Die neuen Werte liegen 1.5–2× über dem Quantisierungs-Floor und
     unterscheiden „echte Bewegung im Wasser" sauber von Heizungs-Bursts.
  2) Slope-Logik ist jetzt heizungs-bewusst:
       Heizung AUS + slope > +0.25 °C/h  → Körperwärme       → present
       Heizung AUS + slope < −0.10 °C/h  → leeres Bett kühlt → not present
       Heizung AN  + slope > +0.40 °C/h  → leer heizt auf    → not present
       Heizung AN  + |slope| < 0.08 + prev > +0.20 → Einstieg → present
     Damit werden Solar-Boost-Phasen mit „Heizung an + leer" nicht mehr
     fälschlich als Präsenz interpretiert.
  3) Hysterese leicht entschärft: 5/20 → 8/25 Min — kürzere Toiletten-
     gänge werfen nicht mehr auf "leer", echter Einstieg braucht 8 Min.
  4) ``_apply_overrides`` wird vom Trigger-Pfad NICHT mehr aufgerufen.
     air_std / surface_temp / body-temp-diff bleiben in den Diagnose-
     Buffern erhalten und in ``get_diagnostics()`` sichtbar, beeinflussen
     die Präsenz-Entscheidung aber nicht mehr (Wasser-Only). Die alten
     Bumps haben bei Solar-Boost regelmäßig False Positives erzeugt.

Replay gegen ``pres.csv`` (echte Nacht 2026-04-28/29):
  4 Flips über 22 h vs. 9 spurious Flips des originalen
  ``binary_sensor.bett_prasenz``. Accuracy 85 % gegen den (selbst
  fehlerhaften) alten Sensor — die echte Genauigkeit gegen Schlaf-
  ground-truth liegt deutlich höher.

ENTSCHEIDUNGS-LOGIK (Priorität von oben nach unten):
  • Heizung aus + Auskühlung + stale  → STALE-COOLDOWN = leer (bricht Lock) [v11.1]
  • σ_d kurz > 0.055 °C               → CHAOS = Person + Lock 25 min ON
  • Chaos-Lock noch aktiv             → halte ON (slope nach Burst verzerrt)
  • slope > +0.20 °C/h                → leeres Bett heizt auf → OFF
  • slope < -0.10 °C/h                → Person raus, kühlt aus → OFF
  • slope ≈ 0 UND prev_slope > 0.15   → Aufheizen→Stabil = Einstieg → ON
  • sonst                             → halte bisherigen Status

CHAOS-LOCK:
  Nach Erkennung eines Chaos-Bursts (Einstieg, Bewegung, Decke verrücken)
  bleibt der Sensor 25 min ON. Ein längeres σ_d-Fenster > 0.045 °C
  frischt den Lock auf, sodass aktive Schläfer ihn kontinuierlich
  verlängern.

HYSTERESE (asymmetrisch):
  Einsteigen: 8 min konstant "da"  → kein Flackern bei Heizungs-Bursts
  Aussteigen: 25 min konstant "weg" → keine Fehlausstiege bei Toilettengängen
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
    local_now,
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

    # Hysterese (asymmetrisch: schnell rein, langsam raus).
    # v11: Anhebung von 5/20 auf 8/25 Minuten — kürzere Toilettengänge dürfen
    # den Sensor nicht mehr auf "leer" werfen, dafür braucht ein echter Einstieg
    # 8 statt 5 Minuten. Schwellen sind jetzt symmetrisch zu chaos_lock_minutes.
    presence_enter_minutes: int = 8
    presence_leave_minutes: int = 25

    # v11: Wasser-Only Slope/Sigma-Erkennung — quantisierungs-bewusst und
    # heizungs-bewusst. Der DS18B20-Sensor produziert auch bei leerem Bett ein
    # σ ≈ 0.031 °C aus reiner Quantisierung (12-bit, 0.0625 °C/LSB) — die alten
    # Schwellen 0.10 / 0.06 lagen bereits im Rauschbereich nach kurzen Fenstern.
    # v11.1: chaos_threshold auf 0.055 angehoben. Auf einem warmen, leeren Bett
    # (Heizung aus, Raum warm) erreicht σ_d kurzfristig bis ~0.051 °C aus reiner
    # Quantisierung + Konvektion — knapp über den alten 0.05. Das löste vereinzelt
    # falsche Bursts aus, die das leere Bett wieder ON verriegelten. 0.055 liegt
    # über diesem Leer-Floor; echte Bewegung im Wasser bleibt klar darüber.
    chaos_threshold: float = 0.055  # σ_d > X (kurz) → Bewegung im Wasser
    chaos_lock_minutes: int = 25  # Nach Chaos: ON-Lock für N Minuten
    chaos_refresh_threshold: float = 0.045  # σ_d_60 > X frischt Lock auf
    slope_body_warming: float = 0.25  # °C/h darüber OHNE Heizung → Körperwärme
    slope_heating_threshold: float = 0.40  # °C/h darüber MIT Heizung → leer
    slope_cooling_threshold: float = -0.10  # °C/h darunter OHNE Heizung → leer
    slope_stable_band: float = 0.08  # |slope| < X → stabile Phase
    slope_rise_threshold: float = 0.20  # prev_slope > X UND jetzt stabil = Einstieg

    # v11.1: Stale-Cooldown-Release — bricht den Chaos-Lock bei leerem Bett.
    # Ein warmes, leeres Bett kühlt mit ~0.06-0.16 °C/h aus; sein σ60-Rauschen
    # (~0.045-0.05) hielt den σ60-Lock in v11 stundenlang am Leben, sodass die
    # heizungs-bewusste Slope-Logik nie zum Zug kam (Bett blieb ~12 h fälschlich
    # ON, validiert an einem Tag-Schlaf-Datensatz mit echter Heizungs-Historie).
    # Ein anwesender Schläfer erzeugt dagegen immer wieder echte Bewegungs-Bursts
    # (σ_d > chaos_threshold) und gibt Körperwärme ab. Bedingung für „leer":
    # Heizung AUS + anhaltende Auskühlung + seit cooldown_release_minutes kein
    # echter Burst mehr.
    slope_cooldown_release: float = -0.05  # °C/h: sanfte, anhaltende Auskühlung
    cooldown_release_minutes: int = 90  # ohne echten Burst → Ausstieg (bricht Lock)

    # heat_ratio: nur Diagnose, KEIN Trigger (v9 deaktivierte das Bett zu früh)
    heat_ratio_window_minutes: int = 60  # Fenster für Heizverhältnis-Beobachtung
    heat_ratio_min_samples: int = 10  # Erst ab so vielen Samples berechnen


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
        self._heater_states: dict[int, deque] = {}  # v9: heater_active history
        self._max_buffer = 600  # ~5h bei 30s Updates

        # Zustand pro Zone
        self._is_present: dict[int, bool] = {}
        self._last_state_change: dict[int, Optional[datetime]] = {}

        # Asymmetrische Hysterese (pending = noch nicht bestätigter Wechsel)
        self._pending_state: dict[int, Optional[bool]] = {}
        self._pending_since: dict[int, Optional[datetime]] = {}

        # v8: Chaos-Lock (Zeitpunkt der letzten erkannten Aktivität)
        # Solange aktiv → Sensor bleibt ON, slope-basierte Logik wird ignoriert
        self._last_chaos_time: dict[int, Optional[datetime]] = {}

        # v11.1: Zeitpunkt des letzten ECHTEN Bewegungs-Bursts (σ_d > chaos).
        # Getrennt vom σ60-Lock-Refresh, der auch auf dem Rauschen eines warmen
        # leeren Betts feuert. Grundlage für den Stale-Cooldown-Release.
        self._last_burst_time: dict[int, Optional[datetime]] = {}

        # v11.1: „Bett ist sicher leer" — gesetzt vom Stale-Cooldown-Release.
        # Solange aktiv, darf der σ60-Refresh den Chaos-Lock NICHT neu aufbauen
        # (sonst weckt ein kurzer Heiz-Burst das leere Bett wieder auf). Wird
        # nur durch ECHTE Wiedereinstiegs-Evidenz gelöscht: Bewegungs-Burst,
        # Körperwärme-Anstieg oder rise→stable.
        self._empty_confirmed: dict[int, bool] = {}

        # Diagnostics
        self._last_water_variance: dict[int, float] = {}
        self._last_trend_consistency: dict[int, float] = {}
        self._last_water_std: dict[int, float] = {}
        self._last_air_std: dict[int, float] = {}
        self._last_confidence: dict[int, float] = {}
        self._last_reason: dict[int, str] = {}
        self._last_significant_changes: dict[int, int] = {}  # NEU: Debug
        self._last_heat_ratio: dict[int, Optional[float]] = {}  # v9: Diagnose

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
        now = local_now()

        # Daten speichern (inkl. heater_active für v9 Heat-Ratio)
        self._store(zone_index, water_temp, air_temp, humidity, now)
        self._store_heater(zone_index, heater_active, now)

        # ─────────────────────────────────────────────────────────────
        # Priorität 1: Dedizierter Präsenz-Sensor überschreibt alles
        # ─────────────────────────────────────────────────────────────
        if presence_sensor_state is not None:
            self._set_state(zone_index, presence_sensor_state, 1.0, "Präsenz-Sensor", now)
            return presence_sensor_state, 1.0, "Präsenz-Sensor"

        # ─────────────────────────────────────────────────────────────
        # Heizmatte: Trend-basierte Erkennung
        # ─────────────────────────────────────────────────────────────
        if is_heating_pad:
            return self._detect_presence_heating_pad(zone_index, water_temp, heater_active, now)

        # ─────────────────────────────────────────────────────────────
        # WASSERBETT v11: σ_detrended + heizungs-bewusster Slope
        # ─────────────────────────────────────────────────────────────
        buffer = self._water_temps.get(zone_index)
        if buffer is None or len(buffer) < self.thresholds.min_samples:
            current = self._is_present.get(zone_index, False)
            return current, 0.0, "Sammle Daten..."

        # σ-Signale: kurzes Fenster für Chaos-Erkennung,
        # längeres für Lock-Refresh
        detrended_std = self._calculate_detrended_std(zone_index)
        long_window = self.thresholds.history_window_minutes * 2
        detrended_std_long = self._calculate_detrended_std_window(zone_index, long_window)

        # Slope-Signale: aktueller Slope und Slope einer Stunde davor
        slope = self._calculate_slope_per_hour(zone_index, window_minutes=long_window)
        prev_slope = self._calculate_slope_per_hour(
            zone_index,
            window_minutes=self.thresholds.history_window_minutes,
            offset_minutes=self.thresholds.history_window_minutes,
        )

        # Rohes σ und Trend-Diagnostik (für Logs)
        raw_std = self._calc_std(buffer, self.thresholds.history_window_minutes) or 0.0
        trend_consistency, significant_changes = self._calculate_trend_consistency_noise_immune(zone_index)

        # Diagnostics speichern
        self._last_water_std[zone_index] = detrended_std
        self._last_water_variance[zone_index] = detrended_std**2
        self._last_trend_consistency[zone_index] = trend_consistency
        self._last_significant_changes[zone_index] = significant_changes

        # Luft-Varianz nur für Diagnostics (v11: nicht mehr Trigger)
        air_std = self._calc_std(self._air_temps.get(zone_index), self.thresholds.history_window_minutes)
        self._last_air_std[zone_index] = air_std or 0.0

        # ─────────────────────────────────────────────────────────────
        # Entscheidungslogik (v11: heater-aware, water-only)
        # ─────────────────────────────────────────────────────────────
        raw_present, confidence, reasons = self._determine_presence(
            detrended_std,
            detrended_std_long,
            slope,
            prev_slope,
            raw_std,
            air_std,
            water_temp,
            surface_temp,
            zone_index,
            now,
            heater_active=heater_active,
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

        cutoff = local_now() - timedelta(minutes=self.thresholds.history_window_minutes)
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
    # NEU v7: DETRENDED σ — Primär-Signal für Präsenz
    # ═══════════════════════════════════════════════════════════════════════

    def _calculate_detrended_std(self, zone_index: int) -> float:
        """
        Berechnet σ NACH Abzug der linearen Heiz-Rampe (Standard-Fenster).

        Rohes σ kann hoch sein, weil das Bett gleichmäßig heizt — das ist
        KEIN Mensch. Detrended σ misst nur die Reststreuung um die
        Trendlinie und ist damit immun gegen monotone Heizrampen.

        Reine Heizung (linear)  → detrended ≈ 0
        Person ruhig liegend    → detrended ≈ 0.04-0.06°C
        Person aktiv            → detrended > 0.10°C
        """
        return self._calculate_detrended_std_window(zone_index, self.thresholds.history_window_minutes)

    def _calculate_detrended_std_window(self, zone_index: int, window_minutes: int) -> float:
        """Wie _calculate_detrended_std aber mit konfigurierbarem Fenster."""
        buffer = self._water_temps.get(zone_index)
        if not buffer:
            return 0.0

        cutoff = local_now() - timedelta(minutes=window_minutes)
        temps = [val for ts, val in buffer if ts > cutoff and val is not None]

        n = len(temps)
        if n < 3:
            return 0.0

        x_mean = (n - 1) / 2
        y_mean = sum(temps) / n
        num = sum((i - x_mean) * (temps[i] - y_mean) for i in range(n))
        den = sum((i - x_mean) ** 2 for i in range(n))
        if den == 0:
            return 0.0
        slope = num / den
        intercept = y_mean - slope * x_mean

        residuals_sq = sum((temps[i] - (slope * i + intercept)) ** 2 for i in range(n))
        return (residuals_sq / n) ** 0.5

    # ═══════════════════════════════════════════════════════════════════════
    # NEU v8: SLOPE in °C/h — über Zeitstempel (nicht Index)
    # ═══════════════════════════════════════════════════════════════════════

    def _calculate_slope_per_hour(
        self,
        zone_index: int,
        window_minutes: Optional[int] = None,
        offset_minutes: int = 0,
    ) -> Optional[float]:
        """
        Linear-Regressions-Slope der Wassertemperatur in °C pro Stunde,
        über echtes Zeitfenster (nicht Sample-Index).

        Args:
            window_minutes: Fenster-Länge. Default = history_window_minutes * 2.
            offset_minutes: Wie viele Minuten zurück das Fenster ENDET
                            (für prev_slope: end = now - offset).

        Returns None wenn zu wenig Daten.

        Nutzung:
            slope = _calculate_slope_per_hour(zone)         # last 60 min
            prev  = _calculate_slope_per_hour(zone, offset_minutes=30)  # 30-90 min ago
        """
        buffer = self._water_temps.get(zone_index)
        if not buffer:
            return None

        if window_minutes is None:
            window_minutes = self.thresholds.history_window_minutes * 2

        now = local_now()
        end = now - timedelta(minutes=offset_minutes)
        start = end - timedelta(minutes=window_minutes)

        samples = [(ts, val) for ts, val in buffer if start <= ts <= end and val is not None]
        n = len(samples)
        if n < 3:
            return None

        # Slope in °C / hour
        t0 = samples[0][0]
        xs = [(ts - t0).total_seconds() / 3600 for ts, _ in samples]
        ys = [v for _, v in samples]
        x_mean = sum(xs) / n
        y_mean = sum(ys) / n
        num = sum((xs[i] - x_mean) * (ys[i] - y_mean) for i in range(n))
        den = sum((xs[i] - x_mean) ** 2 for i in range(n))
        if den == 0:
            return 0.0
        return num / den

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

        cutoff = local_now() - timedelta(minutes=self.thresholds.history_window_minutes)
        temps = [val for ts, val in buffer if ts > cutoff and val is not None]

        if len(temps) < 10:
            return 0.0

        # ═══ GLÄTTUNG: Moving Average über 5 Werte ═══
        window_size = 5
        smoothed = []
        for i in range(len(temps) - window_size + 1):
            window = temps[i : i + window_size]
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

        cutoff = local_now() - timedelta(minutes=self.thresholds.history_window_minutes)
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
    # ENTSCHEIDUNGSLOGIK v11 — Wasser-Only, heizungs-bewusst
    # ═══════════════════════════════════════════════════════════════════════
    # Siehe docs/presence_detector_v11.md für die ausführliche Begründung.
    # Kernidee gegenüber v8/v10:
    #  1) σ-Schwellen sind quantisierungs-bewusst (Floor ≈ 0.031 °C bei 0.0625 °C
    #     LSB). Alte 0.10 / 0.06 Schwellen lagen knapp über dem Floor und haben
    #     bei jedem Heizungs-Burst falsch ausgelöst.
    #  2) Slope-Logik ist heizungs-bewusst:
    #       - Anstieg OHNE aktive Heizung → Körperwärme → present
    #       - Anstieg MIT  aktiver Heizung → leeres Bett heizt auf → not present
    #       - Fall   OHNE aktive Heizung → leer kühlt aus → not present
    #     Dadurch werden Solar-Boost-Phasen mit „Heizung an + Bett leer" nicht
    #     mehr als Präsenz interpretiert.
    #  3) air_std / surface_temp / body-temp-diff sind aus dem Trigger-Pfad
    #     entfernt — sie bleiben in den Diagnose-Buffern, beeinflussen die
    #     Präsenz-Entscheidung aber nicht mehr (Wasser-Only). Die alten
    #     `_apply_overrides`-Bumps haben bei Solar-Boost regelmäßig False
    #     Positives erzeugt.

    def _determine_presence(
        self,
        detrended_std: float,
        detrended_std_long: float,
        slope: Optional[float],
        prev_slope: Optional[float],
        raw_std: float,
        air_std: Optional[float],
        water_temp: Optional[float],
        surface_temp: Optional[float],
        zone_index: int,
        now: datetime,
        heater_active: bool = False,
    ) -> Tuple[bool, float, list]:
        """Bett-Zustand aus σ-detrended + Slope + Chaos-Lock (v11)."""
        t = self.thresholds

        # heat_ratio nur für Diagnose — wird NICHT als Trigger benutzt.
        heat_ratio = self._heating_ratio(zone_index, now)
        self._last_heat_ratio[zone_index] = heat_ratio

        reasons = [
            f"σd={detrended_std:.3f}",
            f"σd60={detrended_std_long:.3f}",
            f"slope={slope if slope is not None else 0:+.2f}/h",
            "heat=on" if heater_active else "heat=off",
        ]
        if heat_ratio is not None:
            reasons.append(f"heat%={heat_ratio:.0%}")

        # ─── Echte Bewegungs-Bursts getrennt mitschreiben ─────────────────
        # Nur σ_d (kurz) über chaos_threshold zählt als echter Burst. Der
        # σ60-Refresh weiter unten feuert auch auf Leer-Rauschen — er darf
        # den Stale-Timer NICHT zurücksetzen.
        if detrended_std > t.chaos_threshold:
            self._last_burst_time[zone_index] = now

        # ─── 0) Stale heizungs-aus Cooldown ⇒ Bett ist leer ──────────────
        # Bricht den Chaos-Lock: Heizung AUS + anhaltende Auskühlung + seit
        # cooldown_release_minutes kein echter Burst → die Person ist raus.
        # Ein anwesender Schläfer gibt Körperwärme ab (Trend flach/steigend)
        # und erzeugt wiederkehrende Bursts; ein warmes leeres Bett kühlt
        # stetig aus, während sein σ60-Rauschen den Lock sonst ON hielte.
        #
        # "Stale" wird relativ zum letzten echten Burst gemessen — gab es noch
        # nie einen, relativ zum Beobachtungsbeginn (ältester Puffer-Sample).
        # So löst ein 30-min-Kaltstart NICHT sofort aus, sondern erst nach
        # cooldown_release_minutes tatsächlicher Beobachtung.
        last_burst = self._last_burst_time.get(zone_index)
        buffer = self._water_temps.get(zone_index)
        stale_since = last_burst if last_burst is not None else (buffer[0][0] if buffer else now)
        quiet_min = (now - stale_since).total_seconds() / 60
        if (
            not heater_active
            and slope is not None
            and slope < t.slope_cooldown_release
            and quiet_min >= t.cooldown_release_minutes
        ):
            self._empty_confirmed[zone_index] = True
            tag = "seit-start" if last_burst is None else "letzter-burst"
            reasons.append(f"→stale-cooldown(empty, {tag}={quiet_min:.0f}min)")
            return False, 0.10, reasons

        empty_confirmed = self._empty_confirmed.get(zone_index, False)

        # ─── Chaos-Lock auffrischen wenn längeres Fenster aktiv aussieht ──
        # NICHT solange das Bett als leer bestätigt ist — sonst baut das
        # σ60-Rauschen (oder ein kurzer Heiz-Burst) den Lock sofort wieder auf.
        if detrended_std_long > t.chaos_refresh_threshold and not empty_confirmed:
            self._last_chaos_time[zone_index] = now

        # ─── 1) Chaos-Burst: sofort ON (echter Wiedereinstieg) ────────────
        if detrended_std > t.chaos_threshold:
            self._last_chaos_time[zone_index] = now
            self._empty_confirmed[zone_index] = False
            reasons.append("→chaos")
            return True, 0.95, reasons

        # ─── 2) Chaos-Lock aktiv: ON halten ──────────────────────────────
        # Ein bestätigt leeres Bett wird NICHT vom Lock wiederbelebt.
        last_chaos = self._last_chaos_time.get(zone_index)
        if last_chaos is not None and not empty_confirmed:
            elapsed_min = (now - last_chaos).total_seconds() / 60
            if elapsed_min < t.chaos_lock_minutes:
                reasons.append(f"→lock({elapsed_min:.0f}/{t.chaos_lock_minutes}min)")
                return True, 0.85, reasons

        # ─── 3) Slope-basierte Phasen (nur wenn genug Daten) ──────────────
        if slope is None:
            current = self._is_present.get(zone_index, False)
            reasons.append("→halte(zu wenig Daten)")
            return current, 0.30, reasons

        if heater_active:
            # Heizung an: starker Anstieg ist erwartetes Aufheizen → leer.
            if slope > t.slope_heating_threshold:
                reasons.append("→heizt(empty)")
                return False, 0.10, reasons
            # rise→stable greift auch unter aktiver Heizung (Person dämpft Rampe).
            if (
                abs(slope) < t.slope_stable_band
                and prev_slope is not None
                and prev_slope > t.slope_rise_threshold
            ):
                reasons.append(f"→rise→stable(prev={prev_slope:+.2f})")
                self._last_chaos_time[zone_index] = now
                self._empty_confirmed[zone_index] = False
                return True, 0.80, reasons
        else:
            # Heizung aus: Physik gibt sauberes Signal.
            # Anstieg ohne Heizung = Körperwärme.
            if slope > t.slope_body_warming:
                reasons.append("→Körperwärme")
                self._last_chaos_time[zone_index] = now
                self._empty_confirmed[zone_index] = False
                return True, 0.90, reasons
            # Fall ohne Heizung = leer kühlt aus.
            if slope < t.slope_cooling_threshold:
                reasons.append("→kühlt(empty)")
                return False, 0.10, reasons
            # Stabil nach starkem Anstieg = Person eingestiegen.
            if (
                abs(slope) < t.slope_stable_band
                and prev_slope is not None
                and prev_slope > t.slope_rise_threshold
            ):
                reasons.append(f"→rise→stable(prev={prev_slope:+.2f})")
                self._empty_confirmed[zone_index] = False
                self._last_chaos_time[zone_index] = now
                return True, 0.80, reasons

        # ─── 4) Mildes Drift / unklar: bisherigen Status halten ───────────
        current = self._is_present.get(zone_index, False)
        reasons.append("→halte")
        return current, 0.40, reasons

    def _apply_overrides(
        self,
        raw_present: bool,
        confidence: float,
        reasons: list,
        air_std: Optional[float],
        water_temp: Optional[float],
        surface_temp: Optional[float],
    ) -> Tuple[bool, float, list]:
        """v11: NICHT mehr aus dem Trigger-Pfad aufgerufen.

        Die Methode bleibt definiert, damit externe Aufrufer / Tests, die
        sie noch verwenden, weiter funktionieren. Sie ist aber nicht mehr
        Teil der Präsenz-Entscheidung — air_std / surface_temp / body-temp-
        diff haben in v11 keinen Einfluss mehr auf is_present.
        """
        # Luft-Varianz als Verstärker
        if air_std is not None:
            at = self.thresholds.air_variance_threshold
            if air_std > at:
                confidence = min(1.0, confidence + 0.15)
                if not raw_present and air_std > at * 2:
                    raw_present = True
                reasons.append(f"σL={air_std:.3f}")

        # Auflagen-Temperatur (Körperkontakt)
        if surface_temp is not None and water_temp is not None:
            diff = surface_temp - water_temp
            if diff > self.thresholds.body_temp_diff:
                raw_present = True
                confidence = max(confidence, 0.80)
                reasons.append(f"Körper(Δ={diff:.1f}°C)")

        return raw_present, confidence, reasons

    # ═══════════════════════════════════════════════════════════════════════
    # DEBOUNCE
    # ═══════════════════════════════════════════════════════════════════════

    def _apply_debounce(self, zone_index: int, raw_present: bool, now: datetime) -> bool:
        """
        Asymmetrische Hysterese (schnell rein / langsam raus):
        • Einsteigen (OFF→ON): presence_enter_minutes konstant "da" (v11: 8)
        • Aussteigen (ON→OFF): presence_leave_minutes konstant "weg" (v11: 25)

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
        required = self.thresholds.presence_enter_minutes if raw_present else self.thresholds.presence_leave_minutes

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

    def _calc_std(self, buffer: Optional[deque], window_minutes: int) -> Optional[float]:
        """Berechnet Standardabweichung über rollendes Zeitfenster."""
        if buffer is None or len(buffer) < self.thresholds.min_samples:
            return None

        cutoff = local_now() - timedelta(minutes=window_minutes)
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

        now = local_now()

        recent_cutoff = now - timedelta(minutes=self.thresholds.sweat_confirm_minutes)
        recent = [val for ts, val in buffer if ts > recent_cutoff and val is not None]
        if len(recent) < 5:
            return False

        avg_recent = sum(recent) / len(recent)

        baseline_cutoff = now - timedelta(hours=6)
        all_vals = [val for ts, val in buffer if ts > baseline_cutoff and val is not None]
        if not all_vals:
            return False

        baseline = min(all_vals)
        rise = avg_recent - baseline

        return avg_recent > self.thresholds.sweat_humidity_abs and rise > self.thresholds.sweat_humidity_rise

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

        now = local_now()
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

    def _store_heater(self, zone_index: int, heater_active: bool, now: datetime):
        """v9: Speichert heater_active-Verlauf für Heat-Ratio-Berechnung."""
        if zone_index not in self._heater_states:
            self._heater_states[zone_index] = deque(maxlen=self._max_buffer)
        self._heater_states[zone_index].append((now, bool(heater_active)))

    def _heating_ratio(self, zone_index: int, now: datetime) -> Optional[float]:
        """
        v9: Anteil der Zeit, in der die Heizung im Fenster aktiv war.

        Person im Bett senkt den Heizbedarf — wenig Heizen + stabile Temp
        = Körperwärme deckt den Verlust. Sehr robustes Signal aus v1.0.

        Returns:
            None falls zu wenig History, sonst Anteil [0.0..1.0].
        """
        history = self._heater_states.get(zone_index)
        if not history:
            return None
        cutoff = now - timedelta(minutes=self.thresholds.heat_ratio_window_minutes)
        samples = [active for ts, active in history if ts > cutoff]
        if len(samples) < self.thresholds.heat_ratio_min_samples:
            return None
        return sum(1 for s in samples if s) / len(samples)

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

        # v8 diagnostics
        slope = self._calculate_slope_per_hour(zone_index)
        last_chaos = self._last_chaos_time.get(zone_index)
        chaos_lock_remaining = 0.0
        if last_chaos is not None:
            elapsed = (local_now() - last_chaos).total_seconds() / 60
            chaos_lock_remaining = max(0.0, self.thresholds.chaos_lock_minutes - elapsed)

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
            "significant_changes": sig_changes,
            "water_temp_std": round(w_std, 4),
            "air_temp_std": round(a_std, 4),
            "slope_per_hour": round(slope, 3) if slope is not None else None,
            "chaos_lock_remaining_min": round(chaos_lock_remaining, 1),
            "heat_ratio": (
                round(self._last_heat_ratio.get(zone_index), 3)
                if self._last_heat_ratio.get(zone_index) is not None
                else None
            ),
            "noise_threshold": SENSOR_NOISE_THRESHOLD,
            "thresholds": {
                "variance_low": self.thresholds.variance_low,
                "variance_high": self.thresholds.variance_high,
                "trend_threshold": self.thresholds.trend_threshold,
                "trend_chaotic": self.thresholds.trend_chaotic,
                "slope_heating": self.thresholds.slope_heating_threshold,
                "slope_cooling": self.thresholds.slope_cooling_threshold,
                "chaos": self.thresholds.chaos_threshold,
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
