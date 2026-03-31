"""
HeatingStateMachine - Unified heating control combining anti-short-cycle and ramp.

Consolidates the decision logic that was previously split across
AntiShortCycleManager and RampController into a single state machine.
This reduces per-loop state checks and makes the heating logic easier
to reason about.

States:
  IDLE      - Heater off, no demand
  RAMPING   - Gradually approaching target (vinyl protection)
  HEATING   - Heater on, maintaining/reaching target
  COOLDOWN  - Heater off, minimum off-time enforced
  HOLDING   - At target, heater cycling to maintain

The original AntiShortCycleManager and RampController remain functional
for backwards compatibility. This class wraps and coordinates them.
"""

import logging
from datetime import datetime
from enum import Enum
from typing import Optional
from dataclasses import dataclass

from .anti_short_cycle_manager import AntiShortCycleManager
from .ramp_controller import RampController

_LOGGER = logging.getLogger(__name__)


class HeatingState(Enum):
    """Possible states of the heating system."""

    IDLE = "idle"
    RAMPING = "ramping"
    HEATING = "heating"
    COOLDOWN = "cooldown"
    HOLDING = "holding"


@dataclass
class HeatingDecision:
    """Result of a heating state machine evaluation."""

    should_heat: bool
    state: HeatingState
    setpoint: float
    reason: str
    ramp_active: bool = False
    estimated_completion: Optional[datetime] = None


class HeatingStateMachine:
    """
    Unified heating controller per zone.

    Combines:
    - RampController (vinyl-safe temperature changes, max 1C/h)
    - AntiShortCycleManager (relay protection, min on/off times)

    One evaluate() call per loop replaces multiple separate checks.
    """

    def __init__(
        self,
        ramp_controller: RampController,
        anti_cycle: AntiShortCycleManager,
        ramp_enabled: bool = True,
    ):
        self.ramp = ramp_controller
        self.anti_cycle = anti_cycle
        self.ramp_enabled = ramp_enabled

        # Per-zone state tracking
        self._state: dict[int, HeatingState] = {}
        self._state_since: dict[int, datetime] = {}

    def evaluate(
        self,
        zone_index: int,
        heater_id: str,
        desired_temp: float,
        current_temp: float,
        heater_on: bool,
    ) -> HeatingDecision:
        """
        Single entry point for all heating decisions.

        Args:
            zone_index: Zone to evaluate
            heater_id: Entity ID of the heater switch
            desired_temp: Target temperature from calculator
            current_temp: Current measured temperature
            heater_on: Current heater state (True=ON)

        Returns:
            HeatingDecision with all relevant info
        """
        now = datetime.now()

        # Step 1: Apply ramp if enabled (waterbed vinyl protection)
        if self.ramp_enabled:
            setpoint, ramp_state = self.ramp.calculate_ramped_setpoint(
                zone_index, desired_temp, current_temp
            )
            ramp_active = ramp_state.ramp_active
            completion = ramp_state.estimated_completion
        else:
            setpoint = desired_temp
            ramp_active = False
            completion = None

        # Step 2: Determine if heater should be on based on setpoint vs current
        want_heat = current_temp < setpoint - 0.15  # Small deadband

        # Step 3: Check anti-short-cycle constraints
        allowed, cycle_reason = self.anti_cycle.can_switch(
            heater_id=heater_id,
            current_state=heater_on,
            desired_state=want_heat,
            current_temp=current_temp,
            target_temp=setpoint,
        )

        # Step 4: Final decision
        if allowed:
            should_heat = want_heat
        else:
            should_heat = heater_on  # Keep current state

        # Step 5: Determine state
        state = self._classify_state(
            should_heat, ramp_active, current_temp, setpoint, heater_on
        )

        # Track state transitions
        prev_state = self._state.get(zone_index)
        if state != prev_state:
            self._state[zone_index] = state
            self._state_since[zone_index] = now
            if prev_state is not None:
                _LOGGER.debug(
                    f"Zone {zone_index}: {prev_state.value} -> {state.value} "
                    f"(current={current_temp:.1f}, setpoint={setpoint:.1f})"
                )

        # Build reason string
        reason = self._build_reason(state, setpoint, cycle_reason, ramp_active)

        return HeatingDecision(
            should_heat=should_heat,
            state=state,
            setpoint=round(setpoint, 2),
            reason=reason,
            ramp_active=ramp_active,
            estimated_completion=completion,
        )

    def _classify_state(
        self,
        should_heat: bool,
        ramp_active: bool,
        current_temp: float,
        setpoint: float,
        heater_on: bool,
    ) -> HeatingState:
        """Classify the current state based on conditions."""
        if not should_heat and not heater_on:
            if ramp_active:
                return HeatingState.RAMPING
            return HeatingState.IDLE

        if should_heat and ramp_active:
            return HeatingState.RAMPING

        if should_heat:
            if abs(current_temp - setpoint) < 0.3:
                return HeatingState.HOLDING
            return HeatingState.HEATING

        # Heater is on but shouldn't be (anti-cycle holding)
        if heater_on and not should_heat:
            return HeatingState.COOLDOWN

        return HeatingState.IDLE

    def _build_reason(
        self,
        state: HeatingState,
        setpoint: float,
        cycle_reason: str,
        ramp_active: bool,
    ) -> str:
        if state == HeatingState.IDLE:
            return f"Standby ({setpoint:.1f}°C)"
        elif state == HeatingState.RAMPING:
            return f"Rampe aktiv -> {setpoint:.1f}°C"
        elif state == HeatingState.HEATING:
            return f"Heizen -> {setpoint:.1f}°C"
        elif state == HeatingState.COOLDOWN:
            return f"Abkühlen ({cycle_reason})"
        elif state == HeatingState.HOLDING:
            return f"Halten bei {setpoint:.1f}°C"
        return cycle_reason

    def get_state(self, zone_index: int) -> Optional[HeatingState]:
        """Get current state for a zone."""
        return self._state.get(zone_index)

    def get_diagnostics(self, zone_index: int) -> dict:
        """Combined diagnostics from both subsystems."""
        state = self._state.get(zone_index)
        since = self._state_since.get(zone_index)

        return {
            "state": state.value if state else "unknown",
            "state_since": since.isoformat() if since else None,
            "ramp_enabled": self.ramp_enabled,
            "ramp": self.ramp.get_ramp_state(zone_index).__dict__
            if self.ramp.get_ramp_state(zone_index)
            else None,
            "anti_cycle": self.anti_cycle.get_diagnostics(),
        }
