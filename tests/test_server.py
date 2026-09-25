import asyncio
import json
from pathlib import Path

import pytest

pytest.importorskip("aiohttp")

from aiohttp.test_utils import TestClient, TestServer

from whip import realtime, server


def run(coro):
    return asyncio.run(coro)


def with_client(test):
    """Spin the real app up around a fresh manager, no hardware anywhere."""
    async def inner(tmp_path):
        manager = server.RingManager(checkpoint=tmp_path / "absent.pt")
        app = server.build_app(manager)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            await test(client, manager, tmp_path)
        finally:
            await client.close()
    return inner


def test_status_reports_idle_and_no_device(tmp_path):
    @with_client
    async def check(client, manager, _tmp):
        res = await client.get("/api/status")
        body = await res.json()
        assert res.status == 200
        assert body["state"] == "idle"
        assert body["device"] is None
        assert body["mode"] == "unknown"
    run(check(tmp_path))


def test_missing_model_is_reported_not_crashed(tmp_path):
    @with_client
    async def check(client, manager, _tmp):
        res = await client.get("/api/model")
        body = await res.json()
        assert body["available"] is False
        assert "no checkpoint" in body["reason"]
    run(check(tmp_path))


def test_flash_targets_are_the_two_pinned_images(tmp_path):
    @with_client
    async def check(client, manager, _tmp):
        res = await client.get("/api/flash/targets")
        body = await res.json()
        assert set(body) == {"gesture", "stock"}
        assert body["gesture"]["image"] == "rt02cr-25hz-optical-off-v2-experimental.bin"
        assert body["stock"]["image"] == "rt02cr-stock-3.12.02.bin"
    run(check(tmp_path))


def test_flash_refuses_without_a_connection(tmp_path):
    """State machine first: no ring, no flash, whatever the request says."""
    @with_client
    async def check(client, manager, _tmp):
        res = await client.post("/api/flash",
                                json={"target": "gesture", "confirm": "FLASH"})
        assert res.status == 409
        assert "connected" in await res.text()
    run(check(tmp_path))


def test_flash_refuses_the_wrong_confirmation_word(tmp_path):
    @with_client
    async def check(client, manager, _tmp):
        res = await client.post("/api/flash",
                                json={"target": "gesture", "confirm": "yes"})
        assert res.status == 400
    run(check(tmp_path))


def test_flash_requires_a_passed_dry_run_first(tmp_path):
    """
    The UI's validate step is not decoration: the server itself refuses a
    flash for a target whose dry run has not passed in this connection.
    """
    @with_client
    async def check(client, manager, _tmp):
        manager.state = "connected"      # simulate a live connection
        res = await client.post("/api/flash",
                                json={"target": "gesture", "confirm": "FLASH"})
        assert res.status == 412
        assert "dry-run" in await res.text()
    run(check(tmp_path))


def test_validate_runs_disconnected_but_does_not_arm(tmp_path):
    """Preflight and dry run need no radio; arming the button needs a ring."""
    @with_client
    async def check(client, manager, _tmp):
        res = await client.post("/api/flash/validate", json={"target": "gesture"})
        body = await res.json()
        assert res.status == 200
        assert body["ok"] is True
        assert body["chunks"] > 0
        assert body["armed"] is False
        assert "connect" in body["note"]
    run(check(tmp_path))


def test_validate_rejects_an_unknown_target(tmp_path):
    @with_client
    async def check(client, manager, _tmp):
        res = await client.post("/api/flash/validate", json={"target": "yolo"})
        assert res.status == 400
    run(check(tmp_path))


def test_streaming_refuses_without_a_connection(tmp_path):
    @with_client
    async def check(client, manager, _tmp):
        res = await client.post("/api/stream/start")
        assert res.status == 409
    run(check(tmp_path))


def test_streaming_refuses_without_a_model(tmp_path):
    @with_client
    async def check(client, manager, _tmp):
        manager.state = "connected"
        res = await client.post("/api/stream/start")
        assert res.status == 424
        assert "checkpoint" in await res.text()
    run(check(tmp_path))


def test_config_round_trips_through_the_api(tmp_path, monkeypatch):
    @with_client
    async def check(client, manager, tmp):
        config_path = tmp / "app_config.json"
        monkeypatch.setattr(realtime, "DEFAULT_CONFIG_PATH", config_path)
        monkeypatch.setattr(server, "DEFAULT_CONFIG_PATH", config_path)
        res = await client.put("/api/config", json={
            "mappings": {"flick": "flag", "wave:up": "approve"}, "threshold": 0.7})
        assert res.status == 200
        saved = json.loads(config_path.read_text())
        assert saved["mappings"]["wave:up"] == "approve"
        assert saved["threshold"] == 0.7
    run(check(tmp_path))


def test_websocket_greets_with_current_state(tmp_path):
    @with_client
    async def check(client, manager, _tmp):
        ws = await client.ws_connect("/ws")
        msg = await ws.receive_json()
        assert msg["type"] == "state"
        assert msg["state"] == "idle"
        await ws.close()
    run(check(tmp_path))


def test_the_frontend_is_served(tmp_path):
    @with_client
    async def check(client, manager, _tmp):
        res = await client.get("/")
        text = await res.text()
        assert res.status == 200
        assert "Whip" in text and "ring console" in text
        for asset in ("/static/app.js", "/static/style.css"):
            got = await client.get(asset)
            assert got.status == 200
    run(check(tmp_path))


def test_recalibrate_needs_a_tracking_session(tmp_path):
    @with_client
    async def check(client, manager, _tmp):
        res = await client.post("/api/calibrate")
        assert res.status == 409
        body = await (await client.get("/api/status")).json()
        assert body["calibrated"] is False and body["calibration"] is None
    run(check(tmp_path))


def test_recalibrate_holds_events_until_a_fresh_pose(tmp_path):
    @with_client
    async def check(client, manager, _tmp):
        manager.state = "streaming"
        manager._calibrator = realtime.PoseCalibrator()
        manager._calibrator.feed(0.0, (0, 8005, 0))
        manager.calibrated = True
        manager.calibration = {"frame": "identity", "wearing": "canonical"}
        res = await client.post("/api/calibrate")
        body = await res.json()
        assert res.status == 200 and body["calibrated"] is False and body["calibration"] is None
        assert manager._calibrator._buf == [] and not manager._calibrator.done
    run(check(tmp_path))
