"""Remote Modbus-backed register store for the UI."""
from __future__ import annotations

import logging
import struct
from datetime import datetime, timezone
from typing import Any, List, Optional

from pyModbusTCP.client import ModbusClient

from app.register_store import RegisterStore
from app.schemas import ChangeRecord, RegisterDefinition, RegisterValueResponse

logger = logging.getLogger(__name__)


class RemoteModbusRegisterStore(RegisterStore):
    """Expose the RegisterStore API while reading/writing a remote Modbus server."""

    def __init__(self, host: str, port: int, unit_id: int) -> None:
        super().__init__()
        self.client = ModbusClient(
            host=host,
            port=port,
            unit_id=unit_id,
            auto_open=True,
            auto_close=False,
            timeout=5.0,
        )

    def get_raw_16(self, address: int) -> int:
        return self._read_words(address, 1)[0]

    def set_from_modbus(self, address: int, value: int) -> None:
        self._write_words(address, [int(value) & 0xFFFF])

    def get_engineering_value(self, address: int) -> Optional[float]:
        response = self.get_register_value(address)
        return response.engineering_value if response else None

    def set_engineering_value(
        self, address: int, eng_value: float, source: str = "api"
    ) -> None:
        with self._lock:
            reg = self._registers.get(address)
            if reg is None:
                raise ValueError(f"Register {address} not found")

            old_words = self._read_register_words(reg)
            old_raw = self._raw_value(reg, old_words)
            new_words, new_raw = self._encode_engineering_value(reg, eng_value)
            self._write_words(address, new_words)
            self._append_history(
                ChangeRecord(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    source=source,
                    address=address,
                    name=reg.name,
                    old_raw=old_raw,
                    new_raw=new_raw,
                    engineering_value=eng_value,
                )
            )

    def get_all_register_values(self) -> List[RegisterValueResponse]:
        with self._lock:
            return [
                self._response_from_register(self._registers[address])
                for address in sorted(self._registers)
            ]

    def get_register_value(self, address: int) -> Optional[RegisterValueResponse]:
        with self._lock:
            reg = self._registers.get(address)
            if reg is None:
                return None
            return self._response_from_register(reg)

    def reset(self, definitions: List[RegisterDefinition]) -> None:
        with self._lock:
            for reg in definitions:
                words, _raw = self._encode_engineering_value(reg, reg.default)
                self._write_words(reg.address, words)
            logger.info("Remote Modbus register store reset to defaults")

    def _response_from_register(self, reg: RegisterDefinition) -> RegisterValueResponse:
        words = self._read_register_words(reg)
        raw_value: Any = words if reg.is_32bit() else words[0]
        return RegisterValueResponse(
            definition=reg,
            raw_value=raw_value,
            engineering_value=self._engineering_value(reg, words),
        )

    def _read_register_words(self, reg: RegisterDefinition) -> List[int]:
        count = 2 if reg.is_32bit() else 1
        return self._read_words(reg.address, count)

    def _read_words(self, address: int, count: int) -> List[int]:
        values = self.client.read_holding_registers(int(address), int(count))
        if values is None or len(values) != count:
            raise ValueError(f"Modbus read failed at address {address} count {count}")
        return [int(item) & 0xFFFF for item in values]

    def _write_words(self, address: int, values: List[int]) -> None:
        payload = [int(item) & 0xFFFF for item in values]
        if len(payload) == 1:
            ok = self.client.write_single_register(int(address), payload[0])
        else:
            ok = self.client.write_multiple_registers(int(address), payload)
        if not ok:
            raise ValueError(
                f"Modbus write failed at address {address} count {len(payload)}"
            )

    def _engineering_value(self, reg: RegisterDefinition, words: List[int]) -> Optional[float]:
        raw = self._raw_value(reg, words)
        factor = reg.factor if reg.factor != 0 else 1.0
        return float(raw * factor)

    def _raw_value(self, reg: RegisterDefinition, words: List[int]) -> int | float:
        if reg.datatype in ("uint16", "BIT"):
            return words[0]
        if reg.datatype == "int16":
            return words[0] if words[0] <= 32767 else words[0] - 65536
        if reg.datatype == "int32":
            return self._decode_int32(words[0], words[1])
        if reg.datatype == "uint32":
            return (words[0] << 16) | words[1]
        if reg.datatype == "float32":
            packed = struct.pack(">HH", words[0] & 0xFFFF, words[1] & 0xFFFF)
            return struct.unpack(">f", packed)[0]
        raise ValueError(f"Unsupported datatype '{reg.datatype}'")

    def _encode_engineering_value(
        self, reg: RegisterDefinition, eng_value: float
    ) -> tuple[List[int], int | float]:
        raw_value = eng_value / reg.factor if reg.factor != 0 else eng_value
        if reg.datatype in ("uint16", "BIT"):
            raw_int = self._validate_uint16(int(round(raw_value)), reg.name)
            return [raw_int], raw_int
        if reg.datatype == "int16":
            raw_int = self._validate_int16(int(round(raw_value)), reg.name)
            return [raw_int & 0xFFFF], raw_int
        if reg.datatype == "int32":
            raw_int = self._validate_int32(int(round(raw_value)), reg.name)
            high, low = self._encode_int32(raw_int)
            return [high, low], raw_int
        if reg.datatype == "uint32":
            raw_int = self._validate_uint32(int(round(raw_value)), reg.name)
            return [(raw_int >> 16) & 0xFFFF, raw_int & 0xFFFF], raw_int
        if reg.datatype == "float32":
            packed = struct.pack(">f", float(raw_value))
            high, low = struct.unpack(">HH", packed)
            return [high, low], float(raw_value)
        raise ValueError(f"Unsupported datatype '{reg.datatype}'")
