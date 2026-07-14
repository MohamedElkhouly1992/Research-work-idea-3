from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np

from .config import BMSConfig, FaultConfig


@dataclass
class DegradationState:
    filter_clogging: float
    coil_fouling: float
    chiller_fouling: float
    last_maintenance_day: int = -10_000

    @property
    def index(self) -> float:
        return float(np.mean([self.filter_clogging, self.coil_fouling, self.chiller_fouling]))


def initial_degradation(faults: FaultConfig) -> DegradationState:
    return DegradationState(
        filter_clogging=float(np.clip(faults.filter_clogging_initial, 0, 1)),
        coil_fouling=float(np.clip(faults.coil_fouling_initial, 0, 1)),
        chiller_fouling=float(np.clip(faults.chiller_fouling_initial, 0, 1)),
    )


def advance_degradation(state: DegradationState, faults: FaultConfig, dt_days: float) -> None:
    state.filter_clogging = float(np.clip(state.filter_clogging + faults.filter_clogging_growth_per_day * dt_days, 0, 1))
    state.coil_fouling = float(np.clip(state.coil_fouling + faults.coil_fouling_growth_per_day * dt_days, 0, 1))
    state.chiller_fouling = float(np.clip(state.chiller_fouling + faults.chiller_fouling_growth_per_day * dt_days, 0, 1))


def maybe_maintain(state: DegradationState, bms: BMSConfig, day_index: int) -> Optional[str]:
    if not bms.maintenance_enabled:
        return None
    due = day_index - state.last_maintenance_day >= bms.maintenance_min_interval_days
    if due and max(state.filter_clogging, state.coil_fouling, state.chiller_fouling) >= bms.maintenance_threshold:
        recovery = float(np.clip(bms.maintenance_recovery, 0, 1))
        state.filter_clogging *= (1.0 - recovery)
        state.coil_fouling *= (1.0 - recovery)
        state.chiller_fouling *= (1.0 - recovery)
        state.last_maintenance_day = day_index
        return "Condition-based maintenance executed; degradation states partially restored."
    return None


def generate_alarms(
    timestamp,
    total_power_kW: float,
    avg_zone_temp_C: float,
    max_comfort_dev_C: float,
    avg_co2_ppm: float,
    degradation: DegradationState,
    bms: BMSConfig,
    plant_cop: float,
    maintenance_message: Optional[str] = None,
) -> List[Dict[str, object]]:
    alarms: List[Dict[str, object]] = []
    def add(code: str, severity: str, message: str, value: float | None = None):
        alarms.append({"timestamp": timestamp, "code": code, "severity": severity, "message": message, "value": value})

    if total_power_kW > bms.demand_limit_kW:
        add("BMS-DEMAND-HIGH", "High", "Electrical demand exceeded the configured limit.", total_power_kW)
    if max_comfort_dev_C > 1.5:
        add("BMS-COMFORT", "Medium", "Occupied-zone comfort deviation exceeded 1.5 C.", max_comfort_dev_C)
    if avg_co2_ppm > bms.co2_limit_ppm:
        add("BMS-IAQ-CO2", "High", "Average occupied-zone CO2 exceeded the configured limit.", avg_co2_ppm)
    if degradation.filter_clogging > 0.55:
        add("FDD-FILTER-DP", "Medium", "Filter clogging index indicates elevated fan pressure loss.", degradation.filter_clogging)
    if degradation.coil_fouling > 0.55:
        add("FDD-COIL-UA", "Medium", "Cooling-coil fouling index indicates reduced heat-transfer effectiveness.", degradation.coil_fouling)
    if degradation.chiller_fouling > 0.55 or (plant_cop < 3.0 and total_power_kW > 30):
        add("FDD-CHILLER-EFF", "High", "Chiller efficiency is below the expected operating range.", plant_cop)
    if avg_zone_temp_C > 29.0:
        add("BMS-ZONE-HOT", "High", "Average zone temperature is excessive.", avg_zone_temp_C)
    if maintenance_message:
        add("MAINT-ACTION", "Info", maintenance_message, degradation.index)
    return alarms
