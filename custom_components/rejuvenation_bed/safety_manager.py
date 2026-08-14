"""
Safety-Manager für das Rejuvenation Bed.

KRITISCHE SICHERHEITSKOMPONENTE!

Schützt vor:
1. Übertemperatur (>34°C → Notification + Alarm)
2. Klebe-Relais (Heizung AN aber HA sagt AUS → Alarm)
3. Sensor-Defekt (3h heizen, <0.5°C Anstieg → NOT-AUS)
4. Sensor-Ausfall → Degraded Mode (30% Duty-Cycle)
5. Leckage (Feuchtigkeit >30 Min → Warnung) - NUR Wasserbett!

WICHTIG: Der Hardware-Thermostat muss IMMER im Kreis bleiben!
Software-Safety ist die ZWEITE Verteidigungslinie, nicht die erste!

HIERARCHIE DER SICHERHEIT:
1. Hardware-Thermostat (34-36°C) - MUSS im Kreis sein!
2. Dieser Safety-Manager (Software)
3. User-Notification (wenn alles andere versagt)
"""

import logging
from datetime import datetime
from typing import Dict, Optional, Tuple
from homeassistant.core import HomeAssistant

from .const import ABSOLUTE_MAX_TEMP, WATERBED_CONFIG, local_now

_LOGGER = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# SAFETY-KONSTANTEN
# ═══════════════════════════════════════════════════════════════════════════════

# Übertemperatur-Schwellen
OVERHEAT_WARNING_TEMP = 32.0  # Erste Warnung
OVERHEAT_CRITICAL_TEMP = 34.0  # Kritisch - User muss handeln!
OVERHEAT_EMERGENCY_TEMP = 36.0  # NOT-AUS - Relais wahrscheinlich defekt

# Sensor-Defekt-Erkennung
HEATING_EFFICIENCY_CHECK_HOURS = 3.0  # Nach 3h heizen prüfen
HEATING_MIN_TEMP_RISE = 0.5  # Mindestens 0.5°C Anstieg erwartet

# Klebe-Relais-Erkennung
#
# Ein klebendes Relais heizt KONTINUIERLICH → die Temperatur steigt schnell und
# anhaltend. Langsame Drift (warmes Schlafzimmer im Sommer, Körperwärme eines
# Schläfers) ist KEIN Defekt. Deshalb bewerten wir die ANSTIEGSRATE in einem
# gleitenden Fenster – nicht den absoluten Anstieg seit dem (evtl. Stunden alten)
# AUS-Befehl. Sonst kippt jede minimale Drift nach genug Zeit in einen Fehlalarm.
STUCK_RELAY_CHECK_MINUTES = 10  # Frühestens nach 10 Min bewerten (Sensor-Rauschen glätten)
STUCK_RELAY_WINDOW_MINUTES = 30  # Gleitendes Beobachtungsfenster
STUCK_RELAY_TEMP_RISE = 0.8  # Anstieg INNERHALB des Fensters, der auf aktives Heizen deutet (~1.6°C/h)

# Degraded Mode (bei Sensor-Ausfall)
DEGRADED_DUTY_CYCLE = 0.30  # 30% Heizleistung
DEGRADED_CYCLE_TIME_SEC = 600  # 10 Min Zyklus (3 Min AN, 7 Min AUS)


