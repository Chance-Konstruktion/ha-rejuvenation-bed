import logging
from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature, UnitOfEnergy, UnitOfPower
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo
from .const import DOMAIN, MANUFACTURER, SW_VERSION

_LOGGER = logging.getLogger(__name__)


def get_device_info(coordinator) -> DeviceInfo:
    """Gibt die Device-Info für alle Entities zurück."""
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


class RejuvenationBedSensorBase(CoordinatorEntity, SensorEntity):
    """Base class für alle Rejuvenation Bed Sensoren mit Device Info."""
    
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_device_info = get_device_info(coordinator)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Setze die Sensoren basierend auf dem Coordinator-Update auf."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    entities = []
    zones_config = config_entry.data.get("zones", [])
    global_config = config_entry.data.get("global", {})
    is_dual_zone = len(zones_config) > 1

    for zone_idx, zone_config in enumerate(zones_config):
        # Namens-Logik für Dual-Zone
        if not is_dual_zone:
            display_name = ""
        else:
            display_name = " Links" if zone_idx == 0 else " Rechts"

        # ═══════════════════════════════════════════════════════════
        # PFLICHT-SENSOREN (immer erstellen)
        # ═══════════════════════════════════════════════════════════
        entities.append(BedTemperatureSensor(coordinator, zone_idx, display_name))
        entities.append(BedStatusSensor(coordinator, zone_idx, display_name))
        
        # Thermal Summary (immer nützlich)
        entities.append(BedThermalSummarySensor(coordinator, zone_idx, display_name))
        
        # NEU: Rampen-Status (Materialschutz)
        entities.append(BedRampStatusSensor(coordinator, zone_idx, display_name))
        
        # ═══════════════════════════════════════════════════════════
        # SCHLAF-SCORE: Nur wenn alle nötigen Sensoren vorhanden!
        # Braucht: Temperatursensor + CO2-Sensor für aussagekräftige Bewertung
        # ═══════════════════════════════════════════════════════════
        has_temp_sensor = bool(zone_config.get("temp_sensor"))
        has_co2_sensor = bool(global_config.get("co2_sensor"))
        
        if has_temp_sensor and has_co2_sensor:
            entities.append(BedSleepScoreSensor(coordinator, zone_idx, display_name))
            entities.append(BedSleepScoreWeeklySensor(coordinator, zone_idx, display_name))
            entities.append(BedSleepScoreTrendSensor(coordinator, zone_idx, display_name))
        
        # ═══════════════════════════════════════════════════════════
        # BEDINGTE SENSOREN (nur wenn konfiguriert)
        # ═══════════════════════════════════════════════════════════
        
        # Leistungssensor nur wenn power_sensor ODER power_rating konfiguriert
        if zone_config.get("power_sensor") or zone_config.get("power_rating"):
            entities.append(BedZonePowerSensor(coordinator, zone_idx, display_name))

    # ═══════════════════════════════════════════════════════════
    # GLOBALE SENSOREN (bedingt)
    # ═══════════════════════════════════════════════════════════
    
    # Strompreis-Status nur wenn price_sensor konfiguriert
    if global_config.get("price_sensor"):
        entities.append(BedEnergyPriceStatusSensor(coordinator))
    
    # Gesamtleistung nur wenn mindestens eine Zone Power hat
    has_any_power = any(
        z.get("power_sensor") or z.get("power_rating") 
        for z in zones_config
    )
    if has_any_power:
        entities.append(BedTotalPowerSensor(coordinator))
    
    # ═══════════════════════════════════════════════════════════
    # ENERGIE-SENSOREN (nur wenn Energie-Tracking aktiv)
    # ═══════════════════════════════════════════════════════════
    energy_config = config_entry.data.get("energy", {})
    
    if energy_config.get("enable_tracking", False) or has_any_power:
        entities.append(BedEnergyBudgetSensor(coordinator))
        entities.append(BedEnergyTodaySensor(coordinator))
        entities.append(BedAvgDailyEnergySensor(coordinator))
        entities.append(BedHeatingHoursSensor(coordinator))
        
        # Ersparnis nur wenn Vergleichsbasis vorhanden
        if energy_config.get("compare_to_legacy", True):
            entities.append(BedEstimatedSavingsSensor(coordinator))
            entities.append(BedLegacyComparisonSensor(coordinator))
    
    # ═══════════════════════════════════════════════════════════
    # SOLAR-SENSOREN (nur wenn solar_sensor konfiguriert)
    # ═══════════════════════════════════════════════════════════
    if global_config.get("solar_sensor"):
        entities.append(BedSolarPercentageSensor(coordinator))
        entities.append(BedSolarEnergyTodaySensor(coordinator))
        entities.append(BedGridEnergyTodaySensor(coordinator))

    # Zähle Schlaf-Score Sensoren
    has_sleep_score = any(
        bool(z.get("temp_sensor")) for z in zones_config
    ) and bool(global_config.get("co2_sensor"))
    
    # ═══════════════════════════════════════════════════════════
    # BED-INTELLIGENCE SENSOR (Kalibrierung + Status)
    # ═══════════════════════════════════════════════════════════
    entities.append(BedIntelligenceSensor(coordinator))
    
    # Bedtime-Learning Sensor pro Zone
    for zone_idx in range(len(zones_config)):
        entities.append(BedtimePredictionSensor(coordinator, zone_idx))
    
    async_add_entities(entities)
    
    _LOGGER.info(
        f"Rejuvenation Bed: {len(entities)} Sensoren erstellt "
        f"(Solar: {'✓' if global_config.get('solar_sensor') else '✗'}, "
        f"Energie: {'✓' if has_any_power else '✗'}, "
        f"Preis: {'✓' if global_config.get('price_sensor') else '✗'}, "
        f"Schlaf-Score: {'✓' if has_sleep_score else '✗ (braucht Temp+CO2)'})"
    )

