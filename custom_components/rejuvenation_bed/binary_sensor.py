import logging
from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN, BED_TYPE_WATERBED
from .device_info import (
    get_zone_device_info,
    get_sleep_device_info,
)

_LOGGER = logging.getLogger(__name__)



async def async_setup_entry(hass, config_entry, async_add_entities):
    """Setze die binären Sensoren basierend auf der Zonen-Konfiguration auf."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    entities = []
    zones_config = config_entry.data.get("zones", [])
    global_conf = config_entry.data.get("global", {})
    
    # Bett-Typ prüfen
    bed_type = global_conf.get("bed_type", BED_TYPE_WATERBED)
    is_waterbed = bed_type == BED_TYPE_WATERBED
    
    is_dual_zone = len(zones_config) > 1
    
    # Prüfen ob mindestens ein Temperatur-Sensor konfiguriert ist
    has_any_temp_sensor = any(zone.get("temp_sensor") for zone in zones_config)

    for zone_idx, zone_config in enumerate(zones_config):
        suffix = ""
        if is_dual_zone:
            suffix = " Links" if zone_idx == 0 else " Rechts"

        # Feuchtigkeits-Sensoren nur wenn:
        # 1. Ein Feuchtigkeitssensor konfiguriert wurde UND
        # 2. Es sich um ein Wasserbett handelt (Heizmatte hat kein Leckage-Risiko)
        if zone_config.get("moisture_sensor"):
            # 1. Schwitzerkennung (reagiert sofort) - für beide Typen relevant
            entities.append(BedMoistureSensor(
                coordinator, zone_idx, suffix, "Schwitzerkennung", "is_sweating", BinarySensorDeviceClass.MOISTURE
            ))
            
            # 2. Leckage-Verdacht - NUR für Wasserbett!
            if is_waterbed:
                entities.append(BedMoistureSensor(
                    coordinator, zone_idx, suffix, "Leckage-Verdacht", "is_leaking", BinarySensorDeviceClass.PROBLEM
                ))
        
        # 3. Präsenz-Erkennung (immer verfügbar - nutzt Sensor-Fusion!)
        entities.append(BedPresenceSensor(coordinator, zone_idx, suffix))

    # 3. Globaler System-Status (Watchdog)
    entities.append(BedWatchdogSensor(coordinator))
    
    # 4. Degraded Mode Sensor (NEU!)
    entities.append(BedDegradedModeSensor(coordinator))
    
    # 5. Kondensations-Warnung - NUR für Wasserbett UND nur wenn Temp-Sensor vorhanden!
    if is_waterbed and has_any_temp_sensor:
        entities.append(BedCondensationRiskSensor(coordinator))
    
    # 6. Isolations-Erkennung (Decken-Check) - nur Wasserbett, pro Zone
    if is_waterbed:
        for zone_idx, zone_config in enumerate(zones_config):
            suffix = ""
            if is_dual_zone:
                suffix = " Links" if zone_idx == 0 else " Rechts"
            entities.append(BedIsolationSensor(coordinator, zone_idx, suffix))

    async_add_entities(entities)

class BedMoistureSensor(CoordinatorEntity, BinarySensorEntity):
    """Sensor für Feuchtigkeits-Events (Schwitzen oder Leck)."""
    
    def __init__(self, coordinator, zone_idx, suffix, name_type, data_key, device_class):
        super().__init__(coordinator)
        self._zone_idx = zone_idx
        self._zone_name = f"Zone {zone_idx + 1}"
        self._data_key = data_key
        self._attr_name = f"Bett{suffix} {name_type}"
        self._attr_device_class = device_class
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_z{zone_idx}_{data_key}"
        self._attr_device_info = get_sleep_device_info(coordinator)
        
        # Icon-Anpassung für Schwitzen
        if data_key == "is_sweating":
            self._attr_icon = "mdi:water-percent"

    @property
    def is_on(self) -> bool:
        """Holt den spezifischen Status aus dem Coordinator."""
        data = self.coordinator.data
        if data and "zones" in data:
            return data["zones"].get(self._zone_name, {}).get(self._data_key, False)
        return False

class BedWatchdogSensor(CoordinatorEntity, BinarySensorEntity):
    """Überwacht die allgemeine System-Gesundheit (Offline/Fehler)."""
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Bett System-Status"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_watchdog"
        self._attr_device_info = get_sleep_device_info(coordinator)

    @property
    def is_on(self) -> bool:
        """True, wenn der Coordinator keine Daten liefert oder ein kritischer Fehler vorliegt."""
        if not self.coordinator.last_update_success:
            return True
            
        # Überhitzungsschutz-Check
        data = self.coordinator.data
        if data and data.get("global_state", {}).get("status") == "EMERGENCY_SHUTDOWN":
            return True
            
        return False

    @property
    def extra_state_attributes(self):
        """Zusätzliche Diagnose-Infos."""
        data = self.coordinator.data
        # FIX: last_update_success_time existiert nicht im Standard-Coordinator. 
        # Wir nutzen last_update_success (boolean).
        attrs = {"last_update_successful": self.coordinator.last_update_success}
        
        if data:
            # FIX: Pfad korrigiert auf data["global_state"]["energy"]["total_power"]
            global_state = data.get("global_state", {})
            energy = global_state.get("energy", {})
            total_power = energy.get("total_power", 0)
            attrs["total_power"] = f"{total_power} W"
            
            if "reason" in global_state:
                attrs["error_reason"] = global_state["reason"]
                
        return attrs


class BedDegradedModeSensor(CoordinatorEntity, BinarySensorEntity):
    """Zeigt an, ob das System im Degraded Mode läuft (Sensor-Ausfall)."""
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:alert-circle"
    
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Bett Degraded Mode"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_degraded_mode"
        self._attr_device_info = get_sleep_device_info(coordinator)

    @property
    def is_on(self) -> bool:
        """True, wenn System im Degraded Mode läuft."""
        data = self.coordinator.data
        if data:
            status = data.get("global_state", {}).get("status")
            return status == "DEGRADED_MODE"
        return False

    @property
    def extra_state_attributes(self):
        """Zeigt Details zum Degraded Mode."""
        data = self.coordinator.data
        if not data:
            return {}
        
        attrs = {}
        
        if self.is_on:
            global_state = data.get("global_state", {})
            attrs["reason"] = global_state.get("degraded_reason", "Unbekannt")
            attrs["duty_cycle"] = "30%"
            attrs["cycle_time"] = "10 Minuten (3 Min AN, 7 Min AUS)"
            attrs["info"] = (
                "Sensor ausgefallen - System hält Bett warm mit "
                "reduzierter Leistung. Sensor prüfen!"
            )
        
        return attrs


class BedPresenceSensor(CoordinatorEntity, BinarySensorEntity):
    """Erkennt Präsenz im Bett durch Sensor-Fusion (OHNE dedizierten Sensor!)."""
    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    _attr_icon = "mdi:bed"
    
    def __init__(self, coordinator, zone_idx, suffix):
        super().__init__(coordinator)
        self._zone_idx = zone_idx
        self._zone_name = f"Zone {zone_idx + 1}"
        self._attr_name = f"Bett{suffix} Präsenz"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_z{zone_idx}_presence"
        self._attr_device_info = get_zone_device_info(coordinator, zone_idx)

    @property
    def is_on(self) -> bool:
        """True, wenn Person im Bett erkannt wurde."""
        data = self.coordinator.data
        if data and "zones" in data:
            return data["zones"].get(self._zone_name, {}).get("is_present", False)
        return False

    @property
    def extra_state_attributes(self):
        """Zeigt Details zur Präsenz-Erkennung."""
        data = self.coordinator.data
        if not data or "zones" not in data:
            return {}
        
        zone_data = data["zones"].get(self._zone_name, {})
        
        return {
            "confidence": zone_data.get("presence_confidence", 0.0),
            "detection_method": zone_data.get("presence_reason", "Unbekannt"),
            "info": (
                "Sensor-Fusion: Kombiniert Heizverhalten, "
                "Temperatur-Trend und optionale Sensoren"
            )
        }


class BedCondensationRiskSensor(CoordinatorEntity, BinarySensorEntity):
    """
    Warnt vor Kondensationsrisiko bei Wasserbetten.
    
    Wird aktiv wenn:
    - Temperatur unter 24°C sinkt
    - Raumluftfeuchtigkeit hoch ist (wenn Sensor verfügbar)
    
    NUR für Wasserbetten relevant!
    """
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:water-alert"
    
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Bett Kondensationsrisiko"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_condensation_risk"
        self._attr_device_info = get_sleep_device_info(coordinator)

    @property
    def is_on(self) -> bool:
        """True, wenn Kondensationsrisiko besteht."""
        data = self.coordinator.data
        if not data or "zones" not in data:
            return False
        
        # Prüfe alle Zonen auf zu niedrige Temperatur
        for zone_name, zone_data in data.get("zones", {}).items():
            current_temp = zone_data.get("current")
            if isinstance(current_temp, (int, float)) and current_temp < 24.0:
                return True
        
        return False

    @property
    def extra_state_attributes(self):
        """Zeigt Details zum Kondensationsrisiko."""
        data = self.coordinator.data
        if not data:
            return {}
        
        attrs = {
            "min_safe_temp": "24°C",
            "info": (
                "Wasserbetten sollten nie unter 24°C abkühlen, "
                "da sonst Kondenswasser zwischen Vinyl und Bezug entstehen kann. "
                "Dies führt zu Schimmelbildung und Materialschäden!"
            )
        }
        
        # Finde niedrigste Temperatur
        lowest_temp = None
        for zone_name, zone_data in data.get("zones", {}).items():
            current_temp = zone_data.get("current")
            if isinstance(current_temp, (int, float)):
                if lowest_temp is None or current_temp < lowest_temp:
                    lowest_temp = current_temp
        
        if lowest_temp is not None:
            attrs["current_lowest_temp"] = f"{lowest_temp:.1f}°C"
            if lowest_temp < 24.0:
                attrs["warning"] = f"⚠️ Temperatur {lowest_temp:.1f}°C ist unter dem Minimum von 24°C!"
        
        return attrs


class BedIsolationSensor(CoordinatorEntity, BinarySensorEntity):
    """
    Isolations-Erkennung (Decken-Check).
    
    ON = Bett offen/schlecht isoliert (Wärme verpufft)
    OFF = Bett zugedeckt (gut isoliert)
    
    Funktioniert nur wenn SHT41 (Luft-Temp oben) vorhanden ist.
    Ohne SHT41 zeigt der Sensor "unbekannt" an.
    """
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:blanket"

    def __init__(self, coordinator, zone_idx, suffix):
        super().__init__(coordinator)
        self._zone_idx = zone_idx
        self._zone_name = f"Zone {zone_idx + 1}"
        self._attr_name = f"Bett{suffix} Isolation"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_z{zone_idx}_isolation"
        self._attr_device_info = get_zone_device_info(coordinator, zone_idx)

    @property
    def is_on(self) -> bool:
        """ON = Problem (Bett offen), OFF = OK (zugedeckt)."""
        iso = self.coordinator.bed_intelligence.get_isolation_status(self._zone_idx)
        return not iso.is_covered

    @property
    def available(self) -> bool:
        """Nur verfügbar wenn SHT41 Luft-Temp Sensor vorhanden."""
        return self.coordinator.bed_intelligence._has_air_temp.get(
            self._zone_idx, False
        )

    @property
    def extra_state_attributes(self):
        iso = self.coordinator.bed_intelligence.get_isolation_status(self._zone_idx)
        return {
            "level": iso.level,
            "delta_water_air": f"{iso.delta_water_air:.1f}°C",
            "uncovered_minutes": round(iso.uncovered_minutes, 0),
            "energy_waste_warning": iso.energy_waste_warning,
        }