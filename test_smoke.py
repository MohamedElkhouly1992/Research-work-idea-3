from hvac_bms.config import default_config
from hvac_bms.simulator import run_simulation


def test_short_simulation_runs():
    cfg = default_config()
    cfg.days = 1
    cfg.timestep_minutes = 60
    cfg.bms.optimizer_population = 8
    cfg.bms.optimizer_iterations = 3
    result = run_simulation(cfg)
    assert len(result.timeseries) == 24
    assert not result.summary.empty
    assert result.timeseries["electric_power_kW"].ge(0).all()
    assert result.zones["temperature_C"].between(10, 45).all()
