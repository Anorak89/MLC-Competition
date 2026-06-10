import json
import urllib.request
import time
import os

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
net_path = os.path.join(base_dir, 'sbrp_rl', 'hackensack_network.json')

with open(net_path, 'r') as f:
    network = json.load(f)

nodes = network['nodes']
edges = network['edges']

geometries = {}

for edge in edges:
    u = nodes[edge['from']]
    v = nodes[edge['to']]
    
    lon1, lat1 = u['lng'], u['lat']
    lon2, lat2 = v['lng'], v['lat']
    
    url = f"http://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=full&geometries=geojson"
    
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read())
            if data['code'] == 'Ok':
                coords = data['routes'][0]['geometry']['coordinates']
                geometries[edge['id']] = coords
            else:
                print(f"Failed to route {edge['id']}")
    except Exception as e:
        print(f"Error on {edge['id']}: {e}")
    time.sleep(0.1)

out_path = os.path.join(base_dir, 'data', 'edge_geometries.json')
with open(out_path, 'w') as f:
    json.dump(geometries, f)
print(f"Saved geometries for {len(geometries)} edges.")
