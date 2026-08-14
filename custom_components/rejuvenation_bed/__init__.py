import logging
from datetime import datetime, timedelta
from pathlib import Path
from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv, device_registry as dr
import voluptuous as vol
from .const import DOMAIN, MANUFACTURER, SW_VERSION, local_now
from .coordinator import RejuvenationBedCoordinator

_LOGGER = logging.getLogger(__name__)

# Diese Plattformen müssen als .py Dateien im Ordner existieren
PLATFORMS: list[str] = ["climate", "sensor", "binary_sensor", "switch"]

# Lovelace-Karte (Nachttischwecker). Wird von der Integration selbst
# ausgeliefert und ins Frontend geladen — kein manueller Ressourcen-
# Eintrag, kein Kopieren nach /config/www.
CARD_FILENAME = "rejuvenation-nightstand-card.js"
CARD_URL = f"/{DOMAIN}/{CARD_FILENAME}"
# Lovelace lädt seine Ressourcen, *bevor* es die Karten baut. Die Version im
# URL erneuert den Browser-Cache nach einem Update der Integration.
CARD_RESOURCE_URL = f"{CARD_URL}?v={SW_VERSION}"
CARD_REGISTERED = f"{DOMAIN}_card_registered"

MODEL_WASSERBETT = "Smart Wasserbett Controller"
MODEL_HEIZMATTE = "Smart Heizmatte Controller"

# Service Schemas
SERVICE_SET_BOOST_SCHEMA = vol.Schema(
    {
        vol.Optional("duration_minutes", default=30): vol.All(vol.Coerce(int), vol.Range(min=5, max=120)),
    }
)

SERVICE_SET_SICK_MODE_SCHEMA = vol.Schema(
    {
        vol.Optional("temperature", default=30): vol.All(vol.Coerce(float), vol.Range(min=28, max=35)),
        vol.Optional("days", default=3): vol.All(vol.Coerce(int), vol.Range(min=1, max=14)),
    }
)

SERVICE_SET_VACATION_SCHEMA = vol.Schema(
    {
        vol.Optional("temperature", default=20): vol.All(vol.Coerce(float), vol.Range(min=15, max=25)),
        vol.Optional("end_date"): cv.date,
    }
)

SERVICE_CLEAR_EMERGENCY_SCHEMA = vol.Schema(
    {
        # Ohne Angabe werden alle verriegelten Zonen freigegeben. Die
        # Nummer ist die, die der Nutzer in der Meldung gelesen hat --
        # also 1-basiert, nicht der interne Index.
        vol.Optional("zone"): vol.All(vol.Coerce(int), vol.Range(min=1, max=3)),
    }
)

