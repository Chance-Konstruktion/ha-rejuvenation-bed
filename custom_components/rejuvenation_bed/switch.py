"""
Schalter für das Rejuvenation Bed.

Bietet verschiedene Modi:
- Schnellheizen (Boost)
- Krank-Modus
- Solar-Batterie
- Eco-Modus
- Urlaub-Modus

WICHTIG: Diese Schalter setzen Flags im Coordinator, die dann
von der Temperatur-Berechnung ausgewertet werden müssen!
"""

import logging
from datetime import timedelta
from homeassistant.components.switch import SwitchEntity, SwitchDeviceClass
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo
from .const import (
    DOMAIN, 
    DEFAULT_SICK_MODE_TEMP, 
    DEFAULT_SICK_MODE_DAYS, 
    MANUFACTURER, 
    SW_VERSION, 
    BED_TYPE_WATERBED,
    local_now,
)

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





def get_energy_device_info(coordinator) -> DeviceInfo:
    """Energie-Gerät: Verbrauch, Solar, Ersparnis, Batterie."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"{coordinator.config_entry.entry_id}_energy")},
        manufacturer=MANUFACTURER,
        model="Energie & Ersparnis",
        name="Bett Energie",
        sw_version=SW_VERSION,
        via_device=(DOMAIN, coordinator.config_entry.entry_id),
    )



async def async_setup_entry(hass, entry, async_add_entities):
    """Richtet die Schalter für das Rejuvenation Bed ein."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    zones_config = entry.data.get("zones", [])
    global_conf = entry.data.get("global", {})
    is_dual_zone = len(zones_config) > 1
    
    # Bett-Typ prüfen
    bed_type = global_conf.get("bed_type", BED_TYPE_WATERBED)
    is_waterbed = bed_type == BED_TYPE_WATERBED

    # ═══════════════════════════════════════════════════════════════════════
    # Initialisiere ALLE benötigten Attribute im Coordinator
    # Das verhindert AttributeError später!
    # ═══════════════════════════════════════════════════════════════════════
    if not hasattr(coordinator, "manual_boost"):
        coordinator.manual_boost = {}
    if not hasattr(coordinator, "boost_until"):
        coordinator.boost_until = {}
    if not hasattr(coordinator, "sick_mode_until"):
        coordinator.sick_mode_until = {}
    if not hasattr(coordinator, "sick_mode_temp"):
        coordinator.sick_mode_temp = {}
    if not hasattr(coordinator, "thermal_battery_enabled"):
        coordinator.thermal_battery_enabled = True
    if not hasattr(coordinator, "eco_mode_enabled"):
        coordinator.eco_mode_enabled = False
    if not hasattr(coordinator, "vacation_mode_enabled"):
        coordinator.vacation_mode_enabled = False
    if not hasattr(coordinator, "vacation_until"):
        coordinator.vacation_until = None

    entities = []
    for index, zone_config in enumerate(zones_config):
        # Namens-Suffix für Links/Rechts oder Zone 1/2
        if is_dual_zone:
            suffix = " Links" if index == 0 else " Rechts"
        else:
            suffix = ""
        
        # Schnellheizen für alle Bett-Typen
        entities.append(BedBoostSwitch(coordinator, index, suffix))
        
        # Krank-Modus für alle Bett-Typen (nicht nur Level C!)
        entities.append(BedSickModeSwitch(coordinator, index, suffix))
    
    # Solar-Batterie-Modus NUR für Wasserbett (macht bei Heizmatte keinen Sinn)
    if is_waterbed:
        entities.append(BedThermalBatterySwitch(coordinator))
    
    # Tarifmodus NUR wenn Strompreis-Sensor konfiguriert ist
    if entry.options.get("price_sensor") or global_conf.get("price_sensor"):
        entities.append(BedTariffModeSwitch(coordinator, is_waterbed))
    
    # Urlaub-Modus für alle Typen
    entities.append(BedVacationModeSwitch(coordinator, is_waterbed))

    async_add_entities(entities)


