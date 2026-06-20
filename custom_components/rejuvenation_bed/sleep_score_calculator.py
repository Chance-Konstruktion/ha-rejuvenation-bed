"""
Schlaf-Score Calculator für das Rejuvenation Bed.

Berechnet einen täglichen Schlaf-Score (0-100) basierend auf:
- Temperatur-Stabilität (30%)
- Kurven-Treue (35%)
- Aufwärmzeit (15%)
- Heizzyklen-Effizienz (10%)
- Luftqualität/CO2 (10%) - optional

Das ist DAS Feature, das User lieben werden!
"""

import logging
from datetime import datetime, time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import deque
from homeassistant.core import HomeAssistant
from .const import local_now

_LOGGER = logging.getLogger(__name__)


@dataclass
class NightData:
    """Daten einer Nacht für Score-Berechnung."""

    date: datetime
    zone_index: int

    # Temperatur-Daten
    temp_readings: List[float] = field(default_factory=list)
    target_temps: List[float] = field(default_factory=list)

    # Timing
    bedtime_actual: Optional[datetime] = None
    bedtime_planned: Optional[datetime] = None
    wake_time_actual: Optional[datetime] = None
    wake_time_planned: Optional[datetime] = None

    # Heizzyklen
    heating_cycles: int = 0
    total_heating_minutes: float = 0
    short_cycles_prevented: int = 0

    # Unterbrechungen (Toilette, Kind, etc.)
    interruptions: int = 0
    total_interruption_minutes: float = 0

    # CO2 (optional)
    co2_readings: List[float] = field(default_factory=list)

    # Flags
    bed_was_warm_at_bedtime: bool = False
    nadir_time_actual: Optional[datetime] = None
    nadir_time_expected: Optional[datetime] = None


@dataclass
class SleepScore:
    """Ergebnis der Score-Berechnung."""

    total_score: int  # 0-100

    # Einzelne Komponenten
    temperature_stability_score: int  # 0-100
    curve_adherence_score: int  # 0-100
    warmup_score: int  # 0-100
    heating_efficiency_score: int  # 0-100
    air_quality_score: int  # 0-100 (oder -1 wenn kein CO2-Sensor)

    # Gewichtete Beiträge
    temperature_contribution: float
    curve_contribution: float
    warmup_contribution: float
    efficiency_contribution: float
    air_quality_contribution: float

    # Meta
    date: datetime
    zone_index: int
    has_co2_data: bool

    # Tipps
    tips: List[str] = field(default_factory=list)
    trend: str = ""  # "↑", "↓", "→"
    trend_value: int = 0  # +5, -3, etc.


