import streamlit as st
from streamlit_folium import st_folium
import folium
import pandas as pd
import googlemaps
import polyline
import plotly.express as px 
from datetime import datetime, timedelta,time
from pymongo import MongoClient
import json
import hashlib
import math
import re

st.set_page_config(page_title="EV Network Planning", layout="wide", page_icon="⚡")

gmaps = googlemaps.Client(key="AIzaSyCcdyw_-0olqzOu9vSdDQBgZvaTw8GGLbc")

MONGO_URI = "mongodb+srv://sahilrajput:NM09NKfilkALYovi@cluster0.cybby1b.mongodb.net/"

@st.cache_resource
def get_mongo_client():
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")
        return client
    except Exception as e:
        st.warning(f"MongoDB unavailable: {e}. Save/Load disabled.")
        return None

_mongo_client = get_mongo_client()
db = _mongo_client["ev_simulator"] if _mongo_client else None
collection = db["sessions"] if db is not None else None


STATE_KEYS = [
    "bus_stations", "charging_stations", "services",
    "networks",  "temp_route", "route_data_cache"
]

def make_serializable(obj):
    if isinstance(obj, pd.DataFrame):
        # First convert to list of dicts
        records = obj.to_dict(orient="records")
        # Then recursively serialize each value inside
        return [make_serializable(row) for row in records]
    
    elif isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    
    elif isinstance(obj, datetime):
        return obj.isoformat()
    
    elif isinstance(obj, time):
        return obj.strftime("%H:%M:%S")
    
    elif isinstance(obj, dict):
        return {k: make_serializable(v) for k, v in obj.items()}
    
    elif isinstance(obj, list):
        return [make_serializable(v) for v in obj]
    
    
    else:
        return obj

def clean_session_state():
    cleaned = {}
    for key in STATE_KEYS:
        val = st.session_state.get(key)
        cleaned[key] = make_serializable(val)


    return cleaned

def load_session_state(data):
    for key in STATE_KEYS:
        val = data.get(key)

        if key == "charging_stations":
            st.session_state[key] = pd.DataFrame(val, columns=[
                'Station Name', 'Charging Capacity (kW)', 'Number of Chargers','Latitude','Longitude'
            ]) if isinstance(val, list) else pd.DataFrame()
        
        elif key == "services":
            st.session_state[key] = pd.DataFrame(val, columns=[
                'Service Name', 'Bus Charging Capacity (kW)', 'Mileage (km/kWh)',
                'Number of Buses', 'Departure Intervals', 'Route Data',
                'Start Time', 'Distance (km)', 'Duration (mins)', 'Distance Time Matrix','Buffer Times','Wait Time'
            ]) if isinstance(val, list) else pd.DataFrame()

        elif key == "networks":
            st.session_state[key] = pd.DataFrame(val, columns=[
                'Network Name', 'Tolerance (%)', 'Services',  'Status', 'Allocations', 'Logs', 'Charging Events','Bus Schedule'
            ]) if isinstance(val, list) else pd.DataFrame()


        else:
            st.session_state[key] = val if val is not None else ({} if key == "route_data_cache" else [])
            
def save_session_to_mongo(user_id="default_user"):
    if collection is None:
        st.error("MongoDB is not connected. Save is unavailable.")
        return
    try:
        data = clean_session_state()
        collection.update_one(
            {"_id": user_id},
            {"$set": {"state": data}},
            upsert=True
        )
        st.success("Session saved to MongoDB.")
    except Exception as e:
        with open("error_log.txt", "a") as f:
            f.write(f"{datetime.now()}: Failed to save session for user {user_id}: {str(e)}\n")
        st.error(f"Failed to save session: {e}")

def load_session_from_mongo(user_id="default_user"):
    if collection is None:
        st.error("MongoDB is not connected. Load is unavailable.")
        return
    try:
        doc = collection.find_one({"_id": user_id})
        if doc and "state" in doc:
            load_session_state(doc["state"])
            st.success("Session loaded from MongoDB.")
        else:
            st.warning("No saved session found.")
    except Exception as e:
        st.error(f"Failed to load session: {e}")

def init_session_state():
    if "bus_stations" not in st.session_state:
        st.session_state.bus_stations = []
    if "charging_stations" not in st.session_state:
        st.session_state.charging_stations = pd.DataFrame(columns=[
            'Station Name', 'Charging Capacity (kW)', 'Number of Chargers','Latitude','Longitude'
        ])
    if "services" not in st.session_state:
        st.session_state.services = pd.DataFrame(columns=[
            'Service Name', 'Bus Charging Capacity (kW)', 'Mileage (km/kWh)', 'Number of Buses',
            'Departure Intervals', 'Route Data', 'Start Time', 'Distance (km)', 'Duration (mins)','Distance Time Matrix','Buffer Times','Wait Time'
        ])
    if "networks" not in st.session_state:
        st.session_state.networks = pd.DataFrame(columns=[
            'Network Name', 'Tolerance (%)', 'Services',
            'Status', 'Allocations', 'Logs'
        ])
    if "pending_service" not in st.session_state:
        st.session_state.pending_service = pd.DataFrame(columns=[
            'Service Name', 'Bus Charging Capacity (kW)', 'Mileage (km/kWh)',
            'Number of Buses', 'Departure Intervals', 'Route Data', 'Start Time','Buffer Times','Distance (km)', 'Duration (mins)', 'Distance Time Matrix','Wait Time'
        ])
    if "temp_route" not in st.session_state:
        st.session_state.temp_route = []
    if "temp_edit_route" not in st.session_state:
        st.session_state.temp_edit_route = None
    if "route_data_cache" not in st.session_state:
        st.session_state.route_data_cache = {}
    if "edit_departure_intervals" not in st.session_state:   
        st.session_state.edit_departure_intervals = None
    if "edit_route_data" not in st.session_state:
        st.session_state.edit_route_data=False
    if "edit_wait_times" not in st.session_state:
        st.session_state.edit_wait_times = None
    if "edit_buffer_times" not in st.session_state:
        st.session_state.edit_buffer_times = None
    if "edit_svc" not in st.session_state:
        st.session_state.edit_svc=False
    if 'prev_selected_svc' not in st.session_state:
        st.session_state.prev_selected_svc = None
    if "add_service_cond" not in st.session_state:
        st.session_state.add_service_cond = [False,False,False]

init_session_state()

def minutes_to_str(m):
    m = m % (24 * 60)  
    return f"{m // 60:02d}:{m % 60:02d}"

