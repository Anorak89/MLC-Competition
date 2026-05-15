"""
Generate scenario data (students, buses, events) for the bus routing simulator.
Places students along the road network and creates dynamic event timelines.

Usage:
    python generate_scenario.py --road-network ../data/road_network.geojson --output ../data/scenario_default.json
"""
import argparse
import json
import random
import os

def main():
    parser = argparse.ArgumentParser(description='Generate scenario data for bus routing simulator')
    parser.add_argument('--output', default='../data/scenario_default.json', help='Output JSON file path')
    parser.add_argument('--num-students', type=int, default=40, help='Number of students')
    parser.add_argument('--num-buses', type=int, default=5, help='Number of buses')
    parser.add_argument('--center-lat', type=float, default=40.9448, help='Center latitude')
    parser.add_argument('--center-lng', type=float, default=-74.0718, help='Center longitude')
    parser.add_argument('--radius', type=float, default=0.015, help='Spread radius in degrees')
    parser.add_argument('--seed', type=int, default=42, help='Random seed')
    args = parser.parse_args()

    random.seed(args.seed)
    os.makedirs(os.path.dirname(args.output), exist_ok=True)

    neighborhoods = ['north', 'south', 'east', 'west', 'central', 'northwest']
    neighborhood_centers = {
        'north': (args.center_lat + 0.008, args.center_lng - 0.005),
        'south': (args.center_lat - 0.008, args.center_lng + 0.003),
        'east': (args.center_lat - 0.003, args.center_lng + 0.012),
        'west': (args.center_lat + 0.002, args.center_lng - 0.015),
        'central': (args.center_lat, args.center_lng),
        'northwest': (args.center_lat + 0.006, args.center_lng - 0.010)
    }

    students = []
    for i in range(args.num_students):
        hood = neighborhoods[i % len(neighborhoods)]
        center = neighborhood_centers[hood]
        lat = center[0] + random.gauss(0, 0.003)
        lng = center[1] + random.gauss(0, 0.004)
        window_start = random.randint(425, 445)
        students.append({
            'id': f's{i+1:02d}',
            'home': [round(lat, 4), round(lng, 4)],
            'pickup_window': [window_start, window_start + 20],
            'attendance_prob': round(random.uniform(0.85, 0.99), 2),
            'special_needs': random.random() < 0.15,
            'neighborhood': hood
        })

    bus_colors = ['#00d4ff', '#ff6b35', '#7ddf64', '#c084fc', '#fbbf24']
    buses = []
    for i in range(args.num_buses):
        buses.append({
            'id': f'bus_{i+1}',
            'capacity': random.choice([8, 10, 12]),
            'speed': random.randint(25, 30),
            'depot': [args.center_lat - 0.003, args.center_lng + 0.001],
            'color': bus_colors[i % len(bus_colors)]
        })

    events = [
        {'type': 'traffic_spike', 'time': random.randint(440, 455), 'duration': 15,
         'location': [args.center_lat + 0.002, args.center_lng - 0.003], 'radius': 0.005, 'multiplier': 2.5,
         'desc': 'Heavy traffic on main road'},
        {'type': 'road_closure', 'time': random.randint(445, 460), 'duration': 20,
         'edge': [[args.center_lat, args.center_lng - 0.008], [args.center_lat + 0.002, args.center_lng - 0.006]],
         'desc': 'Accident blocking road'},
        {'type': 'weather', 'time': random.randint(435, 450), 'duration': 30,
         'multiplier': 1.4, 'desc': 'Light rain'},
        {'type': 'bus_breakdown', 'time': random.randint(450, 465), 'bus_id': f'bus_{random.randint(1, args.num_buses)}',
         'desc': f'Bus mechanical failure'},
    ]
    absent_students = random.sample([s['id'] for s in students], k=min(3, args.num_students))
    for sid in absent_students:
        events.append({'type': 'student_absence', 'time': 0, 'student_id': sid, 'desc': f'{sid} absent'})

    scenario = {
        'meta': {
            'district': 'Paramus, NJ',
            'center': [args.center_lat, args.center_lng],
            'bounds': [[args.center_lat - args.radius, args.center_lng - args.radius * 1.3],
                        [args.center_lat + args.radius, args.center_lng + args.radius * 1.3]]
        },
        'school': {
            'id': 'school_1',
            'name': 'Bergen County Academies',
            'location': [args.center_lat - 0.003, args.center_lng + 0.001],
            'bell_time': 480
        },
        'students': students,
        'buses': buses,
        'neighborhoods': {n: {'name': n.replace('_', ' ').title(), 'color': bus_colors[i % len(bus_colors)]}
                          for i, n in enumerate(neighborhoods)},
        'events': events
    }

    with open(args.output, 'w') as f:
        json.dump(scenario, f, indent=2)
    print(f"Generated scenario: {args.num_students} students, {args.num_buses} buses, {len(events)} events")
    print(f"Saved to {args.output}")

if __name__ == '__main__':
    main()
