"""
Anti-Short-Cycle-Manager für das Rejuvenation Bed.

KRITISCH für Wasserbetten!

Wasserbetten haben:
- Hohe thermische Trägheit (200-400L Wasser)
- Langsame Temperaturänderungen (1°C in 15-20 Min)

Probleme ohne Anti-Short-Cycle:
- Relais schaltet alle 60s (bei Wolken + Solar)
- Mechanischer Verschleiß
- Verkürzte Relais-Lebensdauer
- Unnötiger Stromverbrauch durch Schaltverluste

Lösung:
- Minimum ON-Zeit: 10 Minuten
- Minimum OFF-Zeit: 5 Minuten
- Sanfte Übergänge durch Hysterese

FIX v0.1.1: Grace Period blockiert nicht mehr das Einschalten!
"""

import logging
from datetime import timedelta
from typing import Dict, Optional, Tuple

from .const import local_now

_LOGGER = logging.getLogger(__name__)


class AntiShortCycleManager:
    """
    Verhindert zu häufiges Schalten der Relais.

    Basiert auf bewährten Thermostat-Praktiken:
    - Minimum Run Time (Relais läuft mind. X Minuten)
    - Minimum Off Time (Relais pausiert mind. Y Minuten)
    - Grace Period (Startverzögerung nach HA-Neustart)

    FIX: Grace Period erlaubt jetzt das EINSCHALTEN, blockiert nur
         schnelles Hin-und-Her-Schalten.
    """

    # Konfigurierbare Zeiten (können später in Options übernommen werden)
    MIN_RUN_TIME_SECONDS = 600  # 10 Minuten minimum AN
    MIN_OFF_TIME_SECONDS = 300  # 5 Minuten minimum AUS
    GRACE_PERIOD_SECONDS = 120  # 2 Minuten nach HA-Start

    # Hysterese (verhindert Flattern an der Grenze)
    HYSTERESIS_DELTA_C = 0.3  # ±0.3°C Hysterese

    def __init__(self):
        """Initialisiert den Anti-Short-Cycle-Manager."""
        self._state_history: Dict[str, dict] = {}
        self._startup_time = local_now()
        self._blocked_switches = 0  # Statistik
        self._total_decisions = 0  # Statistik
        self._grace_period_active = True  # NEU: Flag für Grace Period

    def can_switch(
        self,
        heater_id: str,
        current_state: bool,
        desired_state: bool,
        current_temp: float,
        target_temp: float,
        actual_hardware_state: Optional[bool] = None,  # NEU: Echter Hardware-Zustand
    ) -> Tuple[bool, str]:
        """
        Prüft, ob ein Schalter-Wechsel erlaubt ist.

        Args:
            heater_id: Entity-ID des Heizers (z.B. "switch.bett_heizung")
            current_state: Aktueller Zustand aus internem Tracking (True = AN, False = AUS)
            desired_state: Gewünschter Zustand
            current_temp: Aktuelle Temperatur (°C)
            target_temp: Zieltemperatur (°C)
            actual_hardware_state: NEU! Echter Zustand aus Home Assistant (falls bekannt)

        Returns:
            (allowed, reason) - Tuple mit Erlaubnis und Begründung
        """
        self._total_decisions += 1
        now = local_now()

        # ═══════════════════════════════════════════════════════════════════════
        # FIX: Grace Period - NICHT mehr komplett blockieren!
        # Stattdessen: Erlaube EINSCHALTEN wenn Heizung gebraucht wird
        # ═══════════════════════════════════════════════════════════════════════
        if self._is_in_grace_period():
            # NEU: Wenn echter Hardware-Zustand bekannt ist, synchronisieren
            if actual_hardware_state is not None and heater_id not in self._state_history:
                self._state_history[heater_id] = {
                    "current_state": actual_hardware_state,
                    "last_change": now - timedelta(minutes=30),  # Fake "lange her"
                    "last_on_time": now - timedelta(minutes=30) if actual_hardware_state else None,
                    "last_off_time": now - timedelta(minutes=30) if not actual_hardware_state else None,
                }
                _LOGGER.info(
                    f"Grace Period: Synchronisiere {heater_id} mit echtem Zustand: "
                    f"{'AN' if actual_hardware_state else 'AUS'}"
                )

            # FIX: Während Grace Period erlauben wir das gewünschte Verhalten,
            # aber loggen es deutlich
            if desired_state != current_state:
                _LOGGER.info(
                    f"Grace Period: Erlaube Schalten von {heater_id} "
                    f"({'AUS→AN' if desired_state else 'AN→AUS'}) - "
                    f"Temp: {current_temp:.1f}°C, Ziel: {target_temp:.1f}°C"
                )

            # Initialisiere History falls noch nicht vorhanden
            if heater_id not in self._state_history:
                self._state_history[heater_id] = {
                    "current_state": current_state,
                    "last_change": now,
                    "last_on_time": now if desired_state else None,
                    "last_off_time": now if not desired_state else None,
                }

            # FIX: Während Grace Period erlauben - keine Blockierung mehr!
            return desired_state, "Grace Period (erlaubt)"

        # Nach Grace Period: Normale Logik
        self._grace_period_active = False

        # Initialisiere History für diesen Heater (falls noch nicht vorhanden)
        if heater_id not in self._state_history:
            self._state_history[heater_id] = {
                "current_state": current_state,
                "last_change": now,
                "last_on_time": None,
                "last_off_time": None,
            }
            _LOGGER.debug(f"Erste Entscheidung für {heater_id}: desired={desired_state}")
            return desired_state, "Erste Entscheidung"

        history = self._state_history[heater_id]

        # Wenn gewünschter Zustand = aktueller Zustand → Erlaubt
        if desired_state == current_state:
            return True, "Keine Änderung nötig"

        # Hysterese-Check (verhindert Flattern)
        if not self._hysteresis_allows_switch(current_temp, target_temp, current_state, desired_state):
            self._blocked_switches += 1
            _LOGGER.debug(f"{heater_id}: Hysterese blockiert - " f"Temp={current_temp:.1f}°C, Ziel={target_temp:.1f}°C")
            return False, f"Hysterese (±{self.HYSTERESIS_DELTA_C}°C)"

        # Zeitbasierte Checks

        # Fall 1: Heizung will EINSCHALTEN (current=OFF, desired=ON)
        if not current_state and desired_state:
            # Prüfe Minimum OFF-Zeit
            if history["last_off_time"]:
                time_since_off = (now - history["last_off_time"]).total_seconds()
                if time_since_off < self.MIN_OFF_TIME_SECONDS:
                    remaining = self.MIN_OFF_TIME_SECONDS - time_since_off
                    self._blocked_switches += 1
                    _LOGGER.debug(f"{heater_id}: Min. OFF-Zeit nicht erreicht " f"(noch {int(remaining)}s)")
                    return False, f"Min. OFF-Zeit (noch {int(remaining)}s)"

            # Erlaubt
            self._update_history(heater_id, True)
            _LOGGER.debug(f"{heater_id}: Einschalten erlaubt")
            return True, "Einschalten erlaubt"

        # Fall 2: Heizung will AUSSCHALTEN (current=ON, desired=OFF)
        if current_state and not desired_state:
            # Prüfe Minimum ON-Zeit
            if history["last_on_time"]:
                time_since_on = (now - history["last_on_time"]).total_seconds()
                if time_since_on < self.MIN_RUN_TIME_SECONDS:
                    remaining = self.MIN_RUN_TIME_SECONDS - time_since_on
                    self._blocked_switches += 1
                    _LOGGER.debug(f"{heater_id}: Min. ON-Zeit nicht erreicht " f"(noch {int(remaining)}s)")
                    return False, f"Min. ON-Zeit (noch {int(remaining)}s)"

            # Erlaubt
            self._update_history(heater_id, False)
            _LOGGER.debug(f"{heater_id}: Ausschalten erlaubt")
            return True, "Ausschalten erlaubt"

        # Sollte nie erreicht werden, aber Sicherheit
        return True, "Unbekannter Fall"

    def _hysteresis_allows_switch(
        self, current_temp: float, target_temp: float, current_state: bool, desired_state: bool
    ) -> bool:
        """
        Hysterese-Logik: Verhindert Flattern an der Zieltemperatur.

        Beispiel:
        - Ziel: 28.0°C
        - Hysterese: ±0.3°C

        Wenn Heizung AN:
          → Schaltet erst bei ≥28.0°C aus (kein Offset nach oben)

        Wenn Heizung AUS:
          → Schaltet erst bei <27.7°C ein (Offset nach unten)

        Das verhindert, dass die Heizung bei 27.95°C ständig an/aus geht.
        """
        delta = current_temp - target_temp

        # Heizung ist AN, will AUSSCHALTEN
        if current_state and not desired_state:
            # Nur ausschalten, wenn wir wirklich über dem Ziel sind
            return delta >= 0.0

        # Heizung ist AUS, will EINSCHALTEN
        if not current_state and desired_state:
            # Nur einschalten, wenn wir deutlich unter dem Ziel sind
            return delta < -self.HYSTERESIS_DELTA_C

        return True  # Andere Fälle erlauben

    def _update_history(self, heater_id: str, new_state: bool):
        """Aktualisiert die Switch-Historie mit automatischer Bereinigung."""
        now = local_now()

        # NEU: Alte Einträge bereinigen (älter als 24h nicht mehr relevant)
        cutoff = now - timedelta(hours=24)
        self._state_history = {k: v for k, v in self._state_history.items() if v.get("last_change", now) > cutoff}

        self._state_history[heater_id]["current_state"] = new_state
        self._state_history[heater_id]["last_change"] = now

        if new_state:
            self._state_history[heater_id]["last_on_time"] = now
        else:
            self._state_history[heater_id]["last_off_time"] = now

    def _is_in_grace_period(self) -> bool:
        """Prüft, ob wir noch in der Grace Period nach HA-Start sind."""
        elapsed = (local_now() - self._startup_time).total_seconds()
        return elapsed < self.GRACE_PERIOD_SECONDS

    def sync_with_hardware(self, heater_id: str, actual_state: bool):
        """
        NEU: Synchronisiert den internen Zustand mit dem echten Hardware-Zustand.

        Sollte beim ersten Update nach HA-Start aufgerufen werden!

        Args:
            heater_id: Entity-ID des Heaters
            actual_state: Echter Zustand aus Home Assistant
        """
        now = local_now()

        if heater_id in self._state_history:
            old_state = self._state_history[heater_id]["current_state"]
            if old_state != actual_state:
                _LOGGER.warning(
                    f"Hardware-Sync: {heater_id} war intern "
                    f"{'AN' if old_state else 'AUS'}, aber Hardware ist "
                    f"{'AN' if actual_state else 'AUS'}. Synchronisiere."
                )

        self._state_history[heater_id] = {
            "current_state": actual_state,
            "last_change": now - timedelta(minutes=30),  # Fake "lange her" für sofortige Schaltbarkeit
            "last_on_time": now - timedelta(minutes=30) if actual_state else None,
            "last_off_time": now - timedelta(minutes=30) if not actual_state else None,
        }

    def get_diagnostics(self) -> dict:
        """
        Gibt Statistiken über Short-Cycle-Protection zurück.

        Nützlich für UI und Debugging.
        """
        total_blocked_pct = 0.0
        if self._total_decisions > 0:
            total_blocked_pct = (self._blocked_switches / self._total_decisions) * 100

        return {
            "total_decisions": self._total_decisions,
            "blocked_switches": self._blocked_switches,
            "blocked_percentage": round(total_blocked_pct, 1),
            "min_run_time_seconds": self.MIN_RUN_TIME_SECONDS,
            "min_off_time_seconds": self.MIN_OFF_TIME_SECONDS,
            "hysteresis_delta_c": self.HYSTERESIS_DELTA_C,
            "grace_period_active": self._is_in_grace_period(),
            "active_heaters": len(self._state_history),
            "heater_states": {
                heater_id: {
                    "state": "ON" if history["current_state"] else "OFF",
                    "last_change": history["last_change"].isoformat(),
                }
                for heater_id, history in self._state_history.items()
            },
        }

    def force_allow_switch(self, heater_id: str):
        """
        Erzwingt das Erlauben des nächsten Switches (Emergency Override).

        VORSICHT: Nur für manuelle User-Eingriffe oder Notfälle!
        """
        if heater_id in self._state_history:
            # Reset der Zeiten → nächster Switch wird erlaubt
            self._state_history[heater_id]["last_on_time"] = None
            self._state_history[heater_id]["last_off_time"] = None
            _LOGGER.warning(f"Anti-Short-Cycle für {heater_id} manuell überschrieben!")