class BedTemperatureSensor(RejuvenationBedSensorBase):
    """Zeigt die vom System berechnete Zieltemperatur."""
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, zone_idx, display_name):
        super().__init__(coordinator)
        self.zone_idx = zone_idx
        self.internal_zone_name = f"Zone {zone_idx + 1}"
        self._attr_name = f"Bett{display_name} Zieltemperatur"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_zone_{zone_idx}_target"

    @property
    def native_value(self):
        data = self.coordinator.data
        if data and "zones" in data:
            return data["zones"].get(self.internal_zone_name, {}).get("target")
        return None

class BedStatusSensor(RejuvenationBedSensorBase):
    """Zeigt den aktuellen Betriebsmodus der Zone (Textform)."""
    
    def __init__(self, coordinator, zone_idx, display_name):
        super().__init__(coordinator)
        self.zone_idx = zone_idx
        self.internal_zone_name = f"Zone {zone_idx + 1}"
        self._attr_name = f"Bett{display_name} Status"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_zone_{zone_idx}_mode"
        self._attr_icon = "mdi:bed-clock"

    @property
    def native_value(self):
        data = self.coordinator.data
        if not data or "zones" not in data:
            return "Warten..."
        
        zone_data = data["zones"].get(self.internal_zone_name, {})
        reason = zone_data.get("reason", "")
        
        if data.get("global_state", {}).get("status") == "EMERGENCY_SHUTDOWN":
            return "NOT-AUS"
        if "is_leaking" in zone_data and zone_data["is_leaking"]:
            return "ALARM: Leckage"
        if "Veto" in reason or "Sommer" in reason:
            return "Sommerpause"
        if "Solar" in reason:
            return "Solar-Boost"
        if zone_data.get("active"):
            return "Heizen"
        return "Bereit"

class BedZonePowerSensor(RejuvenationBedSensorBase):
    """Zeigt den aktuellen Verbrauch pro Zone in Watt."""
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = "W"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, zone_idx, display_name):
        super().__init__(coordinator)
        self.internal_zone_name = f"Zone {zone_idx + 1}"
        self._attr_name = f"Bett{display_name} Leistung"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_zone_{zone_idx}_power"

    @property
    def native_value(self):
        data = self.coordinator.data
        if data and "zones" in data:
            return data["zones"].get(self.internal_zone_name, {}).get("watt", 0.0)
        return 0.0

