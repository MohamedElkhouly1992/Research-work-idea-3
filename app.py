from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# Streamlit Cloud may launch the entry point from a repository working
# directory that is different from this file's directory. Add all supported
# project layouts explicitly so the bundled ``hvac_bms`` package is importable.
APP_DIR = Path(__file__).resolve().parent
for candidate in (APP_DIR, APP_DIR / "HVAC_BMS_Digital_Twin", APP_DIR / "src"):
    if (candidate / "hvac_bms").is_dir() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

try:
    from hvac_bms.config import SimulationConfig, default_config
    from hvac_bms.io_utils import config_from_json_bytes, zones_from_csv
    from hvac_bms.reporting import excel_bytes, journal_figures_zip, pdf_bytes
    from hvac_bms.simulator import run_simulation
    from hvac_bms.validation import compare_timeseries
except ModuleNotFoundError as exc:
    st.set_page_config(page_title="HVAC-BMS deployment error", page_icon="⚠️")
    st.error(
        "The application code was deployed without the `hvac_bms` package. "
        "Upload the complete repository, including the `hvac_bms/` folder and "
        "its `__init__.py` file, then set the Streamlit main file to "
        "`streamlit_app.py`."
    )
    st.code(
        "Required repository layout:\n"
        "streamlit_app.py\n"
        "app.py\n"
        "requirements.txt\n"
        "runtime.txt\n"
        "hvac_bms/\n"
        "  __init__.py\n"
        "  config.py\n"
        "  simulator.py\n"
        "  ..."
    )
    st.exception(exc)
    st.stop()

