"""Application entry-point for the remote Modbus visualization UI."""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import uvicorn

from app.register_map import load_registers
from app.remote_store import RemoteModbusRegisterStore
from app.web import create_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s – %(message)s",
)
logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config" / "registers.csv"


def _resolve_register_config_path() -> Path:
    env_path = os.getenv("REGISTER_CSV_PATH", "").strip()
    if env_path:
        return Path(env_path)
    return _DEFAULT_CONFIG_PATH


async def _main() -> None:
    definitions = load_registers(_resolve_register_config_path())

    modbus_host = os.getenv("MODBUS_HOST", "localhost")
    modbus_port = int(os.getenv("MODBUS_PORT", "5020"))
    unit_id = int(os.getenv("UNIT_ID", "1"))

    store = RemoteModbusRegisterStore(
        host=modbus_host,
        port=modbus_port,
        unit_id=unit_id,
    )
    store.initialize(definitions)

    # Build the FastAPI application
    web_host = os.getenv("WEB_HOST", "0.0.0.0")
    web_port = int(os.getenv("WEB_PORT", "8005"))
    app = create_app(store, definitions)

    # Configure uvicorn (log_level must stay compatible with root logger)
    uv_config = uvicorn.Config(
        app=app,
        host=web_host,
        port=web_port,
        log_level="info",
        access_log=True,
    )
    uv_server = uvicorn.Server(uv_config)

    logger.info(
        "Starting web server on http://%s:%d", web_host, web_port
    )

    logger.info(
        "Connecting UI to Modbus TCP server at %s:%d (unit_id=%d)",
        modbus_host,
        modbus_port,
        unit_id,
    )
    await uv_server.serve()


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
