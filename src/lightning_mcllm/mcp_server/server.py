"""MCP server — Claude's authoring interface to a running Lightning instance.

The server itself is a thin HTTP client of the Lightning web API. It runs as a
separate process spawned by Claude Desktop / Claude Code (over stdio). The
running engine + GUI process is whatever the user has open (`lightning run`)
on http://127.0.0.1:7777 by default.

Tools exposed:

    list_environments            return [str], plus current
    list_show                    return fixtures + scenes + chases + banks summary
    list_yaml(prefix?)           return list of YAML files under data/
    read_yaml(path)              return full file contents
    write_yaml(path, content)    write a file (atomic), data/ sandboxed
    delete_yaml(path)            delete a file
    reload                       force engine to re-read data/
    snap_scene(scene, fade?)     trigger a scene
    start_chase(name)            start a chase
    stop_chase(name)             stop a chase by name
    blackout                     blackout
    release_blackout             release blackout
    set_bpm(bpm)                 set BPM
    fire_slot(bank, slot_id)     fire a bank slot
    set_value(addr, value)       direct DMX channel override (debug)
    status                       current engine status
    switch_environment(name)     change environments without restart

If the `mcp` package isn't installed (optional extra), this module prints an
explanatory message and exits non-zero.
"""

from __future__ import annotations

import json
import logging
import sys
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlencode

log = logging.getLogger(__name__)


# --------------------------------------------------------- HTTP helpers (sync)


def _http_get(url: str) -> Any:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=5.0) as r:  # noqa: S310 — local URL
        body = r.read()
        if r.headers.get("content-type", "").startswith("application/json"):
            return json.loads(body)
        return body.decode("utf-8", errors="replace")


def _http_post(url: str, payload: Any = None) -> Any:
    data = None if payload is None else json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"} if data is not None else {}
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=5.0) as r:  # noqa: S310
        body = r.read()
        if r.headers.get("content-type", "").startswith("application/json"):
            return json.loads(body)
        return body.decode("utf-8", errors="replace")


def _http_put(url: str, raw_body: bytes) -> Any:
    req = urllib.request.Request(url, data=raw_body, method="PUT")
    with urllib.request.urlopen(req, timeout=5.0) as r:  # noqa: S310
        body = r.read()
        return json.loads(body) if r.headers.get("content-type", "").startswith("application/json") else body


def _http_delete(url: str) -> Any:
    req = urllib.request.Request(url, method="DELETE")
    with urllib.request.urlopen(req, timeout=5.0) as r:  # noqa: S310
        body = r.read()
        return json.loads(body) if r.headers.get("content-type", "").startswith("application/json") else body


# --------------------------------------------------------- API wrapper class


class LightningClient:
    def __init__(self, base: str):
        self._base = base.rstrip("/")

    def status(self) -> Any:
        return _http_get(f"{self._base}/api/status")

    def show(self) -> Any:
        return _http_get(f"{self._base}/api/show")

    def environments(self) -> Any:
        return _http_get(f"{self._base}/api/environments")

    def switch_environment(self, name: str) -> Any:
        return _http_post(f"{self._base}/api/environments/{name}")

    def reload(self) -> Any:
        return _http_post(f"{self._base}/api/reload")

    def cmd(self, op: str, **args: Any) -> Any:
        return _http_post(f"{self._base}/api/cmd/{op}", args)

    def list_yaml(self, prefix: str = "") -> Any:
        q = "?" + urlencode({"prefix": prefix}) if prefix else ""
        return _http_get(f"{self._base}/api/yaml/list{q}")

    def read_authoring_guide(self) -> str:
        text = _http_get(f"{self._base}/api/instruct")
        return text if isinstance(text, str) else json.dumps(text)

    def read_yaml(self, path: str) -> str:
        text = _http_get(f"{self._base}/api/yaml?{urlencode({'path': path})}")
        if isinstance(text, str):
            return text
        return json.dumps(text)

    def write_yaml(self, path: str, content: str) -> Any:
        return _http_put(f"{self._base}/api/yaml?{urlencode({'path': path})}", content.encode("utf-8"))

    def delete_yaml(self, path: str) -> Any:
        return _http_delete(f"{self._base}/api/yaml?{urlencode({'path': path})}")


# --------------------------------------------------------- MCP server entry


