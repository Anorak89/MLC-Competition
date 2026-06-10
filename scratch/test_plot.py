import matplotlib.pyplot as plt
import json

with open("data/road_network.geojson", "r") as f:
    road_network = json.load(f)

fig, ax_map = plt.subplots(figsize=(10, 10), facecolor='#0f172a')
ax_map.set_facecolor('#0f172a')

for feature in road_network.get("features", []):
    geom = feature.get("geometry", {})
    if geom.get("type") == "LineString":
        coords = geom.get("coordinates", [])
        if len(coords) > 1:
            xs, ys = zip(*coords)
            ax_map.plot(xs, ys, color='#1e293b', linewidth=0.6, alpha=0.6, zorder=0)

plt.savefig("scratch/test_plot.png")
