"""
Climate-Plattform für das Rejuvenation Bed.

HVAC-Modi:
- OFF: Komplett aus
- AUTO: Idle (Eco/Solar-Batterie, Bett leer)
- HEAT: Biorhythmus (Kurve aktiv, Präsenz erkannt)
- DRY: Krank-Modus (konstant warm, 3 Tage)

Presets:
- NONE: Normal
- AWAY: Urlaub (Frostschutz)
- COMFORT: Ausschlafen (verlängerte Kurve)
- BOOST: Schnellheizen
"""

import logging
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
    HVACAction,
    PRESET_NONE,
    PRESET_AWAY,
    PRESET_COMFORT,
    PRESET_BOOST,
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    UnitOfTemperature,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo
from .const import DOMAIN, ABSOLUTE_MAX_TEMP, MANUFACTURER, SW_VERSION

_LOGGER = logging.getLogger(__name__)


def get_device_info(coordinator) -> DeviceInfo:
    """Hauptgerät (Mono) oder Container-Gerät (Dual)."""
    global_conf = coordinator.config_entry.data.get("global", {})
    bed_type = global_conf.get("bed_type", "wasserbett")
    zones_count = len(coordinator.config_entry.data.get("zones", []))
    
    model = "Smart Wasserbett Controller" if bed_type == "wasserbett" else "Smart Heizmatte Controller"
    zone_suffix = "Dual-Zone" if zones_count > 1 else "Mono"
    
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
        manufacturer=MANUFACTURER,
        model=f"{model} ({zone_suffix})",
        name="Rejuvenation Bed",
        sw_version=SW_VERSION,
    )


def get_zone_device_info(coordinator, zone_index: int) -> DeviceInfo:
    """Zone-Gerät für Dual-Bett (Links/Rechts)."""
    zones_count = len(coordinator.config_entry.data.get('zones', []))
    if zones_count <= 1:
        return get_device_info(coordinator)
    zone_name = 'Links' if zone_index == 0 else 'Rechts'
    return DeviceInfo(
        identifiers={(DOMAIN, f'{coordinator.config_entry.entry_id}_zone_{zone_index}')},
        manufacturer=MANUFACTURER,
        model=f'Bett-Zone {zone_name}',
        name=f'Bett {zone_name}',
        sw_version=SW_VERSION,
        via_device=(DOMAIN, coordinator.config_entry.entry_id),
    )


