import streamlit as st
from streamlit_folium import st_folium
import folium
import pandas as pd
import googlemaps
import polyline
import plotly.express as px 
from datetime import datetime, timedelta
from pymongo import MongoClient
import json
import hashlib
import copy
import time

st.set_page_config(page_title="EV Network Planning", layout="wide")

gmaps = googlemaps.Client(key="AIzaSyCcdyw_-0olqzOu9vSdDQBgZvaTw8GGLbc")

# --- MongoDB Setup ---
MONGO_URI = "mongodb+srv://sahilrajput:NM09NKfilkALYovi@cluster0.cybby1b.mongodb.net/"
client = MongoClient(MONGO_URI)

db = client["ev_simulator"]
collection = db["sessions"]  


STATE_KEYS = [
    "bus_stations", "charging_stations", "services",
    "networks", "pending_service", "temp_route", "route_data_cache"
]

def clean_session_state():
    cleaned = {}
    for key in STATE_KEYS:
        val = st.session_state.get(key)
        if isinstance(val, pd.DataFrame):
            cleaned[key] = val.to_dict(orient="records")
        else:
            cleaned[key] = val
    return cleaned

def load_session_state(data):
    for key in STATE_KEYS:
        val = data.get(key)

        if key == "charging_stations":
            st.session_state[key] = pd.DataFrame(val, columns=[
                'Station Name', 'City', 'Charging Capacity (kW)', 'Number of Chargers', 'Charging Events','Latitude','Longitude'
            ]) if isinstance(val, list) else pd.DataFrame()
        
        elif key == "services":
            st.session_state[key] = pd.DataFrame(val, columns=[
                'Service Name', 'Bus Charging Capacity (kW)', 'Mileage (km/kWh)',
                'Number of Buses', 'Departure Intervals', 'Route Data',
                'Start Time', 'Distance (km)', 'Duration (mins)', 'Distance Time Matrix'
            ]) if isinstance(val, list) else pd.DataFrame()

        elif key == "networks":
            st.session_state[key] = pd.DataFrame(val, columns=[
                'Network Name', 'Tolerance (%)', 'Services', 'Start Times',
                'Buffer Times', 'Status', 'Allocations', 'Logs'
            ]) if isinstance(val, list) else pd.DataFrame()

        elif key == "pending_service":
            st.session_state[key] = pd.DataFrame(val, columns=[
                'Service Name', 'Bus Charging Capacity (kW)', 'Mileage (km/kWh)',
                'Number of Buses', 'Departure Intervals', 'Route Data',
                'Start Time', 'Distance (km)', 'Duration (mins)', 'Distance Time Matrix'
            ]) if isinstance(val, list) else pd.DataFrame()

        elif key == "networks":
            st.session_state[key] = pd.DataFrame(val, columns=[
                'Network Name', 'Tolerance (%)', 'Services', 'Start Times',
                'Buffer Times', 'Status', 'Allocations', 'Logs'
            ]) if isinstance(val, list) else pd.DataFrame()

        elif key == "pending_service":
            st.session_state[key] = pd.DataFrame(val, columns=[
                'Service Name', 'Bus Charging Capacity (kW)', 'Mileage (km/kWh)',
                'Number of Buses', 'Departure Intervals', 'Route Data', 'Start Time','Distance (km)', 'Duration (mins)', 'Distance Time Matrix'
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
            'Station Name', 'City', 'Charging Capacity (kW)', 'Number of Chargers', 'Charging Events','Latitude','Longitude'
        ])
    if "services" not in st.session_state:
        st.session_state.services = pd.DataFrame(columns=[
            'Service Name', 'Bus Charging Capacity (kW)', 'Mileage (km/kWh)', 'Number of Buses',
            'Departure Intervals', 'Route Data', 'Start Time', 'Distance (km)', 'Duration (mins)','Distance Time Matrix'
        ])
    if "networks" not in st.session_state:
        st.session_state.networks = pd.DataFrame(columns=[
            'Network Name', 'Tolerance (%)', 'Services', 'Start Times', 'Buffer Times',
            'Status', 'Allocations', 'Logs'
        ])
    if "pending_service" not in st.session_state:
        st.session_state.pending_service = pd.DataFrame(columns=[
            'Service Name', 'Bus Charging Capacity (kW)', 'Mileage (km/kWh)',
            'Number of Buses', 'Departure Intervals', 'Route Data', 'Start Time'
        ])
    if "temp_route" not in st.session_state:
        st.session_state.temp_route = []
    if "route_data_cache" not in st.session_state:
        st.session_state.route_data_cache = {}
