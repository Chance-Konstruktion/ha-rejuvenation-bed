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
from typing import Optional

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

        # Solar-Boost-Trigger: welche unabhängigen Auslöser gerade greifen
        # (für UI/Diagnose) und ein menschenlesbarer Grund.
        self._boost_reason = ""
        self._boost_waiting = False
        self._active_triggers = {"solar": None, "soc": None, "forecast": None}

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
    # Unabhängige Solar-Boost-Trigger: Hausakku-SoC und PV-Forecast
    # ───────────────────────────────────────────────────────────────────────

    @property
    def battery_soc_sensor(self) -> str:
        """Hausakku-SoC-Sensor (optional). Eigenständiger Boost-Trigger."""
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
        """SoC-Schwelle ab der der SoC-Trigger Boost auslöst (Default 90%)."""
        val = self.config_entry.options.get(
            "bed_boost_soc_threshold",
            self.global_config.get(
                "bed_boost_soc_threshold", DEFAULT_BED_BOOST_SOC_THRESHOLD
            ),
        )
        return float(val)

    @property
    def bed_boost_min_forecast_kwh(self) -> float:
        """Forecast-Rest-Tag-Schwelle in kWh ab der der Forecast-Trigger auslöst (Default 3)."""
        val = self.config_entry.options.get(
            "bed_boost_min_forecast_kwh",
            self.global_config.get(
                "bed_boost_min_forecast_kwh", DEFAULT_BED_BOOST_MIN_FORECAST_KWH
            ),
        )
        return float(val)

    @property
    def battery_priority(self) -> bool:
        """
        Akku-Vorrang (optional, Default AUS).

        AUS: Solar-Schwelle, Akku-SoC und Forecast sind unabhängige
             ODER-Trigger — jeder löst Boost allein aus.
        AN:  Akku/Boiler haben Vorrang. Die Solar-Schwelle löst nur dann
             aus, wenn zusätzlich der Akku (fast) voll ODER die Forecast
             üppig ist. Ohne Akku-/Forecast-Sensor bleibt es beim
             klassischen Solar-only-Verhalten.
        """
        val = self.config_entry.options.get(
            "battery_priority",
            self.global_config.get("battery_priority", False),
        )
        return bool(val)

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
            # #7: abgeleitete Status-Keys, die Coordinator/Switch/Sensor erwarten
            "solar_active": mode == EnergyMode.SOLAR_BOOST,
            "price_status": self._classify_price(current_price),
            "boost_available": mode == EnergyMode.SOLAR_BOOST,
            "boost_reason": self._boost_reason,
            "boost_waiting": self._boost_waiting,
            "active_triggers": dict(self._active_triggers),
            "battery_priority": self.battery_priority,
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

    def _evaluate_boost_triggers(self, solar_power: float) -> dict:
        """
        Wertet die einzelnen Solar-Boost-Trigger aus.

        Drei Auslöser, jeder mit eigener Hysterese (referenziert
        ``self._current_mode``, damit nichts flattert):

        - Solar-Schwelle: aktuelle PV-Leistung ≥ Schwelle (klassisch).
        - Akku-SoC:       Hausakku-SoC ≥ Schwelle.
        - PV-Forecast:    Rest-Tag-Prognose ≥ Schwelle (optional).

        Ein Trigger zählt nur, wenn sein Sensor konfiguriert UND lesbar
        ist; sonst ist sein Status ``None`` (nicht vorhanden).

        Die Verknüpfung (ODER bzw. Akku-Vorrang-Gating) übernimmt
        ``_determine_mode``.

        Returns:
            Dict ``{trigger: (active|None, label|None)}`` für solar,
            soc, forecast. ``active`` ist True/False, ``None`` bei
            fehlendem/unlesbarem Sensor; ``label`` ist menschenlesbar.
        """
        already_boost = self._current_mode == EnergyMode.SOLAR_BOOST
        triggers = {
            "solar": (None, None),
            "soc": (None, None),
            "forecast": (None, None),
        }

        # ── Trigger 1: Solar-Schwelle ───────────────────────────────────
        if self.solar_sensor:
            threshold = (
                self.solar_boost_off_w if already_boost else self.solar_boost_on_w
            )
            triggers["solar"] = (
                solar_power >= threshold,
                f"{solar_power:.0f}W Überschuss",
            )

        # ── Trigger 2: Akku-SoC ─────────────────────────────────────────
        soc = self._read_battery_soc()
        if self.battery_soc_sensor and soc is not None:
            threshold = self.bed_boost_soc_threshold
            if already_boost:
                threshold -= BED_BOOST_SOC_HYSTERESIS
            triggers["soc"] = (soc >= threshold, f"Akku {soc:.0f}%")

        # ── Trigger 3: PV-Forecast (optional) ───────────────────────────
        forecast = self._read_forecast_remaining_kwh()
        if self.forecast_sensor and forecast is not None:
            threshold = self.bed_boost_min_forecast_kwh
            if already_boost:
                threshold -= BED_BOOST_FORECAST_HYSTERESIS_KWH
            triggers["forecast"] = (
                forecast >= threshold,
                f"Forecast {forecast:.1f} kWh",
            )

        return triggers

    def _evaluate_solar_boost(self, solar_power: float) -> bool:
        """
        Verknüpft die Trigger zur Solar-Boost-Entscheidung.

        - Akku-Vorrang AUS (Default): ODER — ein Trigger genügt.
        - Akku-Vorrang AN: Die Solar-Schwelle löst nur aus, wenn der
          Akku/Forecast den Boost freigibt (UND). Ist kein Akku-/
          Forecast-Sensor konfiguriert, greift das Gate nicht und es
          bleibt beim klassischen Solar-only-Verhalten.

        Setzt ``self._active_triggers``, ``self._boost_reason`` und
        ``self._boost_waiting`` als Nebeneffekt (für UI/Diagnose).
        """
        triggers = self._evaluate_boost_triggers(solar_power)
        self._active_triggers = {k: v[0] for k, v in triggers.items()}
        self._boost_waiting = False

        solar_active = triggers["solar"][0] is True
        soc_active = triggers["soc"][0] is True
        forecast_active = triggers["forecast"][0] is True

        reserve_active = soc_active or forecast_active
        reserve_configured = (
            triggers["soc"][0] is not None or triggers["forecast"][0] is not None
        )

        if self.battery_priority and reserve_configured:
            boost = solar_active and reserve_active
        else:
            boost = solar_active or soc_active or forecast_active

        if boost:
            parts = [
                triggers[k][1]
                for k in ("solar", "soc", "forecast")
                if triggers[k][0] is True
            ]
            self._boost_reason = " · ".join(parts)
            return True

        # Kein Boost — Grund merken, falls der Akku-Vorrang gerade gatet
        self._boost_reason = ""
        if self.battery_priority and reserve_configured and solar_active:
            self._boost_waiting = True
            wait_parts = []
            soc = self._read_battery_soc()
            if triggers["soc"][0] is not None and soc is not None:
                wait_parts.append(
                    f"Akku {soc:.0f}% < {self.bed_boost_soc_threshold:.0f}%"
                )
            forecast = self._read_forecast_remaining_kwh()
            if triggers["forecast"][0] is not None and forecast is not None:
                wait_parts.append(
                    f"Forecast {forecast:.1f} < {self.bed_boost_min_forecast_kwh:.1f} kWh"
                )
            self._boost_reason = " · ".join(wait_parts)
        return False

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
            # Trigger verknüpfen (ODER, oder Akku-Vorrang-Gating).
            if self._evaluate_solar_boost(solar_power):
                self._current_mode = EnergyMode.SOLAR_BOOST
                return EnergyMode.SOLAR_BOOST

            # Sehr günstiger Strom = auch Solar-Boost
            # (Netzstrom-Pfad: unabhängig von PV-Triggern)
            if price <= self.CHEAP_PRICE_THRESHOLD_EUR:
                self._current_mode = EnergyMode.SOLAR_BOOST
                self._boost_reason = ""
                self._boost_waiting = False
                return EnergyMode.SOLAR_BOOST
        else:
            self._active_triggers = {"solar": None, "soc": None, "forecast": None}
            self._boost_reason = ""
            self._boost_waiting = False

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
    
    def _classify_price(self, price: float) -> str:
        """
        Klassifiziert den Strompreis als 'cheap' / 'expensive' / 'normal' (#7).

        Nur mit dynamischem Preis-Sensor aussagekräftig — ohne Sensor (Festpreis-
        Fallback) wird 'normal' gemeldet, damit der Tarif-Status nicht fälschlich
        'Günstig'/'Teuer' anzeigt.
        """
        if not self.price_sensor or price is None:
            return "normal"
        if price <= self.CHEAP_PRICE_THRESHOLD_EUR:
            return "cheap"
        if price >= self.ECO_PRICE_ON_EUR:
            return "expensive"
        return "normal"

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
            if self._boost_reason:
                return f"☀️ Solar-Boost aktiv — {self._boost_reason}"
            if solar_power > 0:
                return f"☀️ Solar-Boost aktiv ({solar_power:.0f}W Überschuss)"
            return f"💰 Günstiger Strom ({price:.2f} €/kWh)"

        elif mode == EnergyMode.ECO_MODE:
            return f"💡 Energie-Sparmodus ({price:.2f} €/kWh)"

        elif mode == EnergyMode.GRID_CRITICAL:
            return "⚠️ Netz-Notfall: Minimalbetrieb"

        else:
            # Akku-Vorrang gatet gerade den Boost trotz PV-Überschuss
            if self._boost_waiting and self._boost_reason:
                return f"⏸ Boost wartet (Akku-Vorrang) — {self._boost_reason}"
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
            "boost_available": state["boost_available"],
            "boost_reason": state["boost_reason"],
            "boost_waiting": state["boost_waiting"],
            "active_triggers": state["active_triggers"],
            "battery_priority": state["battery_priority"],
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
