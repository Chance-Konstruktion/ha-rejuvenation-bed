"""
Biorhythmus-Temperaturkurve für das Rejuvenation Bed.

Diese Datei enthält KEINE Home Assistant-Abhängigkeiten - reine Mathematik!
Sie kann isoliert getestet und auch außerhalb von HA verwendet werden.

Physiologische Grundlagen:
- Tiefschlaf korreliert mit fallender Körperkerntemperatur
- Aufwachen korreliert mit steigendem Temperaturgradienten
- Plötzliche Sprünge → Stress / Mikro-Arousals
- Das Bett moduliert die periphere Temperatur zur Unterstützung
"""

import math
from datetime import datetime, time, timedelta
from typing import Tuple, Optional
import logging

_LOGGER = logging.getLogger(__name__)

# NEU: Chronotyp Nadir-Offsets (in Stunden)
CHRONOTYPE_NADIR_OFFSETS = {
    "lerche": -1.5,  # Nadir 1.5h früher (~02:00 statt ~03:30)
    "normal": 0.0,  # Nadir wie berechnet (~03:30)
    "eule": +1.5,  # Nadir 1.5h später (~05:00)
}


class BiorhythmusCurve:
    """
    Berechnet die optimale Bett-Temperatur basierend auf circadianen Rhythmen.

    Die Kurve ist asymmetrisch (Einschlafen ≠ Aufwachen) und nutzt
    Cosinus-Interpolation für glatte Übergänge ohne Relais-Flattern.

    SAISONALE ANPASSUNG (basierend auf Schlafmedizin):
    - Sommer (>20°C außen): 26-28°C Wassertemperatur
    - Winter (<15°C außen): 28-30°C Wassertemperatur
    - Übergang: Lineare Interpolation
    """

    # ═══════════════════════════════════════════════════════════════════════════
    # SAISONALE TEMPERATUR-PROFILE (basierend auf Schlafmedizin)
    # ═══════════════════════════════════════════════════════════════════════════

    # SOMMER-PROFIL (Außentemp > 20°C)
    SUMMER_SLEEP_TEMP = 27.0  # Einschlaftemperatur
    SUMMER_DEEP_SLEEP_TEMP = 26.0  # Tiefschlaf (Nadir) - kühlster Punkt
    SUMMER_WAKE_TEMP = 28.0  # Aufwachtemperatur

    # WINTER-PROFIL (Außentemp < 15°C)
    WINTER_SLEEP_TEMP = 29.0  # Einschlaftemperatur
    WINTER_DEEP_SLEEP_TEMP = 27.5  # Tiefschlaf (Nadir)
    WINTER_WAKE_TEMP = 30.0  # Aufwachtemperatur

    # ÜBERGANGS-SCHWELLEN
    SUMMER_THRESHOLD = 20.0  # Ab dieser Außentemp = Sommer
    WINTER_THRESHOLD = 15.0  # Unter dieser Außentemp = Winter

    # Fallback wenn kein Außensensor (Ganzjahres-Komfortwert)
    DEFAULT_SLEEP_TEMP = 28.0  # Einschlaftemperatur
    DEFAULT_DEEP_SLEEP_TEMP = 27.0  # Tiefschlaf-Minimum
    DEFAULT_WAKE_TEMP = 29.0  # Aufwachtemperatur

    # Phasen-Anteile (relativ zur Gesamtschlafzeit, summiert zu 1.0)
    # OPTIMIERT: Schnelleres Einschlafen, schnellerer Aufwach-Anstieg
    PHASE_LANDING = 0.08  # 0.00 - 0.08: Einschlafphase (~38 Min bei 8h)
    PHASE_DEEP_SLEEP = 0.55  # 0.08 - 0.63: Tiefschlaf (~264 Min bei 8h)
    PHASE_TRANSITION = 0.22  # 0.63 - 0.85: Übergangsphase (~106 Min bei 8h)
    PHASE_WAKE = 0.15  # 0.85 - 1.00: Aufwachphase (~72 Min bei 8h)

    def __init__(
        self,
        bedtime: time,
        wake_time: time,
        sleep_temp: float = None,
        deep_sleep_temp: float = None,
        wake_temp: float = None,
        chronotype: str = "normal",
        outdoor_temp: float = None,  # NEU: Für saisonale Anpassung
        user_offset: float = 0.0,  # NEU: Feinjustierung vom User
    ):
        """
        Initialisiert die Kurve mit individuellen Parametern.

        Args:
            bedtime: Geplante Schlafenszeit (z.B. time(23, 0))
            wake_time: Geplante Aufwachzeit (z.B. time(7, 0))
            sleep_temp: Temperatur beim Einschlafen (None = saisonal)
            deep_sleep_temp: Minimale Temperatur im Tiefschlaf (None = saisonal)
            wake_temp: Temperatur beim Aufwachen (None = saisonal)
            chronotype: "lerche", "normal" oder "eule"
            outdoor_temp: Aktuelle Außentemperatur für saisonale Anpassung
            user_offset: Persönlicher Temperatur-Offset (+/- °C)
        """
        self.bedtime = bedtime
        self.wake_time = wake_time
        self.chronotype = chronotype
        self.outdoor_temp = outdoor_temp
        self.user_offset = user_offset

        # Berechne saisonale Temperaturen
        base_sleep, base_deep, base_wake = self._calculate_seasonal_temps(outdoor_temp)

        # User-Override oder saisonal + Offset
        self.sleep_temp = (sleep_temp if sleep_temp is not None else base_sleep) + user_offset
        self.deep_sleep_temp = (deep_sleep_temp if deep_sleep_temp is not None else base_deep) + user_offset
        self.wake_temp = (wake_temp if wake_temp is not None else base_wake) + user_offset

        # Nadir-Zeit basierend auf Chronotyp
        self.nadir_offset_hours = CHRONOTYPE_NADIR_OFFSETS.get(chronotype, 0.0)

        # Validierung
        if not (24.0 <= self.deep_sleep_temp <= 32.0):
            _LOGGER.warning(
                f"Tiefschlaf-Temperatur {self.deep_sleep_temp}°C ist ungewöhnlich. "
                "Empfohlen: 26-28°C (Sommer) bzw. 27-29°C (Winter)"
            )

        _LOGGER.debug(
            f"BiorhythmusCurve initialisiert: sleep={self.sleep_temp}°C, "
            f"deep={self.deep_sleep_temp}°C, wake={self.wake_temp}°C, "
            f"outdoor={outdoor_temp}°C, offset={user_offset}°C"
        )

    def _calculate_seasonal_temps(self, outdoor_temp: Optional[float]) -> Tuple[float, float, float]:
        """
        Berechnet saisonale Temperaturen basierend auf Außentemperatur.

        Returns:
            (sleep_temp, deep_sleep_temp, wake_temp)
        """
        if outdoor_temp is None:
            # Kein Außensensor → Ganzjahres-Komfortwert
            return (self.DEFAULT_SLEEP_TEMP, self.DEFAULT_DEEP_SLEEP_TEMP, self.DEFAULT_WAKE_TEMP)

        if outdoor_temp >= self.SUMMER_THRESHOLD:
            # Sommer-Profil
            return (self.SUMMER_SLEEP_TEMP, self.SUMMER_DEEP_SLEEP_TEMP, self.SUMMER_WAKE_TEMP)

        elif outdoor_temp <= self.WINTER_THRESHOLD:
            # Winter-Profil
            return (self.WINTER_SLEEP_TEMP, self.WINTER_DEEP_SLEEP_TEMP, self.WINTER_WAKE_TEMP)

        else:
            # Übergangszeit: Lineare Interpolation
            # outdoor_temp ist zwischen 15°C und 20°C
            factor = (outdoor_temp - self.WINTER_THRESHOLD) / (self.SUMMER_THRESHOLD - self.WINTER_THRESHOLD)
            # factor = 0 → Winter, factor = 1 → Sommer

            sleep = self.WINTER_SLEEP_TEMP + factor * (self.SUMMER_SLEEP_TEMP - self.WINTER_SLEEP_TEMP)
            deep = self.WINTER_DEEP_SLEEP_TEMP + factor * (self.SUMMER_DEEP_SLEEP_TEMP - self.WINTER_DEEP_SLEEP_TEMP)
            wake = self.WINTER_WAKE_TEMP + factor * (self.SUMMER_WAKE_TEMP - self.WINTER_WAKE_TEMP)

            return (round(sleep, 1), round(deep, 1), round(wake, 1))

    def update_outdoor_temp(self, outdoor_temp: float):
        """
        Aktualisiert die Außentemperatur und passt die Kurve an.

        Sollte regelmäßig aufgerufen werden (z.B. alle 30 Min).
        """
        if self.outdoor_temp != outdoor_temp:
            old_deep = self.deep_sleep_temp
            base_sleep, base_deep, base_wake = self._calculate_seasonal_temps(outdoor_temp)

            self.sleep_temp = base_sleep + self.user_offset
            self.deep_sleep_temp = base_deep + self.user_offset
            self.wake_temp = base_wake + self.user_offset
            self.outdoor_temp = outdoor_temp

            if abs(old_deep - self.deep_sleep_temp) > 0.3:
                _LOGGER.info(
                    f"Saisonale Anpassung: Außen {outdoor_temp}°C → "
                    f"Tiefschlaf {self.deep_sleep_temp}°C (war {old_deep}°C)"
                )

    def get_target_temperature(self, current_time: Optional[datetime] = None) -> float:
        """
        Berechnet die Zieltemperatur für den aktuellen Zeitpunkt.

        Args:
            current_time: Zeitpunkt für die Berechnung (default: jetzt)

        Returns:
            Zieltemperatur in °C (float)
        """
        if current_time is None:
            current_time = datetime.now()

        # Normierte Zeit berechnen [0.0 ... 1.0]
        t = self._normalize_time(current_time)

        # Temperatur aus der Kurve berechnen
        temp = self._calculate_temperature(t)

        return round(temp, 2)

    def _normalize_time(self, current_time: datetime) -> float:
        """
        Konvertiert eine Uhrzeit in einen normierten Wert [0.0 ... 1.0].

        0.0 = bedtime
        1.0 = wake_time

        NEU: Berücksichtigt Chronotyp-Offset!
        Der Offset verschiebt den Nadir (tiefsten Punkt der Kurve).

        Beispiel:
        - bedtime = 23:00, wake_time = 07:00 (8h Schlaf)
        - 23:00 → 0.0
        - 03:00 → 0.5
        - 07:00 → 1.0
        """
        # Heutige Zeiten als datetime konstruieren
        today = current_time.date()
        bedtime_dt = datetime.combine(today, self.bedtime)
        wake_dt = datetime.combine(today, self.wake_time)

        # Falls wake_time < bedtime → wake_time ist am nächsten Tag
        if self.wake_time < self.bedtime:
            # Wenn wir VOR bedtime sind, dann ist bedtime gestern
            if current_time.time() < self.bedtime:
                bedtime_dt -= timedelta(days=1)
            else:
                wake_dt += timedelta(days=1)

        # NEU: Chronotyp-Offset anwenden
        # Positiver Offset (Eule) = Nadir später = current_time erscheint früher im Zyklus
        # Negativer Offset (Lerche) = Nadir früher = current_time erscheint später im Zyklus
        # Wir erreichen das, indem wir die aktuelle Zeit verschieben
        offset_td = timedelta(hours=self.nadir_offset_hours)
        adjusted_current_time = current_time - offset_td

        # Gesamtdauer berechnen
        total_duration = (wake_dt - bedtime_dt).total_seconds()

        # Aktuelle Position (mit Chronotyp-Anpassung)
        elapsed = (adjusted_current_time - bedtime_dt).total_seconds()

        # Normieren auf [0, 1]
        # Wenn wir außerhalb des Schlafzyklus sind, clippen wir
        if elapsed < 0:
            return 0.0
        if elapsed > total_duration:
            return 1.0

        return elapsed / total_duration

    def _calculate_temperature(self, t: float) -> float:
        """
        Die eigentliche Kurven-Funktion (stückweise, aber glatt).

        Args:
            t: Normierte Zeit [0.0 ... 1.0]

        Returns:
            Temperatur in °C
        """
        # Phase 1: Landing (Einschlafphase) - Sanftes Absenken
        if t < self.PHASE_LANDING:
            # Fortschritt innerhalb dieser Phase [0...1]
            phase_t = t / self.PHASE_LANDING
            # Cosinus-Interpolation für glatten Übergang
            return self._lerp(self.sleep_temp, self.deep_sleep_temp, self._smooth_cos(phase_t))

        # Phase 2: Tiefschlaf - Konstante Temperatur
        elif t < (self.PHASE_LANDING + self.PHASE_DEEP_SLEEP):
            return self.deep_sleep_temp

        # Phase 3: Transition - Sanfter Anstieg beginnt
        elif t < (self.PHASE_LANDING + self.PHASE_DEEP_SLEEP + self.PHASE_TRANSITION):
            phase_start = self.PHASE_LANDING + self.PHASE_DEEP_SLEEP
            phase_t = (t - phase_start) / self.PHASE_TRANSITION
            return self._lerp(self.deep_sleep_temp, self.wake_temp, self._smooth_cos(phase_t))

        # Phase 4: Wake - Finaler thermischer "Push"
        else:
            phase_start = self.PHASE_LANDING + self.PHASE_DEEP_SLEEP + self.PHASE_TRANSITION
            phase_t = (t - phase_start) / self.PHASE_WAKE

            # Kleine Extra-Absenkung vor dem finalen Anstieg
            # (simuliert die natürliche Körpertemperatur-Dip kurz vor dem Aufwachen)
            temp_pre_wake = self.wake_temp - 0.3

            return self._lerp(temp_pre_wake, self.wake_temp, self._smooth_cos(phase_t))

    @staticmethod
    def _smooth_cos(x: float) -> float:
        """
        Cosinus-basierte Smooth-Step-Funktion.

        Erzeugt einen glatten S-förmigen Übergang von 0 → 1
        ohne Sprünge in der ersten Ableitung (keine Relais-Klicks).

        Args:
            x: Eingabe [0.0 ... 1.0]

        Returns:
            Geglätteter Wert [0.0 ... 1.0]
        """
        return 0.5 * (1.0 - math.cos(math.pi * x))

    @staticmethod
    def _lerp(a: float, b: float, t: float) -> float:
        """
        Lineare Interpolation zwischen zwei Werten.

        Args:
            a: Startwert
            b: Endwert
            t: Fortschritt [0.0 ... 1.0]

        Returns:
            Interpolierter Wert
        """
        return a + (b - a) * t

    def get_curve_info(self, current_time: Optional[datetime] = None) -> dict:
        """
        Gibt Debug-Informationen über die aktuelle Phase zurück.

        Nützlich für UI-Anzeigen und Logging.

        Returns:
            Dict mit Phase, Fortschritt, Temperatur, etc.
        """
        if current_time is None:
            current_time = datetime.now()

        t = self._normalize_time(current_time)
        temp = self._calculate_temperature(t)

        # Aktuelle Phase ermitteln
        if t < self.PHASE_LANDING:
            phase = "Landing"
            phase_progress = t / self.PHASE_LANDING
        elif t < (self.PHASE_LANDING + self.PHASE_DEEP_SLEEP):
            phase = "Tiefschlaf"
            phase_progress = (t - self.PHASE_LANDING) / self.PHASE_DEEP_SLEEP
        elif t < (self.PHASE_LANDING + self.PHASE_DEEP_SLEEP + self.PHASE_TRANSITION):
            phase = "Transition"
            phase_start = self.PHASE_LANDING + self.PHASE_DEEP_SLEEP
            phase_progress = (t - phase_start) / self.PHASE_TRANSITION
        else:
            phase = "Aufwachen"
            phase_start = self.PHASE_LANDING + self.PHASE_DEEP_SLEEP + self.PHASE_TRANSITION
            phase_progress = (t - phase_start) / self.PHASE_WAKE

        return {
            "normalized_time": round(t, 3),
            "target_temperature": round(temp, 2),
            "phase": phase,
            "phase_progress": round(phase_progress * 100, 1),  # Prozent
            "bedtime": self.bedtime.strftime("%H:%M"),
            "wake_time": self.wake_time.strftime("%H:%M"),
        }

    def validate_parameters(self) -> Tuple[bool, str]:
        """
        Prüft, ob die Kurven-Parameter physiologisch sinnvoll sind.

        Returns:
            (is_valid, message)
        """
        issues = []

        # Temperatur-Checks
        if self.deep_sleep_temp > self.sleep_temp:
            issues.append("Tiefschlaf sollte kühler sein als Einschlafen")

        if self.wake_temp < self.deep_sleep_temp:
            issues.append("Aufwachtemperatur sollte höher sein als Tiefschlaf")

        if abs(self.sleep_temp - self.deep_sleep_temp) < 0.5:
            issues.append("Temperatur-Differenz zu gering für effektive Modulation")

        # Zeit-Checks
        bedtime_minutes = self.bedtime.hour * 60 + self.bedtime.minute
        wake_minutes = self.wake_time.hour * 60 + self.wake_time.minute

        # Schlafdauer berechnen (mit Tagesüberlauf)
        if wake_minutes < bedtime_minutes:
            wake_minutes += 24 * 60

        sleep_duration_hours = (wake_minutes - bedtime_minutes) / 60

        if sleep_duration_hours < 4:
            issues.append(f"Schlafdauer zu kurz: {sleep_duration_hours:.1f}h")
        elif sleep_duration_hours > 12:
            issues.append(f"Schlafdauer ungewöhnlich lang: {sleep_duration_hours:.1f}h")

        if issues:
            return False, "; ".join(issues)

        return True, "Alle Parameter OK"


