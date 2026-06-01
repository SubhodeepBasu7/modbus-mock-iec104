"""Load register definitions from the YAML configuration file."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List

import yaml

from app.schemas import RegisterDefinition

logger = logging.getLogger(__name__)


def load_registers(config_path: Path) -> List[RegisterDefinition]:
    """Parse *config_path* and return a list of :class:`RegisterDefinition`."""
    with open(config_path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    definitions: List[RegisterDefinition] = []
    for item in data.get("registers", []):
        try:
            reg = RegisterDefinition(**item)
            definitions.append(reg)
        except Exception as exc:
            logger.error("Skipping malformed register entry %s: %s", item, exc)

    logger.info("Loaded %d register definitions from %s", len(definitions), config_path)
    return definitions
