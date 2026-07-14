from __future__ import annotations

import io
import json
import zipfile
from typing import Dict

import matplotlib.pyplot as plt
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .simulator import SimulationResult


def excel_bytes(result: SimulationResult) -> bytes:
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="xlsxwriter", datetime_format="yyyy-mm-dd hh:mm") as writer:
        result.summary.to_excel(writer, sheet_name="Summary", index=False)
        result.timeseries.to_excel(writer, sheet_name="TimeSeries", index=False)
        result.zones.to_excel(writer, sheet_name="Zones", index=False)
        result.ahus.to_excel(writer, sheet_name="AHUs", index=False)
        result.alarms.to_excel(writer, sheet_name="Alarms", index=False)
        pd.DataFrame({"config_json": [json.dumps(result.config.to_dict(), indent=2)]}).to_excel(writer, sheet_name="Configuration", index=False)
        workbook = writer.book
        header_fmt = workbook.add_format({"bold": True, "bg_color": "#17365D", "font_color": "white", "border": 1})
        num_fmt = workbook.add_format({"num_format": "0.000"})
        for sheet_name, df in {"Summary": result.summary, "TimeSeries": result.timeseries, "Zones": result.zones, "AHUs": result.ahus, "Alarms": result.alarms}.items():
            ws = writer.sheets[sheet_name]
            ws.freeze_panes(1, 0)
            ws.autofilter(0, 0, max(len(df), 1), max(len(df.columns)-1, 0))
            for c, col in enumerate(df.columns):
                ws.write(0, c, col, header_fmt)
                width = min(max(len(str(col)) + 2, 12), 28)
                if len(df):
                    width = min(max(width, int(df[col].astype(str).str.len().quantile(0.95)) + 2), 34)
                ws.set_column(c, c, width, num_fmt if pd.api.types.is_numeric_dtype(df[col]) else None)
    return bio.getvalue()


def pdf_bytes(result: SimulationResult) -> bytes:
    bio = io.BytesIO()
    doc = SimpleDocTemplate(bio, pagesize=landscape(A4), leftMargin=14*mm, rightMargin=14*mm, topMargin=12*mm, bottomMargin=12*mm)
    styles = getSampleStyleSheet()
    story = [Paragraph(result.config.building_name, styles["Title"]), Paragraph("HVAC-BMS Reduced-Order Digital Twin Report", styles["Heading2"]), Spacer(1, 6)]
    summary_data = [["KPI", "Value", "Unit"]] + [[str(r.KPI), f"{r.Value:.3f}" if isinstance(r.Value, (float, int)) else str(r.Value), str(r.Unit)] for r in result.summary.itertuples()]
    table = Table(summary_data, colWidths=[95*mm, 45*mm, 35*mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#17365D")), ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"), ("GRID", (0,0), (-1,-1), 0.4, colors.grey),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#EEF3F8")]),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"), ("FONTSIZE", (0,0), (-1,-1), 8),
    ]))
    story += [table, PageBreak(), Paragraph("BMS alarm log", styles["Heading2"])]
    alarm_head = ["Timestamp", "Code", "Severity", "Message", "Value"]
    alarms = result.alarms.head(60)
    def _cell(x):
        if isinstance(x, float):
            return f"{x:.3f}"
        return str(x)
    alarm_data = [alarm_head] + [[_cell(x) for x in row] for row in alarms.fillna("").itertuples(index=False, name=None)]
    if len(alarm_data) == 1:
        alarm_data.append(["-", "-", "Info", "No alarm events recorded.", "-"])
    at = Table(alarm_data, colWidths=[35*mm, 35*mm, 22*mm, 140*mm, 25*mm], repeatRows=1)
    at.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#17365D")), ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"), ("GRID", (0,0), (-1,-1), 0.3, colors.grey),
        ("FONTSIZE", (0,0), (-1,-1), 6.5), ("VALIGN", (0,0), (-1,-1), "TOP"),
    ]))
    story.append(at)
    doc.build(story)
    return bio.getvalue()


def journal_figures_zip(result: SimulationResult) -> bytes:
    ts = result.timeseries.copy()
    zone = result.zones.copy()
    files: Dict[str, bytes] = {}

    def save_current(name: str):
        b = io.BytesIO()
        plt.tight_layout()
        plt.savefig(b, format="png", dpi=300, bbox_inches="tight")
        plt.close()
        files[name] = b.getvalue()

    plt.figure(figsize=(8.0, 4.6))
    plt.plot(ts["timestamp"], ts["electric_power_kW"], label="Electric HVAC power")
    plt.plot(ts["timestamp"], ts["cooling_load_kW"], label="Cooling load")
    plt.ylabel("Power / load (kW)"); plt.xlabel("Time"); plt.legend(); plt.grid(alpha=0.25)
    save_current("figure_01_power_and_cooling_load.png")

    plt.figure(figsize=(8.0, 4.6))
    plt.plot(ts["timestamp"], ts["outdoor_temp_C"], label="Outdoor")
    plt.plot(ts["timestamp"], ts["average_zone_temp_C"], label="Average zone")
    plt.plot(ts["timestamp"], ts["supply_air_temp_setpoint_C"], label="SAT setpoint")
    plt.ylabel("Temperature (C)"); plt.xlabel("Time"); plt.legend(); plt.grid(alpha=0.25)
    save_current("figure_02_temperatures.png")

    plt.figure(figsize=(8.0, 4.6))
    plt.plot(ts["timestamp"], ts["filter_clogging"], label="Filter clogging")
    plt.plot(ts["timestamp"], ts["coil_fouling"], label="Coil fouling")
    plt.plot(ts["timestamp"], ts["chiller_fouling"], label="Chiller fouling")
    plt.ylabel("Severity index (0-1)"); plt.xlabel("Time"); plt.legend(); plt.grid(alpha=0.25)
    save_current("figure_03_degradation.png")

    energy_components = (ts[["chiller_power_kW", "fan_power_kW", "pump_power_kW", "cooling_tower_power_kW", "auxiliary_power_kW"]].sum() * result.config.timestep_minutes / 60)
    plt.figure(figsize=(7.0, 4.6))
    plt.bar(["Chiller", "Fans", "Pumps", "Tower", "Auxiliary"], energy_components.values)
    plt.ylabel("Energy (kWh)"); plt.xticks(rotation=20); plt.grid(axis="y", alpha=0.25)
    save_current("figure_04_energy_breakdown.png")

    zstats = zone.groupby("zone").agg(mean_temp_C=("temperature_C", "mean"), max_co2_ppm=("co2_ppm", "max"), comfort_degree_h=("comfort_deviation_C", lambda s: s.sum()*result.config.timestep_minutes/60)).reset_index()
    files["zone_performance_summary.csv"] = zstats.to_csv(index=False).encode("utf-8")

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return out.getvalue()
