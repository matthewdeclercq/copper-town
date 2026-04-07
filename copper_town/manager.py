"""Agent lifecycle manager: concurrent runs with tracking, cancellation, timeout."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from .events import Event, EventBus, EventType
from .models import AgentResult, AgentStatus

if TYPE_CHECKING:
    from .engine import Engine

logger = logging.getLogger("copper_town.manager")


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


@dataclass
class AgentRun:
    id: str
    agent_slug: str
    task: str
    status: RunStatus = RunStatus.PENDING
    result: AgentResult | None = None
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    _task: asyncio.Task[None] | None = field(default=None, repr=False)


_MAX_COMPLETED_RUNS = 200


class AgentManager:
    """Supervisor for concurrent agent runs with tracking, cancellation, and timeout."""

    def __init__(
        self,
        engine: Engine,
        event_bus: EventBus | None = None,
        max_concurrent: int = 10,
        default_timeout: float = 300.0,
    ) -> None:
        self._engine = engine
        self._event_bus = event_bus
        self._max_concurrent = max_concurrent
        self._default_timeout = default_timeout
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._runs: dict[str, AgentRun] = {}

    async def _emit(
        self, event_type: EventType, source: str, data: dict[str, Any]
    ) -> None:
        if self._event_bus:
            await self._event_bus.publish(
                Event(type=event_type, source=source, data=data)
            )

    async def submit(
        self,
        agent_slug: str,
        task: str,
        context: str = "",
        timeout: float | None = None,
    ) -> str:
        """Submit an agent task. Returns a run_id for tracking."""
        run_id = str(uuid.uuid4())[:8]
        run = AgentRun(id=run_id, agent_slug=agent_slug, task=task)
        self._runs[run_id] = run

        await self._emit(
            EventType.TASK_SUBMITTED,
            "manager",
            {"run_id": run_id, "agent_slug": agent_slug, "task": task},
        )

        effective_timeout = timeout or self._default_timeout
        run._task = asyncio.create_task(self._run(run, context, effective_timeout))
        return run_id

    async def _run(self, run: AgentRun, context: str, timeout: float) -> None:
        run.status = RunStatus.RUNNING
        run.started_at = datetime.now()

        try:
            async with self._semaphore:
                result = await asyncio.wait_for(
                    self._engine.run_task(
                        run.agent_slug, run.task, context=context
                    ),
                    timeout=timeout,
                )
            run.result = result
            run.status = (
                RunStatus.COMPLETED if result.succeeded else RunStatus.FAILED
            )
            run.completed_at = datetime.now()
        except asyncio.TimeoutError:
            run.status = RunStatus.TIMEOUT
            run.completed_at = datetime.now()
            run.result = AgentResult(
                status=AgentStatus.TIMEOUT,
                result="",
                error="Task timed out",
                agent_slug=run.agent_slug,
                task=run.task,
            )
        except asyncio.CancelledError:
            run.status = RunStatus.CANCELLED
            run.completed_at = datetime.now()
            run.result = AgentResult(
                status=AgentStatus.CANCELLED,
                result="",
                error="Task cancelled",
                agent_slug=run.agent_slug,
                task=run.task,
            )
            await self._emit(
                EventType.TASK_CANCELLED,
                run.agent_slug,
                {"run_id": run.id},
            )
        except Exception as e:
            run.status = RunStatus.FAILED
            run.completed_at = datetime.now()
            run.result = AgentResult(
                status=AgentStatus.ERROR,
                result="",
                error=str(e),
                agent_slug=run.agent_slug,
                task=run.task,
            )
        finally:
            self._prune_runs()

    def _prune_runs(self) -> None:
        """Evict oldest completed runs to keep _runs from growing unbounded."""
        done = [r for r in self._runs.values()
                if r.status not in (RunStatus.PENDING, RunStatus.RUNNING)]
        if len(done) > _MAX_COMPLETED_RUNS:
            to_evict = sorted(done, key=lambda r: r.completed_at or datetime.min)
            for r in to_evict[:len(done) - _MAX_COMPLETED_RUNS]:
                del self._runs[r.id]

    async def cancel(self, run_id: str) -> bool:
        """Cancel a running task. Returns True if cancelled."""
        run = self._runs.get(run_id)
        if not run or not run._task:
            return False
        if run._task.done():
            return False
        run._task.cancel()
        await self._emit(
            EventType.TASK_CANCELLED, "manager", {"run_id": run_id}
        )
        return True

    def get_run(self, run_id: str) -> AgentRun | None:
        return self._runs.get(run_id)

    async def wait_for(self, run_id: str) -> AgentResult | None:
        """Wait for a specific run to complete and return its result."""
        run = self._runs.get(run_id)
        if not run or not run._task:
            return None
        try:
            await run._task
        except (asyncio.CancelledError, Exception):
            pass
        return run.result

    async def wait_all(self, run_ids: list[str]) -> list[AgentResult | None]:
        """Wait for all specified runs to complete."""
        tasks = []
        for rid in run_ids:
            run = self._runs.get(rid)
            if run and run._task:
                tasks.append(run._task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        return [self._runs[rid].result if rid in self._runs else None for rid in run_ids]

    def list_runs(self, status: RunStatus | None = None) -> list[AgentRun]:
        if status is None:
            return list(self._runs.values())
        return [r for r in self._runs.values() if r.status == status]

    def active_count(self) -> int:
        return sum(
            1
            for r in self._runs.values()
            if r.status in (RunStatus.PENDING, RunStatus.RUNNING)
        )