st.set_page_config(page_title="HVAC-BMS Digital Twin", page_icon="🏢", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
.block-container {padding-top: 1.2rem; padding-bottom: 2rem;}
[data-testid="stMetricValue"] {font-size: 1.65rem;}
.app-title {font-size: 2.15rem; font-weight: 750; letter-spacing: -0.02em; margin-bottom: 0;}
.app-subtitle {opacity: 0.78; margin-top: 0.15rem; margin-bottom: 1rem;}
.panel {border: 1px solid rgba(127,127,127,.25); border-radius: 12px; padding: .85rem 1rem;}
</style>
""", unsafe_allow_html=True)

if "config" not in st.session_state:
    st.session_state.config = default_config()
if "result" not in st.session_state:
    st.session_state.result = None
if "weather" not in st.session_state:
    st.session_state.weather = None
if "benchmark" not in st.session_state:
    st.session_state.benchmark = None
if "validation_metrics" not in st.session_state:
    st.session_state.validation_metrics = None

cfg: SimulationConfig = st.session_state.config

head1, head2 = st.columns([7, 1])
with head1:
    st.markdown('<div class="app-title">HVAC–BMS Building Digital Twin</div>', unsafe_allow_html=True)
    st.markdown('<div class="app-subtitle">Multi-zone thermal simulation · central chilled-water plant · supervisory control · FDD · degradation · research exports</div>', unsafe_allow_html=True)
with head2:
    with st.popover("⚙ Setup", use_container_width=True):
        uploaded_config = st.file_uploader("Load configuration JSON", type=["json"], key="config_upload")
        if uploaded_config is not None:
            try:
                st.session_state.config = config_from_json_bytes(uploaded_config.getvalue())
                st.success("Configuration loaded.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
        st.download_button("Download current JSON", json.dumps(cfg.to_dict(), indent=2), "hvac_bms_config.json", "application/json", use_container_width=True)
        if st.button("Restore demonstration building", use_container_width=True):
            st.session_state.config = default_config(); st.session_state.result = None; st.rerun()

tabs = st.tabs(["Building", "Zones", "HVAC plant", "BMS & faults", "Weather", "Run", "Dashboard", "Time series", "Alarms", "Benchmark", "Validation", "Downloads"])

with tabs[0]:
    c1, c2, c3 = st.columns(3)
    cfg.building_name = c1.text_input("Building name", cfg.building_name)
    cfg.location = c2.text_input("Location", cfg.location)
    cfg.floor_area_m2 = c3.number_input("Total floor area (m²)", 100.0, 1_000_000.0, float(cfg.floor_area_m2), 100.0)
    c1, c2, c3, c4 = st.columns(4)
    cfg.start = str(c1.text_input("Simulation start", cfg.start))
    cfg.days = int(c2.number_input("Duration (days)", 1, 365, int(cfg.days)))
    cfg.timestep_minutes = int(c3.selectbox("Timestep", [5, 10, 15, 30, 60], index=[5,10,15,30,60].index(cfg.timestep_minutes) if cfg.timestep_minutes in [5,10,15,30,60] else 2))
    cfg.initial_zone_temp_C = float(c4.number_input("Initial zone temperature (°C)", 10.0, 40.0, float(cfg.initial_zone_temp_C), 0.5))
    st.info("This application is a reduced-order digital twin. Use measured or EnergyPlus/DesignBuilder data for calibration and formal validation.")

with tabs[1]:
    zone_df = pd.DataFrame([z.__dict__ for z in cfg.zones])
    edited = st.data_editor(zone_df, use_container_width=True, num_rows="dynamic", height=440, key="zone_editor")
    try:
        cfg.zones = zones_from_csv(edited)
        st.caption(f"Configured zones: {len(cfg.zones)}")
    except Exception as exc:
        st.error(str(exc))
    zfile = st.file_uploader("Import zone table CSV", type=["csv"], key="zones_upload")
    if zfile is not None:
        try:
            cfg.zones = zones_from_csv(pd.read_csv(zfile)); st.success("Zone table imported."); st.rerun()
        except Exception as exc:
            st.error(str(exc))

with tabs[2]:
    st.subheader("Central plant")
    p = cfg.plant
    c = st.columns(4)
    p.chiller_capacity_kW = c[0].number_input("Chiller capacity (kW)", 10.0, 10000.0, float(p.chiller_capacity_kW), 10.0)
    p.chiller_reference_COP = c[1].number_input("Reference COP", 1.0, 12.0, float(p.chiller_reference_COP), 0.1)
    p.chilled_water_supply_C = c[2].number_input("Nominal CHWS (°C)", 3.0, 12.0, float(p.chilled_water_supply_C), 0.1)
    p.chilled_water_deltaT_K = c[3].number_input("CHW ΔT (K)", 2.0, 12.0, float(p.chilled_water_deltaT_K), 0.5)
    c = st.columns(4)
    p.chilled_water_pump_design_kW = c[0].number_input("CHW pump design power (kW)", 0.1, 500.0, float(p.chilled_water_pump_design_kW), 1.0)
    p.condenser_pump_design_kW = c[1].number_input("Condenser pump design power (kW)", 0.1, 500.0, float(p.condenser_pump_design_kW), 1.0)
    p.cooling_tower_design_kW = c[2].number_input("Cooling tower design power (kW)", 0.1, 500.0, float(p.cooling_tower_design_kW), 1.0)
    p.auxiliary_base_kW = c[3].number_input("Auxiliary base power (kW)", 0.0, 100.0, float(p.auxiliary_base_kW), 0.5)
    st.subheader("Air-handling units")
    ahu_df = pd.DataFrame([a.__dict__ for a in cfg.ahus])
    ahu_edit = st.data_editor(ahu_df, use_container_width=True, num_rows="dynamic", height=260, key="ahu_editor")
    try:
        from hvac_bms.config import AHUConfig
        cfg.ahus = [AHUConfig(**{k:v for k,v in r.items() if pd.notna(v)}) for r in ahu_edit.to_dict(orient="records")]
    except Exception as exc:
        st.error(str(exc))

with tabs[3]:
    b, f = cfg.bms, cfg.faults
    left, right = st.columns(2)
    with left:
        st.subheader("Supervisory BMS")
        b.strategy = st.selectbox("Control strategy", ["S0", "S1", "S2", "S3"], index=["S0","S1","S2","S3"].index(b.strategy.upper()))
        st.caption("S0=fixed; S1=scheduled reset; S2=fault-aware supervisory; S3=APO-inspired optimized supervisory control.")
        b.demand_limit_kW = st.number_input("Demand limit (kW)", 10.0, 10000.0, float(b.demand_limit_kW), 10.0)
        b.control_interval_minutes = int(st.selectbox("Supervisory interval", [15, 30, 60, 120], index=[15,30,60,120].index(b.control_interval_minutes) if b.control_interval_minutes in [15,30,60,120] else 2))
        b.co2_limit_ppm = st.number_input("CO₂ alarm limit (ppm)", 600.0, 2500.0, float(b.co2_limit_ppm), 50.0)
        b.comfort_weight = st.slider("Comfort objective weight", 0.0, 25.0, float(b.comfort_weight), 0.5)
        b.iaq_weight = st.slider("IAQ objective weight", 0.0, 15.0, float(b.iaq_weight), 0.5)
        b.demand_weight = st.slider("Demand objective weight", 0.0, 15.0, float(b.demand_weight), 0.5)
        b.maintenance_enabled = st.toggle("Condition-based maintenance", b.maintenance_enabled)
        b.maintenance_threshold = st.slider("Maintenance threshold", 0.1, 1.0, float(b.maintenance_threshold), 0.05)
    with right:
        st.subheader("Faults and degradation")
        f.filter_clogging_initial = st.slider("Initial filter clogging", 0.0, 1.0, float(f.filter_clogging_initial), 0.01)
        f.filter_clogging_growth_per_day = st.number_input("Filter growth / day", 0.0, 0.1, float(f.filter_clogging_growth_per_day), 0.0005, format="%.4f")
        f.coil_fouling_initial = st.slider("Initial coil fouling", 0.0, 1.0, float(f.coil_fouling_initial), 0.01)
        f.coil_fouling_growth_per_day = st.number_input("Coil growth / day", 0.0, 0.1, float(f.coil_fouling_growth_per_day), 0.0005, format="%.4f")
        f.chiller_fouling_initial = st.slider("Initial chiller fouling", 0.0, 1.0, float(f.chiller_fouling_initial), 0.01)
        f.chiller_fouling_growth_per_day = st.number_input("Chiller growth / day", 0.0, 0.1, float(f.chiller_fouling_growth_per_day), 0.0005, format="%.4f")
        f.zone_temp_sensor_bias_C = st.number_input("Zone temperature sensor bias (°C)", -5.0, 5.0, float(f.zone_temp_sensor_bias_C), 0.1)
        f.supply_air_temp_sensor_bias_C = st.number_input("SAT sensor bias (°C)", -5.0, 5.0, float(f.supply_air_temp_sensor_bias_C), 0.1)
        f.outdoor_damper_stuck_fraction = st.number_input("Stuck OA damper fraction (-1=disabled)", -1.0, 1.0, float(f.outdoor_damper_stuck_fraction), 0.05)

with tabs[4]:
    st.write("Upload measured weather or an EPW-converted CSV. Required: `timestamp`, `dry_bulb_C`. Optional: `rel_humidity_pct`, `solar_W_m2`, `wind_m_s`.")
    wf = st.file_uploader("Weather CSV", type=["csv"], key="weather_upload")
    if wf is not None:
        try:
            st.session_state.weather = pd.read_csv(wf)
            st.success(f"Loaded {len(st.session_state.weather):,} weather rows.")
            st.dataframe(st.session_state.weather.head(20), use_container_width=True)
        except Exception as exc:
            st.error(str(exc))
    elif st.session_state.weather is None:
        st.info("No weather file loaded. The simulator will generate deterministic hot-climate demonstration weather.")

with tabs[5]:
    st.subheader("Execute simulation")
    est_steps = int(cfg.days * 24 * 60 / cfg.timestep_minutes)
    st.write(f"{len(cfg.zones)} zones · {len(cfg.ahus)} AHUs · {est_steps:,} timesteps · strategy {cfg.bms.strategy}")
    if st.button("▶ Run HVAC–BMS simulation", type="primary", use_container_width=True):
        bar = st.progress(0.0, text="Initializing simulation…")
        try:
            st.session_state.result = run_simulation(cfg, st.session_state.weather, lambda x: bar.progress(float(x), text=f"Simulating… {x:.0%}"))
            bar.progress(1.0, text="Simulation complete")
            st.success("Simulation completed. Open Dashboard, Time series, Alarms, or Downloads.")
        except Exception as exc:
            st.exception(exc)

result = st.session_state.result

with tabs[6]:
    if result is None:
        st.info("Run a simulation to populate the dashboard.")
    else:
        sm = result.summary.set_index("KPI")["Value"]
        cols = st.columns(6)
        cols[0].metric("HVAC energy", f"{float(sm['Electric HVAC energy']):,.0f} kWh")
        cols[1].metric("Peak demand", f"{float(sm['Peak electric demand']):,.1f} kW")
        cols[2].metric("Average COP", f"{float(sm['Average chiller COP']):.2f}")
        cols[3].metric("Discomfort", f"{float(sm['Occupied discomfort ratio']):.1f}%")
        cols[4].metric("Carbon", f"{float(sm['Operational carbon']):,.0f} kgCO₂")
        cols[5].metric("Alarms", f"{int(sm['Alarm events'])}")
        ts = result.timeseries
        c1, c2 = st.columns(2)
        with c1:
            fig = px.line(ts, x="timestamp", y=["electric_power_kW", "cooling_load_kW"], labels={"value":"kW", "variable":"Series"}, title="Electric power and cooling load")
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            fig = px.line(ts, x="timestamp", y=["outdoor_temp_C", "average_zone_temp_C", "supply_air_temp_setpoint_C"], labels={"value":"°C", "variable":"Series"}, title="Outdoor, zone, and supply-air temperatures")
            st.plotly_chart(fig, use_container_width=True)
        c1, c2 = st.columns(2)
        with c1:
            energy = ts[["chiller_power_kW", "fan_power_kW", "pump_power_kW", "cooling_tower_power_kW", "auxiliary_power_kW"]].sum() * cfg.timestep_minutes / 60
            fig = px.bar(x=["Chiller", "Fans", "Pumps", "Tower", "Auxiliary"], y=energy.values, labels={"x":"Component", "y":"Energy (kWh)"}, title="HVAC energy breakdown")
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            fig = px.line(ts, x="timestamp", y=["filter_clogging", "coil_fouling", "chiller_fouling"], labels={"value":"Severity", "variable":"State"}, title="Degradation trajectories")
            st.plotly_chart(fig, use_container_width=True)

with tabs[7]:
    if result is None:
        st.info("Run a simulation first.")
    else:
        series_options = [c for c in result.timeseries.columns if c != "timestamp"]
        selected = st.multiselect("Building/plant series", series_options, default=["electric_power_kW", "average_zone_temp_C", "chiller_COP"])
        if selected:
            fig = go.Figure()
            for col in selected:
                fig.add_trace(go.Scatter(x=result.timeseries["timestamp"], y=result.timeseries[col], mode="lines", name=col))
            fig.update_layout(height=520, hovermode="x unified", xaxis_title="Time")
            st.plotly_chart(fig, use_container_width=True)
        zone_name = st.selectbox("Zone", sorted(result.zones["zone"].unique()))
        zdf = result.zones[result.zones["zone"] == zone_name]
        zseries = st.multiselect("Zone series", [c for c in zdf.columns if c not in ["timestamp","zone","ahu"]], default=["temperature_C", "cooling_setpoint_C", "co2_ppm"])
        if zseries:
            fig = px.line(zdf, x="timestamp", y=zseries, title=f"{zone_name} performance")
            st.plotly_chart(fig, use_container_width=True)
        st.dataframe(result.timeseries, use_container_width=True, height=320)

with tabs[8]:
    if result is None:
        st.info("Run a simulation first.")
    else:
        if result.alarms.empty:
            st.success("No alarms were generated.")
        else:
            sev = st.multiselect("Severity", sorted(result.alarms["severity"].unique()), default=sorted(result.alarms["severity"].unique()))
            st.dataframe(result.alarms[result.alarms["severity"].isin(sev)], use_container_width=True, height=520)

with tabs[9]:
    st.subheader("S0-S3 strategy benchmark")
    st.write("Runs the same building, weather, faults, and schedules under all four supervisory strategies.")
    if st.button("Run comparative benchmark", use_container_width=True):
        bench_rows = []
        prog = st.progress(0.0, text="Starting benchmark…")
        try:
            for i, strategy in enumerate(["S0", "S1", "S2", "S3"]):
                ccfg = SimulationConfig.from_dict(deepcopy(cfg.to_dict()))
                ccfg.bms.strategy = strategy
                rr = run_simulation(ccfg, st.session_state.weather)
                vals = rr.summary.set_index("KPI")["Value"]
                bench_rows.append({
                    "Strategy": strategy,
                    "Electric_HVAC_kWh": float(vals["Electric HVAC energy"]),
                    "Peak_kW": float(vals["Peak electric demand"]),
                    "Average_COP": float(vals["Average chiller COP"]),
                    "Discomfort_pct": float(vals["Occupied discomfort ratio"]),
                    "Max_CO2_ppm": float(vals["Maximum average CO2"]),
                    "Cost_USD": float(vals["Electricity cost"]),
                    "Carbon_kgCO2": float(vals["Operational carbon"]),
                    "Alarm_events": int(vals["Alarm events"]),
                })
                prog.progress((i + 1) / 4, text=f"Completed {strategy}")
            bdf = pd.DataFrame(bench_rows)
            base = float(bdf.loc[bdf["Strategy"] == "S0", "Electric_HVAC_kWh"].iloc[0])
            bdf["Energy_saving_vs_S0_pct"] = 100 * (base - bdf["Electric_HVAC_kWh"]) / max(base, 1e-9)
            st.session_state.benchmark = bdf
            st.success("Benchmark completed.")
        except Exception as exc:
            st.exception(exc)
    if st.session_state.benchmark is not None:
        bdf = st.session_state.benchmark
        st.dataframe(bdf, use_container_width=True)
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.bar(bdf, x="Strategy", y="Electric_HVAC_kWh", title="Energy by BMS strategy"), use_container_width=True)
        c2.plotly_chart(px.scatter(bdf, x="Discomfort_pct", y="Electric_HVAC_kWh", text="Strategy", size="Peak_kW", title="Energy-comfort trade-off"), use_container_width=True)
        st.download_button("Download benchmark CSV", bdf.to_csv(index=False), "BMS_strategy_benchmark.csv", "text/csv", use_container_width=True)

with tabs[10]:
    st.subheader("Reference-model or field-data validation")
    if result is None:
        st.info("Run a simulation before validating it.")
    else:
        st.write("Upload a reference CSV with `timestamp` and one or more columns matching the simulator output names.")
        ref_file = st.file_uploader("Reference CSV", type=["csv"], key="validation_upload")
        if ref_file is not None:
            try:
                ref_df = pd.read_csv(ref_file)
                candidates = sorted(set(ref_df.columns).intersection(result.timeseries.columns) - {"timestamp"})
                selected_vars = st.multiselect("Variables to validate", candidates, default=candidates[:4])
                if st.button("Calculate validation metrics", use_container_width=True):
                    st.session_state.validation_metrics = compare_timeseries(ref_df, result.timeseries, selected_vars)
            except Exception as exc:
                st.error(str(exc))
        if st.session_state.validation_metrics is not None:
            st.dataframe(st.session_state.validation_metrics, use_container_width=True)
            st.download_button("Download validation metrics", st.session_state.validation_metrics.to_csv(index=False), "validation_metrics.csv", "text/csv", use_container_width=True)

with tabs[11]:
    if result is None:
        st.info("Run a simulation first.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.download_button("Download Excel results", excel_bytes(result), "HVAC_BMS_simulation_results.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
        c2.download_button("Download PDF report", pdf_bytes(result), "HVAC_BMS_simulation_report.pdf", "application/pdf", use_container_width=True)
        c3.download_button("Download journal figures", journal_figures_zip(result), "HVAC_BMS_journal_figures.zip", "application/zip", use_container_width=True)
        c1, c2, c3 = st.columns(3)
        c1.download_button("Building time series CSV", result.timeseries.to_csv(index=False), "building_timeseries.csv", "text/csv", use_container_width=True)
        c2.download_button("Zone time series CSV", result.zones.to_csv(index=False), "zone_timeseries.csv", "text/csv", use_container_width=True)
        c3.download_button("Alarm log CSV", result.alarms.to_csv(index=False), "bms_alarm_log.csv", "text/csv", use_container_width=True)
        st.dataframe(result.summary, use_container_width=True)

st.session_state.config = cfg
