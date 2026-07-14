from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable

import numpy as np

from .config import BMSConfig


@dataclass
class ControlAction:
    supply_air_temp_C: float
    chilled_water_supply_C: float
    static_pressure_fraction: float
    cooling_setpoint_reset_C: float
    outdoor_air_fraction: float
    demand_response: bool = False
    optimizer_objective: float = 0.0


def baseline_action(strategy: str, outdoor_temp_C: float, occupied: bool, bms: BMSConfig) -> ControlAction:
    strategy = strategy.upper()
    if strategy == "S0":
        return ControlAction(13.0, 6.5, 1.0, 0.0, 0.20)
    if strategy == "S1":
        sat = float(np.clip(13.0 + 0.18 * (24.0 - outdoor_temp_C), 12.0, 15.5))
        return ControlAction(sat, 6.8, 0.78 if occupied else 0.45, 0.2 if occupied else 1.0, 0.16)
    if strategy == "S2":
        sat = float(np.clip(13.5 + 0.15 * (25.0 - outdoor_temp_C), 12.0, 15.8))
        return ControlAction(sat, 7.0, 0.72 if occupied else 0.40, 0.35 if occupied else 1.2, 0.15)
    return ControlAction(14.0, 7.2, 0.68 if occupied else 0.38, 0.4 if occupied else 1.4, 0.15)


def _candidate_objective(candidate: np.ndarray, context: Dict[str, float], bms: BMSConfig) -> float:
    sat, chws, sp, reset, oa = candidate
    out = context["outdoor_temp_C"]
    avg_zone = context["avg_zone_temp_C"]
    load = max(context["load_proxy_kW"], 0.0)
    occupancy = context["occupancy_fraction"]
    fouling = context["degradation_index"]
    avg_co2 = context.get("avg_co2_ppm", 600.0)

    lift = max(4.0, out - chws)
    cooling_factor = (lift / 24.0) ** 1.25 * (1.0 + 0.45 * fouling)
    fan_factor = sp ** 3 * (1.0 + 0.8 * context.get("filter_clogging", 0.0))
    sat_penalty = 1.0 + 0.035 * max(sat - 13.0, 0) ** 2
    estimated_kw = load * 0.19 * cooling_factor * sat_penalty + 35.0 * fan_factor + 3.0

    predicted_zone = avg_zone + 0.45 * reset + 0.16 * (sat - 13.0) + 0.0015 * load
    comfort_dev = max(0.0, predicted_zone - (bms.occupied_cooling_setpoint_C + 1.0)) * occupancy
    predicted_co2 = avg_co2 + 700.0 * occupancy * max(0.0, 0.18 - oa)
    iaq_violation = max(0.0, predicted_co2 - bms.co2_limit_ppm) / 200.0
    demand_violation = max(0.0, estimated_kw - bms.demand_limit_kW) / max(bms.demand_limit_kW, 1.0)

    return (
        estimated_kw
        + bms.comfort_weight * 25.0 * comfort_dev ** 2
        + bms.iaq_weight * 20.0 * iaq_violation ** 2
        + bms.demand_weight * 100.0 * demand_violation ** 2
    )


def optimize_action_apo(context: Dict[str, float], bms: BMSConfig, seed_offset: int = 0) -> ControlAction:
    """Compact APO-inspired stochastic supervisory optimizer.

    The population alternates between exploration around random peers and
    exploitation around the best solution. It is intentionally lightweight so
    it can be used inside an interactive BMS simulation.
    """
    rng = np.random.default_rng(bms.random_seed + seed_offset)
    lower = np.array([11.5, 5.5, 0.35, 0.0, 0.10])
    upper = np.array([16.0, 9.0, 1.00, 2.0, 0.35])
    n = max(8, int(bms.optimizer_population))
    iters = max(3, int(bms.optimizer_iterations))
    pop = rng.uniform(lower, upper, size=(n, 5))
    scores = np.array([_candidate_objective(x, context, bms) for x in pop])

    for t in range(iters):
        order = np.argsort(scores)
        pop, scores = pop[order], scores[order]
        best = pop[0].copy()
        progress = (t + 1) / iters
        new_pop = pop.copy()
        for i in range(1, n):
            peer = pop[rng.integers(0, max(2, n // 2))]
            if rng.random() < 0.5 * (1.0 - progress) + 0.15:
                step = rng.normal(0, 0.35, 5) * (peer - pop[i]) + rng.normal(0, 0.08, 5) * (upper - lower)
            else:
                step = rng.uniform(0.15, 0.85, 5) * (best - pop[i]) + rng.normal(0, 0.04, 5) * (upper - lower)
            trial = np.clip(pop[i] + step, lower, upper)
            score = _candidate_objective(trial, context, bms)
            if score < scores[i]:
                new_pop[i] = trial
                scores[i] = score
        pop = new_pop
        scores = np.array([_candidate_objective(x, context, bms) for x in pop])

    best_idx = int(np.argmin(scores))
    sat, chws, sp, reset, oa = pop[best_idx]
    return ControlAction(
        supply_air_temp_C=float(sat),
        chilled_water_supply_C=float(chws),
        static_pressure_fraction=float(sp),
        cooling_setpoint_reset_C=float(reset),
        outdoor_air_fraction=float(oa),
        demand_response=bool(context.get("previous_total_power_kW", 0.0) > bms.demand_limit_kW),
        optimizer_objective=float(scores[best_idx]),
    )
