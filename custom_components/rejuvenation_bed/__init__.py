import logging
from datetime import datetime, timedelta
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv, device_registry as dr
import voluptuous as vol
from .const import DOMAIN
from .coordinator import RejuvenationBedCoordinator

_LOGGER = logging.getLogger(__name__)

# Diese Plattformen müssen als .py Dateien im Ordner existieren
PLATFORMS: list[str] = ["climate", "sensor", "binary_sensor", "switch"]

# Device Info für alle Entities
MANUFACTURER = "Rejuvenation Bed"
MODEL_WASSERBETT = "Smart Wasserbett Controller"
MODEL_HEIZMATTE = "Smart Heizmatte Controller"

# Service Schemas
SERVICE_SET_BOOST_SCHEMA = vol.Schema({
    vol.Optional("duration_minutes", default=30): vol.All(
        vol.Coerce(int), vol.Range(min=5, max=120)
    ),
})

SERVICE_SET_SICK_MODE_SCHEMA = vol.Schema({
    vol.Optional("temperature", default=30): vol.All(
        vol.Coerce(float), vol.Range(min=28, max=35)
    ),
    vol.Optional("days", default=3): vol.All(
        vol.Coerce(int), vol.Range(min=1, max=14)
    ),
})

SERVICE_SET_VACATION_SCHEMA = vol.Schema({
    vol.Optional("temperature", default=20): vol.All(
        vol.Coerce(float), vol.Range(min=15, max=25)
    ),
    vol.Optional("end_date"): cv.date,
})

