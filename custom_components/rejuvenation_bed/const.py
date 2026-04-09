from dataclasses import dataclass
from typing import Optional

DOMAIN = "rejuvenation_bed"
DEFAULT_POWER = 300
DEFAULT_SUMMER_TEMP = 25
DEFAULT_MAX_TEMP = 36
ABSOLUTE_MAX_TEMP = 38
UPDATE_INTERVAL = 60


@dataclass(frozen=True)
class BedTypeConfig:
    """Validated configuration for a bed type.

    Using frozen=True prevents accidental mutation at runtime.
    """

    # Temperature limits
    min_temp: float
    max_temp: float
    standby_temp: float
    away_temp: float
    eco_min_temp: float

    # Material protection
    max_change_per_hour: float
    ramp_enabled: bool

    # Thermal properties
    heating_rate: float
    cooling_rate: float

    # Features
    thermal_battery: bool
    leak_detection: bool
    condensation_risk: bool

    # Solar
    solar_boost_max: float
    solar_boost_enabled: bool

    # Eco
    eco_reduction_max: float
    eco_can_turn_off: bool

    # Preheat (one of these is used depending on type)
    preheat_hours: Optional[float] = None
    preheat_minutes: Optional[int] = None

    # Energy calibration (waterbed specific)
    power_sensor_correction: Optional[float] = None
    real_avg_watts: Optional[int] = None
    real_duty_cycle: Optional[float] = None

    def __post_init__(self):
        if self.min_temp > self.max_temp:
            raise ValueError(
                f"min_temp ({self.min_temp}) > max_temp ({self.max_temp})"
            )
        if self.away_temp < self.min_temp:
            raise ValueError(
                f"away_temp ({self.away_temp}) < min_temp ({self.min_temp})"
            )
        if self.max_change_per_hour <= 0:
            raise ValueError("max_change_per_hour must be positive")

    def to_dict(self) -> dict:
        """Convert to dict for backwards compatibility."""
        from dataclasses import asdict
        return {k: v for k, v in asdict(self).items() if v is not None}

# ═══════════════════════════════════════════════════════════════════════════════
# BETT-TYPEN: WASSERBETT vs. HEIZMATTE
# ═══════════════════════════════════════════════════════════════════════════════
# Die Parameter unterscheiden sich fundamental aufgrund der thermischen Eigenschaften!

BED_TYPE_WATERBED = "wasserbett"
BED_TYPE_HEATING_PAD = "heizmatte"

# ═══════════════════════════════════════════════════════════════════════════════
# WASSERBETT PARAMETER (hohe thermische Masse: 300-700L Wasser)
# ═══════════════════════════════════════════════════════════════════════════════

WATERBED_CONFIG = {
    # Temperatur-Grenzen
    "min_temp": 24.0,              # Kondensationsschutz (PFLICHT!)
    "max_temp": 30.0,              # Schlafkomfort
    "standby_temp": 26.0,          # Standby: Warmhalten (Kondensation!)
    "away_temp": 24.0,             # Urlaub-Modus (nie unter 24°C!)
    "eco_min_temp": 26.0,          # Eco-Absenkung nicht unter 26°C
    
    # Materialschutz
    "max_change_per_hour": 1.0,    # Max. 1°C/h (schont Vinyl-Schweißnähte)
    "ramp_enabled": True,          # Temperatur-Rampen AKTIV
    
    # Thermische Eigenschaften (kalibriert Feb 2026, Dual-Kern 2m×2m)
    # Hinweis: Eine Seite aktiv = zusätzliche Verluste an kalten Nachbar-Kern
    "heating_rate": 0.3,           # ~0.3°C/h bei 100% Duty (kalibriert Feb 2026)
    "cooling_rate": 0.1,           # ~0.1°C/h (Dual-Kern: kalte Seite zieht Wärme)
    "preheat_hours": 5.0,          # 5h vor Schlafzeit (konservativ bei 0.3°C/h)
    
    # Energie (kalibriert auf realen Verbrauch)
    # Fibaro-Power überschätzt um ~2.2x (misst Scheinleistung bei PWM)
    "power_sensor_correction": 0.45,  # Korrekturfaktor: gemessen × 0.45 = real
    "real_avg_watts": 50,          # Realer Durchschnitt: ~50W = 1.2 kWh/Tag
    "real_duty_cycle": 0.17,       # ~17% echte Heizzeit (4h/Tag)
    
    # Features
    "thermal_battery": True,       # Solar-Boost sinnvoll (speichert Wärme)
    "leak_detection": True,        # Leckage-Erkennung relevant
    "condensation_risk": True,     # Nie unter Mindesttemp!
    
    # Solar-Boost
    "solar_boost_max": 28.5,       # Max. Temperatur bei Solar-Überschuss
    "solar_boost_enabled": True,   # Feature aktiviert
    
    # Eco-Modus
    "eco_reduction_max": 2.0,      # Max. -2°C Absenkung
    "eco_can_turn_off": False,     # NIEMALS komplett AUS!
}

