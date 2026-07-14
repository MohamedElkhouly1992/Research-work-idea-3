from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


@dataclass
class ZoneConfig:
    name: str
    area_m2: float
    height_m: float = 3.2
    ua_W_K: float = 900.0
    thermal_capacitance_kJ_K: float = 90_000.0
    max_occupancy: int = 40
    people_sensible_W: float = 75.0
    people_latent_W: float = 55.0
    lighting_W_m2: float = 9.0
    equipment_W_m2: float = 12.0
    infiltration_ach: float = 0.25
    window_area_m2: float = 30.0
    solar_gain_factor: float = 0.35
    cooling_setpoint_C: float = 24.0
    heating_setpoint_C: float = 20.0
    deadband_C: float = 1.0
    min_airflow_m3_s: float = 0.20
    max_airflow_m3_s: float = 2.20
    ahu: str = "AHU-1"
    occupancy_start_hour: float = 8.0
    occupancy_end_hour: float = 17.0
    weekday_only: bool = True


@dataclass
class AHUConfig:
    name: str
    design_airflow_m3_s: float = 12.0
    fan_efficiency: float = 0.68
    motor_efficiency: float = 0.92
    design_static_pressure_Pa: float = 850.0
    supply_air_temp_C: float = 13.0
    min_outdoor_air_fraction: float = 0.15
    economizer_enabled: bool = True
    heat_recovery_efficiency: float = 0.0


@dataclass
class PlantConfig:
    chiller_capacity_kW: float = 1000.0
    chiller_reference_COP: float = 5.5
    chilled_water_supply_C: float = 6.5
    chilled_water_deltaT_K: float = 5.0
    chilled_water_pump_design_kW: float = 22.0
    condenser_pump_design_kW: float = 18.0
    cooling_tower_design_kW: float = 16.0
    boiler_capacity_kW: float = 450.0
    boiler_efficiency: float = 0.90
    heating_pump_design_kW: float = 8.0
    auxiliary_base_kW: float = 2.0


@dataclass
class BMSConfig:
    strategy: str = "S3"
    occupied_cooling_setpoint_C: float = 24.0
    unoccupied_cooling_setpoint_C: float = 29.0
    occupied_heating_setpoint_C: float = 20.0
    unoccupied_heating_setpoint_C: float = 16.0
    optimal_start_enabled: bool = True
    demand_limit_kW: float = 900.0
    control_interval_minutes: int = 60
    co2_limit_ppm: float = 1000.0
    comfort_weight: float = 8.0
    iaq_weight: float = 2.0
    demand_weight: float = 4.0
    optimizer_population: int = 18
    optimizer_iterations: int = 10
    random_seed: int = 42
    maintenance_enabled: bool = True
    maintenance_threshold: float = 0.70
    maintenance_recovery: float = 0.85
    maintenance_min_interval_days: int = 30
    electricity_price_usd_kWh: float = 0.12
    grid_emission_kgCO2_kWh: float = 0.45


@dataclass
class FaultConfig:
    filter_clogging_initial: float = 0.05
    filter_clogging_growth_per_day: float = 0.0015
    coil_fouling_initial: float = 0.04
    coil_fouling_growth_per_day: float = 0.0008
    chiller_fouling_initial: float = 0.03
    chiller_fouling_growth_per_day: float = 0.0005
    supply_air_temp_sensor_bias_C: float = 0.0
    outdoor_air_temp_sensor_bias_C: float = 0.0
    zone_temp_sensor_bias_C: float = 0.0
    outdoor_damper_stuck_fraction: float = -1.0


@dataclass
class SimulationConfig:
    building_name: str = "Educational Building HVAC-BMS Digital Twin"
    location: str = "New Mansoura, Egypt"
    floor_area_m2: float = 18_000.0
    start: str = "2026-07-01 00:00:00"
    days: int = 7
    timestep_minutes: int = 15
    initial_zone_temp_C: float = 27.0
    initial_zone_rh_pct: float = 50.0
    zones: List[ZoneConfig] = field(default_factory=list)
    ahus: List[AHUConfig] = field(default_factory=list)
    plant: PlantConfig = field(default_factory=PlantConfig)
    bms: BMSConfig = field(default_factory=BMSConfig)
    faults: FaultConfig = field(default_factory=FaultConfig)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SimulationConfig":
        zones = [ZoneConfig(**z) for z in data.get("zones", [])]
        ahus = [AHUConfig(**a) for a in data.get("ahus", [])]
        plant = PlantConfig(**data.get("plant", {}))
        bms = BMSConfig(**data.get("bms", {}))
        faults = FaultConfig(**data.get("faults", {}))
        kwargs = {k: v for k, v in data.items() if k not in {"zones", "ahus", "plant", "bms", "faults"}}
        return cls(zones=zones, ahus=ahus, plant=plant, bms=bms, faults=faults, **kwargs)


def default_config() -> SimulationConfig:
    zones = [
        ZoneConfig("Lecture Hall A", 850, ua_W_K=1450, thermal_capacitance_kJ_K=150_000, max_occupancy=180,
                   equipment_W_m2=6, window_area_m2=85, min_airflow_m3_s=0.8, max_airflow_m3_s=5.0, ahu="AHU-1"),
        ZoneConfig("Lecture Hall B", 760, ua_W_K=1320, thermal_capacitance_kJ_K=135_000, max_occupancy=150,
                   equipment_W_m2=6, window_area_m2=75, min_airflow_m3_s=0.7, max_airflow_m3_s=4.5, ahu="AHU-1"),
        ZoneConfig("Laboratories", 1100, ua_W_K=1900, thermal_capacitance_kJ_K=190_000, max_occupancy=120,
                   equipment_W_m2=25, lighting_W_m2=11, window_area_m2=95, min_airflow_m3_s=1.2, max_airflow_m3_s=6.0, ahu="AHU-2"),
        ZoneConfig("Faculty Offices", 900, ua_W_K=1250, thermal_capacitance_kJ_K=170_000, max_occupancy=90,
                   equipment_W_m2=14, window_area_m2=100, min_airflow_m3_s=0.6, max_airflow_m3_s=4.0, ahu="AHU-2"),
        ZoneConfig("Administration", 650, ua_W_K=980, thermal_capacitance_kJ_K=125_000, max_occupancy=65,
                   equipment_W_m2=13, window_area_m2=70, min_airflow_m3_s=0.45, max_airflow_m3_s=3.2, ahu="AHU-3"),
        ZoneConfig("Library", 1250, ua_W_K=1780, thermal_capacitance_kJ_K=225_000, max_occupancy=160,
                   equipment_W_m2=9, lighting_W_m2=10, window_area_m2=110, min_airflow_m3_s=1.0, max_airflow_m3_s=5.5, ahu="AHU-3", occupancy_end_hour=20),
    ]
    ahus = [
        AHUConfig("AHU-1", design_airflow_m3_s=10.0),
        AHUConfig("AHU-2", design_airflow_m3_s=11.0),
        AHUConfig("AHU-3", design_airflow_m3_s=10.0),
    ]
    return SimulationConfig(zones=zones, ahus=ahus)
