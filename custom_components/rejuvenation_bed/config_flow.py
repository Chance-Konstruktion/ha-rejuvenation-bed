import voluptuous as vol
import logging
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from .const import (
    DOMAIN, 
    DEFAULT_POWER, 
    DEFAULT_SUMMER_TEMP
)

_LOGGER = logging.getLogger(__name__)

class RejuvenationBedConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handhabt den kompletten Konfigurations-Flow für das Rejuvenation Bed."""
    VERSION = 2

    def __init__(self):
        self._data = {"zones": [], "global": {}}
        self._zones_count = 1

    async def async_step_user(self, user_input=None):
        """Schritt 1: Auswahl der Zonen-Anzahl (Mono oder Dual)."""
        if user_input is not None:
            self._zones_count = int(user_input["zones"])
            return await self.async_step_bed_type()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("zones", default="1"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": "1", "label": "1 Zone (Mono)"}, 
                            {"value": "2", "label": "2 Zonen (Dual)"}
                        ],
                        mode=selector.SelectSelectorMode.LIST
                    )
                )
            })
        )

    async def async_step_bed_type(self, user_input=None):
        """Schritt 2: Bett-Typ Auswahl (VOR den Zonen!)."""
        if user_input is not None:
            self._data["global"]["bed_type"] = user_input["bed_type"]
            return await self.async_step_safety_info()

        return self.async_show_form(
            step_id="bed_type",
            data_schema=vol.Schema({
                vol.Required("bed_type", default="wasserbett"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": "wasserbett", "label": "💧 Wasserbett"},
                            {"value": "heizmatte", "label": "⚡ Heizmatte / Wärmeunterbett"},
                        ],
                        mode=selector.SelectSelectorMode.LIST
                    )
                ),
            }),
        )

    async def async_step_safety_info(self, user_input=None):
        """Schritt 3: Wichtiger Sicherheitshinweis zur Hardware-Einstellung."""
        if user_input is not None:
            return await self.async_step_zone_config()

        # FIX: Explizite description_placeholders für Warnhinweis
        return self.async_show_form(
            step_id="safety_info",
            description_placeholders={
                "warning_text": (
                    "⚠️ WICHTIG: Stelle sicher, dass der physische Thermostat "
                    "deiner Bett-Heizung auf MAXIMUM (38°C) gestellt ist!\n\n"
                    "Nur so kann Home Assistant die Temperatur präzise regeln.\n\n"
                    "Der Hardware-Thermostat bleibt als Sicherheits-Backup im Stromkreis!"
                )
            }
        )

    async def async_step_zone_config(self, user_input=None):
        """Schritt 4: Hardware-Details pro Heizzone."""
        current_zone_index = len(self._data["zones"]) + 1
        
        if self._zones_count == 1:
            zone_key = "main_zone"
        else:
            zone_key = "left_side" if current_zone_index == 1 else "right_side"

        if user_input is not None:
            user_input["zone_key"] = zone_key 
            
            # Hardware-Level erkennen
            hardware_level = self._detect_hardware_level(user_input)
            user_input["hardware_level"] = hardware_level
            
            self._data["zones"].append(user_input)
            
            _LOGGER.info(
                f"Zone {current_zone_index}: Hardware-Level '{hardware_level}' erkannt"
            )
            
            if len(self._data["zones"]) < self._zones_count:
                return await self.async_step_zone_config()
            
            return await self.async_step_hardware_summary()

        # Zonen-Label für UI
        zone_labels = {
            "main_zone": "Hauptmatratze",
            "left_side": "Linke Seite", 
            "right_side": "Rechte Seite"
        }
        zone_label = zone_labels.get(zone_key, f"Zone {current_zone_index}")

        return self.async_show_form(
            step_id="zone_config",
            description_placeholders={"zone_info": zone_label},
            data_schema=vol.Schema({
                vol.Required("heater"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["switch", "light", "number", "input_boolean"])
                ),
                vol.Optional("temp_sensor"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
                vol.Required("hardware_max", default=36): vol.All(
                    vol.Coerce(int), vol.Range(min=25, max=38)
                ),
                vol.Required("boost_target_temp", default=34): vol.All(
                    vol.Coerce(int), vol.Range(min=25, max=38)
                ),
                vol.Required("power_rating", default=DEFAULT_POWER): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=1000)
                ),
                vol.Optional("power_sensor"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="power")
                ),
                vol.Optional("presence_sensor"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="binary_sensor", device_class="occupancy")
                ),
                # ═══════════════════════════════════════════════════════════════════
                # FIX: Feuchtigkeitssensor - BEIDE Typen erlauben!
                # binary_sensor mit device_class moisture ODER normaler sensor mit humidity
                # ═══════════════════════════════════════════════════════════════════
                vol.Optional("moisture_sensor"): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor", device_class="humidity"
                    )
                ),
                # ═══════════════════════════════════════════════════════════════════
                # NEU: Optionaler Luft-/Oberflächentemperatur-Sensor (z.B. SHT41)
                # Ermöglicht: Isolations-Erkennung, Schwitz 2.0, bessere Präsenz
                # ═══════════════════════════════════════════════════════════════════
                vol.Optional("air_temp_sensor"): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor", device_class="temperature"
                    )
                ),
            })
        )
    
    def _detect_hardware_level(self, zone_config: dict) -> str:
        """
        Erkennt Hardware-Level basierend auf konfigurierten Sensoren.
        
        Level A (Basic): Nur Relay
        Level B (Smart): Relay + Power-Monitoring
        Level C (Verjüngungsbrunnen): Relay + Power + Temp
        
        Returns:
            "A", "B" oder "C"
        """
        has_temp = zone_config.get("temp_sensor") is not None
        has_power = zone_config.get("power_sensor") is not None
        
        if has_temp:
            return "C"  # Vollausstattung - Alle Features!
        elif has_power:
            return "B"  # Smart - Präsenz-Erkennung + Solar-Batterie
        else:
            return "A"  # Basic - Nur Zeitschaltuhr
    
    async def async_step_hardware_summary(self, user_input=None):
        """
        NEU: Zeigt User, welche Features mit seinem Hardware-Setup verfügbar sind.
        """
        if user_input is not None:
            return await self.async_step_energy_config()
        
        # Erstelle Feature-Matrix
        features_available = []
        features_unavailable = []
        
        for idx, zone in enumerate(self._data["zones"]):
            level = zone.get("hardware_level", "A")
            zone_name = f"Zone {idx + 1}"
            
            if level == "C":
                features_available.append(f"✅ {zone_name}: VERJÜNGUNGSBRUNNEN")
                features_available.append("   • Biorhythmus-Kurve mit Schlafphasen")
                features_available.append("   • Präsenz-Erkennung (Sensor-Fusion)")
                features_available.append("   • Solar-Batterie-Modus")
                features_available.append("   • Alle Sicherheits-Features")
            elif level == "B":
                features_available.append(f"✅ {zone_name}: SMART")
                features_available.append("   • Präsenz-Erkennung (Heizverhalten)")
                features_available.append("   • Solar-Batterie-Modus")
                features_available.append("   • Energie-Statistiken")
                features_unavailable.append(f"❌ {zone_name}: Biorhythmus-Kurve")
                features_unavailable.append("   → Benötigt Temperatur-Sensor!")
            else:  # Level A
                features_available.append(f"✅ {zone_name}: BASIC")
                features_available.append("   • Zeitschaltuhr (Energie sparen)")
                features_available.append("   • Manueller Boost")
                features_unavailable.append(f"❌ {zone_name}: Biorhythmus-Kurve")
                features_unavailable.append(f"❌ {zone_name}: Solar-Batterie")
                features_unavailable.append("   → Benötigt Temperatur + Power-Sensor!")
        
        summary_text = "\n".join(features_available)
        if features_unavailable:
            summary_text += "\n\n" + "\n".join(features_unavailable)
        
        return self.async_show_form(
            step_id="hardware_summary",
            description_placeholders={
                "features": summary_text
            }
        )

    async def async_step_energy_config(self, user_input=None):
        """
        NEU: Energie-Tracking Konfiguration.
        """
        if user_input is not None:
            self._data["energy"] = user_input
            return await self.async_step_global_config()
        
        # Prüfe ob Power-Sensor bereits konfiguriert ist
        has_power_sensor = any(
            zone.get("power_sensor") for zone in self._data["zones"]
        )
        
        # Berechne Gesamt-Nennleistung aus Zonen
        total_power_rating = sum(
            zone.get("power_rating", DEFAULT_POWER) 
            for zone in self._data["zones"]
        )
        
        return self.async_show_form(
            step_id="energy_config",
            data_schema=vol.Schema({
                vol.Required("enable_tracking", default=True): selector.BooleanSelector(),
                
                vol.Required("total_power_rating", default=total_power_rating): vol.All(
                    vol.Coerce(int), vol.Range(min=50, max=2000)
                ),
                
                vol.Optional("energy_sensor"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="energy")
                ),
                
                vol.Required("compare_to_legacy", default=True): selector.BooleanSelector(),
                
                vol.Optional("electricity_price", default=0.30): vol.All(
                    vol.Coerce(float), vol.Range(min=0.05, max=1.0)
                ),
            }),
            description_placeholders={
                "has_power_sensor": "✓" if has_power_sensor else "✗",
                "total_power": str(total_power_rating),
            }
        )

    async def async_step_global_config(self, user_input=None):
        """Schritt 7: Globale Parameter (Warmhalte-Zeitfenster, Chronotyp, etc.)."""
        if user_input is not None:
            # Merge mit bereits gesetztem bed_type
            if "energy" in self._data and "electricity_price" in self._data["energy"]:
                self._data["global"].setdefault(
                    "electricity_price", self._data["energy"]["electricity_price"]
                )
            self._data["global"].update(user_input)
            return self.async_create_entry(title="Rejuvenation Bed", data=self._data)

        return self.async_show_form(
            step_id="global_config",
            data_schema=vol.Schema({
                # NEU: Warmhalte-Zeitfenster statt nur Schlafzeit
                vol.Required("warm_from", default="22:00"): selector.TimeSelector(),
                vol.Required("warm_until", default="07:00"): selector.TimeSelector(),
                
                # Wecker-Entity: ALLE Sensoren erlauben (nicht nur mit bestimmtem Namen)
                vol.Optional("alarm_entity"): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["sensor", "input_datetime"],
                        multiple=False
                    )
                ),
                
                # Chronotyp (Lerche/Eule) - MIT deutschen Labels
                vol.Required("chronotype", default="normal"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": "lerche", "label": "🌅 Lerche (Frühaufsteher)"},
                            {"value": "normal", "label": "😊 Normal"},
                            {"value": "eule", "label": "🦉 Eule (Nachteule)"},
                        ],
                        mode=selector.SelectSelectorMode.LIST
                    )
                ),
                
                vol.Optional("solar_sensor"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="power")
                ),
                vol.Optional("price_sensor"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                    # FIX: device_class "monetary" existiert nicht in allen HA-Versionen
                    # Daher kein device_class Filter
                ),
                # ═══════════════════════════════════════════════════════════════════
                # FIX: Outdoor-Sensor - weather.* UND sensor.* erlauben
                # ═══════════════════════════════════════════════════════════════════
                vol.Optional("outdoor_sensor"): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["sensor", "weather"],
                        # KEIN device_class - weather entities haben keinen!
                    )
                ),
                # ═══════════════════════════════════════════════════════════════════
                # FIX: CO2-Sensor - ALLE Sensoren erlauben, nicht nur device_class
                # Manche CO2-Sensoren haben keinen device_class gesetzt!
                # ═══════════════════════════════════════════════════════════════════
                vol.Optional("co2_sensor"): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor", device_class="carbon_dioxide"
                    )
                ),
                vol.Optional("summer_threshold", default=DEFAULT_SUMMER_TEMP): vol.All(
                    vol.Coerce(int), vol.Range(min=15, max=35)
                ),
                vol.Optional("bed_volume_liters", default=250): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=100, max=1200, step=50,
                        unit_of_measurement="L",
                        mode=selector.NumberSelectorMode.SLIDER
                    )
                ),
            })
        )
    
    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Gibt den Options-Flow zurück."""
        from .options_flow import RejuvenationBedOptionsFlow
        return RejuvenationBedOptionsFlow(config_entry)
