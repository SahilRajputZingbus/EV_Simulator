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

st.set_page_config(page_title="EV Network Planning", layout="wide")

gmaps = googlemaps.Client(key="AIzaSyCcdyw_-0olqzOu9vSdDQBgZvaTw8GGLbc")

MONGO_URI = "mongodb+srv://sahilrajput:NM09NKfilkALYovi@cluster0.cybby1b.mongodb.net/"

@st.cache_resource
def get_mongo_client():
    return MongoClient(MONGO_URI)
    
db = get_mongo_client()["ev_simulator"]
collection = db["sessions"]


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
        with open("logs.txt", "a") as f:
            f.write(f"{key} :\n{(type(cleaned[key]))}\n\n")

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
                'Start Time', 'Distance (km)', 'Duration (mins)', 'Distance Time Matrix','Buffer Times'
            ]) if isinstance(val, list) else pd.DataFrame()

        elif key == "networks":
            st.session_state[key] = pd.DataFrame(val, columns=[
                'Network Name', 'Tolerance (%)', 'Services',  'Status', 'Allocations', 'Logs', 'Charging Events','Bus Schedule'
            ]) if isinstance(val, list) else pd.DataFrame()


        else:
            st.session_state[key] = val if val is not None else ({} if key == "route_data_cache" else [])
            
def save_session_to_mongo(user_id="default_user"):
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
            'Departure Intervals', 'Route Data', 'Start Time', 'Distance (km)', 'Duration (mins)','Distance Time Matrix'
        ])
    if "networks" not in st.session_state:
        st.session_state.networks = pd.DataFrame(columns=[
            'Network Name', 'Tolerance (%)', 'Services',
            'Status', 'Allocations', 'Logs'
        ])
    if "pending_service" not in st.session_state:
        st.session_state.pending_service = pd.DataFrame(columns=[
            'Service Name', 'Bus Charging Capacity (kW)', 'Mileage (km/kWh)',
            'Number of Buses', 'Departure Intervals', 'Route Data', 'Start Time','Buffer Times','Distance (km)', 'Duration (mins)', 'Distance Time Matrix'
        ])
    if "temp_route" not in st.session_state:
        st.session_state.temp_route = []
    if "temp_edit_route" not in st.session_state:
        st.session_state.temp_edit_route = []
    if "route_data_cache" not in st.session_state:
        st.session_state.route_data_cache = {}
    if "edit_departure_intervals" not in st.session_state:   
        st.session_state.edit_departure_intervals = []
    if "edit_buffer_times" not in st.session_state:
        st.session_state.edit_buffer_times = []
    if "edit_svc" not in st.session_state:
        st.session_state.edit_svc=False
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
        st.write(service)
        buffer_times = service['Buffer Times']

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
                    start_slot, end_slot = get_slot_range(arrival_min, charge_minutes + 5)
                    station_name = next_station['Station']
                    allocated = False

                    for charger_num, events in simulated_events[station_name].items():
                        overlap = [
                            e for e in events
                            if not (end_slot <= e['start'] or start_slot >= e['end'])
                        ]
                        if not overlap:
                            events.append({'start': start_slot, 'end': end_slot, 'bus': bus_name})
                            charging_events.append({
                                'station': station_name,
                                'bus_name': bus_name,
                                'arrival': minutes_to_str(arrival_min),
                                'start_time': minutes_to_str(start_slot),
                                'end_time': minutes_to_str(end_slot),
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
                                "Slot Start": minutes_to_str(start_slot),
                                "Slot End": minutes_to_str(end_slot),
                                "Battery % on Arrival": f"{battery / bus_capacity_kwh * 100:.1f}%",
                                "Battery % After Charging": f"{(battery + needed) / bus_capacity_kwh * 100:.1f}%",
                                "Battery After Charging (kWh)": round(min(battery + needed, bus_capacity_kwh), 2)
                            })
                            battery = min(battery + needed, bus_capacity_kwh)
                            departure_min = end_slot
                            allocated = True
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
    /* Get the tab container and make it flex */
    .centered-header {
        text-align: center;
        font-size: 2em;
        margin-bottom: 1rem;
    }
    div[data-baseweb="tab-list"] {
        display: flex;
        justify-content: space-evenly;
    }
    
    /* Make each tab fill space equally */
    button[role="tab"] {
        flex-grow: 1;
        flex-basis: 0;
        text-align: center;
    }
    </style>