class BedTotalPowerSensor(RejuvenationBedSensorBase):
    """Zeigt den Gesamtverbrauch des Betts."""
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = "W"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Bett Gesamtleistung"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_total_power"

    @property
    def native_value(self):
        if self.coordinator.data:
            # Power steht in global_state.energy.total_power
            energy = self.coordinator.data.get("global_state", {}).get("energy", {})
            return energy.get("total_power", 0.0)
        return 0.0

class BedEnergyPriceStatusSensor(RejuvenationBedSensorBase):
    """Zeigt, ob der Strompreis gerade günstig, teuer oder normal ist."""
    
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Bett Strompreis Status"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_grid_status"

    @property
    def native_value(self):
        data = self.coordinator.data
        if data and "global_state" in data:
            val = data["global_state"].get("energy", {}).get("price_status", "normal")
            status_map = {"cheap": "Günstig", "expensive": "Teuer", "normal": "Normal"}
            return status_map.get(val, "Normal")
        return "Normal"

    @property
    def icon(self):
        val = self.native_value
        if val == "Günstig": return "mdi:currency-eur-off"
        if val == "Teuer": return "mdi:alert-circle-outline"
        return "mdi:currency-eur"


class BedThermalSummarySensor(RejuvenationBedSensorBase):
    """Zeigt detaillierte Thermal Summary (Temperature Breakdown)."""
    
    def __init__(self, coordinator, zone_idx, display_name):
        super().__init__(coordinator)
        self.zone_idx = zone_idx
        self._attr_name = f"Bett{display_name} Thermal Summary"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_zone_{zone_idx}_thermal_summary"
        self._attr_icon = "mdi:thermometer-lines"
    
    @property
    def native_value(self):
        """Haupt-Wert: Finale Zieltemperatur."""
        summary = self.coordinator.diagnostics_manager.get_thermal_summary(
            self.zone_idx, self.coordinator
        )
        return summary.get("final_target")
    
    @property
    def extra_state_attributes(self):
        """Komplette Thermal Summary als Attribute."""
        summary = self.coordinator.diagnostics_manager.get_thermal_summary(
            self.zone_idx, self.coordinator
        )
        
        # Formatiere für bessere Lesbarkeit
        breakdown = summary.get("breakdown", {})
        
        return {
            "calculation_method": summary.get("calculation_method"),
            "base_curve_temp": breakdown.get("base_curve_temp"),
            "energy_offset": breakdown.get("energy_offset"),
            "sleep_stage_offset": breakdown.get("sleep_stage_offset"),
            "manual_override": breakdown.get("manual_override"),
            "boost_active": breakdown.get("boost_active"),
            "current_phase": summary.get("curve_info", {}).get("phase"),
            "phase_progress": summary.get("curve_info", {}).get("phase_progress"),
            "energy_mode": summary.get("energy_mode"),
            "reason": summary.get("reason"),
        }


class BedRampStatusSensor(RejuvenationBedSensorBase):
    """
    Zeigt den Status der Temperatur-Rampe (Materialschutz).
    
    Das Vinyl wird durch sanfte Änderungen (max. 1°C/h) geschont.
    Dieser Sensor zeigt ob gerade eine Rampe aktiv ist.
    """
    _attr_icon = "mdi:chart-timeline-variant"
    
    def __init__(self, coordinator, zone_idx, display_name):
        super().__init__(coordinator)
        self.zone_idx = zone_idx
        self._attr_name = f"Bett{display_name} Rampen-Status"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_zone_{zone_idx}_ramp"
    
    @property
    def native_value(self):
        ramp_state = self.coordinator.ramp_controller.get_ramp_state(self.zone_idx)
        if ramp_state is None:
            return "Initialisierung..."
        
        if not ramp_state.ramp_active:
            return "Stabil"
        elif ramp_state.ramp_direction == "heating":
            return "Aufheizen"
        else:
            return "Abkühlen"
    
    @property
    def icon(self):
        ramp_state = self.coordinator.ramp_controller.get_ramp_state(self.zone_idx)
        if ramp_state and ramp_state.ramp_active:
            if ramp_state.ramp_direction == "heating":
                return "mdi:trending-up"
            else:
                return "mdi:trending-down"
        return "mdi:minus"
    
    @property
    def extra_state_attributes(self):
        ramp_state = self.coordinator.ramp_controller.get_ramp_state(self.zone_idx)
        if ramp_state is None:
            return {}
        
        attrs = {
            "ziel_temperatur": f"{ramp_state.target_temp:.1f}°C",
            "aktueller_setpoint": f"{ramp_state.current_setpoint:.1f}°C",
            "rampe_aktiv": ramp_state.ramp_active,
            "richtung": ramp_state.ramp_direction,
            "grund": ramp_state.reason,
            "max_aenderung": "1.0°C/h (Materialschutz)",
        }
        
        if ramp_state.estimated_completion:
            attrs["geschaetzte_fertigstellung"] = ramp_state.estimated_completion.strftime("%H:%M")
        
        return attrs


