# System architecture

```text
Weather / EPW-derived CSV ─┐
Building + zone inputs ────┼─> Multi-zone heat, humidity and CO2 balances
Schedules and occupancy ───┘                    │
                                                v
                                  Zone VAV airflow and loads
                                                │
                                                v
                          AHU mixing, coils, fans and ventilation
                                                │
                                                v
                    Chiller + pumps + tower + boiler + auxiliaries
                                                │
                                                v
          BMS S0/S1/S2/S3 supervisory control and demand management
                    ^                           │
                    │                           v
       Fault/degradation states <──── FDD alarms and maintenance
                                                │
                                                v
                 KPI dashboard / CSV / Excel / PDF / figures
```

## S3 control vector

`u = [SAT, CHWS, static-pressure fraction, zone setpoint reset, outdoor-air fraction]`

The APO-inspired optimizer minimizes a weighted surrogate objective containing estimated HVAC electric power, occupied comfort deviation, IAQ violation, and peak-demand violation. The physical simulator then evaluates the selected control action at each supervisory interval.
