"""Pydantic models for register definitions, API requests, and responses."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, field_validator


class RegisterDefinition(BaseModel):
    address: int
    name: str
    description: str
    datatype: str          # BIT | uint16 | int16 | uint32 | int32 | float32
    byteorder: str         # bigE
    factor: float
    unit: str
    access: str            # read | write | readwrite
    role: str              # config | ems_measurement | feedback | grid_operator_command
    category: Optional[str] = None
    default: float = 0.0

    @field_validator("datatype")
    @classmethod
    def validate_datatype(cls, v: str) -> str:
        allowed = {"BIT", "uint16", "int16", "uint32", "int32", "float32"}
        if v not in allowed:
            raise ValueError(f"Unknown datatype '{v}', must be one of {allowed}")
        return v

    @field_validator("access")
    @classmethod
    def validate_access(cls, v: str) -> str:
        if v not in {"read", "write", "readwrite"}:
            raise ValueError(f"Unknown access '{v}'")
        return v

    def is_32bit(self) -> bool:
        return self.datatype in ("int32", "uint32", "float32")

    def is_writable(self) -> bool:
        return self.access in ("write", "readwrite")


class RegisterValueResponse(BaseModel):
    definition: RegisterDefinition
    raw_value: Union[int, List[int]]   # single word or [high, low] for 32-bit
    engineering_value: Optional[float]


class WriteRequest(BaseModel):
    value: float
    source: str = "api"


class BulkWriteRequest(BaseModel):
    source: str = "api"
    values: Dict[str, float]           # address (as string) -> engineering value


class ChangeRecord(BaseModel):
    timestamp: str
    source: str                        # ui | api | modbus
    address: int
    name: str
    old_raw: Any
    new_raw: Any
    engineering_value: float


class EMSSimRequest(BaseModel):
    active_power_kw: float = 0.0
    reactive_power_kvar: float = 0.0
    voltage_v: float = 400.0
    current_a: float = 0.0
    frequency_hz: float = 50.0
    soc_percent: float = 0.0