class BedEnergyBudgetSensor(RejuvenationBedSensorBase):
    """Zeigt gesamtes Energy Budget."""
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = "kWh"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Bett Energie Gesamt"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_energy_budget"
    
    @property
    def native_value(self):
        """Gesamtverbrauch (Solar + Grid)."""
        budget = self.coordinator.diagnostics_manager.get_energy_budget()
        return budget.get("total_kwh", 0.0)
    
    @property
    def extra_state_attributes(self):
        """Detailliertes Budget."""
        return self.coordinator.diagnostics_manager.get_energy_budget()


class BedSolarPercentageSensor(RejuvenationBedSensorBase):
    """Zeigt Solar-Anteil am Gesamtverbrauch."""
    _attr_native_unit_of_measurement = "%"
    _attr_icon = "mdi:solar-power"
    
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Bett Solar-Anteil"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_solar_percentage"
    
    @property
    def native_value(self):
        budget = self.coordinator.diagnostics_manager.get_energy_budget()
        return budget.get("solar_percentage", 0.0)


class BedEstimatedSavingsSensor(RejuvenationBedSensorBase):
    """Zeigt geschätzte Geld-Ersparnis."""
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "EUR"
    _attr_icon = "mdi:piggy-bank"
    
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Bett Geschätzte Ersparnis"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_estimated_savings"
    
    @property
    def native_value(self):
        budget = self.coordinator.diagnostics_manager.get_energy_budget()
        return budget.get("estimated_savings_eur", 0.0)


# ═══════════════════════════════════════════════════════════════════════════════
# SLEEP SCORE SENSOREN
# ═══════════════════════════════════════════════════════════════════════════════

class BedSleepScoreSensor(RejuvenationBedSensorBase):
    """Zeigt den Schlaf-Score der letzten Nacht (0-100)."""
    _attr_icon = "mdi:sleep"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "Punkte"
    
    def __init__(self, coordinator, zone_idx, display_name):
        super().__init__(coordinator)
        self.zone_idx = zone_idx
        self._attr_name = f"Bett{display_name} Schlaf-Score"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_zone_{zone_idx}_sleep_score"
    
    @property
    def native_value(self):
        score = self.coordinator.sleep_score_calculator.get_last_score(self.zone_idx)
        if score:
            return score.total_score
        return None
    
    @property
    def extra_state_attributes(self):
        score = self.coordinator.sleep_score_calculator.get_last_score(self.zone_idx)
        if not score:
            return {"status": "Noch keine Daten"}
        
        attrs = {
            "datum": score.date.strftime("%Y-%m-%d"),
            "temperatur_stabilitaet": score.temperature_stability_score,
            "kurven_treue": score.curve_adherence_score,
            "heiz_effizienz": score.heating_efficiency_score,
            "trend": f"{score.trend}{score.trend_value:+d}" if score.trend else "→0",
            "tipps": score.tips,
        }
        
        if score.has_co2_data:
            attrs["luftqualitaet"] = score.air_quality_score
        
        return attrs