class BedBoostSwitch(CoordinatorEntity, SwitchEntity):
    """
    Schnellheizen-Schalter.
    
    Aktiviert Boost-Temperatur für schnelles Aufwärmen vor dem Schlafengehen.
    """
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:fire"

    def __init__(self, coordinator, zone_index, suffix):
        """Initialisiere den Schalter."""
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.zone_index = zone_index
        self._attr_name = f"Bett{suffix} Schnellheizen"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_zone_{zone_index}_boost"
        self._attr_device_info = get_zone_device_info(coordinator, zone_index)

    @property
    def is_on(self) -> bool:
        """Gibt an, ob der Boost-Modus aktiv ist."""
        # Prüfe ob Boost aktiv UND nicht abgelaufen
        boost_active = self.coordinator.manual_boost.get(self.zone_index, False)
        boost_until = self.coordinator.boost_until.get(self.zone_index)
        
        if boost_active and boost_until:
            if local_now() > boost_until:
                # Abgelaufen - deaktivieren
                self.coordinator.manual_boost[self.zone_index] = False
                return False
        
        return boost_active

    async def async_turn_on(self, **kwargs):
        """Aktiviert den Boost-Modus für 60 Minuten."""
        self.coordinator.manual_boost[self.zone_index] = True
        self.coordinator.boost_until[self.zone_index] = local_now() + timedelta(minutes=60)
        
        _LOGGER.info(
            f"🔥 Schnellheizen für Zone {self.zone_index} aktiviert! "
            f"(60 Minuten bis {self.coordinator.boost_until[self.zone_index].strftime('%H:%M')})"
        )
        
        # Sofortige Neuberechnung der Heizziele erzwingen
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        """Deaktiviert den Boost-Modus."""
        self.coordinator.manual_boost[self.zone_index] = False
        self.coordinator.boost_until[self.zone_index] = None
        
        _LOGGER.info(f"Schnellheizen für Zone {self.zone_index} deaktiviert.")
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self):
        """Zeigt Boost-Details an."""
        boost_until = self.coordinator.boost_until.get(self.zone_index)
        
        if self.is_on and boost_until:
            remaining = boost_until - local_now()
            minutes_left = max(0, int(remaining.total_seconds() / 60))
            return {
                "endet_um": boost_until.strftime("%H:%M"),
                "verbleibend_minuten": minutes_left,
                "info": "Schnellheizen aktiv - Bett wird vorgeheizt!"
            }
        
        return {
            "info": "Aktivieren für schnelles Aufwärmen (60 Min)"
        }


class BedSickModeSwitch(CoordinatorEntity, SwitchEntity):
    """
    Krank-Modus: Konstante erhöhte Temperatur für Genesung.
    """
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:thermometer-plus"

    def __init__(self, coordinator, zone_index, suffix):
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.zone_index = zone_index
        self._attr_name = f"Bett{suffix} Krank-Modus"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_zone_{zone_index}_sick"
        self._attr_device_info = get_zone_device_info(coordinator, zone_index)
        
        # Konfigurierbare Werte aus Options holen
        options = coordinator.config_entry.options
        self._sick_temp = options.get("sick_mode_temp", DEFAULT_SICK_MODE_TEMP)
        self._sick_days = options.get("sick_mode_days", DEFAULT_SICK_MODE_DAYS)

    @property
    def is_on(self) -> bool:
        """Prüft ob Krank-Modus aktiv und nicht abgelaufen."""
        sick_until = self.coordinator.sick_mode_until.get(self.zone_index)
        if sick_until and local_now() < sick_until:
            return True
        return False

    async def async_turn_on(self, **kwargs):
        """Aktiviert den Krank-Modus."""
        # Aktualisiere konfigurierbare Werte (falls geändert)
        options = self.coordinator.config_entry.options
        self._sick_temp = options.get("sick_mode_temp", DEFAULT_SICK_MODE_TEMP)
        self._sick_days = options.get("sick_mode_days", DEFAULT_SICK_MODE_DAYS)
        
        self.coordinator.sick_mode_until[self.zone_index] = local_now() + timedelta(days=self._sick_days)
        self.coordinator.sick_mode_temp[self.zone_index] = self._sick_temp
        
        _LOGGER.info(
            f"🤒 Krank-Modus für Zone {self.zone_index} aktiviert! "
            f"({self._sick_days} Tage bei konstant {self._sick_temp}°C)"
        )
        
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        """Deaktiviert den Krank-Modus."""
        self.coordinator.sick_mode_until[self.zone_index] = None
        self.coordinator.sick_mode_temp[self.zone_index] = None
        
        _LOGGER.info(f"Krank-Modus für Zone {self.zone_index} deaktiviert.")
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self):
        """Zeigt Krank-Modus-Details an."""
        sick_until = self.coordinator.sick_mode_until.get(self.zone_index)
        
        if self.is_on and sick_until:
            remaining = sick_until - local_now()
            hours = int(remaining.total_seconds() / 3600)
            return {
                "endet_am": sick_until.strftime("%d.%m.%Y %H:%M"),
                "verbleibend_stunden": hours,
                "temperatur": f"{self._sick_temp}°C (konstant)",
                "info": "Heilungs-Modus aktiv - konstante Wärme"
            }
        
        return {
            "konfigurierte_temperatur": f"{self._sick_temp}°C",
            "konfigurierte_dauer": f"{self._sick_days} Tage",
            "info": "Krank? Aktivieren für konstante Wärme."
        }


