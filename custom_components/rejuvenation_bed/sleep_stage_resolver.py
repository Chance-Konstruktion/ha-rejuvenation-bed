"""
Sleep-Stage-Resolver für das Rejuvenation Bed.

Fungiert als Bridge zwischen Wearable-Sensoren (Apple Watch, Fitbit, etc.)
und der Biorhythmus-Kurve.

Wenn ein Wearable echte Schlafphasen-Daten liefert, können wir:
- Präziser in den Tiefschlaf-Modus wechseln
- Optimaler aufwecken (während Leichtschlaf-Phase)
- Die Kurve langfristig an dein Schlafverhalten anpassen
"""

import logging
from typing import Optional, Tuple
from homeassistant.core import HomeAssistant
from enum import Enum

_LOGGER = logging.getLogger(__name__)


class SleepStage(Enum):
    """Normierte Schlafphasen (unabhängig vom Wearable-Hersteller)."""
    AWAKE = "awake"
    LIGHT = "light"
    DEEP = "deep"
    REM = "rem"
    UNKNOWN = "unknown"


class SleepStageResolver:
    """
    Liest Schlafphasen-Daten von verschiedenen Wearable-Sensoren.
    
    Unterstützte Sensoren:
    - Apple Watch (über HA Companion App)
    - Fitbit (über Fitbit Integration)
    - Withings (über Withings Integration)
    - Generische Sensoren mit Standard-Werten
    """
    
    # Mapping verschiedener Wearable-Werte auf normierte Phasen
    STAGE_MAPPINGS = {
        # Apple Watch
        "asleep": SleepStage.LIGHT,
        "deep": SleepStage.DEEP,
        "core": SleepStage.LIGHT,  # Apple's "Core Sleep"
        "rem": SleepStage.REM,
        "awake": SleepStage.AWAKE,
        
        # Fitbit
        "light": SleepStage.LIGHT,
        "deep": SleepStage.DEEP,
        "rem": SleepStage.REM,
        "wake": SleepStage.AWAKE,
        
        # Withings
        "light_sleep": SleepStage.LIGHT,
        "deep_sleep": SleepStage.DEEP,
        "rem_sleep": SleepStage.REM,
        
        # Generisch
        "sleeping": SleepStage.LIGHT,
        "not_sleeping": SleepStage.AWAKE,
    }
    
    def __init__(
        self,
        hass: HomeAssistant,
        sleep_stage_entity: Optional[str] = None,
        enabled: bool = True
    ):
        """
        Initialisiert den Sleep-Stage-Resolver.
        
        Args:
            hass: Home Assistant Instanz
            sleep_stage_entity: Entity-ID des Schlafphasen-Sensors
                               (z.B. "sensor.apple_watch_sleep_stage")
            enabled: Ob Wearable-Daten genutzt werden sollen
        """
        self.hass = hass
        self.sleep_stage_entity = sleep_stage_entity
        self.enabled = enabled and sleep_stage_entity is not None
        
        if enabled and not sleep_stage_entity:
            _LOGGER.info(
                "Sleep-Stage-Resolver aktiviert, aber keine Entity konfiguriert. "
                "Fallback auf zeitbasierte Kurve."
            )
            self.enabled = False
    
    def get_current_stage(self) -> Tuple[SleepStage, str]:
        """
        Ermittelt die aktuelle Schlafphase.
        
        Returns:
            (sleep_stage, source) - Tuple mit Phase und Quelle
        """
        if not self.enabled:
            return SleepStage.UNKNOWN, "Wearable nicht konfiguriert"
        
        state = self.hass.states.get(self.sleep_stage_entity)
        
        if not state:
            _LOGGER.debug(
                f"Schlafphasen-Sensor '{self.sleep_stage_entity}' nicht gefunden."
            )
            return SleepStage.UNKNOWN, "Sensor nicht verfügbar"
        
        if state.state in ["unknown", "unavailable"]:
            return SleepStage.UNKNOWN, f"Sensor {state.state}"
        
        # State normieren (lowercase, whitespace entfernen)
        raw_stage = state.state.lower().strip()
        
        # Mapping durchsuchen
        normalized_stage = self.STAGE_MAPPINGS.get(raw_stage, SleepStage.UNKNOWN)
        
        if normalized_stage == SleepStage.UNKNOWN:
            _LOGGER.warning(
                f"Unbekannter Schlafphasen-Wert: '{state.state}'. "
                "Bitte melde dies als Issue mit deinem Wearable-Modell!"
            )
        
        return normalized_stage, self.sleep_stage_entity
    
    def should_override_curve(self) -> bool:
        """
        Prüft, ob Wearable-Daten die zeitbasierte Kurve überschreiben sollen.
        
        Returns:
            True, wenn Wearable verlässliche Daten liefert
        """
        if not self.enabled:
            return False
        
        stage, _ = self.get_current_stage()
        
        # Nur wenn wir eine klare Phase haben, überschreiben wir
        return stage != SleepStage.UNKNOWN
    
    def get_temperature_modifier(self) -> float:
        """
        Gibt einen Temperatur-Offset basierend auf der Schlafphase zurück.
        
        Logik:
        - Tiefschlaf → -0.5°C (kühlere Umgebung fördert Tiefschlaf)
        - REM → +0.0°C (neutral)
        - Leichtschlaf → +0.0°C
        - Aufwachen → +0.3°C (sanft wärmer werden)
        
        Returns:
            Temperatur-Offset in °C
        """
        stage, _ = self.get_current_stage()
        
        modifiers = {
            SleepStage.DEEP: -0.5,
            SleepStage.REM: 0.0,
            SleepStage.LIGHT: 0.0,
            SleepStage.AWAKE: 0.3,
            SleepStage.UNKNOWN: 0.0,
        }
        
        return modifiers.get(stage, 0.0)
    
    def get_diagnostics(self) -> dict:
        """
        Gibt Debug-Informationen zurück.
        
        Nützlich für UI und Troubleshooting.
        """
        stage, source = self.get_current_stage()
        
        diag = {
            "enabled": self.enabled,
            "entity": self.sleep_stage_entity or "Nicht konfiguriert",
            "current_stage": stage.value,
            "source": source,
            "temperature_modifier": self.get_temperature_modifier(),
            "override_active": self.should_override_curve(),
        }
        
        # Rohdaten hinzufügen
        if self.enabled and self.sleep_stage_entity:
            state = self.hass.states.get(self.sleep_stage_entity)
            if state:
                diag["raw_state"] = state.state
                diag["last_updated"] = state.last_updated.isoformat()
        
        return diag
    
    def get_optimal_wake_window(self) -> Optional[Tuple[int, int]]:
        """
        Berechnet das optimale Aufwach-Fenster basierend auf Schlafphasen.
        
        Wenn das Wearable Leichtschlaf-Phasen erkennt, können wir
        den Wecker "intelligenter" klingeln lassen.
        
        Returns:
            (minutes_before, minutes_after) - Fenster relativ zur wake_time
            oder None, wenn nicht verfügbar
        """
        if not self.should_override_curve():
            return None
        
        stage, _ = self.get_current_stage()
        
        # Nur in Leichtschlaf-Phasen ist sanftes Wecken optimal
        if stage == SleepStage.LIGHT:
            # Empfehlung: Bis zu 20 Min vor geplanter Zeit wecken,
            # wenn Leichtschlaf-Phase erreicht ist
            return (-20, 0)
        
        return None


# ============================================================================
# STANDALONE-TEST
# ============================================================================

if __name__ == "__main__":
    """
    Demo: Zeigt Funktionsweise des Sleep-Stage-Resolvers.
    """
    print("=" * 60)
    print("Sleep-Stage-Resolver Demo")
    print("=" * 60)
    print("\nDieser Resolver verbindet Wearables mit der Bett-Steuerung.")
    print("\nUnterstützte Schlafphasen:")
    for stage in SleepStage:
        print(f"  - {stage.value}")
    print("\nTemperatur-Modifikatoren:")
    print("  - Tiefschlaf: -0.5°C (fördert Regeneration)")
    print("  - REM: ±0.0°C (neutral)")
    print("  - Leichtschlaf: ±0.0°C")
    print("  - Aufwachen: +0.3°C (sanfte Aktivierung)")
    print("\n" + "=" * 60)
