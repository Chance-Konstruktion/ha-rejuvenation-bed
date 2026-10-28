"""Gemeinsame DeviceInfo-Factories für alle Plattform-Module."""

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, MANUFACTURER, SW_VERSION


def _via_device_fields(coordinator) -> dict[str, object]:
    """Return the parent-device link using the API available in this Core."""
    entry = coordinator.config_entry
    identifier = (DOMAIN, entry.entry_id)

    # Core 2026.8 introduced via_device_id and dropped via_device from the
    # DeviceInfo type; 2026.11 then made DeviceInfo a dataclass. Detect the
    # field so the integration still works with earlier supported Core builds.
    if "via_device_id" not in getattr(DeviceInfo, "__annotations__", {}):
        return {"via_device": identifier}

    device_id_lookup = getattr(dr, "async_get_device_id_by_identifier", None)
    if device_id_lookup is not None:
        try:
            return {
                "via_device_id": device_id_lookup(
                    coordinator.hass, identifier, config_entry_id=entry.entry_id
                )
            }
        except ValueError:
            # The parent should already exist, but setup must survive an
            # incomplete device registry without leaving a stale link.
            return {}

    # Defensive fallback for a Core build that exposes the field but not the
    # module helper. Prefer entry-scoped lookup when available.
    registry = dr.async_get(coordinator.hass)
    lookup = getattr(registry, "async_get_device_by_identifier", None)
    if lookup is not None:
        parent = lookup(identifier, entry.entry_id)
    else:
        parent = registry.async_get_device(identifiers={identifier})
    if parent is None:
        return {}
    return {"via_device_id": parent.id}


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
        **_via_device_fields(coordinator),
    )


def get_energy_device_info(coordinator) -> DeviceInfo:
    """Energie-Gerät: Verbrauch, Solar, Ersparnis, Batterie."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"{coordinator.config_entry.entry_id}_energy")},
        manufacturer=MANUFACTURER,
        model="Energie & Ersparnis",
        name="Bett Energie",
        sw_version=SW_VERSION,
        **_via_device_fields(coordinator),
    )


def get_sleep_device_info(coordinator) -> DeviceInfo:
    """Schlaf-Gerät: Score, Analyse, Diagnose, Intelligenz."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"{coordinator.config_entry.entry_id}_sleep")},
        manufacturer=MANUFACTURER,
        model="Schlaf, Analyse & Intelligenz",
        name="Bett Schlaf/Analyse",
        sw_version=SW_VERSION,
        **_via_device_fields(coordinator),
    )