# ============================================================================
# STANDALONE-TEST (funktioniert ohne Home Assistant!)
# ============================================================================

if __name__ == "__main__":
    """
    Test-Modus: Zeigt die Kurve für einen kompletten Tag.

    Aufruf: python3 biorhythmus_curve.py
    """
    print("=" * 60)
    print("Biorhythmus-Kurve Test")
    print("=" * 60)

    # Test-Kurve erstellen
    curve = BiorhythmusCurve(
        bedtime=time(23, 0), wake_time=time(7, 0), sleep_temp=28.5, deep_sleep_temp=27.2, wake_temp=28.5
    )

    # Validierung
    is_valid, msg = curve.validate_parameters()
    print(f"\nValidierung: {msg}\n")

    # Kurve für 24 Stunden ausgeben (alle 30 Min)
    print("Zeit  | Temp (°C) | Phase        | Fortschritt")
    print("-" * 60)

    base_time = datetime.now().replace(hour=22, minute=0, second=0, microsecond=0)

    for i in range(48):  # 24h * 2 (alle 30 Min)
        test_time = base_time + timedelta(minutes=30 * i)
        info = curve.get_curve_info(test_time)

        print(
            f"{test_time.strftime('%H:%M')} | "
            f"{info['target_temperature']:5.2f}°C  | "
            f"{info['phase']:<12} | "
            f"{info['phase_progress']:5.1f}%"
        )

    print("\n" + "=" * 60)
    print("Test abgeschlossen!")
