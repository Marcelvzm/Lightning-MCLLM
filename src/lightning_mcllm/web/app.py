"""FastAPI app: REST + WebSocket + static GUI.

The single user-facing surface. Browser GUI talks to it; the MCP server
(separate Claude-spawned process) also talks to it via HTTP. One uvicorn
instance serves both.

Endpoints:
    GET  /                              static GUI (index.html)
    GET  /api/status                    engine status snapshot
    GET  /api/stage                     full stage summary (fixtures, scenes,
                                        chases, banks, shows)
    GET  /api/shadow                    current 512-byte shadow universe (b64)
    GET  /api/environments              list environments + current
    POST /api/environments/{name}       switch environment
    POST /api/reload                    force reload from disk
    GET  /api/shows                     list shows + their keybindings
    POST /api/show/{name}/play          start a show from the beginning
    POST /api/show/pause                pause active show
    POST /api/show/resume               resume paused show
    POST /api/show/reset                restart active show from beginning
    POST /api/show/stop                 stop and unload the active show
    POST /api/cmd/{op}                  submit engine command (json body = args)
    GET  /api/yaml?path=...             read a YAML file (data/-sandboxed)
    PUT  /api/yaml                      write a YAML file (data/-sandboxed)
    DELETE /api/yaml?path=...           delete a YAML file
    GET  /api/yaml/list?prefix=...      list YAML files
    GET  /api/instruct                  llm_instruct.md
    GET  /api/genre_concepts            list genre concept files
    GET  /api/genre_concept/{name}      one genre concept (markdown)
    WS   /api/ws                        5Hz status push + command intake
"""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from lightning_mcllm.config import Settings
from lightning_mcllm.core.library import list_environments
from lightning_mcllm.engine.reload import HotReloader
from lightning_mcllm.engine.runtime import Engine
from lightning_mcllm.ipc.messages import ENGINE_OPS

log = logging.getLogger(__name__)


def _engine_status_dict(engine: Engine) -> dict[str, Any]:
    return dataclasses.asdict(engine.status())


def _stage_summary(engine: Engine) -> dict[str, Any]:
    stage = engine.stage()
    if stage is None:
        return {"loaded": False}
    return {
        "loaded": True,
        "name": stage.name,
        "fixtures": [
            {
                "name": f.name,
                "profile": f.profile,
                "address": f.address,
                "universe": f.universe,
                "tags": list(f.tags),
                "footprint": (
                    stage.library.get(f.profile).footprint
                    if stage.library.get(f.profile)
                    else 0
                ),
            }
            for f in stage.fixtures
        ],
        "scenes": sorted(stage.scenes.keys()),
        "chases": [
            {
                "name": c.name,
                "loop": c.loop,
                "length_beats": c.length_beats,
                "length_seconds": c.length_seconds,
                "step_count": len(c.steps),
            }
            for c in stage.chases.values()
        ],
        "banks": [
            {
                "name": b.name,
                "slots": [
                    {
                        "id": s.id,
                        "kind": s.kind,
                        "name": getattr(s, "name", None),
                        "label": s.label,
                    }
                    for s in b.slots
                ],
            }
            for b in stage.banks.values()
        ],
        "shows": [
            {
                "name": s.name,
                "description": s.description,
                "bpm": s.bpm,
                "loop": s.loop,
                "keybindings": {
                    k: {
                        "kind": v.kind,
                        "name": v.name,
                        "label": v.label,
                    }
                    for k, v in s.keybindings.items()
                },
                "script_length": len(s.script),
            }
            for s in stage.shows.values()
        ],
    }


def _resolve_data_path(settings: Settings, raw: str) -> Path:
    """Resolve a path inside data/ — refuse traversal outside."""
    base = settings.paths.data_dir.resolve()
    target = (base / raw).resolve()
    try:
        target.relative_to(base)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="path escapes data dir") from e
    return target


