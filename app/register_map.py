"""Load register definitions from CSV or YAML configuration files."""
from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import List

import yaml

from app.schemas import RegisterDefinition

logger = logging.getLogger(__name__)


def load_registers(config_path: Path) -> List[RegisterDefinition]:
    """Parse *config_path* and return a list of :class:`RegisterDefinition`."""
    path = Path(config_path)
    if not path.exists() and path.suffix.lower() == ".csv":
        yaml_fallback = path.with_suffix(".yaml")
        if yaml_fallback.exists():
            path = yaml_fallback

    if path.suffix.lower() == ".csv":
        with open(path, "r", encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        entries = [_normalize_csv_row(row) for row in rows]
    else:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        entries = data.get("registers", [])

    definitions: List[RegisterDefinition] = []
    for item in entries:
        try:
            reg = RegisterDefinition(**item)
            definitions.append(reg)
        except Exception as exc:
            logger.error("Skipping malformed register entry %s: %s", item, exc)

    logger.info("Loaded %d register definitions from %s", len(definitions), path)
    return definitions


def _normalize_csv_row(row: dict[str, str]) -> dict:
    normalized = dict(row)
    normalized["address"] = int(row["address"])
    normalized["factor"] = float(row.get("factor", 1) or 1)
    normalized["default"] = float(row.get("default", 0) or 0)

    polling = row.get("polling_interval_ms")
    normalized["polling_interval_ms"] = int(polling) if polling not in (None, "") else None
    return normalized
