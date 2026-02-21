"""
Rejuvenation Bed Coordinator - FIXED v0.1.1

Zentrale Steuerung mit allen Bug-Fixes:
- Hardware-Sync beim Start
- Mode-Auswertung (Boost, Krank, Eco, Urlaub)
- Fail-Safe bei Sensor-Ausfall
- Robustes Sensor-Lesen
"""

import logging
from collections import deque
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.components.persistent_notification import async_create as notify_create

from .const import DOMAIN, UPDATE_INTERVAL, get_bed_config, BED_TYPE_WATERBED, BED_TYPE_HEATING_PAD
from .safety_manager import SafetyManager
from .temperature_calculator import TemperatureCalculator
from .energy_calculator import EnergyCalculator
from .anti_short_cycle_manager import AntiShortCycleManager
from .diagnostics_manager import DiagnosticsManager
from .presence_detector import PresenceDetector
from .sleep_score_calculator import SleepScoreCalculator
from .ramp_controller import RampController
from .bed_intelligence import BedIntelligence

_LOGGER = logging.getLogger(__name__)


class RejuvenationBedCoordinator(DataUpdateCoordinator):
    """Zentrale Steuerung: Koordiniert Sicherheit, Energie und Hardware-Schaltung."""

    def __init__(self, hass: HomeAssistant, config_entry):
        """Initialisiere den Coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="Rejuvenation Bed",
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )
        
        self.config_entry = config_entry
        self.hass = hass
        
        # ═══════════════════════════════════════════════════════════════════════
        # BETT-TYP KONFIGURATION
        # ═══════════════════════════════════════════════════════════════════════
        global_conf = config_entry.data.get("global", {})
        self.bed_type = global_conf.get("bed_type", BED_TYPE_WATERBED)
        self.bed_config = get_bed_config(self.bed_type)
        
        _LOGGER.info(
            f"Rejuvenation Bed initialisiert: Typ={self.bed_type}, "
            f"Min={self.bed_config['min_temp']}°C, Max={self.bed_config['max_temp']}°C, "
            f"Rampen={'aktiv' if self.bed_config['ramp_enabled'] else 'deaktiviert'}"
        )
        
        # Sub-Manager initialisieren (MIT Bett-Typ!)
        self.safety_manager = SafetyManager(hass, config_entry, self.bed_config)
        self.temperature_calculator = TemperatureCalculator(hass, config_entry, self.bed_config)
        self.energy_calculator = EnergyCalculator(hass, config_entry)
        self.anti_short_cycle_manager = AntiShortCycleManager()
        self.diagnostics_manager = DiagnosticsManager(hass, config_entry)
        self.presence_detector = PresenceDetector()
        self.sleep_score_calculator = SleepScoreCalculator(hass, config_entry)
        self.bed_intelligence = BedIntelligence(hass, config_entry)
        
        # Ramp Controller (nur bei Wasserbett aktiv!)
        if self.bed_config["ramp_enabled"]:
            self.ramp_controller = RampController(
                max_change_per_hour=self.bed_config["max_change_per_hour"],
                heating_rate=self.bed_config["heating_rate"],
            )
        else:
            self.ramp_controller = None
        
        # CO2 Sensor (optional)
        self.co2_sensor = config_entry.options.get("co2_sensor", config_entry.data.get("global", {}).get("co2_sensor"))
        
        # Speicher für Zustände
        self._decision_log = deque(maxlen=100)
        self._heater_states = {}
        
        # ═══════════════════════════════════════════════════════════════════════
        # FIX: Hardware-Sync Flag
        # ═══════════════════════════════════════════════════════════════════════
        self._hardware_synced = False
        self._last_successful_update = None
        self._consecutive_failures = 0
        
        # ═══════════════════════════════════════════════════════════════════════
        # FIX: Startup-Grace-Period (ESP-Sensoren brauchen Zeit nach HA-Restart)
        # ═══════════════════════════════════════════════════════════════════════
        self._startup_time = datetime.now()
        self._startup_grace_seconds = 180  # 3 Minuten Geduld für ESP-Boot
        self._sensor_failure_notified = {}  # Nur einmal pro Zone benachrichtigen
        
        # ═══════════════════════════════════════════════════════════════════════
        # FIX: Alle Mode-Attribute initialisieren (für switch.py!)
        # ═══════════════════════════════════════════════════════════════════════
        self.manual_boost = {}
        self.boost_until = {}  # NEU: Ablaufzeit für Boost
        self.manual_hvac_mode = {}
        self.manual_preset = {}
        self.manual_target_temp = {}
        self.sick_mode_until = {}
        self.sick_mode_temp = {}
        self.thermal_battery_enabled = True  # NEU: Solar-Batterie Default AN
        self.eco_mode_enabled = False  # Tarifmodus Default AUS
        self.vacation_mode_enabled = False  # NEU: Urlaub-Modus Default AUS
        self.vacation_until = None  # NEU: Urlaub-Ende
        
        # Präsenz-Tracking für Biorhythmus-Aktivierung
        self._presence_detected_at = {}
        self._curve_active = {}
        self._night_tracking_active = {}
        self._last_presence_state = {}
        
        # Tracker für Performance-Überwachung
        self._heating_start_time = {}
        self._heating_start_temp = {}
        
        # Schwitz-Erkennung & Leckage-Tracking
        self._moisture_start_time = {}

    @property
    def is_waterbed(self) -> bool:
        """Gibt True zurück wenn es ein Wasserbett ist."""
        return self.bed_type == BED_TYPE_WATERBED
    
    @property
    def is_heating_pad(self) -> bool:
        """Gibt True zurück wenn es eine Heizmatte ist."""
        return self.bed_type == BED_TYPE_HEATING_PAD

    # ═══════════════════════════════════════════════════════════════════════════
    # FIX: Robustes Sensor-Lesen
    # ═══════════════════════════════════════════════════════════════════════════
    def _safe_get_sensor_value(
        self, 
        entity_id: str, 
        default: float = None,
        value_type: str = "float"
    ):
        """
        Liest einen Sensor SICHER aus - crasht NICHT bei Fehlern!
        
        Args:
            entity_id: Entity-ID des Sensors
            default: Fallback-Wert bei Fehler
            value_type: "float", "bool", oder "str"
        
        Returns:
            Sensor-Wert oder default
        """
        if not entity_id:
            return default
        
        try:
            state = self.hass.states.get(entity_id)
            
            if state is None:
                _LOGGER.warning(f"Sensor {entity_id} nicht gefunden!")
                return default
            
            if state.state in ["unknown", "unavailable", "none", None]:
                _LOGGER.debug(f"Sensor {entity_id} nicht verfügbar: {state.state}")
                return default
            
            if value_type == "float":
                return float(state.state)
            elif value_type == "bool":
                return state.state.lower() in ["on", "true", "1", "yes"]
            else:
                return state.state
                
        except (ValueError, TypeError, AttributeError) as e:
            _LOGGER.warning(f"Fehler beim Lesen von {entity_id}: {e}")
            return default

    # ═══════════════════════════════════════════════════════════════════════════
    # FIX: Mode-Auswertung
    # ═══════════════════════════════════════════════════════════════════════════
    def _apply_mode_adjustments(self, zone_index: int, base_temp: float) -> tuple:
        """
        Wendet aktive Modi auf die Temperatur an.
        
        Priorität:
        1. Urlaub-Modus (niedrigste Temperatur)
        2. Krank-Modus (konstant hoch)
        3. Boost-Modus (erhöht)
        4. Tarifmodus (strompreis-abhängig)
        
        Returns:
            (adjusted_temp, active_mode, reason)
        """
        # ═══════════════════════════════════════════════════════════════════
        # PRIORITÄT 1: Urlaub-Modus
        # ═══════════════════════════════════════════════════════════════════
        if self.vacation_mode_enabled:
            vacation_until = self.vacation_until
            
            # Prüfe ob Urlaub abgelaufen
            if vacation_until and datetime.now() > vacation_until:
                self.vacation_mode_enabled = False
                _LOGGER.info("Urlaub-Modus automatisch beendet.")
            else:
                # Wasserbett: 24°C, Heizmatte: kann aus
                if self.bed_type == BED_TYPE_WATERBED:
                    return 24.0, "vacation", "✈️ Urlaub-Modus (24°C Frostschutz)"
                else:
                    return 0.0, "vacation", "✈️ Urlaub-Modus (Heizmatte AUS)"
        
        # ═══════════════════════════════════════════════════════════════════
        # PRIORITÄT 2: Krank-Modus
        # ═══════════════════════════════════════════════════════════════════
        sick_until = self.sick_mode_until.get(zone_index)
        if sick_until and datetime.now() < sick_until:
            sick_temp = self.sick_mode_temp.get(zone_index, 30.0)
            return sick_temp, "sick", f"🤒 Krank-Modus ({sick_temp}°C konstant)"
        
        # ═══════════════════════════════════════════════════════════════════
        # PRIORITÄT 3: Boost-Modus
        # ═══════════════════════════════════════════════════════════════════
        boost_active = self.manual_boost.get(zone_index, False)
        boost_until = self.boost_until.get(zone_index)
        
        if boost_active:
            # Prüfe ob Boost abgelaufen
            if boost_until and datetime.now() > boost_until:
                self.manual_boost[zone_index] = False
                _LOGGER.info(f"Boost für Zone {zone_index} automatisch beendet.")
            else:
                # Boost-Temperatur aus Config
                zone_config = self.config_entry.data["zones"][zone_index]
                boost_temp = zone_config.get("boost_target_temp", 34.0)
                return boost_temp, "boost", f"🔥 Schnellheizen ({boost_temp}°C)"
        
        # ═══════════════════════════════════════════════════════════════════
        # PRIORITÄT 4: Tarifmodus (nur wenn price_sensor konfiguriert)
        # ═══════════════════════════════════════════════════════════════════
        if self.eco_mode_enabled:
            # Wasserbett: Max -2°C, nie unter 26°C
            if self.bed_type == BED_TYPE_WATERBED:
                eco_temp = max(26.0, base_temp - 2.0)
                return eco_temp, "eco", f"💰 Tarifmodus ({eco_temp}°C)"
            else:
                # Heizmatte kann mehr absenken
                eco_temp = max(0.0, base_temp - 5.0)
                return eco_temp, "eco", f"💰 Tarifmodus ({eco_temp}°C)"
        
        # ═══════════════════════════════════════════════════════════════════
        # KEIN SPEZIAL-MODUS: Normale Kurve
        # ═══════════════════════════════════════════════════════════════════
        return base_temp, "normal", "📈 Biorhythmus-Kurve"

    # ═══════════════════════════════════════════════════════════════════════════
    # FIX: Fail-Safe bei Sensor-Ausfall
    # ═══════════════════════════════════════════════════════════════════════════
    async def _async_handle_sensor_failure(self, zone_index: int, zone_config: dict):
        """
        FAIL-SAFE: Bei Sensor-Ausfall Heizung sicherheitshalber EINSCHALTEN!
        
        Lieber zu warm als zu kalt - besonders bei Wasserbetten!
        """
        heater_entity = zone_config.get("heater")
        
        _LOGGER.warning(
            f"⚠️ FAIL-SAFE Zone {zone_index}: Sensor-Ausfall! "
            f"Heizung {heater_entity} wird eingeschaltet."
        )
        
        # Heizung einschalten
        await self._async_control_heater(heater_entity, True)
        self._heater_states[heater_entity] = True
        
        # Notification senden
        await self._async_send_notification(
            title="⚠️ Wasserbett Sensor-Ausfall!",
            message=(
                f"Der Temperatursensor für Zone {zone_index + 1} ist nicht erreichbar. "
                f"Die Heizung wurde sicherheitshalber EINGESCHALTET. "
                f"Bitte prüfe den Sensor!"
            ),
            notification_id=f"rejuvenation_bed_sensor_failure_{zone_index}"
        )
        
        return {
            "status": "FAIL_SAFE",
            "reason": "⚠️ Sensor nicht verfügbar - Heizung AN (Sicherheit)",
            "heater_state": True,
        }

    async def _async_update_data(self) -> Dict:
        """Zentraler Loop: Sicherheit -> Energie -> Entscheidung -> Schaltung."""
        try:
            decision = {
                "timestamp": datetime.now().isoformat(),
                "zones": {},
                "global_state": {"energy": {}, "status": "OK"},
                "errors": []
            }
            
            # ═══════════════════════════════════════════════════════════════════
            # FIX: Hardware-Sync beim ersten Update
            # ═══════════════════════════════════════════════════════════════════
            zones = self.config_entry.data.get("zones", [])
            
            if not self._hardware_synced:
                _LOGGER.info("Erster Update-Zyklus: Synchronisiere mit Hardware...")
                
                # KRITISCH: Gespeicherte Diagnostics LADEN bevor irgendwas passiert!
                await self.diagnostics_manager.async_load()
                await self.bed_intelligence.async_load()
                
                for zone_idx, zone_cfg in enumerate(zones):
                    heater_entity = zone_cfg.get("heater")
                    if heater_entity:
                        heater_state = self.hass.states.get(heater_entity)
                        if heater_state:
                            actual_on = heater_state.state == "on"
                            self._heater_states[heater_entity] = actual_on
                            self.anti_short_cycle_manager.sync_with_hardware(
                                heater_entity, actual_on
                            )
                            _LOGGER.info(
                                f"Zone {zone_idx}: Heizung ist "
                                f"{'AN' if actual_on else 'AUS'} (Hardware-Sync)"
                            )
                        else:
                            _LOGGER.warning(f"Zone {zone_idx}: Heizung {heater_entity} nicht gefunden!")
                self._hardware_synced = True
            
            # 1. SICHERHEIT (Prio 1: Überhitzung & Sensor-Check)
            safety_check = await self.safety_manager.async_check_all()
            
            # KRITISCH: Emergency Shutdown (nur bei Überhitzung!)
            if not safety_check["is_safe"]:
                await self._async_emergency_shutdown(safety_check["reason"])
                decision["global_state"]["status"] = "EMERGENCY_SHUTDOWN"
                decision["reason"] = safety_check["reason"]
                return decision
            
            # NEU: Degraded Mode (Sensor-Ausfall)
            is_degraded_mode = safety_check.get("mode") == "degraded"
            degraded_zone = safety_check.get("zone_index")
            
            if is_degraded_mode:
                duty_pct = safety_check.get("duty_cycle", 0.30)
                _LOGGER.warning(
                    f"System im Degraded Mode: {safety_check['reason']} "
                    f"(Duty-Cycle: {duty_pct*100:.0f}%)"
                )
                decision["global_state"]["status"] = "DEGRADED_MODE"
                decision["global_state"]["degraded_reason"] = safety_check["reason"]
            
            # 2. VETO-CHECKS (Sommer-Modus & Präsenz)
            veto_result = await self._async_check_vetos()
            
            # 3. ENERGIE-LOGIK (Solar-Verfügbarkeit & Strompreise)
            energy_state = await self.energy_calculator.async_calculate()
            
            # 4. ZONEN-STEUERUNG
            total_current_power = 0.0

            for zone_index, zone_config in enumerate(zones):
                zone_name = f"Zone {zone_index + 1}"
                
                try:
                    # ═══════════════════════════════════════════════════════════
                    # FIX: Robustes Sensor-Lesen mit Fail-Safe
                    # ═══════════════════════════════════════════════════════════
                    temp_sensor = zone_config.get("temp_sensor")
                    current_temp = self._safe_get_sensor_value(temp_sensor, default=None)
                    current_watt = self._get_zone_power(zone_config)
                    total_current_power += current_watt
                    
                    # FAIL-SAFE: Kein Temperatur-Sensor oder -Wert?
                    if current_temp is None:
                        if temp_sensor:
                            # Sensor konfiguriert aber nicht verfügbar
                            elapsed = (datetime.now() - self._startup_time).total_seconds()
                            
                            if elapsed < self._startup_grace_seconds:
                                # STARTUP GRACE: ESP noch nicht bereit, warten
                                _LOGGER.info(
                                    f"Zone {zone_index}: Sensor noch nicht verfügbar "
                                    f"(Startup {elapsed:.0f}s/{self._startup_grace_seconds}s) - warte..."
                                )
                                decision["zones"][zone_name] = {
                                    "status": "STARTUP_WAIT",
                                    "reason": f"⏳ Warte auf Sensor ({self._startup_grace_seconds - elapsed:.0f}s)",
                                }
                                continue
                            else:
                                # Grace-Period vorbei → FAIL-SAFE!
                                fail_safe_result = await self._async_handle_sensor_failure(
                                    zone_index, zone_config
                                )
                                decision["zones"][zone_name] = fail_safe_result
                                continue
                        else:
                            # Kein Sensor konfiguriert → Basic-Modus
                            _LOGGER.debug(f"Zone {zone_index}: Kein Temp-Sensor, Basic-Modus")
                            current_temp = 27.0  # Annahme für Basic-Modus
                    
                    # NEU: Degraded Mode Override
                    if is_degraded_mode and degraded_zone == zone_index:
                        should_heat = safety_check.get("should_heat", False)
                        target_temp = 27.0
                        
                        decision["zones"][zone_name] = {
                            "target": round(target_temp, 1),
                            "current": round(current_temp, 1) if current_temp else "unknown",
                            "active": should_heat,
                            "watt": round(current_watt, 1),
                            "mode": "degraded",
                            "reason": "⚠️ Degraded Mode: Sensor ausgefallen (30% Duty-Cycle)"
                        }
                        
                        heater_entity = zone_config.get("heater")
                        await self._async_control_heater(heater_entity, should_heat)
                        self._heater_states[heater_entity] = should_heat
                        continue

                    # ═══════════════════════════════════════════════════════════
                    # Präsenz-Erkennung (Sensor-Fusion)
                    # ═══════════════════════════════════════════════════════════
                    moisture_sensor = zone_config.get("moisture_sensor")
                    presence_sensor = zone_config.get("presence_sensor")
                    
                    # Feuchtigkeit als numerischen Wert lesen (SHT41)
                    humidity_value = None
                    if moisture_sensor:
                        humidity_value = self._safe_get_sensor_value(
                            moisture_sensor, default=None
                        )
                    
                    # Luft-Temp lesen (SHT41 oben auf Kern)
                    # PRIORITÄT: 1. Konfigurierter air_temp_sensor, 2. Namenstrick vom Feuchtesensor
                    air_temp = None
                    air_temp_entity = zone_config.get("air_temp_sensor")
                    if air_temp_entity:
                        air_temp = self._safe_get_sensor_value(
                            air_temp_entity, default=None
                        )
                    elif moisture_sensor:
                        # Fallback: SHT41 Luft-Temp über Entity-Namensableitung
                        air_temp_entity = moisture_sensor.replace(
                            "feuchtigkeit", "lufttemp"
                        ).replace("humidity", "temperature")
                        air_temp = self._safe_get_sensor_value(
                            air_temp_entity, default=None
                        )
                    
                    # Dedizierter Präsenz-Sensor (optional)
                    presence_state = None
                    if presence_sensor:
                        presence_state = self._safe_get_sensor_value(
                            presence_sensor, default=None, value_type="bool"
                        )
                    
                    # Power für Duty-Cycle
                    heater_active = self._heater_states.get(
                        zone_config.get("heater"), False
                    )
                    
                    # Kalibrierte Schwellwerte anwenden (wenn verfügbar)
                    if self.bed_intelligence.calibration.is_calibrated:
                        self.presence_detector.thresholds.water_variance_threshold = (
                            self.bed_intelligence.calibration.water_std_threshold
                        )
                    
                    is_present, presence_confidence, presence_reason = (
                        self.presence_detector.detect_presence(
                            zone_index=zone_index,
                            water_temp=current_temp,
                            air_temp=air_temp,
                            humidity=humidity_value,
                            power_watts=current_watt,
                            heater_active=heater_active,
                            presence_sensor_state=presence_state,
                        )
                    )
                    
                    has_presence_sensor = presence_sensor is not None
                    
                    # Zieltemperatur berechnen
                    self.temperature_calculator.update_trend_data(zone_index, current_temp)
                    desired_temp = await self.temperature_calculator.async_calculate_target(
                        zone_index, 
                        energy_state, 
                        veto_result, 
                        coordinator=self,
                        is_present=is_present,
                        has_presence_sensor=has_presence_sensor
                    )
                    
                    # ═══════════════════════════════════════════════════════════
                    # FIX: Mode-Auswertung HIER!
                    # ═══════════════════════════════════════════════════════════
                    final_temp, active_mode, mode_reason = self._apply_mode_adjustments(
                        zone_index, desired_temp
                    )
                    
                    # Wenn Spezial-Modus aktiv, diese Temperatur verwenden
                    if active_mode != "normal":
                        desired_temp = final_temp
                        _LOGGER.debug(f"Zone {zone_index}: {mode_reason}")
                    
                    # MATERIALSCHUTZ: Sanfte Rampen (nur Wasserbett!)
                    if self.ramp_controller is not None:
                        target_temp, ramp_state = self.ramp_controller.calculate_ramped_setpoint(
                            zone_index=zone_index,
                            desired_temp=desired_temp,
                            current_temp=current_temp,
                        )
                        
                        if ramp_state.ramp_active:
                            _LOGGER.debug(
                                f"Zone {zone_index}: Rampe aktiv - "
                                f"Ziel: {desired_temp:.1f}°C, Aktuell: {target_temp:.1f}°C"
                            )
                    else:
                        target_temp = desired_temp
                    
                    # HVAC OFF CHECK
                    from homeassistant.components.climate.const import HVACMode
                    manual_hvac = self.manual_hvac_mode.get(zone_index)
                    
                    if manual_hvac == HVACMode.OFF:
                        should_heat = False
                        target_temp = self.bed_config.get("min_temp", 24.0)
                        
                        heater_entity = zone_config.get("heater")
                        await self._async_control_heater(heater_entity, False)
                        self._heater_states[heater_entity] = False
                        
                        decision["zones"][zone_name] = {
                            "target": round(target_temp, 1),
                            "current": round(current_temp, 1),
                            "active": False,
                            "watt": 0.0,
                            "hvac_mode": HVACMode.OFF,
                            "preset_mode": "none",
                            "is_present": is_present,
                            "reason": "🔴 Manuell ausgeschaltet (HVAC OFF)"
                        }
                        continue
                    
                    # Heiz-Entscheidung mit Hysterese
                    should_heat = await self._async_decide_heating(
                        zone_index, target_temp, current_temp
                    )
                    
                    # Anti-Short-Cycle-Prüfung
                    # BEI BOOST/KRANK: Sofort schalten, kein Anti-Short-Cycle!
                    heater_entity = zone_config.get("heater")
                    current_heater_state = self._heater_states.get(heater_entity, False)
                    
                    if active_mode in ("boost", "sick"):
                        # Sofort schalten bei Sonder-Modi
                        allowed_to_switch = True
                        cycle_reason = f"Sonder-Modus '{active_mode}' umgeht Anti-Short-Cycle"
                    else:
                        # Hole echten Hardware-Zustand für bessere Entscheidung
                        actual_hw_state = None
                        hw_state_obj = self.hass.states.get(heater_entity)
                        if hw_state_obj:
                            actual_hw_state = hw_state_obj.state == "on"
                        
                        allowed_to_switch, cycle_reason = self.anti_short_cycle_manager.can_switch(
                            heater_id=heater_entity,
                            current_state=current_heater_state,
                            desired_state=should_heat,
                            current_temp=current_temp,
                            target_temp=target_temp,
                            actual_hardware_state=actual_hw_state,
                        )
                    
                    if not allowed_to_switch:
                        should_heat = current_heater_state
                        _LOGGER.debug(f"Zone {zone_index}: Short-Cycle verhindert - {cycle_reason}")
                    
                    # Effizienz-Check
                    await self._async_check_heating_efficiency(zone_index, current_temp, should_heat)
                    
                    # Hardware schalten
                    await self._async_control_heater(heater_entity, should_heat)
                    self._heater_states[heater_entity] = should_heat
                    
                    # Schwitz-Erkennung & Leckage-Detection (über PresenceDetector)
                    is_leaking = self.presence_detector.is_potential_leak(zone_index)
                    
                    if is_leaking:
                        _LOGGER.warning(
                            f"⚠️ Zone {zone_index}: LECKAGE-VERDACHT! "
                            f"Feuchtigkeit >85% seit über 3 Stunden!"
                        )
                    
                    # ═══════════════════════════════════════════════════
                    # BedIntelligence: Kalibrierung + Isolation + Schwitz 2.0
                    # ═══════════════════════════════════════════════════
                    water_std = self.presence_detector._last_water_std.get(zone_index, 0.0)
                    
                    # Heizungsstatus für Isolation-Korrektur übergeben
                    heater_entity = zone_config.get("heater")
                    self.bed_intelligence._heater_heating[zone_index] = self._heater_states.get(heater_entity, False)
                    
                    self.bed_intelligence.update(
                        zone_index=zone_index,
                        water_temp=current_temp,
                        air_temp=air_temp,
                        humidity=humidity_value,
                        is_present=is_present,
                        water_std=water_std,
                    )
                    
                    # Schwitz 2.0 (aus BedIntelligence statt PresenceDetector)
                    sweat_status = self.bed_intelligence.get_sweat_status(zone_index)
                    is_sweating = sweat_status.is_sweating or sweat_status.is_wet
                    
                    # Isolations-Check
                    isolation = self.bed_intelligence.get_isolation_status(zone_index)
                    if isolation.energy_waste_warning:
                        await self._async_send_notification(
                            title="🛏️ Bett offen!",
                            message=(
                                f"Dein Bett ist seit {isolation.uncovered_minutes:.0f} Min offen. "
                                f"Δ(Wasser-Luft) = {isolation.delta_water_air:.1f}°C. "
                                f"Bitte zudecken um Energie zu sparen!"
                            ),
                            notification_id=f"rejuvenation_bed_isolation_{zone_index}"
                        )
                    
                    # HVAC-Modus bestimmen
                    hvac_mode, preset_mode = self._determine_hvac_mode(
                        zone_index, is_present, zone_config
                    )
                    
                    decision["zones"][zone_name] = {
                        "target": round(target_temp, 1),
                        "current": round(current_temp, 1),
                        "active": should_heat,
                        "watt": round(current_watt, 1),
                        "hvac_mode": hvac_mode,
                        "preset_mode": preset_mode,
                        "reason": mode_reason if active_mode != "normal" else await self.temperature_calculator.async_get_decision_reason(
                            zone_index, target_temp, current_temp, should_heat, energy_state, coordinator=self
                        ),
                        "is_present": is_present,
                        "presence_confidence": presence_confidence,
                        "presence_reason": presence_reason,
                        "is_sweating": is_sweating,
                        "is_leaking": is_leaking,
                        "humidity_level": sweat_status.humidity_level,
                        "sweat_cause": sweat_status.cause,
                        "isolation_level": isolation.level,
                        "isolation_delta": isolation.delta_water_air,
                        "active_mode": active_mode,
                    }
                    
                    # Sleep Score Tracking
                    await self._async_update_sleep_tracking(
                        zone_index=zone_index,
                        is_present=is_present,
                        current_temp=current_temp,
                        target_temp=target_temp,
                        should_heat=should_heat
                    )
                    
                except Exception as zone_error:
                    # ═══════════════════════════════════════════════════════════
                    # FIX: Bei JEDEM Fehler → Heizung AN (Fail-Safe!)
                    # ═══════════════════════════════════════════════════════════
                    _LOGGER.error(f"Fehler in Zone {zone_index}: {zone_error}", exc_info=True)
                    
                    heater_entity = zone_config.get("heater")
                    if heater_entity:
                        await self._async_control_heater(heater_entity, True)
                        self._heater_states[heater_entity] = True
                    
                    decision["zones"][zone_name] = {
                        "status": "ERROR",
                        "error": str(zone_error),
                        "heater_state": True,
                        "reason": "⚠️ Fehler - Heizung AN (Sicherheit)"
                    }

            decision["global_state"]["energy"] = {
                "total_power": round(total_current_power, 1),
                "solar_active": energy_state.get("solar_active", False),
                "price_status": energy_state.get("price_status", "normal")
            }
            
            # Energy-Budget aktualisieren
            is_solar_active = energy_state.get("mode") and energy_state["mode"].value == "solar_boost"
            is_peak_price = energy_state.get("price_status") == "expensive"
            
            energy_config = self.config_entry.data.get("energy", {})
            total_power_rating = energy_config.get("total_power_rating", 350)
            
            self.diagnostics_manager.update_energy_usage(
                power_watts=total_current_power,
                update_interval_seconds=UPDATE_INTERVAL,
                is_solar_active=is_solar_active,
                is_peak_price=is_peak_price,
                total_power_rating=total_power_rating,
            )

            self._decision_log.append(decision)
            self._last_successful_update = datetime.now()
            self._consecutive_failures = 0
            return decision
        
        except Exception as err:
            self._consecutive_failures += 1
            _LOGGER.error(f"Coordinator Fehler (#{self._consecutive_failures}): {err}", exc_info=True)
            
            # Nach 3 Fehlern: Fail-Safe aktivieren
            if self._consecutive_failures >= 3:
                _LOGGER.critical("3+ aufeinanderfolgende Fehler - aktiviere Fail-Safe!")
                for zone_config in self.config_entry.data.get("zones", []):
                    heater_entity = zone_config.get("heater")
                    if heater_entity:
                        await self._async_control_heater(heater_entity, True)
            
            raise UpdateFailed(f"Update fehlgeschlagen: {err}")

    async def _async_check_heating_efficiency(self, zone_index, current_temp, should_heat):
        """Prüft, ob die Heizung effektiv arbeitet."""
        if not should_heat:
            self._heating_start_time[zone_index] = None
            return

        if self._heating_start_time.get(zone_index) is None:
            self._heating_start_time[zone_index] = datetime.now()
            self._heating_start_temp[zone_index] = current_temp
            return

        duration = (datetime.now() - self._heating_start_time[zone_index]).total_seconds()
        if duration > 2700: 
            temp_diff = current_temp - self._heating_start_temp[zone_index]
            if temp_diff < 0.2:
                _LOGGER.warning(
                    f"Zone {zone_index + 1}: Geringe Heizleistung erkannt. "
                    "Prüfen Sie auf Wärmeverlust oder Defekt."
                )
    
    async def _async_update_sleep_tracking(
        self,
        zone_index: int,
        is_present: bool,
        current_temp: float,
        target_temp: float,
        should_heat: bool
    ):
        """Aktualisiert das Sleep-Score-Tracking basierend auf Präsenz."""
        was_present = self._last_presence_state.get(zone_index, False)
        self._last_presence_state[zone_index] = is_present
        
        # ═══════════════════════════════════════════════════════════════════
        # ANTI-TOILETTENGANG: Kurze Unterbrechungen (<30 min) ignorieren!
        # Tracking läuft weiter, wird nicht neu gestartet.
        # ═══════════════════════════════════════════════════════════════════
        
        if is_present and not was_present:
            # Person kommt (zurück) ins Bett
            if self._night_tracking_active.get(zone_index, False):
                # Tracking läuft schon → NICHT neu starten (z.B. Toilettengang)
                _LOGGER.info(f"Zone {zone_index}: Zurück im Bett - Tracking läuft weiter")
            else:
                # Erstes Hinlegen → Tracking starten
                global_conf = self.config_entry.data.get("global", {})
                options = self.config_entry.options
                bedtime_str = options.get("warm_from", global_conf.get("warm_from", "22:00"))
                
                from datetime import time as dt_time
                bp = bedtime_str.split(":")
                h, m = int(bp[0]), int(bp[1]) if len(bp) > 1 else 0
                planned_bedtime = datetime.combine(datetime.now().date(), dt_time(h, m))
                
                wake_str = options.get("warm_until", global_conf.get("warm_until", "07:00"))
                wp = wake_str.split(":")
                wh, wm = int(wp[0]), int(wp[1]) if len(wp) > 1 else 0
                planned_wake = datetime.combine(datetime.now().date(), dt_time(wh, wm))
                if planned_wake <= planned_bedtime:
                    planned_wake += timedelta(days=1)
                
                self.sleep_score_calculator.start_night_tracking(
                    zone_index=zone_index,
                    planned_bedtime=planned_bedtime,
                    planned_wake=planned_wake
                )
                self._night_tracking_active[zone_index] = True
                
                was_warm = abs(current_temp - target_temp) < 1.0
                self.sleep_score_calculator.record_bed_warm_at_bedtime(zone_index, was_warm)
                
                _LOGGER.info(f"Zone {zone_index}: Schlaf-Tracking gestartet")
        
        elif not is_present and was_present and self._night_tracking_active.get(zone_index, False):
            # Person verlässt Bett ABER Tracking läuft
            # → NICHT sofort beenden! Merke uns den Zeitpunkt
            if not hasattr(self, '_presence_left_at'):
                self._presence_left_at = {}
            self._presence_left_at[zone_index] = datetime.now()
            _LOGGER.debug(f"Zone {zone_index}: Bett verlassen - warte ob Toilettengang")
        
        # Tracking beenden wenn Person >30 Min weg ist
        if (not is_present 
            and self._night_tracking_active.get(zone_index, False)
            and hasattr(self, '_presence_left_at')
            and zone_index in self._presence_left_at):
            
            gone_minutes = (datetime.now() - self._presence_left_at[zone_index]).total_seconds() / 60
            if gone_minutes > 30:
                score = self.sleep_score_calculator.end_night_tracking(zone_index)
                self._night_tracking_active[zone_index] = False
                del self._presence_left_at[zone_index]
                
                if score:
                    _LOGGER.info(f"Zone {zone_index}: Schlaf-Score = {score.total_score}/100")
        
        # Wenn Person zurück ist, Timer löschen
        if is_present and hasattr(self, '_presence_left_at') and zone_index in self._presence_left_at:
            del self._presence_left_at[zone_index]
        
        if self._night_tracking_active.get(zone_index, False):
            self.sleep_score_calculator.record_temperature(zone_index, current_temp, target_temp)
            
            if self.co2_sensor:
                co2_ppm = self._safe_get_sensor_value(self.co2_sensor, default=None)
                if co2_ppm is not None:
                    self.sleep_score_calculator.record_co2(zone_index, co2_ppm)

    async def _async_check_vetos(self) -> Dict:
        """Prüft auf Sommer-Schwelle im Außenbereich."""
        global_cfg = self.config_entry.data.get("global", {})
        outdoor_sensor = global_cfg.get("outdoor_sensor")
        summer_limit = global_cfg.get("summer_threshold", 25)
        
        is_summer = False
        if outdoor_sensor:
            temp = self._safe_get_sensor_value(outdoor_sensor, default=None)
            if temp and temp > summer_limit:
                is_summer = True
        
        return {"is_summer": is_summer}

    async def _async_decide_heating(self, zone_index, target, current) -> bool:
        """Hysterese: Schaltet bei Ziel aus, aber erst 0.3°C unter Ziel wieder ein."""
        zone_config = self.config_entry.data["zones"][zone_index]
        heater = zone_config.get("heater")
        is_active = self._heater_states.get(heater, False)
        
        if is_active:
            should_heat = current < target
        else:
            should_heat = current < (target - 0.3)
        
        _LOGGER.debug(
            f"Zone {zone_index}: {'AN bleiben' if is_active and should_heat else 'EINSCHALTEN' if should_heat else 'AUSSCHALTEN' if is_active else 'AUS bleiben'} - "
            f"Aktuell: {current:.1f}°C, Ziel: {target:.1f}°C"
        )
        
        return should_heat

    def _get_zone_power(self, zone_config) -> float:
        """Ermittelt die Leistung via Sensor oder Schätzung."""
        p_sensor = zone_config.get("power_sensor")
        if p_sensor:
            val = self._safe_get_sensor_value(p_sensor, default=None)
            if val is not None:
                return val
        
        h_state = self.hass.states.get(zone_config.get("heater"))
        if h_state and h_state.state == "on":
            return float(zone_config.get("power_rating", 250))
        return 0.0

    def _get_float_state(self, entity_id) -> Optional[float]:
        """Legacy-Methode - nutzt jetzt _safe_get_sensor_value."""
        return self._safe_get_sensor_value(entity_id, default=None, value_type="float")

    async def _async_control_heater(self, entity, should_heat):
        """Direkte Schaltung der HA-Entität (Switch oder Plug)."""
        if not entity:
            return
            
        domain = entity.split(".")[0]
        service = "turn_on" if should_heat else "turn_off"
        
        # Prüfe ob sich der Zustand wirklich ändert
        current_state = self.hass.states.get(entity)
        if current_state:
            current_on = current_state.state == "on"
            if current_on == should_heat:
                return  # Keine Änderung nötig
        
        try:
            _LOGGER.info(f"🔌 SCHALTE {entity}: {'AUS→AN' if should_heat else 'AN→AUS'}")
            await self.hass.services.async_call(domain, service, {"entity_id": entity})
        except Exception as e:
            _LOGGER.error(f"❌ Hardware-Fehler beim Schalten von {entity}: {e}")
    
    def _determine_hvac_mode(
        self,
        zone_index: int,
        is_present: bool,
        zone_config: dict
    ) -> tuple:
        """Bestimmt HVAC-Modus und Preset."""
        from homeassistant.components.climate.const import (
            HVACMode,
            PRESET_NONE,
            PRESET_AWAY,
            PRESET_BOOST,
        )
        
        hardware_level = zone_config.get("hardware_level", "A")
        manual_hvac = self.manual_hvac_mode.get(zone_index)
        manual_preset = self.manual_preset.get(zone_index, PRESET_NONE)
        manual_boost = self.manual_boost.get(zone_index, False)
        
        if manual_hvac is not None:
            return manual_hvac, manual_preset
        
        if manual_boost:
            return HVACMode.HEAT, PRESET_BOOST
        
        if self.vacation_mode_enabled:
            return HVACMode.AUTO, PRESET_AWAY
        
        sick_until = self.sick_mode_until.get(zone_index)
        if sick_until and datetime.now() < sick_until:
            return HVACMode.HEAT, "sick"
        
        if self.eco_mode_enabled:
            return HVACMode.AUTO, "eco"
        
        if hardware_level in ["C", "B"]:
            return (HVACMode.HEAT, PRESET_NONE) if is_present else (HVACMode.AUTO, PRESET_NONE)
        
        return HVACMode.HEAT, PRESET_NONE

    async def _async_emergency_shutdown(self, reason):
        """Sicherheitsabschaltung aller Zonen."""
        _LOGGER.critical(f"EMERGENCY SHUTDOWN ausgelöst: {reason}")
        for zone in self.config_entry.data.get("zones", []):
            await self._async_control_heater(zone.get("heater"), False)

    @callback
    def get_last_decision(self) -> Optional[Dict]:
        return self._decision_log[-1] if self._decision_log else None
    
    async def _async_send_notification(
        self,
        title: str,
        message: str,
        notification_id: Optional[str] = None
    ):
        """Sendet eine persistente Notification an den User."""
        try:
            await notify_create(
                self.hass,
                message,
                title=title,
                notification_id=notification_id
            )
            _LOGGER.info(f"Notification gesendet: {title}")
        except Exception as e:
            _LOGGER.error(f"Fehler beim Senden der Notification: {e}")