""", unsafe_allow_html=True)
# --- Layout Tabs ---
st.markdown('<div class="centered-header">EV Network Planning & Simulation Tool</div>', unsafe_allow_html=True)

st.sidebar.title("Save / Load")

USER_ID = st.sidebar.text_input("User ID", value="1")

if st.sidebar.button("💾 Save Session"):
    save_session_to_mongo(USER_ID)

if st.sidebar.button("📥 Load Session"):
    load_session_from_mongo(USER_ID)

if "station_type_choice" not in st.session_state:
            st.session_state.station_type_choice = "Charging Station"


tabs = st.tabs(["Charging Station/Bus Station", "Service", "EV Network"])

# --- Charging Station Screen ---
with tabs[0]:
    st.header("Charging Station/Bus Station")
    search = st.text_input("Search Station by Name")
    cs_df = st.session_state.charging_stations.copy()
    if search:
        cs_df = cs_df[cs_df['Station Name'].str.contains(search, case=False)]
    st.dataframe(cs_df, use_container_width=True)
    
    
    col1,col2= st.columns(2)
    with col1:
        st.subheader("Add  Station")
        if "form_step" not in st.session_state:
             st.session_state.form_step = 0
        
        with st.form("dynamic_form"):
            if st.session_state.form_step == 0:
                # Step 1: Choose station type
                selected_type=st.radio("Choose station type", ["Charging Station", "Bus Station"])
                
                next_step = st.form_submit_button("Next")
                if next_step:
                    st.session_state.station_type_choice = selected_type
                    st.session_state.form_step = 1
                    st.rerun()

            elif st.session_state.form_step == 1:
                # Step 2: Fill station details
                station_type = st.session_state.station_type_choice
                name = st.text_input("Station Name")
                lat = st.number_input("Latitude", format="%.6f")
                lon = st.number_input("Longitude", format="%.6f")

                if station_type == "Charging Station":
                    cap = st.number_input("Charging Capacity (kW)", min_value=0)
                    num = st.number_input("Number of Chargers", min_value=1, step=1)
                st.write(station_type)

                space, column1, column2 = st.columns([16,4,3])
                with column1:
                    submit = st.form_submit_button("Add Station")
                with column2:
                    cancel = st.form_submit_button("Cancel")

                if submit:
                    if station_type == "Charging Station":
                        st.session_state.charging_stations = pd.concat([
                            st.session_state.charging_stations,
                            pd.DataFrame([{
                                'Station Name': name,
                                'Latitude': lat,
                                'Longitude': lon,
                                'Charging Capacity (kW)': cap,
                                'Number of Chargers': num
                            }])
                        ], ignore_index=True)
                        st.write("charging station sfdjjdsfsdkjfhjhskfhdsj")
                    else:
                        st.session_state.bus_stations.append({
                            'Station': name,
                            'Latitude': lat,
                            'Longitude': lon,
                            'ChargeFlag': False,  
                            'BusStation': True
                        })
                    st.success(f"{station_type} '{name}' added!")
                    st.session_state.form_step = 0
                    st.rerun()

                if cancel:
                    st.session_state.form_step = 0
                    st.rerun()

    with col2:
        st.subheader("Edit Station")
        if not cs_df.empty:
            selected = st.selectbox("Select Station to Edit", cs_df['Station Name'].tolist())
            station = st.session_state.charging_stations[
                st.session_state.charging_stations['Station Name'] == selected
            ].iloc[0]
            new_cap = st.number_input("Charging Capacity (kW)", value=station['Charging Capacity (kW)'])
            new_num = st.number_input("Number of Chargers", value=int(station['Number of Chargers']))
            new_lat = st.number_input("Latitude", value=station.get('Latitude', 0.0), format="%.6f")
            new_lon = st.number_input("Longitude", value=station.get('Longitude', 0.0), format="%.6f")
            if st.button("Update Station"):
                idx = st.session_state.charging_stations[
                    st.session_state.charging_stations['Station Name'] == selected
                ].index[0]
                st.session_state.charging_stations.at[idx, 'Charging Capacity (kW)'] = new_cap
                st.session_state.charging_stations.at[idx, 'Number of Chargers'] = new_num
                st.session_state.charging_stations.at[idx, 'Latitude'] = new_lat
                st.session_state.charging_stations.at[idx, 'Longitude'] = new_lon
                st.success(f"Station '{selected}' updated.")
    if st.session_state.charging_stations.empty:
        st.warning("No charging stations available.")
    
        

# --- Service Screen ---
with tabs[1]:
    st.header("Service / Bus")
    search_s = st.text_input("Search Service by Name")
    srv_df = st.session_state.services.copy()
    if search_s:
        srv_df = srv_df[srv_df['Service Name'].str.contains(search_s, case=False)]
    st.dataframe(srv_df[['Service Name', 'Bus Charging Capacity (kW)', 'Mileage (km/kWh)', 'Number of Buses', 'Departure Intervals','Distance (km)', 'Duration (mins)']], use_container_width=True)

    c1,c2=st.columns(2)
    with c1:
        st.subheader("Add Service")
        with st.form("add_service"):
            svc_name = st.text_input("Service Name", key="new_svc_name")
            svc_cap = st.number_input("Bus Charging Capacity (kW)", min_value=1, key="new_svc_cap")
            mileage = st.number_input("Mileage (km/kWh)", min_value=0.1, format="%.2f", key="new_svc_mileage")
            bus_count = st.number_input("Number of Buses", min_value=1, value=1, step=1, key="new_bus_count")
            start_time=st.time_input("Start Time")  

            add_interval_col, add_buffer_col, submit_col = st.columns([4, 4, 2])
            with add_interval_col:
                add_interval = st.form_submit_button("Set Departure Intervals")

            with add_buffer_col:
                add_buffer = st.form_submit_button("Set Buffer Time")
            with submit_col:
                submitted = st.form_submit_button("Add Service")
        if submitted:
            if st.session_state.temp_route:
                distance_time_matrix= [
                    {
                        "distance_m":0,
                        "distance_text":"0 km",
                        "duration_s":0,
                        "duration_text":"0 mins"
                    }
                ]

                for i in range(len(st.session_state.temp_route) - 1):
                    origin = (st.session_state.temp_route[i]['Latitude'], st.session_state.temp_route[i]['Longitude'])
                    destination = (st.session_state.temp_route[i + 1]['Latitude'], st.session_state.temp_route[i + 1]['Longitude'])
                    result = getDistanceAndDurationGmaps(origin, destination)
                    distance_time_matrix.append(result)
                total_distance = sum(d["distance_m"] for d in distance_time_matrix) / 1000
                total_duration = sum(d["duration_s"] for d in distance_time_matrix) / 60

                st.session_state.pending_service.at[0,'Service Name'] = svc_name
                st.session_state.pending_service.at[0,'Bus Charging Capacity (kW)'] = svc_cap
                st.session_state.pending_service.at[0,'Mileage (km/kWh)'] = mileage
                st.session_state.pending_service.at[0,'Number of Buses'] = bus_count
                st.session_state.pending_service.at[0,'Route Data'] = st.session_state.temp_route
                st.session_state.pending_service.at[0,'Start Time'] = start_time
                st.session_state.pending_service.at[0,'Distance (km)'] = total_distance
                st.session_state.pending_service.at[0,'Duration (mins)'] = total_duration
                st.session_state.pending_service.at[0,'Distance Time Matrix'] = distance_time_matrix
                
                st.session_state.temp_route = []
                st.write(st.session_state.pending_service)
                if st.session_state.pending_service['Departure Intervals'] is None:
                    st.session_state.pending_service['Departure Intervals'] = [0] * (bus_count - 1)
                if st.session_state.pending_service['Buffer Times'] is None:
                    st.session_state.pending_service['Buffer Times'] = [0] * bus_count
                st.session_state.services = pd.concat([
                    st.session_state.services,
                    st.session_state.pending_service
                ], ignore_index=True)
                st.success(f"Service '{svc_name}' added with {bus_count} buses.")
                st.session_state.pending_service = pd.DataFrame(columns=[
                    'Service Name', 'Bus Charging Capacity (kW)', 'Mileage (km/kWh)',
                    'Number of Buses', 'Departure Intervals', 'Route Data', 'Start Time',
                    'Buffer Times','Distance (km)', 'Duration (mins)', 'Distance Time Matrix'
                ])
                st.rerun()
                
            else:
                st.error("Please add at least one station.")
                
        if add_interval:
            if bus_count > 1:
                st.session_state.show_interval_modal = True
                st.session_state.show_interval_modal_dismissed = False
                st.session_state.edit_svc = False
            else:
                st.error("At least 2 buses are required to set intervals.")
        if add_buffer:
            if bus_count > 0:
                st.session_state.show_buffer_modal = True
                st.session_state.show_buffer_modal_dismissed = False
                st.session_state.edit_svc = False
            else:
                st.error("At least 1 bus is required to set buffer times.")
        
        col2, col3 = st.columns(2)
        with col2:
            if st.button("➕ Add Bus Station to Route"):
                st.session_state.show_add_ext_busStation_modal = True
                st.session_state.show_add_ext_busStation_modal_dismissed=False
        with col3:
            if st.button("➕ Add Charging Station to Route"):
                st.session_state.show_add_charger_station_modal = True
                st.session_state.show_add_charger_station_modal_dismissed=False
        
        if st.session_state.get("show_add_ext_busStation_modal", False) and not st.session_state.get("show_add_ext_busStation_modal_dismissed", False):
            @st.dialog("Add Existing Bus Station")
            def bus_station_modal():
                stations = st.session_state.bus_stations
                if not stations:
                    st.warning("No saved bus stations found.")
                    if st.button("Close"):
                        st.session_state.show_add_ext_busStation_modal = False
                        st.rerun()
                    return

                search_query = st.text_input("Search Station Name")
                filtered = [s for s in stations if search_query.lower() in s['Station'].lower()]

                if not filtered:
                    st.info("No matching stations found.")
                    if st.button("Close"):
                        st.session_state.show_add_ext_busStation_modal = False
                        st.rerun()
                    return

                station_names = [s['Station'] for s in filtered]
                selected_name = st.selectbox("Select Existing Station", station_names)
                selected = next((s for s in filtered if s['Station'] == selected_name), None)

                if selected:
                    st.write(f"**Latitude:** {selected['Latitude']}")
                    st.write(f"**Longitude:** {selected['Longitude']}")
                    st.write(f"**Charging Allowed:** {'Yes' if selected['ChargeFlag'] else 'No'}")

                    if st.button("Add to Route", key="ext_bus_add"):
                        st.session_state.temp_route.append(selected.copy())
                        st.success(f"Added '{selected_name}' to route.")
                        st.session_state.show_add_ext_busStation_modal = False
                        st.rerun()

                    if st.button("Cancel", key="ext_bus_cancel"):
                        st.session_state.show_add_ext_busStation_modal = False
                        st.rerun()
            st.session_state.show_add_ext_busStation_modal_dismissed = True
            bus_station_modal()
            
        # Modal for adding Charging Station from existing chargers
        if st.session_state.get("show_add_charger_station_modal", False) and not st.session_state.get("show_add_charger_station_modal_dismissed", False):
            @st.dialog("Add Charging Station")
            def charger_station_modal():
                chargers_df = st.session_state.charging_stations
                if chargers_df.empty:
                    st.warning("No charging stations available. Please add in tab 1.")
                    if st.button("Close", key="close_no_chargers"): 
                        st.session_state.show_add_charger_station_modal = False
                        st.rerun()
                    return

                station_selected = st.selectbox("Select Charging Station", chargers_df['Station Name'].tolist())
                # Autofill lat/lon for display (read only)
                lat = float(chargers_df.loc[chargers_df['Station Name'] == station_selected, 'Latitude'])
                lon = float(chargers_df.loc[chargers_df['Station Name'] == station_selected, 'Longitude'])
                st.write(f"Latitude: {lat}, Longitude: {lon}")
                charge = True
                is_bus = False

                if st.button("Add", key="charger_modal_add"):
                    st.session_state.temp_route.append({
                        "Station": station_selected,
                        "Latitude": lat,
                        "Longitude": lon,
                        "ChargeFlag": charge,
                        "BusStation": is_bus
                    })
                    st.warning(f"Charging station '{station_selected}' added to route.")
                    st.session_state.show_add_charger_station_modal = False
                    st.rerun()

                if st.button("Cancel", key="charger_modal_cancel"):
                    st.session_state.show_add_charger_station_modal = False
                    st.rerun()
            st.session_state.show_add_charger_station_modal_dismissed = True
            charger_station_modal()

        if st.session_state.temp_route:
            st.subheader("Current Route")

            if st.button("🔄 Reverse Route"):
                st.session_state.temp_route.reverse()
                st.rerun()

            for i, stop in enumerate(st.session_state.temp_route):
                col1, col2, col3, col4, col5 = st.columns([4, 2, 1, 1, 1])
                with col1:
                    st.markdown(
                        f"**{stop['Station']}**  \n"
                        f"Lat: {stop['Latitude']} | Lon: {stop['Longitude']}  \n"
                        f"Charging: {'✅' if stop['ChargeFlag'] else '❌'} | Type: {'Bus Stand' if stop['BusStation'] else 'Charger'}"
                    )
                with col2:
                    st.write(f"Position: {i + 1}")
                with col3:
                    if i > 0 and st.button("⬆", key=f"up_{i}"):
                        st.session_state.temp_route[i], st.session_state.temp_route[i - 1] = (
                            st.session_state.temp_route[i - 1],
                            st.session_state.temp_route[i],
                        )
                        st.rerun()
                with col4:
                    if i < len(st.session_state.temp_route) - 1 and st.button("⬇", key=f"down_{i}"):
                        st.session_state.temp_route[i], st.session_state.temp_route[i + 1] = (
                            st.session_state.temp_route[i + 1],
                            st.session_state.temp_route[i],
                        )
                        st.rerun()
                with col5:
                    if st.button("🗑️", key=f"delete_{i}"):
                        st.session_state.temp_route.pop(i)
                        st.rerun()
    

    with c2:
    # Buttons to add stations to route (outside form)
        st.subheader("Edit Service")
        if not srv_df.empty:
            with st.form("edit_service"):
                selected_svc = st.selectbox("Select Service to Edit", srv_df['Service Name'].tolist())
                svc= st.session_state.services[
                    st.session_state.services['Service Name'] == selected_svc
                ].iloc[0]
                svc_cap = st.number_input("Bus Charging Capacity (kW)", min_value=1, key="edit_svc_cap", value=svc['Bus Charging Capacity (kW)'])
                mileage = st.number_input("Mileage (km/kWh)", min_value=0.1, format="%.2f", key="edit_svc_mileage", value=svc['Mileage (km/kWh)'])
                bus_count = st.number_input("Number of Buses", min_value=1, step=1, key="edit_bus_count", value=svc['Number of Buses'])
                start_time=st.time_input("Start Time", value=svc['Start Time'])
                                
                st.session_state.temp_edit_route = svc['Route Data']
                edit_interval_col, edit_buffer_col, edit_submit_col = st.columns([4, 4, 2])
                with edit_interval_col:
                    edit_interval = st.form_submit_button("Set Departure Intervals")

                with edit_buffer_col:
                    edit_buffer = st.form_submit_button("Set Buffer Time")
                with edit_submit_col:
                    editService = st.form_submit_button("Edit Service")
                if editService:
                    if st.session_state.temp_edit_route:
                        distance_time_matrix= [
                            {
                                "distance_m":0,
                                "distance_text":"0 km",
                                "duration_s":0,
                                "duration_text":"0 mins"
                            }
                        ]

                        for i in range(len(st.session_state.temp_edit_route) - 1):
                            origin = (st.session_state.temp_edit_route[i]['Latitude'], st.session_state.temp_edit_route[i]['Longitude'])
                            destination = (st.session_state.temp_edit_route[i + 1]['Latitude'], st.session_state.temp_edit_route[i + 1]['Longitude'])
                            result = getDistanceAndDurationGmaps(origin, destination)
                            distance_time_matrix.append(result)
                        total_distance = sum(d["distance_m"] for d in distance_time_matrix) / 1000
                        total_duration = sum(d["duration_s"] for d in distance_time_matrix) / 60

                        idx = st.session_state.services[st.session_state.services['Service Name'] == selected_svc].index[0]
                        st.session_state.services.at[idx, 'Bus Charging Capacity (kW)'] = svc_cap
                        st.session_state.services.at[idx, 'Mileage (km/kWh)'] = mileage
                        st.session_state.services.at[idx, 'Number of Buses'] = bus_count
                        st.session_state.services.at[idx, 'Route Data'] = st.session_state.temp_edit_route
                        st.session_state.services.at[idx, 'Start Time'] = start_time
                        st.session_state.services.at[idx, 'Distance (km)'] = total_distance
                        st.session_state.services.at[idx, 'Duration (mins)'] = total_duration
                        st.session_state.services.at[idx, 'Distance Time Matrix'] = distance_time_matrix

                        if st.session_state.edit_departure_intervals is None:
                            st.session_state.edit_departure_intervals = [0] * (bus_count - 1)
                        if st.session_state.edit_buffer_times is None:
                            st.session_state.edit_buffer_times = [0] * bus_count

                        st.session_state.services.at[idx, 'Departure Intervals'] = st.session_state.edit_departure_intervals
                        st.session_state.services.at[idx, 'Buffer Times'] = st.session_state.edit_buffer_times
                        
                        st.success(f"Service '{selected_svc}' updated with {bus_count} buses.")
                        st.session_state.temp_edit_route = []
                        st.rerun()
                    else:
                        st.error("Please add at least one station.")
                if edit_interval:
                    if len(st.session_state.edit_departure_intervals)==0:
                        st.session_state.edit_departure_intervals = svc['Departure Intervals']
                    if bus_count > 1:
                        st.session_state.show_interval_modal = True
                        st.session_state.show_interval_modal_dismissed = False
                        st.session_state.edit_svc = True
                    else:
                        st.error("At least 2 buses are required to set intervals.")
                if edit_buffer:
                    if len(st.session_state.edit_buffer_times)==0:
                        st.session_state.edit_buffer_times = svc['Buffer Times']
                    if bus_count > 0:
                        st.session_state.show_buffer_modal = True
                        st.session_state.show_buffer_modal_dismissed = False
                        st.session_state.edit_svc = True
                    else:
                        st.error("At least 1 bus is required to set buffer times.")
            if st.session_state.temp_edit_route:
                    
                st.subheader("Edit Route")

                if st.button("🔄 Reverse Route",key="edit_reverse"):
                    st.session_state.temp_edit_route.reverse()
                    st.rerun()

                for i, stop in enumerate(st.session_state.temp_edit_route):
                    col1, col2, col3, col4, col5 = st.columns([4, 2, 1, 1, 1])
                    with col1:
                        st.markdown(
                            f"**{stop['Station']}**  \n"
                            f"Lat: {stop['Latitude']} | Lon: {stop['Longitude']}  \n"
                            f"Charging: {'✅' if stop['ChargeFlag'] else '❌'} | Type: {'Bus Stand' if stop['BusStation'] else 'Charger'}"
                        )
                    with col2:
                        st.write(f"Position: {i + 1}")
                    with col3:
                        if i > 0 and st.button("⬆", key=f"up{i}"):
                            st.session_state.temp_edit_route[i], st.session_state.temp_edit_route[i - 1] = (
                                st.session_state.temp_edit_route[i - 1],
                                st.session_state.temp_edit_route[i],
                            )
                            st.rerun()
                    with col4:
                        if i < len(st.session_state.temp_edit_route) - 1 and st.button("⬇", key=f"down{i}"):
                            st.session_state.temp_edit_route[i], st.session_state.temp_edit_route[i + 1] = (
                                st.session_state.temp_edit_route[i + 1],
                                st.session_state.temp_edit_route[i],
                            )
                            st.rerun()
                    with col5:
                        if st.button("🗑️", key=f"delete{i}"):
                            st.session_state.temp_edit_route.pop(i)
                            st.rerun()
                            
    if st.session_state.get('show_interval_modal', False) and not st.session_state.get('show_interval_modal_dismissed', False):
            @st.dialog("Set Departure Intervals")
            def interval_modal():
                intervals = []
                if not st.session_state.edit_svc:
                    for i in range(1,bus_count ):
                        
                        val = st.number_input(f"Interval between Bus {i} and {i+1} (min)", min_value=0, key=f"modal_interval_{i}",value=st.session_state.pending_service.get('Departure Intervals').iloc[0][i] if not st.session_state.pending_service.empty else 0)
                        intervals.append(val)   
                    if st.button("Confirm & Save"):
                        intervals.insert(0, 0)
                        st.session_state.pending_service.at[0,'Departure Intervals'] = intervals
                        st.session_state.show_interval_modal = False
                        st.rerun()

                    if st.button("Cancel"):
                        st.session_state.show_interval_modal = False
                        st.rerun()
                else:
                    for i in range(1, bus_count):
                        val = st.number_input(f"Interval between Bus {i} and {i+1} (min)", min_value=0, key=f"modal_interval{i}", value=st.session_state.edit_departure_intervals[i] if st.session_state.edit_departure_intervals else 0)
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
        @st.dialog("Set Buffer Tolerance")
        def buffer_modal():
            buffers=[]
            if not st.session_state.edit_svc:
                for i in range(bus_count):
                    buffer = st.number_input(f"Buffer for Bus {i+1} (min)", min_value=0, key=f"modal_buffer_{i}", value=st.session_state.pending_service.get('Buffer Times').iloc[0][i] if not st.session_state.pending_service.empty else 0)
                    buffers.append(buffer)
                if st.button("Confirm & Save"):

                    st.session_state.pending_service.at[0,'Buffer Times'] = buffers
                    st.session_state.show_buffer_modal = False
                    st.session_state.show_buffer_modal_dismissed = True
                    st.rerun()

                if st.button("Cancel"):
                    st.session_state.show_buffer_modal = False
                    st.rerun()
            else:
                for i in range(bus_count):
                    buffer = st.number_input(f"Buffer for Bus {i+1} (min)", min_value=0, key=f"modal_buffer{i}", value=st.session_state.edit_buffer_times[i] if st.session_state.edit_buffer_times else 0)
                    buffers.append(buffer)
                if st.button("Confirm & Save "):
                    st.session_state.edit_buffer_times = buffers
                    st.session_state.show_buffer_modal = False
                    st.rerun()

                if st.button("Cancel "):
                    st.session_state.show_buffer_modal = False
        st.session_state.show_buffer_modal_dismissed = True
        buffer_modal()
    st.subheader("Show Service Route & Distances")
    selected_srv = st.selectbox("Select Service", st.session_state.services['Service Name'].tolist())
    if selected_srv:
        svc = st.session_state.services[
            st.session_state.services['Service Name'] == selected_srv
        ].iloc[0]
        route = pd.DataFrame(svc['Route Data'])

        # Compute distances and times
        coords = list(zip(route['Latitude'], route['Longitude']))
        start_idx = route[route['BusStation']].index.min()
        start_coord = coords[start_idx]

        distances = [i['distance_text'] for i in svc['Distance Time Matrix']]
        est_times = [i['duration_text'] for i in svc['Distance Time Matrix']]

        route['Distance from Prev (km)'] = distances
        route['Est. Time from Prev (min)'] = est_times
        route['Station Type'] = route['BusStation'].apply(lambda x: "Bus Station" if x else "Charger")

        st.dataframe(route[['Station', 'Distance from Prev (km)', 'Est. Time from Prev (min)', 'ChargeFlag', 'Station Type']], use_container_width=True)

        if st.button("✏️ Edit Route"):
            st.session_state.temp_route = svc['Route Data'].copy()
            st.success(f"Loaded route for '{svc['Service Name']}'. Make changes and click Save.")
            st.rerun()

        if st.session_state.temp_route and st.button("💾 Save Edited Route"):
            idx = st.session_state.services[st.session_state.services['Service Name'] == svc["Service Name"]].index[0]
            distance_time_matrix = [{
                    "distance_m":0,
                     "distance_text":"0 km",
                    "duration_s":0,
                    "duration_text":"0 mins"
                }]
            for i in range(len(st.session_state.temp_route) - 1):
                origin = (st.session_state.temp_route[i]['Latitude'], st.session_state.temp_route[i]['Longitude'])
                destination = (st.session_state.temp_route[i + 1]['Latitude'], st.session_state.temp_route[i + 1]['Longitude'])
                result = getDistanceAndDurationGmaps(origin, destination)
                distance_time_matrix.append(result)
            total_distance = sum(d["distance_m"] for d in distance_time_matrix) / 1000
            total_duration = sum(d["duration_s"] for d in distance_time_matrix) / 60
            st.session_state.services.at[idx, 'Route Data'] = st.session_state.temp_route.copy()
            st.session_state.services.at[idx, 'Distance (km)'] = total_distance
            st.session_state.services.at[idx, 'Distance Time Matrix'] = distance_time_matrix
            st.session_state.services.at[idx, 'Duration (mins)'] = total_duration
            st.session_state.temp_route = []
            st.rerun()
            st.success(f"Route for '{svc['Service Name']}' updated.")
        
        route_data = svc['Route Data']
        
        if route_data:
            route_data_hash = get_route_data_hash(route_data)
            if route_data_hash not in st.session_state.route_data_cache:
                st.session_state.route_data_cache[route_data_hash] = route_data

            route_data_cache = st.session_state.route_data_cache

            path_segments = get_directions_path(route_data_hash,st.session_state.route_data_cache)
            m = build_folium_map(route_data, path_segments=path_segments)
            m_data=st_folium(m, width=500, height=500)

                
            

# --- EV Network Screen ---
with tabs[2]:
    st.header("EV Network")
    search_n = st.text_input("Search Network by Name")
    net_df = st.session_state.networks.copy()
    if search_n:
        net_df = net_df[net_df['Network Name'].str.contains(search_n, case=False)]
    st.dataframe(net_df[['Network Name','Status']], use_container_width=True)

    st.subheader("Add & Run Network")
    with st.form("add_network"):
        net_name = st.text_input("Network Name", key="new_net_name")
        tol = st.number_input("Tolerance (%)", min_value=0.0, format="%.2f", key="new_net_tol")
        svcs = st.multiselect("Select Services", st.session_state.services['Service Name'].tolist(), key="new_net_svcs")

            
        if st.form_submit_button("Add & Run"):
            # Filter only selected services
            services_subset = get_services_by_names(svcs)
            
            # Before calling run_network_allocation()


            bus_schedule,charging_events,alloc_df,simulated_events,success = simulate_bus_trips( services_subset, tol,charging_stations_df=st.session_state.charging_stations)
            if not success:
                
                st.error("❌ Allocation failed. Network creation rolled back.")
                
            else:
                # Save results into the network row
                st.session_state.networks = pd.concat([
                    st.session_state.networks,
                    pd.DataFrame([{
                        'Network Name': net_name,
                        'Tolerance (%)': tol,
                        'Services': svcs,
                        'Status': 'SUCCESS',
                        'Allocations': alloc_df,
                        'Bus Schedule': bus_schedule,
                        'Logs': [],
                        'Charging Events': charging_events  
                    }])
                ], ignore_index=True)
                st.rerun()
                st.success(f"Network '{net_name}' created and algorithm run successfully.")
    
    st.subheader("Bus Schedule & Charging Slot Allocation")


    if not net_df.empty:
        selected_net = st.selectbox("Select Network for Allocation View", net_df['Network Name'].tolist(), key="alloc_net_view")
        network = st.session_state.networks[
            st.session_state.networks['Network Name'] == selected_net
        ].iloc[0]
        
        alloc_df = pd.DataFrame(network['Allocations']) if not isinstance(network['Allocations'],pd.DataFrame) else network['Allocations']
        
        charging_events = network.get('Charging Events', [])
        bus_schedule = network.get('Bus Schedule', [])
        bus_df = pd.DataFrame(bus_schedule)
        
        invalid_arrival_df = bus_df[bus_df['arrival'] == "--"].copy()
        valid_arrival_df = bus_df[bus_df['arrival'] != "--"].copy()
        valid_arrival_df['arrival'] = pd.to_datetime(valid_arrival_df['arrival'], format="%H:%M", errors='coerce')
        valid_arrival_df = valid_arrival_df.sort_values(by='arrival')
        valid_arrival_df['arrival'] = valid_arrival_df['arrival'].dt.strftime('%H:%M')
        sorted_bus_df = pd.concat([invalid_arrival_df, valid_arrival_df], ignore_index=True)

        st.subheader(f"Charging Slot Allocation for '{selected_net}'")

        if isinstance(alloc_df, pd.DataFrame) and not alloc_df.empty:
            # Merge charging_events with allocation if needed or show separately
            alloc_df_display = alloc_df.copy()
            enrich_map = {
                (e['station'], e['bus_name']): e for e in charging_events
            }

            # Enrich allocation with battery data
            alloc_df_display['Battery % After Charging'] = alloc_df_display.apply(
                lambda row: enrich_map.get((row['Station Name'], row['Bus Name']), {}).get('battery_after_pct', None),
                axis=1
            )
            alloc_df_display['Battery After Charging (kWh)'] = alloc_df_display.apply(
                lambda row: enrich_map.get((row['Station Name'], row['Bus Name']), {}).get('battery_after_kwh', None),
                axis=1
            )

            st.dataframe(alloc_df_display)
        else:
            st.info("No allocation found for this network.")   
         
         
        st.subheader("🔋 Charging Demand Summary (All Networks)")

        all_events=[]
        all_events = net_df.get('Charging Events', []).iloc[0]
        
        if  all_events:
            df = pd.DataFrame(all_events)
            cs_df = st.session_state.charging_stations.copy()
            df['Duration_Hours'] = df['energy_to_charge'] / df['station'].map({
                row['Station Name']: row['Charging Capacity (kW)']
                for _, row in cs_df.iterrows()
            })

            bus_counts = df.groupby('station')['bus_name'].nunique().rename("Buses Charged")
            total_kwh = df.groupby('station')['energy_to_charge'].sum().rename("Total Charge (kWh)")
            hours_util = df.groupby('station')['Duration_Hours'].sum().rename("Hours Utilized")

            summary_df = pd.concat([bus_counts, total_kwh, hours_util], axis=1).reset_index().rename(columns={'station': 'Station Name'})

            # Join to get number of chargers
            summary_df = summary_df.merge(cs_df[['Station Name', 'Number of Chargers']], on='Station Name', how='left')
            summary_df['Utilization (%)'] = (summary_df['Hours Utilized'] / (16 * summary_df['Number of Chargers'])) * 100
            summary_df['Utilization (%)'] = summary_df['Utilization (%)'].round(2)

            st.dataframe(summary_df[['Station Name', 'Buses Charged', 'Total Charge (kWh)', 'Hours Utilized', 'Utilization (%)']],
                        use_container_width=True)
        else:
            st.info("No charging data available from networks yet.")
        
   
            
        st.subheader("Charger Allocation")
        station_names = sorted({event['station'] for event in charging_events})
        selected = st.selectbox("Select Station for Allocation View", station_names)
        rows = []
        charging_event_per_station = [event for event in charging_events if event['station'] == selected]
        total_chargers = st.session_state.charging_stations[st.session_state.charging_stations['Station Name'] == selected].iloc[0]["Number of Chargers"]


# Prepare rows
        rows = []

        for charger_num in range(1, total_chargers + 1):
            charger_key = str(charger_num)
            events = [e for e in charging_event_per_station if str(e.get('charger_num')) == charger_key]

            if not events:
                rows.append({
                    "Charger": f"Charger {charger_key}",
                    "Start": to_24h_datetime(0),
                    "Finish": to_24h_datetime(1),
                    "Service": "Unused"
                })
            else:
                for event in events:
                    start_min = to_24h_reference(event["start_time"])
                    end_min = to_24h_reference(event["end_time"])

                    # Handle overnight wrap
                    if end_min < start_min:
                        end_min += 1440

                    rows.append({
                        "Charger": f"Charger {charger_key}",
                        "Start": to_24h_datetime(start_min),
                        "Finish": to_24h_datetime(end_min),
                        "Service": event.get("service", "Unknown")
                    })

        df = pd.DataFrame(rows)

        # Plot Gantt chart
        if df.empty:
            st.write("No charging events to display.")
        else:

            fig = px.timeline(
                df,
                x_start="Start",
                x_end="Finish",
                y="Charger",
                color="Service",
                title="Charging Station Gantt Chart (24h View)"
            )

            fig.update_layout(
                xaxis=dict(
                    tickformat="%H:%M",
                    title="Time (24h)"
                )
            )

            fig.update_yaxes(autorange="reversed")
            fig.update_traces(marker_line_color='black', marker_line_width=1)

            st.plotly_chart(fig)


        st.dataframe(sorted_bus_df)


    if not st.session_state.networks.empty:
        st.subheader("✏️ Edit Existing Network")
        net_names = st.session_state.networks['Network Name'].tolist()
        selected_edit_net = st.selectbox("Select Network to Edit", net_names, key="edit_net")

        net_row = st.session_state.networks[
            st.session_state.networks['Network Name'] == selected_edit_net
        ].iloc[0]

        edit_name = st.text_input("Network Name", value=net_row['Network Name'], key="edit_name")
        edit_tol = st.number_input("Tolerance (%)", min_value=0.0, value=float(net_row['Tolerance (%)']), key="edit_tol")

        services_list = []

        if isinstance(net_row['Services'], list):
            # Check if list of dicts:
            if len(net_row['Services']) > 0 and isinstance(net_row['Services'][0], dict):
                for svc in net_row['Services']:
                    services_list.append(svc.get('Service Name', ''))
            else:
                # maybe list of strings already
                services_list = [str(s) for s in net_row['Services']]

        elif isinstance(net_row['Services'], pd.DataFrame):
            services_list = net_row['Services']['Service Name'].tolist()

        else:
            services_list = []

        all_services = st.session_state.services['Service Name'].tolist()
        edit_svcs = st.multiselect("Select Services", all_services, default=services_list, key="edit_svcs")

        if st.button("💾 Save Network Changes"):
            #TODO::fix functionality 
            idx = st.session_state.networks[st.session_state.networks['Network Name'] == selected_edit_net].index[0]
            services_subset = get_services_by_names(edit_svcs)
            success=update_network(idx, edit_name, edit_tol, services_subset)
            msg_box = st.empty()
            if success:
                msg_box.success(f"✅ Network '{edit_name}' updated successfully.")
            else:
                msg_box.warning("⚠️ Allocation failed. No changes were made.")

            msg_box.empty()
    
        

            
        
        
        
        

    
