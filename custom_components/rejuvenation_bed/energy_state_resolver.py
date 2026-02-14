"""
Energy-State-Resolver für das Rejuvenation Bed.

Erweitert den energy_calculator.py um intelligente Entscheidungslogik:

KERNPRINZIP: "Das Bett darf NIE zu kalt werden!"

Modi:
1. SOLAR_BOOST: Überschuss-Energie → Bett als thermische Batterie
2. ECO_MODE: Teurer Strom → Minimale Komforttemperatur
3. NORMAL: Standard-Biorhythmus

Wichtig: Energie-Logik wirkt ADDITIV, nie destruktiv!
"""

import logging
from typing import Optional
from homeassistant.core import HomeAssistant
from enum import Enum

_LOGGER = logging.getLogger(__name__)


class EnergyMode(Enum):
    """Energie-Betriebsmodi des Betts."""
    NORMAL = "normal"               # Standard-Biorhythmus
    SOLAR_BOOST = "solar_boost"     # Überschuss-Energie nutzen
    ECO_MODE = "eco_mode"           # Energie sparen (teurer Strom)
    GRID_CRITICAL = "grid_critical" # Netz-Engpass (sehr selten)


class EnergyStateResolver:
    """
    Entscheidet, wie Energie-Verfügbarkeit die Temperatur beeinflusst.
    
    Arbeitet mit dem EnergyCalculator zusammen, aber fügt Logik hinzu.
    NEU: Mit Hysterese für stabiles Schaltverhalten!
    """
    
    # Schwellenwerte MIT Hysterese (verhindert Flattern!)
    SOLAR_BOOST_ON_W = 500       # Einschalten bei >= 500W
    SOLAR_BOOST_OFF_W = 450      # Ausschalten bei < 450W (Hysterese!)
    
    ECO_PRICE_ON_EUR = 0.35      # Eco einschalten bei >= 35ct
    ECO_PRICE_OFF_EUR = 0.32     # Eco ausschalten bei < 32ct (Hysterese!)
    
    CHEAP_PRICE_THRESHOLD_EUR = 0.15  # Unter 15 ct/kWh → wie Solar
    
    # Temperatur-Offsets (additiv zur Biorhythmus-Kurve)
    SOLAR_BOOST_OFFSET = +1.5   # Solar-Überschuss → +1.5°C
    ECO_OFFSET = -2.0           # Teurer Strom → -2.0°C
    CRITICAL_OFFSET = -3.0      # Netz-Notfall → -3.0°C (sehr selten)
    
    # Anti-Kalt-Garantie: Absolutes Minimum
    ABSOLUTE_MIN_TEMP = 25.0    # Niemals unter 25°C, egal was passiert!
    
    def __init__(
        self,
        hass: HomeAssistant,
        config_entry
    ):
        """
        Initialisiert den Energy-State-Resolver.
        
        Args:
            hass: Home Assistant Instanz
            config_entry: ConfigEntry mit globalen Einstellungen
        """
        self.hass = hass
        self.config_entry = config_entry
        self.global_config = config_entry.data.get("global", {})
        
        # Sensor-Entity-IDs
        self.solar_sensor = self.global_config.get("solar_sensor")
        self.price_sensor = self.global_config.get("price_sensor")
        
        # NEU: Zustand für Hysterese merken
        self._current_mode = EnergyMode.NORMAL
    
    def resolve(self) -> dict:
        """
        Hauptfunktion: Ermittelt den aktuellen Energie-Zustand.
        
        Returns:
            Dict mit:
            - mode: EnergyMode
            - temperature_offset: float (additiv zur Kurve)
            - solar_power: float (aktuelle Solar-Leistung)
            - current_price: float (aktueller Strompreis)
            - reason: str (Erklärung für UI)
        """
        # Schritt 1: Aktuelle Werte auslesen
        solar_power = self._read_solar_power()
        current_price = self._read_energy_price()
        
        # Schritt 2: Modus ermitteln
        mode = self._determine_mode(solar_power, current_price)
        
        # Schritt 3: Temperatur-Offset berechnen
        temp_offset = self._calculate_offset(mode)
        
        # Schritt 4: Erklärung generieren
        reason = self._generate_reason(mode, solar_power, current_price)
        
        return {
            "mode": mode,
            "temperature_offset": temp_offset,
            "solar_power": solar_power,
            "current_price": current_price,
            "reason": reason,
            "boost_available": mode == EnergyMode.SOLAR_BOOST,
        }
    
    def _read_solar_power(self) -> float:
        """
        Liest die aktuelle Solar-Leistung aus dem Sensor.
        
        Returns:
            Leistung in Watt (0.0 wenn nicht verfügbar)
        """
        if not self.solar_sensor:
            return 0.0
        
        state = self.hass.states.get(self.solar_sensor)
        
        if not state or state.state in ["unknown", "unavailable"]:
            return 0.0
        
        try:
            return float(state.state)
        except (ValueError, TypeError):
            _LOGGER.warning(
                f"Konnte Solar-Sensor '{self.solar_sensor}' nicht als Zahl lesen: "
                f"{state.state}"
            )
            return 0.0
    
    def _read_energy_price(self) -> float:
        """
        Liest den aktuellen Strompreis aus dem Sensor.
        
        Returns:
            Preis in EUR/kWh (0.30 als Default-Fallback)
        """
        if not self.price_sensor:
            return 0.30  # Durchschnittlicher Strompreis als Fallback
        
        state = self.hass.states.get(self.price_sensor)
        
        if not state or state.state in ["unknown", "unavailable"]:
            return 0.30
        
        try:
            return float(state.state)
        except (ValueError, TypeError):
            _LOGGER.warning(
                f"Konnte Preis-Sensor '{self.price_sensor}' nicht als Zahl lesen: "
                f"{state.state}"
            )
            return 0.30
    
    def _determine_mode(self, solar_power: float, price: float) -> EnergyMode:
        """
        Entscheidet basierend auf Solar + Preis den Betriebsmodus.
        
        NEU: Mit Hysterese für stabiles Schaltverhalten!
        
        Priorität (höchste zuerst):
        1. Solar-Boost (viel Überschuss)
        2. Günstiger Strom (wie Solar behandeln)
        3. Eco-Mode (teuer)
        4. Normal (alles andere)
        """
        # Solar-Boost mit Hysterese
        if self._current_mode == EnergyMode.SOLAR_BOOST:
            # Bereits aktiv → nur ausschalten wenn unter OFF-Schwelle
            if solar_power >= self.SOLAR_BOOST_OFF_W:
                return EnergyMode.SOLAR_BOOST
            # Unter OFF-Schwelle → prüfe andere Modi
        else:
            # Noch nicht aktiv → einschalten bei ON-Schwelle
            if solar_power >= self.SOLAR_BOOST_ON_W:
                self._current_mode = EnergyMode.SOLAR_BOOST
                return EnergyMode.SOLAR_BOOST
        
        # Prio 2: Sehr günstiger Strom (z.B. nachts) - keine Hysterese nötig
        if price <= self.CHEAP_PRICE_THRESHOLD_EUR:
            self._current_mode = EnergyMode.SOLAR_BOOST  # Behandeln wie Solar
            return EnergyMode.SOLAR_BOOST
        
        # Eco-Mode mit Hysterese
        if self._current_mode == EnergyMode.ECO_MODE:
            # Bereits aktiv → nur ausschalten wenn unter OFF-Schwelle
            if price >= self.ECO_PRICE_OFF_EUR:
                return EnergyMode.ECO_MODE
            # Unter OFF-Schwelle → Normal
        else:
            # Noch nicht aktiv → einschalten bei ON-Schwelle
            if price >= self.ECO_PRICE_ON_EUR:
                self._current_mode = EnergyMode.ECO_MODE
                return EnergyMode.ECO_MODE
        
        # Default: Normal
        self._current_mode = EnergyMode.NORMAL
        return EnergyMode.NORMAL
    
    def _calculate_offset(self, mode: EnergyMode) -> float:
        """
        Berechnet den Temperatur-Offset basierend auf dem Modus.
        
        WICHTIG: Offset wird zur Biorhythmus-Kurve ADDIERT,
        aber NIEMALS unter ABSOLUTE_MIN_TEMP!
        """
        offsets = {
            EnergyMode.NORMAL: 0.0,
            EnergyMode.SOLAR_BOOST: self.SOLAR_BOOST_OFFSET,
            EnergyMode.ECO_MODE: self.ECO_OFFSET,
            EnergyMode.GRID_CRITICAL: self.CRITICAL_OFFSET,
        }
        
        return offsets.get(mode, 0.0)
    
    def _generate_reason(
        self,
        mode: EnergyMode,
        solar_power: float,
        price: float
    ) -> str:
        """
        Generiert eine menschenlesbare Erklärung für das UI.
        """
        if mode == EnergyMode.SOLAR_BOOST:
            if solar_power > 0:
                return f"☀️ Solar-Boost aktiv ({solar_power:.0f}W Überschuss)"
            else:
                return f"💰 Günstiger Strom ({price:.2f} €/kWh)"
        
        elif mode == EnergyMode.ECO_MODE:
            return f"💡 Energie-Sparmodus ({price:.2f} €/kWh)"
        
        elif mode == EnergyMode.GRID_CRITICAL:
            return "⚠️ Netz-Notfall: Minimalbetrieb"
        
        else:
            return "✅ Normal-Betrieb"
    
    def apply_offset_safely(
        self,
        base_temp: float,
        offset: float
    ) -> float:
        """
        Wendet den Offset an, aber garantiert ABSOLUTE_MIN_TEMP.
        
        Args:
            base_temp: Temperatur aus der Biorhythmus-Kurve
            offset: Energie-Offset (kann negativ sein)
        
        Returns:
            Finale Temperatur (niemals < ABSOLUTE_MIN_TEMP)
        """
        final_temp = base_temp + offset
        
        # Anti-Kalt-Garantie!
        if final_temp < self.ABSOLUTE_MIN_TEMP:
            _LOGGER.warning(
                f"Energie-Offset würde zu {final_temp:.1f}°C führen. "
                f"Limitiere auf {self.ABSOLUTE_MIN_TEMP}°C (Anti-Kalt-Garantie)."
            )
            return self.ABSOLUTE_MIN_TEMP
        
        return round(final_temp, 2)
    
    def get_diagnostics(self) -> dict:
        """
        Gibt Debug-Informationen zurück.
        """
        state = self.resolve()
        
        return {
            "mode": state["mode"].value,
            "temperature_offset": state["temperature_offset"],
            "solar_power": state["solar_power"],
            "current_price": state["current_price"],
            "reason": state["reason"],
            "solar_sensor": self.solar_sensor or "Nicht konfiguriert",
            "price_sensor": self.price_sensor or "Nicht konfiguriert",
            "thresholds": {
                "solar_boost_w": self.SOLAR_BOOST_THRESHOLD_W,
                "eco_price_eur": self.ECO_PRICE_THRESHOLD_EUR,
                "cheap_price_eur": self.CHEAP_PRICE_THRESHOLD_EUR,
            },
        }


# ============================================================================
# STANDALONE-TEST
# ============================================================================

if __name__ == "__main__":
    """
    Demo: Zeigt Funktionsweise des Energy-State-Resolvers.
    """
    print("=" * 60)
    print("Energy-State-Resolver Demo")
    print("=" * 60)
    print("\nEnergie-Modi:")
    for mode in EnergyMode:
        print(f"  - {mode.value}")
    print("\nTemperatur-Offsets:")
    print(f"  - Solar-Boost: +{EnergyStateResolver.SOLAR_BOOST_OFFSET}°C")
    print(f"  - Eco-Mode: {EnergyStateResolver.ECO_OFFSET}°C")
    print(f"  - Normal: ±0.0°C")
    print(f"\n⚠️ Anti-Kalt-Garantie: Niemals unter {EnergyStateResolver.ABSOLUTE_MIN_TEMP}°C!")
    print("\n" + "=" * 60)