SERVICE_PREHEAT_SCHEMA = vol.Schema({
    vol.Optional("target_temperature", default=29): vol.All(
        vol.Coerce(float), vol.Range(min=26, max=34)
    ),
    vol.Optional("duration_minutes", default=30): vol.All(
        vol.Coerce(int), vol.Range(min=15, max=60)
    ),
})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Initialisierung der Rejuvenation Bed Integration."""
    
    # 1. Speicherbereich anlegen
    hass.data.setdefault(DOMAIN, {})
    
    # 2. Den Coordinator instanziieren
    # Er verbindet SafetyManager, Energy- & TemperatureCalculator
    coordinator = RejuvenationBedCoordinator(hass, entry)
    
    # 3. Ersten Refresh erzwingen (Initialisiert alle Sensorwerte)
    await coordinator.async_config_entry_first_refresh()

    # 4. Coordinator im globalen hass.data Objekt speichern
    hass.data[DOMAIN][entry.entry_id] = coordinator
    
    # 5. Device im Device Registry registrieren
    await _async_register_device(hass, entry)

    # 6. Plattformen laden (climate.py, sensor.py, binary_sensor.py, switch.py)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # 7. Services registrieren
    await _async_setup_services(hass, entry)

    return True


async def _async_register_device(hass: HomeAssistant, entry: ConfigEntry):
    """Registriert das Bett als Device im Device Registry."""
    device_registry = dr.async_get(hass)
    
    global_conf = entry.data.get("global", {})
    bed_type = global_conf.get("bed_type", "wasserbett")
    zones_count = len(entry.data.get("zones", []))
    
    # Model basierend auf Bett-Typ
    model = MODEL_WASSERBETT if bed_type == "wasserbett" else MODEL_HEIZMATTE
    
    # Zonen-Info für Namen
    zone_suffix = "Dual-Zone" if zones_count > 1 else "Mono"
    
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer=MANUFACTURER,
        model=f"{model} ({zone_suffix})",
        name="Rejuvenation Bed",
        sw_version="0.1.0",
    )
    
    _LOGGER.info(f"Device registriert: {model} ({zone_suffix})")

    return True


async def _async_setup_services(hass: HomeAssistant, entry: ConfigEntry):
    """Registriert die Custom Services."""
    
    async def handle_set_boost(call: ServiceCall):
        """Handle set_boost service."""
        coordinator = hass.data[DOMAIN][entry.entry_id]
        duration = call.data.get("duration_minutes", 30)
        
        # Aktiviere Boost für alle Zonen (oder spezifische via entity_id)
        for zone_idx in range(len(entry.data.get("zones", []))):
            coordinator.manual_boost[zone_idx] = True
            coordinator.boost_until = coordinator.boost_until if hasattr(coordinator, 'boost_until') else {}
            coordinator.boost_until[zone_idx] = datetime.now() + timedelta(minutes=duration)
        
        _LOGGER.info(f"Boost aktiviert für {duration} Minuten")
        await coordinator.async_request_refresh()
    
    async def handle_set_sick_mode(call: ServiceCall):
        """Handle set_sick_mode service."""
        coordinator = hass.data[DOMAIN][entry.entry_id]
        temperature = call.data.get("temperature", 30)
        days = call.data.get("days", 3)
        
        for zone_idx in range(len(entry.data.get("zones", []))):
            coordinator.sick_mode_until[zone_idx] = datetime.now() + timedelta(days=days)
            coordinator.sick_mode_temp = coordinator.sick_mode_temp if hasattr(coordinator, 'sick_mode_temp') else {}
            coordinator.sick_mode_temp[zone_idx] = temperature
        
        _LOGGER.info(f"Krank-Modus aktiviert: {temperature}°C für {days} Tage")
        await coordinator.async_request_refresh()
    
    async def handle_set_vacation(call: ServiceCall):
        """Handle set_vacation_mode service."""
        coordinator = hass.data[DOMAIN][entry.entry_id]
        temperature = call.data.get("temperature", 20)
        end_date = call.data.get("end_date")
        
        from homeassistant.components.climate.const import PRESET_AWAY
        
        for zone_idx in range(len(entry.data.get("zones", []))):
            coordinator.manual_preset[zone_idx] = PRESET_AWAY
            coordinator.vacation_temp = coordinator.vacation_temp if hasattr(coordinator, 'vacation_temp') else {}
            coordinator.vacation_temp[zone_idx] = temperature
            if end_date:
                coordinator.vacation_until = coordinator.vacation_until if hasattr(coordinator, 'vacation_until') else {}
                coordinator.vacation_until[zone_idx] = datetime.combine(end_date, datetime.min.time())
        
        _LOGGER.info(f"Urlaub-Modus aktiviert: {temperature}°C")
        await coordinator.async_request_refresh()
    
    async def handle_cancel_special_mode(call: ServiceCall):
        """Handle cancel_special_mode service."""
        coordinator = hass.data[DOMAIN][entry.entry_id]
        
        from homeassistant.components.climate.const import PRESET_NONE
        
        for zone_idx in range(len(entry.data.get("zones", []))):
            coordinator.manual_boost[zone_idx] = False
            coordinator.sick_mode_until[zone_idx] = None
            coordinator.manual_preset[zone_idx] = PRESET_NONE
            if hasattr(coordinator, 'boost_until'):
                coordinator.boost_until[zone_idx] = None
        
        _LOGGER.info("Alle Sonder-Modi beendet")
        await coordinator.async_request_refresh()
    
    async def handle_reset_energy_budget(call: ServiceCall):
        """Handle reset_energy_budget service."""
        if not call.data.get("confirm", False):
            _LOGGER.warning("Energie-Budget Reset abgebrochen (keine Bestätigung)")
            return
        
        coordinator = hass.data[DOMAIN][entry.entry_id]
        coordinator.diagnostics_manager.reset_energy_budget()
        _LOGGER.info("Energie-Budget zurückgesetzt")
    
    async def handle_preheat(call: ServiceCall):
        """Handle preheat_bed service."""
        coordinator = hass.data[DOMAIN][entry.entry_id]
        target_temp = call.data.get("target_temperature", 29)
        duration = call.data.get("duration_minutes", 30)
        
        for zone_idx in range(len(entry.data.get("zones", []))):
            coordinator.manual_target_temp[zone_idx] = target_temp
            coordinator.preheat_until = coordinator.preheat_until if hasattr(coordinator, 'preheat_until') else {}
            coordinator.preheat_until[zone_idx] = datetime.now() + timedelta(minutes=duration)
        
        _LOGGER.info(f"Vorheizen auf {target_temp}°C für {duration} Minuten")
        await coordinator.async_request_refresh()
    
    # Services registrieren
    hass.services.async_register(
        DOMAIN, "set_boost", handle_set_boost, schema=SERVICE_SET_BOOST_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "set_sick_mode", handle_set_sick_mode, schema=SERVICE_SET_SICK_MODE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "set_vacation_mode", handle_set_vacation, schema=SERVICE_SET_VACATION_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "cancel_special_mode", handle_cancel_special_mode
    )
    hass.services.async_register(
        DOMAIN, "reset_energy_budget", handle_reset_energy_budget
    )
    hass.services.async_register(
        DOMAIN, "preheat_bed", handle_preheat, schema=SERVICE_PREHEAT_SCHEMA
    )
    
    _LOGGER.info("Rejuvenation Bed Services registriert")


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Sicheres Entladen der Integration."""
    
    # Not-Aus beim Entladen/Neustart: Wir holen den Coordinator
    coordinator = hass.data[DOMAIN].get(entry.entry_id)
    if coordinator:
        _LOGGER.info("Entlade Integration: Schalte Heizungen zur Sicherheit aus.")
        # Optional: Hier könnte man einen finalen Turn-Off Befehl senden
    
    # Plattformen entladen
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    # Services entfernen
    for service in ["set_boost", "set_sick_mode", "set_vacation_mode", 
                    "cancel_special_mode", "reset_energy_budget", "preheat_bed"]:
        hass.services.async_remove(DOMAIN, service)
    
    # Speicher bereinigen
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok