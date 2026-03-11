"""
Ramp Controller für das Rejuvenation Bed.

Schützt das Vinyl durch sanfte Temperaturänderungen:
- Max. 1°C/h Änderung (schont Schweißnähte)
- Keine harten Sprünge
- Berechnet realistische Vorheizzeiten

PERSISTENT STATE: Überlebt HA-Neustarts!

Physikalische Grundlagen:
- Wasser: 1 kWh ≈ +0.86°C pro 1000L
- Typisches Doppelbett: 650-750L
- 300W Heizung: ~0.7°C/h (mit Verlusten)
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any
from dataclasses import dataclass, asdict

from .const import (
    MAX_TEMP_CHANGE_PER_HOUR,
    TYPICAL_HEATING_RATE,
    PREHEAT_BUFFER_HOURS,
    ABSOLUTE_MIN_TEMP,
    SOLAR_BOOST_MAX_TEMP,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class RampState:
    """Aktueller Zustand einer Temperatur-Rampe."""
    target_temp: float
    current_setpoint: float  # Aktuell angestrebte Temp (kann != target sein)
    ramp_active: bool
    ramp_direction: str  # "heating", "cooling", "stable"
    estimated_completion: Optional[datetime]
    reason: str


class RampController:
    """
    Kontrolliert Temperaturänderungen um das Material zu schonen.
    
    Statt:
        Setpoint: 26°C → 29°C (sofort)
    
    Mit RampController:
        Setpoint: 26°C → 27°C (nach 1h) → 28°C (nach 2h) → 29°C (nach 3h)
    
    Das Vinyl dehnt sich langsam aus/zusammen, Schweißnähte werden geschont.
    """
    
    def __init__(
        self,
        max_change_per_hour: float = MAX_TEMP_CHANGE_PER_HOUR,
        heating_rate: float = TYPICAL_HEATING_RATE,
    ):
        """
        Initialisiert den Ramp Controller.
        
        Args:
            max_change_per_hour: Max. erlaubte Änderung in °C/h
            heating_rate: Typische Aufheizrate in °C/h
        """
        self.max_change_per_hour = max_change_per_hour
        self.heating_rate = heating_rate
        
        # State pro Zone
        self._last_setpoint: dict[int, float] = {}
        self._last_update: dict[int, datetime] = {}
        self._target_temp: dict[int, float] = {}
        self._ramp_start: dict[int, datetime] = {}
    
    def calculate_ramped_setpoint(
        self,
        zone_index: int,
        desired_temp: float,
        current_temp: float,
    ) -> Tuple[float, RampState]:
        """
        Berechnet den nächsten Setpoint unter Berücksichtigung der max. Änderungsrate.
        
        Args:
            zone_index: Index der Zone
            desired_temp: Gewünschte Zieltemperatur
            current_temp: Aktuelle Ist-Temperatur
        
        Returns:
            (ramped_setpoint, RampState)
        """
        now = datetime.now()
        
        # Initialisierung beim ersten Aufruf
        if zone_index not in self._last_setpoint:
            self._last_setpoint[zone_index] = current_temp
            self._last_update[zone_index] = now
            self._target_temp[zone_index] = desired_temp
        
        last_setpoint = self._last_setpoint[zone_index]
        last_update = self._last_update[zone_index]
        
        # Zeit seit letztem Update
        elapsed_hours = (now - last_update).total_seconds() / 3600
        
        # Max. erlaubte Änderung basierend auf verstrichener Zeit
        max_change = self.max_change_per_hour * elapsed_hours
        
        # Differenz zum Ziel
        diff = desired_temp - last_setpoint
        
        # Rampe aktiv?
        if abs(diff) < 0.1:
            # Ziel erreicht
            new_setpoint = desired_temp
            ramp_active = False
            direction = "stable"
            completion = None
            reason = "Zieltemperatur erreicht"
        else:
            # Rampe nötig
            ramp_active = True
            
            if diff > 0:
                # Aufheizen → Rampe zum Vinyl-Schutz (max 1°C/h)
                direction = "heating"
                change = min(diff, max_change)
                new_setpoint = last_setpoint + change
                
                # Geschätzte Dauer
                remaining = desired_temp - new_setpoint
                hours_remaining = remaining / self.max_change_per_hour
                completion = now + timedelta(hours=hours_remaining)
                reason = f"Aufheizen: +{change:.1f}°C (max. {self.max_change_per_hour}°C/h)"
            else:
                # Abkühlen → SOFORT auf Zieltemperatur, keine Rampe nötig!
                # Das Wasser kühlt durch Wärmeverlust von selbst langsam ab.
                # Die Heizung schaltet einfach aus, das Vinyl wird nicht belastet.
                direction = "cooling"
                new_setpoint = desired_temp
                ramp_active = False
                completion = None
                reason = f"Abkühlen: Heizung aus (Δ{diff:.1f}°C)"
        
        # Sicherheitsgrenzen
        new_setpoint = max(ABSOLUTE_MIN_TEMP, min(SOLAR_BOOST_MAX_TEMP + 2, new_setpoint))
        
        # State aktualisieren
        self._last_setpoint[zone_index] = new_setpoint
        self._last_update[zone_index] = now
        self._target_temp[zone_index] = desired_temp
        
        if ramp_active and zone_index not in self._ramp_start:
            self._ramp_start[zone_index] = now
        elif not ramp_active and zone_index in self._ramp_start:
            # Rampe beendet
            duration = (now - self._ramp_start[zone_index]).total_seconds() / 60
            _LOGGER.info(
                f"Zone {zone_index}: Temperatur-Rampe abgeschlossen "
                f"({duration:.0f} Min, {last_setpoint:.1f}°C → {new_setpoint:.1f}°C)"
            )
            del self._ramp_start[zone_index]
        
        state = RampState(
            target_temp=desired_temp,
            current_setpoint=new_setpoint,
            ramp_active=ramp_active,
            ramp_direction=direction,
            estimated_completion=completion,
            reason=reason,
        )
        
        return new_setpoint, state
    
    def calculate_preheat_time(
        self,
        current_temp: float,
        target_temp: float,
        power_watts: float = 300,
        water_liters: float = 350,
    ) -> timedelta:
        """
        Berechnet die benötigte Vorheizzeit.
        
        Args:
            current_temp: Aktuelle Temperatur
            target_temp: Zieltemperatur
            power_watts: Heizleistung in Watt
            water_liters: Wassermenge in Litern
        
        Returns:
            timedelta mit geschätzter Vorheizzeit
        """
        temp_diff = target_temp - current_temp
        
        if temp_diff <= 0:
            return timedelta(0)
        
        # Physikalische Berechnung
        # 1 kWh erwärmt ~1000L um ~0.86°C
        # Also: 1 kWh erwärmt water_liters um (0.86 * 1000 / water_liters) °C
        kwh_per_degree = water_liters / (0.86 * 1000)  # kWh pro °C
        total_kwh_needed = temp_diff * kwh_per_degree
        
        # Zeit = Energie / Leistung (mit Verlustfaktor 0.85)
        efficiency = 0.85
        hours_needed = total_kwh_needed / (power_watts / 1000) / efficiency
        
        # Rampen-Begrenzung beachten
        ramp_limited_hours = temp_diff / self.max_change_per_hour
        
        # Das Maximum von beiden (physikalisch vs. Rampen-Limit)
        actual_hours = max(hours_needed, ramp_limited_hours)
        
        # Puffer hinzufügen
        actual_hours += PREHEAT_BUFFER_HOURS
        
        return timedelta(hours=actual_hours)
    
    def should_start_preheat(
        self,
        current_temp: float,
        target_temp: float,
        bedtime: datetime,
        power_watts: float = 300,
        water_liters: float = 350,
    ) -> Tuple[bool, str]:
        """
        Prüft ob jetzt mit dem Vorheizen begonnen werden sollte.
        
        Args:
            current_temp: Aktuelle Temperatur
            target_temp: Zieltemperatur zur Schlafzeit
            bedtime: Geplante Schlafzeit
            power_watts: Heizleistung
            water_liters: Wassermenge
        
        Returns:
            (should_start, reason)
        """
        now = datetime.now()
        
        # Wenn Schlafzeit schon vorbei, nicht vorheizen
        if now >= bedtime:
            return False, "Schlafzeit bereits erreicht"
        
        # Berechne benötigte Zeit
        preheat_time = self.calculate_preheat_time(
            current_temp, target_temp, power_watts, water_liters
        )
        
        # Wann müssen wir starten?
        start_time = bedtime - preheat_time
        
        if now >= start_time:
            minutes_until_bed = (bedtime - now).total_seconds() / 60
            return True, f"Vorheizen starten! {preheat_time.total_seconds()/60:.0f} Min nötig, noch {minutes_until_bed:.0f} Min bis Schlafzeit"
        else:
            minutes_until_start = (start_time - now).total_seconds() / 60
            return False, f"Vorheizen in {minutes_until_start:.0f} Min"
    
    def get_ramp_state(self, zone_index: int) -> Optional[RampState]:
        """Gibt den aktuellen Rampen-Status für eine Zone zurück."""
        if zone_index not in self._last_setpoint:
            return None
        
        target = self._target_temp.get(zone_index, self._last_setpoint[zone_index])
        current = self._last_setpoint[zone_index]
        
        diff = abs(target - current)
        
        if diff < 0.1:
            direction = "stable"
            ramp_active = False
        elif target > current:
            direction = "heating"
            ramp_active = True
        else:
            direction = "cooling"
            ramp_active = True
        
        return RampState(
            target_temp=target,
            current_setpoint=current,
            ramp_active=ramp_active,
            ramp_direction=direction,
            estimated_completion=None,
            reason=f"{'Rampe aktiv' if ramp_active else 'Stabil'}: {current:.1f}°C → {target:.1f}°C"
        )
    
    def force_setpoint(self, zone_index: int, temp: float):
        """
        Erzwingt einen Setpoint ohne Rampe (für Notfälle).
        
        Sollte nur bei Sicherheits-Events verwendet werden!
        """
        _LOGGER.warning(
            f"Zone {zone_index}: Setpoint erzwungen auf {temp}°C (Rampe übersprungen!)"
        )
        self._last_setpoint[zone_index] = temp
        self._last_update[zone_index] = datetime.now()
        self._target_temp[zone_index] = temp
    
    # ═══════════════════════════════════════════════════════════════════════════
    # PERSISTENT STATE (überlebt HA-Neustarts)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def get_state_for_storage(self) -> Dict[str, Any]:
        """
        Exportiert den aktuellen State für persistente Speicherung.
        
        Wird vom DiagnosticsManager aufgerufen.
        """
        return {
            "last_setpoint": {str(k): v for k, v in self._last_setpoint.items()},
            "target_temp": {str(k): v for k, v in self._target_temp.items()},
            "last_update": {
                str(k): v.isoformat() for k, v in self._last_update.items()
            },
            "ramp_start": {
                str(k): v.isoformat() for k, v in self._ramp_start.items()
            },
            "saved_at": datetime.now().isoformat(),
        }
    
    def restore_state_from_storage(self, data: Dict[str, Any]):
        """
        Stellt den State nach einem HA-Neustart wieder her.
        
        Wird beim Start vom DiagnosticsManager aufgerufen.
        """
        if not data:
            return
        
        try:
            # Zeitpunkt der Speicherung prüfen
            saved_at_str = data.get("saved_at")
            if saved_at_str:
                saved_at = datetime.fromisoformat(saved_at_str)
                age_minutes = (datetime.now() - saved_at).total_seconds() / 60
                
                if age_minutes > 30:
                    # Daten zu alt - ignorieren
                    _LOGGER.info(
                        f"RampController: Gespeicherter State ist {age_minutes:.0f} Min alt, "
                        "wird ignoriert (>30 Min)"
                    )
                    return
            
            # State wiederherstellen
            for key, value in data.get("last_setpoint", {}).items():
                self._last_setpoint[int(key)] = float(value)
            
            for key, value in data.get("target_temp", {}).items():
                self._target_temp[int(key)] = float(value)
            
            for key, value in data.get("last_update", {}).items():
                self._last_update[int(key)] = datetime.fromisoformat(value)
            
            for key, value in data.get("ramp_start", {}).items():
                self._ramp_start[int(key)] = datetime.fromisoformat(value)
            
            _LOGGER.info(
                f"RampController: State wiederhergestellt "
                f"({len(self._last_setpoint)} Zonen)"
            )
            
        except Exception as e:
            _LOGGER.warning(f"RampController: Fehler beim Wiederherstellen: {e}")