def get_slot_range(start_min, duration_min):
    start_slot = (start_min // 15) * 15
    end_slot = math.ceil((start_min + duration_min) / 15) * 15
    return start_slot, end_slot 

def round_to_previous_slot(dt):
    """Rounds datetime down to nearest 15-minute slot."""
    minute = (dt.minute // 15) * 15
    return dt.replace(minute=minute, second=0, microsecond=0)

def round_to_next_slot(dt):
    """Rounds datetime up to nearest 15-minute slot."""
    minute = ((dt.minute + 14) // 15) * 15
    if minute == 60:
        dt += timedelta(hours=1)
        minute = 0
    return dt.replace(minute=minute, second=0, microsecond=0)


def to_24h_datetime(mins):
    """Returns a fake datetime starting from 2000-01-01 + minutes."""
    return datetime(2000, 1, 1) + timedelta(minutes=mins)
def to_24h_reference(time_obj):
    """Converts 'HH:MM' string to minutes since midnight."""
    if isinstance(time_obj, str):
        time_obj = datetime.strptime(time_obj, "%H:%M")
    return time_obj.hour * 60 + time_obj.minute


def simulate_bus_trips(services_df, tolerance=10, charging_stations_df=None):
    charging_events = []
    bus_schedule = []
    allocation_rows = []

    # Charger info per station
    charging_info = {
        row['Station Name']: {
            'count': row['Number of Chargers'],
            'capacity': row['Charging Capacity (kW)']
        }
        for _, row in charging_stations_df.iterrows()
    }

    # Internal simulated allocation state (by 15-min slots)
    simulated_events = {
        station: {str(i + 1): [] for i in range(info['count'])}
        for station, info in charging_info.items()
    }



    for _, service in services_df.iterrows():
        if isinstance(service['Start Time'], str):
            time_str = service['Start Time']
            time_str = time_str.split("T")[-1]  # removes date part if present
            time_str = time_str[:5]             # takes only HH:MM
            start_time = datetime.strptime(time_str, "%H:%M").time()
        else:
            start_time = service['Start Time']
        start_min = start_time if isinstance(start_time, int) else start_time.hour * 60 + start_time.minute
        route = service['Route Data']
        dtm = service['Distance Time Matrix']
        bus_count = service.get('Number of Buses', 1)
        dep_intervals = service.get('Departure Intervals')
        bus_capacity_kwh = service['Bus Charging Capacity (kW)']
        mileage = service['Mileage (km/kWh)']
        buffer_times = service['Buffer Times']
        wait_times= service['Wait Time']

        prev_min = start_min

        for bus_num in range(bus_count):
            dep_offset = dep_intervals[bus_num] 
            departure_min = prev_min + dep_offset
            prev_min = departure_min

            battery = bus_capacity_kwh
            bus_name = f"{service['Service Name']}-{minutes_to_str(departure_min)}"

            # First station entry
            bus_schedule.append({
                'service': service['Service Name'],
                'bus_name': bus_name,
                'station': route[0]['Station'],
                'arrival': "--",
                'departure': minutes_to_str(departure_min),
                'distance_from_prev_km': 0.0,
                'battery_remaining_kwh': battery
            })

            for i in range(len(route) - 1):
                next_station = route[i + 1]
                dist_km = dtm[i + 1]["distance_m"] / 1000
                travel_min = dtm[i + 1]["duration_s"] // 60
                energy_used = dist_km / mileage
                battery -= energy_used
                arrival_min = departure_min + travel_min
                departure_min = arrival_min

                if next_station['ChargeFlag']:
                    remaining = route[i + 1:]
                    rem_dtm = dtm[i + 1:]
                    next_dist = 0
                    for j in range(len(remaining) - 1):
                        next_dist += rem_dtm[j + 1]["distance_m"] / 1000
                        if remaining[j + 1]['ChargeFlag']:
                            break
                    
                    required = bus_capacity_kwh if next_station == route[-1] else next_dist / mileage
                    buffer = 0 if next_station == route[-1] else required * (tolerance / 100)
                    target = min(bus_capacity_kwh,required + buffer)    
                    needed = max(target - battery, 0)
                    with open("logs.txt", "a") as f:
                        f.write(f"Bus: {bus_name}, Arrival: {minutes_to_str(arrival_min)},BufferTime: {buffer_times[bus_num]} ,Needed: {needed}, Battery: {battery}, Target: {target}\n")
                    arrival_min = arrival_min if next_station == route[-1] else arrival_min + buffer_times[bus_num]
                    with open("logs.txt", "a") as f:
                        f.write(f"Bus: {bus_name}, Arrival: {minutes_to_str(arrival_min)}, Needed: {needed}, Battery: {battery}, Target: {target}\n")
                    charge_minutes = 0 if needed == 0 else math.ceil((needed / charging_info[next_station['Station']]['capacity']) * 60)
                    start_slot, end_slot = get_slot_range(arrival_min, charge_minutes)
                    station_name = next_station['Station']
                    allocated = False

                    for charger_num, events in simulated_events[station_name].items():
                        found_slot = False
                        shifted_end=end_slot
                        shifted_start=start_slot
                        if next_station==route[-1]:
                            max_wait=wait_times[bus_num]
                            shift=15
                            
                        
                            while shift<= max_wait:
                                shifted_start += shift
                                shifted_end += shift
                                overlap = [
                                    e for e in events
                                    if not (shifted_end <= e['start'] or shifted_start >= e['end'])
                                ]
                                with open("logs.txt", "a") as f:
                                    f.write(f"Bus: {bus_name}, Station: {station_name}, Start Slot: {minutes_to_str(shifted_start)}, End Slot: {minutes_to_str(shifted_end)}, Overlap: {len(overlap)}\n")   
                                if not overlap:
                                    found_slot = True
                                    break

                        else:  
                            overlap = [
                                e for e in events
                                if not (end_slot <= e['start'] or start_slot >= e['end'])
                            ]
                            with open("logs.txt", "a") as f:
                                f.write(f"Bus: {bus_name}, Station: {station_name}, Start Slot: {minutes_to_str(start_slot)}, End Slot: {minutes_to_str(end_slot)}, Overlap: {len(overlap)}\n")
                        if not overlap or found_slot:
                            events.append({'start': start_slot if not found_slot else shifted_start, 'end': end_slot if not found_slot else shifted_end, 'bus': bus_name})
                            charging_events.append({
                                'station': station_name,
                                'bus_name': bus_name,
                                'arrival': minutes_to_str(arrival_min),
                                'start_time': minutes_to_str(start_slot) if not found_slot else minutes_to_str(shifted_start),
                                'end_time': minutes_to_str(end_slot) if not found_slot else minutes_to_str(shifted_end),
                                'service': service['Service Name'],
                                'energy_to_charge': needed,
                                'battery_before_pct': battery / bus_capacity_kwh * 100,
                                'battery_after_pct': (battery + needed) / bus_capacity_kwh * 100,
                                'battery_after_kwh': min(battery + needed, bus_capacity_kwh),
                                'charger_num': charger_num
                            })
                            allocation_rows.append({
                                "Station Name": station_name,
                                "Bus Name": bus_name,
                                "Charger #": charger_num,
                                "Slot Start": minutes_to_str(start_slot) if not found_slot else minutes_to_str(shifted_start),
                                "Slot End": minutes_to_str(end_slot) if not found_slot else minutes_to_str(shifted_end),
                                "Battery % on Arrival": f"{battery / bus_capacity_kwh * 100:.1f}%",
                                "Battery % After Charging": f"{(battery + needed) / bus_capacity_kwh * 100:.1f}%",
                                "Battery After Charging (kWh)": round(min(battery + needed, bus_capacity_kwh), 2)
                            })
                            battery = min(battery + needed, bus_capacity_kwh)
                            departure_min = end_slot
                            allocated = True
                            found_slot=False
                            break

                    if not allocated:
                        for o in overlap:
                            existing_slot = f"{minutes_to_str(o['start'])} - {minutes_to_str(o['end'])}"
                            new_slot = f"{minutes_to_str(start_slot)} - {minutes_to_str(end_slot)}"

                            st.error(f"""
                            ❌ System Alert Overlap Detected! 
                            
                            Station Name:**{station_name}**  
                            Service Occupying Slot:       **{o['bus']}** ⏱️ **`{existing_slot}`**  
                            Service to be Allocated:      **{bus_name}** ⏱️ **`{new_slot}`**
                            """)
                        return None, None, None, None, False
               
                bus_schedule.append({
                    'service': service['Service Name'],
                    'bus_name': bus_name,
                    'station': next_station['Station'],
                    'arrival': minutes_to_str(arrival_min),
                    'departure': "--" if next_station == route[-1] else minutes_to_str(departure_min),
                    'distance_from_prev_km': round(dist_km, 2),
                    'battery_remaining_kwh': round(battery, 2)
                })

    return bus_schedule, charging_events, pd.DataFrame(allocation_rows), simulated_events, True




def get_services_by_names(service_names):
    return st.session_state.services[
        st.session_state.services['Service Name'].isin(service_names)
    ]



def update_network(index, name, tolerance, services):
    bus_schedule, charging_events, alloc_df, charger_timeline, success = simulate_bus_trips(services, tolerance,charging_stations_df=st.session_state.charging_stations)
    if not success:
        
        return False
    else:
        st.session_state.networks.at[index, 'Network Name'] = name
        st.session_state.networks.at[index, 'Tolerance (%)'] = tolerance
        st.session_state.networks.at[index, 'Services'] = services
        st.session_state.networks.at[index, 'Allocations'] = alloc_df
        st.session_state.networks.at[index, 'Charging Events'] = charging_events
        st.session_state.networks.at[index, 'Bus Schedule'] = bus_schedule
        return True
    
@st.cache_data(show_spinner=False)
def get_directions_path(route_data_h,route_data_cache):

    route_data = route_data_cache[route_data_h]

    path_segments = []
    for i in range(len(route_data) - 1):
        origin = (route_data[i]["Latitude"], route_data[i]["Longitude"])
        destination = (route_data[i+1]["Latitude"], route_data[i+1]["Longitude"])
        directions = gmaps.directions(origin, destination, mode="driving")

        if directions and "overview_polyline" in directions[0]:
            polyline1 = directions[0]["overview_polyline"]["points"]
            path_segments.append(polyline.decode(polyline1))
    return path_segments


def build_folium_map(route_data, path_segments):
    m = folium.Map(location=[route_data[0]['Latitude'], route_data[0]['Longitude']], zoom_start=7)

    for station in route_data:
        color = 'green' if station["BusStation"] else 'red'
        folium.Marker(
            location=[station["Latitude"], station["Longitude"]],
            popup=f"{station['Station']} ({'Bus' if station['BusStation'] else 'Charger'})",
            icon=folium.Icon(color=color)
        ).add_to(m)

    for segment in path_segments:
        folium.PolyLine(locations=segment, color='blue', weight=5).add_to(m)


    return m

@st.cache_data(show_spinner=False)
def get_route_data_hash(route_data):
    route_data_hash = hashlib.md5(json.dumps(route_data, sort_keys=True).encode()).hexdigest()

    return route_data_hash

@st.cache_data(show_spinner=False)
def getDistanceAndDurationGmaps(origin, destination,mode="driving"):
    
    result = gmaps.distance_matrix(origins=[origin],
                                   destinations=[destination],
                                   mode=mode)
    
    try:
        element = result["rows"][0]["elements"][0]
        if element["status"] != "OK":
            raise Exception(f"Element status error: {element['status']}")
        
        return {
            "distance_m": element["distance"]["value"],
            "distance_text": element["distance"]["text"],
            "duration_s": element["duration"]["value"],
            "duration_text": element["duration"]["text"]
        }
    except (KeyError, IndexError):
        raise Exception("Error parsing distance matrix result.")










st.markdown("""
<style>
/* ── Global ── */
[data-testid="stAppViewContainer"] { background: #0f1117; }
[data-testid="stSidebar"] { background: #1a1d27 !important; border-right: 1px solid #2e3250; }
[data-testid="stSidebar"] * { color: #e0e4f0 !important; }

/* ── Tabs ── */
div[data-baseweb="tab-list"] {
    display: flex; justify-content: space-evenly;
    background: #1a1d27; border-radius: 12px;
    padding: 6px; gap: 6px; margin-bottom: 1rem;
}
button[role="tab"] {
    flex-grow: 1; flex-basis: 0; text-align: center;
    border-radius: 8px !important; font-weight: 600 !important;
    color: #8892b0 !important; background: transparent !important;
    border: none !important; padding: 10px 0 !important;
    transition: all 0.2s ease;
}
button[role="tab"][aria-selected="true"] {
    background: #3b5bdb !important; color: #fff !important;
    box-shadow: 0 2px 12px rgba(59,91,219,0.4);
}

/* ── Metric cards ── */
.metric-card {
    background: #1a1d27; border: 1px solid #2e3250;
    border-radius: 12px; padding: 18px 20px;
    text-align: center; margin-bottom: 1rem;
}
.metric-card .metric-value {
    font-size: 2rem; font-weight: 700; color: #74c0fc; line-height: 1.1;
}
.metric-card .metric-label {
    font-size: 0.75rem; color: #8892b0; margin-top: 4px; text-transform: uppercase; letter-spacing: 0.05em;
}

/* ── Section header ── */
.section-header {
    font-size: 1.1rem; font-weight: 700; color: #cdd9f0;
    padding: 10px 0 6px 0; border-bottom: 2px solid #3b5bdb;
    margin-bottom: 14px; letter-spacing: 0.03em;
}

/* ── Route stop card ── */
.stop-card {
    background: #1e2235; border: 1px solid #2e3250;
    border-radius: 10px; padding: 10px 14px; margin-bottom: 6px;
}
.stop-card .stop-name { font-weight: 600; color: #e0e4f0; font-size: 0.95rem; }
.stop-card .stop-meta { font-size: 0.78rem; color: #8892b0; margin-top: 2px; }
.stop-card .badge-bus   { background: #1c7ed6; color: #fff; border-radius: 5px; padding: 2px 8px; font-size: 0.7rem; }
.stop-card .badge-charger { background: #2f9e44; color: #fff; border-radius: 5px; padding: 2px 8px; font-size: 0.7rem; }

/* ── Status badges ── */
.badge-success { background: #2f9e44; color: #fff; border-radius: 5px; padding: 3px 10px; font-size: 0.75rem; font-weight: 600; }
.badge-fail    { background: #c92a2a; color: #fff; border-radius: 5px; padding: 3px 10px; font-size: 0.75rem; font-weight: 600; }

/* ── Page title ── */
.page-title {
    text-align: center; font-size: 2.1rem; font-weight: 800;
    background: linear-gradient(90deg, #74c0fc, #3b5bdb);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    margin-bottom: 0.5rem;
}
.page-sub { text-align: center; color: #8892b0; font-size: 0.9rem; margin-bottom: 1.5rem; }

/* ── Forms ── */
div[data-testid="stForm"] {
    background: #1a1d27; border: 1px solid #2e3250;
    border-radius: 12px; padding: 18px;
}
/* ── Dataframe ── */
[data-testid="stDataFrame"] { border-radius: 10px; overflow: hidden; }

/* ── Buttons ── */
button[kind="primaryFormSubmit"], button[kind="secondary"] {
    border-radius: 8px !important; font-weight: 600 !important;
}
</style>
""", unsafe_allow_html=True)

# ── Page header ──
st.markdown('<div class="page-title">⚡ EV Network Planning & Simulation</div>', unsafe_allow_html=True)
st.markdown('<div class="page-sub">Plan charging infrastructure, define bus services, and run allocation simulations</div>', unsafe_allow_html=True)

# ── Sidebar ──
with st.sidebar:
    st.markdown("### 💾 Session")
    USER_ID = st.text_input("User ID", value="1")
    col_s, col_l = st.columns(2)
    with col_s:
        if st.button("Save", use_container_width=True):
            save_session_to_mongo(USER_ID)
    with col_l:
        if st.button("Load", use_container_width=True):
            load_session_from_mongo(USER_ID)

    st.divider()
    st.markdown("### 📊 Overview")
    n_bus   = len(st.session_state.bus_stations)
    n_cs    = len(st.session_state.charging_stations)
    n_svc   = len(st.session_state.services)
    n_net   = len(st.session_state.networks)
    n_chrg  = int(st.session_state.charging_stations['Number of Chargers'].sum()) if n_cs else 0
    st.metric("Bus Stations", n_bus)
    st.metric("Charging Stations", n_cs)
    st.metric("Total Chargers", n_chrg)
    st.metric("Services", n_svc)
    st.metric("Networks", n_net)

if "station_type_choice" not in st.session_state:
    st.session_state.station_type_choice = "Charging Station"

tabs = st.tabs(["🏢 Stations", "🚌 Services", "🌐 EV Network"])

# ══════════════════════════════════════════
# TAB 0 — STATIONS
# ══════════════════════════════════════════
with tabs[0]:
    # Metric row
    cs_df_full = st.session_state.charging_stations.copy()
    bus_list   = st.session_state.bus_stations
    m1, m2, m3 = st.columns(3)
    with m1:
        st.markdown(f'<div class="metric-card"><div class="metric-value">{len(bus_list)}</div><div class="metric-label">Bus Stations</div></div>', unsafe_allow_html=True)
    with m2:
        st.markdown(f'<div class="metric-card"><div class="metric-value">{len(cs_df_full)}</div><div class="metric-label">Charging Stations</div></div>', unsafe_allow_html=True)
    with m3:
        total_chargers = int(cs_df_full['Number of Chargers'].sum()) if not cs_df_full.empty else 0
        st.markdown(f'<div class="metric-card"><div class="metric-value">{total_chargers}</div><div class="metric-label">Total Chargers</div></div>', unsafe_allow_html=True)

    search = st.text_input("🔍 Search station by name", placeholder="Type to filter…", key="station_search")

    # Tables
    bus_display = pd.DataFrame(bus_list).drop(columns=['ChargeFlag','BusStation'], errors='ignore')
    cs_display  = cs_df_full.copy()
    if search:
        if not bus_display.empty:
            bus_display = bus_display[bus_display['Station'].str.contains(search, case=False)]
        if not cs_display.empty:
            cs_display = cs_display[cs_display['Station Name'].str.contains(search, case=False)]

    with st.expander("🚏 Bus Stations", expanded=True):
        if bus_display.empty:
            st.info("No bus stations added yet.")
        else:
            st.dataframe(bus_display, use_container_width=True, hide_index=True)
            # Delete bus station
            del_bus = st.selectbox("Select bus station to delete", [""] + [s['Station'] for s in bus_list], key="del_bus_sel")
            if del_bus and st.button("🗑️ Delete Bus Station", key="del_bus_btn"):
                st.session_state.bus_stations = [s for s in st.session_state.bus_stations if s['Station'] != del_bus]
                st.success(f"Bus station '{del_bus}' deleted.")
                st.rerun()

    with st.expander("⚡ Charging Stations", expanded=True):
        if cs_display.empty:
            st.info("No charging stations added yet.")
        else:
            st.dataframe(cs_display, use_container_width=True, hide_index=True)
            # Delete charging station
            del_cs = st.selectbox("Select charging station to delete", [""] + cs_display['Station Name'].tolist(), key="del_cs_sel")
            if del_cs and st.button("🗑️ Delete Charging Station", key="del_cs_btn"):
                st.session_state.charging_stations = st.session_state.charging_stations[
                    st.session_state.charging_stations['Station Name'] != del_cs
                ].reset_index(drop=True)
                st.success(f"Charging station '{del_cs}' deleted.")
                st.rerun()

    st.divider()
    col1, col2 = st.columns(2)

    # ── ADD STATION ──
    with col1:
        st.markdown('<div class="section-header">➕ Add Station</div>', unsafe_allow_html=True)
        if "form_step" not in st.session_state:
            st.session_state.form_step = 0

        with st.form("dynamic_form"):
            if st.session_state.form_step == 0:
                selected_type = st.radio("Choose station type", ["Charging Station", "Bus Station"], horizontal=True)
                if st.form_submit_button("Next →"):
                    st.session_state.station_type_choice = selected_type
                    st.session_state.form_step = 1
                    st.rerun()
            elif st.session_state.form_step == 1:
                station_type = st.session_state.station_type_choice
                st.markdown(f"**Adding:** `{station_type}`")
                name = st.text_input("Station Name")
                c_lat, c_lon = st.columns(2)
                with c_lat:
                    lat = st.number_input("Latitude", format="%.6f")
                with c_lon:
                    lon = st.number_input("Longitude", format="%.6f")

                if station_type == "Charging Station":
                    c_cap, c_num = st.columns(2)
                    with c_cap:
                        cap = st.number_input("Capacity (kW)", min_value=0)
                    with c_num:
                        num = st.number_input("# Chargers", min_value=1, step=1)

                _, c_add, c_cancel = st.columns([10, 3, 2])
                with c_add:
                    submit = st.form_submit_button("Add")
                with c_cancel:
                    cancel = st.form_submit_button("Cancel")

                if submit:
                    if not name:
                        st.error("Station name is required.")
                    else:
                        name_clean = re.sub(r'\W+', '', name.lower())
                        if station_type == "Charging Station":
                            existing_names = st.session_state.charging_stations['Station Name'].str.lower().str.replace(r'\W+', '', regex=True)
                            if name_clean in existing_names.values:
                                st.error(f"Charging station '{name}' already exists.")
                            else:
                                st.session_state.charging_stations = pd.concat([
                                    st.session_state.charging_stations,
                                    pd.DataFrame([{'Station Name': name, 'Latitude': lat, 'Longitude': lon,
                                                   'Charging Capacity (kW)': cap, 'Number of Chargers': num}])
                                ], ignore_index=True)
                                st.success(f"✅ '{name}' added as charging station!")
                                st.session_state.form_step = 0
                                st.rerun()
                        else:
                            existing_names = [re.sub(r'\W+', '', n['Station'].lower()) for n in st.session_state.bus_stations]
                            if name_clean in existing_names:
                                st.error(f"Bus station '{name}' already exists.")
                            else:
                                st.session_state.bus_stations.append({
                                    'Station': name, 'Latitude': lat, 'Longitude': lon,
                                    'ChargeFlag': False, 'BusStation': True
                                })
                                st.success(f"✅ '{name}' added as bus station!")
                                st.session_state.form_step = 0
                                st.rerun()
                if cancel:
                    st.session_state.form_step = 0
                    st.rerun()

    # ── EDIT STATION ──
    with col2:
        st.markdown('<div class="section-header">✏️ Edit Charging Station</div>', unsafe_allow_html=True)
        if not cs_df_full.empty:
            selected = st.selectbox("Select station to edit", cs_df_full['Station Name'].tolist(), key="edit_cs_sel")
            station = st.session_state.charging_stations[
                st.session_state.charging_stations['Station Name'] == selected
            ].iloc[0]
            e1, e2 = st.columns(2)
            with e1:
                new_cap = st.number_input("Capacity (kW)", value=float(station['Charging Capacity (kW)']), key="edit_cap")
                new_lat = st.number_input("Latitude", value=float(station.get('Latitude', 0.0)), format="%.6f", key="edit_lat")
            with e2:
                new_num = st.number_input("# Chargers", value=int(station['Number of Chargers']), key="edit_num")
                new_lon = st.number_input("Longitude", value=float(station.get('Longitude', 0.0)), format="%.6f", key="edit_lon")
            if st.button("💾 Update Station", use_container_width=True):
                idx = st.session_state.charging_stations[
                    st.session_state.charging_stations['Station Name'] == selected
                ].index[0]
                st.session_state.charging_stations.at[idx, 'Charging Capacity (kW)'] = new_cap
                st.session_state.charging_stations.at[idx, 'Number of Chargers']     = new_num
                st.session_state.charging_stations.at[idx, 'Latitude']               = new_lat
                st.session_state.charging_stations.at[idx, 'Longitude']              = new_lon
                st.success(f"✅ Station '{selected}' updated.")
        else:
            st.info("Add a charging station first to edit it.")

# ══════════════════════════════════════════
# TAB 1 — SERVICES
# ══════════════════════════════════════════
with tabs[1]:
    svc_full = st.session_state.services.copy()

    # Metric row
    total_buses = int(svc_full['Number of Buses'].sum()) if not svc_full.empty and 'Number of Buses' in svc_full.columns else 0
    sm1, sm2, sm3 = st.columns(3)
    with sm1:
        st.markdown(f'<div class="metric-card"><div class="metric-value">{len(svc_full)}</div><div class="metric-label">Services</div></div>', unsafe_allow_html=True)
    with sm2:
        st.markdown(f'<div class="metric-card"><div class="metric-value">{total_buses}</div><div class="metric-label">Total Buses</div></div>', unsafe_allow_html=True)
    with sm3:
        total_km = round(svc_full['Distance (km)'].sum(), 1) if not svc_full.empty and 'Distance (km)' in svc_full.columns else 0
        st.markdown(f'<div class="metric-card"><div class="metric-value">{total_km}</div><div class="metric-label">Total Route km</div></div>', unsafe_allow_html=True)

    search_s = st.text_input("🔍 Search service by name", placeholder="Type to filter…", key="svc_search")
    srv_df = svc_full.copy()
    if search_s:
        srv_df = srv_df[srv_df['Service Name'].str.contains(search_s, case=False)]

    with st.expander("📋 All Services", expanded=True):
        if srv_df.empty:
            st.info("No services added yet.")
        else:
            display_cols = [c for c in ['Service Name','Bus Charging Capacity (kW)','Mileage (km/kWh)',
                            'Number of Buses','Distance (km)','Duration (mins)','Start Time'] if c in srv_df.columns]
            st.dataframe(srv_df[display_cols], use_container_width=True, hide_index=True)
            del_svc = st.selectbox("Select service to delete", [""] + srv_df['Service Name'].tolist(), key="del_svc_sel")
            if del_svc and st.button("🗑️ Delete Service", key="del_svc_btn"):
                st.session_state.services = st.session_state.services[
                    st.session_state.services['Service Name'] != del_svc
                ].reset_index(drop=True)
                st.success(f"Service '{del_svc}' deleted.")
                st.rerun()

    st.divider()
    c1, c2 = st.columns(2)

    # ── ADD SERVICE ──
    with c1:
        st.markdown('<div class="section-header">➕ Add Service</div>', unsafe_allow_html=True)
        with st.form("add_service"):
            svc_name  = st.text_input("Service Name", key="new_svc_name")
            f1, f2    = st.columns(2)
            with f1:
                svc_cap   = st.number_input("Bus Battery (kWh)", min_value=1, key="new_svc_cap")
                bus_count = st.number_input("Number of Buses", min_value=1, value=1, step=1, key="new_bus_count")
            with f2:
                mileage    = st.number_input("Mileage (km/kWh)", min_value=0.1, format="%.2f", key="new_svc_mileage")
                start_time = st.time_input("Start Time", key="new_start_time")

            btn_cols = st.columns(4)
            with btn_cols[0]:
                add_interval = st.form_submit_button("⏱ Intervals")
            with btn_cols[1]:
                add_buffer   = st.form_submit_button("🛡 Buffer")
            with btn_cols[2]:
                add_wait     = st.form_submit_button("⏳ Wait")
            with btn_cols[3]:
                submitted    = st.form_submit_button("✅ Add", type="primary")

        if submitted:
            if not st.session_state.temp_route:
                st.error("Add at least one station to the route first.")
            elif not (st.session_state.add_service_cond[0] and st.session_state.add_service_cond[2] and
                      (st.session_state.add_service_cond[1] or bus_count == 1)):
                st.error("Please set Buffer Time and Wait Time (and Departure Intervals if >1 bus).")
            else:
                with st.spinner("Fetching distances from Google Maps…"):
                    distance_time_matrix = [{"distance_m":0,"distance_text":"0 km","duration_s":0,"duration_text":"0 mins"}]
                    for i in range(len(st.session_state.temp_route) - 1):
                        origin      = (st.session_state.temp_route[i]['Latitude'],     st.session_state.temp_route[i]['Longitude'])
                        destination = (st.session_state.temp_route[i+1]['Latitude'],   st.session_state.temp_route[i+1]['Longitude'])
                        distance_time_matrix.append(getDistanceAndDurationGmaps(origin, destination))
                total_distance = sum(d["distance_m"] for d in distance_time_matrix) / 1000
                total_duration = sum(d["duration_s"] for d in distance_time_matrix) / 60

                st.session_state.pending_service.at[0,'Service Name']              = svc_name
                st.session_state.pending_service.at[0,'Bus Charging Capacity (kW)']= svc_cap
                st.session_state.pending_service.at[0,'Mileage (km/kWh)']          = mileage
                st.session_state.pending_service.at[0,'Number of Buses']           = bus_count
                st.session_state.pending_service.at[0,'Route Data']                = st.session_state.temp_route
                st.session_state.pending_service.at[0,'Start Time']                = start_time
                st.session_state.pending_service.at[0,'Distance (km)']             = total_distance
                st.session_state.pending_service.at[0,'Duration (mins)']           = total_duration
                st.session_state.pending_service.at[0,'Distance Time Matrix']      = distance_time_matrix

                st.session_state.temp_route = []
                _di = st.session_state.pending_service.at[0, 'Departure Intervals']
                if _di is None or (not isinstance(_di, list) and pd.isna(_di)):
                    st.session_state.pending_service.at[0, 'Departure Intervals'] = [0] * (bus_count - 1)
                _bt = st.session_state.pending_service.at[0, 'Buffer Times']
                if _bt is None or (not isinstance(_bt, list) and pd.isna(_bt)):
                    st.session_state.pending_service.at[0, 'Buffer Times'] = [0] * bus_count
                _wt = st.session_state.pending_service.at[0, 'Wait Time']
                if _wt is None or (not isinstance(_wt, list) and pd.isna(_wt)):
                    st.session_state.pending_service.at[0, 'Wait Time'] = [0] * bus_count

                st.session_state.services = pd.concat([
                    st.session_state.services,
                    st.session_state.pending_service
                ], ignore_index=True)
                st.success(f"✅ Service '{svc_name}' added with {bus_count} bus(es).")
                st.session_state.pending_service = pd.DataFrame(columns=[
                    'Service Name','Bus Charging Capacity (kW)','Mileage (km/kWh)',
                    'Number of Buses','Departure Intervals','Route Data','Start Time',
                    'Buffer Times','Distance (km)','Duration (mins)','Distance Time Matrix','Wait Time'
                ])
                st.session_state.add_service_cond = [False, False, False]
                st.rerun()

        if add_interval:
            if bus_count > 1:
                st.session_state.show_interval_modal = True
                st.session_state.show_interval_modal_dismissed = False
                st.session_state.edit_svc = False
            else:
                st.error("Need at least 2 buses to set departure intervals.")
        if add_buffer:
            st.session_state.show_buffer_modal = True
            st.session_state.show_buffer_modal_dismissed = False
            st.session_state.edit_svc = False
        if add_wait:
            st.session_state.show_wait_modal = True
            st.session_state.show_wait_modal_dismissed = False
            st.session_state.edit_svc = False

        # Route builder buttons
        rb1, rb2 = st.columns(2)
        with rb1:
            if st.button("🚏 Add Bus Station to Route", key="add_bus_station_to_route", use_container_width=True):
                st.session_state.show_add_ext_busStation_modal_dismissed = False
                st.session_state.show_add_ext_busStation_modal = True
        with rb2:
            if st.button("⚡ Add Charging Station to Route", key="add_charging_station_to_route", use_container_width=True):
                st.session_state.show_add_charger_station_modal_dismissed = False
                st.session_state.show_add_charger_station_modal = True

        # Route preview
        if st.session_state.temp_route:
            st.markdown('<div class="section-header">🗺️ Current Route</div>', unsafe_allow_html=True)
            if st.button("🔄 Reverse Route", key="rev_add"):
                st.session_state.temp_route.reverse()
                st.rerun()
            for i, stop in enumerate(st.session_state.temp_route):
                badge = '<span class="badge-bus">Bus Stand</span>' if stop['BusStation'] else '<span class="badge-charger">Charger</span>'
                charge_icon = "✅" if stop['ChargeFlag'] else "❌"
                st.markdown(f"""
                <div class="stop-card">
                  <div style="display:flex;justify-content:space-between;align-items:center">
                    <span class="stop-name">#{i+1} &nbsp; {stop['Station']}</span>
                    {badge}
                  </div>
                  <div class="stop-meta">
                    📍 {stop['Latitude']:.4f}, {stop['Longitude']:.4f} &nbsp;|&nbsp; Charge: {charge_icon}
                  </div>
                </div>
                """, unsafe_allow_html=True)
                rc1, rc2, rc3 = st.columns([1, 1, 1])
                with rc1:
                    if i > 0 and st.button("⬆", key=f"up_{i}"):
                        st.session_state.temp_route[i], st.session_state.temp_route[i-1] = st.session_state.temp_route[i-1], st.session_state.temp_route[i]
                        st.rerun()
                with rc2:
                    if i < len(st.session_state.temp_route) - 1 and st.button("⬇", key=f"down_{i}"):
                        st.session_state.temp_route[i], st.session_state.temp_route[i+1] = st.session_state.temp_route[i+1], st.session_state.temp_route[i]
                        st.rerun()
                with rc3:
                    if st.button("🗑️", key=f"delete_{i}"):
                        st.session_state.temp_route.pop(i)
                        st.rerun()

    # ── EDIT SERVICE ──
    with c2:
        st.markdown('<div class="section-header">✏️ Edit Service</div>', unsafe_allow_html=True)
        if not srv_df.empty:
            selected_svc = st.selectbox("Select service to edit", srv_df['Service Name'].tolist(), key="edit_svc_select")
            svc = st.session_state.services[st.session_state.services['Service Name'] == selected_svc].iloc[0]

            if selected_svc != st.session_state.prev_selected_svc:
                st.session_state.edit_departure_intervals = svc['Departure Intervals'].copy() if isinstance(svc['Departure Intervals'], list) else None
                st.session_state.temp_edit_route          = svc['Route Data'].copy() if isinstance(svc['Route Data'], list) else []
                st.session_state.edit_buffer_times        = svc['Buffer Times'].copy() if isinstance(svc['Buffer Times'], list) else None
                st.session_state.edit_wait_times          = svc['Wait Time'].copy() if isinstance(svc['Wait Time'], list) else None
                st.session_state.prev_selected_svc        = selected_svc

            with st.form("edit_service"):
                ef1, ef2 = st.columns(2)
                with ef1:
                    edit_svc_cap  = st.number_input("Bus Battery (kWh)", min_value=1, key="edit_svc_cap",   value=int(svc['Bus Charging Capacity (kW)']))
                    edit_bus_count= st.number_input("Number of Buses",   min_value=1, step=1, key="edit_bus_count", value=int(svc['Number of Buses']))
                with ef2:
                    edit_mileage  = st.number_input("Mileage (km/kWh)", min_value=0.1, format="%.2f", key="edit_svc_mileage", value=float(svc['Mileage (km/kWh)']))
                    _st_val = svc['Start Time']
                    if isinstance(_st_val, str):
                        _st_val = datetime.strptime(_st_val.split("T")[-1][:5], "%H:%M").time()
                    edit_start_time = st.time_input("Start Time", value=_st_val, key="edit_start_time")

                eb1, eb2, eb3, eb4 = st.columns(4)
                with eb1:
                    edit_interval = st.form_submit_button("⏱ Intervals")
                with eb2:
                    edit_buffer   = st.form_submit_button("🛡 Buffer")
                with eb3:
                    edit_wait     = st.form_submit_button("⏳ Wait")
                with eb4:
                    editService   = st.form_submit_button("💾 Save", type="primary")

                if editService:
                    if not st.session_state.temp_edit_route:
                        st.error("Route cannot be empty.")
                    else:
                        with st.spinner("Fetching distances…"):
                            distance_time_matrix = [{"distance_m":0,"distance_text":"0 km","duration_s":0,"duration_text":"0 mins"}]
                            for i in range(len(st.session_state.temp_edit_route) - 1):
                                origin      = (st.session_state.temp_edit_route[i]['Latitude'],   st.session_state.temp_edit_route[i]['Longitude'])
                                destination = (st.session_state.temp_edit_route[i+1]['Latitude'], st.session_state.temp_edit_route[i+1]['Longitude'])
                                distance_time_matrix.append(getDistanceAndDurationGmaps(origin, destination))
                        total_distance = sum(d["distance_m"] for d in distance_time_matrix) / 1000
                        total_duration = sum(d["duration_s"] for d in distance_time_matrix) / 60

                        idx = st.session_state.services[st.session_state.services['Service Name'] == selected_svc].index[0]
                        st.session_state.services.at[idx, 'Bus Charging Capacity (kW)'] = edit_svc_cap
                        st.session_state.services.at[idx, 'Mileage (km/kWh)']           = edit_mileage
                        st.session_state.services.at[idx, 'Number of Buses']            = edit_bus_count
                        st.session_state.services.at[idx, 'Route Data']                 = st.session_state.temp_edit_route
                        st.session_state.services.at[idx, 'Start Time']                 = edit_start_time
                        st.session_state.services.at[idx, 'Distance (km)']              = total_distance
                        st.session_state.services.at[idx, 'Duration (mins)']            = total_duration
                        st.session_state.services.at[idx, 'Distance Time Matrix']       = distance_time_matrix

                        if st.session_state.edit_departure_intervals is None:
                            st.session_state.edit_departure_intervals = [0] * (edit_bus_count - 1)
                        if st.session_state.edit_buffer_times is None:
                            st.session_state.edit_buffer_times = [0] * edit_bus_count
                        if st.session_state.edit_wait_times is None:
                            st.session_state.edit_wait_times = [0] * edit_bus_count

                        st.session_state.services.at[idx, 'Departure Intervals'] = st.session_state.edit_departure_intervals
                        st.session_state.services.at[idx, 'Buffer Times']        = st.session_state.edit_buffer_times
                        st.session_state.services.at[idx, 'Wait Time']           = st.session_state.edit_wait_times
                        st.success(f"✅ Service '{selected_svc}' updated.")
                        st.session_state.temp_edit_route = []
                        st.rerun()

                if edit_interval:
                    if edit_bus_count > 1:
                        st.session_state.show_interval_modal = True
                        st.session_state.show_interval_modal_dismissed = False
                        st.session_state.edit_svc = True
                    else:
                        st.error("Need at least 2 buses.")
                if edit_buffer:
                    st.session_state.show_buffer_modal = True
                    st.session_state.show_buffer_modal_dismissed = False
                    st.session_state.edit_svc = True
                if edit_wait:
                    st.session_state.show_wait_modal = True
                    st.session_state.show_wait_modal_dismissed = False
                    st.session_state.edit_svc = True

            # Edit route buttons
            erb1, erb2 = st.columns(2)
            with erb1:
                if st.button("🚏 Add Bus Station", key="add_bus_station_to_route_edit", use_container_width=True):
                    st.session_state.show_add_ext_busStation_modal_dismissed = False
                    st.session_state.edit_route_data = True
                    st.session_state.show_add_ext_busStation_modal = True
            with erb2:
                if st.button("⚡ Add Charging Station", key="add_charging_station_to_route_edit", use_container_width=True):
                    st.session_state.show_add_charger_station_modal_dismissed = False
                    st.session_state.edit_route_data = True
                    st.session_state.show_add_charger_station_modal = True

            # Edit route preview
            if st.session_state.temp_edit_route:
                st.markdown('<div class="section-header">🗺️ Edit Route</div>', unsafe_allow_html=True)
                if st.button("🔄 Reverse Route", key="edit_reverse"):
                    st.session_state.temp_edit_route.reverse()
                    st.rerun()
                for i, stop in enumerate(st.session_state.temp_edit_route):
                    badge = '<span class="badge-bus">Bus Stand</span>' if stop['BusStation'] else '<span class="badge-charger">Charger</span>'
                    charge_icon = "✅" if stop['ChargeFlag'] else "❌"
                    st.markdown(f"""
                    <div class="stop-card">
                      <div style="display:flex;justify-content:space-between;align-items:center">
                        <span class="stop-name">#{i+1} &nbsp; {stop['Station']}</span>
                        {badge}
                      </div>
                      <div class="stop-meta">
                        📍 {stop['Latitude']:.4f}, {stop['Longitude']:.4f} &nbsp;|&nbsp; Charge: {charge_icon}
                      </div>
                    </div>
                    """, unsafe_allow_html=True)
                    ec1, ec2, ec3 = st.columns([1,1,1])
                    with ec1:
                        if i > 0 and st.button("⬆", key=f"up{i}"):
                            st.session_state.temp_edit_route[i], st.session_state.temp_edit_route[i-1] = st.session_state.temp_edit_route[i-1], st.session_state.temp_edit_route[i]
                            st.rerun()
                    with ec2:
                        if i < len(st.session_state.temp_edit_route)-1 and st.button("⬇", key=f"down{i}"):
                            st.session_state.temp_edit_route[i], st.session_state.temp_edit_route[i+1] = st.session_state.temp_edit_route[i+1], st.session_state.temp_edit_route[i]
                            st.rerun()
                    with ec3:
                        if st.button("🗑️", key=f"delete{i}"):
                            st.session_state.temp_edit_route.pop(i)
                            st.rerun()

            # ── Modals triggered from edit column ──
            if st.session_state.get("show_add_ext_busStation_modal", False) and not st.session_state.get("show_add_ext_busStation_modal_dismissed", False):
                @st.dialog("Add Existing Bus Station")
                def bus_station_modal():
                    stations = st.session_state.bus_stations
                    if not stations:
                        st.warning("No bus stations saved yet.")
                        if st.button("Close"):
                            st.session_state.show_add_ext_busStation_modal = False
                            st.rerun()
                        return
                    search_query  = st.text_input("Search")
                    filtered      = [s for s in stations if search_query.lower() in s['Station'].lower()]
                    if not filtered:
                        st.info("No matching stations.")
                        if st.button("Close"):
                            st.session_state.show_add_ext_busStation_modal = False
                            st.rerun()
                        return
                    station_names = [s['Station'] for s in filtered]
                    selected_name = st.selectbox("Select Station", station_names)
                    selected_s    = next((s for s in filtered if s['Station'] == selected_name), None)
                    if selected_s:
                        st.write(f"📍 {selected_s['Latitude']}, {selected_s['Longitude']}")
                        if st.button("Add to Route"):
                            if st.session_state.edit_route_data:
                                st.session_state.temp_edit_route.append(selected_s.copy())
                            else:
                                st.session_state.temp_route.append(selected_s.copy())
                            st.session_state.edit_route_data = False
                            st.session_state.show_add_ext_busStation_modal = False
                            st.rerun()
                        if st.button("Cancel"):
                            st.session_state.show_add_ext_busStation_modal = False
                            st.rerun()
                st.session_state.show_add_ext_busStation_modal_dismissed = True
                bus_station_modal()

            if st.session_state.get("show_add_charger_station_modal", False) and not st.session_state.get("show_add_charger_station_modal_dismissed", False):
                @st.dialog("Add Charging Station to Route")
                def charger_station_modal():
                    chargers_df = st.session_state.charging_stations
                    if chargers_df.empty:
                        st.warning("No charging stations. Add one in the Stations tab.")
                        if st.button("Close"):
                            st.session_state.show_add_charger_station_modal = False
                            st.rerun()
                        return
                    station_selected = st.selectbox("Select Charging Station", chargers_df['Station Name'].tolist())
                    lat = float(chargers_df.loc[chargers_df['Station Name'] == station_selected, 'Latitude'])
                    lon = float(chargers_df.loc[chargers_df['Station Name'] == station_selected, 'Longitude'])
                    st.write(f"📍 Lat: {lat}, Lon: {lon}")
                    if st.button("Add to Route"):
                        entry = {"Station": station_selected, "Latitude": lat, "Longitude": lon, "ChargeFlag": True, "BusStation": False}
                        if st.session_state.edit_route_data:
                            st.session_state.temp_edit_route.append(entry)
                        else:
                            st.session_state.temp_route.append(entry)
                        st.session_state.edit_route_data = False
                        st.session_state.show_add_charger_station_modal = False
                        st.rerun()
                    if st.button("Cancel"):
                        st.session_state.show_add_charger_station_modal = False
                        st.rerun()
                st.session_state.show_add_charger_station_modal_dismissed = True
                charger_station_modal()
        else:
            st.info("No services available to edit. Add a service first.")

    # ── Interval / Buffer / Wait modals ──
    if st.session_state.get('show_interval_modal', False) and not st.session_state.get('show_interval_modal_dismissed', False):
        @st.dialog("Set Departure Intervals")
        def interval_modal():
            intervals = []
            if not st.session_state.edit_svc:
                for i in range(1, bus_count):
                    val = st.number_input(f"Interval Bus {i} → {i+1} (min)", min_value=0, key=f"modal_interval_{i}")
                    intervals.append(val)
                if st.button("Confirm & Save"):
                    intervals.insert(0, 0)
                    st.session_state.pending_service.at[0, 'Departure Intervals'] = intervals
                    st.session_state.show_interval_modal = False
                    st.session_state.add_service_cond[1] = True
                    st.rerun()
                if st.button("Cancel"):
                    st.session_state.show_interval_modal = False
                    st.rerun()
            else:
                for i in range(1, edit_bus_count):
                    default = st.session_state.edit_departure_intervals[i] if st.session_state.edit_departure_intervals and i < len(st.session_state.edit_departure_intervals) else 0
                    val = st.number_input(f"Interval Bus {i} → {i+1} (min)", min_value=0, key=f"modal_interval{i}", value=default)
                    intervals.append(val)
                if st.button("Confirm & Save "):
                    intervals.insert(0, 0)
                    st.session_state.edit_departure_intervals = intervals
                    st.session_state.show_interval_modal = False
                    st.rerun()
                if st.button("Cancel "):
                    st.session_state.show_interval_modal = False
                    st.rerun()
        st.session_state.show_interval_modal_dismissed = True
        interval_modal()

    if st.session_state.get("show_buffer_modal", False) and not st.session_state.get("show_buffer_modal_dismissed", False):
        @st.dialog("Set Buffer Times")
        def buffer_modal():
            buffers = []
            if not st.session_state.edit_svc:
                for i in range(bus_count):
                    buffers.append(st.number_input(f"Buffer for Bus {i+1} (min)", min_value=0, key=f"modal_buffer_{i}"))
                if st.button("Confirm & Save"):
                    st.session_state.pending_service.at[0, 'Buffer Times'] = buffers
                    st.session_state.show_buffer_modal = False
                    st.session_state.show_buffer_modal_dismissed = True
                    st.session_state.add_service_cond[0] = True
                    st.rerun()
                if st.button("Cancel"):
                    st.session_state.show_buffer_modal = False
                    st.rerun()
            else:
                for i in range(edit_bus_count):
                    default = st.session_state.edit_buffer_times[i] if st.session_state.edit_buffer_times and i < len(st.session_state.edit_buffer_times) else 0
                    buffers.append(st.number_input(f"Buffer for Bus {i+1} (min)", min_value=0, key=f"modal_buffer{i}", value=default))
                if st.button("Confirm & Save "):
                    st.session_state.edit_buffer_times = buffers
                    st.session_state.show_buffer_modal = False
                    st.session_state.show_buffer_modal_dismissed = True
                    st.rerun()
                if st.button("Cancel "):
                    st.session_state.show_buffer_modal = False
        st.session_state.show_buffer_modal_dismissed = True
        buffer_modal()

    if st.session_state.get("show_wait_modal", False) and not st.session_state.get("show_wait_modal_dismissed", False):
        @st.dialog("Set Wait Times")
        def wait_modal():
            wait_times = []
            if not st.session_state.edit_svc:
                for i in range(bus_count):
                    wait_times.append(st.number_input(f"Wait Time for Bus {i+1} (min)", min_value=0, key=f"modal_wait_{i}"))
                if st.button("Confirm & Save"):
                    st.session_state.pending_service.at[0, 'Wait Time'] = wait_times
                    st.session_state.show_wait_modal = False
                    st.session_state.show_wait_modal_dismissed = True
                    st.session_state.add_service_cond[2] = True
                    st.rerun()
                if st.button("Cancel"):
                    st.session_state.show_wait_modal = False
                    st.rerun()
            else:
                for i in range(edit_bus_count):
                    wait_times.append(st.number_input(f"Wait Time for Bus {i+1} (min)", min_value=0, key=f"modal_wait{i}"))
                if st.button("Confirm & Save "):
                    st.session_state.edit_wait_times = wait_times
                    st.session_state.show_wait_modal = False
                    st.session_state.show_wait_modal_dismissed = True
                    st.rerun()
                if st.button("Cancel "):
                    st.session_state.show_wait_modal = False
        st.session_state.show_wait_modal_dismissed = True
        wait_modal()

    # ── Service route map viewer ──
    st.divider()
    st.markdown('<div class="section-header">🗺️ Service Route Viewer</div>', unsafe_allow_html=True)
    svc_names = st.session_state.services['Service Name'].tolist()
    if svc_names:
        selected_srv = st.selectbox("Select service to view", svc_names, key="srv_view_sel")
        if selected_srv:
            svc_v = st.session_state.services[st.session_state.services['Service Name'] == selected_srv].iloc[0]
            route_v = pd.DataFrame(svc_v['Route Data'])

            distances  = [i['distance_text'] for i in svc_v['Distance Time Matrix']]
            est_times  = [i['duration_text']  for i in svc_v['Distance Time Matrix']]
            route_v['Distance from Prev'] = distances
            route_v['Est. Time from Prev'] = est_times
            route_v['Type'] = route_v['BusStation'].apply(lambda x: "Bus Station" if x else "Charger")

            rv1, rv2 = st.columns([3, 2])
            with rv1:
                st.dataframe(
                    route_v[['Station','Distance from Prev','Est. Time from Prev','ChargeFlag','Type']],
                    use_container_width=True, hide_index=True
                )
                if st.button("📋 Load Route into Editor", key="load_route_btn"):
                    st.session_state.temp_route = svc_v['Route Data'].copy()
                    st.success("Route loaded. Switch to Add Service to modify.")
                    st.rerun()
            with rv2:
                route_data_v = svc_v['Route Data']
                if route_data_v:
                    route_data_hash = get_route_data_hash(route_data_v)
                    if route_data_hash not in st.session_state.route_data_cache:
                        st.session_state.route_data_cache[route_data_hash] = route_data_v
                    path_segments = get_directions_path(route_data_hash, st.session_state.route_data_cache)
                    m = build_folium_map(route_data_v, path_segments=path_segments)
                    st_folium(m, width=420, height=380)
    else:
        st.info("Add a service to see its route on the map.")

# ══════════════════════════════════════════
# TAB 2 — EV NETWORK
# ══════════════════════════════════════════
with tabs[2]:
    net_all = st.session_state.networks.copy()

    # Metric row
    n_success = int((net_all['Status'] == 'SUCCESS').sum()) if not net_all.empty and 'Status' in net_all.columns else 0
    n_fail    = len(net_all) - n_success if not net_all.empty else 0
    nm1, nm2, nm3 = st.columns(3)
    with nm1:
        st.markdown(f'<div class="metric-card"><div class="metric-value">{len(net_all)}</div><div class="metric-label">Total Networks</div></div>', unsafe_allow_html=True)
    with nm2:
        st.markdown(f'<div class="metric-card"><div class="metric-value" style="color:#51cf66">{n_success}</div><div class="metric-label">Successful</div></div>', unsafe_allow_html=True)
    with nm3:
        st.markdown(f'<div class="metric-card"><div class="metric-value" style="color:#ff6b6b">{n_fail}</div><div class="metric-label">Failed</div></div>', unsafe_allow_html=True)

    search_n = st.text_input("🔍 Search network by name", placeholder="Type to filter…", key="net_search")
    net_df = net_all.copy()
    if search_n:
        net_df = net_df[net_df['Network Name'].str.contains(search_n, case=False)]

    with st.expander("📋 All Networks", expanded=True):
        if net_df.empty:
            st.info("No networks yet.")
        else:
            disp = net_df[['Network Name','Tolerance (%)','Status']].copy()
            st.dataframe(disp, use_container_width=True, hide_index=True)
            del_net = st.selectbox("Select network to delete", [""] + net_df['Network Name'].tolist(), key="del_net_sel")
            if del_net and st.button("🗑️ Delete Network", key="del_net_btn"):
                st.session_state.networks = st.session_state.networks[
                    st.session_state.networks['Network Name'] != del_net
                ].reset_index(drop=True)
                st.success(f"Network '{del_net}' deleted.")
                st.rerun()

    st.divider()
    na1, na2 = st.columns([1, 1])

    # ── ADD NETWORK ──
    with na1:
        st.markdown('<div class="section-header">➕ Add & Run Network</div>', unsafe_allow_html=True)
        with st.form("add_network"):
            net_name = st.text_input("Network Name", key="new_net_name")
            tol      = st.number_input("Tolerance (%)", min_value=0.0, format="%.2f", key="new_net_tol")
            svcs     = st.multiselect("Select Services", st.session_state.services['Service Name'].tolist(), key="new_net_svcs")

            if st.form_submit_button("▶️ Add & Run Simulation", type="primary"):
                if not net_name:
                    st.error("Network name is required.")
                elif not svcs:
                    st.error("Select at least one service.")
                elif st.session_state.charging_stations.empty:
                    st.error("Add at least one charging station first.")
                else:
                    services_subset = get_services_by_names(svcs)
                    with st.spinner("Running allocation simulation…"):
                        bus_schedule, charging_events, alloc_df, simulated_events, success = simulate_bus_trips(
                            services_subset, tol, charging_stations_df=st.session_state.charging_stations
                        )
                    if not success:
                        st.error("❌ Allocation failed — charger overlap detected. Network not saved.")
                    else:
                        st.session_state.networks = pd.concat([
                            st.session_state.networks,
                            pd.DataFrame([{
                                'Network Name': net_name, 'Tolerance (%)': tol,
                                'Services': svcs, 'Status': 'SUCCESS',
                                'Allocations': alloc_df, 'Bus Schedule': bus_schedule,
                                'Logs': [], 'Charging Events': charging_events
                            }])
                        ], ignore_index=True)
                        st.success(f"✅ Network '{net_name}' created successfully.")
                        st.rerun()

    # ── EDIT NETWORK ──
    with na2:
        st.markdown('<div class="section-header">✏️ Edit Network</div>', unsafe_allow_html=True)
        if not net_all.empty:
            net_names = net_all['Network Name'].tolist()
            selected_edit_net = st.selectbox("Select network to edit", net_names, key="edit_net")
            net_row = st.session_state.networks[st.session_state.networks['Network Name'] == selected_edit_net].iloc[0]

            edit_name = st.text_input("Network Name", value=net_row['Network Name'], key="edit_name")
            edit_tol  = st.number_input("Tolerance (%)", min_value=0.0, value=float(net_row['Tolerance (%)']), key="edit_tol")

            services_list = []
            if isinstance(net_row['Services'], list):
                if len(net_row['Services']) > 0 and isinstance(net_row['Services'][0], dict):
                    services_list = [s.get('Service Name', '') for s in net_row['Services']]
                else:
                    services_list = [str(s) for s in net_row['Services']]
            elif isinstance(net_row['Services'], pd.DataFrame):
                services_list = net_row['Services']['Service Name'].tolist()

            all_services = st.session_state.services['Service Name'].tolist()
            edit_svcs = st.multiselect("Select Services", all_services, default=services_list, key="edit_svcs")

            if st.button("💾 Save & Re-run Network", use_container_width=True, key="save_net_btn"):
                idx             = st.session_state.networks[st.session_state.networks['Network Name'] == selected_edit_net].index[0]
                services_subset = get_services_by_names(edit_svcs)
                with st.spinner("Re-running simulation…"):
                    success = update_network(idx, edit_name, edit_tol, services_subset)
                if success:
                    st.success(f"✅ Network '{edit_name}' updated.")
                    st.rerun()
                else:
                    st.error("❌ Allocation failed. No changes saved.")
        else:
            st.info("No networks to edit yet.")

    # ── Results dashboard ──
    st.divider()
    if not net_df.empty:
        st.markdown('<div class="section-header">📊 Allocation Results</div>', unsafe_allow_html=True)
        selected_net = st.selectbox("Select network to inspect", net_df['Network Name'].tolist(), key="alloc_net_view")
        network      = st.session_state.networks[st.session_state.networks['Network Name'] == selected_net].iloc[0]

        alloc_df       = pd.DataFrame(network['Allocations']) if not isinstance(network['Allocations'], pd.DataFrame) else network['Allocations']
        charging_events= network.get('Charging Events', [])
        bus_schedule   = network.get('Bus Schedule', [])
        bus_df         = pd.DataFrame(bus_schedule)

        res_t1, res_t2 = st.tabs(["Charging Allocations", "Bus Schedule"])

        with res_t1:
            if isinstance(alloc_df, pd.DataFrame) and not alloc_df.empty:
                enrich_map = {(e['station'], e['bus_name']): e for e in charging_events}
                alloc_df_display = alloc_df.copy()
                alloc_df_display['Battery % After'] = alloc_df_display.apply(
                    lambda row: f"{enrich_map.get((row['Station Name'], row['Bus Name']), {}).get('battery_after_pct', 0):.1f}%", axis=1
                )
                alloc_df_display['kWh After'] = alloc_df_display.apply(
                    lambda row: round(enrich_map.get((row['Station Name'], row['Bus Name']), {}).get('battery_after_kwh', 0), 2), axis=1
                )
                st.dataframe(alloc_df_display, use_container_width=True, hide_index=True)
            else:
                st.info("No allocation data for this network.")

        with res_t2:
            if not bus_df.empty:
                invalid_arr = bus_df[bus_df['arrival'] == "--"].copy()
                valid_arr   = bus_df[bus_df['arrival'] != "--"].copy()
                valid_arr['arrival'] = pd.to_datetime(valid_arr['arrival'], format="%H:%M", errors='coerce')
                valid_arr = valid_arr.sort_values('arrival')
                valid_arr['arrival'] = valid_arr['arrival'].dt.strftime('%H:%M')
                sorted_bus_df = pd.concat([invalid_arr, valid_arr], ignore_index=True)
                st.dataframe(sorted_bus_df, use_container_width=True, hide_index=True)
            else:
                st.info("No bus schedule data.")

        # Charging demand summary
        st.divider()
        st.markdown('<div class="section-header">🔋 Charging Demand Summary (All Networks)</div>', unsafe_allow_html=True)
        all_events = []
        if 'Charging Events' in net_df.columns:
            for _evts in net_df['Charging Events']:
                if isinstance(_evts, list):
                    all_events.extend(_evts)

        if all_events:
            ev_df    = pd.DataFrame(all_events)
            cs_cap   = {row['Station Name']: row['Charging Capacity (kW)'] for _, row in st.session_state.charging_stations.iterrows()}
            ev_df['Duration_Hours'] = ev_df['energy_to_charge'] / ev_df['station'].map(cs_cap)
            bus_counts  = ev_df.groupby('station')['bus_name'].nunique().rename("Buses Charged")
            total_kwh   = ev_df.groupby('station')['energy_to_charge'].sum().rename("Total kWh")
            hours_util  = ev_df.groupby('station')['Duration_Hours'].sum().rename("Hours Utilized")
            summary_df  = pd.concat([bus_counts, total_kwh, hours_util], axis=1).reset_index().rename(columns={'station':'Station Name'})
            summary_df  = summary_df.merge(st.session_state.charging_stations[['Station Name','Number of Chargers']], on='Station Name', how='left')
            summary_df['Utilization (%)'] = (summary_df['Hours Utilized'] / (16 * summary_df['Number of Chargers']) * 100).round(2)
            st.dataframe(summary_df[['Station Name','Buses Charged','Total kWh','Hours Utilized','Utilization (%)']], use_container_width=True, hide_index=True)
        else:
            st.info("No charging data across networks yet.")

        # Gantt chart
        st.divider()
        st.markdown('<div class="section-header">📅 Charger Timeline (Gantt)</div>', unsafe_allow_html=True)
        if charging_events:
            station_names = sorted({e['station'] for e in charging_events})
            sel_station   = st.selectbox("Select Station", station_names, key="gantt_station")
            total_chargers= int(st.session_state.charging_stations[
                st.session_state.charging_stations['Station Name'] == sel_station
            ].iloc[0]["Number of Chargers"])

            rows = []
            for charger_num in range(1, total_chargers + 1):
                charger_key = str(charger_num)
                events      = [e for e in charging_events if e['station'] == sel_station and str(e.get('charger_num')) == charger_key]
                if not events:
                    rows.append({"Charger": f"Charger {charger_key}", "Start": to_24h_datetime(0), "Finish": to_24h_datetime(1), "Service": "Unused"})
                else:
                    for event in events:
                        start_min = to_24h_reference(event["start_time"])
                        end_min   = to_24h_reference(event["end_time"])
                        if end_min < start_min:
                            end_min += 1440
                        rows.append({"Charger": f"Charger {charger_key}", "Start": to_24h_datetime(start_min), "Finish": to_24h_datetime(end_min), "Service": event.get("service","Unknown")})

            gantt_df = pd.DataFrame(rows)
            fig = px.timeline(gantt_df, x_start="Start", x_end="Finish", y="Charger", color="Service",
                              title=f"Charger Allocation — {sel_station}",
                              color_discrete_sequence=px.colors.qualitative.Vivid)
            fig.update_layout(
                xaxis=dict(tickformat="%H:%M", title="Time of Day"),
                plot_bgcolor="#1a1d27", paper_bgcolor="#1a1d27",
                font=dict(color="#cdd9f0"), title_font_size=14,
                legend=dict(bgcolor="#1a1d27", bordercolor="#2e3250")
            )
            fig.update_yaxes(autorange="reversed")
            fig.update_traces(marker_line_color='#2e3250', marker_line_width=1)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Run a network to see the charger timeline.")