def create_app(engine: Engine, reloader: HotReloader, settings: Settings) -> FastAPI:
    static_dir = Path(__file__).parent / "static"
    active_websockets: set[WebSocket] = set()

    async def status_broadcaster() -> None:
        while True:
            await asyncio.sleep(0.2)  # 5Hz
            if not active_websockets:
                continue
            payload = {"type": "status", "data": _engine_status_dict(engine)}
            dead: list[WebSocket] = []
            for w in active_websockets:
                try:
                    await w.send_json(payload)
                except Exception:  # noqa: BLE001
                    dead.append(w)
            for w in dead:
                active_websockets.discard(w)

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
        task = asyncio.create_task(status_broadcaster())
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, BaseException):
                pass

    app = FastAPI(title="LightningMCLLM", version="0.1.0", lifespan=lifespan)

    # --------------------------------------------------------------- static

    @app.get("/", response_class=FileResponse)
    async def index() -> Any:
        return FileResponse(static_dir / "index.html")

    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    # --------------------------------------------------------------- status

    @app.get("/api/status")
    async def get_status() -> Any:
        return _engine_status_dict(engine)

    @app.get("/api/stage")
    async def get_stage() -> Any:
        return _stage_summary(engine)

    @app.get("/api/shadow")
    async def get_shadow() -> Any:
        frame = engine.shadow_snapshot()
        return {"universe": 0, "frame_b64": base64.b64encode(frame).decode()}

    # ---------------------------------------------------------- environments

    @app.get("/api/environments")
    async def get_envs() -> Any:
        return {
            "environments": list_environments(settings.paths.environments),
            "current": reloader.env_name,
        }

    @app.post("/api/environments/{name}")
    async def switch_env(name: str) -> Any:
        stage, issues = reloader.switch_environment(name)
        return {
            "ok": stage is not None,
            "errors": issues.errors,
            "warnings": issues.warnings,
        }

    @app.post("/api/reload")
    async def force_reload() -> Any:
        stage, issues = reloader.reload_now()
        return {
            "ok": stage is not None,
            "errors": issues.errors,
            "warnings": issues.warnings,
        }

    # ----------------------------------------------------------------- shows

    @app.get("/api/shows")
    async def get_shows() -> Any:
        stage = engine.stage()
        if stage is None:
            return {"shows": []}
        return {
            "shows": [
                {
                    "name": s.name,
                    "description": s.description,
                    "bpm": s.bpm,
                    "loop": s.loop,
                    "script_length": len(s.script),
                    "keybindings": {
                        k: {"kind": v.kind, "name": v.name, "label": v.label}
                        for k, v in s.keybindings.items()
                    },
                }
                for s in stage.shows.values()
            ]
        }

    @app.post("/api/show/{name}/play")
    async def play_show(name: str) -> Any:
        stage = engine.stage()
        if stage is None or name not in stage.shows:
            raise HTTPException(404, f"unknown show {name!r}")
        engine.submit("play_show", show=name)
        return {"ok": True, "show": name}

    @app.post("/api/show/pause")
    async def pause_show() -> Any:
        engine.submit("pause_show")
        return {"ok": True}

    @app.post("/api/show/resume")
    async def resume_show() -> Any:
        engine.submit("resume_show")
        return {"ok": True}

    @app.post("/api/show/reset")
    async def reset_show() -> Any:
        engine.submit("reset_show")
        return {"ok": True}

    @app.post("/api/show/stop")
    async def stop_show() -> Any:
        engine.submit("stop_show")
        return {"ok": True}

    # --------------------------------------------------------------- commands

    @app.post("/api/cmd/{op}")
    async def submit_cmd(op: str, request: Request) -> Any:
        if op not in ENGINE_OPS:
            raise HTTPException(status_code=400, detail=f"unknown op {op!r}")
        body = b""
        try:
            body = await request.body()
        except Exception:  # noqa: BLE001
            body = b""
        args: dict[str, Any] = {}
        if body:
            try:
                args = json.loads(body) or {}
            except Exception as e:  # noqa: BLE001
                raise HTTPException(status_code=400, detail=f"bad json: {e}") from e
        if op in (
            "status", "shadow", "list_environments", "switch_environment",
            "list_stage", "reload",
        ):
            raise HTTPException(status_code=400, detail=f"use the dedicated route for {op!r}")
        engine.submit(op, **args)
        return {"ok": True, "submitted": op}

    # ---------------------------------------------------------------- yaml

    @app.get("/api/yaml")
    async def get_yaml(path: str) -> Any:
        target = _resolve_data_path(settings, path)
        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail="not found")
        text = target.read_text(encoding="utf-8")
        return PlainTextResponse(text, media_type="text/yaml")

    @app.put("/api/yaml")
    async def put_yaml(request: Request) -> Any:
        params = request.query_params
        path = params.get("path")
        if not path:
            raise HTTPException(status_code=400, detail="missing ?path=")
        body = await request.body()
        text = body.decode("utf-8")
        target = _resolve_data_path(settings, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(target)
        return {"ok": True, "path": str(target.relative_to(settings.paths.data_dir))}

    @app.delete("/api/yaml")
    async def delete_yaml(path: str) -> Any:
        target = _resolve_data_path(settings, path)
        if target.is_file():
            target.unlink()
            return {"ok": True}
        raise HTTPException(status_code=404, detail="not found")

    @app.get("/api/yaml/list")
    async def list_yaml(prefix: str = "") -> Any:
        base = settings.paths.data_dir
        if prefix:
            base = _resolve_data_path(settings, prefix)
        if not base.exists() or not base.is_dir():
            raise HTTPException(status_code=404, detail="dir not found")
        out: list[str] = []
        for p in sorted(base.rglob("*.yaml")):
            out.append(str(p.relative_to(settings.paths.data_dir)))
        for p in sorted(base.rglob("*.yml")):
            out.append(str(p.relative_to(settings.paths.data_dir)))
        return {"files": out}

    # ---------------------------------------------------------------- instruct

    @app.get("/api/instruct")
    async def get_instruct() -> Any:
        repo_root = settings.paths.data_dir.parent
        candidate = repo_root / "llm_instruct.md"
        if not candidate.is_file():
            raise HTTPException(404, f"llm_instruct.md not found at {candidate}")
        return PlainTextResponse(candidate.read_text(encoding="utf-8"), media_type="text/markdown")

    @app.get("/api/program")
    async def get_program() -> Any:
        """Return program.md — the technical YAML schema reference.

        This is the HOW (syntax / semantics / voice model / parameters /
        palettes / pitfalls) that complements the design principles in
        llm_instruct.md.
        """
        repo_root = settings.paths.data_dir.parent
        candidate = repo_root / "program.md"
        if not candidate.is_file():
            raise HTTPException(404, f"program.md not found at {candidate}")
        return PlainTextResponse(candidate.read_text(encoding="utf-8"), media_type="text/markdown")

    def _genre_concepts_dir() -> Path:
        return settings.paths.data_dir.parent / "genre_concepts"

    @app.get("/api/genre_concepts")
    async def list_genre_concepts() -> Any:
        d = _genre_concepts_dir()
        if not d.is_dir():
            return {"concepts": []}
        names = sorted(p.stem for p in d.glob("*.md") if p.stem.lower() != "readme")
        return {"concepts": names}

    @app.get("/api/genre_concept/{name}")
    async def read_genre_concept(name: str) -> Any:
        safe = Path(name).name
        if not safe or safe.startswith(".") or "/" in name or "\\" in name:
            raise HTTPException(400, "invalid name")
        candidate = _genre_concepts_dir() / f"{safe}.md"
        if not candidate.is_file():
            raise HTTPException(404, f"genre concept {name!r} not found")
        return PlainTextResponse(candidate.read_text(encoding="utf-8"), media_type="text/markdown")

    # ------------------------------------------------------------------- ws

    @app.websocket("/api/ws")
    async def ws(ws_: WebSocket) -> None:
        await ws_.accept()
        active_websockets.add(ws_)
        try:
            await ws_.send_json({"type": "status", "data": _engine_status_dict(engine)})
            await ws_.send_json({"type": "stage", "data": _stage_summary(engine)})
            while True:
                msg = await ws_.receive_text()
                try:
                    payload = json.loads(msg)
                    op = payload.get("op")
                    args = payload.get("args", {})
                    if op in ENGINE_OPS:
                        engine.submit(op, **(args or {}))
                except Exception as e:  # noqa: BLE001
                    await ws_.send_json({"type": "error", "data": str(e)})
        except WebSocketDisconnect:
            pass
        finally:
            active_websockets.discard(ws_)

    return app
