DOMAIN = "rejuvenation_bed"
DEFAULT_POWER = 300
DEFAULT_SUMMER_TEMP = 25  # Außentemperatur-Schwelle, ab der der Sommer-Modus greift
DEFAULT_SUMMER_HOLD_TEMP = 25.0  # Bett-Haltetemperatur im Sommer-Modus
DEFAULT_MAX_TEMP = 36
ABSOLUTE_MAX_TEMP = 38
UPDATE_INTERVAL = 60


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
    "min_temp": 24.0,  # Kondensationsschutz (PFLICHT!)
    "max_temp": 30.0,  # Schlafkomfort
    "standby_temp": 26.0,  # Standby: Warmhalten (Kondensation!)
    "away_temp": 24.0,  # Urlaub-Modus (nie unter 24°C!)
    "eco_min_temp": 26.0,  # Eco-Absenkung nicht unter 26°C
    # Materialschutz
    "max_change_per_hour": 1.0,  # Max. 1°C/h (schont Vinyl-Schweißnähte)
    "ramp_enabled": True,  # Temperatur-Rampen AKTIV
    # Thermische Eigenschaften (kalibriert Feb 2026, Dual-Kern 2m×2m)
    # Hinweis: Eine Seite aktiv = zusätzliche Verluste an kalten Nachbar-Kern
    "heating_rate": 0.3,  # ~0.3°C/h bei 100% Duty (kalibriert Feb 2026)
    "cooling_rate": 0.1,  # ~0.1°C/h (Dual-Kern: kalte Seite zieht Wärme)
    "preheat_hours": 5.0,  # 5h vor Schlafzeit (konservativ bei 0.3°C/h)
    # Energie (kalibriert auf realen Verbrauch)
    # Fibaro-Power überschätzt um ~2.2x (misst Scheinleistung bei PWM)
    "power_sensor_correction": 0.45,  # Korrekturfaktor: gemessen × 0.45 = real
    "real_avg_watts": 50,  # Realer Durchschnitt: ~50W = 1.2 kWh/Tag
    "real_duty_cycle": 0.17,  # ~17% echte Heizzeit (4h/Tag)
    # Features
    "thermal_battery": True,  # Solar-Boost sinnvoll (speichert Wärme)
    "leak_detection": True,  # Leckage-Erkennung relevant
    "condensation_risk": True,  # Nie unter Mindesttemp!
    # Solar-Boost
    "solar_boost_max": 28.5,  # Max. Temperatur bei Solar-Überschuss
    "solar_boost_enabled": True,  # Feature aktiviert
    # Eco-Modus
    "eco_reduction_max": 2.0,  # Max. -2°C Absenkung
    "eco_can_turn_off": False,  # NIEMALS komplett AUS!
}

# ═══════════════════════════════════════════════════════════════════════════════
# HEIZMATTE PARAMETER (niedrige thermische Masse: nur Matratze + Körper)
# ═══════════════════════════════════════════════════════════════════════════════

HEATING_PAD_CONFIG = {
    # Temperatur-Grenzen
    "min_temp": 0.0,  # Kann komplett AUS sein
    "max_temp": 40.0,  # Höheres Limit OK (kein Wasser)
    "standby_temp": 0.0,  # Standby: AUS (keine Kondensationsgefahr)
    "away_temp": 0.0,  # Urlaub = AUS
    "eco_min_temp": 0.0,  # Eco = kann AUS sein
    # Materialschutz
    "max_change_per_hour": 10.0,  # Praktisch unbegrenzt (schnelle Reaktion)
    "ramp_enabled": False,  # Keine Rampen nötig
    # Thermische Eigenschaften
    "heating_rate": 5.0,  # ~5°C/h (schnell!)
    "cooling_rate": 3.0,  # ~3°C/h (kühlt schnell ab)
    "preheat_minutes": 15,  # Nur 15 Min vor Schlafzeit
    # Features
    "thermal_battery": False,  # Kein Wärmespeicher
    "leak_detection": False,  # Kein Wasser = keine Leckage
    "condensation_risk": False,  # Kein Risiko
    # Solar-Boost
    "solar_boost_max": 35.0,  # Kann wärmer werden
    "solar_boost_enabled": False,  # Macht keinen Sinn (speichert nicht)
    # Eco-Modus
    "eco_reduction_max": 100.0,  # Unbegrenzt
    "eco_can_turn_off": True,  # Kann komplett AUS
}

# ═══════════════════════════════════════════════════════════════════════════════
# LEGACY KONSTANTEN (für Abwärtskompatibilität - nutzen Wasserbett-Defaults)
# ═══════════════════════════════════════════════════════════════════════════════