init_session_state()
    

def simulate_bus_trips(services_df, tolerance=10, charging_stations_df=None):
    charging_events = []
    bus_schedule = []
    allocation_rows = []

    # Charger station info
    charging_info = {
        row['Station Name']: {
            'count': row['Number of Chargers'],
            'capacity': row['Charging Capacity (kW)']
        }
        for _, row in charging_stations_df.iterrows()
    }

    # In-network-only simulated charger state
    simulated_events = {
        station: {str(i + 1): [] for i in range(info['count'])}
        for station, info in charging_info.items()
    }
    
    

    for _, service in services_df.iterrows():
        base_date = service['Start Time']
        route = service['Route Data']
        dtm = service['Distance Time Matrix']
        bus_count = service.get('Number of Buses', 1)
        dep_intervals = service.get('Departure Intervals')
        bus_capacity_kwh = service['Bus Charging Capacity (kW)']
        mileage = service['Mileage (km/kWh)']
        prev_time = base_date
        
        for bus_num in range(1, bus_count + 1):
            
            departure_time = prev_time + timedelta(minutes=dep_intervals[bus_num - 1])
            prev_time = departure_time
            battery_remaining = bus_capacity_kwh
            bus_name = f"{service['Service Name']}-{departure_time.strftime('%H:%M')}"
            
            bus_schedule.append({
                'service': service['Service Name'],
                'bus_name': bus_name,
                'station': route[0]['Station'],
                'arrival': "--",
                'departure': base_date.strftime("%H:%M"),
                'distance_from_prev_km': 0.0,
                'battery_remaining_kwh': round(battery_remaining, 2)
            })
            st.write(bus_schedule)
            for i in range(len(route) - 1):
                curr_station = route[i]
                next_station = route[i + 1]

                dist_km = dtm[i + 1]["distance_m"] / 1000
                travel_time = timedelta(seconds=dtm[i + 1]["duration_s"])
                energy_used = dist_km / mileage
                battery_remaining -= energy_used
                arrival_time = departure_time + travel_time
                departure_time = arrival_time

                bus_schedule.append({
                    'service': service['Service Name'],
                    'bus_name': bus_name,
                    'station': next_station['Station'],
                    'arrival': arrival_time.strftime("%H:%M"),
                    'departure': departure_time.strftime("%H:%M"),
                    'distance_from_prev_km': round(dist_km, 2),
                    'battery_remaining_kwh': round(battery_remaining, 2)
                })
                if next_station==route[-1]:
                    bus_schedule[-1]["departure"] = "--"

                if next_station['ChargeFlag']:
                    remaining = route[i + 1:]
                    rem_dtm = dtm[i + 1:]
                    next_charge_dist = 0
                    for j in range(len(remaining) - 1):
                        next_charge_dist += rem_dtm[j + 1]["distance_m"] / 1000
                        if remaining[j + 1]['ChargeFlag']:
                            break

                    if next_station == route[-1]:
                        required_energy = bus_capacity_kwh
                        buffer = 0
                    else:
                        required_energy = next_charge_dist / mileage
                        buffer = required_energy * (tolerance / 100)

                    target_energy = required_energy + buffer
                    energy_needed = max(target_energy - battery_remaining, 0)
                    battery_before = battery_remaining
                    battery_remaining = min(bus_capacity_kwh, battery_remaining + energy_needed)

                    # Inline charger allocation
                    station_name = next_station['Station']
                    capacity = charging_info[station_name]['capacity']
                    num_chargers = charging_info[station_name]['count']
                    charge_duration_min = 0 if energy_needed == 0 else energy_needed / capacity * 60
                    charge_end = arrival_time + timedelta(minutes=charge_duration_min + 5)

                    allocated = False
                    for charger_num, events in simulated_events[station_name].items():
                        overlap = any(
                            not (charge_end <= e['start_time'] or arrival_time >= e['end_time'])
                            for e in events
                        )
                        if not overlap:
                            events.append({
                                'start_time': arrival_time,
                                'end_time': charge_end,
                                'service': service['Service Name'],
                                'bus_name': bus_name
                            })

                            charging_event = {
                                'start_time': arrival_time,
                                'end_time': charge_end,
                                'service': service['Service Name'],
                                'station': station_name,
                                'bus_name': bus_name,
                                'arrival': arrival_time,
                                'energy_to_charge': energy_needed,
                                'battery_before_pct': battery_before / bus_capacity_kwh * 100,
                                'battery_after_pct': battery_remaining / bus_capacity_kwh * 100,
                                'battery_after_kwh': battery_remaining,
                                'charger_num': charger_num,
                            }

                            allocation_row = {
                                "Station Name": station_name,
                                "Bus Name": bus_name,
                                "Charger #": charger_num,
                                "Charge Start": arrival_time.strftime("%H:%M"),
                                "Charge End": charge_end.strftime("%H:%M"),
                                "Battery % on Arrival": f"{charging_event['battery_before_pct']:.1f}%",
                                "Battery % After Charging": f"{charging_event['battery_after_pct']:.1f}%",
                                "Battery After Charging (kWh)": round(charging_event['battery_after_kwh'], 2)
                            }

                            charging_events.append(charging_event)
                            allocation_rows.append(allocation_row)
                            allocated = True
                            break

                    if not allocated:
                        return None, None, None,None, False
        # with open('logs.txt', 'a') as log_file:
        #     log_file.write(f"Network: {net_name}\n")
        #     log_file.write(f"Services: {', '.join(services_df["Service Name"])}\n")
        #     log_file.write(f"Tolerance: {tolerance}%\n")
        #     log_file.write(f"Bus Schedule:\n{json.dumps(bus_schedule, indent=2)}\n")
        #     log_file.write(f"Allocations:\n{json.dumps(allocation_rows, indent=2)}\n")
        #     log_file.write(f"Success: {True}\n")
        #     log_file.write("\n")
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

