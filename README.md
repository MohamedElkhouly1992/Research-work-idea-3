> **Streamlit Cloud:** deploy the complete repository and set the main file to `streamlit_app.py`. See `DEPLOY_STREAMLIT_CLOUD.md`. Uploading only `app.py` causes `ModuleNotFoundError: No module named 'hvac_bms'`.

# HVAC–BMS Building Digital Twin

A deployable, research-oriented **reduced-order simulation system** for a multi-zone building served by central air-conditioning and a Building Management System (BMS).

## Included simulation layers

1. **Building and zones**
   - Multi-zone 1R1C sensible heat balance
   - Occupancy, lighting, equipment, solar, envelope, and infiltration loads
   - Zone humidity and CO₂ mass-balance approximations
   - Zone-level VAV airflow, cooling/heating delivery, comfort deviation, and IAQ

2. **Air-side HVAC**
   - Multiple AHUs and zone-to-AHU assignment
   - Supply-air temperature control
   - Outdoor-air/economizer fraction
   - Fan power from airflow and static pressure
   - Filter clogging pressure-loss effect
   - Cooling-coil fouling effect

3. **Central plant**
   - Chiller capacity, part-load ratio, COP, lift, and fouling
   - Chilled-water and condenser pumps
   - Cooling tower
   - Boiler/heating input and auxiliary power

4. **BMS control strategies**
   - **S0:** fixed conventional control
   - **S1:** schedule and setpoint reset
   - **S2:** fault-aware supervisory control
   - **S3:** APO-inspired stochastic supervisory optimization
   - Demand limit, temperature/IAQ weights, control interval, and condition-based maintenance

5. **Faults, degradation, and FDD**
   - Filter clogging
   - Cooling-coil fouling
   - Chiller fouling
   - Zone/outdoor/supply temperature sensor biases
   - Outdoor-air damper stuck position
   - Comfort, demand, CO₂, filter, coil, and chiller alarms
   - Degradation-triggered maintenance with recovery and minimum interval

6. **Outputs**
   - Interactive Streamlit dashboard
   - Building, plant, AHU, and zone time series
   - KPI summary, alarm/event log, energy, cost, carbon, COP, comfort, IAQ, and degradation
   - Excel workbook export
   - PDF summary report
   - 300-dpi journal figure package
   - CSV exports and JSON configuration

## Run locally

### Windows

Double-click `run_local.bat`, or run:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

### Linux/macOS

```bash
chmod +x run_local.sh
./run_local.sh
```

The app opens at `http://localhost:8501`.

## Docker

```bash
docker build -t hvac-bms-digital-twin .
docker run --rm -p 8501:8501 hvac-bms-digital-twin
```

## Weather input

CSV requirements:

| Column | Requirement | Unit |
|---|---:|---:|
| `timestamp` | required | datetime |
| `dry_bulb_C` | required | °C |
| `rel_humidity_pct` | optional | % |
| `solar_W_m2` | optional | W/m² |
| `wind_m_s` | optional | m/s |

When no weather file is uploaded, deterministic hot-climate demonstration weather is generated.

## Zone table

The in-app editor exposes all zone parameters. A minimum imported zone CSV needs `name`, `area_m2`, and `ahu`; omitted fields use default values. See `sample_data/zones_template.csv`.

## DesignBuilder / EnergyPlus validation workflow

This software is a reduced-order digital twin, not a replacement for a detailed whole-building engine. For manuscript-grade validation:

1. Export hourly or sub-hourly DesignBuilder/EnergyPlus results for outdoor conditions, zone temperatures, zone loads, airflow, chiller electricity, fan electricity, pump electricity, and total HVAC electricity.
2. Match geometry, envelope, schedules, internal gains, ventilation, HVAC capacity/COP, weather, and timestep.
3. Run the clean case first, then identical fault/degradation cases.
4. Compare CVRMSE, NMBE, MAPE, peak-demand error, daily energy, monthly energy, zone-temperature error, and component energy.
5. Calibrate uncertain parameters such as zone capacitance, UA, infiltration, equipment schedules, fan pressure, and part-load COP.

## Important scientific limitation

The equations are intentionally compact and interpretable for supervisory-control, degradation, maintenance, and optimization studies. Formal publication claims should be supported by calibration against field measurements or an EnergyPlus/DesignBuilder reference model and by uncertainty/sensitivity analysis.

## Test

```bash
pytest -q
```

## Comparative S0-S3 benchmark

The **Benchmark** tab executes the same scenario under S0, S1, S2, and S3 and reports energy, peak demand, COP, discomfort, CO2, cost, carbon, alarms, and energy saving relative to S0.

## Reference validation

The **Validation** tab compares matching simulator/reference columns by timestamp and calculates RMSE, MAE, MAPE, CVRMSE, NMBE, and R2.

## Optional CatBoost surrogate

Install the ML extension:

```bash
pip install -r requirements-ml.txt
```

Train from an exported `building_timeseries.csv`:

```bash
python train_catboost_surrogate.py --input building_timeseries.csv --output_dir surrogate_model
```

The script trains separate surrogate models for electric power, cooling load, COP, and comfort deviation. If CatBoost is unavailable, it falls back to Extra Trees.
