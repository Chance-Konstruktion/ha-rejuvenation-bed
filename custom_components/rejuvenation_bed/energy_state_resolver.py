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
from enum import Enum
from typing import Optional, Tuple

from homeassistant.core import HomeAssistant

from .const import (
    DEFAULT_BED_BOOST_SOC_THRESHOLD,
    DEFAULT_BED_BOOST_MIN_FORECAST_KWH,
    BED_BOOST_SOC_HYSTERESIS,
    BED_BOOST_FORECAST_HYSTERESIS_KWH,
)

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

        # NEU: Zustand für Hysterese merken
        self._current_mode = EnergyMode.NORMAL

        # Cascade-Hysterese: merken ob Cascade gerade Boost erlaubt
        self._cascade_allows = False
        self._cascade_reason = ""

        # Referenz zum Coordinator (wird gesetzt nach init)
        self._coordinator = None
    
    @property
    def solar_sensor(self) -> str:
        """Solar-Sensor frisch aus Options lesen (damit Änderungen sofort wirken)."""
        return self.config_entry.options.get(
            "solar_sensor", self.global_config.get("solar_sensor")
        )
    
    @property
    def price_sensor(self) -> str:
        """Preis-Sensor frisch aus Options lesen."""
        return self.config_entry.options.get(
            "price_sensor", self.global_config.get("price_sensor")
        )

    @property
    def solar_boost_on_w(self) -> float:
        """Solar-Schwellwert aus Options lesen (Default: 500W)."""
        val = self.config_entry.options.get(
            "solar_boost_threshold",
            self.global_config.get("solar_boost_threshold", 500)
        )
        return float(val)

    @property
    def solar_boost_off_w(self) -> float:
        """Solar-Aus-Schwellwert = Ein-Schwellwert minus 50W Hysterese."""
        return self.solar_boost_on_w - 50

    # ───────────────────────────────────────────────────────────────────────
    # PV-Prioritäts-Kaskade: Hausakku-SoC und PV-Forecast
    # ───────────────────────────────────────────────────────────────────────

    @property
    def battery_soc_sensor(self) -> str:
        """Hausakku-SoC-Sensor (optional). Ohne den ist die Cascade-Gate inaktiv."""
        return self.config_entry.options.get(
            "battery_soc_sensor", self.global_config.get("battery_soc_sensor")
        )

    @property
    def forecast_sensor(self) -> str:
        """PV-Forecast-Sensor (Rest-Tag in kWh, z.B. Solcast)."""
        return self.config_entry.options.get(
            "forecast_sensor", self.global_config.get("forecast_sensor")
        )

    @property
    def bed_boost_soc_threshold(self) -> float:
        """SoC-Schwelle ab der Bett-Boost erlaubt ist (Default 90%)."""
        val = self.config_entry.options.get(
            "bed_boost_soc_threshold",
            self.global_config.get(
                "bed_boost_soc_threshold", DEFAULT_BED_BOOST_SOC_THRESHOLD
            ),
        )
        return float(val)

    @property
    def bed_boost_min_forecast_kwh(self) -> float:
        """Forecast-Rest-Tag-Schwelle in kWh ab der Bett-Boost erlaubt ist (Default 3)."""
        val = self.config_entry.options.get(
            "bed_boost_min_forecast_kwh",
            self.global_config.get(
                "bed_boost_min_forecast_kwh", DEFAULT_BED_BOOST_MIN_FORECAST_KWH
            ),
        )
        return float(val)

    def resolve(self) -> dict:
        """
        Hauptfunktion: Ermittelt den aktuellen Energie-Zustand.
        
        Berücksichtigt jetzt:
        - Solar/Eco SWITCHES (User kann Solar-Boost und Eco deaktivieren!)
        - Tibber Auto-Detect (€/kWh vs. ct/kWh)
        
        Returns:
            Dict mit:
            - mode: EnergyMode
            - temperature_offset: float (additiv zur Kurve)
            - solar_power: float (aktuelle Solar-Leistung)
            - current_price: float (aktueller Strompreis in €/kWh)
            - reason: str (Erklärung für UI)
        """
        # Schritt 1: Aktuelle Werte auslesen
        solar_power = self._read_solar_power()
        current_price = self._read_energy_price()
        
        # Schritt 1b: Switch-Status vom Coordinator prüfen
        solar_enabled = True
        eco_enabled = False
        if self._coordinator:
            solar_enabled = getattr(self._coordinator, "thermal_battery_enabled", True)
            eco_enabled = getattr(self._coordinator, "eco_mode_enabled", False)
        
        # Schritt 2: Modus ermitteln (mit Switch-Checks!)
        mode = self._determine_mode(solar_power, current_price, solar_enabled, eco_enabled)
        
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
            "cascade_allows_boost": self._cascade_allows,
            "cascade_reason": self._cascade_reason,
            "battery_soc": self._read_battery_soc(),
            "forecast_remaining_kwh": self._read_forecast_remaining_kwh(),
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
    
    @property
    def _fallback_price(self) -> float:
        """Konfigurierter Strompreis als Fallback (ct/kWh → EUR/kWh)."""
        # Aus Options oder Config lesen, Default 30 ct/kWh
        ct_price = (
            self.config_entry.options.get("electricity_price")
            or self.global_config.get("electricity_price")
            or 30.0
        )
        return float(ct_price) / 100.0

    def _read_energy_price(self) -> float:
        """
        Liest den aktuellen Strompreis aus dem Sensor.
        
        Priorität:
        1. Dynamischer Preis-Sensor (Tibber, aWATTar, ENTSO-E)
        2. Manuell konfigurierter Festpreis
        
        Auto-Detect: Tibber/ENTSO-E liefern €/kWh (z.B. 0.2543),
        manche Custom-Sensoren liefern ct/kWh (z.B. 25.43).
        Werte > 1.0 werden als ct/kWh interpretiert und konvertiert.
        
        Returns:
            Preis in EUR/kWh
        """
        if not self.price_sensor:
            return self._fallback_price
        
        state = self.hass.states.get(self.price_sensor)
        
        if not state or state.state in ["unknown", "unavailable"]:
            return self._fallback_price
        
        try:
            price = float(state.state)
            
            # Auto-Detect: Werte > 1.0 sind vermutlich ct/kWh
            if price > 1.0:
                price = price / 100.0
                _LOGGER.debug(f"Strompreis Auto-Detect: {state.state} → {price:.4f} €/kWh")
            
            # Plausibilitäts-Check: Negative Preise möglich (Börse), aber > 2€ ist Fehler
            if price > 2.0:
                _LOGGER.warning(
                    f"Strompreis unplausibel hoch: {price:.2f} €/kWh "
                    f"→ Fallback {self._fallback_price:.2f}"
                )
                return self._fallback_price
            
            return price
            
        except (ValueError, TypeError):
            _LOGGER.warning(
                f"Konnte Preis-Sensor '{self.price_sensor}' nicht als Zahl lesen: "
                f"{state.state}"
            )
            return self._fallback_price

    def _read_battery_soc(self) -> Optional[float]:
        """
        Liest den Hausakku-SoC in Prozent.

        Returns:
            SoC in %, oder None wenn Sensor nicht konfiguriert / unavailable.
        """
        if not self.battery_soc_sensor:
            return None

        state = self.hass.states.get(self.battery_soc_sensor)
        if not state or state.state in ("unknown", "unavailable", None, ""):
            return None

        try:
            return float(state.state)
        except (ValueError, TypeError):
            _LOGGER.warning(
                f"Konnte Akku-SoC-Sensor '{self.battery_soc_sensor}' nicht "
                f"als Zahl lesen: {state.state}"
            )
            return None

    def _read_forecast_remaining_kwh(self) -> Optional[float]:
        """
        Liest die PV-Forecast für den Rest des Tages in kWh.

        Erwartet einen Sensor mit kWh-Wert (z.B. Solcast
        `sensor.solcast_pv_forecast_forecast_remaining_today`).

        Returns:
            kWh, oder None wenn Sensor nicht konfiguriert / unavailable.
        """
        if not self.forecast_sensor:
            return None

        state = self.hass.states.get(self.forecast_sensor)
        if not state or state.state in ("unknown", "unavailable", None, ""):
            return None

        try:
            return float(state.state)
        except (ValueError, TypeError):
            _LOGGER.warning(
                f"Konnte Forecast-Sensor '{self.forecast_sensor}' nicht "
                f"als Zahl lesen: {state.state}"
            )
            return None

    def _cascade_evaluate(self) -> Tuple[bool, str]:
        """
        Prüft die PV-Prioritäts-Kaskade für Solar-Boost.

        Logik (ODER):
        - Sind WEDER Akku-Sensor NOCH Forecast-Sensor konfiguriert
          → Cascade inaktiv, Boost erlaubt (klassisches Verhalten).
        - Mindestens einer konfiguriert
          → Boost erlaubt wenn Akku >= Schwelle ODER Forecast >= Schwelle.
        - Beide konfiguriert aber beide unavailable
          → Boost blockiert (lieber auf Nummer sicher: Akku/Boiler-Prio).

        Hysterese: Sobald Boost erlaubt, bleibt er erlaubt bis
        SoC < (Schwelle − 5%) UND Forecast < (Schwelle − 1 kWh).
        Das verhindert Flattern wenn SoC um die Schwelle pendelt.

        Returns:
            (allowed, reason) — reason ist menschenlesbar für UI/Logs.
        """
        has_battery = bool(self.battery_soc_sensor)
        has_forecast = bool(self.forecast_sensor)

        if not has_battery and not has_forecast:
            self._cascade_allows = True
            self._cascade_reason = ""
            return True, ""

        soc = self._read_battery_soc() if has_battery else None
        forecast = self._read_forecast_remaining_kwh() if has_forecast else None

        soc_threshold = self.bed_boost_soc_threshold
        fc_threshold = self.bed_boost_min_forecast_kwh

        # Hysterese: andere Schwelle je nachdem ob aktuell schon erlaubt
        if self._cascade_allows:
            soc_gate = soc_threshold - BED_BOOST_SOC_HYSTERESIS
            fc_gate = fc_threshold - BED_BOOST_FORECAST_HYSTERESIS_KWH
        else:
            soc_gate = soc_threshold
            fc_gate = fc_threshold

        soc_ok = soc is not None and soc >= soc_gate
        fc_ok = forecast is not None and forecast >= fc_gate

        if soc_ok or fc_ok:
            parts = []
            if soc is not None:
                parts.append(f"Akku {soc:.0f}%")
            if forecast is not None:
                parts.append(f"Forecast {forecast:.1f} kWh")
            reason = " · ".join(parts) if parts else ""
            self._cascade_allows = True
            self._cascade_reason = reason
            return True, reason

        # Boost blockiert — Grund erklären
        if soc is None and forecast is None:
            reason = "Akku/Forecast-Sensoren unavailable — Boost pausiert (Prio: Akku)"
        else:
            parts = []
            if soc is not None:
                parts.append(f"Akku {soc:.0f}% < {soc_threshold:.0f}%")
            elif has_battery:
                parts.append("Akku-Sensor unavailable")
            if forecast is not None:
                parts.append(f"Forecast {forecast:.1f} < {fc_threshold:.1f} kWh")
            elif has_forecast:
                parts.append("Forecast-Sensor unavailable")
            reason = " · ".join(parts)

        self._cascade_allows = False
        self._cascade_reason = reason
        return False, reason

    def _determine_mode(
        self,
        solar_power: float,
        price: float,
        solar_enabled: bool = True,
        eco_enabled: bool = False,
    ) -> EnergyMode:
        """
        Entscheidet basierend auf Solar + Preis + Switches den Betriebsmodus.
        
        NEU: Switches werden respektiert!
        - thermal_battery_enabled=False → Solar-Boost blockiert
        - eco_mode_enabled=False → Eco blockiert
        
        Priorität (höchste zuerst):
        1. Solar-Boost (viel Überschuss + Switch AN)
        2. Günstiger Strom (wie Solar behandeln + Switch AN)
        3. Eco-Mode (teuer + Switch AN)
        4. Normal (alles andere)
        """
        # Solar-Boost nur wenn Switch AN
        if solar_enabled:
            # PV-Kaskade: Akku/Boiler haben Vorrang vor Bett-Boost
            cascade_ok, _ = self._cascade_evaluate()

            if cascade_ok:
                if self._current_mode == EnergyMode.SOLAR_BOOST:
                    if solar_power >= self.solar_boost_off_w:
                        return EnergyMode.SOLAR_BOOST
                else:
                    if solar_power >= self.solar_boost_on_w:
                        self._current_mode = EnergyMode.SOLAR_BOOST
                        return EnergyMode.SOLAR_BOOST

            # Sehr günstiger Strom = auch Solar-Boost
            # (Cascade gilt nicht: das ist Netzstrom, Akku-Prio irrelevant)
            if price <= self.CHEAP_PRICE_THRESHOLD_EUR:
                self._current_mode = EnergyMode.SOLAR_BOOST
                return EnergyMode.SOLAR_BOOST
        
        # Eco-Mode nur wenn Switch AN
        if eco_enabled:
            if self._current_mode == EnergyMode.ECO_MODE:
                if price >= self.ECO_PRICE_OFF_EUR:
                    return EnergyMode.ECO_MODE
            else:
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
                base = f"☀️ Solar-Boost aktiv ({solar_power:.0f}W Überschuss)"
                if self._cascade_reason:
                    return f"{base} — {self._cascade_reason}"
                return base
            else:
                return f"💰 Günstiger Strom ({price:.2f} €/kWh)"

        elif mode == EnergyMode.ECO_MODE:
            return f"💡 Energie-Sparmodus ({price:.2f} €/kWh)"

        elif mode == EnergyMode.GRID_CRITICAL:
            return "⚠️ Netz-Notfall: Minimalbetrieb"

        else:
            # Erklärung wenn Cascade gerade Boost blockiert (interessant für UI)
            cascade_configured = bool(self.battery_soc_sensor or self.forecast_sensor)
            cascade_blocks_boost = (
                cascade_configured
                and solar_power >= self.solar_boost_on_w
                and not self._cascade_allows
            )
            if cascade_blocks_boost and self._cascade_reason:
                return f"⏸ Boost wartet — {self._cascade_reason}"
            return "✅ Normal-Betrieb"
    
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
            "battery_soc_sensor": self.battery_soc_sensor or "Nicht konfiguriert",
            "forecast_sensor": self.forecast_sensor or "Nicht konfiguriert",
            "battery_soc": state["battery_soc"],
            "forecast_remaining_kwh": state["forecast_remaining_kwh"],
            "cascade_allows_boost": state["cascade_allows_boost"],
            "cascade_reason": state["cascade_reason"],
            "thresholds": {
                "solar_boost_on_w": self.solar_boost_on_w,
                "solar_boost_off_w": self.solar_boost_off_w,
                "eco_price_on_eur": self.ECO_PRICE_ON_EUR,
                "eco_price_off_eur": self.ECO_PRICE_OFF_EUR,
                "cheap_price_eur": self.CHEAP_PRICE_THRESHOLD_EUR,
                "bed_boost_soc_threshold": self.bed_boost_soc_threshold,
                "bed_boost_min_forecast_kwh": self.bed_boost_min_forecast_kwh,
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
    print("  - Normal: ±0.0°C")
    print(f"\n⚠️ Anti-Kalt-Garantie: Niemals unter {EnergyStateResolver.ABSOLUTE_MIN_TEMP}°C!")
    print("\n" + "=" * 60)