class BedSleepScoreWeeklySensor(RejuvenationBedSensorBase):
    """Zeigt den Wochen-Durchschnitt des Schlaf-Scores."""
    _attr_icon = "mdi:calendar-week"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "Punkte"
    
    def __init__(self, coordinator, zone_idx, display_name):
        super().__init__(coordinator)
        self.zone_idx = zone_idx
        self._attr_name = f"Bett{display_name} Schlaf-Score Woche"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_zone_{zone_idx}_sleep_score_weekly"
    
    @property
    def native_value(self):
        avg = self.coordinator.sleep_score_calculator.get_weekly_average(self.zone_idx)
        if avg:
            return round(avg, 1)
        return None
    
    @property
    def extra_state_attributes(self):
        history = self.coordinator.sleep_score_calculator.get_score_history(self.zone_idx, 7)
        if not history:
            return {"status": "Noch keine Daten"}
        
        return {
            "tage_erfasst": len(history),
            "beste_nacht": max(s.total_score for s in history),
            "schlechteste_nacht": min(s.total_score for s in history),
        }


class BedSleepScoreTrendSensor(RejuvenationBedSensorBase):
    """Zeigt den Trend des Schlaf-Scores."""
    _attr_icon = "mdi:trending-up"
    
    def __init__(self, coordinator, zone_idx, display_name):
        super().__init__(coordinator)
        self.zone_idx = zone_idx
        self._attr_name = f"Bett{display_name} Schlaf-Trend"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_zone_{zone_idx}_sleep_trend"
    
    @property
    def native_value(self):
        score = self.coordinator.sleep_score_calculator.get_last_score(self.zone_idx)
        if score:
            return f"{score.trend}{score.trend_value:+d}"
        return "→0"
    
    @property
    def icon(self):
        score = self.coordinator.sleep_score_calculator.get_last_score(self.zone_idx)
        if score:
            if score.trend == "↑":
                return "mdi:trending-up"
            elif score.trend == "↓":
                return "mdi:trending-down"
        return "mdi:trending-neutral"
    
    @property
    def extra_state_attributes(self):
        score = self.coordinator.sleep_score_calculator.get_last_score(self.zone_idx)
        if not score:
            return {}
        
        return {
            "richtung": "aufwärts" if score.trend == "↑" else ("abwärts" if score.trend == "↓" else "stabil"),
            "punkte_differenz": score.trend_value,
            "vergleich": "vs. letzte 7 Tage",
        }


# ═══════════════════════════════════════════════════════════════════════════════
# ENERGIE-AUSWERTUNGS-SENSOREN
# ═══════════════════════════════════════════════════════════════════════════════

class BedEnergyTodaySensor(RejuvenationBedSensorBase):
    """Zeigt den Energieverbrauch heute (resettet sich um Mitternacht)."""
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:lightning-bolt"
    
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Bett Energie Heute"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_energy_today"
    
    @property
    def native_value(self):
        daily = self.coordinator.diagnostics_manager.get_daily_energy()
        return daily.get("total_kwh", 0.0)
    
    @property
    def extra_state_attributes(self):
        daily = self.coordinator.diagnostics_manager.get_daily_energy()
        return {
            "solar_kwh": daily.get("solar_kwh", 0.0),
            "netz_kwh": daily.get("grid_kwh", 0.0),
            "datum": daily.get("date", ""),
        }


class BedSolarEnergyTodaySensor(RejuvenationBedSensorBase):
    """Zeigt den Solar-Energieverbrauch."""
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:solar-power"
    
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Bett Solar-Energie"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_solar_energy"
    
    @property
    def native_value(self):
        budget = self.coordinator.diagnostics_manager.get_energy_budget()
        return round(budget.get("solar_kwh_used", 0.0), 3)


class BedGridEnergyTodaySensor(RejuvenationBedSensorBase):
    """Zeigt den Netz-Energieverbrauch."""
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:transmission-tower"
    
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Bett Netz-Energie"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_grid_energy"
    
    @property
    def native_value(self):
        budget = self.coordinator.diagnostics_manager.get_energy_budget()
        return round(budget.get("grid_kwh_used", 0.0), 3)


