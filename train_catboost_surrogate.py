"""Train an optional CatBoost surrogate from simulation time-series exports.

Example:
  python train_catboost_surrogate.py --input building_timeseries.csv --output_dir surrogate_model
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split

FEATURES = [
    "outdoor_temp_C", "outdoor_rh_pct", "solar_W_m2", "average_zone_temp_C",
    "average_co2_ppm", "supply_air_temp_setpoint_C", "chilled_water_supply_setpoint_C",
    "static_pressure_fraction", "zone_setpoint_reset_C", "outdoor_air_fraction",
    "filter_clogging", "coil_fouling", "chiller_fouling", "degradation_index",
]
TARGETS = ["electric_power_kW", "cooling_load_kW", "chiller_COP", "max_comfort_deviation_C"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output_dir", default="surrogate_model")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    df = pd.read_csv(args.input)
    features = [c for c in FEATURES if c in df.columns]
    targets = [c for c in TARGETS if c in df.columns]
    if len(features) < 5 or not targets:
        raise ValueError("Input does not contain enough expected simulation features/targets.")
    data = df[features + targets].apply(pd.to_numeric, errors="coerce").dropna()
    X_train, X_test, y_train, y_test = train_test_split(data[features], data[targets], test_size=0.2, random_state=args.seed)

    try:
        from catboost import CatBoostRegressor
        model_type = "CatBoostRegressor"
        models = {}
        predictions = {}
        for target in targets:
            model = CatBoostRegressor(iterations=500, depth=8, learning_rate=0.05, loss_function="RMSE", random_seed=args.seed, verbose=False)
            model.fit(X_train, y_train[target])
            predictions[target] = model.predict(X_test)
            models[target] = model
    except ImportError:
        from sklearn.ensemble import ExtraTreesRegressor
        model_type = "ExtraTreesRegressor fallback"
        models = {}
        predictions = {}
        for target in targets:
            model = ExtraTreesRegressor(n_estimators=350, random_state=args.seed, n_jobs=-1, min_samples_leaf=2)
            model.fit(X_train, y_train[target])
            predictions[target] = model.predict(X_test)
            models[target] = model

    out = Path(args.output_dir); out.mkdir(parents=True, exist_ok=True)
    metrics = []
    for target in targets:
        pred = np.asarray(predictions[target])
        metrics.append({
            "target": target,
            "MAE": mean_absolute_error(y_test[target], pred),
            "RMSE": mean_squared_error(y_test[target], pred) ** 0.5,
            "R2": r2_score(y_test[target], pred),
        })
        if model_type == "CatBoostRegressor":
            models[target].save_model(str(out / f"{target}.cbm"))
        else:
            import joblib
            joblib.dump(models[target], out / f"{target}.joblib")
    pd.DataFrame(metrics).to_csv(out / "surrogate_metrics.csv", index=False)
    (out / "model_manifest.json").write_text(json.dumps({"model_type": model_type, "features": features, "targets": targets}, indent=2))
    print(pd.DataFrame(metrics).to_string(index=False))


if __name__ == "__main__":
    main()
