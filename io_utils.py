from __future__ import annotations

import json
from typing import Any, Dict

import pandas as pd

from .config import SimulationConfig, ZoneConfig


def config_from_json_bytes(data: bytes) -> SimulationConfig:
    return SimulationConfig.from_dict(json.loads(data.decode("utf-8")))


def zones_from_csv(df: pd.DataFrame):
    required = {"name", "area_m2", "ahu"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Zone CSV is missing required columns: {sorted(missing)}")
    defaults = ZoneConfig("Template", 100.0).__dict__
    zones = []
    for row in df.to_dict(orient="records"):
        payload: Dict[str, Any] = defaults.copy()
        payload.update({k: v for k, v in row.items() if pd.notna(v)})
        zones.append(ZoneConfig(**payload))
    return zones