async def async_setup_entry(hass, entry, async_add_entities):
    """Richtet die Thermostate für das Rejuvenation Bed ein."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    zones_config = entry.data.get("zones", [])
    is_dual_zone = len(zones_config) > 1

    entities = []
    for index, zone_config in enumerate(zones_config):
        # Namens-Suffix für Links/Rechts
        if not is_dual_zone:
            display_name = ""
        else:
            suffix = zone_config.get("name", f"{index + 1}")
            display_name = f" {suffix}"

        entities.append(RejuvenationBedClimate(coordinator, index, display_name))

    async_add_entities(entities)


class RejuvenationBedClimate(CoordinatorEntity, ClimateEntity):
    """Thermostat-Interface für eine Bett-Zone."""

    _attr_has_entity_name = True
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    
    # ERWEITERT: Mehr HVAC-Modi!
    _attr_hvac_modes = [
        HVACMode.OFF,
        HVACMode.AUTO,
        HVACMode.HEAT,
        HVACMode.DRY,
    ]
    
    # ERWEITERT: Presets!
    _attr_preset_modes = [
        PRESET_NONE,
        PRESET_AWAY,
        PRESET_COMFORT,
        PRESET_BOOST,
    ]
    
    # Grenzwerte
    _attr_min_temp = 24.0
    _attr_max_temp = ABSOLUTE_MAX_TEMP
    _attr_target_temperature_step = 0.1  # NEU: 0.1°C Schritte!
    
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | 
        ClimateEntityFeature.TURN_ON | 
        ClimateEntityFeature.TURN_OFF |
        ClimateEntityFeature.PRESET_MODE
    )

    def __init__(self, coordinator, zone_index, display_name):
        """Initialisiert das Climate Entity."""
        super().__init__(coordinator)
        self._zone_idx = zone_index
        self._attr_name = f"Thermostat{display_name}"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_zone{zone_index}_climate"
        self._attr_device_info = get_zone_device_info(coordinator, zone_index)
        
        # Min-Temp aus Bed-Config (Heizmatte: 0°C, Wasserbett: 24°C)
        self._attr_min_temp = coordinator.bed_config.get("min_temp", 24.0)
        
        # Ermittle Hardware-Level
        zones_config = coordinator.config_entry.data.get("zones", [])
        if zone_index < len(zones_config):
            zone_conf = zones_config[zone_index]
            self._hardware_level = self._detect_hardware_level(zone_conf)
        else:
            self._hardware_level = "A"
        
        # Passe verfügbare Modi an Hardware an
        self._adjust_modes_for_hardware()

    def _detect_hardware_level(self, zone_conf) -> str:
        """
        Erkennt Hardware-Level: A/B/C
        """
        has_temp = zone_conf.get("temp_sensor") is not None
        has_power = zone_conf.get("power_sensor") is not None
        
        if has_temp:
            return "C"  # Vollausstattung
        elif has_power:
            return "B"  # Smart
        else:
            return "A"  # Basic
    
    def _adjust_modes_for_hardware(self):
        """Passt Modi an Hardware an."""
        if self._hardware_level == "A":
            self._attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
            self._attr_preset_modes = [PRESET_NONE, PRESET_BOOST]
        elif self._hardware_level == "B":
            self._attr_hvac_modes = [HVACMode.OFF, HVACMode.AUTO, HVACMode.HEAT]
            self._attr_preset_modes = [PRESET_NONE, PRESET_AWAY, PRESET_BOOST]

    @property
    def hvac_mode(self) -> HVACMode:
        """Aktueller HVAC-Modus."""
        data = self.coordinator.data
        if not data or "zones" not in data:
            return HVACMode.OFF
        
        zone_name = f"Zone {self._zone_idx + 1}"
        zone_data = data["zones"].get(zone_name, {})
        
        return zone_data.get("hvac_mode", HVACMode.OFF)

    @property
    def hvac_action(self) -> HVACAction:
        """Aktuelle Aktion."""
        data = self.coordinator.data
        if not data or "zones" not in data:
            return HVACAction.OFF
        
        zone_name = f"Zone {self._zone_idx + 1}"
        zone_data = data["zones"].get(zone_name, {})
        
        if zone_data.get("active", False):
            return HVACAction.HEATING
        else:
            return HVACAction.IDLE

    @property
    def current_temperature(self) -> float | None:
        """Aktuelle Temperatur."""
        data = self.coordinator.data
        if not data or "zones" not in data:
            return None
        
        zone_name = f"Zone {self._zone_idx + 1}"
        zone_data = data["zones"].get(zone_name, {})
        
        current = zone_data.get("current")
        if current == "unknown":
            return None
        return current

    @property
    def target_temperature(self) -> float | None:
        """Zieltemperatur."""
        data = self.coordinator.data
        if not data or "zones" not in data:
            return None
        
        zone_name = f"Zone {self._zone_idx + 1}"
        zone_data = data["zones"].get(zone_name, {})
        
        return zone_data.get("target")

    @property
    def preset_mode(self) -> str:
        """Aktueller Preset."""
        data = self.coordinator.data
        if not data or "zones" not in data:
            return PRESET_NONE
        
        zone_name = f"Zone {self._zone_idx + 1}"
        zone_data = data["zones"].get(zone_name, {})
        
        return zone_data.get("preset_mode", PRESET_NONE)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode):
        """Setzt HVAC-Modus."""
        _LOGGER.info(f"Zone {self._zone_idx}: HVAC → {hvac_mode}")
        
        if not hasattr(self.coordinator, "manual_hvac_mode"):
            self.coordinator.manual_hvac_mode = {}
        
        self.coordinator.manual_hvac_mode[self._zone_idx] = hvac_mode
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs):
        """Setzt Zieltemperatur."""
        if (temp := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        
        _LOGGER.info(f"Zone {self._zone_idx}: Temp → {temp}°C")
        
        if not hasattr(self.coordinator, "manual_target_temp"):
            self.coordinator.manual_target_temp = {}
        
        self.coordinator.manual_target_temp[self._zone_idx] = temp
        await self.coordinator.async_request_refresh()

    async def async_set_preset_mode(self, preset_mode: str):
        """Setzt Preset."""
        _LOGGER.info(f"Zone {self._zone_idx}: Preset → {preset_mode}")
        
        if not hasattr(self.coordinator, "manual_preset"):
            self.coordinator.manual_preset = {}
        
        self.coordinator.manual_preset[self._zone_idx] = preset_mode
        
        if preset_mode == PRESET_BOOST:
            if not hasattr(self.coordinator, "manual_boost"):
                self.coordinator.manual_boost = {}
            self.coordinator.manual_boost[self._zone_idx] = True
        
        await self.coordinator.async_request_refresh()

    @property
    def extra_state_attributes(self):
        """Zusätzliche Attribute."""
        data = self.coordinator.data
        if not data or "zones" not in data:
            return {}
        
        zone_name = f"Zone {self._zone_idx + 1}"
        zone_data = data["zones"].get(zone_name, {})
        
        attrs = {
            "hardware_level": self._hardware_level,
            "reason": zone_data.get("reason", ""),
        }
        
        if self._hardware_level == "C":
            attrs["presence_detected"] = zone_data.get("is_present", False)
            attrs["presence_confidence"] = zone_data.get("presence_confidence", 0.0)
        
        return attrs