# Diese werden noch von altem Code genutzt - schrittweise migrieren!
ABSOLUTE_MIN_TEMP = WATERBED_CONFIG["min_temp"]
SOLAR_BOOST_MAX_TEMP = WATERBED_CONFIG["solar_boost_max"]
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

DEFAULT_SICK_MODE_TEMP = 30.0  # Konstante Temp im Krank-Modus
DEFAULT_SICK_MODE_DAYS = 3  # Dauer Krank-Modus in Tagen
DEFAULT_BOOST_OFFSET = 2.0  # +2°C beim Schnellheizen
DEFAULT_COMFORT_OFFSET = 0.5  # +0.5°C beim Ausschlafen
BOOST_MAX_TEMP = 34.0  # Absolute Obergrenze Boost (Hardware-Thermostat = Backup)

# Manuelle Zieltemperatur (Slider): verfällt nach dieser Zeit → zurück zur Kurve
MANUAL_TARGET_TTL_HOURS = 8.0

# Fail-Safe bei Sensor-Ausfall (nur Wasserbett heizt blind weiter)
# Nach Ablauf wird von Dauer-AN auf Degraded-Duty (30%) zurückgefallen,
# damit eine fehlende Rückmeldung nicht zu unbegrenzter Volllast führt.
FAILSAFE_MAX_ON_MINUTES = 90.0

# Startup-Grace: ESP-Sensoren brauchen nach HA-Neustart Zeit zum Booten (O3)
STARTUP_GRACE_SECONDS = 180

# Heiz-Effizienz-Check: nach X Sekunden Dauerheizen wird ein Mindestanstieg
# erwartet, sonst Warnung (Wärmeverlust/Defekt) (O3)
HEATING_EFFICIENCY_WINDOW_SECONDS = 2700  # 45 Minuten
HEATING_EFFICIENCY_MIN_RISE_C = 0.2

# ═══════════════════════════════════════════════════════════════════════════════
# SOLAR-BOOST TRIGGER (unabhängige ODER-Auslöser)
# ═══════════════════════════════════════════════════════════════════════════════
# Der Bett-Boost kennt drei EIGENSTÄNDIGE Auslöser, die mit ODER verknüpft
# sind — jeder funktioniert allein, alle wirken auch zusammen:
#   1. Solar-Schwelle:  aktuelle PV-Leistung >= solar_boost_threshold
#   2. Akku-SoC:        Hausakku-SoC >= Schwelle (Akku voll → Überschuss nutzen)
#   3. PV-Forecast:     Rest-Tag-Prognose >= Schwelle (optional)
# Nur konfigurierte Sensoren zählen; fehlende Sensoren blockieren NICHT.
# Solar-only Setups verhalten sich also exakt wie früher.
#
# Optional: Akku-Vorrang (option "battery_priority", Default AUS). AN gatet
# die Solar-Schwelle hinter SoC/Forecast (UND) — klassisches Gating, gibt
# Akku/Boiler Vorrang auf den PV-Überschuss.

DEFAULT_BED_BOOST_SOC_THRESHOLD = 90.0  # %SoC ab dem der SoC-Trigger auslöst
DEFAULT_BED_BOOST_MIN_FORECAST_KWH = 3.0  # kWh Rest-Tag ab denen Forecast auslöst
BED_BOOST_SOC_HYSTERESIS = 5.0  # %SoC Hysterese (an: 90%, aus: 85%)
BED_BOOST_FORECAST_HYSTERESIS_KWH = 1.0  # kWh Hysterese (an: 3, aus: 2)

# ═══════════════════════════════════════════════════════════════════════════════
# PRÄSENZ-ERKENNUNG (Varianz-basiert, kalibriert Apr 2026)
# ═══════════════════════════════════════════════════════════════════════════════
# Kern-Erkenntnis: Heizung allein → gleichmäßiger Anstieg (niedrige Varianz)
#                  Person im Bett → chaotische Schwankungen (hohe Varianz)

PRESENCE_HISTORY_MINUTES = 30  # Analysefenster für Varianz/Trend
PRESENCE_VARIANCE_LOW = 0.02  # σ² darunter = definitiv Heizung
PRESENCE_VARIANCE_HIGH = 0.08  # σ² darüber = definitiv Person
PRESENCE_TREND_THRESHOLD = 0.85  # Konsistenz darüber = monoton (Heizung)
PRESENCE_TREND_CHAOTIC = 0.6  # Konsistenz darunter = chaotisch (Person)
PRESENCE_MIN_SAMPLES = 20  # Mindestens 20 Messwerte für Analyse
PRESENCE_DEBOUNCE_MINUTES = 15  # Minimum zwischen Statuswechseln
PRESENCE_BODY_TEMP_DIFF = 1.5  # °C Differenz Auflage-Wasser für Körperkontakt

# Device Info
MANUFACTURER = "Rejuvenation Bed"
SW_VERSION = "260620"

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
