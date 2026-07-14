from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd


def _humidity_ratio_from_rh(temp_c: np.ndarray, rh_pct: np.ndarray) -> np.ndarray:
    p_ws = 0.61078 * np.exp((17.2694 * temp_c) / (temp_c + 237.3))
    p_w = np.clip(rh_pct / 100.0, 0.01, 1.0) * p_ws
    return 0.62198 * p_w / np.maximum(101.325 - p_w, 1e-6)


def generate_synthetic_weather(start: str, days: int, timestep_minutes: int, seed: int = 42) -> pd.DataFrame:
    """Generate deterministic hot-climate weather suitable for a demo run.

    This is not an EPW replacement. Users can upload measured/EPW-derived CSV data.
    """
    rng = np.random.default_rng(seed)
    index = pd.date_range(start=start, periods=int(days * 24 * 60 / timestep_minutes), freq=f"{timestep_minutes}min")
    doy = index.dayofyear.to_numpy()
    hour = index.hour.to_numpy() + index.minute.to_numpy() / 60.0

    seasonal = 29.0 + 6.0 * np.sin(2 * np.pi * (doy - 172) / 365.25)
    daily = 6.5 * np.sin(2 * np.pi * (hour - 9.0) / 24.0)
    dry_bulb = seasonal + daily + rng.normal(0, 0.35, len(index))
    rh = np.clip(56 - 0.9 * (dry_bulb - 28) + 8 * np.sin(2 * np.pi * (hour + 3) / 24), 20, 85)
    sun_angle = np.sin(np.pi * np.clip((hour - 6.0) / 12.5, 0, 1))
    solar = np.maximum(0, 880 * sun_angle ** 1.45) * (0.93 + 0.07 * rng.random(len(index)))
    wind = np.clip(3.2 + 1.2 * np.sin(2 * np.pi * hour / 24) + rng.normal(0, 0.25, len(index)), 0.2, None)

    df = pd.DataFrame({
        "timestamp": index,
        "dry_bulb_C": dry_bulb,
        "rel_humidity_pct": rh,
        "solar_W_m2": solar,
        "wind_m_s": wind,
    })
    df["humidity_ratio_kg_kg"] = _humidity_ratio_from_rh(df["dry_bulb_C"].to_numpy(), df["rel_humidity_pct"].to_numpy())
    return df


def normalize_weather(weather: Optional[pd.DataFrame], start: str, days: int, timestep_minutes: int) -> pd.DataFrame:
    if weather is None or weather.empty:
        return generate_synthetic_weather(start, days, timestep_minutes)

    df = weather.copy()
    aliases = {
        "datetime": "timestamp", "date_time": "timestamp", "time": "timestamp",
        "temperature": "dry_bulb_C", "temp_C": "dry_bulb_C", "outdoor_temp_C": "dry_bulb_C",
        "rh": "rel_humidity_pct", "relative_humidity": "rel_humidity_pct",
        "solar": "solar_W_m2", "ghi": "solar_W_m2", "global_horizontal_radiation": "solar_W_m2",
    }
    df = df.rename(columns={c: aliases.get(c, c) for c in df.columns})
    required = {"timestamp", "dry_bulb_C"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Weather CSV is missing required columns: {sorted(missing)}")

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["dry_bulb_C"] = pd.to_numeric(df["dry_bulb_C"], errors="coerce")
    if "rel_humidity_pct" not in df:
        df["rel_humidity_pct"] = 50.0
    if "solar_W_m2" not in df:
        df["solar_W_m2"] = 0.0
    if "wind_m_s" not in df:
        df["wind_m_s"] = 2.0
    df = df.dropna(subset=["timestamp", "dry_bulb_C"]).sort_values("timestamp")
    df = df.set_index("timestamp").resample(f"{timestep_minutes}min").interpolate("time").reset_index()
    target_periods = int(days * 24 * 60 / timestep_minutes)
    if len(df) < target_periods:
        repeats = math.ceil(target_periods / max(len(df), 1))
        base = pd.concat([df.drop(columns=["timestamp"])] * repeats, ignore_index=True).iloc[:target_periods]
        base.insert(0, "timestamp", pd.date_range(start=start, periods=target_periods, freq=f"{timestep_minutes}min"))
        df = base
    else:
        df = df.iloc[:target_periods].copy()
    df["rel_humidity_pct"] = pd.to_numeric(df["rel_humidity_pct"], errors="coerce").fillna(50).clip(1, 100)
    df["solar_W_m2"] = pd.to_numeric(df["solar_W_m2"], errors="coerce").fillna(0).clip(lower=0)
    df["wind_m_s"] = pd.to_numeric(df["wind_m_s"], errors="coerce").fillna(2).clip(lower=0)
    df["humidity_ratio_kg_kg"] = _humidity_ratio_from_rh(df["dry_bulb_C"].to_numpy(), df["rel_humidity_pct"].to_numpy())
    return df