class BedAvgDailyEnergySensor(RejuvenationBedSensorBase):
    """Zeigt den durchschnittlichen täglichen Energieverbrauch."""
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:chart-line"
    
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Bett Ø Tagesverbrauch"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_avg_daily_energy"
    
    @property
    def native_value(self):
        budget = self.coordinator.diagnostics_manager.get_energy_budget()
        return round(budget.get("avg_kwh_per_day", 0.0), 3)
    
    @property
    def extra_state_attributes(self):
        budget = self.coordinator.diagnostics_manager.get_energy_budget()
        return {
            "tracking_days": budget.get("days_tracked", 0),
            "last_reset": budget.get("last_reset", "Unbekannt"),
        }


class BedHeatingHoursSensor(RejuvenationBedSensorBase):
    """Zeigt die Gesamtheizstunden."""
    _attr_icon = "mdi:clock-outline"
    _attr_native_unit_of_measurement = "h"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Bett Heizstunden"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_heating_hours"
    
    @property
    def native_value(self):
        budget = self.coordinator.diagnostics_manager.get_energy_budget()
        return round(budget.get("total_runtime_hours", 0.0), 1)


class BedLegacyComparisonSensor(RejuvenationBedSensorBase):
    """
    Vergleicht Smart-Steuerung mit traditioneller Wasserbett-Heizung.
    
    Der Vergleich basiert auf gemessenen Daten:
    - Hersteller-Thermostat: ~26% Duty-Cycle (kalibriert Feb 2026)
    - Smart-Steuerung: Tatsächlicher Verbrauch aus Energiezähler
    
    Die Ersparnis kommt hauptsächlich aus:
    1. Nachtabsenkung (Biorhythmus-Kurve)
    2. Solar-Nutzung (kostenloser Strom)
    3. Präsenz-basiert (nicht heizen wenn Bett leer)
    """
    _attr_icon = "mdi:chart-bar"
    _attr_native_unit_of_measurement = "%"
    
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Bett Ersparnis vs. Klassisch"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_legacy_comparison"
    
    @property
    def native_value(self):
        """Prozentuale Ersparnis gegenüber Legacy-Betrieb."""
        budget = self.coordinator.diagnostics_manager.get_energy_budget()
        
        smart_kwh = budget.get("total_kwh", 0)
        legacy_kwh = self.coordinator.diagnostics_manager._energy_budget.get("legacy_estimated_kwh", 0)
        
        if legacy_kwh <= 0 or smart_kwh <= 0:
            return 0
        
        savings_percent = ((legacy_kwh - smart_kwh) / legacy_kwh) * 100
        return round(max(0, min(100, savings_percent)), 1)
    
    @property
    def extra_state_attributes(self):
        budget = self.coordinator.diagnostics_manager.get_energy_budget()
        
        smart_kwh = budget.get("total_kwh", 0)
        legacy_kwh = self.coordinator.diagnostics_manager._energy_budget.get("legacy_estimated_kwh", 0)
        days = budget.get("days_tracked", 1)
        solar_kwh = self.coordinator.diagnostics_manager._energy_budget.get("solar_kwh_used", 0)
        
        # Hochrechnung auf Jahr
        smart_yearly = (smart_kwh / max(days, 1)) * 365
        legacy_yearly = (legacy_kwh / max(days, 1)) * 365
        
        # Kosten – aktuellen Strompreis nutzen wenn verfügbar
        energy_state = self.coordinator.energy_calculator.resolve()
        price_per_kwh = energy_state.get("current_price", 0.30)
        
        # Nur Grid-Kosten zählen (Solar ist kostenlos!)
        grid_kwh = smart_kwh - solar_kwh
        smart_cost = grid_kwh * price_per_kwh
        legacy_cost = legacy_kwh * price_per_kwh
        yearly_savings_eur = ((legacy_cost - smart_cost) / max(days, 1)) * 365
        
        return {
            "smart_verbrauch_kwh": round(smart_kwh, 2),
            "davon_solar_kwh": round(solar_kwh, 2),
            "davon_grid_kwh": round(grid_kwh, 2),
            "legacy_verbrauch_kwh": round(legacy_kwh, 2),
            "ersparnis_kwh": round(legacy_kwh - smart_kwh, 2),
            "smart_hochrechnung_jahr_kwh": round(smart_yearly, 1),
            "legacy_hochrechnung_jahr_kwh": round(legacy_yearly, 1),
            "geschaetzte_ersparnis_jahr_eur": round(yearly_savings_eur, 2),
            "strompreis_eur_kwh": round(price_per_kwh, 3),
            "tracking_tage": days,
            "berechnung": (
                f"Legacy: 26% Duty-Cycle (gemessen). "
                f"Smart: Tatsächlicher Verbrauch. "
                f"Solar-Anteil wird als kostenlos bewertet."
            ),
        }