class SafetyManager:
    """
    Zentrale Sicherheitsinstanz für das Rejuvenation Bed.

    Bei Klebe-Relais hilft nur:
    - Notification an User → Stecker ziehen!
    - Hardware-Thermostat als letzte Rettung
    """

    def __init__(self, hass: HomeAssistant, config_entry, bed_config: dict = None):
        """
        Initialisiert den Safety-Manager.

        Args:
            hass: Home Assistant Instanz
            config_entry: Config Entry
            bed_config: Bett-Typ-spezifische Konfiguration (optional, Default=Wasserbett)
        """
        self.hass = hass
        self.config_entry = config_entry

        # Bett-Typ Konfiguration (Default = Wasserbett für maximale Sicherheit)
        self.bed_config = bed_config or WATERBED_CONFIG.copy()

        # Feature-Flags basierend auf Bett-Typ
        self.leak_detection_enabled = self.bed_config.get("leak_detection", True)
        self.condensation_check_enabled = self.bed_config.get("condensation_risk", True)
        self.min_temp = self.bed_config.get("min_temp", 24.0)

        _LOGGER.debug(
            f"SafetyManager initialisiert: "
            f"Leckage={self.leak_detection_enabled}, "
            f"Kondensation={self.condensation_check_enabled}, "
            f"Min-Temp={self.min_temp}°C"
        )

        # Tracking für Sensor-Defekt-Erkennung
        self._heating_start_time: Dict[int, datetime] = {}
        self._heating_start_temp: Dict[int, float] = {}

        # Tracking für Klebe-Relais-Erkennung
        self._off_command_time: Dict[int, datetime] = {}
        self._off_command_temp: Dict[int, float] = {}

        # Alarm-Status (verhindert Spam)
        self._last_overheat_notification: Dict[int, datetime] = {}
        self._last_stuck_relay_notification: Dict[int, datetime] = {}
        self._last_sensor_defect_notification: Dict[int, datetime] = {}

        # Emergency-Shutdown Status
        self._emergency_shutdown: Dict[int, bool] = {}
        self._emergency_reason: Dict[int, str] = {}

        # Degraded Mode Tracking
        self._degraded_cycle_start: Dict[int, datetime] = {}
        self._degraded_state: Dict[int, bool] = {}  # True = heating, False = pause

    async def async_check_all(self) -> Dict:
        """
        Führt alle kritischen Sicherheitschecks durch.

        DIESE METHODE WIRD VOM COORDINATOR AUFGERUFEN!
        """
        # 1. ÜBERHITZUNG (Hard-Limit Schutz bei max 38°C)
        temp_check = await self._check_overheating()
        if not temp_check["is_safe"]:
            return temp_check

        # 2. SENSOR-VERFÜGBARKEIT
        availability_check = await self._check_sensor_availability()
        if availability_check.get("mode") == "degraded":
            return availability_check

        # Alles OK
        return {"is_safe": True, "mode": "normal", "reason": "OK"}

    async def async_check_zone_safety(
        self,
        zone_index: int,
        current_temp: float,
        target_temp: float,
        heater_commanded_on: bool,
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Führt erweiterte Sicherheitschecks für eine Zone durch.

        Returns:
            (is_safe, status, notification_message)
        """
        now = local_now()
        notification = None

        # ═══════════════════════════════════════════════════════════════════════
        # CHECK 1: Übertemperatur
        # ═══════════════════════════════════════════════════════════════════════
        if current_temp >= OVERHEAT_EMERGENCY_TEMP:
            self._emergency_shutdown[zone_index] = True
            self._emergency_reason[zone_index] = f"NOTFALL: {current_temp:.1f}°C erreicht!"

            notification = self._create_critical_notification(
                zone_index,
                f"🚨 NOTFALL Zone {zone_index+1}: {current_temp:.1f}°C!\n\n"
                f"SOFORT STECKER ZIEHEN!\n\n"
                f"Das Relais ist möglicherweise defekt (klebt). "
                f"Die Software kann die Heizung nicht mehr abschalten.\n\n"
                f"Prüfe den Hardware-Thermostat und das Relais!",
            )
            return False, "EMERGENCY_SHUTDOWN", notification

        elif current_temp >= OVERHEAT_CRITICAL_TEMP:
            notification = self._create_warning_notification(
                zone_index,
                "overheat",
                f"⚠️ Zone {zone_index+1}: {current_temp:.1f}°C!\n\n"
                f"Das ist zu heiß! Prüfe:\n"
                f"• Ist der Hardware-Thermostat auf max. 34°C gestellt?\n"
                f"• Funktioniert das Relais korrekt?\n\n"
                f"Heizung wird abgeschaltet.",
            )
            return False, f"OVERHEAT_CRITICAL ({current_temp:.1f}°C)", notification

        elif current_temp >= OVERHEAT_WARNING_TEMP:
            _LOGGER.warning(f"Zone {zone_index}: Temperatur hoch ({current_temp:.1f}°C)")
            return True, f"OVERHEAT_WARNING ({current_temp:.1f}°C)", None

        # ═══════════════════════════════════════════════════════════════════════
        # CHECK 2: Klebe-Relais Erkennung
        # ═══════════════════════════════════════════════════════════════════════
        if not heater_commanded_on:
            ref_time = self._off_command_time.get(zone_index)
            if ref_time is None:
                # Erstkontakt: Referenzpunkt für das gleitende Fenster setzen.
                self._off_command_time[zone_index] = now
                self._off_command_temp[zone_index] = current_temp
            else:
                window_minutes = (now - ref_time).total_seconds() / 60
                temp_rise = current_temp - self._off_command_temp[zone_index]

                if window_minutes >= STUCK_RELAY_CHECK_MINUTES and temp_rise >= STUCK_RELAY_TEMP_RISE:
                    # Schneller, anhaltender Anstieg trotz AUS-Befehl → echter Verdacht.
                    notification = self._create_warning_notification(
                        zone_index,
                        "stuck_relay",
                        f"⚠️ Zone {zone_index+1}: Relais-Verdacht!\n\n"
                        f"Die Heizung ist AUS befohlen, aber die Temperatur steigt "
                        f"schnell weiter (+{temp_rise:.1f}°C in {window_minutes:.0f} Min).\n\n"
                        f"Das deutet auf ein klebendes Relais hin. Häufige harmlose Ursachen:\n"
                        f"• Jemand liegt im Bett (Körperwärme)\n"
                        f"• Sehr warmes Schlafzimmer (Sommer)\n"
                        f"• Jemand hat manuell eingeschaltet\n\n"
                        f"Bitte prüfen, ob die Heizung wirklich aus ist.",
                    )
                    return True, f"STUCK_RELAY_SUSPECTED (+{temp_rise:.1f}°C/{window_minutes:.0f}min)", notification

                # Fenster nachziehen, sobald es abgelaufen ist ODER die Temperatur
                # nicht (mehr) steigt. So vergleichen wir stets gegen einen frischen
                # Messwert und werten nur einen ANHALTENDEN Anstieg – langsame
                # Sommer-/Körperwärme-Drift akkumuliert nie zu einem Fehlalarm.
                if window_minutes >= STUCK_RELAY_WINDOW_MINUTES or temp_rise <= 0:
                    self._off_command_time[zone_index] = now
                    self._off_command_temp[zone_index] = current_temp
        else:
            self._off_command_time.pop(zone_index, None)
            self._off_command_temp.pop(zone_index, None)

        # ═══════════════════════════════════════════════════════════════════════
        # CHECK 3: Sensor-Defekt (lange heizen, keine Temp-Änderung)
        # ═══════════════════════════════════════════════════════════════════════
        if heater_commanded_on:
            if zone_index not in self._heating_start_time:
                self._heating_start_time[zone_index] = now
                self._heating_start_temp[zone_index] = current_temp
            else:
                heating_hours = (now - self._heating_start_time[zone_index]).total_seconds() / 3600
                temp_rise = current_temp - self._heating_start_temp[zone_index]

                if heating_hours >= HEATING_EFFICIENCY_CHECK_HOURS:
                    if temp_rise < HEATING_MIN_TEMP_RISE:
                        notification = self._create_warning_notification(
                            zone_index,
                            "sensor_defect",
                            f"⚠️ Zone {zone_index+1}: Sensor-Problem?\n\n"
                            f"Heizung läuft seit {heating_hours:.1f}h, "
                            f"aber Temperatur stieg nur um {temp_rise:.1f}°C.\n\n"
                            f"Mögliche Ursachen:\n"
                            f"• Sensor verrutscht/falsch platziert\n"
                            f"• Sensor defekt\n"
                            f"• Heizung defekt\n"
                            f"• Großer Wärmeverlust (Fenster offen?)\n\n"
                            f"Heizung wird zur Sicherheit abgeschaltet.",
                        )
                        self._heating_start_time[zone_index] = now
                        self._heating_start_temp[zone_index] = current_temp
                        return False, "SENSOR_DEFECT_SUSPECTED", notification
        else:
            self._heating_start_time.pop(zone_index, None)
            self._heating_start_temp.pop(zone_index, None)

        return True, "OK", None

    async def _check_overheating(self) -> Dict:
        """Prüft auf Überschreitung der konfigurierten Max-Temperatur."""
        zones = self.config_entry.data.get("zones", [])

        for idx, zone in enumerate(zones):
            sensor = zone.get("temp_sensor")
            if not sensor:
                continue

            user_limit = zone.get("hardware_max", 36)
            hard_limit = min(user_limit, ABSOLUTE_MAX_TEMP)

            state = self.hass.states.get(sensor)
            if state and state.state not in ["unknown", "unavailable"]:
                try:
                    current_temp = float(state.state)
                    if current_temp >= hard_limit:
                        _LOGGER.critical(f"Zone {idx}: ÜBERHITZUNG! {current_temp}°C >= {hard_limit}°C")
                        return {
                            "is_safe": False,
                            "mode": "emergency",
                            "reason": f"Zone {idx+1}: Überhitzung ({current_temp:.1f}°C)",
                            "zone": idx,
                        }
                except ValueError:
                    pass

        return {"is_safe": True}

    async def _check_sensor_availability(self) -> Dict:
        """
        Prüft ob Sensoren verfügbar sind.

        Bei Ausfall: Degraded Mode (nicht komplettes Aus!)
        """
        zones = self.config_entry.data.get("zones", [])
        unavailable_zones = []

        for idx, zone in enumerate(zones):
            sensor = zone.get("temp_sensor")
            if sensor:
                state = self.hass.states.get(sensor)
                if state is None or state.state in ["unknown", "unavailable"]:
                    unavailable_zones.append(idx)

        if unavailable_zones:
            return {
                "is_safe": True,  # NICHT unsafe!
                "mode": "degraded",
                "reason": f"Sensor(en) ausgefallen: Zone(n) {[z+1 for z in unavailable_zones]}",
                "degraded_zones": unavailable_zones,
            }

        return {"is_safe": True, "mode": "normal"}

    def should_heat_in_degraded_mode(self, zone_index: int) -> bool:
        """
        Bestimmt ob im Degraded Mode gerade geheizt werden soll.

        Verwendet 30% Duty-Cycle: 3 Min AN, 7 Min AUS
        """
        now = local_now()

        if zone_index not in self._degraded_cycle_start:
            self._degraded_cycle_start[zone_index] = now
            self._degraded_state[zone_index] = True

        elapsed = (now - self._degraded_cycle_start[zone_index]).total_seconds()

        if elapsed >= DEGRADED_CYCLE_TIME_SEC:
            self._degraded_cycle_start[zone_index] = now
            elapsed = 0

        heating_time = DEGRADED_CYCLE_TIME_SEC * DEGRADED_DUTY_CYCLE
        return elapsed < heating_time

    def _create_critical_notification(self, zone_index: int, message: str) -> str:
        """Erstellt eine kritische Notification."""
        _LOGGER.critical(f"SAFETY CRITICAL Zone {zone_index}: {message}")
        return message

    def _create_warning_notification(self, zone_index: int, notification_type: str, message: str) -> Optional[str]:
        """Erstellt eine Warnung mit Spam-Schutz (max. 1x pro Stunde)."""
        now = local_now()

        tracking = {
            "overheat": self._last_overheat_notification,
            "stuck_relay": self._last_stuck_relay_notification,
            "sensor_defect": self._last_sensor_defect_notification,
        }.get(notification_type, {})

        last_sent = tracking.get(zone_index)
        if last_sent and (now - last_sent).total_seconds() < 3600:
            return None

        tracking[zone_index] = now
        _LOGGER.warning(f"SAFETY WARNING Zone {zone_index}: {message}")
        return message

    def trigger_emergency(self, zone_index: int, reason: str) -> bool:
        """Verriegelt eine Zone von außen. Gibt True zurück, wenn neu.

        Bis hierher konnte die Verriegelung nur in
        :meth:`async_check_zone_safety` gesetzt werden -- und die wurde bei
        einer Überhitzung nie erreicht. Der Grund: ``_check_overheating``
        greift bei ``min(hardware_max, ABSOLUTE_MAX_TEMP)``, und
        ``hardware_max`` ist per Voreinstellung 36, also genau
        :data:`OVERHEAT_EMERGENCY_TEMP`. Der Coordinator kehrte deshalb
        immer schon in der globalen Prüfung zurück, und die Zonen-Prüfung
        lief erst gar nicht.

        Ergebnis war ein Not-Aus, der keiner war: Heizung aus, solange der
        Fühler zu heiß meldet, und selbsttätig wieder an, sobald er einen
        plausiblen Wert liefert. Genau der Verlauf, den ein klebendes
        Relais erzeugt.

        Die Schwellen bleiben unangetastet -- sie zu verschieben hieße, die
        Abschaltung nach oben zu rücken. Stattdessen darf die globale
        Prüfung die Verriegelung jetzt selbst setzen.

        Der Rückgabewert unterscheidet die erste Verriegelung von jedem
        weiteren Durchlauf, damit die Benachrichtigung nicht im
        Sekundentakt neu geschrieben wird.
        """
        if self._emergency_shutdown.get(zone_index):
            return False
        self._emergency_shutdown[zone_index] = True
        self._emergency_reason[zone_index] = reason
        _LOGGER.critical(f"Zone {zone_index}: NOT-AUS verriegelt -- {reason}")
        return True

    def is_emergency_shutdown(self, zone_index: int) -> bool:
        """Prüft ob ein Emergency-Shutdown aktiv ist."""
        return self._emergency_shutdown.get(zone_index, False)

    def emergency_zones(self) -> list:
        """Alle derzeit verriegelten Zonen."""
        return sorted(z for z, aktiv in self._emergency_shutdown.items() if aktiv)

    def get_emergency_reason(self, zone_index: int) -> Optional[str]:
        """Gibt den Grund für einen Emergency-Shutdown zurück."""
        return self._emergency_reason.get(zone_index)

    def clear_emergency(self, zone_index: int):
        """Hebt einen Emergency-Shutdown auf (nach manueller Prüfung!)."""
        if zone_index in self._emergency_shutdown:
            _LOGGER.info(f"Zone {zone_index}: Emergency-Shutdown manuell aufgehoben")
            del self._emergency_shutdown[zone_index]
            self._emergency_reason.pop(zone_index, None)

    def get_safety_status(self, zone_index: int) -> dict:
        """Gibt den aktuellen Sicherheits-Status zurück."""
        return {
            "emergency_shutdown": self.is_emergency_shutdown(zone_index),
            "emergency_reason": self.get_emergency_reason(zone_index),
            "heating_duration_hours": self._get_heating_duration(zone_index),
            "off_duration_minutes": self._get_off_duration(zone_index),
        }

    def _get_heating_duration(self, zone_index: int) -> Optional[float]:
        """Gibt die aktuelle Heizdauer in Stunden zurück."""
        start = self._heating_start_time.get(zone_index)
        if start:
            return (local_now() - start).total_seconds() / 3600
        return None

    def _get_off_duration(self, zone_index: int) -> Optional[float]:
        """Gibt die Dauer seit AUS-Befehl in Minuten zurück."""
        start = self._off_command_time.get(zone_index)
        if start:
            return (local_now() - start).total_seconds() / 60
        return None
