"""
Temperature-Calculator für das Rejuvenation Bed (v2.0).

KOMPLETT ÜBERARBEITET!

Neu:
- Nutzt BiorhythmusCurve für deterministische Temperaturberechnung
- Integriert WakeTimeResolver für dynamische Aufwachzeit
- Unterstützt SleepStageResolver für Wearable-Daten
- Wendet EnergyStateResolver für Solar-Boost an
- BETT-TYP-SPEZIFISCH: Wasserbett vs. Heizmatte

Die Zieltemperatur wird berechnet als:
  final_temp = curve_temp + energy_offset + sleep_stage_offset + manual_override
"""

import logging
from datetime import datetime, time, timedelta
from typing import Optional
from homeassistant.core import HomeAssistant

from .biorhythmus_curve import BiorhythmusCurve
from .wake_time_resolver import WakeTimeResolver
from .sleep_stage_resolver import SleepStageResolver
from .energy_state_resolver import EnergyStateResolver
from .const import ABSOLUTE_MAX_TEMP, WATERBED_CONFIG

_LOGGER = logging.getLogger(__name__)


class TemperatureCalculator:
    """
    Berechnet die ideale Zieltemperatur für jede Zone.
    
    Prioritäten (höchste zuerst):
    1. Sicherheits-Vetos (im Coordinator geprüft)
    2. Manuelle Vorgabe (Climate Entity Override)
    3. Biorhythmus-Kurve + Modifikatoren
    
    BETT-TYP-UNTERSCHIEDE:
    - Wasserbett: Lange Vorheizzeit (3h), min 24°C
    - Heizmatte: Kurze Vorheizzeit (15min), kann AUS sein
    """

    def __init__(self, hass: HomeAssistant, config_entry, bed_config: dict = None):
        """
        Initialisiert den Calculator.
        
        Args:
            hass: Home Assistant Instanz
            config_entry: ConfigEntry mit allen Einstellungen
            bed_config: Bett-Typ-spezifische Konfiguration (optional)
        """
        self.hass = hass
        self.config_entry = config_entry
        
        # Bett-Typ Konfiguration
        self.bed_config = bed_config or WATERBED_CONFIG.copy()
        
        # Bett-Typ-spezifische Parameter
        self.min_temp = self.bed_config.get("min_temp", 24.0)
        self.preheat_hours = self.bed_config.get("preheat_hours", 3.0)
        self.preheat_minutes = self.bed_config.get("preheat_minutes", 15)  # Für Heizmatte
        self.thermal_battery_enabled = self.bed_config.get("thermal_battery", True)
        self.eco_can_turn_off = self.bed_config.get("eco_can_turn_off", False)
        
        _LOGGER.debug(
            f"TemperatureCalculator initialisiert: "
            f"Min-Temp={self.min_temp}°C, "
            f"Vorheizzeit={self.preheat_hours}h/{self.preheat_minutes}min, "
            f"Batterie={self.thermal_battery_enabled}"
        )
        
        # Sub-Resolver initialisieren
        self.energy_resolver = EnergyStateResolver(hass, config_entry)
        
        # Pro-Zone Resolver (werden bei async_calculate_target initialisiert)
        self._curves = {}
        self._wake_resolvers = {}
        self._sleep_stage_resolvers = {}
        
        # Historische Daten für Trend-Analyse
        self._temp_history = {}
    
    async def async_calculate_target(
        self,
        zone_index: int,
        energy_state: dict,
        veto_state: dict,
        coordinator=None,  # Coordinator für manuelle Overrides
        is_present: bool = False,
        has_presence_sensor: bool = False,
        actual_bedtime: Optional[datetime] = None,  # NEU: Echte Einschlafzeit
        post_alarm: bool = False,                    # NEU: Nach Wecker-Zeit
    ) -> float:
        """
        Zentrale Funktion: Berechnet die Zieltemperatur für eine Zone.
        
        Präsenz-basierte Kurven-Steuerung:
        - actual_bedtime: Wann Person WIRKLICH ins Bett gegangen ist
          → Kurve startet ab diesem Zeitpunkt (nicht ab konfigurierter warm_from)
        - Toilettengang (<15 Min): Kurve läuft weiter, kein Abbruch
        - post_alarm: Wecker-Zeit vorbei, Person noch im Bett
          → Warmhalten auf Aufwach-Temperatur (nicht auskühlen lassen)
        
        Args:
            zone_index: Index der Zone (0 oder 1)
            energy_state: Dict vom EnergyCalculator
            veto_state: Dict mit Veto-Checks (z.B. Sommer-Modus)
            coordinator: Optional - der Coordinator
            is_present: Ob Person im Bett erkannt wurde
            has_presence_sensor: Ob ein Präsenz-Sensor konfiguriert ist
            actual_bedtime: Echte Einschlafzeit (None = nicht im Bett)
            post_alarm: Wecker ist durch, Person liegt noch drin
        
        Returns:
            Zieltemperatur in °C
        """
        # Schritt 0: Prüfe auf manuelle Vorgabe (mit sicherer Coordinator-Referenz)
        manual_temp = None
        boost_active = False
        sick_mode_active = False
        sick_temp = None
        
        if coordinator:
            manual_temp = getattr(coordinator, "manual_target_temp", {}).get(zone_index)
            boost_active = getattr(coordinator, "manual_boost", {}).get(zone_index, False)
            
            # Krank-Modus prüfen
            sick_until = getattr(coordinator, "sick_mode_until", {}).get(zone_index)
            if sick_until and datetime.now() < sick_until:
                sick_mode_active = True
                sick_temp = getattr(coordinator, "sick_mode_temp", {}).get(zone_index, 30.0)
        
        if manual_temp is not None:
            _LOGGER.debug(f"Zone {zone_index}: Manuelle Vorgabe {manual_temp}°C")
            return float(min(manual_temp, ABSOLUTE_MAX_TEMP))
        
        # Schritt 1: Prüfe auf Krank-Modus
        if sick_mode_active and sick_temp:
            _LOGGER.debug(f"Zone {zone_index}: Krank-Modus aktiv ({sick_temp}°C)")
            return float(min(sick_temp, ABSOLUTE_MAX_TEMP))
        
        # Schritt 2: Prüfe auf Boost-Switch
        if boost_active:
            zones_config = self.config_entry.data.get("zones", [])
            boost_target = zones_config[zone_index].get("boost_target_temp", 34)
            _LOGGER.debug(f"Zone {zone_index}: Boost-Modus aktiv ({boost_target}°C)")
            return float(min(boost_target, ABSOLUTE_MAX_TEMP))
        
        # Schritt 3: Veto-Checks (z.B. Sommer-Abschaltung)
        if veto_state.get("is_summer"):
            summer_temp = 25.0  # Minimale Temperatur im Sommer
            _LOGGER.debug(f"Zone {zone_index}: Sommer-Veto aktiv ({summer_temp}°C)")
            return summer_temp
        
        # Schritt 4: Initialisiere Resolver für diese Zone (falls noch nicht geschehen)
        await self._ensure_resolvers_initialized(zone_index)
        
        # Schritt 5: Präsenz-basierte Logik
        curve = self._curves.get(zone_index)
        if not curve:
            _LOGGER.warning(f"Zone {zone_index}: Keine Kurve initialisiert! Fallback 28°C")
            return 28.0
        
        # NEU: Entscheide ob Biorhythmus-Kurve aktiv sein soll
        use_biorhythmus = False
        standby_temp = 26.0  # Basis-Temperatur wenn Bett leer/wartend
        
        global_conf = self.config_entry.data.get("global", {})
        options = self.config_entry.options
        
        # Warmhalte-Zeitfenster (für Vorheizen und Fallback)
        warm_from_str = options.get("warm_from", global_conf.get("warm_from", "22:00"))
        warm_until_str = options.get("warm_until", global_conf.get("warm_until", "07:00"))
        warm_from = self._parse_time(warm_from_str)
        warm_until = self._parse_time(warm_until_str)
        
        # NEU: Lernbasiertes Vorheizen (BedIntelligence Vorhersage)
        smart_preheat_from = warm_from  # Default: konfigurierte Zeit
        if coordinator and hasattr(coordinator, 'bed_intelligence'):
            predicted_start = coordinator.bed_intelligence.get_predicted_preheat_start(
                zone_index,
                preheat_hours=self.preheat_hours,
                configured_warm_from=warm_from_str,
            )
            if predicted_start:
                smart_preheat_from = self._parse_time(predicted_start)
                _LOGGER.debug(
                    f"Zone {zone_index}: Lernbasiertes Vorheizen ab {predicted_start} "
                    f"(statt konfiguriert {warm_from_str})"
                )
        
        now = datetime.now()
        current_time = now.time()
        
        in_warm_window = self._is_in_time_range(current_time, warm_from, warm_until)
        
        if has_presence_sensor:
            # ═══════════════════════════════════════════════════════════
            # MIT Präsenz-Sensor: Individueller Kurvenstart
            # ═══════════════════════════════════════════════════════════
            
            if post_alarm and is_present:
                # NACH WECKER: Person liegt noch im Bett
                # → Warmhalten auf Aufwach-Temperatur (nicht auskühlen!)
                wake_temp = curve.wake_temp if curve else 29.0
                _LOGGER.debug(
                    f"Zone {zone_index}: Post-Alarm Warmhalten → {wake_temp}°C"
                )
                return wake_temp
            
            if actual_bedtime is not None:
                # Person IM BETT (oder kurzer Toilettengang)
                # → Kurve mit ECHTEM Einschlafzeitpunkt starten!
                use_biorhythmus = True
                
                # Kurve dynamisch an echte Einschlafzeit anpassen
                if curve:
                    curve.bedtime = actual_bedtime.time()
                
                _LOGGER.debug(
                    f"Zone {zone_index}: Biorhythmus aktiv "
                    f"(Einschlafzeit: {actual_bedtime.strftime('%H:%M')})"
                )
            
            elif in_warm_window:
                # Im Zeitfenster aber noch nicht im Bett: Vorheizen
                preheat_temp = curve.sleep_temp if curve else 28.0
                _LOGGER.debug(
                    f"Zone {zone_index}: Warmhalte-Fenster aktiv, wartet auf Präsenz → {preheat_temp}°C"
                )
                return preheat_temp
            
            else:
                # Außerhalb Zeitfenster: Vorheizen ODER Standby
                # NEU: smart_preheat_from = gelernte Zeit oder konfigurierte
                minutes_to_warm_start = self._minutes_until_time(current_time, smart_preheat_from)
                preheat_minutes = int(self.preheat_hours * 60) if self.preheat_hours else self.preheat_minutes
                
                if 0 < minutes_to_warm_start <= preheat_minutes:
                    # Vorheizen! (Wasserbett braucht ~3h)
                    preheat_temp = curve.sleep_temp if curve else 28.0
                    _LOGGER.debug(
                        f"Zone {zone_index}: Vorheizen ({minutes_to_warm_start} Min bis Warmhalte-Start) → {preheat_temp}°C"
                    )
                    return preheat_temp
                else:
                    # Tagsüber: Standby
                    _LOGGER.debug(f"Zone {zone_index}: Standby → {standby_temp}°C")
                    return max(standby_temp, self.min_temp)
        
        else:
            # ═══════════════════════════════════════════════════════════
            # OHNE Präsenz-Sensor: Zeitbasiert (Fallback)
            # ═══════════════════════════════════════════════════════════
            if in_warm_window:
                use_biorhythmus = True
                _LOGGER.debug(f"Zone {zone_index}: Im Warmhalte-Fenster → Biorhythmus aktiv")
            else:
                # NEU: smart_preheat_from statt warm_from
                minutes_to_warm_start = self._minutes_until_time(current_time, smart_preheat_from)
                preheat_minutes = int(self.preheat_hours * 60) if self.preheat_hours else self.preheat_minutes
                
                if 0 < minutes_to_warm_start <= preheat_minutes:
                    preheat_temp = curve.sleep_temp if curve else 28.0
                    _LOGGER.debug(
                        f"Zone {zone_index}: Vorheizen ({minutes_to_warm_start} Min) → {preheat_temp}°C"
                    )
                    return preheat_temp
                else:
                    _LOGGER.debug(f"Zone {zone_index}: Tagsüber → Standby {standby_temp}°C")
                    return max(standby_temp, self.min_temp)
        
        # Schritt 6: Hole Basis-Temperatur aus der Biorhythmus-Kurve
        if use_biorhythmus:
            curve_temp = curve.get_target_temperature()
        else:
            curve_temp = standby_temp
        
        # Schritt 7: Energie-Offset anwenden
        energy_offset = energy_state.get("temperature_offset", 0.0)
        
        # Schritt 8: Sleep-Stage-Offset (falls Wearable aktiv)
        sleep_stage_resolver = self._sleep_stage_resolvers.get(zone_index)
        sleep_stage_offset = 0.0
        
        if sleep_stage_resolver and sleep_stage_resolver.should_override_curve():
            sleep_stage_offset = sleep_stage_resolver.get_temperature_modifier()
            _LOGGER.debug(
                f"Zone {zone_index}: Wearable-Override aktiv "
                f"(Offset: {sleep_stage_offset:+.1f}°C)"
            )
        
        # Schritt 9: Finale Temperatur berechnen
        final_temp = curve_temp + energy_offset + sleep_stage_offset
        
        # Schritt 10: Anti-Kalt-Garantie + Hard-Limit
        final_temp = max(final_temp, EnergyStateResolver.ABSOLUTE_MIN_TEMP)
        final_temp = min(final_temp, ABSOLUTE_MAX_TEMP)
        
        _LOGGER.debug(
            f"Zone {zone_index}: Curve={curve_temp:.1f}°C, "
            f"Energy={energy_offset:+.1f}°C, "
            f"SleepStage={sleep_stage_offset:+.1f}°C → "
            f"Final={final_temp:.1f}°C"
        )
        
        return round(final_temp, 2)
    
    async def _ensure_resolvers_initialized(self, zone_index: int):
        """
        Stellt sicher, dass alle Resolver für diese Zone existieren.
        
        Wird lazy initialisiert (nur beim ersten Aufruf).
        """
        if zone_index in self._curves:
            return  # Bereits initialisiert
        
        zones_config = self.config_entry.data.get("zones", [])
        
        if zone_index >= len(zones_config):
            _LOGGER.error(f"Zone {zone_index} existiert nicht in der Config!")
            return
        
        zone_conf = zones_config[zone_index]
        
        # Hole globale Config
        global_conf = self.config_entry.data.get("global", {})
        
        # Options überschreiben data (falls vorhanden)
        options = self.config_entry.options
        # Options-Flow speichert Zonen-Settings als flat keys: "zone_0_wake_time" etc.
        prefix = f"zone_{zone_index}_"
        zone_options = {
            k[len(prefix):]: v for k, v in options.items()
            if k.startswith(prefix)
        }
        
        # NEU: Warmhalte-Zeitfenster verwenden
        # Options überschreiben Config! (User hat in UI geändert)
        warm_from_str = options.get("warm_from", global_conf.get("warm_from", "22:00"))
        warm_until_str = options.get("warm_until", global_conf.get("warm_until", "07:00"))
        bedtime = self._parse_time(warm_from_str)  # "bedtime" ist jetzt warm_from
        
        # Wake-Time = warm_until (eine Stelle, kein Konfusions-Potenzial)
        wake_time_fixed = self._parse_time(warm_until_str)
        
        # Wake-Mode: Hybrid als Default (Wecker-Entity nutzen wenn vorhanden, sonst warm_until)
        wake_mode = zone_options.get("wake_mode", zone_conf.get("wake_mode", "hybrid"))
        # Alarm-Entity: Zuerst aus Zone, dann aus global
        alarm_entity = zone_options.get("alarm_entity") or zone_conf.get("alarm_entity") or global_conf.get("alarm_entity")
        
        # Weekend-Offset
        weekend_offset = zone_options.get("weekend_offset_hours", zone_conf.get("weekend_offset_hours", 2.0))
        
        wake_resolver = WakeTimeResolver(
            self.hass,
            mode=wake_mode,
            fixed_time=wake_time_fixed,
            alarm_entity=alarm_entity,
            weekend_offset_hours=weekend_offset
        )
        
        # Effektive Wake-Time ermitteln
        wake_time, wake_source = wake_resolver.resolve()
        _LOGGER.info(
            f"Zone {zone_index}: Aufwachzeit = {wake_time.strftime('%H:%M')} "
            f"(Quelle: {wake_source})"
        )
        
        # Temperatur-Präferenzen (None = saisonal automatisch)
        sleep_temp = zone_options.get("sleep_temp", zone_conf.get("sleep_temp"))
        deep_sleep_temp = zone_options.get("deep_sleep_temp", zone_conf.get("deep_sleep_temp"))
        wake_temp = zone_options.get("wake_temp", zone_conf.get("wake_temp"))
        
        # Global-Config und Options laden (WICHTIG: VOR der Verwendung!)
        global_conf = self.config_entry.data.get("global", {})
        global_options = self.config_entry.options
        
        # User-Offset für Feinjustierung
        user_temp_offset = float(global_options.get("temperature_offset", 0.0))
        
        # Chronotyp
        chronotype = global_options.get("chronotype") or global_conf.get("chronotype", "normal")
        
        # ═══════════════════════════════════════════════════════════════════════
        # Außentemperatur für saisonale Anpassung
        # Unterstützt: Temperatur-Sensor ODER Wetter-Entity
        # ═══════════════════════════════════════════════════════════════════════
        outdoor_temp = None
        outdoor_source = global_conf.get("outdoor_sensor")
        
        if outdoor_source:
            state = self.hass.states.get(outdoor_source)
            if state and state.state not in ["unknown", "unavailable"]:
                # Prüfe ob es ein Wetter-Entity ist (hat temperature Attribut)
                if state.domain == "weather":
                    # Wetter-Entity: Temperatur aus Attributen holen
                    temp_attr = state.attributes.get("temperature")
                    if temp_attr is not None:
                        try:
                            outdoor_temp = float(temp_attr)
                            _LOGGER.debug(f"Außentemperatur von Wetter-Entity: {outdoor_temp}°C")
                        except (ValueError, TypeError):
                            pass
                else:
                    # Normaler Sensor: State ist die Temperatur
                    try:
                        outdoor_temp = float(state.state)
                    except ValueError:
                        pass
        
        # Biorhythmus-Kurve initialisieren MIT Saisonaler Anpassung
        curve = BiorhythmusCurve(
            bedtime=bedtime,
            wake_time=wake_time,
            sleep_temp=float(sleep_temp) if sleep_temp else None,  # None = saisonal
            deep_sleep_temp=float(deep_sleep_temp) if deep_sleep_temp else None,
            wake_temp=float(wake_temp) if wake_temp else None,
            chronotype=chronotype,
            outdoor_temp=outdoor_temp,      # Saisonale Anpassung
            user_offset=user_temp_offset,   # User Feinjustierung
        )
        
        _LOGGER.info(
            f"Zone {zone_index}: Kurve initialisiert - "
            f"Sleep={curve.sleep_temp}°C, Deep={curve.deep_sleep_temp}°C, Wake={curve.wake_temp}°C "
            f"(Außen: {outdoor_temp}°C, Offset: {user_temp_offset:+.1f}°C)"
        )
        
        # Validierung
        is_valid, msg = curve.validate_parameters()
        if not is_valid:
            _LOGGER.warning(f"Zone {zone_index}: Kurven-Parameter fragwürdig: {msg}")
        
        # Sleep-Stage-Resolver (optional)
        sleep_stage_entity = zone_options.get("sleep_stage_entity", zone_conf.get("sleep_stage_entity"))
        
        sleep_stage_resolver = SleepStageResolver(
            self.hass,
            sleep_stage_entity=sleep_stage_entity,
            enabled=sleep_stage_entity is not None
        )
        
        # Speichern
        self._curves[zone_index] = curve
        self._wake_resolvers[zone_index] = wake_resolver
        self._sleep_stage_resolvers[zone_index] = sleep_stage_resolver
        
        _LOGGER.info(f"Zone {zone_index}: Resolver erfolgreich initialisiert")
    
    @staticmethod
    def _parse_time(time_str: str) -> time:
        """
        Parst einen Zeit-String (HH:MM) zu einem time-Objekt.
        
        Args:
            time_str: Zeit als String (z.B. "23:00")
        
        Returns:
            time-Objekt
        """
        try:
            parts = time_str.split(":")
            h = int(parts[0])
            m = int(parts[1]) if len(parts) > 1 else 0
            # Sekunden ignorieren (HA TimeSelector gibt HH:MM:SS)
            return time(h, m)
        except Exception as e:
            _LOGGER.error(f"Konnte Zeit '{time_str}' nicht parsen: {e}")
            return time(7, 0)  # Fallback
    
    @staticmethod
    def _is_in_time_range(current: time, start: time, end: time) -> bool:
        """
        Prüft ob current zwischen start und end liegt.
        
        Handhabt auch Übernachtungen (z.B. 22:00 bis 07:00).
        
        Args:
            current: Aktuelle Zeit
            start: Startzeit des Fensters
            end: Endzeit des Fensters
        
        Returns:
            True wenn current im Zeitfenster liegt
        """
        if start <= end:
            # Normaler Fall: z.B. 08:00 bis 18:00
            return start <= current <= end
        else:
            # Übernachtung: z.B. 22:00 bis 07:00
            # Wir sind im Fenster wenn: current >= start ODER current <= end
            return current >= start or current <= end
    
    @staticmethod
    def _minutes_until_time(current: time, target: time) -> Optional[int]:
        """
        Berechnet die Minuten von current bis target.
        
        Positive Werte = target ist in der Zukunft
        Negative Werte = target ist in der Vergangenheit
        
        Args:
            current: Aktuelle Zeit
            target: Zielzeit
        
        Returns:
            Minuten bis zur Zielzeit (kann negativ sein)
        """
        current_minutes = current.hour * 60 + current.minute
        target_minutes = target.hour * 60 + target.minute
        
        diff = target_minutes - current_minutes
        
        # Wenn Differenz sehr groß negativ ist, sind wir "am nächsten Tag"
        # Z.B. current=02:00, target=23:00 → -180 bedeutet wir sind 3h nach Schlafzeit
        
        return diff
    
    def update_trend_data(self, zone_index: int, current_temp: float):
        """
        Füttert die Trend-Analyse mit neuen Werten.
        
        Wird vom Coordinator bei jedem Update aufgerufen.
        
        Args:
            zone_index: Index der Zone
            current_temp: Aktuelle Temperatur in °C
        """
        if zone_index not in self._temp_history:
            self._temp_history[zone_index] = {
                "last_val": current_temp,
                "trend": 0.0
            }
            return
        
        # Trend berechnen (Differenz zur letzten Messung)
        diff = current_temp - self._temp_history[zone_index]["last_val"]
        
        # Glättung mit exponentieller Moving Average
        self._temp_history[zone_index]["trend"] = (
            self._temp_history[zone_index]["trend"] * 0.7 + diff * 0.3
        )
        
        self._temp_history[zone_index]["last_val"] = current_temp
    
    def _get_trend(self, zone_index: int) -> float:
        """
        Gibt den aktuellen Temperatur-Trend zurück.
        
        Returns:
            Trend in °C pro Update-Intervall
        """
        return self._temp_history.get(zone_index, {}).get("trend", 0.0)
    
    async def async_get_decision_reason(
        self,
        zone_index: int,
        target_temp: float,
        current_temp: float,
        should_heat: bool,
        energy_state: dict,
        coordinator=None  # NEU: Coordinator als Parameter
    ) -> str:
        """
        Generiert eine menschenlesbare Erklärung für das UI.
        
        Returns:
            String mit Erklärung (z.B. "☀️ Solar-Boost aktiv")
        """
        # Manuelle Vorgabe?
        if coordinator and getattr(coordinator, "manual_target_temp", {}).get(zone_index):
            return f"🎮 Manuelle Steuerung: {target_temp}°C"
        
        # Boost-Switch?
        if coordinator and getattr(coordinator, "manual_boost", {}).get(zone_index, False):
            return f"🔥 Schnellheizen aktiv: {target_temp}°C"
        
        # Energie-Modus
        energy_mode = energy_state.get("mode")
        if energy_mode and energy_mode.value == "solar_boost":
            return energy_state.get("reason", "☀️ Solar-Boost")
        
        # Wearable-Override?
        sleep_stage_resolver = self._sleep_stage_resolvers.get(zone_index)
        if sleep_stage_resolver and sleep_stage_resolver.should_override_curve():
            stage_info = sleep_stage_resolver.get_diagnostics()
            return f"⌚ Wearable: {stage_info['current_stage']}"
        
        # Biorhythmus-Phase
        curve = self._curves.get(zone_index)
        if curve:
            info = curve.get_curve_info()
            return f"🌙 {info['phase']} ({info['phase_progress']:.0f}%)"
        
        # Fallback
        return "✅ Biorhythmus aktiv"
    
    def get_diagnostics(self, zone_index: int) -> dict:
        """
        Gibt umfassende Debug-Informationen zurück.
        
        Returns:
            Dict mit allen relevanten Status-Infos
        """
        diag = {"zone_index": zone_index}
        
        # Kurven-Info
        curve = self._curves.get(zone_index)
        if curve:
            diag["curve"] = curve.get_curve_info()
        
        # Wake-Time-Info
        wake_resolver = self._wake_resolvers.get(zone_index)
        if wake_resolver:
            diag["wake_time"] = wake_resolver.get_diagnostics()
        
        # Sleep-Stage-Info
        sleep_resolver = self._sleep_stage_resolvers.get(zone_index)
        if sleep_resolver:
            diag["sleep_stage"] = sleep_resolver.get_diagnostics()
        
        # Trend-Info
        diag["temperature_trend"] = self._get_trend(zone_index)
        
        return diag
