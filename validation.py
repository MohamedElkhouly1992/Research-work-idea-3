from __future__ import annotations

from typing import Iterable, List

import numpy as np
import pandas as pd


def validation_metrics(reference: pd.Series, simulated: pd.Series) -> dict:
    ref = pd.to_numeric(reference, errors="coerce")
    sim = pd.to_numeric(simulated, errors="coerce")
    mask = ref.notna() & sim.notna()
    ref, sim = ref[mask].to_numpy(float), sim[mask].to_numpy(float)
    if len(ref) == 0:
        raise ValueError("No overlapping numeric validation data.")
    err = sim - ref
    mean_ref = max(abs(float(np.mean(ref))), 1e-9)
    rmse = float(np.sqrt(np.mean(err ** 2)))
    mae = float(np.mean(np.abs(err)))
    mape = float(np.mean(np.abs(err) / np.maximum(np.abs(ref), 1e-9)) * 100)
    cvrmse = 100 * rmse / mean_ref
    nmbe = 100 * float(np.mean(err)) / mean_ref
    ss_res = float(np.sum(err ** 2))
    ss_tot = float(np.sum((ref - np.mean(ref)) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return {"N": len(ref), "RMSE": rmse, "MAE": mae, "MAPE_pct": mape, "CVRMSE_pct": cvrmse, "NMBE_pct": nmbe, "R2": r2}


def compare_timeseries(reference: pd.DataFrame, simulated: pd.DataFrame, variables: Iterable[str], timestamp_col: str = "timestamp") -> pd.DataFrame:
    ref = reference.copy(); sim = simulated.copy()
    ref[timestamp_col] = pd.to_datetime(ref[timestamp_col], errors="coerce")
    sim[timestamp_col] = pd.to_datetime(sim[timestamp_col], errors="coerce")
    merged = ref.merge(sim, on=timestamp_col, how="inner", suffixes=("_reference", "_simulated"))
    rows: List[dict] = []
    for var in variables:
        rcol, scol = f"{var}_reference", f"{var}_simulated"
        if rcol in merged and scol in merged:
            rows.append({"Variable": var, **validation_metrics(merged[rcol], merged[scol])})
    if not rows:
        raise ValueError("None of the selected variables exists in both data sets.")
    return pd.DataFrame(rows)
