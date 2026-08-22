from datetime import datetime

from atlas_trader.domain.enums.system_state import SystemState
from atlas_trader.domain.exceptions import InvalidSystemStateTransitionError
from atlas_trader.domain.interfaces.events import SystemEventRepository
from atlas_trader.domain.interfaces.risk import RiskStateRepository
from atlas_trader.domain.models.event import SystemEvent
from atlas_trader.domain.models.risk import RiskState


class AdminStateService:
    def __init__(
        self, risk_states: RiskStateRepository, events: SystemEventRepository, *, account_id: str
    ) -> None:
        self._risk_states = risk_states
        self._events = events
        self._account_id = account_id

    async def status(self) -> RiskState:
        state = await self._risk_states.get(self._account_id)
        if state is None:
            raise InvalidSystemStateTransitionError("risk state is not initialized")
        return state

    async def pause(
        self, *, reason: str, operator_id: str, correlation_id: str, now: datetime
    ) -> RiskState:
        return await self._transition(
            target=SystemState.PAUSED,
            allowed={SystemState.ENABLED},
            reason=reason,
            operator_id=operator_id,
            correlation_id=correlation_id,
            now=now,
        )

    async def resume(
        self, *, reason: str, operator_id: str, correlation_id: str, now: datetime
    ) -> RiskState:
        return await self._transition(
            target=SystemState.ENABLED,
            allowed={SystemState.PAUSED},
            reason=reason,
            operator_id=operator_id,
            correlation_id=correlation_id,
            now=now,
        )

    async def kill(
        self, *, reason: str, operator_id: str, correlation_id: str, now: datetime
    ) -> RiskState:
        return await self._transition(
            target=SystemState.KILLED,
            allowed={SystemState.ENABLED, SystemState.PAUSED},
            reason=reason,
            operator_id=operator_id,
            correlation_id=correlation_id,
            now=now,
        )

    async def reset_killed(
        self, *, reason: str, operator_id: str, correlation_id: str, now: datetime
    ) -> RiskState:
        return await self._transition(
            target=SystemState.PAUSED,
            allowed={SystemState.KILLED},
            reason=reason,
            operator_id=operator_id,
            correlation_id=correlation_id,
            now=now,
        )

    async def _transition(
        self,
        *,
        target: SystemState,
        allowed: set[SystemState],
        reason: str,
        operator_id: str,
        correlation_id: str,
        now: datetime,
    ) -> RiskState:
        current = await self.status()
        if current.system_state not in allowed:
            raise InvalidSystemStateTransitionError(
                f"cannot transition from {current.system_state.value} to {target.value}"
            )
        updated = current.model_copy(update={"system_state": target, "updated_at": now})
        await self._risk_states.save(updated)
        await self._events.append(
            SystemEvent(
                event_type="admin.system_state_changed",
                correlation_id=correlation_id,
                payload={
                    "account_id": self._account_id,
                    "from": current.system_state.value,
                    "to": target.value,
                    "reason": reason,
                    "operator_id": operator_id,
                },
                created_at=now,
            )
        )
        return updated
