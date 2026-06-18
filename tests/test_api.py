"""API integration tests for the FastAPI web server.

These tests use httpx (sync client via TestClient) and run entirely
in-process – no Docker required.

Run with:
    pytest tests/test_api.py -v
"""
from __future__ import annotations

from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from app.register_map import load_registers
from app.register_store import RegisterStore
from app.web import create_app

_CONFIG = Path(__file__).parent.parent / "config" / "registers.csv"


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    definitions = load_registers(_CONFIG)
    store = RegisterStore()
    store.initialize(definitions)
    app = create_app(store, definitions)
    with TestClient(app) as c:
        yield c


# ─────────────────────────────────────────────────────────────────────────────
# Health
# ─────────────────────────────────────────────────────────────────────────────

def test_health(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "register_count" in body


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/registers
# ─────────────────────────────────────────────────────────────────────────────

def test_get_all_registers(client: TestClient) -> None:
    resp = client.get("/api/registers")
    assert resp.status_code == 200
    registers = resp.json()
    assert isinstance(registers, list)
    assert len(registers) > 0
    # Each entry must have required keys
    for reg in registers:
        assert "definition" in reg
        assert "raw_value" in reg
        assert "engineering_value" in reg


def test_get_single_register(client: TestClient) -> None:
    resp = client.get("/api/registers/11040")
    assert resp.status_code == 200
    body = resp.json()
    assert body["definition"]["address"] == 11040
    assert body["definition"]["name"] == "ActivePower_SetPoint_P_ON_OFF"


def test_get_nonexistent_register(client: TestClient) -> None:
    resp = client.get("/api/registers/99999")
    assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/registers/{address}
# ─────────────────────────────────────────────────────────────────────────────

def test_write_onoff_register(client: TestClient) -> None:
    resp = client.post(
        "/api/registers/11040", json={"value": 1, "source": "api"}
    )
    assert resp.status_code == 200
    # Verify readback
    resp2 = client.get("/api/registers/11040")
    assert resp2.json()["engineering_value"] == pytest.approx(1.0)


def test_write_setpoint_kw(client: TestClient) -> None:
    resp = client.post(
        "/api/registers/11042", json={"value": 500, "source": "api"}
    )
    assert resp.status_code == 200
    resp2 = client.get("/api/registers/11042")
    assert resp2.json()["engineering_value"] == pytest.approx(500.0)


def test_write_cosphi_factor(client: TestClient) -> None:
    """Engineering value 0.95 with factor 0.001 (stored × 1000) → raw 950."""
    resp = client.post(
        "/api/registers/11032", json={"value": 0.95, "source": "api"}
    )
    assert resp.status_code == 200
    resp2 = client.get("/api/registers/11032")
    body = resp2.json()
    assert body["raw_value"] == 950
    assert body["engineering_value"] == pytest.approx(0.95, rel=1e-3)


def test_write_int32_register(client: TestClient) -> None:
    """Write an int32 measurement register via engineering value."""
    resp = client.post(
        "/api/registers/10050", json={"value": 500, "source": "api"}
    )
    assert resp.status_code == 200
    resp2 = client.get("/api/registers/10050")
    body = resp2.json()
    assert body["engineering_value"] == pytest.approx(500.0)
    assert isinstance(body["raw_value"], list), "int32 raw_value must be [high, low]"
    assert len(body["raw_value"]) == 2


def test_write_negative_int32(client: TestClient) -> None:
    resp = client.post(
        "/api/registers/10052", json={"value": -200, "source": "api"}
    )
    assert resp.status_code == 200
    resp2 = client.get("/api/registers/10062")
    assert resp2.json()["engineering_value"] == pytest.approx(-200.0)


def test_write_out_of_range_uint16(client: TestClient) -> None:
    """Writing a uint16 value > 65535 must return 422."""
    resp = client.post(
        "/api/registers/11042", json={"value": 100_000, "source": "api"}
    )
    assert resp.status_code == 422


def test_write_nonexistent_register(client: TestClient) -> None:
    resp = client.post(
        "/api/registers/99999", json={"value": 1, "source": "api"}
    )
    assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/registers/bulk
# ─────────────────────────────────────────────────────────────────────────────

def test_bulk_write(client: TestClient) -> None:
    payload = {
        "source": "api",
        "values": {
            "11040": 1,
            "11042": 500,
            "11010": 1,
            "11012": 250,
        },
    }
    resp = client.post("/api/registers/bulk", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["written"]) == 4
    assert not body["errors"]

    # Verify all written values
    for addr_str, expected in payload["values"].items():
        r = client.get(f"/api/registers/{addr_str}")
        assert r.json()["engineering_value"] == pytest.approx(float(expected))


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/history
# ─────────────────────────────────────────────────────────────────────────────

def test_history_records_changes(client: TestClient) -> None:
    # Write a register so there is at least one history entry
    client.post("/api/registers/11040", json={"value": 0, "source": "api"})
    resp = client.get("/api/history")
    assert resp.status_code == 200
    history = resp.json()
    assert isinstance(history, list)
    assert len(history) >= 1
    entry = history[-1]
    assert "timestamp" in entry
    assert "address" in entry
    assert "source" in entry


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/reset
# ─────────────────────────────────────────────────────────────────────────────

def test_reset(client: TestClient) -> None:
    # Set a register, then reset, then verify it is back to 0
    client.post("/api/registers/11042", json={"value": 999, "source": "api"})
    resp = client.post("/api/reset")
    assert resp.status_code == 200
    resp2 = client.get("/api/registers/11042")
    assert resp2.json()["engineering_value"] == pytest.approx(0.0)


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/simulate/ems
# ─────────────────────────────────────────────────────────────────────────────

def test_ems_simulation(client: TestClient) -> None:
    payload = {
        "active_power_kw": 500,
        "reactive_power_kvar": 200,
        "voltage_v": 400,
        "current_a": 100,
        "frequency_hz": 50.0,
        "soc_percent": 80,
    }
    resp = client.post("/api/simulate/ems", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"

    # Verify active power written
    r = client.get("/api/registers/10050")
    assert r.json()["engineering_value"] == pytest.approx(500.0)

    # Verify SoC written
    r = client.get("/api/registers/10073")
    assert r.json()["engineering_value"] == pytest.approx(80.0)

    # Verify frequency (factor 0.01)
    r = client.get("/api/registers/10010")
    assert r.json()["engineering_value"] == pytest.approx(50.0, rel=1e-2)


# ─────────────────────────────────────────────────────────────────────────────
# Root / UI
# ─────────────────────────────────────────────────────────────────────────────

def test_root_returns_html(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Modbus IEC104" in resp.text
