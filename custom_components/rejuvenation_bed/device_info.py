"""Gemeinsame DeviceInfo-Factories für alle Plattform-Module."""

from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, MANUFACTURER, SW_VERSION


def detect_hardware_level(zone_config: dict) -> str:
    """
    Erkennt das Hardware-Level einer Zone anhand der konfigurierten Sensoren.

    Einzige Quelle der Wahrheit — vorher 3× dupliziert in config_flow,
    options_flow und climate (#12).

    Level A (Basic):       Nur Relay → Zeitschaltuhr
    Level B (Smart):       Relay + Power → Energie-Tracking
    Level B+ (Temperatur): Relay + Temp → Biorhythmus-Kurve
    Level C (Voll):        Relay + Temp + Power → alle Kern-Features
    Level D (Erweitert):   + Luft ODER Feuchte
    Level E (Premium):     + Luft UND Feuchte
    """
    has_temp = zone_config.get("temp_sensor") is not None
    has_power = zone_config.get("power_sensor") is not None
    has_air = zone_config.get("air_temp_sensor") is not None
    has_moisture = zone_config.get("moisture_sensor") is not None

    if has_temp and has_power and has_air and has_moisture:
        return "E"  # Premium - Alles!
    elif has_temp and has_power and (has_air or has_moisture):
        return "D"  # Erweitert - Umgebungs-Sensorik
    elif has_temp and has_power:
        return "C"  # Vollausstattung - Alle Kern-Features
    elif has_temp:
        return "B+"  # Temperatur - Kurve ja, aber kein Energie-Tracking
    elif has_power:
        return "B"  # Smart - Energie, aber keine Kurve
    return "A"  # Basic - Nur Zeitschaltuhr


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
    zones_count = len(coordinator.config_entry.data.get("zones", []))
    if zones_count <= 1:
        return get_device_info(coordinator)

    zone_name = "Links" if zone_index == 0 else "Rechts"
    return DeviceInfo(
        identifiers={(DOMAIN, f"{coordinator.config_entry.entry_id}_zone_{zone_index}")},
        manufacturer=MANUFACTURER,
        model=f"Bett-Zone {zone_name}",
        name=f"Bett {zone_name}",
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


def get_sleep_device_info(coordinator) -> DeviceInfo:
    """Schlaf-Gerät: Score, Analyse, Diagnose, Intelligenz."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"{coordinator.config_entry.entry_id}_sleep")},
        manufacturer=MANUFACTURER,
        model="Schlaf, Analyse & Intelligenz",
        name="Bett Schlaf/Analyse",
        sw_version=SW_VERSION,
        via_device=(DOMAIN, coordinator.config_entry.entry_id),
    )
