"""
Berechnet Strompreis-Status und Battery-Boost-Logik.
"""
import logging
from typing import Dict

_LOGGER = logging.getLogger(__name__)

class EnergyCalculator:
    """Berechnet Energie- und Kostenoptimierung."""

    def __init__(self, hass, config_entry):
        self.hass = hass
        self.config_entry = config_entry

    async def async_calculate(self) -> Dict:
        """
        Berechnet den aktuellen Energie-Status basierend auf konfigurierten Sensoren.
        """
        global_conf = self.config_entry.data.get("global", {})
        
        # 1. Solar-Leistung abfragen
        solar_sensor = global_conf.get("solar_sensor")
        solar_power = 0.0
        if solar_sensor:
            state = self.hass.states.get(solar_sensor)
            if state and state.state not in ["unknown", "unavailable"]:
                solar_power = float(state.state)

        # 2. Strompreis abfragen
        price_sensor = global_conf.get("price_sensor")
        current_price = 0.30  # Default Fallback
        price_status = "normal"
        
        if price_sensor:
            state = self.hass.states.get(price_sensor)
            if state and state.state not in ["unknown", "unavailable"]:
                current_price = float(state.state)
                # Einfache Logik: Preis-Status basierend auf Schwellenwerten 
                # (Könnte später dynamisch via Attributen des Sensors verbessert werden)
                if current_price < 0.20:
                    price_status = "cheap"
                elif current_price > 0.35:
                    price_status = "expensive"

        # 3. Boost-Entscheidung (Die "Batterie"-Logik)
        # Wir boosten, wenn Solarstrom > 500W ODER Strompreis sehr günstig ist
        battery_boost_active = (solar_power > 500) or (price_status == "cheap")

        return {
            "current_price": current_price,
            "price_status": price_status,
            "solar_power": solar_power,
            "battery_boost_active": battery_boost_active,
            "daily_savings": 0.0  # Platzhalter für spätere Integration
        }