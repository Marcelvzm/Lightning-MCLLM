"""asyncio TCP server bridging external IPC clients (web, MCP) to the Engine.

Protocol: line-delimited JSON. One Envelope per line, one Reply per line.
The server exposes the Engine command surface plus a few read-only ops:
`status`, `shadow`, `list_environments`, `list_show`, `switch_environment`,
`reload`.
"""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import json
import logging
from pathlib import Path
from typing import Any

from lightning_mcllm.config import Settings
from lightning_mcllm.core.library import list_environments
from lightning_mcllm.engine.reload import HotReloader
from lightning_mcllm.engine.runtime import Engine
from lightning_mcllm.ipc.messages import ENGINE_OPS, Envelope, Reply

log = logging.getLogger(__name__)


def _engine_status_to_dict(engine: Engine) -> dict[str, Any]:
    return dataclasses.asdict(engine.status())


def _show_summary(engine: Engine) -> dict[str, Any]:
    show = engine.show()
    if show is None:
        return {"loaded": False}
    return {
        "loaded": True,
        "name": show.name,
        "fixtures": [
            {
                "name": f.name,
                "profile": f.profile,
                "address": f.address,
                "universe": f.universe,
                "tags": list(f.tags),
                "footprint": (show.library.get(f.profile).footprint if show.library.get(f.profile) else 0),
            }
            for f in show.fixtures
        ],
        "scenes": sorted(show.scenes.keys()),
        "chases": [
            {
                "name": c.name,
                "loop": c.loop,
                "length_beats": c.length_beats,
                "length_seconds": c.length_seconds,
                "step_count": len(c.steps),
            }
            for c in show.chases.values()
        ],
        "banks": [
            {
                "name": b.name,
                "slots": [
                    {"id": s.id, "kind": s.kind, "name": getattr(s, "name", None), "label": s.label}
                    for s in b.slots
                ],
            }
            for b in show.banks.values()
        ],
    }


class IpcServer:
    def __init__(
        self,
        engine: Engine,
        reloader: HotReloader,
        settings: Settings,
        host: str = "127.0.0.1",
        port: int = 7772,
    ):
        self._engine = engine
        self._reloader = reloader
        self._settings = settings
        self._host = host
        self._port = port
        self._server: asyncio.AbstractServer | None = None
        self._clients: set[asyncio.StreamWriter] = set()

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, self._host, self._port)
        log.info("IPC server listening on %s:%d", self._host, self._port)

    async def serve_forever(self) -> None:
        if self._server is None:
            raise RuntimeError("call start() first")
        async with self._server:
            await self._server.serve_forever()

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
        for w in list(self._clients):
            try:
                w.close()
            except Exception:  # noqa: BLE001
                pass

    # ----------------------------------------------------------- broadcast

    async def broadcast(self, op: str, data: Any) -> None:
        line = (json.dumps({"op": op, "data": data}) + "\n").encode()
        dead: list[asyncio.StreamWriter] = []
        for w in self._clients:
            try:
                w.write(line)
                await w.drain()
            except Exception:  # noqa: BLE001
                dead.append(w)
        for w in dead:
            self._clients.discard(w)

    # ------------------------------------------------------------ handler

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        log.debug("ipc client connected: %s", peer)
        self._clients.add(writer)
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    payload = json.loads(line.decode())
                    env = Envelope.model_validate(payload)
                except Exception as e:  # noqa: BLE001
                    err = Reply(id=0, ok=False, error=f"bad envelope: {e}").model_dump()
                    writer.write((json.dumps(err) + "\n").encode())
                    await writer.drain()
                    continue
                reply = await self._dispatch(env)
                writer.write((json.dumps(reply.model_dump()) + "\n").encode())
                await writer.drain()
        except (ConnectionResetError, asyncio.IncompleteReadError):
            pass
        finally:
            self._clients.discard(writer)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass

    # ----------------------------------------------------------- dispatch

    async def _dispatch(self, env: Envelope) -> Reply:
        op = env.op
        try:
            if op == "status":
                return Reply(id=env.id, ok=True, data=_engine_status_to_dict(self._engine))
            if op == "shadow":
                return Reply(
                    id=env.id, ok=True,
                    data={"universe": 0, "frame_b64": base64.b64encode(self._engine.shadow_snapshot()).decode()},
                )
            if op == "list_environments":
                return Reply(id=env.id, ok=True,
                             data={"environments": list_environments(self._settings.paths.environments),
                                   "current": self._reloader.env_name})
            if op == "switch_environment":
                show, issues = self._reloader.switch_environment(env.args["name"])
                return Reply(
                    id=env.id, ok=show is not None,
                    data={"errors": issues.errors, "warnings": issues.warnings,
                          "show": _show_summary(self._engine) if show else None},
                    error=None if show else "; ".join(issues.errors[:3]),
                )
            if op == "list_show":
                return Reply(id=env.id, ok=True, data=_show_summary(self._engine))
            if op == "reload":
                show, issues = self._reloader.reload_now()
                return Reply(
                    id=env.id, ok=show is not None,
                    data={"errors": issues.errors, "warnings": issues.warnings},
                    error=None if show else "; ".join(issues.errors[:3]),
                )
            if op in ENGINE_OPS:
                self._engine.submit(op, **env.args)
                return Reply(id=env.id, ok=True, data={"submitted": True})
            return Reply(id=env.id, ok=False, error=f"unknown op {op!r}")
        except Exception as e:  # noqa: BLE001
            log.exception("ipc dispatch %s failed", op)
            return Reply(id=env.id, ok=False, error=str(e))


async def status_broadcaster(server: IpcServer, engine: Engine, *, hz: float = 5.0) -> None:
    """Push periodic status snapshots to all connected IPC clients."""
    period = 1.0 / max(0.5, hz)
    try:
        while True:
            await asyncio.sleep(period)
            await server.broadcast("status_update", _engine_status_to_dict(engine))
    except asyncio.CancelledError:
        pass
