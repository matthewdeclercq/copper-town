"""Starlette HTTP API for Copper-Town agents with SSE streaming."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
from typing import TYPE_CHECKING

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from sse_starlette.sse import EventSourceResponse

from .config import API_KEY
from .engine import _bg_messages_ctx, _bg_push_ctx, _bg_lock_ctx
from .sessions import SessionManager

if TYPE_CHECKING:
    from .engine import Engine

logger = logging.getLogger("copper_town.api")


# ── Auth middleware (pure ASGI) ────────────────────────────────────────────

class APIKeyMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope["path"]
        if path == "/health" or not path.startswith("/api/") or not API_KEY:
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        key = headers.get(b"x-api-key", b"").decode()
        if not hmac.compare_digest(key, API_KEY):
            response = JSONResponse({"error": "Unauthorized"}, status_code=401)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


# ── Endpoints ──────────────────────────────────────────────────────────────

async def health(request: Request) -> Response:
    return JSONResponse({"status": "ok"})


async def list_agents(request: Request) -> Response:
    engine: Engine = request.app.state.engine
    return JSONResponse(engine.list_agents())


async def create_session(request: Request) -> Response:
    engine: Engine = request.app.state.engine
    sm: SessionManager = request.app.state.sessions

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    agent_slug = body.get("agent", "")
    if not agent_slug:
        return JSONResponse({"error": "Missing 'agent' field"}, status_code=400)

    try:
        session = await sm.create(agent_slug, engine)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=404)

    return JSONResponse({"session_id": session.id, "agent": session.agent_slug})


async def list_sessions(request: Request) -> Response:
    sm: SessionManager = request.app.state.sessions
    return JSONResponse(sm.list_sessions())


async def delete_session(request: Request) -> Response:
    engine: Engine = request.app.state.engine
    sm: SessionManager = request.app.state.sessions
    session_id = request.path_params["session_id"]

    session = sm.get(session_id)
    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    # Acquire lock to wait for any active stream to finish, then remove
    async with session.lock:
        sm.delete(session_id)

    # Fire-and-forget memory extraction (LLM call can take seconds)
    agent = engine.agents.get(session.agent_slug)
    if agent:
        async def _extract():
            try:
                await engine._extract_session_memory(agent, session.messages)
            except Exception as e:
                logger.warning("Memory extraction failed for session %s: %s", session_id, e)
        asyncio.create_task(_extract())

    return JSONResponse({"status": "deleted"})


async def send_message(request: Request) -> Response:
    engine: Engine = request.app.state.engine
    sm: SessionManager = request.app.state.sessions
    session_id = request.path_params["session_id"]

    session = sm.get(session_id)
    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    content = body.get("content", "").strip()
    if not content:
        return JSONResponse({"error": "Missing 'content' field"}, status_code=400)

    agent = engine.agents.get(session.agent_slug)
    if not agent:
        return JSONResponse({"error": "Agent not found"}, status_code=404)

    async def event_generator():
        async with session.lock:
            # Drain background task notifications
            pending = engine._bg.drain_into_messages(session.messages)
            if pending:
                yield {"event": "notifications", "data": json.dumps(pending)}

            tasks_before = set(engine._bg.active_ids())
            restore_len = len(session.messages)
            session.messages.append({"role": "user", "content": content})

            queue: asyncio.Queue = asyncio.Queue()

            def on_token(chunk: str):
                queue.put_nowait(("token", chunk))

            # Wire auto-respond: bg tasks spawned in _completion_loop inherit these via create_task
            _bg_messages_ctx.set(session.messages)
            _bg_push_ctx.set(session.event_queue)
            _bg_lock_ctx.set(session.lock)

            async def run_loop():
                try:
                    result = await engine._completion_loop(
                        agent, session.messages, depth=0, on_token=on_token,
                    )
                    queue.put_nowait(("done", result))
                except Exception as e:
                    queue.put_nowait(("error", str(e)))

            task = asyncio.create_task(run_loop())

            try:
                while True:
                    event_type, data = await queue.get()
                    if event_type == "token":
                        yield {"event": "token", "data": json.dumps({"t": data})}
                    elif event_type == "done":
                        session.messages.append({"role": "assistant", "content": data})
                        yield {"event": "done", "data": json.dumps({"content": data})}
                        new_task_ids = [tid for tid in engine._bg.active_ids() if tid not in tasks_before]
                        if new_task_ids:
                            new_tasks = []
                            for tid in new_task_ids:
                                meta = engine._bg.get_meta(tid)
                                slug = meta.get("agent", "?")
                                agent_obj = engine.agents.get(slug)
                                name = agent_obj.name if agent_obj else slug
                                new_tasks.append({"task_id": tid, "name": name})
                            yield {"event": "tasks", "data": json.dumps(new_tasks)}
                        break
                    elif event_type == "error":
                        del session.messages[restore_len:]
                        yield {"event": "error", "data": json.dumps({"error": data})}
                        break
            except asyncio.CancelledError:
                task.cancel()
                raise
            finally:
                await task

    headers = {
        "X-Accel-Buffering": "no",
        "Cache-Control": "no-cache",
    }
    return EventSourceResponse(event_generator(), headers=headers)


async def get_messages(request: Request) -> Response:
    sm: SessionManager = request.app.state.sessions
    session_id = request.path_params["session_id"]

    session = sm.get(session_id)
    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    messages = [
        {"role": m["role"], "content": m.get("content", "")}
        for m in session.messages
        if m["role"] in ("user", "assistant")
    ]
    return JSONResponse(messages)


async def session_stream(request: Request) -> Response:
    """Persistent SSE stream for auto-respond events from background task completions."""
    sm: SessionManager = request.app.state.sessions
    session = sm.get(request.path_params["session_id"])
    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    async def event_gen():
        try:
            while True:
                event = await session.event_queue.get()
                yield {"event": event["event"], "data": json.dumps(event["data"])}
        except asyncio.CancelledError:
            pass

    return EventSourceResponse(event_gen(), headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})


async def list_tasks(request: Request) -> Response:
    engine: Engine = request.app.state.engine
    if not engine._bg.has_tasks:
        return JSONResponse([])
    tasks = [
        {"task_id": tid, "agent": meta.get("agent", "?"), "task": meta.get("task", "?")}
        for tid, meta in engine._bg.active_meta().items()
    ]
    return JSONResponse(tasks)


# ── App factory ────────────────────────────────────────────────────────────

def create_app(engine: Engine) -> Starlette:
    routes = [
        Route("/health", health, methods=["GET"]),
        Route("/api/agents", list_agents, methods=["GET"]),
        Route("/api/sessions", create_session, methods=["POST"]),
        Route("/api/sessions", list_sessions, methods=["GET"]),
        Route("/api/sessions/{session_id}", delete_session, methods=["DELETE"]),
        Route("/api/sessions/{session_id}/messages", send_message, methods=["POST"]),
        Route("/api/sessions/{session_id}/messages", get_messages, methods=["GET"]),
        Route("/api/sessions/{session_id}/stream", session_stream, methods=["GET"]),
        Route("/api/tasks", list_tasks, methods=["GET"]),
    ]

    app = Starlette(routes=routes)
    app.add_middleware(APIKeyMiddleware)
    app.state.engine = engine
    app.state.sessions = SessionManager()
    return app