user_id = st.sidebar.text_input("User ID", value="1")

if st.sidebar.button("💾 Save Session"):
    save_session_to_mongo(user_id)

if st.sidebar.button("📥 Load Session"):
    load_session_from_mongo(user_id)




tabs = st.tabs(["Charging Station", "Service", "EV Network"])

# --- Charging Station Screen ---
with tabs[0]:
    st.header("Charging Station")
    search = st.text_input("Search Station by Name")
    cs_df = st.session_state.charging_stations.copy()
    cs_df.drop(columns=["Charging Events"], inplace=True)
    if search:
        cs_df = cs_df[cs_df['Station Name'].str.contains(search, case=False)]
    st.dataframe(cs_df, use_container_width=True)
    
    st.subheader("🔋 Charging Demand Summary (All Networks)")

    all_events = []
    for _, net in st.session_state.networks.iterrows():
        events = net.get('Charging Events', [])
        all_events.extend(events)

    if all_events:
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

    col1,col2= st.columns(2)
    with col1:
        st.subheader("Add Charging Station")
        with st.form("add_station"):
            name = st.text_input("Station Name", key="new_cs_name")
            city = st.text_input("City", key="new_cs_city")
            lat = st.number_input("Latitude", format="%.6f", key="new_cs_lat")
            lon = st.number_input("Longitude", format="%.6f", key="new_cs_lon")
            cap = st.number_input("Charging Capacity (kW)", min_value=0, key="new_cs_cap")
            num = st.number_input("Number of Chargers", min_value=1, step=1, key="new_cs_num")
            if st.form_submit_button("Add Station"):
                st.session_state.charging_stations = pd.concat([
                    st.session_state.charging_stations,
                    pd.DataFrame([{
                        'Station Name': name,
                        'City': city,
                        'Latitude': lat,
                        'Longitude': lon,
                        'Charging Capacity (kW)': cap,
                        'Number of Chargers': num,
                        'Charging Events': {}
                    }])
                ], ignore_index=True)
                st.success(f"Station '{name}' added.")
    with col2:
        if not cs_df.empty:
            st.subheader("Edit Charging Station")
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
            svc_cap = st.number_input("Bus Charging Capacity (kW)", min_value=0, key="new_svc_cap")
            mileage = st.number_input("Mileage (km/kWh)", min_value=0.0, format="%.2f", key="new_svc_mileage")
            bus_count = st.number_input("Number of Buses", min_value=1, value=1, step=1, key="new_bus_count")
            

            #interval = st.selectbox("Departure Interval (minutes)", [15, 30, 45, 60], key="new_dep_interval")
            start_date=st.date_input("Start Date")
            start_time=st.time_input("Start Time")
            start_time = datetime.combine(start_date,start_time)


            submitted = st.form_submit_button("Add Service")

    with c2:
    # Buttons to add stations to route (outside form)
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("➕ Add New Bus Station to Route"):
                st.session_state.show_add_bus_station_modal = True
                st.session_state.show_add_bus_station_modal_dismissed=False
        with col2:
            if st.button("➕ Add Existing Bus Station to Route"):
                st.session_state.show_add_ext_busStation_modal = True
                st.session_state.show_add_ext_busStation_modal_dismissed=False
        with col3:
            if st.button("➕ Add Charging Station to Route"):
                st.session_state.show_add_charger_station_modal = True
                st.session_state.show_add_charger_station_modal_dismissed=False
        

    # Modal for adding Bus Station (manual input)
        if st.session_state.get("show_add_bus_station_modal", False) and not st.session_state.get("show_add_bus_station_modal_dismissed", False):
            @st.dialog("Add Bus Station")
            def bus_station_modal():
                st_name = st.text_input("Station Name", key="bus_modal_name")
                lat = st.number_input("Latitude", format="%.6f", key="bus_modal_lat")
                lon = st.number_input("Longitude", format="%.6f", key="bus_modal_lon")
                charge = st.checkbox("Charging Allowed", key="bus_modal_charge")
                is_bus = True  # since this is bus station modal, always True

                if st.button("Add", key="bus_modal_add"):
                    existing_names = [s['Station'] for s in st.session_state.bus_stations]
                    if st_name in existing_names:
                        st.error(f"A bus station named '{st_name}' already exists. Please use a different name.")
                    else:
                        st.session_state.temp_route.append({
                            "Station": st_name,
                            "Latitude": lat,
                            "Longitude": lon,
                            "ChargeFlag": charge,
                            "BusStation": is_bus
                        })
                        
                        st.session_state.bus_stations.append({
                            "Station": st_name,
                            "Latitude": lat,
                            "Longitude": lon,
                            "ChargeFlag": charge,
                            "BusStation": is_bus
                        })
                        if(charge):
                            st.session_state.charging_stations = pd.concat([
                                st.session_state.charging_stations,
                                pd.DataFrame([{
                                    'Station Name': st_name,
                                    'City': st_name,
                                    'Latitude': lat,
                                    'Longitude': lon,
                                    'Charging Capacity (kW)': 0,
                                    'Number of Chargers': 0
                                }])
                            ], ignore_index=True)
                        st.success(f"Station '{st_name}' added.")

                        st.session_state.show_add_bus_station_modal = False
                        st.rerun() 

                if st.button("Cancel", key="bus_modal_cancel"):
                    st.session_state.show_add_bus_station_modal = False
                    st.rerun()
            st.session_state.show_add_bus_station_modal_dismissed = True
            bus_station_modal()
            
        #Modal for adding Bus Station from existing stations
        # Modal for adding Bus Station from existing stations
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
            st.write(distance_time_matrix)
            total_distance = sum([d["distance_m"] for d in distance_time_matrix]) / 1000
            total_duration = sum([d["duration_s"] for d in distance_time_matrix]) / 60

            st.session_state.pending_service={
                'Service Name': svc_name,
                'Bus Charging Capacity (kW)': svc_cap,
                'Mileage (km/kWh)': mileage,
                'Route Data': st.session_state.temp_route.copy(),
                'Number of Buses': bus_count,
                'Distance (km)': total_distance,
                'Duration (mins)': total_duration,
                'Distance Time Matrix': distance_time_matrix,
                'Start Time': start_time
            }
            st.session_state.temp_route = []  
            st.session_state.show_interval_modal= True
            st.session_state.show_interval_modal_dismissed=False
        else:
            st.error("Please add at least one station.")
    
    if st.session_state.get('show_interval_modal', False) and not st.session_state.get('show_interval_modal_dismissed', False):
        @st.dialog("Set Departure Intervals")
        def interval_modal():
            bus_count = st.session_state.pending_service.get("Number of Buses", 1)
            intervals = []
            for i in range(bus_count - 1):
                val = st.number_input(f"Interval between Bus {i+1} and {i+2} (min)", min_value=0, key=f"modal_interval_{i}")
                intervals.append(val)

            if st.button("Confirm & Save"):
                data = st.session_state.pending_service.copy()
                intervals.insert(0, 0) 
                data['Departure Intervals'] = intervals
                st.session_state.services = pd.concat([
                    st.session_state.services,
                    pd.DataFrame([data])
                ], ignore_index=True)
                st.success(f"Service '{data['Service Name']}' added.")
                st.session_state.pending_service = {}
                st.session_state.show_interval_modal = False
                st.rerun()

            if st.button("Cancel"):
                st.session_state.temp_route = st.session_state.pending_service.get("Route Data", [])
                st.session_state.pending_service = {}
                st.session_state.show_interval_modal = False
                st.rerun()
            st.session_state.show_interval_modal_dismissed = True
        interval_modal()

    
            
        

    st.subheader("Show Service Route & Distances")
    selected_srv = st.selectbox("Select Service", st.session_state.services['Service Name'].tolist())
    if selected_srv:
        svc = st.session_state.services[
            st.session_state.services['Service Name'] == selected_srv
        ].iloc[0]
        route = pd.DataFrame(svc['Route Data'])

        # Compute distances and times
        coords = list(zip(route['Latitude'], route['Longitude']))
        start_idx = route[route['BusStation'] == True].index.min()
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
            total_distance = sum([d["distance_m"] for d in distance_time_matrix]) / 1000
            total_duration = sum([d["duration_s"] for d in distance_time_matrix]) / 60
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
            st.write(f"hashData: {route_data_hash}")
            if route_data_hash not in st.session_state.route_data_cache:
                st.session_state.route_data_cache[route_data_hash] = route_data

            route_data_cache = st.session_state.route_data_cache

            path_segments = get_directions_path(route_data_hash,st.session_state.route_data_cache)
            m = build_folium_map(route_data, path_segments=path_segments)
            data=st_folium(m, width=700, height=500)

                
            

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
            #TODO::fix the run_network_allocation function to accept services_subset and tol the code was changed so do a runthrough of working 
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
                        'Charging Events': charging_events  # NEW: store for display
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

        alloc_df = network['Allocations']
        charging_events = network.get('Charging Events', [])
        bus_schedule = network.get('Bus Schedule', [])
        bus_df = pd.DataFrame(bus_schedule)
        invalid_arrival_df = bus_df[bus_df['arrival'] == "--"].copy()
        valid_arrival_df = bus_df[bus_df['arrival'] != "--"].copy()
        valid_arrival_df['arrival'] = pd.to_datetime(valid_arrival_df['arrival'], format="%H:%M", errors='coerce')
        valid_arrival_df = valid_arrival_df.sort_values(by='arrival')
        valid_arrival_df['arrival'] = valid_arrival_df['arrival'].dt.strftime('%H:%M')
        sorted_bus_df = pd.concat([invalid_arrival_df, valid_arrival_df], ignore_index=True)
        st.dataframe(sorted_bus_df)
        # st.subheader(f"Bus Schedule for '{selected_net}'")

        # st.write(bus_schedule)

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
            
            st.subheader("Charger Allocation")
            station_names = sorted(set(event['station'] for event in charging_events))
            selected = st.selectbox("Select Station for Allocation View", station_names)
            rows = []
            charging_event_per_station = [event for event in charging_events if event['station'] == selected]
            total_chargers = st.session_state.charging_stations[st.session_state.charging_stations['Station Name'] == selected].iloc[0]["Number of Chargers"]
            for charger_num in range(1, total_chargers + 1):
                charger_key = str(charger_num)
                events = [e for e in charging_event_per_station if str(e.get('charger_num')) == charger_key]

                if not events:
                    # Add a dummy row with minimal span for display
                    rows.append({
                        "Charger": f"Charger {charger_key}",
                        "Start": datetime.now(),
                        "Finish": datetime.now(),
                        "Service": "Unused"
                    })
                else:
                    for event in events:
                            rows.append({
                            "Charger": f"Charger {charger_key}",
                            "Start": event["start_time"],
                            "Finish": event["end_time"],
                            "Service": event.get("service", "Unknown")
                        })
                df = pd.DataFrame(rows)

                    # Create Gantt chart
                if df.empty:
                    st.write("No charging events to display.")
                else:
                    fig = px.timeline(
                        df,
                        x_start="Start",
                        x_end="Finish",
                        y="Charger",
                        color="Service",
                        title="Charging Station Gantt Chart",
                    )

        # Reverse Y-axis so Charger 1 is at the top
            fig.update_yaxes(autorange="reversed")

            st.plotly_chart(fig)

        
        else:
            st.info("No allocation found for this network.")

    if not st.session_state.networks.empty:
        st.subheader("✏️ Edit Existing Network")
        net_names = st.session_state.networks['Network Name'].tolist()
        selected_edit_net = st.selectbox("Select Network to Edit", net_names, key="edit_net")

        net_row = st.session_state.networks[
            st.session_state.networks['Network Name'] == selected_edit_net
        ].iloc[0]

        edit_name = st.text_input("Network Name", value=net_row['Network Name'], key="edit_name")
        edit_tol = st.number_input("Tolerance (%)", min_value=0.0, value=float(net_row['Tolerance (%)']), key="edit_tol")

        all_services = st.session_state.services['Service Name'].tolist()
        edit_svcs = st.multiselect("Select Services", all_services, default=net_row['Services'], key="edit_svcs") 

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

            time.sleep(2)
            msg_box.empty()
            st.rerun()
            
        
        
        
        

    
