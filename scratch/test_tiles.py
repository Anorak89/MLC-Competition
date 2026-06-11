import os
import math
import urllib.request
import numpy as np
import matplotlib.pyplot as plt

def deg2num(lat_deg, lon_deg, zoom):
    lat_rad = math.radians(lat_deg)
    n = 2.0 ** zoom
    xtile = int((lon_deg + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return (xtile, ytile)

def num2deg(xtile, ytile, zoom):
    n = 2.0 ** zoom
    lon_deg = xtile / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * ytile / n)))
    lat_deg = math.degrees(lat_rad)
    return (lat_deg, lon_deg)

def get_basemap(lat_bounds, lng_bounds, zoom=14):
    x_min, y_max = deg2num(lat_bounds[0], lng_bounds[0], zoom)
    x_max, y_min = deg2num(lat_bounds[1], lng_bounds[1], zoom)
    
    # y_max is the tile for lat_min (which is further south, higher Y)
    # y_min is the tile for lat_max (further north, lower Y)
    
    os.makedirs("cache", exist_ok=True)
    
    images = []
    for y in range(y_min, y_max + 1):
        row = []
        for x in range(x_min, x_max + 1):
            url = f"https://a.basemaps.cartocdn.com/dark_all/{zoom}/{x}/{y}.png"
            tile_path = f"cache/tile_{zoom}_{x}_{y}.png"
            if not os.path.exists(tile_path):
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req) as response, open(tile_path, 'wb') as out_file:
                    out_file.write(response.read())
            img = plt.imread(tile_path)
            row.append(img)
        images.append(np.hstack(row))
    
    full_image = np.vstack(images)
    
    # Calculate exact lat/lng bounds of the downloaded tiles
    lat_max_tile, lng_min_tile = num2deg(x_min, y_min, zoom)
    lat_min_tile, lng_max_tile = num2deg(x_max + 1, y_max + 1, zoom)
    
    extent = [lng_min_tile, lng_max_tile, lat_min_tile, lat_max_tile]
    return full_image, extent

img, extent = get_basemap([40.87, 40.91], [-74.06, -74.03], zoom=14)
print(f"Downloaded image shape: {img.shape}, extent: {extent}")
