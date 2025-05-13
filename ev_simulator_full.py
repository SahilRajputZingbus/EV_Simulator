import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from pymongo import MongoClient
import numpy as np

MONGO_URI = "mongodb+srv://sahilrajput:NM09NKfilkALYovi@cluster0.cybby1b.mongodb.net/"
client = MongoClient(MONGO_URI)
db = client["ev_simulator"]
config_collection = db["user_configs"]

if "routes_input" not in st.session_state:
    synced = config_collection.find_one({"_id": "default_config"})
    
    if synced:
        st.session_state.routes_input = synced["routes_input"]
        st.session_state.bus_per_route = synced["bus_per_route"]
        st.session_state.departure_interval = synced["departure_interval"]
        st.session_state.blackout_start = datetime.strptime(synced["blackout_start"], "%H:%M:%S").time()
        st.session_state.blackout_end = datetime.strptime(synced["blackout_end"], "%H:%M:%S").time()
        st.session_state.charger_locations_input = synced["charger_locations_input"]
        st.session_state.charger_config = synced["charger_config"]
    else:
        st.session_state.routes_input = "Delhi–Lucknow,Delhi–Amritsar,Delhi–Jaipur"
        st.session_state.bus_per_route = 10
        st.session_state.departure_interval = 30
        st.session_state.blackout_start = datetime.strptime("01:00", "%H:%M").time()
        st.session_state.blackout_end = datetime.strptime("04:00", "%H:%M").time()
        st.session_state.charger_locations_input = "Delhi,Kuberpur,Rajpura,Jaipur"
        st.session_state.charger_config = {
            "Delhi": {"count": 4, "capacity": 240},
            "Kuberpur": {"count": 3, "capacity": 180},
            "Rajpura": {"count": 5, "capacity": 220},
            "Jaipur": {"count": 6, "capacity": 250}
        }

st.title("🔌 EV Bus Network Simulator - Full Version")
st.sidebar.header("Simulation Inputs")

if st.sidebar.button("🔄 Load Synced Settings from MongoDB"):
    synced = config_collection.find_one({"_id": "default_config"})
    if synced:
        st.session_state.routes_input = synced["routes_input"]
        st.session_state.bus_per_route = synced["bus_per_route"]
        st.session_state.departure_interval = synced["departure_interval"]
        st.session_state.blackout_start = datetime.strptime(synced["blackout_start"], "%H:%M:%S").time()
        st.session_state.blackout_end = datetime.strptime(synced["blackout_end"], "%H:%M:%S").time()
        st.session_state.charger_locations_input = synced["charger_locations_input"]
        st.session_state.charger_config = synced["charger_config"]
        st.session_state["_trigger_rerun"] = True  # ✅ Set a rerun flag

if st.session_state.get("_trigger_rerun", False):
    st.session_state["_trigger_rerun"] = False
    st.rerun()

valid_intervals = [15, 30, 45, 60]

if st.session_state.departure_interval not in valid_intervals:
    st.session_state.departure_interval = 30  

routes_input = st.sidebar.text_area("Enter Routes (comma-separated)", st.session_state.routes_input,key="routes_input")
routes = [r.strip() for r in routes_input.split(",")]

bus_per_route = st.sidebar.selectbox(
    "Number of Buses per Route", 
    list(range(1, 51)), 
    index=st.session_state.bus_per_route - 1,
    key="bus_per_route"
)
departure_interval = st.sidebar.selectbox(
    "Departure Interval (minutes)", 
    valid_intervals, 
    index=valid_intervals.index(st.session_state.departure_interval),key="departure_interval"
)
blackout_start = st.sidebar.time_input("Blackout Start", st.session_state.blackout_start, key="blackout_start")
blackout_end = st.sidebar.time_input("Blackout End", st.session_state.blackout_end, key="blackout_end")

charger_locations_input = st.sidebar.text_area("Charging Locations (comma-separated)", st.session_state.charger_locations_input, key="charger_locations_input")
charger_locations = [loc.strip() for loc in charger_locations_input.split(",")]

charger_config = {}
for loc in charger_locations:
    charger_config[loc] = {
        "count": st.sidebar.number_input(f"{loc} - Chargers", 1, 20, st.session_state.charger_config.get(loc, {}).get("count", 4), key=loc),
        "capacity": st.sidebar.number_input(f"{loc} - kW per Charger", 60, 500, st.session_state.charger_config.get(loc, {}).get("capacity", 240), step=20, key=loc+"_kW")
    }

if st.sidebar.button("✅ Sync Settings to MongoDB"):
    config = {
        "routes_input": routes_input,
        "bus_per_route": bus_per_route,
        "departure_interval": departure_interval,
        "blackout_start": str(blackout_start),
        "blackout_end": str(blackout_end),
        "charger_locations_input": charger_locations_input,
        "charger_config": charger_config,
        "timestamp": datetime.now()
    }
    config_collection.update_one({"_id": "default_config"}, {"$set": config}, upsert=True)
    st.sidebar.success("Settings synced to MongoDB.")



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

st.header("📊 Utilization Summary")
util_summary = []
total_window_minutes = (datetime.strptime("23:59", "%H:%M") - datetime.strptime("04:00", "%H:%M")).seconds / 60

for loc in charger_locations:
    cap = charger_config[loc]["capacity"]
    count = charger_config[loc]["count"]
    minutes_used = sum([(
        datetime.strptime(row["End Time"], "%H:%M") - datetime.strptime(row["Start Time"], "%H:%M")).seconds / 60
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