# ═══════════════════════════════════════════════════════════════════════════════
# HEIZMATTE PARAMETER (niedrige thermische Masse: nur Matratze + Körper)
# ═══════════════════════════════════════════════════════════════════════════════

HEATING_PAD_CONFIG = {
    # Temperatur-Grenzen
    "min_temp": 0.0,               # Kann komplett AUS sein
    "max_temp": 40.0,              # Höheres Limit OK (kein Wasser)
    "standby_temp": 0.0,           # Standby: AUS (keine Kondensationsgefahr)
    "away_temp": 0.0,              # Urlaub = AUS
    "eco_min_temp": 0.0,           # Eco = kann AUS sein
    
    # Materialschutz
    "max_change_per_hour": 10.0,   # Praktisch unbegrenzt (schnelle Reaktion)
    "ramp_enabled": False,         # Keine Rampen nötig
    
    # Thermische Eigenschaften
    "heating_rate": 5.0,           # ~5°C/h (schnell!)
    "cooling_rate": 3.0,           # ~3°C/h (kühlt schnell ab)
    "preheat_minutes": 15,         # Nur 15 Min vor Schlafzeit
    
    # Features
    "thermal_battery": False,      # Kein Wärmespeicher
    "leak_detection": False,       # Kein Wasser = keine Leckage
    "condensation_risk": False,    # Kein Risiko
    
    # Solar-Boost
    "solar_boost_max": 35.0,       # Kann wärmer werden
    "solar_boost_enabled": False,  # Macht keinen Sinn (speichert nicht)
    
    # Eco-Modus
    "eco_reduction_max": 100.0,    # Unbegrenzt
    "eco_can_turn_off": True,      # Kann komplett AUS
}

# ═══════════════════════════════════════════════════════════════════════════════
# TYPED CONFIGS (validated dataclass versions)
# ═══════════════════════════════════════════════════════════════════════════════

WATERBED_TYPE_CONFIG = BedTypeConfig(
    min_temp=24.0,
    max_temp=30.0,
    standby_temp=26.0,
    away_temp=24.0,
    eco_min_temp=26.0,
    max_change_per_hour=1.0,
    ramp_enabled=True,
    heating_rate=0.3,
    cooling_rate=0.1,
    preheat_hours=5.0,
    thermal_battery=True,
    leak_detection=True,
    condensation_risk=True,
    solar_boost_max=28.5,
    solar_boost_enabled=True,
    eco_reduction_max=2.0,
    eco_can_turn_off=False,
    power_sensor_correction=0.45,
    real_avg_watts=50,
    real_duty_cycle=0.17,
)

HEATING_PAD_TYPE_CONFIG = BedTypeConfig(
    min_temp=0.0,
    max_temp=40.0,
    standby_temp=0.0,
    away_temp=0.0,
    eco_min_temp=0.0,
    max_change_per_hour=10.0,
    ramp_enabled=False,
    heating_rate=5.0,
    cooling_rate=3.0,
    preheat_minutes=15,
    thermal_battery=False,
    leak_detection=False,
    condensation_risk=False,
    solar_boost_max=35.0,
    solar_boost_enabled=False,
    eco_reduction_max=100.0,
    eco_can_turn_off=True,
)

# ═══════════════════════════════════════════════════════════════════════════════
# LEGACY KONSTANTEN (für Abwärtskompatibilität - nutzen Wasserbett-Defaults)
# ═══════════════════════════════════════════════════════════════════════════════

