"""
Options Flow für das Rejuvenation Bed.

Vier Bereiche, logisch getrennt:

  🌐 Globale Einstellungen
     ├── Zeitfenster (warm_from, warm_until)
     ├── Temperatur (summer_threshold, temperature_offset)
     └── Sensoren (solar, preis, CO₂)

  📡 Zonen-Sensoren (Hardware pro Zone)
     ├── Heizungsschalter (Pflicht)
     ├── Kern-Sensoren (Temperatur, Leistung)
     └── Komfort-Sensoren (Präsenz, Feuchtigkeit, Luft)

  🌡️ Schlaf-Profil (pro Zone)
     ├── Wecker (Alarm-Entity, Wochenende)
     ├── Temperaturen (Einschlaf, Tiefschlaf, Aufwach)
     └── Wearable (Schlafphasen-Sensor)

  🎛️ Sondermodi
     ├── Krank (Temperatur, Dauer)
     ├── Boost (Offset)
     ├── Urlaub (Haltetemperatur)
     └── Komfort (Ausschlafen-Offset)
"""

import voluptuous as vol
import logging
from homeassistant import config_entries
from homeassistant.helpers import selector
from .const import (
    DEFAULT_SICK_MODE_TEMP,
    DEFAULT_SICK_MODE_DAYS,
    DEFAULT_SUMMER_TEMP,
    DEFAULT_BOOST_OFFSET,
    DEFAULT_COMFORT_OFFSET,
    DEFAULT_BED_BOOST_SOC_THRESHOLD,
    DEFAULT_BED_BOOST_MIN_FORECAST_KWH,
)

_LOGGER = logging.getLogger(__name__)


