import json
import random
import os
import networkx as nx
try:
    import osmnx as ox
except ImportError:
    print("Please install osmnx: pip install osmnx")
    exit(1)

def main():
    random.seed(42)
    print("Downloading street network for Hackensack, NJ from OpenStreetMap...")
    # Bounding box roughly covering Hackensack (north, south, east, west)
    north, south, east, west = 40.9100, 40.8700, -74.0300, -74.0600
    
    # Download the drive network
    G = ox.graph_from_bbox((north, south, east, west), network_type='drive')
    
    # Simplify the graph to intersections
    G = ox.simplify_graph(G)
    
    # Keep only the largest strongly connected component
    G = ox.utils_graph.get_largest_component(G, strongly=True)
    
    print(f"Downloaded graph with {len(G.nodes)} nodes and {len(G.edges)} edges.")
    
    # Convert nodes and edges
    nodes_data = {}
    node_list = list(G.nodes)
    
    for idx, n in enumerate(G.nodes(data=True)):
        node_id, data = n
        nodes_data[str(node_id)] = {
            "id": str(node_id),
            "lat": round(data['y'], 6),
            "lng": round(data['x'], 6),
            "name": f"Intersection {node_id}",
            "neighborhood": "Hackensack"
        }
        
    edges_data = []
    for u, v, k, data in G.edges(keys=True, data=True):
        edge_id = f"{u}_{v}"
        
        # Calculate distance (meters to miles)
        dist_miles = data.get('length', 100) * 0.000621371
        
        # Determine speed based on highway type
        hw_type = data.get('highway', 'residential')
        if type(hw_type) == list: hw_type = hw_type[0]
        
        speed = 25.0
        street_type = "local"
        if hw_type in ['primary', 'secondary', 'trunk']:
            speed = 35.0
            street_type = "arterial"
            
        travel_time = (dist_miles / speed) * 60.0
        
        edges_data.append({
            "id": edge_id,
            "from": str(u),
            "to": str(v),
            "distance_miles": round(dist_miles, 4),
            "speed_mph": speed,
            "travel_time_mins": round(travel_time, 3),
            "street_type": street_type
        })
        
        # OSMnx graphs are directional; two-way streets will have a reverse edge automatically.
        
    # Pick random nodes for schools
    school_nodes = random.sample(node_list, 3)
    schools = {
        "school_hhs": {
            "id": "school_hhs",
            "name": "Hackensack High School",
            "node": str(school_nodes[0]),
            "bell_time": 480.0,
            "type": "high"
        },
        "school_hms": {
            "id": "school_hms",
            "name": "Hackensack Middle School",
            "node": str(school_nodes[1]),
            "bell_time": 510.0,
            "type": "middle"
        },
        "school_fes": {
            "id": "school_fes",
            "name": "Fairmount Elementary School",
            "node": str(school_nodes[2]),
            "bell_time": 540.0,
            "type": "elementary"
        }
    }
    
    # Pick depot node
    depot_node = random.choice([n for n in node_list if n not in school_nodes])
    depots = {
        "depot_1": {
            "id": "depot_1",
            "name": "Hackensack Bus Yard",
            "node": str(depot_node)
        }
    }
    
    # Generate 30 Students
    candidate_home_nodes = [n for n in node_list if n not in school_nodes and n != depot_node]
    students = []
    
    for i in range(30):
        student_id = f"s{i+1:02d}"
        home_node = str(random.choice(candidate_home_nodes))
        
        school_choice = i % 3
        if school_choice == 0:
            assigned_school = "school_hhs"
            window_start = float(random.randint(430, 445))
        elif school_choice == 1:
            assigned_school = "school_hms"
            window_start = float(random.randint(460, 475))
        else:
            assigned_school = "school_fes"
            window_start = float(random.randint(490, 505))
            
        students.append({
            "id": student_id,
            "name": f"Student {i+1}",
            "home_node": home_node,
            "school_id": assigned_school,
            "pickup_window": [window_start, window_start + 15.0],
            "attendance_prob": round(random.uniform(0.90, 0.98), 2),
            "neighborhood": "Hackensack",
            "special_needs": random.random() < 0.15
        })
        
    # Generate 3 Buses
    bus_colors = ["#fbbf24", "#3b82f6", "#10b981"]
    buses = []
    for i in range(3):
        buses.append({
            "id": f"bus_{i+1}",
            "name": f"School Bus {i+1}",
            "depot_id": "depot_1",
            "capacity": 12,
            "color": bus_colors[i]
        })
        
    scenario = {
        "meta": {
            "city": "Hackensack, NJ (Real Map)",
            "lat_bounds": [south, north],
            "lng_bounds": [west, east]
        },
        "nodes": nodes_data,
        "edges": edges_data,
        "schools": schools,
        "depots": depots,
        "students": students,
        "buses": buses
    }
    
    out_path = os.path.join(os.path.dirname(__file__), "hackensack_network.json")
    with open(out_path, "w") as f:
        json.dump(scenario, f, indent=2)
        
    print(f"Successfully generated REAL Hackensack road network data!")
    print(f"Total Nodes: {len(nodes_data)}")
    print(f"Total Edges: {len(edges_data)}")
    print(f"Saved to {out_path}")

if __name__ == "__main__":
    main()
