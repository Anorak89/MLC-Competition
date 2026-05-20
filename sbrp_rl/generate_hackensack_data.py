import json
import random
import math

def haversine(lat1, lng1, lat2, lng2):
    # Radius of the Earth in miles
    R = 3958.8
    dLat = math.radians(lat2 - lat1)
    dLng = math.radians(lng2 - lng1)
    a = math.sin(dLat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dLng / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def main():
    random.seed(42)

    # 1. Define Hackensack, NJ geography
    # Latitudes from 40.8700 to 40.9100, Longitudes from -74.0600 to -74.0300
    lat_min, lat_max = 40.8700, 40.9100
    lng_min, lng_max = -74.0600, -74.0300
    
    rows, cols = 6, 6
    lat_step = (lat_max - lat_min) / (rows - 1)
    lng_step = (lng_max - lng_min) / (cols - 1)

    nodes = {}
    node_id_grid = []

    # Node names for realistic Hackensack intersections
    street_names_ns = ["Summit Ave", "State St", "Main St", "River Rd", "Polifly Rd", "Hackensack Ave"]
    street_names_ew = ["Passaic St", "Essex St", "Central Ave", "Beech St", "Temple Ave", "Route 4"]

    node_count = 0
    for r in range(rows):
        row_ids = []
        for c in range(cols):
            node_id = f"node_{node_count}"
            row_ids.append(node_id)
            node_count += 1
            
            # Geographic coordinate plus a tiny bit of jitter for realism
            jitter_lat = random.uniform(-0.0005, 0.0005)
            jitter_lng = random.uniform(-0.0005, 0.0005)
            lat = lat_min + r * lat_step + jitter_lat
            lng = lng_min + c * lng_step + jitter_lng

            # Neighborhood assignment based on location
            if r >= 4 and c <= 2:
                hood = "Fairmount"  # North-West
            elif r <= 1 and c <= 2:
                hood = "Hillers"  # South-West
            elif r >= 4 and c >= 3:
                hood = "Hackensack Commons"  # North-East
            elif r <= 1 and c >= 3:
                hood = "Maple Hill"  # South-East
            else:
                hood = "Central Hackensack"  # Central

            # Generate realistic street intersection name
            ns_street = street_names_ns[c % len(street_names_ns)]
            ew_street = street_names_ew[r % len(street_names_ew)]
            name = f"{ns_street} & {ew_street}"

            nodes[node_id] = {
                "id": node_id,
                "lat": round(lat, 6),
                "lng": round(lng, 6),
                "name": name,
                "neighborhood": hood
            }
        node_id_grid.append(row_ids)

    # Generate edges (roads)
    edges = []
    
    def add_edge(from_id, to_id, street_type="local"):
        # Calculate distance
        n1 = nodes[from_id]
        n2 = nodes[to_id]
        dist = haversine(n1["lat"], n1["lng"], n2["lat"], n2["lng"])
        
        # Speed limit: arterial = 35 mph, local = 25 mph
        speed = 35.0 if street_type == "arterial" else 25.0
        # Travel time in minutes
        travel_time = (dist / speed) * 60.0
        
        edge_id = f"{from_id}_{to_id}"
        edges.append({
            "id": edge_id,
            "from": from_id,
            "to": to_id,
            "distance_miles": round(dist, 4),
            "speed_mph": speed,
            "travel_time_mins": round(travel_time, 3),
            "street_type": street_type
        })
        
        # Add reverse direction (two-way street)
        rev_id = f"{to_id}_{from_id}"
        edges.append({
            "id": rev_id,
            "from": to_id,
            "to": from_id,
            "distance_miles": round(dist, 4),
            "speed_mph": speed,
            "travel_time_mins": round(travel_time, 3),
            "street_type": street_type
        })

    # Build connectivity grid
    for r in range(rows):
        for c in range(cols):
            curr_id = node_id_grid[r][c]
            
            # Determine street type: column 2 (Main St) and column 5 (Hackensack Ave) are arterials. 
            # Row 5 (Route 4) and row 1 (Essex St) are arterials.
            is_arterial_ew = (r == 1 or r == 5)
            is_arterial_ns = (c == 2 or c == 5)

            # Connect East
            if c < cols - 1:
                next_id = node_id_grid[r][c + 1]
                st_type = "arterial" if is_arterial_ew else "local"
                add_edge(curr_id, next_id, st_type)
            
            # Connect North
            if r < rows - 1:
                next_id = node_id_grid[r + 1][c]
                st_type = "arterial" if is_arterial_ns else "local"
                add_edge(curr_id, next_id, st_type)

    # 2. Design Schools
    # HHS (High School) - Central/North: Row 4, Col 2 (node_26)
    # HMS (Middle School) - Central/East: Row 3, Col 4 (node_22)
    # FES (Fairmount Elementary School) - North/West: Row 5, Col 1 (node_31)
    schools = {
        "school_hhs": {
            "id": "school_hhs",
            "name": "Hackensack High School",
            "node": "node_26",
            "bell_time": 480.0, # 8:00 AM
            "type": "high"
        },
        "school_hms": {
            "id": "school_hms",
            "name": "Hackensack Middle School",
            "node": "node_22",
            "bell_time": 510.0, # 8:30 AM
            "type": "middle"
        },
        "school_fes": {
            "id": "school_fes",
            "name": "Fairmount Elementary School",
            "node": "node_31",
            "bell_time": 540.0, # 9:00 AM
            "type": "elementary"
        }
    }

    # 3. Design Depot
    # Depot is in the industrial south area: Row 0, Col 1 (node_1)
    depots = {
        "depot_1": {
            "id": "depot_1",
            "name": "Hackensack Bus Yard",
            "node": "node_1"
        }
    }

    # 4. Generate Students (stochastically placed and assigned to schools)
    # Total of 30 students to make it computationally manageable but complex
    num_students = 30
    students = []
    
    # Pre-determined home nodes (avoiding school nodes directly)
    candidate_home_nodes = [nid for nid in nodes.keys() if nid not in ["node_26", "node_22", "node_31", "node_1"]]
    
    for i in range(num_students):
        student_id = f"s{i+1:02d}"
        home_node = random.choice(candidate_home_nodes)
        
        # Divide students equally across schools
        school_choice = i % 3
        if school_choice == 0:
            assigned_school = "school_hhs"
            # Pickup window in minutes since 7:00 AM (420 mins)
            # High School bell is at 8:00 AM (480 mins). Window: 7:15 AM - 7:35 AM (435 - 455 mins)
            window_start = float(random.randint(430, 445))
            window_end = window_start + 15.0
        elif school_choice == 1:
            assigned_school = "school_hms"
            # Middle School bell is at 8:30 AM (510 mins). Window: 7:45 AM - 8:05 AM (465 - 485 mins)
            window_start = float(random.randint(460, 475))
            window_end = window_start + 15.0
        else:
            assigned_school = "school_fes"
            # Elementary School bell is at 9:00 AM (540 mins). Window: 8:15 AM - 8:35 AM (495 - 515 mins)
            window_start = float(random.randint(490, 505))
            window_end = window_start + 15.0
            
        students.append({
            "id": student_id,
            "name": f"Student {i+1}",
            "home_node": home_node,
            "school_id": assigned_school,
            "pickup_window": [window_start, window_end],
            "attendance_prob": round(random.uniform(0.90, 0.98), 2),
            "neighborhood": nodes[home_node]["neighborhood"],
            "special_needs": random.random() < 0.15 # 15% special needs (could add extra wait time or priority)
        })

    # 5. Generate Buses
    # 3 buses are available, starting at depot_1
    bus_colors = ["#fbbf24", "#3b82f6", "#10b981"] # Gold, Blue, Green
    buses = []
    for i in range(3):
        buses.append({
            "id": f"bus_{i+1}",
            "name": f"School Bus {i+1}",
            "depot_id": "depot_1",
            "capacity": 12, # Bus capacity limit
            "color": bus_colors[i]
        })

    # 6. Assemble complete scenario JSON
    scenario = {
        "meta": {
            "city": "Hackensack, NJ",
            "lat_bounds": [lat_min, lat_max],
            "lng_bounds": [lng_min, lng_max]
        },
        "nodes": nodes,
        "edges": edges,
        "schools": schools,
        "depots": depots,
        "students": students,
        "buses": buses
    }

    # Write to file
    with open("sbrp_rl/hackensack_network.json", "w") as f:
        json.dump(scenario, f, indent=2)
        
    print(f"Successfully generated realistic Hackensack road network data!")
    print(f"Total Nodes: {len(nodes)}")
    print(f"Total Edges: {len(edges)}")
    print(f"Total Students: {len(students)}")
    print(f"Total Buses: {len(buses)}")

if __name__ == "__main__":
    main()
