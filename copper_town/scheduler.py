"""Core scheduler: reads triggers.yml, fires cron/poll triggers, manages lifecycle."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

import yaml
from croniter import croniter

from .config import (
    SCHEDULER_TICK_INTERVAL,
    TRIGGER_DEFAULT_TIMEOUT,
    TRIGGERS_CONFIG_PATH,
)
from .events import Event, EventType
from .polling import get_checker

if TYPE_CHECKING:
    from .engine import Engine
    from .polling import PollChecker

logger = logging.getLogger("copper_town.scheduler")


# ── Data classes ──────────────────────────────────────────────────────────

@dataclass
class TriggerDef:
    """Parsed trigger definition from triggers.yml."""
    name: str
    type: str                          # "cron" or "poll"
    agent: str
    task: str
    schedule: str | None = None        # cron expression (type=cron)
    interval: float = 60.0             # seconds between poll checks (type=poll)
    checker: str | None = None         # registered PollChecker name (type=poll)
    checker_args: dict[str, Any] = field(default_factory=dict)
    timeout: float = TRIGGER_DEFAULT_TIMEOUT
    enabled: bool = True


@dataclass
class TriggerState:
    """Runtime state for a trigger."""
    last_fired: float = 0.0            # wall-clock timestamp (time.time())
    last_checked: float = 0.0          # monotonic timestamp (poll only)
    fire_count: int = 0
    running: bool = False
    checker_instance: PollChecker | None = None


# ── Scheduler ─────────────────────────────────────────────────────────────

class Scheduler:
    """Reads triggers.yml and fires agent tasks on schedule or poll conditions."""

    def __init__(self, engine: "Engine", config_path: Path | None = None) -> None:
        self._engine = engine
        self._config_path = config_path or TRIGGERS_CONFIG_PATH
        self._triggers: dict[str, TriggerDef] = {}
        self._state: dict[str, TriggerState] = {}
        self._shutdown = asyncio.Event()
        self._active_tasks: set[asyncio.Task] = set()

    # ── Helpers ────────────────────────────────────────────────────────

    async def _emit(self, event_type: EventType, **data: Any) -> None:
        await self._engine.event_bus.publish(Event(
            type=event_type, source="scheduler", data=data,
        ))

    # ── Config loading ────────────────────────────────────────────────

    def _load_triggers(self) -> None:
        if not self._config_path.exists():
            logger.info("No triggers config at %s — nothing to schedule", self._config_path)
            return

        raw = yaml.safe_load(self._config_path.read_text(encoding="utf-8")) or {}

        for name, cfg in (raw.get("triggers") or {}).items():
            if not isinstance(cfg, dict):
                logger.warning("Skipping malformed trigger %r", name)
                continue

            ttype = cfg.get("type", "")
            if ttype not in ("cron", "poll"):
                logger.warning("Trigger %r has unknown type %r — skipping", name, ttype)
                continue

            agent = cfg.get("agent")
            task = cfg.get("task")
            if not agent or not task:
                logger.warning("Trigger %r missing agent or task — skipping", name)
                continue

            trig = TriggerDef(
                name=name,
                type=ttype,
                agent=agent,
                task=task,
                schedule=cfg.get("schedule"),
                interval=float(cfg.get("interval", 60)),
                checker=cfg.get("checker"),
                checker_args=cfg.get("checker_args") or {},
                timeout=float(cfg.get("timeout", TRIGGER_DEFAULT_TIMEOUT)),
                enabled=cfg.get("enabled", True),
            )

            if ttype == "cron" and not trig.schedule:
                logger.warning("Cron trigger %r missing schedule — skipping", name)
                continue
            if ttype == "poll" and not trig.checker:
                logger.warning("Poll trigger %r missing checker — skipping", name)
                continue

            if not trig.enabled:
                logger.info("Trigger %s is disabled — skipping", name)
                continue

            self._triggers[name] = trig
            self._state[name] = TriggerState()
            logger.info("Loaded trigger: %s (%s)", name, ttype)

    # ── Poll checker lifecycle ────────────────────────────────────────

    async def _setup_checkers(self) -> None:
        to_remove: list[str] = []
        for name, trig in self._triggers.items():
            if trig.type == "poll" and trig.checker:
                try:
                    checker = get_checker(trig.checker)
                    await checker.setup()
                    self._state[name].checker_instance = checker
                    logger.info("Checker %r ready for trigger %r", trig.checker, name)
                except KeyError:
                    logger.error("Unknown checker %r for trigger %r — disabling", trig.checker, name)
                    to_remove.append(name)
                except Exception:
                    logger.exception("Checker setup failed for trigger %r — disabling", name)
                    to_remove.append(name)
        for name in to_remove:
            del self._triggers[name]
            del self._state[name]

    async def _teardown_checkers(self) -> None:
        for state in self._state.values():
            if state.checker_instance:
                try:
                    await state.checker_instance.teardown()
                except Exception:
                    logger.exception("Checker teardown error")

    # ── Due-checking ──────────────────────────────────────────────────

    def _is_cron_due(self, trig: TriggerDef, state: TriggerState) -> bool:
        assert trig.schedule is not None
        now = time.time()
        prev_fire = croniter(trig.schedule, now).get_prev(float)
        return (now - prev_fire) <= SCHEDULER_TICK_INTERVAL * 2 and state.last_fired < prev_fire

    def _is_poll_due(self, trig: TriggerDef, state: TriggerState) -> bool:
        now = time.monotonic()
        return (now - state.last_checked) >= trig.interval

    # ── Firing ────────────────────────────────────────────────────────

    async def _fire_trigger(
        self, trig: TriggerDef, state: TriggerState, poll_result: str | None = None
    ) -> None:
        state.running = True
        state.fire_count += 1
        state.last_fired = time.time()

        task_text = trig.task
        if poll_result:
            task_text = task_text.replace("${poll_result}", poll_result)

        await self._emit(
            EventType.TRIGGER_FIRED,
            name=trig.name, agent=trig.agent, trigger_type=trig.type,
        )

        try:
            result = await asyncio.wait_for(
                self._engine.run_task(trig.agent, task_text),
                timeout=trig.timeout,
            )
            status = result.status.value if result else "unknown"
            await self._emit(
                EventType.TRIGGER_COMPLETED, name=trig.name, status=status,
            )
        except asyncio.TimeoutError:
            await self._emit(
                EventType.TRIGGER_ERROR,
                name=trig.name, error=f"Timeout after {trig.timeout}s",
            )
        except Exception as exc:
            await self._emit(
                EventType.TRIGGER_ERROR,
                name=trig.name, error=str(exc)[:200],
            )
        finally:
            state.running = False

    # ── Tick ──────────────────────────────────────────────────────────

    async def _check_poll(self, trig: TriggerDef, state: TriggerState) -> str | None:
        if not self._is_poll_due(trig, state):
            return None
        state.last_checked = time.monotonic()
        if not state.checker_instance:
            return None
        try:
            return await state.checker_instance.check(**trig.checker_args)
        except Exception:
            logger.exception("Checker %r raised during check", trig.checker)
            return None

    async def _tick(self) -> None:
        for name, trig in list(self._triggers.items()):
            state = self._state[name]
            if state.running:
                continue

            if trig.type == "cron" and self._is_cron_due(trig, state):
                self._spawn(self._fire_trigger(trig, state), name)
            elif trig.type == "poll":
                if poll_result := await self._check_poll(trig, state):
                    self._spawn(
                        self._fire_trigger(trig, state, poll_result=poll_result),
                        name,
                    )

    def _spawn(self, coro: Any, trigger_name: str) -> None:
        task = asyncio.create_task(coro, name=f"trigger-{trigger_name}")
        self._active_tasks.add(task)
        task.add_done_callback(self._active_tasks.discard)

    # ── Main loop ─────────────────────────────────────────────────────

    async def run(self) -> None:
        self._load_triggers()

        if not self._triggers:
            print("No triggers loaded — nothing to do.", flush=True)
            return

        print(f"Scheduler started with {len(self._triggers)} trigger(s).", flush=True)

        await self._setup_checkers()

        try:
            while not self._shutdown.is_set():
                await self._tick()
                try:
                    await asyncio.wait_for(self._shutdown.wait(), timeout=SCHEDULER_TICK_INTERVAL)
                except asyncio.TimeoutError:
                    pass  # normal — just means the tick interval elapsed
        finally:
            # Cancel and await in-flight trigger tasks
            for t in self._active_tasks:
                t.cancel()
            if self._active_tasks:
                await asyncio.gather(*self._active_tasks, return_exceptions=True)
            await self._teardown_checkers()
            print("Scheduler stopped.", flush=True)

    def request_shutdown(self) -> None:
        self._shutdown.set()

    # ── Introspection ─────────────────────────────────────────────────

    def list_triggers(self) -> list[dict[str, Any]]:
        return [
            {
                "name": name,
                "type": trig.type,
                "agent": trig.agent,
                "task": trig.task,
                "schedule": trig.schedule,
                "checker": trig.checker,
                "interval": trig.interval,
                "fire_count": self._state[name].fire_count,
                "running": self._state[name].running,
                "enabled": trig.enabled,
            }
            for name, trig in self._triggers.items()
        ]
