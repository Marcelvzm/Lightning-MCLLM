"""FastAPI app: REST + WebSocket + static GUI.

This is the single user-facing surface. The browser GUI talks to it; the MCP
server (run separately by Claude Desktop / Claude Code) also talks to it via
HTTP from another process. One uvicorn instance handles both.

Endpoints:
    GET  /                       static GUI (index.html)
    GET  /api/status             engine status snapshot
    GET  /api/show               full show summary (fixtures, scenes, chases, banks)
    GET  /api/shadow             current 512-byte shadow universe (b64)
    GET  /api/environments       list environments + current
    POST /api/environments/{name}   switch environment
    POST /api/reload             force reload from disk
    POST /api/cmd/{op}           submit engine command (json body = args)
    GET  /api/yaml?path=...      read a YAML file from data/ (sandboxed)
    PUT  /api/yaml               write a YAML file (sandboxed)
    GET  /api/instruct           return llm_instruct.md (authoring guide for LLMs)
    GET  /api/genres             list genre presets
    POST /api/genres/{name}      apply a genre (BPM + start lead chase)
    WS   /api/ws                 5Hz status updates pushed to clients
"""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import json
import logging
from pathlib import Path
from typing import Any

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from lightning_mcllm.config import Settings
from lightning_mcllm.core.library import list_environments
from lightning_mcllm.engine.reload import HotReloader
from lightning_mcllm.engine.runtime import Engine
from lightning_mcllm.ipc.messages import ENGINE_OPS

log = logging.getLogger(__name__)


def _engine_status_dict(engine: Engine) -> dict[str, Any]:
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
                "footprint": (
                    show.library.get(f.profile).footprint
                    if show.library.get(f.profile)
                    else 0
                ),
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
                    {
                        "id": s.id,
                        "kind": s.kind,
                        "name": getattr(s, "name", None),
                        "label": s.label,
                    }
                    for s in b.slots
                ],
            }
            for b in show.banks.values()
        ],
        "genres": [
            {"name": g.name, "bpm": g.bpm, "lead_chase": g.lead_chase}
            for g in show.genres.values()
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

    @app.get("/api/show")
    async def get_show() -> Any:
        return _show_summary(engine)

    @app.get("/api/instruct")
    async def get_instruct() -> Any:
        """Return llm_instruct.md if present in the repo root.

        This is the authoring guide that an LLM should read before writing
        any scene/chase/bank YAML. The MCP server forwards this verbatim.
        """
        # Resolve repo root: data_dir's parent (since data_dir = <repo>/data).
        repo_root = settings.paths.data_dir.parent
        candidate = repo_root / "llm_instruct.md"
        if not candidate.is_file():
            raise HTTPException(404, f"llm_instruct.md not found at {candidate}")
        return PlainTextResponse(candidate.read_text(encoding="utf-8"), media_type="text/markdown")

    def _genre_concepts_dir() -> Path:
        return settings.paths.data_dir.parent / "genre_concepts"

    @app.get("/api/genre_concepts")
    async def list_genre_concepts() -> Any:
        """List available genre concept files (one .md per genre)."""
        d = _genre_concepts_dir()
        if not d.is_dir():
            return {"concepts": []}
        names = sorted(p.stem for p in d.glob("*.md") if p.stem.lower() != "readme")
        return {"concepts": names}

    @app.get("/api/genre_concept/{name}")
    async def read_genre_concept(name: str) -> Any:
        """Return one genre concept file (markdown). Sandboxed to genre_concepts/."""
        # Sanitize: only filename, no path traversal
        safe = Path(name).name
        if not safe or safe.startswith(".") or "/" in name or "\\" in name:
            raise HTTPException(400, "invalid name")
        candidate = _genre_concepts_dir() / f"{safe}.md"
        if not candidate.is_file():
            raise HTTPException(404, f"genre concept {name!r} not found")
        return PlainTextResponse(candidate.read_text(encoding="utf-8"), media_type="text/markdown")

    @app.get("/api/genres")
    async def get_genres() -> Any:
        show = engine.show()
        if show is None:
            return {"genres": []}
        return {
            "genres": [
                {
                    "name": g.name,
                    "description": g.description,
                    "bpm": g.bpm,
                    "lead_chase": g.lead_chase,
                    "recommended_chases": list(g.recommended_chases),
                    "recommended_scenes": list(g.recommended_scenes),
                }
                for g in show.genres.values()
            ]
        }

    @app.post("/api/genres/{name}")
    async def apply_genre(name: str) -> Any:
        show = engine.show()
        if show is None:
            raise HTTPException(404, "no show loaded")
        g = show.genres.get(name)
        if g is None:
            raise HTTPException(404, f"unknown genre {name!r}")
        engine.submit("set_bpm", bpm=g.bpm, source="manual")
        if g.lead_chase and g.lead_chase in show.chases:
            engine.submit("stop_all_chases")
            engine.submit("start_chase", chase=g.lead_chase)
        return {"ok": True, "applied": name, "bpm": g.bpm, "lead_chase": g.lead_chase}

    @app.get("/api/shadow")
    async def get_shadow() -> Any:
        frame = engine.shadow_snapshot()
        return {"universe": 0, "frame_b64": base64.b64encode(frame).decode()}

    # ----------------------------------------------------------- environments

    @app.get("/api/environments")
    async def get_envs() -> Any:
        return {
            "environments": list_environments(settings.paths.environments),
            "current": reloader.env_name,
        }

    @app.post("/api/environments/{name}")
    async def switch_env(name: str) -> Any:
        show, issues = reloader.switch_environment(name)
        return {
            "ok": show is not None,
            "errors": issues.errors,
            "warnings": issues.warnings,
        }

    @app.post("/api/reload")
    async def force_reload() -> Any:
        show, issues = reloader.reload_now()
        return {
            "ok": show is not None,
            "errors": issues.errors,
            "warnings": issues.warnings,
        }

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
        # Only Engine ops handled here; reload/list_show/etc have dedicated routes
        if op in ("status", "shadow", "list_environments", "switch_environment", "list_show", "reload"):
            raise HTTPException(status_code=400, detail=f"use the dedicated route for {op!r}")
        engine.submit(op, **args)
        return {"ok": True, "submitted": op}

    # ----------------------------------------------------------------- yaml

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
        # Atomic write
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

    # ------------------------------------------------------------------- ws

    @app.websocket("/api/ws")
    async def ws(ws_: WebSocket) -> None:
        await ws_.accept()
        active_websockets.add(ws_)
        try:
            # Push initial snapshot
            await ws_.send_json({"type": "status", "data": _engine_status_dict(engine)})
            await ws_.send_json({"type": "show", "data": _show_summary(engine)})
            while True:
                msg = await ws_.receive_text()
                # Allow client-initiated commands via WS (low-latency)
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
