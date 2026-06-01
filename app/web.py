"""FastAPI web application – REST API and static UI serving."""
from __future__ import annotations

import math
import os
from pathlib import Path
from typing import List

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.register_map import load_registers
from app.register_store import RegisterStore
from app.schemas import (
    BulkWriteRequest,
    ChangeRecord,
    EMSSimRequest,
    RegisterDefinition,
    RegisterValueResponse,
    WriteRequest,
)

_STATIC_DIR = Path(__file__).parent / "static"
_CONFIG_PATH = Path(__file__).parent.parent / "config" / "registers.yaml"

_ENFORCE_AC = os.getenv("ENFORCE_ACCESS_CONTROL", "false").lower() == "true"


def create_app(store: RegisterStore, definitions: List[RegisterDefinition]) -> FastAPI:
    app = FastAPI(title="Modbus IEC104 Mock Interface", version="1.0.0")

    # ── Static files ──────────────────────────────────────────────────────────
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # ── Health ────────────────────────────────────────────────────────────────

    @app.get("/api/health")
    def health() -> dict:
        return {
            "status": "ok",
            "modbus_port": int(os.getenv("MODBUS_PORT", "5020")),
            "web_port": int(os.getenv("WEB_PORT", "8000")),
            "unit_id": int(os.getenv("UNIT_ID", "1")),
            "register_count": len(definitions),
            "enforce_access_control": _ENFORCE_AC,
        }

    # ── Register reads ────────────────────────────────────────────────────────

    @app.get("/api/registers", response_model=List[RegisterValueResponse])
    def get_all_registers() -> List[RegisterValueResponse]:
        return store.get_all_register_values()

    @app.get("/api/registers/{address}", response_model=RegisterValueResponse)
    def get_register(address: int) -> RegisterValueResponse:
        rv = store.get_register_value(address)
        if rv is None:
            raise HTTPException(status_code=404, detail=f"Register {address} not found")
        return rv

    # ── Register writes ───────────────────────────────────────────────────────

    @app.post("/api/registers/bulk")
    def bulk_write(body: BulkWriteRequest) -> dict:
        errors: dict = {}
        written: dict = {}
        for addr_str, eng_val in body.values.items():
            try:
                address = int(addr_str)
                rv = store.get_register_value(address)
                if rv is None:
                    errors[addr_str] = "Register not found"
                    continue
                reg = rv.definition
                if _ENFORCE_AC and reg.access == "read" and body.source != "modbus":
                    errors[addr_str] = "Read-only register"
                    continue
                store.set_engineering_value(address, eng_val, source=body.source)
                written[addr_str] = eng_val
            except (ValueError, KeyError) as exc:
                errors[addr_str] = str(exc)

        return {"status": "ok", "written": written, "errors": errors}

    @app.post("/api/registers/{address}")
    def write_register(address: int, body: WriteRequest) -> dict:
        rv = store.get_register_value(address)
        if rv is None:
            raise HTTPException(status_code=404, detail=f"Register {address} not found")

        reg = rv.definition
        if _ENFORCE_AC and reg.access == "read" and body.source != "modbus":
            raise HTTPException(
                status_code=403,
                detail=f"Register {address} ({reg.name}) is read-only",
            )

        try:
            store.set_engineering_value(address, body.value, source=body.source)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        return {"status": "ok", "address": address, "value": body.value}

    # ── History ───────────────────────────────────────────────────────────────

    @app.get("/api/history", response_model=List[ChangeRecord])
    def get_history() -> List[ChangeRecord]:
        return store.get_history(limit=200)

    # ── Reset ─────────────────────────────────────────────────────────────────

    @app.post("/api/reset")
    def reset_registers() -> dict:
        store.reset(definitions)
        return {"status": "ok", "message": "All registers reset to defaults"}

    # ── EMS simulation helper ─────────────────────────────────────────────────

    @app.post("/api/simulate/ems")
    def simulate_ems(body: EMSSimRequest) -> dict:
        """Write typical EMS measurement registers from a single convenient endpoint.

        Apparent power S = sqrt(P² + Q²) – it is NOT a setpoint, only a
        derived/measured value.
        """
        p = body.active_power_kw
        q = body.reactive_power_kvar
        s = math.sqrt(p ** 2 + q ** 2)

        freq_raw = int(round(body.frequency_hz / 0.01))  # factor 0.01 → raw

        updates = {
            10060: p,            # ActivePower_P  (int32, kW)
            10062: q,            # ReactivePower_Q (int32, kVar)
            10064: s,            # ApparentPower_S (int32, kVA)
            # Frequency: engineering value, factor applied inside store
            10010: body.frequency_hz,
            # Voltages (all three phases same for simplicity)
            10017: body.voltage_v,
            10019: body.voltage_v,
            10021: body.voltage_v,
            # Currents (all three phases same for simplicity)
            10011: body.current_a,
            10013: body.current_a,
            10015: body.current_a,
            # SoC
            10083: body.soc_percent,
            10085: 100.0 - body.soc_percent,
            # Feed-in totals (convenience copies)
            10030: abs(p),
            10031: abs(p) / 3,
            10032: abs(p) / 3,
            10033: abs(p) / 3,
            10040: abs(q),
            10041: abs(q) / 3,
            10042: abs(q) / 3,
            10043: abs(q) / 3,
            10050: s,
            10051: s / 3,
            10052: s / 3,
            10053: s / 3,
        }

        errors: dict = {}
        for addr, val in updates.items():
            try:
                store.set_engineering_value(addr, val, source="api")
            except ValueError as exc:
                errors[addr] = str(exc)

        return {"status": "ok", "written": len(updates) - len(errors), "errors": errors}

    # ── Root – serve UI ───────────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    def root() -> HTMLResponse:
        html_path = _STATIC_DIR / "index.html"
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))

    return app