class BedThermalBatterySwitch(CoordinatorEntity, SwitchEntity):
    """
    Solar-Batterie-Modus: Nutzt Solar-Überschuss zum Vorheizen.
    
    NUR für Wasserbett sinnvoll! Die hohe thermische Masse (300-700L Wasser)
    kann Energie speichern wie eine Batterie.
    """
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:solar-power"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self.coordinator = coordinator
        self._attr_name = "Bett Solar-Batterie"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_thermal_battery"
        self._attr_device_info = get_energy_device_info(coordinator)

    @property
    def is_on(self) -> bool:
        """Gibt zurück ob Solar-Batterie-Modus aktiv ist."""
        return getattr(self.coordinator, "thermal_battery_enabled", True)

    async def async_turn_on(self, **kwargs):
        """Aktiviert den Solar-Batterie-Modus."""
        self.coordinator.thermal_battery_enabled = True
        _LOGGER.info("☀️ Solar-Batterie-Modus aktiviert!")
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        """Deaktiviert den Solar-Batterie-Modus."""
        self.coordinator.thermal_battery_enabled = False
        _LOGGER.info("Solar-Batterie-Modus deaktiviert.")
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self):
        """Zeigt Solar-Batterie-Info."""
        return {
            "max_temperatur": "28.5°C",
            "info": (
                "Bei Solar-Überschuss wird das Wasserbett als "
                "thermische Batterie genutzt - kostenlos vorheizen!"
            )
        }


class BedTariffModeSwitch(CoordinatorEntity, SwitchEntity):
    """
    Tarifmodus: Passt Heizverhalten an Strompreise an.
    
    Benötigt: Strompreis-Sensor (z.B. Tibber, aWATTar)
    
    Verhalten je nach Bett-Typ:
    - Wasserbett: Max. -2°C Absenkung bei hohen Preisen (nie unter 26°C!)
    - Heizmatte: Kann bei hohen Preisen komplett AUS gehen
    
    Bei günstigen Preisen: Vorheizen / thermische Batterie laden
    """
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:currency-eur"

    def __init__(self, coordinator, is_waterbed: bool):
        super().__init__(coordinator)
        self.coordinator = coordinator
        self._is_waterbed = is_waterbed
        self._attr_name = "Bett Tarifmodus"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_tariff_mode"
        self._attr_device_info = get_device_info(coordinator)

    @property
    def is_on(self) -> bool:
        """Gibt zurück ob Tarifmodus aktiv ist."""
        return getattr(self.coordinator, "eco_mode_enabled", False)

    async def async_turn_on(self, **kwargs):
        """Aktiviert den Tarifmodus."""
        self.coordinator.eco_mode_enabled = True
        _LOGGER.info("💰 Tarifmodus aktiviert - Heizverhalten wird an Strompreise angepasst!")
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        """Deaktiviert den Tarifmodus."""
        self.coordinator.eco_mode_enabled = False
        _LOGGER.info("Tarifmodus deaktiviert.")
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self):
        """Zeigt Tarifmodus-Info."""
        # Aktuellen Preis-Status anzeigen wenn verfügbar
        price_status = "Unbekannt"
        if self.coordinator.data and "global_state" in self.coordinator.data:
            raw = self.coordinator.data["global_state"].get("energy", {}).get("price_status", "normal")
            status_map = {"cheap": "Günstig ✅", "expensive": "Teuer ⚠️", "normal": "Normal"}
            price_status = status_map.get(raw, "Normal")

        if self._is_waterbed:
            return {
                "strompreis_status": price_status,
                "absenkung_bei_teuer": "Max. 2°C",
                "min_temperatur": "26°C",
                "info": (
                    "Bei hohen Strompreisen wird die Temperatur um max. 2°C gesenkt. "
                    "Bei günstigen Preisen wird das Wasserbett als thermische Batterie vorgeheizt."
                )
            }
        else:
            return {
                "strompreis_status": price_status,
                "absenkung_bei_teuer": "Komplett AUS möglich",
                "min_temperatur": "0°C",
                "info": (
                    "Bei hohen Strompreisen kann die Heizmatte komplett ausgeschaltet werden. "
                    "Bei günstigen Preisen wird rechtzeitig vorgeheizt."
                )
            }


