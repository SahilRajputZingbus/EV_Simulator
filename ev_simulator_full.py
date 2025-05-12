
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import numpy as np

st.title("🔌 EV Bus Network Simulator - Full Version")

# Input section
st.sidebar.header("Simulation Inputs")

routes_input = st.sidebar.text_area("Enter Routes (comma-separated)", "Delhi–Lucknow,Delhi–Amritsar,Delhi–Jaipur")
routes = [r.strip() for r in routes_input.split(",")]



bus_per_route = st.sidebar.number_input("Number of Buses per Route", 1, 50, 10)
departure_interval = st.sidebar.selectbox("Departure Interval (minutes)", [15, 30, 45, 60])
blackout_start = st.sidebar.time_input("Blackout Start", datetime.strptime("01:00", "%H:%M").time())
blackout_end = st.sidebar.time_input("Blackout End", datetime.strptime("04:00", "%H:%M").time())

charger_locations_input = st.sidebar.text_area("Charging Locations (comma-separated)", "Delhi,Kuberpur,Rajpura,Jaipur")
charger_locations = [loc.strip() for loc in charger_locations_input.split(",")]

charger_config = {}
for loc in charger_locations:
    charger_config[loc] = {
        "count": st.sidebar.number_input(f"{loc} - Chargers", 1, 20, 4, key=loc),
        "capacity": st.sidebar.number_input(f"{loc} - kW per Charger", 60, 500, 240, step=20, key=loc+"_kW")
    }

# Generate schedule
st.header("📋 Bus Schedule")
base_time = datetime.strptime("04:00", "%H:%M")
schedule = []

for route in routes:
    for i in range(bus_per_route):
        dep_time = base_time + timedelta(minutes=i * departure_interval)
        schedule.append({
            "Route": route,
            "Bus ID": f"{route[:3].upper()}_{i+1:02d}",
            "Departure Time": dep_time.strftime("%H:%M"),
            "Charging Location": charger_locations[i % len(charger_locations)]
        })

schedule_df = pd.DataFrame(schedule)
st.dataframe(schedule_df)

# Allocate charger slots
st.header("🔋 Charger Slot Allocation")
slots = []

for loc in charger_locations:
    charger_count = charger_config[loc]["count"]
    capacity = charger_config[loc]["capacity"]
    loc_buses = schedule_df[schedule_df["Charging Location"] == loc].copy()
    charger_timeline = [datetime.strptime("04:00", "%H:%M")] * charger_count

    for idx, row in loc_buses.iterrows():
        charge_duration = timedelta(minutes=int((160 / capacity) * 60))  # 160 kWh assumed
        earliest_idx = charger_timeline.index(min(charger_timeline))
        start_time = charger_timeline[earliest_idx]
        end_time = start_time + charge_duration
        charger_timeline[earliest_idx] = end_time

        slots.append({
            "Location": loc,
            "Bus ID": row["Bus ID"],
            "Charger #": earliest_idx + 1,
            "Start Time": start_time.strftime("%H:%M"),
            "End Time": end_time.strftime("%H:%M"),
        })

slots_df = pd.DataFrame(slots)
st.dataframe(slots_df)

# Utilization summary
st.header("📊 Utilization Summary")
util_summary = []
total_window_minutes = (datetime.strptime("23:59", "%H:%M") - datetime.strptime("04:00", "%H:%M")).seconds / 60

for loc in charger_locations:
    cap = charger_config[loc]["capacity"]
    count = charger_config[loc]["count"]
    minutes_used = sum([
        (datetime.strptime(row["End Time"], "%H:%M") - datetime.strptime(row["Start Time"], "%H:%M")).seconds / 60
        for _, row in slots_df[slots_df["Location"] == loc].iterrows()
    ])
    total_available = total_window_minutes * count
    utilization = (minutes_used / total_available) * 100
    util_summary.append({
        "Location": loc,
        "Chargers": count,
        "Total Minutes Used": int(minutes_used),
        "Utilization %": round(utilization, 1),
        "Status": "OK" if utilization >= 20 else "UNDERUTILIZED"
    })

util_df = pd.DataFrame(util_summary)
st.dataframe(util_df)
