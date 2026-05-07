"""Web API integration via TestClient.

Spins the FastAPI app over a real engine + null DMX, hits each endpoint and
verifies responses + side-effects.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from lightning_mcllm.engine.clock import BpmClock
from lightning_mcllm.engine.reload import HotReloader
from lightning_mcllm.engine.runtime import Engine
from lightning_mcllm.web.app import create_app


@pytest.fixture()
def web(stage, null_dmx, settings):
    clock = BpmClock(bpm=120.0)
    eng = Engine(stage=stage, dmx=null_dmx, clock=clock, refresh_hz=60)
    eng.start()
    rel = HotReloader(eng, settings, "default", auto_resume=False)
    app = create_app(eng, rel, settings)
    client = TestClient(app)
    yield client, eng, rel
    eng.stop()


def test_status_endpoint(web):
    client, _, _ = web
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert body["running"] is True
    assert body["stage_name"] == "default"


def test_stage_endpoint(web):
    client, _, _ = web
    r = client.get("/api/stage")
    body = r.json()
    assert body["loaded"] is True
    assert body["name"] == "default"
    assert {f["name"] for f in body["fixtures"]} == {"par-l", "par-r", "mh-l", "mh-r"}
    assert "warm_idle" in body["scenes"]
    assert any(c["name"] == "red_pulse" for c in body["chases"])


def test_environments_listing(web):
    client, _, _ = web
    r = client.get("/api/environments")
    body = r.json()
    assert body["current"] == "default"
    assert "default" in body["environments"]


def test_cmd_snap_then_status(web):
    client, eng, _ = web
    r = client.post("/api/cmd/snap_scene", json={"scene": "warm_idle"})
    assert r.status_code == 200 and r.json()["ok"]
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        if eng.shadow_snapshot()[0] == 140:
            break
        time.sleep(0.02)
    assert eng.shadow_snapshot()[0] == 140


def test_unknown_op_rejected(web):
    client, _, _ = web
    r = client.post("/api/cmd/not_a_real_op", json={})
    assert r.status_code == 400


def test_yaml_read_write_roundtrip(web, settings):
    client, _, _ = web
    # Write
    new_path = "environments/default/scenes/api_test.yaml"
    body = "name: api_test\ntargets:\n  - select: { tag: par }\n    values: { dimmer: 88 }\n"
    r = client.put(f"/api/yaml?path={new_path}", content=body)
    assert r.status_code == 200, r.text
    # Read
    r = client.get(f"/api/yaml?path={new_path}")
    assert r.status_code == 200
    assert r.text.strip() == body.strip()
    # List
    r = client.get("/api/yaml/list?prefix=environments/default/scenes")
    assert "environments/default/scenes/api_test.yaml" in r.json()["files"]
    # Delete
    r = client.delete(f"/api/yaml?path={new_path}")
    assert r.status_code == 200


def test_yaml_path_traversal_rejected(web):
    client, _, _ = web
    r = client.get("/api/yaml?path=../../etc/passwd")
    assert r.status_code == 400


def test_reload_endpoint_after_yaml_write(web, settings):
    client, eng, _ = web
    new_path = "environments/default/scenes/reload_test.yaml"
    body = "name: reload_test\ntargets:\n  - select: { tag: par }\n    values: { dimmer: 99 }\n"
    client.put(f"/api/yaml?path={new_path}", content=body)
    r = client.post("/api/reload")
    assert r.status_code == 200
    assert r.json()["ok"]
    # New scene now usable
    r = client.post("/api/cmd/snap_scene", json={"scene": "reload_test"})
    assert r.json()["ok"]
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        if eng.shadow_snapshot()[0] == 99:
            break
        time.sleep(0.02)
    assert eng.shadow_snapshot()[0] == 99


def test_websocket_initial_handshake_and_command(web):
    """The WS sends two initial messages (status + stage) on connect, then
    accepts commands. The continuous broadcaster runs in production but isn't
    asserted here — TestClient's asyncio task scheduling is finicky."""
    client, eng, _ = web
    with client.websocket_connect("/api/ws") as ws:
        first = ws.receive_json()
        second = ws.receive_json()
        kinds = {first["type"], second["type"]}
        assert "status" in kinds and "stage" in kinds
        # Send a command via WS — engine should see it
        ws.send_json({"op": "snap_scene", "args": {"scene": "warm_idle"}})
    # After the WS context closes, verify the snap landed
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        if eng.shadow_snapshot()[0] == 140:
            return
        time.sleep(0.02)
    assert eng.shadow_snapshot()[0] == 140