def run_stdio(api_url: str) -> None:
    """Run the MCP server over stdio. Imported lazily so the optional `mcp`
    package isn't pulled in just to import this module."""
    try:
        from mcp.server import Server  # type: ignore[import-untyped]
        from mcp.server.stdio import stdio_server  # type: ignore[import-untyped]
        from mcp.types import TextContent, Tool  # type: ignore[import-untyped]
    except ImportError:
        sys.stderr.write(
            "The `mcp` package is not installed.\n"
            "Install with: pip install 'lightning-mcllm[mcp]'\n"
        )
        sys.exit(2)

    import anyio

    client = LightningClient(api_url)
    srv = Server("lightning-mcllm")

    # ---------------------------------------------------------- tool registry
    @srv.list_tools()
    async def list_tools() -> list[Any]:
        return [
            Tool(
                name="read_authoring_guide",
                description=(
                    "Return llm_instruct.md — the authoring guide for writing professional "
                    "lightshows with this system. **Call this FIRST before authoring any scene, "
                    "chase, bank, or genre.** It contains the deterministic principles, genre "
                    "playbook, workflow, YAML cookbook, and anti-patterns. Skipping this step is "
                    "the #1 reason LLM-authored shows fail."
                ),
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="status",
                description="Get current engine status (BPM, beat, voices, errors, DMX connection, etc).",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="list_show",
                description="Return the loaded show: fixtures, scenes, chases, banks. Use to learn what's available before editing.",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="list_environments",
                description="List available environments under data/environments/.",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="switch_environment",
                description="Switch to a different environment (atomic; reuses the running engine).",
                inputSchema={
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            ),
            Tool(
                name="list_yaml",
                description="List all YAML files under data/, optionally under a path prefix (e.g. 'environments/default/scenes').",
                inputSchema={
                    "type": "object",
                    "properties": {"prefix": {"type": "string"}},
                },
            ),
            Tool(
                name="read_yaml",
                description="Read a YAML file under data/. Path is relative to data/.",
                inputSchema={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            ),
            Tool(
                name="write_yaml",
                description="Write (or overwrite) a YAML file under data/. Engine auto-reloads via file watcher.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path relative to data/"},
                        "content": {"type": "string", "description": "Full file content"},
                    },
                    "required": ["path", "content"],
                },
            ),
            Tool(
                name="delete_yaml",
                description="Delete a YAML file under data/.",
                inputSchema={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            ),
            Tool(
                name="reload",
                description="Force the engine to re-read data/ files. Use after multi-file edits to apply atomically.",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="snap_scene",
                description="Trigger a scene. fade in seconds (0 = instant).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "scene": {"type": "string"},
                        "fade": {"type": "number", "default": 0.0},
                    },
                    "required": ["scene"],
                },
            ),
            Tool(
                name="start_chase",
                description="Start a chase by name (running chase with same name is replaced).",
                inputSchema={
                    "type": "object",
                    "properties": {"chase": {"type": "string"}},
                    "required": ["chase"],
                },
            ),
            Tool(
                name="stop_chase",
                description="Stop a chase by name.",
                inputSchema={
                    "type": "object",
                    "properties": {"chase": {"type": "string"}},
                    "required": ["chase"],
                },
            ),
            Tool(
                name="stop_all_chases",
                description="Stop every running chase.",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="blackout",
                description="Blackout (zero all channels until release_blackout or another voice writes).",
                inputSchema={
                    "type": "object",
                    "properties": {"fade": {"type": "number", "default": 0.0}},
                },
            ),
            Tool(
                name="release_blackout",
                description="Lift blackout — voices underneath show through again.",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="set_bpm",
                description="Set BPM manually.",
                inputSchema={
                    "type": "object",
                    "properties": {"bpm": {"type": "number"}, "source": {"type": "string"}},
                    "required": ["bpm"],
                },
            ),
            Tool(
                name="fire_slot",
                description="Fire a bank slot by id.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "bank": {"type": "string"},
                        "slot_id": {"type": "integer"},
                    },
                    "required": ["bank", "slot_id"],
                },
            ),
            Tool(
                name="set_value",
                description="Direct DMX channel override (debug). Channel address is 1..512.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "address": {"type": "integer"},
                        "value": {"type": "integer"},
                        "universe": {"type": "integer", "default": 0},
                    },
                    "required": ["address", "value"],
                },
            ),
        ]

    # ---------------------------------------------------------- tool dispatch
    @srv.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[Any]:
        try:
            if name == "read_authoring_guide":
                out = client.read_authoring_guide()
            elif name == "status":
                out = client.status()
            elif name == "list_show":
                out = client.show()
            elif name == "list_environments":
                out = client.environments()
            elif name == "switch_environment":
                out = client.switch_environment(arguments["name"])
            elif name == "list_yaml":
                out = client.list_yaml(arguments.get("prefix", ""))
            elif name == "read_yaml":
                out = client.read_yaml(arguments["path"])
            elif name == "write_yaml":
                out = client.write_yaml(arguments["path"], arguments["content"])
            elif name == "delete_yaml":
                out = client.delete_yaml(arguments["path"])
            elif name == "reload":
                out = client.reload()
            elif name in {
                "snap_scene", "start_chase", "stop_chase", "stop_all_chases",
                "blackout", "release_blackout", "set_bpm", "fire_slot",
                "set_value", "tap", "set_master",
            }:
                out = client.cmd(name, **arguments)
            else:
                return [TextContent(type="text", text=f"unknown tool: {name}")]
        except urllib.error.URLError as e:
            return [TextContent(
                type="text",
                text=f"Could not reach Lightning at {api_url}: {e}\n"
                f"Make sure `lightning run` is running.",
            )]
        except Exception as e:  # noqa: BLE001
            return [TextContent(type="text", text=f"error: {e}")]
        if isinstance(out, str):
            return [TextContent(type="text", text=out)]
        return [TextContent(type="text", text=json.dumps(out, indent=2))]

    async def _serve() -> None:
        async with stdio_server() as (read, write):
            await srv.run(read, write, srv.create_initialization_options())

    anyio.run(_serve)