class SleepScoreCalculator:
    """
    Berechnet den Schlaf-Score basierend auf Nacht-Daten.

    Gewichtung:
    - Temperatur-Stabilität: 5%
    - Kurven-Treue: 35%
    - Heizzyklen-Effizienz: 35%
    - CO2 Luftqualität (optional): 25%

    Ohne CO2 werden die anderen Faktoren proportional hochskaliert:
    - Temperatur-Stabilität: ~6.7%
    - Kurven-Treue: ~46.7%
    - Heizzyklen-Effizienz: ~46.7%
    """

    # Gewichtungen
    WEIGHT_TEMPERATURE_STABILITY = 0.05
    WEIGHT_CURVE_ADHERENCE = 0.35
    WEIGHT_WARMUP = 0.00  # Entfernt
    WEIGHT_HEATING_EFFICIENCY = 0.35
    WEIGHT_AIR_QUALITY = 0.25

    # CO2 Schwellenwerte
    CO2_EXCELLENT = 600  # ppm - sehr gut
    CO2_GOOD = 800  # ppm - gut
    CO2_MODERATE = 1000  # ppm - akzeptabel
    CO2_POOR = 1500  # ppm - schlecht
    CO2_BAD = 2000  # ppm - sehr schlecht

    # Temperatur-Toleranzen
    TEMP_TOLERANCE_EXCELLENT = 0.3  # °C Abweichung
    TEMP_TOLERANCE_GOOD = 0.5
    TEMP_TOLERANCE_ACCEPTABLE = 1.0

    def __init__(self, hass: HomeAssistant, config_entry):
        """Initialisiert den Score-Calculator."""
        self.hass = hass
        self.config_entry = config_entry

        # Historie für Trend-Berechnung (letzte 30 Tage pro Zone)
        self._score_history: Dict[int, deque] = {}

        # Aktuelle Nacht-Daten (werden während der Nacht gesammelt)
        self._current_night: Dict[int, NightData] = {}

        # CO2 Sensor (optional)
        self.co2_sensor = config_entry.options.get("co2_sensor") or config_entry.data.get("global", {}).get(
            "co2_sensor"
        )

    def start_night_tracking(self, zone_index: int, planned_bedtime: datetime, planned_wake: datetime):
        """
        Startet das Tracking für eine neue Nacht.

        Wird aufgerufen wenn Präsenz erkannt wird oder zur geplanten Schlafzeit.
        """
        today = local_now().date()

        self._current_night[zone_index] = NightData(
            date=datetime.combine(today, time(0, 0)),
            zone_index=zone_index,
            bedtime_planned=planned_bedtime,
            wake_time_planned=planned_wake,
            bedtime_actual=local_now(),
        )

        _LOGGER.info(f"Zone {zone_index}: Nacht-Tracking gestartet")

    def record_temperature(self, zone_index: int, current_temp: float, target_temp: float):
        """Zeichnet einen Temperatur-Datenpunkt auf."""
        if zone_index not in self._current_night:
            return

        night = self._current_night[zone_index]
        night.temp_readings.append(current_temp)
        night.target_temps.append(target_temp)

    def record_interruption(self, zone_index: int, duration_minutes: float):
        """
        Zeichnet eine Schlaf-Unterbrechung auf (Toilette, Kind, etc.).

        Fließt negativ in den Score ein: Aufwachen = schlechterer Schlaf.
        """
        if zone_index not in self._current_night:
            return

        night = self._current_night[zone_index]
        night.interruptions += 1
        night.total_interruption_minutes += duration_minutes
        _LOGGER.debug(
            f"Zone {zone_index}: Schlaf-Unterbrechung #{night.interruptions} " f"({duration_minutes:.0f} Min)"
        )

    def record_co2(self, zone_index: int, co2_ppm: float):
        """Zeichnet einen CO2-Wert auf."""
        if zone_index not in self._current_night:
            return

        self._current_night[zone_index].co2_readings.append(co2_ppm)

    def record_bed_warm_at_bedtime(self, zone_index: int, was_warm: bool):
        """Markiert ob das Bett zur Schlafzeit warm war."""
        if zone_index not in self._current_night:
            return

        self._current_night[zone_index].bed_was_warm_at_bedtime = was_warm

    def end_night_tracking(self, zone_index: int) -> Optional[SleepScore]:
        """
        Beendet das Nacht-Tracking und berechnet den Score.

        Wird aufgerufen wenn Person aufsteht oder zur geplanten Aufwachzeit.

        Returns:
            SleepScore oder None wenn nicht genug Daten
        """
        if zone_index not in self._current_night:
            _LOGGER.warning(f"Zone {zone_index}: Kein aktives Nacht-Tracking")
            return None

        night = self._current_night[zone_index]
        night.wake_time_actual = local_now()

        # Mindestens 2 Stunden Daten?
        if len(night.temp_readings) < 20:  # ~20 Datenpunkte bei 6min Intervall = 2h
            _LOGGER.warning(f"Zone {zone_index}: Nicht genug Daten für Score ({len(night.temp_readings)} Punkte)")
            del self._current_night[zone_index]
            return None

        # Score berechnen
        score = self._calculate_score(night)

        # In Historie speichern
        if zone_index not in self._score_history:
            self._score_history[zone_index] = deque(maxlen=30)
        self._score_history[zone_index].append(score)

        # Trend berechnen
        score.trend, score.trend_value = self._calculate_trend(zone_index)

        # Aufräumen
        del self._current_night[zone_index]

        _LOGGER.info(
            f"Zone {zone_index}: Schlaf-Score berechnet: {score.total_score}/100 "
            f"(Trend: {score.trend}{score.trend_value})"
        )

        return score

    def _calculate_score(self, night: NightData) -> SleepScore:
        """Berechnet den Score aus den Nacht-Daten."""

        # Einzelne Scores berechnen
        temp_score = self._calc_temperature_stability(night)
        curve_score = self._calc_curve_adherence(night)
        warmup_score = self._calc_warmup_score(night)
        efficiency_score = self._calc_heating_efficiency(night)
        air_score, has_co2 = self._calc_air_quality(night)

        # Gewichtung anpassen wenn kein CO2
        if has_co2:
            weights = {
                "temp": self.WEIGHT_TEMPERATURE_STABILITY,
                "curve": self.WEIGHT_CURVE_ADHERENCE,
                "warmup": self.WEIGHT_WARMUP,
                "efficiency": self.WEIGHT_HEATING_EFFICIENCY,
                "air": self.WEIGHT_AIR_QUALITY,
            }
        else:
            # Ohne CO2: Proportional auf die anderen verteilen
            # Temp: 5%, Curve: 35%, Efficiency: 35% → Summe 75%
            # Skalieren auf 100%: 5/75=6.67%, 35/75=46.67%, 35/75=46.67%
            scale = 1.0 / (1.0 - self.WEIGHT_AIR_QUALITY)
            weights = {
                "temp": self.WEIGHT_TEMPERATURE_STABILITY * scale,
                "curve": self.WEIGHT_CURVE_ADHERENCE * scale,
                "warmup": 0,
                "efficiency": self.WEIGHT_HEATING_EFFICIENCY * scale,
                "air": 0,
            }

        # Gewichtete Beiträge
        temp_contrib = temp_score * weights["temp"]
        curve_contrib = curve_score * weights["curve"]
        warmup_contrib = warmup_score * weights["warmup"]
        efficiency_contrib = efficiency_score * weights["efficiency"]
        air_contrib = air_score * weights["air"] if has_co2 else 0

        # Gesamt-Score
        total = temp_contrib + curve_contrib + warmup_contrib + efficiency_contrib + air_contrib

        # Unterbrechungs-Malus: Jedes Aufwachen kostet Punkte
        # 1 Unterbrechung: -3 Punkte, 2: -7, 3+: -12
        interruption_penalty = 0
        if night.interruptions == 1:
            interruption_penalty = 3
        elif night.interruptions == 2:
            interruption_penalty = 7
        elif night.interruptions >= 3:
            interruption_penalty = 12

        total = max(0, total - interruption_penalty)
        total_score = int(round(total))

        # Tipps generieren
        tips = self._generate_tips(temp_score, curve_score, warmup_score, efficiency_score, air_score, has_co2, night)

        return SleepScore(
            total_score=max(0, min(100, total_score)),
            temperature_stability_score=temp_score,
            curve_adherence_score=curve_score,
            warmup_score=warmup_score,
            heating_efficiency_score=efficiency_score,
            air_quality_score=air_score if has_co2 else -1,
            temperature_contribution=temp_contrib,
            curve_contribution=curve_contrib,
            warmup_contribution=warmup_contrib,
            efficiency_contribution=efficiency_contrib,
            air_quality_contribution=air_contrib,
            date=night.date,
            zone_index=night.zone_index,
            has_co2_data=has_co2,
            tips=tips,
        )

    def _calc_temperature_stability(self, night: NightData) -> int:
        """
        Berechnet Temperatur-Stabilität (0-100).

        Misst wie konstant die Temperatur während der Nacht war.
        Wenig Schwankungen = gut.
        """
        if len(night.temp_readings) < 2:
            return 50  # Neutral bei zu wenig Daten

        # Standardabweichung berechnen
        temps = night.temp_readings
        avg = sum(temps) / len(temps)
        variance = sum((t - avg) ** 2 for t in temps) / len(temps)
        std_dev = variance**0.5

        # Score: Je niedriger die Std-Abweichung, desto besser
        # 0.0 - 0.3°C = 100 Punkte
        # 0.3 - 0.5°C = 80-100 Punkte
        # 0.5 - 1.0°C = 50-80 Punkte
        # > 1.0°C = 0-50 Punkte

        if std_dev <= self.TEMP_TOLERANCE_EXCELLENT:
            score = 100
        elif std_dev <= self.TEMP_TOLERANCE_GOOD:
            # Linear interpolieren 100 → 80
            score = (
                100
                - (std_dev - self.TEMP_TOLERANCE_EXCELLENT)
                / (self.TEMP_TOLERANCE_GOOD - self.TEMP_TOLERANCE_EXCELLENT)
                * 20
            )
        elif std_dev <= self.TEMP_TOLERANCE_ACCEPTABLE:
            # Linear interpolieren 80 → 50
            score = (
                80
                - (std_dev - self.TEMP_TOLERANCE_GOOD)
                / (self.TEMP_TOLERANCE_ACCEPTABLE - self.TEMP_TOLERANCE_GOOD)
                * 30
            )
        else:
            # Linear interpolieren 50 → 0
            score = max(0, 50 - (std_dev - self.TEMP_TOLERANCE_ACCEPTABLE) * 25)

        return int(round(score))

    def _calc_curve_adherence(self, night: NightData) -> int:
        """
        Berechnet Kurven-Treue (0-100).

        Misst wie gut die tatsächliche Temperatur der Zielkurve folgte.
        """
        if len(night.temp_readings) != len(night.target_temps) or len(night.temp_readings) < 2:
            return 50

        # Durchschnittliche Abweichung von Zieltemperatur
        deviations = [abs(actual - target) for actual, target in zip(night.temp_readings, night.target_temps)]
        avg_deviation = sum(deviations) / len(deviations)

        # Score basierend auf Abweichung
        # 0.0 - 0.3°C = 100 Punkte
        # 0.3 - 0.5°C = 80-100 Punkte
        # 0.5 - 1.0°C = 50-80 Punkte
        # > 1.0°C = 0-50 Punkte

        if avg_deviation <= 0.3:
            score = 100
        elif avg_deviation <= 0.5:
            score = 100 - (avg_deviation - 0.3) / 0.2 * 20
        elif avg_deviation <= 1.0:
            score = 80 - (avg_deviation - 0.5) / 0.5 * 30
        else:
            score = max(0, 50 - (avg_deviation - 1.0) * 25)

        # Bonus/Malus für Nadir-Timing (wenn vorhanden)
        if night.nadir_time_actual and night.nadir_time_expected:
            nadir_diff_minutes = abs((night.nadir_time_actual - night.nadir_time_expected).total_seconds() / 60)

            # Nadir innerhalb 30 Min = +10 Bonus
            # Nadir > 60 Min daneben = -10 Malus
            if nadir_diff_minutes <= 30:
                score = min(100, score + 10)
            elif nadir_diff_minutes > 60:
                score = max(0, score - 10)

        return int(round(score))

    def _calc_warmup_score(self, night: NightData) -> int:
        """
        Berechnet Aufwärm-Score (0-100).

        War das Bett rechtzeitig warm?
        """
        if night.bed_was_warm_at_bedtime:
            return 100

        # Wenn nicht warm: Wie lange hat es gedauert?
        if night.bedtime_planned and night.bedtime_actual:
            delay_minutes = (night.bedtime_actual - night.bedtime_planned).total_seconds() / 60

            # Negativ = Person kam früher als geplant (Bett noch nicht warm)
            if delay_minutes < 0:
                # Je früher, desto schlechter
                return max(0, 100 + int(delay_minutes))  # -1 Min = 99, -30 Min = 70
            else:
                # Person kam später = Bett hatte Zeit = gut
                return 100

        return 70  # Default bei fehlenden Daten

    def _calc_heating_efficiency(self, night: NightData) -> int:
        """
        Berechnet Heizeffizienz (0-100).

        Wenige, lange Zyklen sind besser als viele kurze.
        """
        if night.heating_cycles == 0:
            return 100  # Keine Heizung nötig = perfekt (oder Sommer)

        # Durchschnittliche Zykluslänge
        avg_cycle_length = night.total_heating_minutes / night.heating_cycles

        # Ideal: > 15 Min pro Zyklus
        # Schlecht: < 5 Min pro Zyklus

        if avg_cycle_length >= 15:
            base_score = 100
        elif avg_cycle_length >= 10:
            base_score = 80 + (avg_cycle_length - 10) * 4
        elif avg_cycle_length >= 5:
            base_score = 50 + (avg_cycle_length - 5) * 6
        else:
            base_score = max(0, avg_cycle_length * 10)

        # Bonus für verhinderte Short-Cycles
        if night.short_cycles_prevented > 0:
            bonus = min(10, night.short_cycles_prevented * 2)
            base_score = min(100, base_score + bonus)

        return int(round(base_score))

    def _calc_air_quality(self, night: NightData) -> Tuple[int, bool]:
        """
        Berechnet Luftqualität-Score (0-100).

        Returns:
            (score, has_data) - Score und ob CO2-Daten vorhanden waren
        """
        if not night.co2_readings:
            return (0, False)

        # Durchschnittlicher CO2-Wert
        avg_co2 = sum(night.co2_readings) / len(night.co2_readings)

        # Score berechnen
        if avg_co2 <= self.CO2_EXCELLENT:
            score = 100
        elif avg_co2 <= self.CO2_GOOD:
            score = 100 - (avg_co2 - self.CO2_EXCELLENT) / (self.CO2_GOOD - self.CO2_EXCELLENT) * 15
        elif avg_co2 <= self.CO2_MODERATE:
            score = 85 - (avg_co2 - self.CO2_GOOD) / (self.CO2_MODERATE - self.CO2_GOOD) * 25
        elif avg_co2 <= self.CO2_POOR:
            score = 60 - (avg_co2 - self.CO2_MODERATE) / (self.CO2_POOR - self.CO2_MODERATE) * 35
        else:
            score = max(0, 25 - (avg_co2 - self.CO2_POOR) / 500 * 25)

        return (int(round(score)), True)

    def _generate_tips(
        self,
        temp_score: int,
        curve_score: int,
        warmup_score: int,
        efficiency_score: int,
        air_score: int,
        has_co2: bool,
        night: NightData = None,
    ) -> List[str]:
        """Generiert personalisierte Tipps basierend auf den Scores."""
        tips = []

        # Unterbrechungen
        if night and night.interruptions >= 3:
            tips.append(
                f"😴 {night.interruptions}× aufgewacht ({night.total_interruption_minutes:.0f} Min) – häufige Unterbrechungen belasten den Schlaf"
            )
        elif night and night.interruptions >= 1:
            tips.append(f"😴 {night.interruptions}× aufgewacht – Unterbrechungen leicht negativ")

        # Temperatur-Stabilität (nur bei extremen Abweichungen)
        if temp_score < 40:
            tips.append("🌡️ Große Temperaturschwankungen - prüfe Isolierung oder Heizleistung")

        # Kurven-Treue (wichtig!)
        if curve_score < 60:
            tips.append("📈 Biorhythmus-Kurve wurde nicht gut eingehalten - Heizung evtl. zu schwach?")
        elif curve_score < 80:
            tips.append("📈 Kurve leicht abweichend - Chronotyp-Einstellung prüfen")

        # Heizeffizienz (wichtig!)
        if efficiency_score < 60:
            tips.append("🔄 Viele kurze Heizzyklen - evtl. Hysterese erhöhen oder Heizleistung prüfen")
        elif efficiency_score < 80:
            tips.append("🔄 Heizzyklen könnten effizienter sein")

        # CO2 (sehr wichtig bei 25%!)
        if has_co2:
            if air_score < 50:
                tips.append("💨 CO2 war sehr hoch - unbedingt vor dem Schlafen lüften!")
            elif air_score < 70:
                tips.append("💨 Luftqualität verbesserungswürdig - Fenster kippen?")
            elif air_score < 85:
                tips.append("💨 CO2 war leicht erhöht - etwas mehr lüften")

        # Lob bei guten Scores
        if not tips:
            if curve_score >= 90 and efficiency_score >= 90:
                tips.append("🌟 Exzellent! Dein Bett arbeitet optimal.")
            else:
                tips.append("✅ Gute Nacht! Alles im grünen Bereich.")

        return tips

    def _calculate_trend(self, zone_index: int) -> Tuple[str, int]:
        """
        Berechnet den Trend im Vergleich zur letzten Woche.

        Returns:
            (symbol, value) - z.B. ("↑", 5) oder ("↓", -3)
        """
        if zone_index not in self._score_history:
            return ("→", 0)

        history = list(self._score_history[zone_index])

        if len(history) < 2:
            return ("→", 0)

        # Vergleiche aktuellen Score mit Durchschnitt der letzten 7 Tage
        current = history[-1].total_score

        if len(history) >= 7:
            week_avg = sum(s.total_score for s in history[-8:-1]) / 7
        else:
            week_avg = sum(s.total_score for s in history[:-1]) / len(history[:-1])

        diff = int(round(current - week_avg))

        if diff > 2:
            return ("↑", diff)
        elif diff < -2:
            return ("↓", diff)
        else:
            return ("→", diff)

    def get_last_score(self, zone_index: int) -> Optional[SleepScore]:
        """Gibt den letzten Score für eine Zone zurück."""
        if zone_index not in self._score_history or not self._score_history[zone_index]:
            return None
        return self._score_history[zone_index][-1]

    def get_weekly_average(self, zone_index: int) -> Optional[float]:
        """Gibt den Wochen-Durchschnitt zurück."""
        if zone_index not in self._score_history:
            return None

        history = list(self._score_history[zone_index])
        if not history:
            return None

        recent = history[-7:] if len(history) >= 7 else history
        return sum(s.total_score for s in recent) / len(recent)

    def get_score_history(self, zone_index: int, days: int = 30) -> List[SleepScore]:
        """Gibt die Score-Historie zurück."""
        if zone_index not in self._score_history:
            return []

        history = list(self._score_history[zone_index])
        return history[-days:]

    def get_diagnostics(self, zone_index: int) -> dict:
        """Gibt Diagnose-Informationen zurück."""
        last_score = self.get_last_score(zone_index)
        weekly_avg = self.get_weekly_average(zone_index)

        current_night = self._current_night.get(zone_index)

        return {
            "last_score": last_score.total_score if last_score else None,
            "last_score_date": last_score.date.isoformat() if last_score else None,
            "weekly_average": round(weekly_avg, 1) if weekly_avg else None,
            "trend": last_score.trend if last_score else None,
            "trend_value": last_score.trend_value if last_score else None,
            "tips": last_score.tips if last_score else [],
            "is_tracking": current_night is not None,
            "tracking_data_points": len(current_night.temp_readings) if current_night else 0,
            "co2_sensor_configured": self.co2_sensor is not None,
            "history_days": len(self._score_history.get(zone_index, [])),
        }