SERVICE_PREHEAT_SCHEMA = vol.Schema(
    {
        vol.Optional("target_temperature", default=29): vol.All(vol.Coerce(float), vol.Range(min=26, max=34)),
        vol.Optional("duration_minutes", default=30): vol.All(vol.Coerce(int), vol.Range(min=15, max=60)),
    }
)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migriert alte Config-Einträge auf aktuelle Struktur."""
    _LOGGER.debug(f"Migration: Config entry version {entry.version}")

    if entry.version < 2:
        # v1 → v2: Neue Felder mit Defaults ergänzen
        new_data = {**entry.data}

        # Global-Defaults sicherstellen
        if "global" in new_data:
            g = new_data["global"]
            g.setdefault("co2_sensor", None)
            g.setdefault("warm_from", "22:00")
            g.setdefault("warm_until", "07:00")
            g.setdefault("chronotype", "normal")

        # Zone-Defaults sicherstellen
        for i, zone in enumerate(new_data.get("zones", [])):
            zone.setdefault("air_temp_sensor", None)
            zone.setdefault("moisture_sensor", None)
            zone.setdefault("presence_sensor", None)
            zone.setdefault("power_rating", 250)
            zone.setdefault("boost_target_temp", 34.0)

        hass.config_entries.async_update_entry(entry, data=new_data, version=2)
        _LOGGER.info(f"Migration v{entry.version} → v2 erfolgreich")

    return True


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

    # 8. Options-Change-Listener: Bei Änderungen Integration neu laden
    #    (z.B. CO₂-Sensor nachträglich hinzugefügt → Score-Sensoren erstellen)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    # 9. Lovelace-Karte im Frontend bereitstellen
    await _async_register_card(hass)

    return True


async def _async_register_card(hass: HomeAssistant) -> None:
    """Die Nachttisch-Karte ausliefern und ins Frontend laden.

    Läuft genau einmal pro Home-Assistant-Start, auch wenn mehrere
    Config-Entries (z.B. zwei Betten) eingerichtet sind.
    """
    if hass.data.get(CARD_REGISTERED):
        return

    card_path = Path(__file__).parent / "frontend" / CARD_FILENAME
    if not card_path.is_file():
        _LOGGER.warning("Karte %s nicht gefunden – Dashboard-Karte steht nicht zur Verfügung", card_path)
        return

    try:
        await hass.http.async_register_static_paths([StaticPathConfig(CARD_URL, str(card_path), cache_headers=False)])

        # Bevorzugt als Lovelace-Ressource: darauf wartet das Dashboard, bevor
        # es die Karten baut. Ein reines add_extra_js_url() wird nebenher
        # geladen — auf langsamen Geräten (Aussendisplay eines Falters) ist die
        # Karte dann noch nicht definiert und das Dashboard zeigt
        # "Konfigurationsfehler".
        als_ressource = await _async_register_lovelace_resource(hass)
        if not als_ressource:
            # YAML-Modus o.ä.: dort pflegt der Nutzer resources selbst, das
            # Extra-Skript bleibt der einzige Weg.
            frontend.add_extra_js_url(hass, CARD_URL)

        hass.data[CARD_REGISTERED] = True
        _LOGGER.debug("Nachttisch-Karte unter %s registriert (Ressource: %s)", CARD_URL, als_ressource)
    except Exception as err:  # pragma: no cover - defensiv, nie fatal
        # Ohne Karte bleibt die Integration voll funktionsfähig; nur das
        # fertige Dashboard fehlt. Das darf das Setup nicht abbrechen.
        _LOGGER.warning("Nachttisch-Karte konnte nicht registriert werden: %s", err)


async def _async_register_lovelace_resource(hass: HomeAssistant) -> bool:
    """Die Karte in die Lovelace-Ressourcen eintragen.

    Gibt True zurück, wenn der Eintrag steht. Im YAML-Modus (oder wenn
    Lovelace noch gar nicht geladen ist) geht das nicht — dann False.
    """
    lovelace = hass.data.get("lovelace")
    resources = getattr(lovelace, "resources", None)
    if resources is None and isinstance(lovelace, dict):
        resources = lovelace.get("resources")
    # Nur die Storage-Variante kann Einträge anlegen.
    if resources is None or not hasattr(resources, "async_create_item"):
        return False

    if not getattr(resources, "loaded", False):
        await resources.async_load()
        resources.loaded = True

    for item in resources.async_items():
        url = str(item.get("url", ""))
        if url.split("?")[0] != CARD_URL:
            continue
        if url != CARD_RESOURCE_URL:
            # Nach einem Update zeigt der alte Eintrag auf die alte Version.
            await resources.async_update_item(item["id"], {"url": CARD_RESOURCE_URL})
        return True

    await resources.async_create_item({"res_type": "module", "url": CARD_RESOURCE_URL})
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry):
    """Wird aufgerufen wenn Options geändert werden → Integration neu laden."""
    _LOGGER.info("Options geändert → Integration wird neu geladen")
    await hass.config_entries.async_reload(entry.entry_id)


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
        sw_version=SW_VERSION,
    )

    _LOGGER.info(f"Device registriert: {model} ({zone_suffix})")

    return True


def _get_coordinator(hass: HomeAssistant):
    """
    Holt den (einzigen) aktiven Coordinator (#6).

    Die Integration ist `single_config_entry`, daher existiert höchstens ein
    Eintrag. Services werden global registriert und lösen den Coordinator zur
    Laufzeit auf, statt einen festen Entry-Closure zu verwenden (der bei
    Reload/Unload veralten würde).
    """
    for value in hass.data.get(DOMAIN, {}).values():
        if isinstance(value, RejuvenationBedCoordinator):
            return value
    return None


async def _async_setup_services(hass: HomeAssistant, entry: ConfigEntry):
    """Registriert die Custom Services (einmalig, global)."""

    # #6: Nur einmal registrieren — nicht pro Config-Entry
    if hass.services.has_service(DOMAIN, "set_boost"):
        return

    async def handle_set_boost(call: ServiceCall):
        """Handle set_boost service."""
        coordinator = _get_coordinator(hass)
        if coordinator is None:
            _LOGGER.warning("set_boost: kein aktiver Coordinator")
            return
        duration = call.data.get("duration_minutes", 30)

        for zone_idx in range(len(coordinator.config_entry.data.get("zones", []))):
            coordinator.manual_boost[zone_idx] = True
            coordinator.boost_until = coordinator.boost_until if hasattr(coordinator, "boost_until") else {}
            coordinator.boost_until[zone_idx] = local_now() + timedelta(minutes=duration)

        _LOGGER.info(f"Boost aktiviert für {duration} Minuten")
        await coordinator.async_request_refresh()

    async def handle_set_sick_mode(call: ServiceCall):
        """Handle set_sick_mode service."""
        coordinator = _get_coordinator(hass)
        if coordinator is None:
            _LOGGER.warning("set_sick_mode: kein aktiver Coordinator")
            return
        temperature = call.data.get("temperature", 30)
        days = call.data.get("days", 3)

        for zone_idx in range(len(coordinator.config_entry.data.get("zones", []))):
            coordinator.sick_mode_until[zone_idx] = local_now() + timedelta(days=days)
            coordinator.sick_mode_temp = coordinator.sick_mode_temp if hasattr(coordinator, "sick_mode_temp") else {}
            coordinator.sick_mode_temp[zone_idx] = temperature

        _LOGGER.info(f"Krank-Modus aktiviert: {temperature}°C für {days} Tage")
        await coordinator.async_request_refresh()

    async def handle_set_vacation(call: ServiceCall):
        """Handle set_vacation_mode service."""
        coordinator = _get_coordinator(hass)
        if coordinator is None:
            _LOGGER.warning("set_vacation_mode: kein aktiver Coordinator")
            return
        end_date = call.data.get("end_date")
        temperature = call.data.get("temperature")

        from homeassistant.components.climate.const import PRESET_AWAY

        coordinator.vacation_mode_enabled = True
        coordinator.vacation_temp_override = temperature
        if end_date:
            coordinator.vacation_until = datetime.combine(end_date, datetime.min.time())
        else:
            # Default: 14 Tage
            coordinator.vacation_until = local_now() + timedelta(days=14)

        for zone_idx in range(len(coordinator.config_entry.data.get("zones", []))):
            coordinator.manual_preset[zone_idx] = PRESET_AWAY

        _LOGGER.info(f"Urlaub-Modus aktiviert bis {coordinator.vacation_until.strftime('%d.%m.%Y')}")
        await coordinator.async_request_refresh()

    async def handle_cancel_special_mode(call: ServiceCall):
        """Handle cancel_special_mode service."""
        coordinator = _get_coordinator(hass)
        if coordinator is None:
            _LOGGER.warning("cancel_special_mode: kein aktiver Coordinator")
            return

        from homeassistant.components.climate.const import PRESET_NONE

        for zone_idx in range(len(coordinator.config_entry.data.get("zones", []))):
            coordinator.manual_boost[zone_idx] = False
            coordinator.sick_mode_until[zone_idx] = None
            coordinator.manual_preset[zone_idx] = PRESET_NONE
            if hasattr(coordinator, "boost_until"):
                coordinator.boost_until[zone_idx] = None
            # #4: manuelle Zieltemperatur ebenfalls verwerfen → zurück zur Kurve
            if hasattr(coordinator, "clear_manual_target"):
                coordinator.clear_manual_target(zone_idx)

        # Vacation zurücksetzen
        coordinator.vacation_mode_enabled = False
        coordinator.vacation_until = None
        coordinator.vacation_temp_override = None

        _LOGGER.info("Alle Sonder-Modi beendet")
        await coordinator.async_request_refresh()

    async def handle_reset_energy_budget(call: ServiceCall):
        """Handle reset_energy_budget service."""
        if not call.data.get("confirm", False):
            _LOGGER.warning("Energie-Budget Reset abgebrochen (keine Bestätigung)")
            return

        coordinator = _get_coordinator(hass)
        if coordinator is None:
            _LOGGER.warning("reset_energy_budget: kein aktiver Coordinator")
            return
        coordinator.diagnostics_manager.reset_energy_budget()
        _LOGGER.info("Energie-Budget zurückgesetzt")

    async def handle_preheat(call: ServiceCall):
        """Handle preheat_bed service."""
        coordinator = _get_coordinator(hass)
        if coordinator is None:
            _LOGGER.warning("preheat_bed: kein aktiver Coordinator")
            return
        target_temp = call.data.get("target_temperature", 29)
        duration = call.data.get("duration_minutes", 30)

        for zone_idx in range(len(coordinator.config_entry.data.get("zones", []))):
            coordinator.manual_target_temp[zone_idx] = target_temp
            # #5: gemeinsame TTL nutzen — Vorheizen verfällt nach 'duration'
            if not hasattr(coordinator, "manual_target_until"):
                coordinator.manual_target_until = {}
            coordinator.manual_target_until[zone_idx] = local_now() + timedelta(minutes=duration)

        _LOGGER.info(f"Vorheizen auf {target_temp}°C für {duration} Minuten")
        await coordinator.async_request_refresh()

    async def handle_clear_emergency(call: ServiceCall):
        """Handle clear_emergency service.

        Die Gegenseite zum Not-Aus. Bis hierher gab es keine: der
        SafetyManager hatte zwar ein ``clear_emergency()``, aber im ganzen
        Projekt keinen einzigen Aufrufer -- die Meldung forderte den Nutzer
        zu einem Reset auf, den es nicht gab.

        Bewusst ein Dienst und kein Knopf in der Karte: eine Freigabe
        gehört hinter eine Handlung, die man nicht im Vorbeiwischen
        auslöst. Wer hier landet, hat gerade den Stecker in der Hand.
        """
        coordinator = _get_coordinator(hass)
        if coordinator is None:
            _LOGGER.warning("clear_emergency: kein aktiver Coordinator")
            return

        gewuenscht = call.data.get("zone")
        verriegelt = coordinator.safety_manager.emergency_zones()
        if not verriegelt:
            _LOGGER.info("clear_emergency: keine Zone ist verriegelt")
            return

        # Ohne Angabe alle -- wer nach einem Not-Aus zurücksetzt, will das
        # Bett wieder benutzen, nicht die Hälfte davon.
        zonen = [gewuenscht - 1] if gewuenscht else verriegelt

        from homeassistant.components.persistent_notification import (
            async_dismiss as notify_dismiss,
        )

        for zone_idx in zonen:
            coordinator.safety_manager.clear_emergency(zone_idx)
            # Die Meldung mitnehmen: eine Warnung, die nach der Freigabe
            # stehen bleibt, erzieht den Nutzer dazu, sie wegzuklicken
            # ohne sie zu lesen.
            notify_dismiss(hass, f"rejuvenation_bed_emergency_{zone_idx}")
            _LOGGER.warning(f"Zone {zone_idx + 1}: Not-Aus manuell freigegeben")

        await coordinator.async_request_refresh()

    # Services registrieren
    hass.services.async_register(DOMAIN, "set_boost", handle_set_boost, schema=SERVICE_SET_BOOST_SCHEMA)
    hass.services.async_register(
        DOMAIN, "clear_emergency", handle_clear_emergency, schema=SERVICE_CLEAR_EMERGENCY_SCHEMA
    )
    hass.services.async_register(DOMAIN, "set_sick_mode", handle_set_sick_mode, schema=SERVICE_SET_SICK_MODE_SCHEMA)
    hass.services.async_register(DOMAIN, "set_vacation_mode", handle_set_vacation, schema=SERVICE_SET_VACATION_SCHEMA)
    hass.services.async_register(DOMAIN, "cancel_special_mode", handle_cancel_special_mode)
    hass.services.async_register(DOMAIN, "reset_energy_budget", handle_reset_energy_budget)
    hass.services.async_register(DOMAIN, "preheat_bed", handle_preheat, schema=SERVICE_PREHEAT_SCHEMA)

    _LOGGER.info("Rejuvenation Bed Services registriert")


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Sicheres Entladen der Integration."""

    # Heizungen werden beim Entladen BEWUSST nicht abgeschaltet: Für ein
    # Wasserbett wäre Auskühlen riskanter als Weiterlaufen, und der
    # Hardware-Thermostat bleibt unabhängig vom HA-Zustand als Schutz aktiv.
    coordinator = hass.data[DOMAIN].get(entry.entry_id)
    if coordinator:
        _LOGGER.info("Entlade Integration (Heizungen laufen abgesichert weiter).")

    # Plattformen entladen
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # Speicher bereinigen
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

    # #6: Globale Services nur entfernen, wenn kein Coordinator mehr übrig ist
    if not any(isinstance(v, RejuvenationBedCoordinator) for v in hass.data.get(DOMAIN, {}).values()):
        for service in [
            "clear_emergency",
            "set_boost",
            "set_sick_mode",
            "set_vacation_mode",
            "cancel_special_mode",
            "reset_energy_budget",
            "preheat_bed",
        ]:
            hass.services.async_remove(DOMAIN, service)

    return unload_ok
