"""
Generate road network data from OpenStreetMap using OSMnx.
Downloads the road graph for a specified location and exports as GeoJSON.
Caches the raw GraphML to disk to avoid re-downloading.

Usage:
    python generate_road_network.py --place "Paramus, NJ" --output ../data/road_network.geojson
"""
import argparse
import os
import json
import osmnx as ox
import networkx as nx

def main():
    parser = argparse.ArgumentParser(description='Generate road network GeoJSON from OpenStreetMap')
    parser.add_argument('--place', default='Paramus, Bergen County, New Jersey, USA', help='Place name for OSMnx query')
    parser.add_argument('--output', default='../data/road_network.geojson', help='Output GeoJSON file path')
    parser.add_argument('--cache-dir', default='../data/cache', help='Directory to cache raw GraphML')
    parser.add_argument('--network-type', default='drive', help='OSMnx network type (drive, walk, bike, all)')
    args = parser.parse_args()

    os.makedirs(args.cache_dir, exist_ok=True)
    os.makedirs(os.path.dirname(args.output), exist_ok=True)

    cache_file = os.path.join(args.cache_dir, 'road_graph.graphml')

    if os.path.exists(cache_file):
        print(f"Loading cached graph from {cache_file}")
        G = ox.load_graphml(cache_file)
    else:
        print(f"Downloading road network for: {args.place}")
        G = ox.graph_from_place(args.place, network_type=args.network_type)
        ox.save_graphml(G, cache_file)
        print(f"Cached graph to {cache_file}")

    print(f"Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    gdf_edges = ox.graph_to_gdfs(G, nodes=False, edges=True)
    gdf_nodes = ox.graph_to_gdfs(G, nodes=True, edges=False)

    edges_geojson = json.loads(gdf_edges.to_json())
    for feature in edges_geojson['features']:
        props = feature['properties']
        feature['properties'] = {
            'length': props.get('length', 0),
            'speed_kph': props.get('speed_kph', 40),
            'travel_time': props.get('travel_time', 0),
            'oneway': props.get('oneway', False),
            'name': props.get('name', ''),
            'highway': props.get('highway', '')
        }

    with open(args.output, 'w') as f:
        json.dump(edges_geojson, f)
    print(f"Wrote road network to {args.output}")

    nodes_output = args.output.replace('road_network', 'intersections')
    nodes_geojson = json.loads(gdf_nodes[['geometry', 'street_count']].to_json())
    with open(nodes_output, 'w') as f:
        json.dump(nodes_geojson, f)
    print(f"Wrote intersections to {nodes_output}")

if __name__ == '__main__':
    main()