# Diese werden noch von altem Code genutzt - schrittweise migrieren!
ABSOLUTE_MIN_TEMP = WATERBED_CONFIG["min_temp"]
ABSOLUTE_MAX_TEMP_WATER = WATERBED_CONFIG["max_temp"]
DEFAULT_AWAY_TEMP = WATERBED_CONFIG["away_temp"]
AWAY_TEMP_SHORT = 25.0
AWAY_TEMP_LONG = 24.0
SOLAR_BOOST_MAX_TEMP = WATERBED_CONFIG["solar_boost_max"]
ECO_REDUCTION_MAX = WATERBED_CONFIG["eco_reduction_max"]
ECO_MIN_TEMP = WATERBED_CONFIG["eco_min_temp"]
MAX_TEMP_CHANGE_PER_HOUR = WATERBED_CONFIG["max_change_per_hour"]
TYPICAL_HEATING_RATE = WATERBED_CONFIG["heating_rate"]
PREHEAT_BUFFER_HOURS = 1.0

# ═══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTION
# ═══════════════════════════════════════════════════════════════════════════════

def get_bed_config(bed_type: str) -> dict:
    """
    Gibt die Konfiguration für den Bett-Typ zurück.
    
    Args:
        bed_type: "wasserbett" oder "heizmatte"
    
    Returns:
        Dict mit allen typ-spezifischen Parametern
    """
    if bed_type == BED_TYPE_HEATING_PAD:
        return HEATING_PAD_CONFIG.copy()
    return WATERBED_CONFIG.copy()  # Default = Wasserbett (sicherer)

# ═══════════════════════════════════════════════════════════════════════════════
# MODUS-DEFAULTS
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_SICK_MODE_TEMP = 30.0       # Konstante Temp im Krank-Modus
DEFAULT_SICK_MODE_DAYS = 3          # Dauer Krank-Modus in Tagen
DEFAULT_BOOST_OFFSET = 2.0          # +2°C beim Schnellheizen
DEFAULT_COMFORT_OFFSET = 0.5        # +0.5°C beim Ausschlafen
BOOST_MAX_TEMP = 34.0               # Absolute Obergrenze Boost (Hardware-Thermostat = Backup)

# ═══════════════════════════════════════════════════════════════════════════════
# PRÄSENZ-ERKENNUNG (Varianz-basiert, kalibriert Apr 2026)
# ═══════════════════════════════════════════════════════════════════════════════
# Kern-Erkenntnis: Heizung allein → gleichmäßiger Anstieg (niedrige Varianz)
#                  Person im Bett → chaotische Schwankungen (hohe Varianz)

PRESENCE_HISTORY_MINUTES = 30           # Analysefenster für Varianz/Trend
PRESENCE_VARIANCE_LOW = 0.02            # σ² darunter = definitiv Heizung
PRESENCE_VARIANCE_HIGH = 0.08           # σ² darüber = definitiv Person
PRESENCE_TREND_THRESHOLD = 0.85         # Konsistenz darüber = monoton (Heizung)
PRESENCE_TREND_CHAOTIC = 0.6            # Konsistenz darunter = chaotisch (Person)
PRESENCE_MIN_SAMPLES = 20              # Mindestens 20 Messwerte für Analyse
PRESENCE_DEBOUNCE_MINUTES = 15          # Minimum zwischen Statuswechseln
PRESENCE_BODY_TEMP_DIFF = 1.5           # °C Differenz Auflage-Wasser für Körperkontakt

# Device Info
MANUFACTURER = "Rejuvenation Bed"
SW_VERSION = "0.7.0"

# ═══════════════════════════════════════════════════════════════════════════════
# ZEIT-HELPER
# ═══════════════════════════════════════════════════════════════════════════════

def local_now():
    """
    Aktuelle Lokalzeit als naive Datetime.
    
    Nutzt dt_util.now() für die korrekte HA-Zeitzone, 
    strippt aber tzinfo für Kompatibilität mit dem restlichen Code.
    Alle internen Zeitvergleiche (Weckzeit, warm_from, etc.) 
    arbeiten mit naiven Datetimes.
    """
    from homeassistant.util import dt as dt_util
    return dt_util.now().replace(tzinfo=None)
