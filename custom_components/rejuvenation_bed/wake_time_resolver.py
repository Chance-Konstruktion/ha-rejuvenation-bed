"""
Wake-Time-Resolver für das Rejuvenation Bed.

Löst die Aufwachzeit dynamisch auf - entweder aus:
1. Einem Home Assistant Wecker (sensor.next_alarm, input_datetime, etc.)
2. Einer fest konfigurierten Zeit (Fallback)
3. Hybrid-Modus (Wecker > Fallback)

NEU: Wochenend-Erkennung!
- Automatisch später aufwachen an freien Tagen
- Nutzt binary_sensor.workday wenn verfügbar

Wichtig: Kein "Einfrieren" der Kurve bei Sensor-Ausfällen!
"""

import logging
from datetime import datetime, time, timedelta
from typing import Optional, Tuple
from homeassistant.core import HomeAssistant, State
from .const import local_now
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)


class WakeTimeResolver:
    """
    Ermittelt die effektive Aufwachzeit basierend auf verschiedenen Quellen.
    
    Unterstützt:
    - Fixed Time: Immer dieselbe Uhrzeit
    - Alarm Entity: Liest aus HA-Wecker-Sensoren
    - Hybrid: Wecker wenn verfügbar, sonst Fixed Time
    
    NEU: Wochenend-Verschiebung!
    """
    
    # Alarm-Entity-Typen, die wir verstehen
    SUPPORTED_ALARM_TYPES = [
        "sensor",           # sensor.next_alarm (Android/iOS Companion App)
        "input_datetime",   # Manueller HA Datetime Helper
    ]
    
    def __init__(
        self,
        hass: HomeAssistant,
        mode: str = "hybrid",
        fixed_time: Optional[time] = None,
        alarm_entity: Optional[str] = None,
        weekend_offset_hours: float = 0.0,  # NEU!
        workday_sensor: Optional[str] = None,  # NEU!
    ):
        """
        Initialisiert den Resolver.
        
        Args:
            hass: Home Assistant Instanz
            mode: "fixed_time", "alarm_entity", oder "hybrid"
            fixed_time: Feste Aufwachzeit (time Objekt)
            alarm_entity: Entity-ID des Weckers (z.B. "sensor.pixel_next_alarm")
            weekend_offset_hours: Stunden später am Wochenende (NEU!)
            workday_sensor: Entity-ID für Arbeitstag-Erkennung (NEU!)
        """
        self.hass = hass
        self.mode = mode
        self.fixed_time = fixed_time or time(7, 0)  # Default: 07:00
        self.alarm_entity = alarm_entity
        
        # NEU: Wochenend-Einstellungen
        self.weekend_offset_hours = weekend_offset_hours
        self.workday_sensor = workday_sensor or "binary_sensor.workday"
        
        # Validierung
        if mode == "alarm_entity" and not alarm_entity:
            _LOGGER.warning(
                "Modus 'alarm_entity' gewählt, aber keine Entity angegeben. "
                "Fallback auf 'fixed_time'."
            )
            self.mode = "fixed_time"
    
    def resolve(self) -> Tuple[time, str]:
        """
        Ermittelt die aktuelle Aufwachzeit.
        
        Returns:
            (wake_time, source) - Tuple mit Zeit und Quelle-Beschreibung
        """
        # Basis-Zeit ermitteln
        if self.mode == "fixed_time":
            base_time, source = self._resolve_fixed()
        elif self.mode == "alarm_entity":
            base_time, source = self._resolve_alarm()
        elif self.mode == "hybrid":
            base_time, source = self._resolve_hybrid()
        else:
            _LOGGER.error(f"Unbekannter Modus: {self.mode}. Fallback auf fixed_time.")
            base_time, source = self._resolve_fixed()
        
        # NEU: Wochenend-Offset anwenden
        if self.weekend_offset_hours > 0 and self._is_weekend_or_holiday():
            adjusted_time = self._apply_time_offset(base_time, self.weekend_offset_hours)
            return adjusted_time, f"{source} + Wochenende (+{self.weekend_offset_hours}h)"
        
        return base_time, source
    
    def _is_weekend_or_holiday(self) -> bool:
        """
        Prüft, ob heute ein freier Tag ist.
        
        Nutzt binary_sensor.workday wenn verfügbar.
        Fallback: Samstag/Sonntag erkennen.
        """
        # Versuche workday Sensor
        workday_state = self.hass.states.get(self.workday_sensor)
        
        if workday_state and workday_state.state not in ["unknown", "unavailable"]:
            is_workday = workday_state.state == "on"
            return not is_workday
        
        # Fallback: Wochentag prüfen (5 = Samstag, 6 = Sonntag)
        today = local_now().weekday()
        return today >= 5
    
    def _apply_time_offset(self, base_time: time, offset_hours: float) -> time:
        """
        Addiert Stunden zu einer Zeit.
        
        Args:
            base_time: Ausgangszeit
            offset_hours: Stunden hinzuzufügen
        
        Returns:
            Neue Zeit (mit Überlauf auf nächsten Tag wenn nötig)
        """
        base_dt = datetime.combine(local_now().date(), base_time)
        adjusted_dt = base_dt + timedelta(hours=offset_hours)
        return adjusted_dt.time()
    
    def _resolve_fixed(self) -> Tuple[time, str]:
        """Gibt die fest konfigurierte Zeit zurück."""
        return self.fixed_time, "Feste Zeit"
    
    def _resolve_alarm(self) -> Tuple[time, str]:
        """
        Liest die Aufwachzeit aus einer HA-Alarm-Entity.
        
        Bei Fehler: Fallback auf fixed_time!
        """
        alarm_time = self._read_alarm_entity()
        
        if alarm_time:
            return alarm_time, f"Wecker ({self.alarm_entity})"
        
        # Fallback
        _LOGGER.warning(
            f"Konnte Wecker-Zeit von '{self.alarm_entity}' nicht lesen. "
            "Verwende feste Zeit als Fallback."
        )
        return self.fixed_time, "Feste Zeit (Wecker-Fallback)"
    
    def _resolve_hybrid(self) -> Tuple[time, str]:
        """
        Hybrid-Logik: Versucht zuerst Alarm, dann Fallback.
        
        Dies ist der empfohlene Modus!
        """
        if not self.alarm_entity:
            return self._resolve_fixed()
        
        alarm_time = self._read_alarm_entity()
        
        if alarm_time:
            return alarm_time, f"Wecker ({self.alarm_entity})"
        
        # Silent Fallback (kein Warning, da Hybrid erwartet wird)
        return self.fixed_time, "Feste Zeit"
    
    def _read_alarm_entity(self) -> Optional[time]:
        """
        Liest die Zeit aus verschiedenen Alarm-Entity-Typen.
        
        Unterstützt:
        - sensor.next_alarm (ISO timestamp als state)
        - input_datetime (time oder datetime)
        
        Returns:
            time Objekt oder None bei Fehler
        """
        if not self.alarm_entity:
            return None
        
        state = self.hass.states.get(self.alarm_entity)
        
        if not state:
            _LOGGER.debug(f"Entity '{self.alarm_entity}' existiert nicht.")
            return None
        
        if state.state in ["unknown", "unavailable", "none", "None"]:
            _LOGGER.debug(f"Entity '{self.alarm_entity}' ist {state.state}.")
            return None
        
        # Typ-spezifisches Parsing
        domain = self.alarm_entity.split(".")[0]
        
        if domain == "sensor":
            return self._parse_sensor_alarm(state)
        
        elif domain == "input_datetime":
            return self._parse_input_datetime(state)
        
        else:
            _LOGGER.warning(
                f"Alarm-Entity-Typ '{domain}' wird noch nicht unterstützt. "
                "Bitte melde dies als Feature-Request!"
            )
            return None
    
    def _parse_sensor_alarm(self, state: State) -> Optional[time]:
        """
        Parst sensor.next_alarm.
        
        Companion App liefert meist ISO 8601 Timestamps wie:
        "2026-01-30T06:30:00+01:00"
        """
        try:
            # Versuche ISO Timestamp zu parsen
            alarm_dt = dt_util.parse_datetime(state.state)
            
            if alarm_dt:
                # Konvertiere zu lokaler Zeit
                alarm_dt = dt_util.as_local(alarm_dt)
                return alarm_dt.time()
            
            # Alternativ: Manchmal nur Zeit ohne Datum
            alarm_time = dt_util.parse_time(state.state)
            if alarm_time:
                return alarm_time
            
            _LOGGER.warning(
                f"Konnte Zeitformat von '{state.state}' nicht parsen. "
                "Erwartet: ISO Timestamp oder HH:MM."
            )
            return None
        
        except Exception as e:
            _LOGGER.error(f"Fehler beim Parsen von sensor.next_alarm: {e}")
            return None
    
    def _parse_input_datetime(self, state: State) -> Optional[time]:
        """
        Parst input_datetime.
        
        Kann datetime oder nur time sein.
        """
        try:
            # Versuche als datetime
            dt = dt_util.parse_datetime(state.state)
            if dt:
                return dt.time()
            
            # Versuche als reine Zeit
            t = dt_util.parse_time(state.state)
            if t:
                return t
            
            _LOGGER.warning(
                f"Konnte input_datetime '{state.state}' nicht parsen."
            )
            return None
        
        except Exception as e:
            _LOGGER.error(f"Fehler beim Parsen von input_datetime: {e}")
            return None
    
    def get_diagnostics(self) -> dict:
        """
        Gibt Debug-Informationen zurück.
        
        Nützlich für Troubleshooting und UI-Anzeigen.
        """
        wake_time, source = self.resolve()
        
        diag = {
            "mode": self.mode,
            "effective_wake_time": wake_time.strftime("%H:%M"),
            "source": source,
            "fixed_time": self.fixed_time.strftime("%H:%M"),
            "alarm_entity": self.alarm_entity or "Nicht konfiguriert",
            "weekend_offset_hours": self.weekend_offset_hours,
            "is_weekend_or_holiday": self._is_weekend_or_holiday(),
            "workday_sensor": self.workday_sensor,
        }
        
        # Zusätzliche Infos, wenn Alarm-Entity konfiguriert ist
        if self.alarm_entity:
            state = self.hass.states.get(self.alarm_entity)
            
            if state:
                diag["alarm_state"] = state.state
                diag["alarm_available"] = state.state not in ["unknown", "unavailable"]
            else:
                diag["alarm_state"] = "Entity existiert nicht"
                diag["alarm_available"] = False
        
        # Workday Sensor Status
        workday_state = self.hass.states.get(self.workday_sensor)
        if workday_state:
            diag["workday_state"] = workday_state.state
        
        return diag


# ============================================================================
# STANDALONE-TEST (Mock für Testing ohne HA)
# ============================================================================

if __name__ == "__main__":
    """
    Test-Modus: Zeigt Resolver-Logik.
    
    HINWEIS: Funktioniert nur in echter HA-Umgebung.
    Hier nur zur Code-Veranschaulichung.
    """
    print("=" * 60)
    print("Wake-Time-Resolver Demo")
    print("=" * 60)
    print("\nDieser Test benötigt eine laufende Home Assistant Instanz.")
    print("In echter Nutzung würde hier die Aufwachzeit ermittelt werden.")
    print("\nBeispiel-Szenarien:")
    print("- Fixed Time: Immer 07:00")
    print("- Alarm Entity: Liest sensor.pixel_next_alarm")
    print("- Hybrid: Wecker falls verfügbar, sonst 07:00")
    print("\n" + "=" * 60)
