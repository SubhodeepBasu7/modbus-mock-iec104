"""Thread-safe in-memory store for Modbus holding registers.

All public methods are safe to call from both sync (Modbus datablock) and
async (FastAPI) contexts because they use threading.Lock with very short
critical sections (dict access only).
"""
from __future__ import annotations

import logging
import struct
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

from app.schemas import ChangeRecord, RegisterDefinition, RegisterValueResponse

logger = logging.getLogger(__name__)

_MAX_HISTORY = 1000


class RegisterStore:
    """Central in-memory store shared by the Modbus server and the web API."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Map of logical address -> RegisterDefinition
        self._registers: Dict[int, RegisterDefinition] = {}
        # Flat map of every allocated Modbus address -> 16-bit raw value
        self._raw: Dict[int, int] = {}
        self._history: List[ChangeRecord] = []

    # ──────────────────────────────────────────────────────────────────────────
    # Initialisation
    # ──────────────────────────────────────────────────────────────────────────

    def initialize(self, definitions: List[RegisterDefinition]) -> None:
        """Load register definitions and reset all raw values to 0."""
        with self._lock:
            self._registers.clear()
            self._raw.clear()
            for reg in definitions:
                self._registers[reg.address] = reg
                self._raw[reg.address] = 0
                if reg.is_32bit():
                    self._raw[reg.address + 1] = 0

    # ──────────────────────────────────────────────────────────────────────────
    # Low-level 16-bit access (used by Modbus datablock)
    # ──────────────────────────────────────────────────────────────────────────

    def get_raw_16(self, address: int) -> int:
        with self._lock:
            return self._raw.get(address, 0)

    def set_from_modbus(self, address: int, value: int) -> None:
        """Write a single 16-bit Modbus register from a Modbus client request."""
        value = int(value) & 0xFFFF
        with self._lock:
            old_raw = self._raw.get(address, 0)
            self._raw[address] = value
            reg = self._registers.get(address)
            name = reg.name if reg else f"addr_{address}"
            eng = self._compute_engineering(address) if reg else float(value)
            record = ChangeRecord(
                timestamp=datetime.now(timezone.utc).isoformat(),
                source="modbus",
                address=address,
                name=name,
                old_raw=old_raw,
                new_raw=value,
                engineering_value=eng,
            )
            self._append_history(record)
        logger.debug("modbus write addr=%d raw=%d", address, value)

    # ──────────────────────────────────────────────────────────────────────────
    # Engineering-value API (used by FastAPI)
    # ──────────────────────────────────────────────────────────────────────────

    def get_engineering_value(self, address: int) -> Optional[float]:
        with self._lock:
            return self._compute_engineering(address)

    def set_engineering_value(
        self, address: int, eng_value: float, source: str = "api"
    ) -> None:
        """Convert an engineering value to raw and store it.

        Raises ValueError for out-of-range or unknown addresses.
        """
        with self._lock:
            reg = self._registers.get(address)
            if reg is None:
                raise ValueError(f"Register {address} not found")

            raw_value = eng_value / reg.factor if reg.factor != 0 else eng_value
            old_eng = self._compute_engineering(address)

            if reg.datatype in ("uint16", "BIT"):
                raw_int = self._validate_uint16(int(round(raw_value)), reg.name)
                old_raw = self._raw.get(address, 0)
                self._raw[address] = raw_int
                new_raw: Any = raw_int

            elif reg.datatype == "int16":
                raw_int = self._validate_int16(int(round(raw_value)), reg.name)
                old_raw = self._raw.get(address, 0)
                self._raw[address] = raw_int & 0xFFFF
                new_raw = raw_int

            elif reg.datatype == "int32":
                raw_int = self._validate_int32(int(round(raw_value)), reg.name)
                old_raw = self._decode_int32(
                    self._raw.get(address, 0), self._raw.get(address + 1, 0)
                )
                high, low = self._encode_int32(raw_int)
                self._raw[address] = high
                self._raw[address + 1] = low
                new_raw = raw_int

            elif reg.datatype == "uint32":
                raw_int = self._validate_uint32(int(round(raw_value)), reg.name)
                old_raw = (
                    (self._raw.get(address, 0) << 16) | self._raw.get(address + 1, 0)
                )
                self._raw[address] = (raw_int >> 16) & 0xFFFF
                self._raw[address + 1] = raw_int & 0xFFFF
                new_raw = raw_int

            else:
                raise ValueError(f"Unsupported datatype '{reg.datatype}'")

            record = ChangeRecord(
                timestamp=datetime.now(timezone.utc).isoformat(),
                source=source,
                address=address,
                name=reg.name,
                old_raw=old_raw,
                new_raw=new_raw,
                engineering_value=eng_value,
            )
            self._append_history(record)

        logger.debug(
            "%s write addr=%d eng=%.4f [%s]", source, address, eng_value, source
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Bulk / snapshot helpers
    # ──────────────────────────────────────────────────────────────────────────

    def get_all_register_values(self) -> List[RegisterValueResponse]:
        with self._lock:
            result: List[RegisterValueResponse] = []
            for address in sorted(self._registers):
                reg = self._registers[address]
                eng = self._compute_engineering(address)
                if reg.is_32bit():
                    raw: Any = [self._raw.get(address, 0), self._raw.get(address + 1, 0)]
                else:
                    raw = self._raw.get(address, 0)
                result.append(
                    RegisterValueResponse(
                        definition=reg, raw_value=raw, engineering_value=eng
                    )
                )
            return result

    def get_register_value(self, address: int) -> Optional[RegisterValueResponse]:
        with self._lock:
            reg = self._registers.get(address)
            if reg is None:
                return None
            eng = self._compute_engineering(address)
            if reg.is_32bit():
                raw: Any = [self._raw.get(address, 0), self._raw.get(address + 1, 0)]
            else:
                raw = self._raw.get(address, 0)
            return RegisterValueResponse(
                definition=reg, raw_value=raw, engineering_value=eng
            )

    def get_all_definitions(self) -> List[RegisterDefinition]:
        with self._lock:
            return list(self._registers.values())

    def get_history(self, limit: int = 100) -> List[ChangeRecord]:
        with self._lock:
            return list(self._history[-limit:])

    def reset(self, definitions: List[RegisterDefinition]) -> None:
        with self._lock:
            self._raw.clear()
            for reg in definitions:
                self._raw[reg.address] = 0
                if reg.is_32bit():
                    self._raw[reg.address + 1] = 0
            logger.info("Register store reset to defaults")

    # ──────────────────────────────────────────────────────────────────────────
    # Internal helpers (call only while _lock is held)
    # ──────────────────────────────────────────────────────────────────────────

    def _compute_engineering(self, address: int) -> Optional[float]:
        reg = self._registers.get(address)
        if reg is None:
            return None
        dtype = reg.datatype
        factor = reg.factor if reg.factor != 0 else 1.0

        if dtype in ("uint16", "BIT"):
            return self._raw.get(address, 0) * factor

        if dtype == "int16":
            raw = self._raw.get(address, 0)
            signed = raw if raw <= 32767 else raw - 65536
            return signed * factor

        if dtype == "int32":
            val = self._decode_int32(
                self._raw.get(address, 0), self._raw.get(address + 1, 0)
            )
            return val * factor

        if dtype == "uint32":
            val = (self._raw.get(address, 0) << 16) | self._raw.get(address + 1, 0)
            return val * factor

        return None

    # ── 32-bit encoding helpers ────────────────────────────────────────────

    @staticmethod
    def _encode_int32(value: int) -> Tuple[int, int]:
        """Pack a signed int32 into two big-endian 16-bit words (high, low)."""
        packed = struct.pack(">i", value)
        high = struct.unpack(">H", packed[0:2])[0]
        low = struct.unpack(">H", packed[2:4])[0]
        return high, low

    @staticmethod
    def _decode_int32(high: int, low: int) -> int:
        """Unpack two big-endian 16-bit words into a signed int32."""
        packed = struct.pack(">HH", high & 0xFFFF, low & 0xFFFF)
        return struct.unpack(">i", packed)[0]

    # ── Validation helpers ─────────────────────────────────────────────────

    @staticmethod
    def _validate_uint16(v: int, name: str) -> int:
        if not (0 <= v <= 65535):
            raise ValueError(
                f"{name}: uint16 value {v} out of range [0, 65535]"
            )
        return v

    @staticmethod
    def _validate_int16(v: int, name: str) -> int:
        if not (-32768 <= v <= 32767):
            raise ValueError(
                f"{name}: int16 value {v} out of range [-32768, 32767]"
            )
        return v

    @staticmethod
    def _validate_int32(v: int, name: str) -> int:
        if not (-2_147_483_648 <= v <= 2_147_483_647):
            raise ValueError(
                f"{name}: int32 value {v} out of range [-2147483648, 2147483647]"
            )
        return v

    @staticmethod
    def _validate_uint32(v: int, name: str) -> int:
        if not (0 <= v <= 4_294_967_295):
            raise ValueError(
                f"{name}: uint32 value {v} out of range [0, 4294967295]"
            )
        return v

    # ── History helper ─────────────────────────────────────────────────────

    def _append_history(self, record: ChangeRecord) -> None:
        self._history.append(record)
        if len(self._history) > _MAX_HISTORY:
            self._history = self._history[-_MAX_HISTORY:]
