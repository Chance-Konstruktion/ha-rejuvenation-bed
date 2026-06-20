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
from typing import Dict, Optional

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.components.persistent_notification import async_create as notify_create

from .const import (
    UPDATE_INTERVAL,
    get_bed_config,
    BED_TYPE_WATERBED,
    BED_TYPE_HEATING_PAD,
    BOOST_MAX_TEMP,
    FAILSAFE_MAX_ON_MINUTES,
    STARTUP_GRACE_SECONDS,
    HEATING_EFFICIENCY_WINDOW_SECONDS,
    HEATING_EFFICIENCY_MIN_RISE_C,
    local_now,
)
from .safety_manager import SafetyManager
from .temperature_calculator import TemperatureCalculator
from .energy_state_resolver import EnergyStateResolver
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
        self.energy_calculator = EnergyStateResolver(hass, config_entry)
        self.energy_calculator._coordinator = self  # Für Switch-Status
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
        # CO2-Sensor: Zuerst aus Zone-Config, dann Options, dann global (Rückwärtskompatibilität)
        self.co2_sensor = None  # Wird pro Zone gelesen
        
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
        self._startup_time = local_now()
        self._startup_grace_seconds = STARTUP_GRACE_SECONDS  # Geduld für ESP-Boot
        self._sensor_failure_notified = {}  # Nur einmal pro Zone benachrichtigen
        self._failsafe_on_since = {}  # NEU: Start des Dauer-AN bei Sensor-Ausfall (#2)
        self._sensor_warn_at = {}  # O2: Throttle für Sensor-Warnungen (je Entity)
        
        # ═══════════════════════════════════════════════════════════════════════
        # FIX: Alle Mode-Attribute initialisieren (für switch.py!)
        # ═══════════════════════════════════════════════════════════════════════
        self.manual_boost = {}
        self.boost_until = {}  # NEU: Ablaufzeit für Boost
        self.manual_hvac_mode = {}
        self.manual_preset = {}
        self.manual_target_temp = {}
        self.manual_target_until = {}  # NEU: TTL für manuellen Slider-Wert (#4/#5)
        self.sick_mode_until = {}
        self.sick_mode_temp = {}
        self.thermal_battery_enabled = True  # NEU: Solar-Batterie Default AN
        self.eco_mode_enabled = False  # Tarifmodus Default AUS
        self.vacation_mode_enabled = False  # NEU: Urlaub-Modus Default AUS
        self.vacation_until = None  # NEU: Urlaub-Ende
        self.vacation_temp_override = None  # Optional per Service gesetzt
        
        # Präsenz-Tracking für Biorhythmus-Aktivierung
        self._presence_detected_at = {}   # Wann Präsenz erstmals erkannt
        self._curve_active = {}           # Kurve läuft für diese Zone
        self._actual_bedtime = {}         # ECHTE Einschlafzeit (nicht konfigurierte!)
        self._presence_left_at = {}       # Wann Bett verlassen (für Toiletten-Check)
        self._night_tracking_active = {}
        self._last_presence_state = {}
        self._post_alarm_mode = {}        # Nach Wecker: Warmhalten statt Kurve
        
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

    def get_active_manual_target(self, zone_index: int) -> Optional[float]:
        """
        Gibt die aktive manuelle Zieltemperatur zurück — oder None (#4/#5).

        Ein per Slider/Service gesetzter Wert verfällt nach Ablauf seiner TTL
        (manual_target_until). Danach übernimmt wieder die Biorhythmus-Kurve,
        statt dass die Automatik dauerhaft ausgehebelt bleibt.
        """
        temp = self.manual_target_temp.get(zone_index)
        if temp is None:
            return None

        until = self.manual_target_until.get(zone_index)
        if until is not None and local_now() > until:
            self.manual_target_temp.pop(zone_index, None)
            self.manual_target_until.pop(zone_index, None)
            _LOGGER.info(
                f"Zone {zone_index}: Manuelle Zieltemperatur abgelaufen "
                f"→ zurück zur Automatik"
            )
            return None

        return temp

    def clear_manual_target(self, zone_index: int):
        """Löscht eine manuelle Zieltemperatur (z.B. bei AUTO/Cancel)."""
        self.manual_target_temp.pop(zone_index, None)
        self.manual_target_until.pop(zone_index, None)

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
                self._warn_sensor_throttled(entity_id, f"Sensor {entity_id} nicht gefunden!")
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
            self._warn_sensor_throttled(entity_id, f"Fehler beim Lesen von {entity_id}: {e}")
            return default

    def _warn_sensor_throttled(self, entity_id: str, message: str):
        """
        Loggt eine Sensor-Warnung höchstens einmal pro Stunde je Entity (O2).

        Verhindert WARNING-Spam im 60s-Loop bei dauerhaft fehlendem Sensor —
        erste Meldung als WARNING, weitere innerhalb der Stunde nur DEBUG.
        """
        now = local_now()
        last = self._sensor_warn_at.get(entity_id)
        if last is None or (now - last).total_seconds() >= 3600:
            self._sensor_warn_at[entity_id] = now
            _LOGGER.warning(message)
        else:
            _LOGGER.debug(message)

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
            if vacation_until and local_now() > vacation_until:
                self.vacation_mode_enabled = False
                self.vacation_temp_override = None
                _LOGGER.info("Urlaub-Modus automatisch beendet.")
            else:
                # Wasserbett: Konfigurierte Urlaub-Temp, Heizmatte: kann aus
                if self.bed_type == BED_TYPE_WATERBED:
                    away_temp = float(
                        self.vacation_temp_override
                        if self.vacation_temp_override is not None
                        else self.config_entry.options.get("away_temp")
                        or self.bed_config.get("away_temp", 24.0)
                    )
                    # #3 Kondensationsschutz: Wasserbett NIE unter min_temp
                    min_temp = self.bed_config.get("min_temp", 24.0)
                    if away_temp < min_temp:
                        _LOGGER.info(
                            f"Urlaub-Temp {away_temp}°C unter Minimum "
                            f"({min_temp}°C) → auf {min_temp}°C angehoben (Kondensationsschutz)"
                        )
                        away_temp = min_temp
                    return away_temp, "vacation", f"✈️ Urlaub-Modus ({away_temp}°C Frostschutz)"
                else:
                    return 0.0, "vacation", "✈️ Urlaub-Modus (Heizmatte AUS)"
        
        # ═══════════════════════════════════════════════════════════════════
        # PRIORITÄT 2: Krank-Modus
        # ═══════════════════════════════════════════════════════════════════
        sick_until = self.sick_mode_until.get(zone_index)
        if sick_until and local_now() < sick_until:
            sick_temp = self.sick_mode_temp.get(zone_index, 30.0)
            return sick_temp, "sick", f"🤒 Krank-Modus ({sick_temp}°C konstant)"
        
        # ═══════════════════════════════════════════════════════════════════
        # PRIORITÄT 3: Boost-Modus (#11: feste Zieltemperatur, absolut)
        # Der Wert kommt aus dem TemperatureCalculator (boost_target_temp) und
        # liegt bereits in base_temp. Hier NUR Ablauf-Logik + Safety-Cap — kein
        # zweites Aufrechnen eines Offsets mehr (das war die Dopplung).
        # ═══════════════════════════════════════════════════════════════════
        boost_active = self.manual_boost.get(zone_index, False)
        boost_until = self.boost_until.get(zone_index)

        if boost_active:
            # Prüfe ob Boost abgelaufen
            if boost_until and local_now() > boost_until:
                self.manual_boost[zone_index] = False
                _LOGGER.info(f"Boost für Zone {zone_index} automatisch beendet.")
            else:
                boost_temp = min(base_temp, BOOST_MAX_TEMP)  # Safety: max 34°C
                return boost_temp, "boost", f"🔥 Schnellheizen ({boost_temp:.1f}°C konstant)"
        
        # ═══════════════════════════════════════════════════════════════════
        # PRIORITÄT 4: Tarifmodus → wird jetzt durch EnergyStateResolver
        # als temperature_offset auf die Kurve angewandt (nicht hier)
        # eco_mode_enabled wird vom Switch gesetzt und vom Resolver gelesen
        # ═══════════════════════════════════════════════════════════════════
        
        # ═══════════════════════════════════════════════════════════════════
        # KEIN SPEZIAL-MODUS: Normale Kurve
        # ═══════════════════════════════════════════════════════════════════
        return base_temp, "normal", "📈 Biorhythmus-Kurve"

    # ═══════════════════════════════════════════════════════════════════════════
    # FIX: Fail-Safe bei Sensor-Ausfall
    # ═══════════════════════════════════════════════════════════════════════════
    async def _async_handle_sensor_failure(self, zone_index: int, zone_config: dict):
        """
        FAIL-SAFE bei Sensor-Ausfall — Richtung abhängig vom Bett-Typ (#2):

        - Wasserbett: blind heizen ist sicherer als auskühlen (Kondensation,
          hohe thermische Masse → langsame Reaktion). ABER mit Max-ON-Timeout:
          nach FAILSAFE_MAX_ON_MINUTES auf 30%-Degraded-Duty zurückfallen,
          damit eine dauerhaft fehlende Rückmeldung nicht zu Volllast führt.
        - Heizmatte: niedrige Masse, kein Kondensationsrisiko → blind heizen ist
          gefährlich. Ohne Sensor wird AUSgeschaltet.
        """
        heater_entity = zone_config.get("heater")
        now = local_now()

        if not self.is_waterbed:
            # Heizmatte: ohne Sensor NICHT blind heizen
            await self._async_control_heater(heater_entity, False)
            self._heater_states[heater_entity] = False
            await self._async_send_notification(
                title="⚠️ Heizmatte Sensor-Ausfall!",
                message=(
                    f"Der Temperatursensor für Zone {zone_index + 1} ist nicht erreichbar. "
                    f"Die Heizmatte wurde sicherheitshalber AUSGESCHALTET. "
                    f"Bitte prüfe den Sensor!"
                ),
                notification_id=f"rejuvenation_bed_sensor_failure_{zone_index}",
            )
            self._failsafe_on_since.pop(zone_index, None)
            return {
                "status": "FAIL_SAFE",
                "reason": "⚠️ Sensor nicht verfügbar - Heizmatte AUS (Sicherheit)",
                "heater_state": False,
                "hvac_mode": "off",
                "active": False,
            }

        # Wasserbett: Dauer-AN mit Max-ON-Timeout
        started = self._failsafe_on_since.get(zone_index)
        if started is None:
            self._failsafe_on_since[zone_index] = now
            started = now
        on_minutes = (now - started).total_seconds() / 60

        if on_minutes >= FAILSAFE_MAX_ON_MINUTES:
            # Timeout: auf Degraded-Duty-Cycle (30%) zurückfallen
            should_heat = self.safety_manager.should_heat_in_degraded_mode(zone_index)
            reason = (
                f"⚠️ Sensor-Ausfall seit {on_minutes:.0f} Min - "
                f"Degraded-Duty 30% ({'AN' if should_heat else 'Pause'})"
            )
        else:
            should_heat = True
            reason = "⚠️ Sensor nicht verfügbar - Heizung AN (Sicherheit)"

        _LOGGER.warning(
            f"⚠️ FAIL-SAFE Zone {zone_index}: Sensor-Ausfall! "
            f"Heizung {heater_entity} → {'AN' if should_heat else 'Pause'} "
            f"(seit {on_minutes:.0f} Min)"
        )

        await self._async_control_heater(heater_entity, should_heat)
        self._heater_states[heater_entity] = should_heat

        await self._async_send_notification(
            title="⚠️ Wasserbett Sensor-Ausfall!",
            message=(
                f"Der Temperatursensor für Zone {zone_index + 1} ist nicht erreichbar. "
                f"Die Heizung wurde sicherheitshalber EINGESCHALTET. "
                f"Bitte prüfe den Sensor!"
            ),
            notification_id=f"rejuvenation_bed_sensor_failure_{zone_index}",
        )

        return {
            "status": "FAIL_SAFE",
            "reason": reason,
            "heater_state": should_heat,
            "hvac_mode": "heat",  # HVACMode.HEAT == "heat"
            "active": should_heat,
        }

    def _finalize_energy(self, decision, total_current_power, energy_state):
        """
        Schreibt den Energie-Status in die Entscheidung und aktualisiert das
        Energie-Budget (#9: aus dem Haupt-Loop ausgelagert).
        """
        decision["global_state"]["energy"] = {
            "total_power": round(total_current_power, 1),
            "solar_active": energy_state.get("solar_active", False),
            "price_status": energy_state.get("price_status", "normal"),
        }

        from .energy_state_resolver import EnergyMode

        mode = energy_state.get("mode")
        is_solar_active = mode == EnergyMode.SOLAR_BOOST if mode else False
        is_peak_price = mode == EnergyMode.ECO_MODE if mode else False

        energy_config = self.config_entry.data.get("energy", {})
        total_power_rating = energy_config.get("total_power_rating", 350)

        self.diagnostics_manager.update_energy_usage(
            power_watts=total_current_power,
            update_interval_seconds=UPDATE_INTERVAL,
            is_solar_active=is_solar_active,
            is_peak_price=is_peak_price,
            total_power_rating=total_power_rating,
            power_correction_factor=self.bed_config.get("power_sensor_correction", 1.0),
        )

    async def _async_sync_hardware_once(self, zones):
        """
        Synchronisiert den internen Heizungs-Zustand einmalig mit der Hardware (#9).

        Lädt zuvor gespeicherte Diagnostics/Intelligenz, liest den realen
        Schaltzustand jeder Heizung und richtet den Anti-Short-Cycle-Manager
        danach aus. Läuft nur beim allerersten Update-Zyklus.
        """
        if self._hardware_synced:
            return

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

    async def _async_update_data(self) -> Dict:
        """Zentraler Loop: Sicherheit -> Energie -> Entscheidung -> Schaltung."""
        try:
            decision = {
                "timestamp": local_now().isoformat(),
                "zones": {},
                "global_state": {"energy": {}, "status": "OK"},
                "errors": []
            }
            
            # FIX: Hardware-Sync beim ersten Update (#9: ausgelagert)
            zones = self.config_entry.data.get("zones", [])
            await self._async_sync_hardware_once(zones)

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
            degraded_zones = safety_check.get("degraded_zones", [])
            
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
            energy_state = self.energy_calculator.resolve()
            
            # 4. ZONEN-STEUERUNG
            total_current_power = 0.0

            for zone_index, zone_config in enumerate(zones):
                zone_name = f"Zone {zone_index + 1}"
                watt = await self._process_zone(
                    zone_index,
                    zone_config,
                    zone_name,
                    decision,
                    energy_state,
                    veto_result,
                    is_degraded_mode,
                    degraded_zones,
                )
                total_current_power += watt

            self._finalize_energy(decision, total_current_power, energy_state)

            self._decision_log.append(decision)
            self._last_successful_update = local_now()
            self._consecutive_failures = 0
            return decision
        
        except Exception as err:
            self._consecutive_failures += 1
            _LOGGER.error(f"Coordinator Fehler (#{self._consecutive_failures}): {err}", exc_info=True)
            
            # Nach 3 Fehlern: Fail-Safe aktivieren (Richtung je Bett-Typ, #2)
            if self._consecutive_failures >= 3:
                fail_state = self.is_waterbed
                _LOGGER.critical(
                    f"3+ aufeinanderfolgende Fehler - aktiviere Fail-Safe "
                    f"({'Heizung AN' if fail_state else 'Heizmatte AUS'})!"
                )
                for zone_config in self.config_entry.data.get("zones", []):
                    heater_entity = zone_config.get("heater")
                    if heater_entity:
                        await self._async_control_heater(heater_entity, fail_state)
            
            raise UpdateFailed(f"Update fehlgeschlagen: {err}")

    async def _process_zone(
        self,
        zone_index,
        zone_config,
        zone_name,
        decision,
        energy_state,
        veto_result,
        is_degraded_mode,
        degraded_zones,
    ):
        """Verarbeitet eine einzelne Zone und gibt die aktuelle Leistung (W)
        zurück (#9: aus dem Haupt-Loop ausgelagert)."""
        current_watt = 0.0
        try:
            # ═══════════════════════════════════════════════════════════
            # FIX: Robustes Sensor-Lesen mit Fail-Safe
            # ═══════════════════════════════════════════════════════════
            temp_sensor = zone_config.get("temp_sensor")
            current_temp = self._safe_get_sensor_value(temp_sensor, default=None)
            current_watt = self._get_zone_power(zone_config)

            # FAIL-SAFE: Kein Temperatur-Sensor oder -Wert?
            if current_temp is None:
                if temp_sensor:
                    # Sensor konfiguriert aber nicht verfügbar
                    elapsed = (local_now() - self._startup_time).total_seconds()

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
                        self._sensor_failure_notified[zone_index] = True
                        return current_watt
                    else:
                        # Grace-Period vorbei → FAIL-SAFE!
                        fail_safe_result = await self._async_handle_sensor_failure(
                            zone_index, zone_config
                        )
                        decision["zones"][zone_name] = fail_safe_result
                        self._sensor_failure_notified[zone_index] = True
                        return current_watt
                else:
                    # Kein Sensor konfiguriert → Basic-Modus
                    _LOGGER.debug(f"Zone {zone_index}: Kein Temp-Sensor, Basic-Modus")
                    current_temp = 27.0  # Annahme für Basic-Modus
            else:
                # ═══════════════════════════════════════════════════
                # RECOVERY: Sensor ist (wieder) da!
                # ═══════════════════════════════════════════════════
                if self._sensor_failure_notified.get(zone_index, False):
                    _LOGGER.info(
                        f"✅ Zone {zone_index}: Sensor RECOVERED! "
                        f"({current_temp:.1f}°C) → zurück zu Auto-Modus"
                    )
                    # Manuellen HVAC-Override löschen (war evtl. auf OFF)
                    self.manual_hvac_mode.pop(zone_index, None)
                    self._sensor_failure_notified[zone_index] = False
                    self._failsafe_on_since.pop(zone_index, None)  # #2 Timeout-Reset

                    # Recovery-Notification
                    await self._async_send_notification(
                        title="✅ Sensor wieder da!",
                        message=(
                            f"Zone {zone_index + 1}: Temperatursensor ist wieder online "
                            f"({current_temp:.1f}°C). Normalbetrieb wiederhergestellt."
                        ),
                        notification_id=f"rejuvenation_bed_sensor_failure_{zone_index}"
                    )

            # ═══════════════════════════════════════════════════════════
            # #1 EMERGENCY-LATCH: Hält Not-Aus bis manuell zurückgesetzt
            # (SafetyManager setzt das Flag bei >36°C = Relais-Verdacht)
            # ═══════════════════════════════════════════════════════════
            if self.safety_manager.is_emergency_shutdown(zone_index):
                from homeassistant.components.climate.const import HVACMode as _HVACMode
                heater_entity = zone_config.get("heater")
                await self._async_control_heater(heater_entity, False)
                self._heater_states[heater_entity] = False
                emergency_reason = self.safety_manager.get_emergency_reason(zone_index)
                decision["zones"][zone_name] = {
                    "target": round(current_temp, 1) if current_temp else "unknown",
                    "current": round(current_temp, 1) if current_temp else "unknown",
                    "active": False,
                    "watt": 0.0,
                    "mode": "emergency",
                    "hvac_mode": _HVACMode.OFF,
                    "reason": f"🚨 NOT-AUS aktiv: {emergency_reason} — Stecker prüfen, dann Reset!",
                }
                return current_watt

            # NEU: Degraded Mode Override
            if is_degraded_mode and zone_index in degraded_zones:
                should_heat = self.safety_manager.should_heat_in_degraded_mode(zone_index)
                target_temp = 27.0

                from homeassistant.components.climate.const import HVACMode as _HVACMode
                decision["zones"][zone_name] = {
                    "target": round(target_temp, 1),
                    "current": round(current_temp, 1) if current_temp else "unknown",
                    "active": should_heat,
                    "watt": round(current_watt, 1),
                    "mode": "degraded",
                    "hvac_mode": _HVACMode.HEAT,
                    "reason": "⚠️ Degraded Mode: Sensor ausgefallen (30% Duty-Cycle)"
                }

                heater_entity = zone_config.get("heater")
                await self._async_control_heater(heater_entity, should_heat)
                self._heater_states[heater_entity] = should_heat
                return current_watt

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

            try:
                is_present, presence_confidence, presence_reason = (
                    self.presence_detector.detect_presence(
                        zone_index=zone_index,
                        water_temp=current_temp,
                        air_temp=air_temp,
                        humidity=humidity_value,
                        power_watts=current_watt,
                        heater_active=heater_active,
                        presence_sensor_state=presence_state,
                        is_heating_pad=self.is_heating_pad,
                    )
                )
            except Exception as pres_err:
                _LOGGER.warning(
                    f"Zone {zone_index}: Präsenz-Erkennung Fehler (Fallback): {pres_err}"
                )
                # Fallback: Externer Sensor oder "nicht anwesend"
                is_present = presence_state if presence_state is not None else False
                presence_confidence = 0.0
                presence_reason = "Fallback (Erkennung fehlgeschlagen)"

            # has_presence_sensor: True wenn IRGENDEINE Präsenz-Erkennung aktiv
            # - Externer Sensor (Druckmatte, mmWave)
            # - ODER interner Varianz-Detektor (braucht Wasser-Temp-Sensor, Level C+)
            has_temp_sensor = zone_config.get("temp_sensor") is not None
            has_presence_sensor = (presence_sensor is not None) or has_temp_sensor

            # ═══════════════════════════════════════════════════
            # SCHLAF-TRACKING: Echten Einschlafzeitpunkt ermitteln
            # ═══════════════════════════════════════════════════
            was_present = self._last_presence_state.get(zone_index, False)
            actual_bedtime = self._actual_bedtime.get(zone_index)
            post_alarm = self._post_alarm_mode.get(zone_index, False)

            # Weckzeit ermitteln (pro Zone!)
            global_c = self.config_entry.data.get("global", {})
            opts = self.config_entry.options
            zone_prefix = f"zone_{zone_index}_"
            wake_str = (
                opts.get(f"{zone_prefix}warm_until")
                or opts.get("warm_until")
                or global_c.get("warm_until", "07:00")
            )
            wp = wake_str.split(":")
            wake_h, wake_m = int(wp[0]), int(wp[1]) if len(wp) > 1 else 0
            from datetime import time as dt_time
            wake_t = dt_time(wake_h, wake_m)
            now_t = local_now().time()

            # Sind wir NACH der Weckzeit? (zwischen Wecker und 14:00)
            past_wake = now_t >= wake_t and now_t < dt_time(14, 0)

            if is_present and not was_present:
                # Person kommt ins Bett
                if actual_bedtime is None:
                    # Neue Schlaf-Session → Einschlafzeit merken
                    self._actual_bedtime[zone_index] = local_now()
                    self._curve_active[zone_index] = True
                    self._post_alarm_mode[zone_index] = False
                    _LOGGER.info(
                        f"Zone {zone_index}: Schlaf-Session gestartet um "
                        f"{self._actual_bedtime[zone_index].strftime('%H:%M')}"
                    )
                    # Bedtime-Learning: Noch NICHT aufzeichnen!
                    # Wird erst beim Session-Ende gespeichert,
                    # aber nur wenn die Session >2h war (echter Schlaf).
                    # → Schichtarbeiter, Nickerchen, Fehlpräsenz werden korrekt behandelt.
                else:
                    # Zurück im Bett — war es eine Unterbrechung?
                    left_at = self._presence_left_at.get(zone_index)
                    if left_at:
                        away_min = (local_now() - left_at).total_seconds() / 60
                        if away_min >= 5 and self._night_tracking_active.get(zone_index, False):
                            # >5 Min weg = echte Unterbrechung → Score-Malus
                            self.sleep_score_calculator.record_interruption(
                                zone_index, away_min
                            )
                    _LOGGER.debug(f"Zone {zone_index}: Zurück im Bett")

                # Toiletten-Timer löschen
                self._presence_left_at.pop(zone_index, None)

            elif not is_present and was_present:
                # Person verlässt Bett
                self._presence_left_at[zone_index] = local_now()
                if past_wake:
                    _LOGGER.debug(f"Zone {zone_index}: Bett verlassen (nach Weckzeit)")
                else:
                    _LOGGER.debug(f"Zone {zone_index}: Bett verlassen (Nacht – Kurve läuft weiter)")

            # ═══════════════════════════════════════════════════
            # AUFSTEH-ERKENNUNG (Session-basiert)
            #
            # Zwei Phasen:
            # 1. Kurze Unterbrechung (<60 Min): Kurve läuft weiter
            #    → Toilette, Kind, Trinken. Score wird nicht beendet
            #    aber die Unterbrechung fließt negativ in den Score.
            # 2. Lange Abwesenheit (≥60 Min): Session beendet
            #    → Echtes Aufstehen. Score wird finalisiert.
            #    Bedtime-Learning: Nur wenn Session >2h war.
            # ═══════════════════════════════════════════════════
            if not is_present and zone_index in self._presence_left_at:
                gone_min = (local_now() - self._presence_left_at[zone_index]).total_seconds() / 60

                if gone_min >= 60:
                    # ≥60 Min weg = Session beendet
                    session_bedtime = self._actual_bedtime.get(zone_index)
                    session_duration_h = 0
                    if session_bedtime:
                        session_duration_h = (local_now() - session_bedtime).total_seconds() / 3600

                    # Bedtime Learning: Nur wenn Session >2h (echter Schlaf)
                    if session_bedtime and session_duration_h >= 2.0:
                        self.bed_intelligence.record_bedtime(
                            zone_index, session_bedtime
                        )
                        _LOGGER.info(
                            f"Zone {zone_index}: Schlaf-Session beendet nach "
                            f"{session_duration_h:.1f}h → Bedtime Learning gespeichert"
                        )
                    else:
                        _LOGGER.info(
                            f"Zone {zone_index}: Kurze Session ({session_duration_h:.1f}h) "
                            f"→ Nicht für Learning gespeichert"
                        )

                    self._curve_active[zone_index] = False
                    self._actual_bedtime.pop(zone_index, None)
                    self._post_alarm_mode.pop(zone_index, None)
                    self._presence_left_at.pop(zone_index, None)

                elif gone_min >= 5 and self._night_tracking_active.get(zone_index, False):
                    # 5-60 Min weg: Unterbrechung registrieren
                    # Score-Tracking läuft weiter, aber Unterbrechung wird gezählt
                    if not hasattr(self, '_interruption_logged'):
                        self._interruption_logged = {}
                    left_at = self._presence_left_at.get(zone_index)
                    if left_at and zone_index not in self._interruption_logged:
                        self._interruption_logged[zone_index] = True
                        _LOGGER.debug(
                            f"Zone {zone_index}: Schlaf-Unterbrechung ({gone_min:.0f} Min)"
                        )

            # Zurück im Bett → Unterbrechungs-Flag resetten
            if is_present and not was_present and hasattr(self, '_interruption_logged'):
                self._interruption_logged.pop(zone_index, None)

            # Wecker-Check: Nach Wecker-Zeit → Post-Alarm-Modus
            if actual_bedtime and self._curve_active.get(zone_index):
                if past_wake and not post_alarm:
                    self._post_alarm_mode[zone_index] = True
                    _LOGGER.info(
                        f"Zone {zone_index}: Wecker-Zeit ({wake_str}) vorbei → Post-Alarm Warmhalten"
                    )

            self._last_presence_state[zone_index] = is_present

            # Zieltemperatur berechnen
            self.temperature_calculator.update_trend_data(zone_index, current_temp)
            desired_temp = await self.temperature_calculator.async_calculate_target(
                zone_index, 
                energy_state, 
                veto_result, 
                coordinator=self,
                is_present=is_present,
                has_presence_sensor=has_presence_sensor,
                actual_bedtime=self._actual_bedtime.get(zone_index),
                post_alarm=self._post_alarm_mode.get(zone_index, False),
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
            # ABER: Boost und Sick umgehen die Rampe!
            if self.ramp_controller is not None and active_mode not in ("boost", "sick"):
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
                return current_watt

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

            # ═══════════════════════════════════════════════════════════
            # #1 ERWEITERTE ZONEN-SAFETY (zweite Verteidigungslinie):
            # Klebe-Relais, Sensor-Defekt (3h ohne Anstieg), Übertemperatur.
            # Setzt ggf. Emergency-Latch (>36°C). Hat das LETZTE Wort vor
            # dem Schalten — kann should_heat nur AUSschalten, nie AN.
            # ═══════════════════════════════════════════════════════════
            is_safe, safety_status, safety_notif = (
                await self.safety_manager.async_check_zone_safety(
                    zone_index, current_temp, target_temp, should_heat
                )
            )
            if not is_safe:
                should_heat = False
                _LOGGER.warning(
                    f"Zone {zone_index}: Safety-Veto ({safety_status}) → Heizung AUS"
                )
            if safety_notif:
                await self._async_send_notification(
                    title=f"🛡️ Sicherheit Zone {zone_index + 1}",
                    message=safety_notif,
                    notification_id=f"rejuvenation_bed_safety_{zone_index}",
                )

            # Effizienz-Check
            await self._async_check_heating_efficiency(zone_index, current_temp, should_heat)

            # Hardware schalten
            await self._async_control_heater(heater_entity, should_heat)
            self._heater_states[heater_entity] = should_heat

            # Schwitz-Erkennung & Leckage-Detection (über PresenceDetector)
            is_leaking = False  # Default falls Leak-Check crasht
            try:
                is_leaking = self.presence_detector.is_potential_leak(zone_index)
                if is_leaking:
                    _LOGGER.warning(
                        f"⚠️ Zone {zone_index}: LECKAGE-VERDACHT! "
                        f"Feuchtigkeit >85% seit über 3 Stunden!"
                    )
            except Exception as leak_err:
                _LOGGER.debug(f"Zone {zone_index}: Leak-Check Fehler: {leak_err}")

            # ═══════════════════════════════════════════════════
            # BedIntelligence: Kalibrierung + Isolation + Schwitz 2.0
            # NICHT-KRITISCH: Crash hier darf Heizung NIE lahmlegen!
            # ═══════════════════════════════════════════════════
            is_sweating = False  # Default falls Intelligence crasht
            sweat_status = None  # Default falls Intelligence crasht
            isolation = None  # Default falls Intelligence crasht
            try:
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
                is_sweating = sweat_status.is_sweating or sweat_status.is_moist

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
            except Exception as intel_err:
                _LOGGER.warning(
                    f"Zone {zone_index}: BedIntelligence-Fehler (Heizung läuft weiter): {intel_err}"
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
                "humidity_level": sweat_status.humidity_level if sweat_status else None,
                "sweat_cause": sweat_status.cause if sweat_status else None,
                "isolation_level": isolation.level if isolation else None,
                "isolation_delta": isolation.delta_water_air if isolation else None,
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

            return current_watt

        except Exception as zone_error:
            # ═══════════════════════════════════════════════════════════
            # FIX: Bei JEDEM Fehler → Heizung AN (Fail-Safe!)
            # ═══════════════════════════════════════════════════════════
            _LOGGER.error(f"Fehler in Zone {zone_index}: {zone_error}", exc_info=True)

            # #2 Fail-Safe-Richtung je Bett-Typ: Wasserbett AN, Heizmatte AUS
            fail_state = self.is_waterbed
            heater_entity = zone_config.get("heater")
            if heater_entity:
                await self._async_control_heater(heater_entity, fail_state)
                self._heater_states[heater_entity] = fail_state

            decision["zones"][zone_name] = {
                "status": "ERROR",
                "error": str(zone_error),
                "heater_state": fail_state,
                "reason": (
                    "⚠️ Fehler - Heizung AN (Sicherheit)"
                    if fail_state
                    else "⚠️ Fehler - Heizmatte AUS (Sicherheit)"
                ),
            }
        return current_watt

    async def _async_check_heating_efficiency(self, zone_index, current_temp, should_heat):
        """Prüft, ob die Heizung effektiv arbeitet."""
        if not should_heat:
            self._heating_start_time[zone_index] = None
            return

        if self._heating_start_time.get(zone_index) is None:
            self._heating_start_time[zone_index] = local_now()
            self._heating_start_temp[zone_index] = current_temp
            return

        duration = (local_now() - self._heating_start_time[zone_index]).total_seconds()
        if duration > HEATING_EFFICIENCY_WINDOW_SECONDS:
            temp_diff = current_temp - self._heating_start_temp[zone_index]
            if temp_diff < HEATING_EFFICIENCY_MIN_RISE_C:
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
        # Präsenz-Tracking passiert jetzt im Haupt-Loop (oben)
        # Hier nur noch: Sleep-Score Daten aufzeichnen
        
        actual_bedtime = self._actual_bedtime.get(zone_index)
        
        if is_present and actual_bedtime and not self._night_tracking_active.get(zone_index, False):
            # Erstes Hinlegen → Sleep-Score Tracking starten
            global_conf = self.config_entry.data.get("global", {})
            options = self.config_entry.options
            
            from datetime import time as dt_time
            z_prefix = f"zone_{zone_index}_"
            wake_str = (
                options.get(f"{z_prefix}warm_until")
                or options.get("warm_until")
                or global_conf.get("warm_until", "07:00")
            )
            wp = wake_str.split(":")
            wh, wm = int(wp[0]), int(wp[1]) if len(wp) > 1 else 0
            planned_wake = datetime.combine(local_now().date(), dt_time(wh, wm))
            if planned_wake <= actual_bedtime:
                planned_wake += timedelta(days=1)
            
            self.sleep_score_calculator.start_night_tracking(
                zone_index=zone_index,
                planned_bedtime=actual_bedtime,
                planned_wake=planned_wake
            )
            self._night_tracking_active[zone_index] = True
            
            was_warm = abs(current_temp - target_temp) < 1.0
            self.sleep_score_calculator.record_bed_warm_at_bedtime(zone_index, was_warm)
            _LOGGER.info(f"Zone {zone_index}: Schlaf-Score Tracking gestartet")
        
        # Tracking beenden wenn Kurve beendet (>15 Min weg, im Haupt-Loop gesetzt)
        if (not self._curve_active.get(zone_index, False)
            and self._night_tracking_active.get(zone_index, False)
            and actual_bedtime is None):
            
            score = self.sleep_score_calculator.end_night_tracking(zone_index)
            self._night_tracking_active[zone_index] = False
            if score:
                _LOGGER.info(f"Zone {zone_index}: Schlaf-Score = {score.total_score}/100")
        
        # Laufende Aufzeichnung
        if self._night_tracking_active.get(zone_index, False):
            self.sleep_score_calculator.record_temperature(zone_index, current_temp, target_temp)
            
            # CO2: Zuerst aus Zone, dann Options, dann global (Rückwärtskompatibilität)
            zones = self.config_entry.data.get("zones", [])
            zone_conf = zones[zone_index] if zone_index < len(zones) else {}
            co2_entity = (
                zone_conf.get("co2_sensor")
                or self.config_entry.options.get("co2_sensor")
                or self.config_entry.data.get("global", {}).get("co2_sensor")
            )
            if co2_entity:
                co2_ppm = self._safe_get_sensor_value(co2_entity, default=None)
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
        if sick_until and local_now() < sick_until:
            return HVACMode.HEAT, PRESET_NONE  # Krank wird über Status-Sensor angezeigt
        
        if self.eco_mode_enabled:
            return HVACMode.AUTO, PRESET_NONE  # Eco wird über Status-Sensor angezeigt
        
        if hardware_level in ["E", "D", "C", "B+", "B"]:
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
            result = notify_create(
                self.hass,
                message,
                title=title,
                notification_id=notification_id
            )
            # HA-Version Kompatibilität: async_create kann sync oder async sein
            if result is not None:
                await result
        except Exception as e:
            _LOGGER.debug(f"Notification-Fehler (nicht kritisch): {e}")