# ============================================================================
# STANDALONE-TEST
# ============================================================================

if __name__ == "__main__":
    """
    Simuliert typische Wasserbett-Szenarien.
    """
    print("=" * 60)
    print("Anti-Short-Cycle-Manager Test")
    print("=" * 60)

    manager = AntiShortCycleManager()

    # Szenario 1: Normale Heiz-Zyklen
    print("\n### Szenario 1: Normaler Betrieb ###")

    # Erste Entscheidung: Einschalten
    allowed, reason = manager.can_switch(
        "switch.bett_heizung", current_state=False, desired_state=True, current_temp=27.0, target_temp=28.0
    )
    print(f"Einschalten? {allowed} - {reason}")

    # 5 Sekunden später: Will wieder ausschalten (zu schnell!)
    from time import sleep

    sleep(5)
    allowed, reason = manager.can_switch(
        "switch.bett_heizung", current_state=True, desired_state=False, current_temp=28.1, target_temp=28.0
    )
    print(f"Ausschalten nach 5s? {allowed} - {reason}")

    # Statistik
    print("\n### Diagnostics ###")
    diag = manager.get_diagnostics()
    print(f"Gesamt-Entscheidungen: {diag['total_decisions']}")
    print(f"Blockierte Switches: {diag['blocked_switches']}")
    print(f"Block-Rate: {diag['blocked_percentage']}%")

    print("\n" + "=" * 60)
    print("Test abgeschlossen!")
