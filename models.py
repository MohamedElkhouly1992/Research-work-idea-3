from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

import numpy as np

from .config import AHUConfig, PlantConfig, ZoneConfig
from .controls import ControlAction

AIR_DENSITY = 1.20
AIR_CP_KJ_KG_K = 1.006
H_FG_KJ_KG = 2450.0


@dataclass
class ZoneState:
    temperature_C: float
    humidity_ratio_kg_kg: float
    co2_ppm: float = 500.0


def occupancy_fraction(zone: ZoneConfig, timestamp) -> float:
    if zone.weekday_only and timestamp.weekday() >= 5:
        return 0.0
    hour = timestamp.hour + timestamp.minute / 60.0
    if zone.occupancy_start_hour <= hour < zone.occupancy_end_hour:
        ramp = min((hour - zone.occupancy_start_hour) / 0.75, 1.0)
        ramp_down = min((zone.occupancy_end_hour - hour) / 0.75, 1.0)
        return float(np.clip(min(ramp, ramp_down) * (0.85 + 0.15 * np.sin(np.pi * (hour - zone.occupancy_start_hour) / max(zone.occupancy_end_hour-zone.occupancy_start_hour, 1))), 0, 1))
    return 0.0


def simulate_zone_step(
    zone: ZoneConfig,
    state: ZoneState,
    weather: Dict[str, float],
    action: ControlAction,
    dt_seconds: float,
    occupied_fraction: float,
    coil_fouling: float,
    filter_clogging: float,
    zone_sensor_bias_C: float,
) -> Tuple[ZoneState, Dict[str, float]]:
    t_out = float(weather["dry_bulb_C"])
    w_out = float(weather["humidity_ratio_kg_kg"])
    solar = float(weather["solar_W_m2"])
    measured_t = state.temperature_C + zone_sensor_bias_C

    cooling_sp = zone.cooling_setpoint_C + action.cooling_setpoint_reset_C
    heating_sp = zone.heating_setpoint_C
    people = zone.max_occupancy * occupied_fraction
    sensible_internal_W = people * zone.people_sensible_W + zone.area_m2 * (
        zone.lighting_W_m2 * occupied_fraction + zone.equipment_W_m2 * (0.25 + 0.75 * occupied_fraction)
    )
    latent_internal_W = people * zone.people_latent_W
    solar_W = zone.window_area_m2 * solar * zone.solar_gain_factor
    volume_m3 = zone.area_m2 * zone.height_m
    infiltration_m3_s = zone.infiltration_ach * volume_m3 / 3600.0 * (0.65 + 0.35 * min(float(weather.get("wind_m_s", 2.0)) / 4.0, 1.5))
    infiltration_W = AIR_DENSITY * infiltration_m3_s * AIR_CP_KJ_KG_K * 1000 * (t_out - state.temperature_C)
    envelope_W = zone.ua_W_K * (t_out - state.temperature_C)
    non_hvac_W = sensible_internal_W + solar_W + infiltration_W + envelope_W

    ideal_cooling_W = max(0.0, non_hvac_W + (measured_t - cooling_sp) * zone.thermal_capacitance_kJ_K * 1000 / max(dt_seconds, 1))
    ideal_heating_W = max(0.0, -non_hvac_W + (heating_sp - measured_t) * zone.thermal_capacitance_kJ_K * 1000 / max(dt_seconds, 1))

    sat_effective = action.supply_air_temp_C + 3.0 * coil_fouling
    delta_t = max(measured_t - sat_effective, 1.5)
    requested_airflow = ideal_cooling_W / (AIR_DENSITY * AIR_CP_KJ_KG_K * 1000 * delta_t) if ideal_cooling_W > 0 else zone.min_airflow_m3_s
    requested_airflow *= 1.0 + 0.15 * filter_clogging
    airflow = float(np.clip(requested_airflow, zone.min_airflow_m3_s, zone.max_airflow_m3_s))
    cooling_delivered_W = max(0.0, AIR_DENSITY * airflow * AIR_CP_KJ_KG_K * 1000 * (state.temperature_C - sat_effective))
    cooling_delivered_W = min(cooling_delivered_W, ideal_cooling_W * 1.15 + 500.0)
    heating_delivered_W = min(ideal_heating_W, 35_000.0)

    net_W = non_hvac_W - cooling_delivered_W + heating_delivered_W
    t_new = state.temperature_C + net_W * dt_seconds / (zone.thermal_capacitance_kJ_K * 1000)
    t_new = float(np.clip(t_new, 10.0, 45.0))

    moisture_in_kg_s = AIR_DENSITY * infiltration_m3_s * (w_out - state.humidity_ratio_kg_kg)
    latent_kg_s = latent_internal_W / (H_FG_KJ_KG * 1000)
    dehumidification_kg_s = max(0.0, cooling_delivered_W * 0.22 / (H_FG_KJ_KG * 1000))
    air_mass = AIR_DENSITY * volume_m3
    w_new = state.humidity_ratio_kg_kg + (moisture_in_kg_s + latent_kg_s - dehumidification_kg_s) * dt_seconds / max(air_mass, 1.0)
    w_new = float(np.clip(w_new, 0.003, 0.030))

    oa_per_person_m3_s = 0.008
    outdoor_airflow = max(zone.min_airflow_m3_s * action.outdoor_air_fraction, people * oa_per_person_m3_s)
    co2_generation_ppm_m3_s = people * 5.0e-6 * 1e6 / max(volume_m3, 1)
    ventilation_decay = outdoor_airflow / max(volume_m3, 1)
    co2_new = state.co2_ppm + dt_seconds * (co2_generation_ppm_m3_s - ventilation_decay * (state.co2_ppm - 420.0))
    co2_new = float(np.clip(co2_new, 400.0, 5000.0))

    comfort_dev = 0.0
    if occupied_fraction > 0:
        if t_new > cooling_sp + zone.deadband_C:
            comfort_dev = t_new - (cooling_sp + zone.deadband_C)
        elif t_new < heating_sp - zone.deadband_C:
            comfort_dev = (heating_sp - zone.deadband_C) - t_new

    return ZoneState(t_new, w_new, co2_new), {
        "occupancy_fraction": occupied_fraction,
        "occupants": people,
        "internal_sensible_kW": sensible_internal_W / 1000,
        "solar_gain_kW": solar_W / 1000,
        "envelope_infiltration_kW": (envelope_W + infiltration_W) / 1000,
        "cooling_demand_kW": ideal_cooling_W / 1000,
        "cooling_delivered_kW": cooling_delivered_W / 1000,
        "heating_delivered_kW": heating_delivered_W / 1000,
        "airflow_m3_s": airflow,
        "outdoor_airflow_m3_s": outdoor_airflow,
        "comfort_deviation_C": comfort_dev,
        "cooling_setpoint_C": cooling_sp,
        "heating_setpoint_C": heating_sp,
    }


