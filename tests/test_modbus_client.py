"""Modbus TCP client test script.

Demonstrates:
  - Connecting to the Modbus server on localhost:5020
  - Writing and reading back grid-operator setpoint registers (uint16)
  - Writing and reading back measurement registers (int32)
  - CosPhi factor encoding  (engineering 0.95 → raw 950)
  - int32 big-endian encoding / decoding

Run after starting the server:
    python -m app.main   # or  docker compose up
    python tests/test_modbus_client.py
"""
from __future__ import annotations

import asyncio
import struct
import sys
import time
from typing import Tuple

from pymodbus.client import AsyncModbusTcpClient

HOST = "localhost"
PORT = 5020
UNIT_ID = 1


# ─────────────────────────────────────────────────────────────────────────────
# Helper: encode / decode big-endian int32
# ─────────────────────────────────────────────────────────────────────────────

def encode_int32_be(value: int) -> Tuple[int, int]:
    """Pack a signed int32 into (high_word, low_word) big-endian."""
    packed = struct.pack(">i", value)
    high = struct.unpack(">H", packed[0:2])[0]
    low = struct.unpack(">H", packed[2:4])[0]
    return high, low


def decode_int32_be(high: int, low: int) -> int:
    """Unpack (high_word, low_word) big-endian into a signed int32."""
    packed = struct.pack(">HH", high & 0xFFFF, low & 0xFFFF)
    return struct.unpack(">i", packed)[0]


# ─────────────────────────────────────────────────────────────────────────────
# Test functions
# ─────────────────────────────────────────────────────────────────────────────

async def run_tests() -> int:
    """Execute all Modbus tests.  Returns 0 on success, non-zero on failure."""
    failed = 0

    async with AsyncModbusTcpClient(host=HOST, port=PORT) as client:
        if not client.connected:
            print(f"ERROR: Could not connect to {HOST}:{PORT}", file=sys.stderr)
            return 1

        print(f"Connected to Modbus TCP server at {HOST}:{PORT}")

        # ── Test 1: Write and read back grid-operator uint16 setpoints ────────
        print("\n── Test 1: Grid-operator uint16 setpoints ──")
        setpoints = [
            (11040, 1,   "ActivePower_SetPoint_P_ON_OFF"),
            (11042, 500, "ActivePower_SetPoint_P_kW"),
            (11010, 1,   "ReactivePower_SetPoint_Q_kVar_ON_OFF"),
            (11012, 250, "ReactivePower_SetPoint_Q_kVar"),
        ]

        for addr, value, name in setpoints:
            # Write
            wr = await client.write_register(addr, value, slave=UNIT_ID)
            assert not wr.isError(), f"Write failed for {name} ({addr}): {wr}"

            # Read back
            rr = await client.read_holding_registers(addr, count=1, slave=UNIT_ID)
            assert not rr.isError(), f"Read failed for {name} ({addr}): {rr}"
            got = rr.registers[0]
            status = "PASS" if got == value else "FAIL"
            if got != value:
                failed += 1
            print(f"  {status}  addr={addr} {name:45s}  expected={value}  got={got}")

        # ── Test 2: Write and read back int32 measurement registers ───────────
        print("\n── Test 2: int32 measurement registers ──")
        int32_cases = [
            (10060, 500,   "ActivePower_P  (kW)"),
            (10062, -200,  "ReactivePower_Q (kVar, negative)"),
            (10064, 539,   "ApparentPower_S (kVA, derived)"),
        ]

        for base_addr, value, name in int32_cases:
            high, low = encode_int32_be(value)

            # Write two consecutive registers (high word at base, low word at base+1)
            wr = await client.write_registers(base_addr, [high, low], slave=UNIT_ID)
            assert not wr.isError(), f"Write failed for {name}: {wr}"

            # Read back
            rr = await client.read_holding_registers(base_addr, count=2, slave=UNIT_ID)
            assert not rr.isError(), f"Read failed for {name}: {rr}"
            got_high, got_low = rr.registers[0], rr.registers[1]
            got_value = decode_int32_be(got_high, got_low)

            status = "PASS" if got_value == value else "FAIL"
            if got_value != value:
                failed += 1
            print(
                f"  {status}  addr={base_addr} {name:40s}  "
                f"encoded=[0x{high:04X}, 0x{low:04X}]  "
                f"decoded={got_value}"
            )

        # ── Test 3: CosPhi factor encoding  (engineering 0.95 → raw 950) ─────
        print("\n── Test 3: CosPhi factor encoding ──")
        # Register 11032  CosPhi_SetPoint  factor=0.001 (stored as integer × 1000)
        # UI / API input: engineering value 0.95
        # Raw register value: 950  (= 0.95 / 0.001)
        cos_phi_eng = 0.95
        cos_phi_raw = round(cos_phi_eng / 0.001)   # 950 (use round to avoid float imprecision)

        wr = await client.write_register(11032, cos_phi_raw, slave=UNIT_ID)
        assert not wr.isError(), f"Write CosPhi failed: {wr}"

        rr = await client.read_holding_registers(11032, count=1, slave=UNIT_ID)
        assert not rr.isError(), f"Read CosPhi failed: {rr}"
        got_raw = rr.registers[0]
        got_eng = got_raw / 1000.0

        status = "PASS" if got_raw == cos_phi_raw else "FAIL"
        if got_raw != cos_phi_raw:
            failed += 1
        print(
            f"  {status}  addr=11032 CosPhi_SetPoint  "
            f"eng_in={cos_phi_eng}  raw_written={cos_phi_raw}  "
            f"raw_read={got_raw}  eng_out={got_eng:.3f}"
        )

        # ── Test 4: Frequency factor encoding  (50.00 Hz → raw 5000) ─────────
        print("\n── Test 4: Frequency factor encoding ──")
        # Register 10010  LineCurrent_Frequency  factor=0.01
        freq_hz = 50.0
        freq_raw = int(freq_hz / 0.01)  # 5000

        wr = await client.write_register(10010, freq_raw, slave=UNIT_ID)
        assert not wr.isError(), f"Write Frequency failed: {wr}"

        rr = await client.read_holding_registers(10010, count=1, slave=UNIT_ID)
        assert not rr.isError(), f"Read Frequency failed: {rr}"
        got_raw = rr.registers[0]
        got_hz = got_raw * 0.01

        status = "PASS" if got_raw == freq_raw else "FAIL"
        if got_raw != freq_raw:
            failed += 1
        print(
            f"  {status}  addr=10010 LineCurrent_Frequency  "
            f"eng_in={freq_hz} Hz  raw_written={freq_raw}  "
            f"raw_read={got_raw}  eng_out={got_hz:.2f} Hz"
        )

    print(f"\n── Summary: {'ALL PASSED' if failed == 0 else f'{failed} FAILED'} ──")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    rc = asyncio.run(run_tests())
    sys.exit(rc)