class RejuvenationBedOptionsFlow(config_entries.OptionsFlow):
    """Options Flow Handler."""

    def __init__(self, config_entry):
        self._config_entry = config_entry
        self._editing_zone_index = 0

    # ═══════════════════════════════════════════════════════════════════════
    # HAUPTMENÜ
    # ═══════════════════════════════════════════════════════════════════════

    async def async_step_init(self, user_input=None):
        """Hauptmenü: Was soll konfiguriert werden?"""
        return self.async_show_menu(
            step_id="init",
            menu_options={
                "global_settings": "🌐 Globale Einstellungen",
                "zone_sensors": "📡 Zonen-Sensoren",
                "zone_settings": "🌡️ Schlaf-Profil",
                "mode_settings": "🎛️ Sondermodi",
            },
        )

    # ═══════════════════════════════════════════════════════════════════════
    # 🌐 GLOBALE EINSTELLUNGEN (Sub-Menü)
    # ═══════════════════════════════════════════════════════════════════════

    async def async_step_global_settings(self, user_input=None):
        """Globale Einstellungen: Sub-Menü."""
        return self.async_show_menu(
            step_id="global_settings",
            menu_options={
                "global_times": "🌡️ Temperatur & Bett",
                "global_sensors": "📊 Sensoren & Strompreis",
            },
        )

    async def async_step_global_times(self, user_input=None):
        """Temperatur-Grenzen und Bett-Eigenschaften."""
        if user_input is not None:
            new_options = {**self._config_entry.options, **user_input}
            return self.async_create_entry(title="", data=new_options)

        current = self._config_entry.options
        global_data = self._config_entry.data.get("global", {})

        def _val(key, fallback=None):
            return current.get(key, global_data.get(key, fallback))

        return self.async_show_form(
            step_id="global_times",
            data_schema=vol.Schema({

                vol.Optional(
                    "summer_threshold",
                    default=_val("summer_threshold", DEFAULT_SUMMER_TEMP)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=15, max=35, step=1,
                        unit_of_measurement="°C",
                        mode=selector.NumberSelectorMode.SLIDER
                    )
                ),

                vol.Optional(
                    "temperature_offset",
                    default=_val("temperature_offset", 0.0)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=-3.0, max=3.0, step=0.5,
                        unit_of_measurement="°C",
                        mode=selector.NumberSelectorMode.SLIDER
                    )
                ),

                vol.Optional(
                    "bed_volume_liters",
                    default=_val("bed_volume_liters", 250)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=100, max=1200, step=50,
                        unit_of_measurement="L",
                        mode=selector.NumberSelectorMode.SLIDER
                    )
                ),
            }),
        )

    async def async_step_global_sensors(self, user_input=None):
        """Sensoren und Strompreis."""
        if user_input is not None:
            new_options = dict(self._config_entry.options)
            optional_sensors = {
                "solar_sensor",
                "price_sensor",
                "co2_sensor",
                "battery_soc_sensor",
                "forecast_sensor",
            }
            for key, value in user_input.items():
                if key in optional_sensors and (value is None or value == ""):
                    new_options.pop(key, None)
                else:
                    new_options[key] = value
            return self.async_create_entry(title="", data=new_options)

        current = self._config_entry.options
        global_data = self._config_entry.data.get("global", {})

        def _val(key, fallback=None):
            return current.get(key, global_data.get(key, fallback))

        return self.async_show_form(
            step_id="global_sensors",
            data_schema=vol.Schema({

                # ─── Strompreis ───────────────────────────────────
                vol.Optional(
                    "electricity_price",
                    default=_val("electricity_price", 30.0)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=5.0, max=80.0, step=0.5,
                        unit_of_measurement="ct/kWh",
                        mode=selector.NumberSelectorMode.SLIDER
                    )
                ),

                # ─── Dynamischer Preis-Sensor ─────────────────────
                vol.Optional(
                    "price_sensor",
                    description={"suggested_value": _val("price_sensor")}
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),

                # ─── Solar ────────────────────────────────────────
                vol.Optional(
                    "solar_sensor",
                    description={"suggested_value": _val("solar_sensor")}
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor", device_class="power"
                    )
                ),

                vol.Optional(
                    "solar_boost_threshold",
                    default=_val("solar_boost_threshold", 500)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=100, max=2000, step=50,
                        unit_of_measurement="W",
                        mode=selector.NumberSelectorMode.SLIDER
                    )
                ),

                # ─── PV-Prioritäts-Kaskade (optional) ─────────────
                # Hausakku + PV-Forecast geben dem Bett-Boost niedrigere
                # Priorität als Akku/Boiler. Ohne diese Sensoren bleibt
                # das klassische Verhalten erhalten.
                vol.Optional(
                    "battery_soc_sensor",
                    description={"suggested_value": _val("battery_soc_sensor")}
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor", device_class="battery"
                    )
                ),

                vol.Optional(
                    "bed_boost_soc_threshold",
                    default=_val(
                        "bed_boost_soc_threshold",
                        DEFAULT_BED_BOOST_SOC_THRESHOLD,
                    )
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=50, max=100, step=1,
                        unit_of_measurement="%",
                        mode=selector.NumberSelectorMode.SLIDER
                    )
                ),

                vol.Optional(
                    "forecast_sensor",
                    description={"suggested_value": _val("forecast_sensor")}
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),

                vol.Optional(
                    "bed_boost_min_forecast_kwh",
                    default=_val(
                        "bed_boost_min_forecast_kwh",
                        DEFAULT_BED_BOOST_MIN_FORECAST_KWH,
                    )
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.5, max=20.0, step=0.5,
                        unit_of_measurement="kWh",
                        mode=selector.NumberSelectorMode.SLIDER
                    )
                ),

                # ─── Akku-Vorrang (optional) ──────────────────────
                # AUS (Default): Solar-Schwelle, SoC und Forecast sind
                # unabhängige ODER-Trigger. AN: Akku/Boiler haben Vorrang,
                # die Solar-Schwelle löst nur mit (fast) vollem Akku /
                # üppiger Forecast aus.
                vol.Optional(
                    "battery_priority",
                    default=_val("battery_priority", False)
                ): selector.BooleanSelector(),

                # ─── CO₂ ──────────────────────────────────────────
                vol.Optional(
                    "co2_sensor",
                    description={"suggested_value": _val("co2_sensor")}
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor", device_class="carbon_dioxide"
                    )
                ),
            }),
        )

    # ═══════════════════════════════════════════════════════════════════════
    # 📡 ZONEN-SENSOREN (Hardware)
    # ═══════════════════════════════════════════════════════════════════════

    async def async_step_zone_sensors(self, user_input=None):
        """Zonen-Sensoren: Bei Dual-Zone erst auswählen."""
        zones = self._config_entry.data.get("zones", [])
        if not zones:
            return self.async_abort(reason="no_zones")

        if len(zones) > 1 and user_input is None:
            return self.async_show_form(
                step_id="zone_sensors",
                data_schema=vol.Schema({
                    vol.Required("zone_index", default="0"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {"value": "0", "label": "Zone 1 (Links)"},
                                {"value": "1", "label": "Zone 2 (Rechts)"},
                            ],
                            mode=selector.SelectSelectorMode.LIST
                        )
                    ),
                }),
            )

        if user_input is not None and "zone_index" in user_input:
            self._editing_zone_index = int(user_input["zone_index"])
            return await self.async_step_edit_zone_sensors()

        self._editing_zone_index = 0
        return await self.async_step_edit_zone_sensors()

    async def async_step_edit_zone_sensors(self, user_input=None):
        """Hardware-Sensoren einer Zone bearbeiten."""
        zone_index = self._editing_zone_index
        zones = self._config_entry.data.get("zones", [])
        if zone_index >= len(zones):
            return self.async_abort(reason="invalid_zone")

        current_zone = zones[zone_index]

        if user_input is not None:
            cleaned = {k: v for k, v in user_input.items() if v not in ("", None)}

            sensor_keys = {
                "heater", "temp_sensor", "power_sensor",
                "presence_sensor", "moisture_sensor", "air_temp_sensor"
            }
            new_zone = {k: v for k, v in current_zone.items() if k not in sensor_keys}
            new_zone.update(cleaned)
            new_zone["hardware_level"] = self._detect_hardware_level(new_zone)

            new_zones = list(zones)
            new_zones[zone_index] = new_zone
            new_data = {**self._config_entry.data, "zones": new_zones}

            self.hass.config_entries.async_update_entry(
                self._config_entry, data=new_data
            )
            _LOGGER.info(f"Zone {zone_index} Sensoren aktualisiert: {cleaned}")
            return self.async_create_entry(title="", data=self._config_entry.options)

        zone_name = self._zone_display_name(zone_index, zones)
        schema_dict = {}

        # Pflicht: Heizungsschalter
        schema_dict[vol.Required(
            "heater", default=current_zone.get("heater", "")
        )] = selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain=["switch", "light", "number", "input_boolean"]
            )
        )

        # Optional: Kern-Sensoren
        self._add_optional_entity(
            schema_dict, "temp_sensor",
            current_zone.get("temp_sensor"),
            domain="sensor", device_class="temperature"
        )
        self._add_optional_entity(
            schema_dict, "power_sensor",
            current_zone.get("power_sensor"),
            domain="sensor", device_class="power"
        )

        # Optional: Komfort-Sensoren
        self._add_optional_entity(
            schema_dict, "presence_sensor",
            current_zone.get("presence_sensor"),
            domain="binary_sensor", device_class="occupancy"
        )
        self._add_optional_entity(
            schema_dict, "moisture_sensor",
            current_zone.get("moisture_sensor"),
            domain="sensor", device_class="humidity"
        )
        self._add_optional_entity(
            schema_dict, "air_temp_sensor",
            current_zone.get("air_temp_sensor"),
            domain="sensor", device_class="temperature"
        )

        return self.async_show_form(
            step_id="edit_zone_sensors",
            data_schema=vol.Schema(schema_dict),
            description_placeholders={"zone_name": zone_name},
        )

    # ═══════════════════════════════════════════════════════════════════════
    # 🌡️ SCHLAF-PROFIL (pro Zone)
    # ═══════════════════════════════════════════════════════════════════════

    async def async_step_zone_settings(self, user_input=None):
        """Schlaf-Profil: Bei Dual-Zone erst auswählen."""
        zones = self._config_entry.data.get("zones", [])
        if not zones:
            return self.async_abort(reason="no_zones")

        if len(zones) > 1 and user_input is None:
            return self.async_show_form(
                step_id="zone_settings_select",
                data_schema=vol.Schema({
                    vol.Required("zone_index", default="0"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {"value": "0", "label": "Zone 1 (Links)"},
                                {"value": "1", "label": "Zone 2 (Rechts)"},
                            ],
                            mode=selector.SelectSelectorMode.LIST
                        )
                    ),
                }),
            )

        if user_input is not None and "zone_index" in user_input:
            self._editing_zone_index = int(user_input["zone_index"])
            return await self.async_step_edit_zone_settings()

        self._editing_zone_index = 0
        return await self.async_step_edit_zone_settings()

    async def async_step_zone_settings_select(self, user_input=None):
        """Zone-Auswahl Weiterleitung."""
        if user_input is not None and "zone_index" in user_input:
            self._editing_zone_index = int(user_input["zone_index"])
            return await self.async_step_edit_zone_settings()
        self._editing_zone_index = 0
        return await self.async_step_edit_zone_settings()

    async def async_step_edit_zone_settings(self, user_input=None):
        """Schlaf-Profil einer Zone bearbeiten."""
        zone_index = self._editing_zone_index
        zones = self._config_entry.data.get("zones", [])
        if zone_index >= len(zones):
            return self.async_abort(reason="invalid_zone")

        opts = self._config_entry.options
        global_data = self._config_entry.data.get("global", {})
        prefix = f"zone_{zone_index}_"

        if user_input is not None:
            new_options = dict(opts)
            for key, value in user_input.items():
                if value not in (None, ""):
                    new_options[f"{prefix}{key}"] = value
                else:
                    new_options.pop(f"{prefix}{key}", None)
            return self.async_create_entry(title="", data=new_options)

        zone_name = self._zone_display_name(zone_index, zones)

        def _get(key, default=None):
            """Zone-Option lesen, Fallback auf Global."""
            return opts.get(f"{prefix}{key}",
                   opts.get(key,
                   global_data.get(key, default)))

        schema_dict = {}

        # ─── Zeitfenster (pro Zone!) ──────────────────────────
        schema_dict[vol.Required(
            "warm_from", default=_get("warm_from", "22:00")
        )] = selector.TimeSelector()

        schema_dict[vol.Required(
            "warm_until", default=_get("warm_until", "07:00")
        )] = selector.TimeSelector()

        # ─── Chronotyp (pro Zone!) ────────────────────────────
        schema_dict[vol.Required(
            "chronotype", default=_get("chronotype", "normal")
        )] = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    {"value": "lerche", "label": "🌅 Lerche (Frühaufsteher)"},
                    {"value": "normal", "label": "😊 Normal"},
                    {"value": "eule", "label": "🦉 Eule (Nachteule)"},
                ],
                mode=selector.SelectSelectorMode.LIST
            )
        )

        # ─── Wecker ───────────────────────────────────────────
        current_alarm = _get("alarm_entity")
        self._add_optional_entity(
            schema_dict, "alarm_entity", current_alarm,
            domain=["sensor", "input_datetime"]
        )

        schema_dict[vol.Optional(
            "weekend_offset_hours", default=_get("weekend_offset_hours", 1.5)
        )] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0.0, max=4.0, step=0.5,
                unit_of_measurement="h",
                mode=selector.NumberSelectorMode.SLIDER
            )
        )

        # ─── Schlaf-Temperaturen ──────────────────────────────
        for temp_key in ("sleep_temp", "deep_sleep_temp", "wake_temp"):
            current_val = opts.get(f"{prefix}{temp_key}")
            kwargs = {}
            if current_val is not None:
                kwargs["description"] = {"suggested_value": current_val}
            schema_dict[vol.Optional(temp_key, **kwargs)] = selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=24.0, max=36.0, step=0.5,
                    unit_of_measurement="°C",
                    mode=selector.NumberSelectorMode.SLIDER
                )
            )

        # ─── Wearable ────────────────────────────────────────
        self._add_optional_entity(
            schema_dict, "sleep_stage_entity",
            opts.get(f"{prefix}sleep_stage_entity"),
            domain="sensor"
        )

        return self.async_show_form(
            step_id="edit_zone_settings",
            data_schema=vol.Schema(schema_dict),
            description_placeholders={"zone_name": zone_name},
        )

    # ═══════════════════════════════════════════════════════════════════════
    # 🎛️ SONDERMODI
    # ═══════════════════════════════════════════════════════════════════════

    async def async_step_mode_settings(self, user_input=None):
        """Sondermodi: Krank, Boost, Urlaub, Komfort."""
        if user_input is not None:
            new_options = {**self._config_entry.options, **user_input}
            return self.async_create_entry(title="", data=new_options)

        current = self._config_entry.options

        return self.async_show_form(
            step_id="mode_settings",
            data_schema=vol.Schema({

                # ─── Krank ────────────────────────────────────────
                vol.Required(
                    "sick_mode_temp",
                    default=current.get("sick_mode_temp", DEFAULT_SICK_MODE_TEMP)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=28.0, max=35.0, step=0.5,
                        unit_of_measurement="°C",
                        mode=selector.NumberSelectorMode.SLIDER
                    )
                ),

                vol.Required(
                    "sick_mode_days",
                    default=current.get("sick_mode_days", DEFAULT_SICK_MODE_DAYS)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=14, step=1,
                        unit_of_measurement="Tage",
                        mode=selector.NumberSelectorMode.SLIDER
                    )
                ),

                # ─── Boost ────────────────────────────────────────
                vol.Required(
                    "boost_offset",
                    default=current.get("boost_offset", DEFAULT_BOOST_OFFSET)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.5, max=5.0, step=0.5,
                        unit_of_measurement="°C",
                        mode=selector.NumberSelectorMode.SLIDER
                    )
                ),

                # ─── Urlaub ───────────────────────────────────────
                vol.Required(
                    "away_temp",
                    default=current.get("away_temp", 24.0)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=22.0, max=26.0, step=0.5,
                        unit_of_measurement="°C",
                        mode=selector.NumberSelectorMode.SLIDER
                    )
                ),

                # ─── Komfort ──────────────────────────────────────
                vol.Required(
                    "comfort_offset",
                    default=current.get("comfort_offset", DEFAULT_COMFORT_OFFSET)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.0, max=3.0, step=0.5,
                        unit_of_measurement="°C",
                        mode=selector.NumberSelectorMode.SLIDER
                    )
                ),
            }),
        )

    # ═══════════════════════════════════════════════════════════════════════
    # HILFSFUNKTIONEN
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _add_optional_entity(schema_dict, key, current_value,
                             domain=None, device_class=None):
        """Optionalen Entity-Selector hinzufügen."""
        kwargs = {}
        if current_value:
            kwargs["description"] = {"suggested_value": current_value}

        entity_config = {}
        if domain:
            entity_config["domain"] = domain
        if device_class:
            entity_config["device_class"] = device_class

        schema_dict[vol.Optional(key, **kwargs)] = selector.EntitySelector(
            selector.EntitySelectorConfig(**entity_config)
        )

    @staticmethod
    def _detect_hardware_level(zone_config: dict) -> str:
        """Erkennt Hardware-Level basierend auf vorhandenen Sensoren."""
        has_temp = bool(zone_config.get("temp_sensor"))
        has_power = bool(zone_config.get("power_sensor"))
        has_air = bool(zone_config.get("air_temp_sensor"))
        has_moisture = bool(zone_config.get("moisture_sensor"))

        if has_temp and has_power and has_air and has_moisture:
            return "E"
        elif has_temp and has_power and (has_air or has_moisture):
            return "D"
        elif has_temp and has_power:
            return "C"
        elif has_temp:
            return "B+"
        elif has_power:
            return "B"
        return "A"

    @staticmethod
    def _zone_display_name(zone_index: int, zones: list) -> str:
        """Anzeigename für eine Zone."""
        if len(zones) == 1:
            return "Hauptzone"
        return "Links" if zone_index == 0 else "Rechts"