class BedVacationModeSwitch(CoordinatorEntity, SwitchEntity):
    """
    Urlaub-Modus: Minimaler Energieverbrauch bei längerer Abwesenheit.
    
    Verhalten je nach Bett-Typ:
    - Wasserbett: Hält 24-25°C (Kondensationsschutz!)
    - Heizmatte: Komplett AUS
    """
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:airplane"

    def __init__(self, coordinator, is_waterbed: bool):
        super().__init__(coordinator)
        self.coordinator = coordinator
        self._is_waterbed = is_waterbed
        self._attr_name = "Bett Urlaub-Modus"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_vacation_mode"
        self._attr_device_info = get_energy_device_info(coordinator)

    @property
    def is_on(self) -> bool:
        """Gibt zurück ob Urlaub-Modus aktiv ist."""
        # Prüfe ob Urlaub aktiv UND nicht abgelaufen
        vacation_enabled = getattr(self.coordinator, "vacation_mode_enabled", False)
        vacation_until = getattr(self.coordinator, "vacation_until", None)
        
        if vacation_enabled and vacation_until:
            if local_now() > vacation_until:
                # Urlaub vorbei!
                self.coordinator.vacation_mode_enabled = False
                return False
        
        return vacation_enabled

    async def async_turn_on(self, **kwargs):
        """Aktiviert den Urlaub-Modus (14 Tage Standard)."""
        self.coordinator.vacation_mode_enabled = True
        self.coordinator.vacation_until = local_now() + timedelta(days=14)
        
        _LOGGER.info(
            f"✈️ Urlaub-Modus aktiviert! "
            f"(bis {self.coordinator.vacation_until.strftime('%d.%m.%Y')})"
        )
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        """Deaktiviert den Urlaub-Modus."""
        self.coordinator.vacation_mode_enabled = False
        self.coordinator.vacation_until = None
        self.coordinator.vacation_temp_override = None
        _LOGGER.info("Urlaub-Modus deaktiviert - willkommen zurück!")
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self):
        """Zeigt Urlaub-Modus-Info."""
        vacation_until = getattr(self.coordinator, "vacation_until", None)
        
        base_attrs = {}
        if self.is_on and vacation_until:
            remaining = vacation_until - local_now()
            days_left = max(0, remaining.days)
            base_attrs = {
                "endet_am": vacation_until.strftime("%d.%m.%Y"),
                "verbleibend_tage": days_left,
            }
        
        if self._is_waterbed:
            base_attrs.update({
                "halte_temperatur": "24-25°C",
                "info": (
                    "Wasserbett-Urlaub: Hält 24-25°C um "
                    "Kondensation zu vermeiden. ⚠️ NIEMALS komplett ausschalten!"
                )
            })
        else:
            base_attrs.update({
                "halte_temperatur": "AUS",
                "info": "Heizmatte-Urlaub: Komplett ausgeschaltet."
            })
        
        return base_attrs
