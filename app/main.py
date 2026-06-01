"""Application entry-point.

Starts the Modbus TCP server and the FastAPI/Uvicorn web server concurrently
inside the same asyncio event loop.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import uvicorn

from app.modbus_server import run_modbus_server
from app.register_map import load_registers
from app.register_store import RegisterStore
from app.web import create_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s – %(message)s",
)
logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "registers.yaml"


async def _main() -> None:
    # Load register definitions from YAML
    definitions = load_registers(_CONFIG_PATH)

    # Build the shared register store
    store = RegisterStore()
    store.initialize(definitions)

    # Build the FastAPI application
    web_host = os.getenv("WEB_HOST", "0.0.0.0")
    web_port = int(os.getenv("WEB_PORT", "8000"))
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

    # Run Modbus TCP server and web server side-by-side
    await asyncio.gather(
        run_modbus_server(store),
        uv_server.serve(),
    )


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
