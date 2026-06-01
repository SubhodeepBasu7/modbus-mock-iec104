"""Modbus TCP server backed by the shared RegisterStore.

Uses pymodbus 3.x async API.  A custom data-block delegates every Modbus
read/write directly to the RegisterStore so that changes made via the web UI
are immediately visible to Modbus clients, and vice-versa.
"""
from __future__ import annotations

import logging
import os
from typing import List

from pymodbus.datastore import ModbusServerContext, ModbusSlaveContext
from pymodbus.datastore.store import ModbusSparseDataBlock
from pymodbus.server import StartAsyncTcpServer

from app.register_store import RegisterStore

logger = logging.getLogger(__name__)


class _SharedBlock(ModbusSparseDataBlock):
    """Custom Modbus data-block that reads/writes the shared RegisterStore.

    Big-endian int32 encoding note
    --------------------------------
    When a Modbus client reads/writes a 32-bit value it issues two consecutive
    16-bit register accesses.  The RegisterStore stores each 16-bit word at its
    own Modbus address; the high word is at *address* and the low word is at
    *address + 1*.  The Modbus client is responsible for issuing the correct
    two-word read/write.
    """

    def __init__(self, store: RegisterStore) -> None:
        # Initialise the parent with an empty map; we override all access.
        super().__init__({})
        self.store = store

    # pymodbus calls validate() before every read/write.
    def validate(self, address: int, count: int = 1) -> bool:  # noqa: D401
        return True  # Accept all valid Modbus addresses

    def getValues(self, address: int, count: int = 1) -> List[int]:
        """Return *count* 16-bit raw values starting at *address*."""
        return [self.store.get_raw_16(address + i) for i in range(count)]

    def setValues(self, address: int, values: List[int]) -> None:
        """Write *values* (one per Modbus register) starting at *address*."""
        for i, val in enumerate(values):
            self.store.set_from_modbus(address + i, val)


async def run_modbus_server(store: RegisterStore) -> None:
    """Start the async Modbus TCP server and run until cancelled."""
    host = os.getenv("MODBUS_HOST", "0.0.0.0")
    port = int(os.getenv("MODBUS_PORT", "5020"))
    unit_id = int(os.getenv("UNIT_ID", "1"))

    block = _SharedBlock(store)

    slave_context = ModbusSlaveContext(
        di=block,
        co=block,
        hr=block,
        ir=block,
        zero_mode=True,  # address 0 in request == index 0 in the data-block
    )

    server_context = ModbusServerContext(
        slaves={unit_id: slave_context},
        single=False,
    )

    logger.info(
        "Starting Modbus TCP server on %s:%d (unit_id=%d)", host, port, unit_id
    )

    await StartAsyncTcpServer(
        context=server_context,
        address=(host, port),
    )