class BedIntelligenceSensor(RejuvenationBedSensorBase):
    """
    Zeigt den Status der Bed-Intelligence Engine.
    
    Wert: "lernphase" oder "kalibriert"
    Attribute: Fortschritt, gelernte Schwellwerte, Feature-Status
    """
    _attr_icon = "mdi:brain"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Bett Intelligence"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_intelligence"

    @property
    def native_value(self):
        progress = self.coordinator.bed_intelligence.get_calibration_progress()
        status = progress.get("status", "unbekannt")
        if status == "lernphase":
            pct = progress.get("progress_percent", 0)
            return f"Lernphase ({pct}%)"
        return status

    @property
    def extra_state_attributes(self):
        bi = self.coordinator.bed_intelligence
        progress = bi.get_calibration_progress()
        
        attrs = {"calibration": progress}
        
        # Feature-Status für jede Zone
        zones = self.coordinator.config_entry.data.get("zones", [])
        for z_idx in range(len(zones)):
            diag = bi.get_diagnostics(z_idx)
            attrs[f"zone_{z_idx}_features"] = diag.get("features", {})
            attrs[f"zone_{z_idx}_isolation"] = diag.get("isolation", {})
            attrs[f"zone_{z_idx}_sweat"] = diag.get("sweat", {})
        
        return attrs


class BedtimePredictionSensor(RejuvenationBedSensorBase):
    """
    Zeigt die vom System gelernte Einschlafzeit-Vorhersage.
    
    Lernt aus den letzten 28 Nächten, unterscheidet Wochentag/Wochenende.
    Zeigt auch den vorhergesagten Vorheiz-Start.
    """
    _attr_icon = "mdi:crystal-ball"
    
    def __init__(self, coordinator, zone_index: int):
        super().__init__(coordinator)
        self._zone_idx = zone_index
        zone_suffix = f" Zone {zone_index + 1}" if len(coordinator.config_entry.data.get("zones", [])) > 1 else ""
        self._attr_name = f"Bett Einschlafzeit-Vorhersage{zone_suffix}"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_bedtime_prediction_{zone_index}"
    
    @property
    def native_value(self):
        bi = self.coordinator.bed_intelligence
        prediction = bi.predict_bedtime(self._zone_idx)
        if prediction:
            return prediction["predicted_str"]
        
        history = bi._bedtime_history.get(self._zone_idx, []) if hasattr(bi, '_bedtime_history') else []
        if history:
            return f"Lerne... ({len(history)}/{bi._MIN_SAMPLES_FOR_PREDICTION} Nächte)"
        return "Warte auf Daten"
    
    @property
    def extra_state_attributes(self):
        bi = self.coordinator.bed_intelligence
        diag = bi.get_bedtime_diagnostics(self._zone_idx)
        
        attrs = {
            "nächte_gespeichert": diag.get("nights_recorded", 0),
            "mindestens_nötig": diag.get("min_required", 3),
        }
        
        if "prediction" in diag:
            attrs["vorhersage"] = diag["prediction"]
            attrs["konfidenz"] = diag.get("confidence", "?")
            attrs["streuung_minuten"] = diag.get("spread_minutes", 0)
            attrs["basis"] = diag.get("basis", "?")
            
            if "predicted_preheat_start" in diag:
                attrs["vorheiz_start"] = diag["predicted_preheat_start"]
        
        if "recent_bedtimes" in diag:
            attrs["letzte_nächte"] = diag["recent_bedtimes"]
        
        return attrs