def ahu_power(
    ahu: AHUConfig,
    total_airflow_m3_s: float,
    action: ControlAction,
    filter_clogging: float,
    mixed_air_temp_C: float,
    return_air_temp_C: float,
) -> Dict[str, float]:
    flow_frac = float(np.clip(total_airflow_m3_s / max(ahu.design_airflow_m3_s, 0.1), 0.0, 1.35))
    pressure = ahu.design_static_pressure_Pa * action.static_pressure_fraction * (1.0 + 1.3 * filter_clogging)
    fan_kW = total_airflow_m3_s * pressure / max(ahu.fan_efficiency * ahu.motor_efficiency, 0.1) / 1000
    fan_kW = max(fan_kW, 0.0)
    sensible_cooling_kW = max(0.0, AIR_DENSITY * total_airflow_m3_s * AIR_CP_KJ_KG_K * (mixed_air_temp_C - action.supply_air_temp_C))
    return {
        "airflow_m3_s": total_airflow_m3_s,
        "flow_fraction": flow_frac,
        "static_pressure_Pa": pressure,
        "fan_power_kW": fan_kW,
        "coil_sensible_load_kW": sensible_cooling_kW,
        "return_air_temp_C": return_air_temp_C,
        "mixed_air_temp_C": mixed_air_temp_C,
    }


def plant_power(
    plant: PlantConfig,
    cooling_load_kW: float,
    heating_load_kW: float,
    outdoor_temp_C: float,
    action: ControlAction,
    chiller_fouling: float,
) -> Dict[str, float]:
    load = max(cooling_load_kW, 0.0)
    plr = float(np.clip(load / max(plant.chiller_capacity_kW, 1.0), 0.0, 1.2))
    lift_factor = 1.0 + 0.018 * max(outdoor_temp_C - 30.0, -10.0) + 0.035 * (6.5 - action.chilled_water_supply_C)
    part_load_factor = 0.88 + 0.22 * (plr - 0.72) ** 2
    fouling_factor = 1.0 + 0.65 * chiller_fouling
    cop = plant.chiller_reference_COP / max(lift_factor * part_load_factor * fouling_factor, 0.45)
    cop = float(np.clip(cop, 1.5, 8.0))
    chiller_kW = load / cop if load > 0 else 0.0

    pump_frac = float(np.clip(plr ** 0.5, 0.0, 1.0))
    chw_pump_kW = plant.chilled_water_pump_design_kW * pump_frac ** 3
    condenser_pump_kW = plant.condenser_pump_design_kW * pump_frac ** 3
    tower_kW = plant.cooling_tower_design_kW * float(np.clip((outdoor_temp_C - 18.0) / 20.0, 0.15, 1.0)) * pump_frac
    boiler_input_kW = heating_load_kW / max(plant.boiler_efficiency, 0.1) if heating_load_kW > 0 else 0.0
    heating_pump_kW = plant.heating_pump_design_kW * min(heating_load_kW / max(plant.boiler_capacity_kW, 1.0), 1.0) ** 3
    auxiliary_kW = plant.auxiliary_base_kW if load + heating_load_kW > 0 else 0.4

    return {
        "cooling_load_kW": load,
        "heating_load_kW": heating_load_kW,
        "part_load_ratio": plr,
        "chiller_COP": cop,
        "chiller_power_kW": chiller_kW,
        "chw_pump_power_kW": chw_pump_kW,
        "condenser_pump_power_kW": condenser_pump_kW,
        "cooling_tower_power_kW": tower_kW,
        "boiler_input_kW": boiler_input_kW,
        "heating_pump_power_kW": heating_pump_kW,
        "auxiliary_power_kW": auxiliary_kW,
    }
