from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .config import SimulationConfig
from .controls import ControlAction, baseline_action, optimize_action_apo
from .faults import advance_degradation, generate_alarms, initial_degradation, maybe_maintain
from .models import ZoneState, ahu_power, occupancy_fraction, plant_power, simulate_zone_step
from .weather import normalize_weather


@dataclass
class SimulationResult:
    summary: pd.DataFrame
    timeseries: pd.DataFrame
    zones: pd.DataFrame
    ahus: pd.DataFrame
    alarms: pd.DataFrame
    config: SimulationConfig


def _specific_humidity_to_rh(temp_c: float, w: float) -> float:
    p_w = w * 101.325 / max(0.62198 + w, 1e-6)
    p_ws = 0.61078 * np.exp((17.2694 * temp_c) / (temp_c + 237.3))
    return float(np.clip(100 * p_w / max(p_ws, 1e-6), 1, 100))


def run_simulation(config: SimulationConfig, weather: Optional[pd.DataFrame] = None, progress_callback=None) -> SimulationResult:
    if not config.zones:
        raise ValueError("At least one thermal zone is required.")
    if not config.ahus:
        raise ValueError("At least one AHU is required.")
    if config.timestep_minutes <= 0 or config.days <= 0:
        raise ValueError("Simulation days and timestep must be positive.")

    weather_df = normalize_weather(weather, config.start, config.days, config.timestep_minutes)
    dt_s = config.timestep_minutes * 60.0
    dt_h = config.timestep_minutes / 60.0
    dt_days = dt_h / 24.0
    zones_by_ahu = {ahu.name: [z for z in config.zones if z.ahu == ahu.name] for ahu in config.ahus}
    states = {z.name: ZoneState(config.initial_zone_temp_C, 0.010, 500.0) for z in config.zones}
    degradation = initial_degradation(config.faults)

    global_rows: List[Dict[str, object]] = []
    zone_rows: List[Dict[str, object]] = []
    ahu_rows: List[Dict[str, object]] = []
    alarm_rows: List[Dict[str, object]] = []
    previous_total_power = 0.0
    last_action: Optional[ControlAction] = None
    control_steps = max(1, int(config.bms.control_interval_minutes / config.timestep_minutes))

    for k, wr in weather_df.iterrows():
        ts = pd.Timestamp(wr["timestamp"])
        weather_rec = wr.to_dict()
        occ = {z.name: occupancy_fraction(z, ts) for z in config.zones}
        occupied = any(v > 0.05 for v in occ.values())
        avg_temp_before = float(np.mean([s.temperature_C for s in states.values()]))
        avg_co2_before = float(np.mean([s.co2_ppm for s in states.values()]))
        load_proxy = sum(max(0.0, wr["dry_bulb_C"] - z.cooling_setpoint_C) * z.ua_W_K / 1000 for z in config.zones)
        context = {
            "outdoor_temp_C": float(wr["dry_bulb_C"] + config.faults.outdoor_air_temp_sensor_bias_C),
            "avg_zone_temp_C": avg_temp_before,
            "avg_co2_ppm": avg_co2_before,
            "occupancy_fraction": float(np.mean(list(occ.values()))),
            "load_proxy_kW": float(load_proxy + sum(z.area_m2 * z.equipment_W_m2 / 1000 * occ[z.name] for z in config.zones)),
            "degradation_index": degradation.index,
            "filter_clogging": degradation.filter_clogging,
            "previous_total_power_kW": previous_total_power,
        }
        if last_action is None or k % control_steps == 0:
            if config.bms.strategy.upper() == "S3":
                last_action = optimize_action_apo(context, config.bms, seed_offset=k)
            else:
                last_action = baseline_action(config.bms.strategy, context["outdoor_temp_C"], occupied, config.bms)
                if config.bms.strategy.upper() == "S2":
                    # Fault-aware compensation: recover coil/chiller capacity while limiting fan overreaction.
                    last_action = ControlAction(
                        supply_air_temp_C=float(np.clip(last_action.supply_air_temp_C - 1.2 * degradation.coil_fouling, 11.5, 16.0)),
                        chilled_water_supply_C=float(np.clip(last_action.chilled_water_supply_C - 0.9 * degradation.chiller_fouling, 5.5, 9.0)),
                        static_pressure_fraction=float(np.clip(last_action.static_pressure_fraction + 0.12 * degradation.filter_clogging, 0.35, 1.0)),
                        cooling_setpoint_reset_C=last_action.cooling_setpoint_reset_C,
                        outdoor_air_fraction=last_action.outdoor_air_fraction,
                        demand_response=last_action.demand_response,
                        optimizer_objective=last_action.optimizer_objective,
                    )
        action = last_action

        if config.faults.outdoor_damper_stuck_fraction >= 0:
            action = ControlAction(
                action.supply_air_temp_C, action.chilled_water_supply_C, action.static_pressure_fraction,
                action.cooling_setpoint_reset_C, float(np.clip(config.faults.outdoor_damper_stuck_fraction, 0, 1)),
                action.demand_response, action.optimizer_objective,
            )

        # A positive sensor bias means the sensor reports warmer than actual; therefore
        # the physical supply temperature settles below the commanded setpoint.
        physical_action = ControlAction(
            supply_air_temp_C=action.supply_air_temp_C - config.faults.supply_air_temp_sensor_bias_C,
            chilled_water_supply_C=action.chilled_water_supply_C,
            static_pressure_fraction=action.static_pressure_fraction,
            cooling_setpoint_reset_C=action.cooling_setpoint_reset_C,
            outdoor_air_fraction=action.outdoor_air_fraction,
            demand_response=action.demand_response,
            optimizer_objective=action.optimizer_objective,
        )

        current_zone_metrics: Dict[str, Dict[str, float]] = {}
        for z in config.zones:
            new_state, metrics = simulate_zone_step(
                z, states[z.name], weather_rec, physical_action, dt_s, occ[z.name],
                degradation.coil_fouling, degradation.filter_clogging, config.faults.zone_temp_sensor_bias_C,
            )
            states[z.name] = new_state
            current_zone_metrics[z.name] = metrics
            zone_rows.append({
                "timestamp": ts, "zone": z.name, "ahu": z.ahu,
                "temperature_C": new_state.temperature_C,
                "relative_humidity_pct": _specific_humidity_to_rh(new_state.temperature_C, new_state.humidity_ratio_kg_kg),
                "co2_ppm": new_state.co2_ppm,
                **metrics,
            })

        total_fan_kW = 0.0
        total_coil_load_kW = 0.0
        for ahu in config.ahus:
            azones = zones_by_ahu.get(ahu.name, [])
            if not azones:
                continue
            airflow = sum(current_zone_metrics[z.name]["airflow_m3_s"] for z in azones)
            return_t = float(np.average([states[z.name].temperature_C for z in azones], weights=[max(z.area_m2, 1) for z in azones]))
            oa = action.outdoor_air_fraction
            mixed_t = oa * float(wr["dry_bulb_C"]) + (1 - oa) * return_t
            am = ahu_power(ahu, airflow, physical_action, degradation.filter_clogging, mixed_t, return_t)
            total_fan_kW += am["fan_power_kW"]
            total_coil_load_kW += max(am["coil_sensible_load_kW"], sum(current_zone_metrics[z.name]["cooling_delivered_kW"] for z in azones))
            ahu_rows.append({"timestamp": ts, "ahu": ahu.name, **am, "supply_air_temp_C": action.supply_air_temp_C, "outdoor_air_fraction": oa})

        heating_load_kW = sum(m["heating_delivered_kW"] for m in current_zone_metrics.values())
        pp = plant_power(config.plant, total_coil_load_kW, heating_load_kW, float(wr["dry_bulb_C"]), physical_action, degradation.chiller_fouling)
        total_power_kW = total_fan_kW + pp["chiller_power_kW"] + pp["chw_pump_power_kW"] + pp["condenser_pump_power_kW"] + pp["cooling_tower_power_kW"] + pp["heating_pump_power_kW"] + pp["auxiliary_power_kW"]
        total_site_energy_kW = total_power_kW + pp["boiler_input_kW"]
        avg_zone_temp = float(np.mean([s.temperature_C for s in states.values()]))
        avg_zone_rh = float(np.mean([_specific_humidity_to_rh(s.temperature_C, s.humidity_ratio_kg_kg) for s in states.values()]))
        avg_co2 = float(np.mean([s.co2_ppm for s in states.values()]))
        max_comfort = float(max(m["comfort_deviation_C"] for m in current_zone_metrics.values()))
        occupied_discomfort = float(np.mean([m["comfort_deviation_C"] > 0 for m in current_zone_metrics.values() if m["occupancy_fraction"] > 0])) if any(m["occupancy_fraction"] > 0 for m in current_zone_metrics.values()) else 0.0

        day_idx = int((ts - pd.Timestamp(weather_df.iloc[0]["timestamp"])).total_seconds() // 86400)
        maintenance_message = maybe_maintain(degradation, config.bms, day_idx)
        alarms = generate_alarms(ts, total_power_kW, avg_zone_temp, max_comfort, avg_co2, degradation, config.bms, pp["chiller_COP"], maintenance_message)
        alarm_rows.extend(alarms)

        global_rows.append({
            "timestamp": ts,
            "outdoor_temp_C": float(wr["dry_bulb_C"]),
            "outdoor_rh_pct": float(wr["rel_humidity_pct"]),
            "solar_W_m2": float(wr["solar_W_m2"]),
            "average_zone_temp_C": avg_zone_temp,
            "average_zone_rh_pct": avg_zone_rh,
            "average_co2_ppm": avg_co2,
            "max_comfort_deviation_C": max_comfort,
            "occupied_discomfort_fraction": occupied_discomfort,
            "supply_air_temp_setpoint_C": action.supply_air_temp_C,
            "chilled_water_supply_setpoint_C": action.chilled_water_supply_C,
            "static_pressure_fraction": action.static_pressure_fraction,
            "zone_setpoint_reset_C": action.cooling_setpoint_reset_C,
            "outdoor_air_fraction": action.outdoor_air_fraction,
            "optimizer_objective": action.optimizer_objective,
            "cooling_load_kW": pp["cooling_load_kW"],
            "heating_load_kW": pp["heating_load_kW"],
            "chiller_COP": pp["chiller_COP"],
            "chiller_power_kW": pp["chiller_power_kW"],
            "fan_power_kW": total_fan_kW,
            "pump_power_kW": pp["chw_pump_power_kW"] + pp["condenser_pump_power_kW"] + pp["heating_pump_power_kW"],
            "cooling_tower_power_kW": pp["cooling_tower_power_kW"],
            "auxiliary_power_kW": pp["auxiliary_power_kW"],
            "boiler_input_kW": pp["boiler_input_kW"],
            "electric_power_kW": total_power_kW,
            "site_energy_rate_kW": total_site_energy_kW,
            "filter_clogging": degradation.filter_clogging,
            "coil_fouling": degradation.coil_fouling,
            "chiller_fouling": degradation.chiller_fouling,
            "degradation_index": degradation.index,
            "active_alarm_count": len(alarms),
        })
        previous_total_power = total_power_kW
        advance_degradation(degradation, config.faults, dt_days)
        if progress_callback and (k % max(1, len(weather_df) // 100) == 0 or k == len(weather_df) - 1):
            progress_callback((k + 1) / len(weather_df))

    ts_df = pd.DataFrame(global_rows)
    zone_df = pd.DataFrame(zone_rows)
    ahu_df = pd.DataFrame(ahu_rows)
    alarms_df = pd.DataFrame(alarm_rows, columns=["timestamp", "code", "severity", "message", "value"])

    electric_kWh = float((ts_df["electric_power_kW"] * dt_h).sum())
    boiler_kWh = float((ts_df["boiler_input_kW"] * dt_h).sum())
    peak_kW = float(ts_df["electric_power_kW"].max())
    comfort_hours = float((zone_df["comfort_deviation_C"] * zone_df["occupancy_fraction"] * dt_h).sum())
    occupied_zone_hours = float((zone_df["occupancy_fraction"] * dt_h).sum())
    discomfort_zone_hours = float(((zone_df["comfort_deviation_C"] > 0).astype(float) * (zone_df["occupancy_fraction"] > 0).astype(float) * dt_h).sum())
    summary = pd.DataFrame([
        {"KPI": "Simulation strategy", "Value": config.bms.strategy.upper(), "Unit": "-"},
        {"KPI": "Simulation duration", "Value": config.days, "Unit": "days"},
        {"KPI": "Electric HVAC energy", "Value": electric_kWh, "Unit": "kWh"},
        {"KPI": "Thermal/boiler input", "Value": boiler_kWh, "Unit": "kWh"},
        {"KPI": "Peak electric demand", "Value": peak_kW, "Unit": "kW"},
        {"KPI": "Average chiller COP", "Value": float(ts_df.loc[ts_df["chiller_power_kW"] > 0, "chiller_COP"].mean() if (ts_df["chiller_power_kW"] > 0).any() else 0), "Unit": "-"},
        {"KPI": "Comfort-degree hours", "Value": comfort_hours, "Unit": "C.h"},
        {"KPI": "Occupied discomfort ratio", "Value": 100 * discomfort_zone_hours / max(occupied_zone_hours, 1e-9), "Unit": "%"},
        {"KPI": "Maximum average CO2", "Value": float(ts_df["average_co2_ppm"].max()), "Unit": "ppm"},
        {"KPI": "Electricity cost", "Value": electric_kWh * config.bms.electricity_price_usd_kWh, "Unit": "USD"},
        {"KPI": "Operational carbon", "Value": electric_kWh * config.bms.grid_emission_kgCO2_kWh, "Unit": "kgCO2"},
        {"KPI": "Alarm events", "Value": int(len(alarms_df)), "Unit": "events"},
        {"KPI": "Final degradation index", "Value": float(ts_df["degradation_index"].iloc[-1]), "Unit": "0-1"},
    ])
    return SimulationResult(summary, ts_df, zone_df, ahu_df, alarms_df, config)
