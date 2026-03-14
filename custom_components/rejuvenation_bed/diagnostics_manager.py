"""
Diagnostics-Manager für das Rejuvenation Bed.

Bietet umfassende Einblicke in:
1. Thermal Summary - Wo kommt die Temperatur her?
2. Energy Budget - Wieviel Energie wurde gespart/genutzt?
3. System Health - Läuft alles rund?

NEU: Persistent Storage - Statistiken überleben HA-Restart!

TRANSPARENZ ist Kernprinzip!
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from homeassistant.helpers.storage import Store
from .const import local_now
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

# Storage Version (erhöhen bei Schema-Änderungen)
STORAGE_VERSION = 1
STORAGE_KEY = "rejuvenation_bed_diagnostics"


class DiagnosticsManager:
    """
    Zentrale Diagnose- und Transparenz-Engine.
    
    Sammelt Daten aus allen Subsystemen und bietet:
    - Thermal Summary (Temperatur-Breakdown)
    - Energy Budget (Solar/Grid-Tracking)
    - System Health (Fehler, Warnings)
    
    NEU: Persistente Speicherung via HA Storage API
    """
    
    def __init__(self, hass, config_entry):
        """Initialisiert den Diagnostics-Manager."""
        self.hass = hass
        self.config_entry = config_entry
        
        # Persistent Storage
        self._store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}_{config_entry.entry_id}")
        self._storage_loaded = False
        
        # Energie-Tracking (kumulativ - überlebt Resets!)
        self._energy_budget = {
            "solar_kwh_used": 0.0,
            "grid_kwh_used": 0.0,
            "peak_kwh_saved": 0.0,  # Teurer Strom vermieden
            "total_runtime_hours": 0.0,
            "last_reset": None,  # Wird beim ersten async_load oder ersten Update gesetzt
        }
        
        # NEU: Separater Tages-Zähler (resettet sich um Mitternacht)
        self._daily_energy = {
            "solar_kwh": 0.0,
            "grid_kwh": 0.0,
            "date": local_now().strftime("%Y-%m-%d"),
        }
        
        # System-Health-Tracking
        self._health_events: List[dict] = []
        self._max_health_events = 100  # Rolling window
        
        # Performance-Tracking
        self._performance_metrics = {
            "avg_warmup_time_minutes": None,
            "avg_cooldown_time_minutes": None,
            "efficiency_rating": None,  # 0-100%
        }
        
        # Auto-Save Timer (alle 15 Minuten)
        self._last_save = local_now()
        self._save_interval = timedelta(minutes=15)
    
    async def async_load(self):
        """Lädt gespeicherte Daten aus dem Storage."""
        if self._storage_loaded:
            return
        
        try:
            data = await self._store.async_load()
            
            if data:
                self._energy_budget = data.get("energy_budget", self._energy_budget)
                self._health_events = data.get("health_events", [])[-self._max_health_events:]
                self._performance_metrics = data.get("performance_metrics", self._performance_metrics)
                self._daily_energy = data.get("daily_energy", self._daily_energy)
                
                # Tages-Zähler resetten wenn neuer Tag
                today = local_now().strftime("%Y-%m-%d")
                if self._daily_energy.get("date") != today:
                    _LOGGER.info(f"Neuer Tag erkannt ({today}) - Tages-Zähler zurückgesetzt")
                    self._daily_energy = {
                        "solar_kwh": 0.0,
                        "grid_kwh": 0.0,
                        "date": today,
                    }
                
                _LOGGER.info(
                    f"Diagnostics geladen: {self._energy_budget.get('solar_kwh_used', 0):.2f} kWh Solar, "
                    f"{self._energy_budget.get('grid_kwh_used', 0):.2f} kWh Grid"
                )
            else:
                _LOGGER.info("Keine gespeicherten Diagnostics gefunden - starte neu")
            
            self._storage_loaded = True
            
        except Exception as e:
            _LOGGER.error(f"Fehler beim Laden der Diagnostics: {e}")
            self._storage_loaded = True  # Verhindere weitere Ladeversuch
    
    async def async_save(self, force: bool = False):
        """Speichert Daten in den Storage."""
        now = local_now()
        
        # Nur speichern wenn Intervall abgelaufen oder Force
        if not force and (now - self._last_save) < self._save_interval:
            return
        
        try:
            data = {
                "energy_budget": self._energy_budget,
                "daily_energy": self._daily_energy,
                "health_events": self._health_events[-self._max_health_events:],
                "performance_metrics": self._performance_metrics,
                "saved_at": now.isoformat(),
            }
            
            await self._store.async_save(data)
            self._last_save = now
            
            _LOGGER.debug("Diagnostics gespeichert")
            
        except Exception as e:
            _LOGGER.error(f"Fehler beim Speichern der Diagnostics: {e}")
    
    def get_thermal_summary(
        self,
        zone_index: int,
        coordinator
    ) -> dict:
        """
        Erstellt eine detaillierte Thermal Summary für eine Zone.
        
        Zeigt GENAU, wie sich die Zieltemperatur zusammensetzt:
        
        Beispiel-Output:
        {
            "final_target": 28.7,
            "breakdown": {
                "base_curve": 28.0,
                "energy_offset": +0.5,
                "sleep_stage_offset": +0.2,
                "manual_override": 0.0
            },
            "active_phase": "Tiefschlaf",
            "reason": "Solar-Boost aktiv"
        }
        
        Args:
            zone_index: Index der Zone
            coordinator: RejuvenationBedCoordinator Instanz
        
        Returns:
            Dict mit detailliertem Breakdown
        """
        # Hole relevante Daten
        temp_calc = coordinator.temperature_calculator
        
        # Initialisiere Resolver (falls noch nicht geschehen)
        if zone_index not in temp_calc._curves:
            return {"error": "Zone nicht initialisiert"}
        
        # Basis-Kurve
        curve = temp_calc._curves[zone_index]
        curve_info = curve.get_curve_info()
        base_temp = curve_info["target_temperature"]
        
        # Energie-Offset
        energy_resolver = temp_calc.energy_resolver
        energy_state = energy_resolver.resolve()
        energy_offset = energy_state.get("temperature_offset", 0.0)
        
        # Sleep-Stage-Offset (falls Wearable aktiv)
        sleep_stage_offset = 0.0
        sleep_stage_resolver = temp_calc._sleep_stage_resolvers.get(zone_index)
        if sleep_stage_resolver and sleep_stage_resolver.should_override_curve():
            sleep_stage_offset = sleep_stage_resolver.get_temperature_modifier()
        
        # Manuelle Overrides
        manual_override = getattr(coordinator, "manual_target_temp", {}).get(zone_index)
        boost_active = getattr(coordinator, "manual_boost", {}).get(zone_index, False)
        
        # Finale Temperatur
        if manual_override is not None:
            final_target = manual_override
            breakdown_method = "manual_override"
        elif boost_active:
            zones_config = self.config_entry.data.get("zones", [])
            final_target = zones_config[zone_index].get("boost_target_temp", 34)
            breakdown_method = "boost_mode"
        else:
            final_target = base_temp + energy_offset + sleep_stage_offset
            breakdown_method = "calculated"
        
        return {
            "final_target": round(final_target, 2),
            "calculation_method": breakdown_method,
            "breakdown": {
                "base_curve_temp": round(base_temp, 2),
                "energy_offset": round(energy_offset, 2),
                "sleep_stage_offset": round(sleep_stage_offset, 2),
                "manual_override": manual_override,
                "boost_active": boost_active,
            },
            "curve_info": {
                "phase": curve_info["phase"],
                "phase_progress": curve_info["phase_progress"],
                "normalized_time": curve_info["normalized_time"],
            },
            "energy_mode": energy_state.get("mode").value if energy_state.get("mode") else "unknown",
            "reason": energy_state.get("reason", "Normal"),
        }
    
    def get_daily_energy(self) -> dict:
        """
        Gibt den heutigen Energieverbrauch zurück.
        
        Resettet sich automatisch um Mitternacht.
        Getrennt vom Gesamt-Zähler!
        """
        today = local_now().strftime("%Y-%m-%d")
        if self._daily_energy.get("date") != today:
            self._daily_energy = {
                "solar_kwh": 0.0,
                "grid_kwh": 0.0,
                "date": today,
            }
        
        solar = self._daily_energy.get("solar_kwh", 0.0)
        grid = self._daily_energy.get("grid_kwh", 0.0)
        total = solar + grid
        
        return {
            "total_kwh": round(total, 3),
            "solar_kwh": round(solar, 3),
            "grid_kwh": round(grid, 3),
            "date": today,
        }

    def get_energy_budget(self) -> dict:
        """
        Gibt detailliertes Energy-Budget zurück.
        
        Zeigt:
        - Wieviel Solar-Strom genutzt wurde
        - Wieviel Grid-Strom verbraucht
        - Wieviel Geld gespart (teurer Strom vermieden)
        - Effizienz-Rating
        
        Returns:
            Dict mit Budget-Daten
        """
        budget = self._energy_budget.copy()
        
        # Berechne Geld-Ersparnis (grobe Schätzung)
        avg_grid_price = 0.30  # €/kWh (könnte aus Sensor gelesen werden)
        avg_peak_price = 0.40  # €/kWh
        
        grid_cost = budget["grid_kwh_used"] * avg_grid_price
        solar_value = budget["solar_kwh_used"] * avg_grid_price
        peak_savings = budget["peak_kwh_saved"] * (avg_peak_price - avg_grid_price)
        
        total_savings = solar_value + peak_savings
        
        # Laufzeit - last_reset kann String (aus Storage) oder datetime sein
        last_reset = budget.get("last_reset")
        if isinstance(last_reset, str):
            try:
                last_reset_dt = datetime.fromisoformat(last_reset).replace(tzinfo=None)
            except:
                last_reset_dt = local_now()
        elif hasattr(last_reset, 'replace'):
            last_reset_dt = last_reset.replace(tzinfo=None) if last_reset else local_now()
        else:
            last_reset_dt = local_now()
        
        elapsed = local_now() - last_reset_dt
        days_since_reset = elapsed.total_seconds() / 86400
        
        return {
            "solar_kwh_used": round(budget["solar_kwh_used"], 2),
            "grid_kwh_used": round(budget["grid_kwh_used"], 2),
            "peak_kwh_saved": round(budget["peak_kwh_saved"], 2),
            "total_kwh": round(
                budget["solar_kwh_used"] + budget["grid_kwh_used"], 2
            ),
            "total_runtime_hours": round(budget.get("total_runtime_hours", 0.0), 1),
            "solar_percentage": round(
                (budget["solar_kwh_used"] / max(budget["solar_kwh_used"] + budget["grid_kwh_used"], 0.001)) * 100,
                1
            ),
            "estimated_savings_eur": round(total_savings, 2),
            "grid_cost_eur": round(grid_cost, 2),
            "days_tracked": round(days_since_reset, 1),
            "avg_kwh_per_day": round(
                (budget["solar_kwh_used"] + budget["grid_kwh_used"]) / max(days_since_reset, 0.04),
                2
            ),
            "last_reset": last_reset_dt.isoformat() if isinstance(last_reset_dt, datetime) else str(last_reset),
        }
    
    def update_energy_usage(
        self,
        power_watts: float,
        update_interval_seconds: int,
        is_solar_active: bool,
        is_peak_price: bool,
        total_power_rating: float = 300.0,
        power_correction_factor: float = 1.0,
    ):
        """
        Aktualisiert das Energy-Budget mit neuem Verbrauch.
        
        Wird vom Coordinator bei jedem Update aufgerufen.
        
        Args:
            power_watts: Aktuelle Leistung in Watt (gemessen ODER geschätzt)
            update_interval_seconds: Zeit seit letztem Update
            is_solar_active: Läuft gerade Solar-Boost?
            is_peak_price: Ist der Strom gerade teuer?
            total_power_rating: Nominale Leistung aller Heizungen
            power_correction_factor: Korrekturfaktor für Sensoren die Scheinleistung
                                    statt Wirkleistung messen (z.B. Fibaro bei PWM/Triac).
                                    1.0 = keine Korrektur, 0.45 = typisch für PWM-Heizer
        """
        # Korrekturfaktor anwenden (Fibaro misst Scheinleistung bei PWM)
        corrected_watts = power_watts * power_correction_factor
        
        # last_reset setzen wenn noch nicht geschehen (erster Start)
        if self._energy_budget.get("last_reset") is None:
            self._energy_budget["last_reset"] = local_now().isoformat()
        
        # Energie berechnen (Wh → kWh)
        energy_wh = (corrected_watts * update_interval_seconds) / 3600
        energy_kwh = energy_wh / 1000
        
        # Laufzeit tracken (nur wenn wirklich geheizt wird)
        if corrected_watts > 5:
            runtime_hours = update_interval_seconds / 3600
            self._energy_budget["total_runtime_hours"] = self._energy_budget.get("total_runtime_hours", 0) + runtime_hours
        
        # ═══════════════════════════════════════════════════════════
        # Tages-Zähler: Prüfe ob Mitternacht überschritten
        # ═══════════════════════════════════════════════════════════
        today = local_now().strftime("%Y-%m-%d")
        if self._daily_energy.get("date") != today:
            _LOGGER.info(f"Mitternacht: Tages-Zähler zurückgesetzt ({self._daily_energy.get('date')} → {today})")
            self._daily_energy = {
                "solar_kwh": 0.0,
                "grid_kwh": 0.0,
                "date": today,
            }
        
        # Kategorisieren: GESAMT-Zähler + TAGES-Zähler
        if is_solar_active:
            self._energy_budget["solar_kwh_used"] += energy_kwh
            self._daily_energy["solar_kwh"] += energy_kwh
        else:
            self._energy_budget["grid_kwh_used"] += energy_kwh
            self._daily_energy["grid_kwh"] += energy_kwh
        
        # Peak-Savings tracken (wenn wir NICHT zu Peakzeit heizen)
        if is_peak_price and corrected_watts < 5:
            # Schätzung: Ohne Intelligenz hätte der Thermostat geheizt
            # Realer Duty-Cycle eines Hersteller-Thermostats: ~17%
            estimated_peak_usage = (total_power_rating * 0.17 * update_interval_seconds) / 3600 / 1000
            self._energy_budget["peak_kwh_saved"] += estimated_peak_usage
        
        # ═══════════════════════════════════════════════════════════
        # Legacy-Vergleich (Hersteller-Thermostat, kalibriert)
        # ═══════════════════════════════════════════════════════════
        # Gemessen: ~1.2 kWh/Tag mit Hersteller-Thermostat (Dual-Kern, eine Seite)
        # Das entspricht ~50W Durchschnitt = 17% Duty-Cycle bei 300W
        legacy_duty_cycle = 0.26  # 26% Duty-Cycle (kalibriert aus Messdaten Feb 2026)
        legacy_energy_kwh = (total_power_rating * legacy_duty_cycle * update_interval_seconds) / 3600 / 1000
        
        self._energy_budget["legacy_estimated_kwh"] = (
            self._energy_budget.get("legacy_estimated_kwh", 0) + legacy_energy_kwh
        )
        
        # Auto-Save (async via hass.async_create_task)
        if self.hass and hasattr(self.hass, 'async_create_task'):
            self.hass.async_create_task(self.async_save())
    
    def log_health_event(
        self,
        severity: str,
        category: str,
        message: str,
        details: Optional[dict] = None
    ):
        """
        Loggt ein System-Health-Event.
        
        Args:
            severity: "info", "warning", "error", "critical"
            category: "sensor", "safety", "relay", "calculation", etc.
            message: Menschenlesbare Beschreibung
            details: Zusätzliche Debug-Daten
        """
        event = {
            "timestamp": local_now().isoformat(),
            "severity": severity,
            "category": category,
            "message": message,
            "details": details or {},
        }
        
        self._health_events.append(event)
        
        # Rolling window (nur letzte 100 Events behalten)
        if len(self._health_events) > self._max_health_events:
            self._health_events.pop(0)
        
        # Logging
        if severity == "critical":
            _LOGGER.critical(f"[{category}] {message}")
        elif severity == "error":
            _LOGGER.error(f"[{category}] {message}")
        elif severity == "warning":
            _LOGGER.warning(f"[{category}] {message}")
        else:
            _LOGGER.info(f"[{category}] {message}")
    
    def get_system_health(self) -> dict:
        """
        Gibt System-Health-Status zurück.
        
        Returns:
            Dict mit Health-Metriken und aktuellen Events
        """
        # Zähle Events nach Severity
        severity_counts = {
            "critical": 0,
            "error": 0,
            "warning": 0,
            "info": 0,
        }
        
        for event in self._health_events:
            severity = event.get("severity", "info")
            severity_counts[severity] += 1
        
        # Gesamtstatus
        if severity_counts["critical"] > 0:
            overall_status = "critical"
        elif severity_counts["error"] > 0:
            overall_status = "degraded"
        elif severity_counts["warning"] > 5:
            overall_status = "warning"
        else:
            overall_status = "healthy"
        
        # Letzte Events (nur 10 neueste)
        recent_events = self._health_events[-10:]
        
        return {
            "overall_status": overall_status,
            "severity_counts": severity_counts,
            "total_events": len(self._health_events),
            "recent_events": recent_events,
            "performance_metrics": self._performance_metrics,
        }
    
    def reset_energy_budget(self):
        """Setzt Energy-Budget zurück (z.B. monatlich)."""
        _LOGGER.info("Energy-Budget zurückgesetzt")
        self._energy_budget = {
            "solar_kwh_used": 0.0,
            "grid_kwh_used": 0.0,
            "peak_kwh_saved": 0.0,
            "total_runtime_hours": 0.0,
            "last_reset": local_now().isoformat(),
        }
        
        # Sofort speichern
        if self.hass and hasattr(self.hass, 'async_create_task'):
            self.hass.async_create_task(self.async_save(force=True))
    
    def get_complete_diagnostics(self, coordinator) -> dict:
        """
        Gibt ALLE Diagnostics auf einmal zurück.
        
        Nützlich für Developer Tools oder Debug-Sensor.
        """
        zones_count = len(self.config_entry.data.get("zones", []))
        
        thermal_summaries = {}
        for zone_idx in range(zones_count):
            thermal_summaries[f"zone_{zone_idx}"] = self.get_thermal_summary(
                zone_idx, coordinator
            )
        
        return {
            "thermal_summaries": thermal_summaries,
            "energy_budget": self.get_energy_budget(),
            "system_health": self.get_system_health(),
            "anti_short_cycle": coordinator.anti_short_cycle_manager.get_diagnostics() if hasattr(coordinator, 'anti_short_cycle_manager') else {},
            "timestamp": local_now().isoformat(),
        }


# ============================================================================
# STANDALONE-TEST
# ============================================================================

if __name__ == "__main__":
    """
    Demo: Zeigt Diagnostics-Funktionalität.
    """
    print("=" * 60)
    print("Diagnostics-Manager Demo")
    print("=" * 60)
    
    print("\nBeispiel Energy Budget:")
    print("""
    {
      "solar_kwh_used": 12.5,
      "grid_kwh_used": 8.3,
      "solar_percentage": 60.1,
      "estimated_savings_eur": 4.75,
      "days_tracked": 30.2
    }
    """)
    
    print("\nBeispiel Thermal Summary:")
    print("""
    {
      "final_target": 28.7,
      "breakdown": {
        "base_curve_temp": 28.0,
        "energy_offset": +0.5,  ← Solar-Boost!
        "sleep_stage_offset": +0.2  ← Wearable!
      },
      "active_phase": "Tiefschlaf",
      "reason": "☀️ Solar-Boost aktiv"
    }
    """)
    
    print("\n" + "=" * 60)
    print("Transparenz = Vertrauen!")
