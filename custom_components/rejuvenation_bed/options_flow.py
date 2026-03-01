"""
Options Flow für das Rejuvenation Bed.

Erlaubt nachträgliche Änderungen an:
- Globalen Einstellungen (Zeiten, Temperaturen)
- Zonen-Sensoren (Heizung, Temperatur, Präsenz, Feuchtigkeit etc.)
- Zonen-Einstellungen (Aufwachzeit, Schlaf-Temperaturen, Wearable)
- Modus-Einstellungen (Krank, Boost, Urlaub, Eco, Komfort)
"""

import voluptuous as vol
import logging
from homeassistant import config_entries
from homeassistant.helpers import selector
from .const import (
    DOMAIN,
    DEFAULT_SICK_MODE_TEMP,
    DEFAULT_SICK_MODE_DAYS,
    DEFAULT_SUMMER_TEMP,
    DEFAULT_BOOST_OFFSET,
    DEFAULT_COMFORT_OFFSET,
)

_LOGGER = logging.getLogger(__name__)


class RejuvenationBedOptionsFlow(config_entries.OptionsFlow):
    """Options Flow Handler."""

    def __init__(self, config_entry):
        """Initialisiere den Options Flow."""
        self._config_entry = config_entry
        self._editing_zone_index = 0

    # ═══════════════════════════════════════════════════════════════════════════
    # HAUPTMENÜ
    # ═══════════════════════════════════════════════════════════════════════════

    async def async_step_init(self, user_input=None):
        """Hauptmenü: Was soll konfiguriert werden?"""
        return self.async_show_menu(
            step_id="init",
            menu_options={
                "global_settings": "🌐 Globale Einstellungen",
                "zone_sensors": "📡 Zonen-Sensoren ändern",
                "zone_settings": "🌡️ Zonen-Einstellungen",
                "mode_settings": "🎛️ Modus-Einstellungen",
            },
        )

    # ═══════════════════════════════════════════════════════════════════════════
    # GLOBALE EINSTELLUNGEN
    # ═══════════════════════════════════════════════════════════════════════════

    async def async_step_global_settings(self, user_input=None):
        """Globale Einstellungen bearbeiten."""
        if user_input is not None:
            new_options = {**self._config_entry.options, **user_input}
            return self.async_create_entry(title="", data=new_options)

        current = self._config_entry.options
        global_data = self._config_entry.data.get("global", {})

        return self.async_show_form(
            step_id="global_settings",
            data_schema=vol.Schema({
                vol.Required(
                    "warm_from",
                    default=current.get("warm_from", global_data.get("warm_from", "22:00"))
                ): selector.TimeSelector(),

                vol.Required(
                    "warm_until",
                    default=current.get("warm_until", global_data.get("warm_until", "07:00"))
                ): selector.TimeSelector(),

                vol.Optional(
                    "summer_threshold",
                    default=current.get("summer_threshold", DEFAULT_SUMMER_TEMP)
                ): vol.All(vol.Coerce(int), vol.Range(min=15, max=35)),

                vol.Optional(
                    "temperature_offset",
                    default=current.get("temperature_offset", 0.0)
                ): vol.All(vol.Coerce(float), vol.Range(min=-3.0, max=3.0)),
            }),
        )

    # ═══════════════════════════════════════════════════════════════════════════
    # ZONEN-SENSOREN (Hardware)
    # ═══════════════════════════════════════════════════════════════════════════

    async def async_step_zone_sensors(self, user_input=None):
        """Zonen-Sensoren: Zuerst Zone auswählen (bei Dual)."""
        zones = self._config_entry.data.get("zones", [])

        if len(zones) == 0:
            return self.async_abort(reason="no_zones")

        # Bei mehreren Zonen: Erst Zone auswählen
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

        # Zone-Index ermitteln
        if user_input is not None and "zone_index" in user_input:
            zone_index = int(user_input["zone_index"])
            self._editing_zone_index = zone_index
            return await self.async_step_edit_zone_sensors()

        # Nur eine Zone → direkt bearbeiten
        self._editing_zone_index = 0
        return await self.async_step_edit_zone_sensors()

    async def async_step_edit_zone_sensors(self, user_input=None):
        """Sensoren einer Zone bearbeiten."""
        zone_index = self._editing_zone_index
        zones = self._config_entry.data.get("zones", [])

        if zone_index >= len(zones):
            return self.async_abort(reason="invalid_zone")

        current_zone = zones[zone_index]

        if user_input is not None:
            # Leere Strings entfernen (= Sensor deaktiviert)
            cleaned_input = {}
            for key, value in user_input.items():
                if value == "" or value is None:
                    pass  # Optionaler Sensor nicht gesetzt → weglassen
                else:
                    cleaned_input[key] = value

            # Bestehende nicht-sensor Felder beibehalten
            sensor_keys = {
                "heater", "temp_sensor", "power_sensor",
                "presence_sensor", "moisture_sensor", "air_temp_sensor",
                "co2_sensor"
            }
            new_zone = {
                k: v for k, v in current_zone.items()
                if k not in sensor_keys
            }

            # Neue Sensor-Werte überschreiben
            new_zone.update(cleaned_input)

            # Hardware-Level neu berechnen
            new_zone["hardware_level"] = self._detect_hardware_level(new_zone)

            new_zones = list(zones)
            new_zones[zone_index] = new_zone

            new_data = {**self._config_entry.data, "zones": new_zones}

            self.hass.config_entries.async_update_entry(
                self._config_entry,
                data=new_data
            )

            _LOGGER.info(
                f"Zone {zone_index} Sensoren aktualisiert: {cleaned_input}"
            )

            return self.async_create_entry(title="", data=self._config_entry.options)

        # Zone-Name für Anzeige
        zone_name = "Links" if zone_index == 0 else "Rechts"
        if len(zones) == 1:
            zone_name = "Hauptzone"

        # ───────────────────────────────────────────────────────────────────
        # Schema bauen:
        #   - Pflichtfelder (heater) mit default
        #   - Optionale Sensoren OHNE default="" → können leer bleiben!
        #   - suggested_value zeigt den aktuellen Wert an
        # ───────────────────────────────────────────────────────────────────
        schema_dict = {}

        # Pflicht: Heizungsschalter (muss immer gesetzt sein)
        schema_dict[vol.Required(
            "heater",
            default=current_zone.get("heater", "")
        )] = selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain=["switch", "light", "number", "input_boolean"]
            )
        )

        # Optional: Temperatursensor
        self._add_optional_entity(
            schema_dict, "temp_sensor",
            current_zone.get("temp_sensor"),
            domain="sensor", device_class="temperature"
        )

        # Optional: Leistungssensor
        self._add_optional_entity(
            schema_dict, "power_sensor",
            current_zone.get("power_sensor"),
            domain="sensor", device_class="power"
        )

        # Optional: Präsenzsensor (DAS WAR DER BUG! Kein default="" mehr!)
        self._add_optional_entity(
            schema_dict, "presence_sensor",
            current_zone.get("presence_sensor"),
            domain="binary_sensor", device_class="occupancy"
        )

        # Optional: Feuchtigkeitssensor
        self._add_optional_entity(
            schema_dict, "moisture_sensor",
            current_zone.get("moisture_sensor"),
            domain=["sensor", "binary_sensor"]
        )

        # Optional: Luft-/Oberflächentemperatur (SHT41 oben)
        self._add_optional_entity(
            schema_dict, "air_temp_sensor",
            current_zone.get("air_temp_sensor"),
            domain="sensor", device_class="temperature"
        )

        # Optional: CO2-Sensor (für Sleep-Score, 25% Gewichtung)
        self._add_optional_entity(
            schema_dict, "co2_sensor",
            current_zone.get("co2_sensor"),
            domain="sensor", device_class="carbon_dioxide"
        )

        return self.async_show_form(
            step_id="edit_zone_sensors",
            data_schema=vol.Schema(schema_dict),
            description_placeholders={
                "zone_name": zone_name,
            }
        )

    @staticmethod
    def _add_optional_entity(
        schema_dict: dict,
        key: str,
        current_value: str | None,
        **selector_kwargs
    ):
        """
        Fügt ein optionales Entity-Feld zum Schema hinzu.
        
        Wenn ein Wert gesetzt ist → suggested_value (zeigt aktuellen Wert).
        Wenn kein Wert → leeres Feld, OK ohne Auswahl möglich.
        """
        sel = selector.EntitySelector(
            selector.EntitySelectorConfig(**selector_kwargs)
        )
        if current_value:
            schema_dict[vol.Optional(
                key,
                description={"suggested_value": current_value}
            )] = sel
        else:
            schema_dict[vol.Optional(key)] = sel

    @staticmethod
    def _detect_hardware_level(zone_config: dict) -> str:
        """Hardware-Level erkennen (identisch zu config_flow)."""
        has_temp = zone_config.get("temp_sensor") is not None
        has_power = zone_config.get("power_sensor") is not None

        if has_temp:
            return "C"
        elif has_power:
            return "B"
        else:
            return "A"

    # ═══════════════════════════════════════════════════════════════════════════
    # ZONEN-EINSTELLUNGEN (Temperaturen, Aufwachzeit, Wearable)
    # ═══════════════════════════════════════════════════════════════════════════

    async def async_step_zone_settings(self, user_input=None):
        """Zonen-Einstellungen: Zuerst Zone auswählen (bei Dual)."""
        zones = self._config_entry.data.get("zones", [])

        if len(zones) == 0:
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
            zone_index = int(user_input["zone_index"])
            self._editing_zone_index = zone_index
            return await self.async_step_edit_zone_settings()

        self._editing_zone_index = 0
        return await self.async_step_edit_zone_settings()

    async def async_step_zone_settings_select(self, user_input=None):
        """Zone-Auswahl für Zonen-Einstellungen (bei Dual)."""
        if user_input is not None and "zone_index" in user_input:
            self._editing_zone_index = int(user_input["zone_index"])
            return await self.async_step_edit_zone_settings()

        # Fallback: Erste Zone
        self._editing_zone_index = 0
        return await self.async_step_edit_zone_settings()

    async def async_step_edit_zone_settings(self, user_input=None):
        """Individuelle Einstellungen pro Zone bearbeiten."""
        zone_index = self._editing_zone_index
        zones = self._config_entry.data.get("zones", [])

        if zone_index >= len(zones):
            return self.async_abort(reason="invalid_zone")

        current_opts = self._config_entry.options
        prefix = f"zone_{zone_index}_"

        if user_input is not None:
            new_options = dict(self._config_entry.options)
            for key, value in user_input.items():
                if value is not None and value != "":
                    new_options[f"{prefix}{key}"] = value
                else:
                    new_options.pop(f"{prefix}{key}", None)

            return self.async_create_entry(title="", data=new_options)

        zone_name = "Links" if zone_index == 0 else "Rechts"
        if len(zones) == 1:
            zone_name = "Hauptzone"

        def _get(key, default=None):
            return current_opts.get(f"{prefix}{key}", default)

        schema_dict = {}

        # Wecker-Entity (optional, für individuellen Wecker pro Zone)
        current_alarm = _get("alarm_entity")
        self._add_optional_entity(
            schema_dict, "alarm_entity", current_alarm,
            domain=["sensor", "input_datetime"]
        )

        # Wochenend-Ausschlafen
        schema_dict[vol.Optional(
            "weekend_offset_hours",
            default=_get("weekend_offset_hours", 1.5)
        )] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0.0, max=4.0, step=0.5,
                unit_of_measurement="h",
                mode=selector.NumberSelectorMode.SLIDER
            )
        )

        # Schlaf-Temperaturen (optional → leer = saisonal automatisch)
        for temp_key, temp_default in [
            ("sleep_temp", None),
            ("deep_sleep_temp", None),
            ("wake_temp", None),
        ]:
            current_val = _get(temp_key)
            if current_val is not None:
                schema_dict[vol.Optional(
                    temp_key,
                    description={"suggested_value": current_val}
                )] = selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=24.0, max=36.0, step=0.5,
                        unit_of_measurement="°C",
                        mode=selector.NumberSelectorMode.SLIDER
                    )
                )
            else:
                schema_dict[vol.Optional(temp_key)] = selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=24.0, max=36.0, step=0.5,
                        unit_of_measurement="°C",
                        mode=selector.NumberSelectorMode.SLIDER
                    )
                )

        # Wearable Schlafphasen-Sensor (optional)
        self._add_optional_entity(
            schema_dict, "sleep_stage_entity",
            _get("sleep_stage_entity"),
            domain="sensor"
        )

        return self.async_show_form(
            step_id="edit_zone_settings",
            data_schema=vol.Schema(schema_dict),
            description_placeholders={
                "zone_name": zone_name,
            }
        )

    # ═══════════════════════════════════════════════════════════════════════════
    # MODUS-EINSTELLUNGEN
    # ═══════════════════════════════════════════════════════════════════════════

    async def async_step_mode_settings(self, user_input=None):
        """Modus-Einstellungen bearbeiten."""
        if user_input is not None:
            new_options = {**self._config_entry.options, **user_input}
            return self.async_create_entry(title="", data=new_options)

        current = self._config_entry.options

        return self.async_show_form(
            step_id="mode_settings",
            data_schema=vol.Schema({
                # Krank-Modus
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

                # Boost
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

                # Urlaub
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

                # Komfort / Ausschlafen
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
