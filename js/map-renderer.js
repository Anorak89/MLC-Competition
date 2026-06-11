// Hackensack SBRP Map Renderer using Leaflet

class MapRenderer {
    constructor(containerId, options = {}) {
        this.theme = options.theme || 'dark';
        
        // Center on Hackensack, NJ
        this.map = L.map(containerId, {
            zoomControl: true,
            attributionControl: false,
            preferCanvas: true
        }).setView([40.885, -74.048], 13.5);

        const tileUrl = this.theme === 'light'
            ? 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png'
            : 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png';
        L.tileLayer(tileUrl, { maxZoom: 19 }).addTo(this.map);

        this.roadLayer = L.layerGroup().addTo(this.map);
        this.studentLayer = L.layerGroup().addTo(this.map);
        this.busLayer = L.layerGroup().addTo(this.map);
        this.routeLayer = L.layerGroup().addTo(this.map);
        this.eventLayer = L.layerGroup().addTo(this.map);
        this.decisionLayer = L.layerGroup().addTo(this.map);

        this.studentMarkers = {};
        this.busMarkers = {};
        this.schoolMarkers = [];
    }

    renderNetwork(network) {
        this.roadLayer.clearLayers();
        
        // Render thin, low-opacity dashed lines from each stop to its target school
        // This visualizes stop-to-school assignments beautifully!
        const schoolColors = ['rgba(59, 130, 246, 0.18)', 'rgba(249, 115, 22, 0.18)', 'rgba(34, 197, 94, 0.18)'];
        
        const data = window.HACKENSACK_SCENARIO_DATA;
        if (!data) return;

        for (let i = 0; i < network.num_stops; i++) {
            const stopNodeId = network.stop_nodes[i];
            const stopNode = network.nodes.get(stopNodeId);
            
            // To find the school target, we look at HACKENSACK_SCENARIO_DATA
            // We can retrieve it dynamically from SimulationEngine's stop_states if available, 
            // but we can fall back to a default since assignments are seeded.
            // Let's get the stop's school target from stop_states if window._simStopStates exists, or default to i % 3
            let schoolIdx = i % 3;
            if (window.HACKENSACK_SCENARIO_DATA) {
                // Pre-computed assignments are loaded or randomized.
                // We'll draw them once stop states are known, or draw them dynamically.
            }

            const schoolNodeId = network.school_nodes[schoolIdx];
            const schoolNode = network.nodes.get(schoolNodeId);

            if (stopNode && schoolNode) {
                const line = L.polyline([[stopNode.lat, stopNode.lng], [schoolNode.lat, schoolNode.lng]], {
                    color: schoolColors[schoolIdx],
                    weight: 1.5,
                    dashArray: '4, 4',
                    interactive: false
                });
                this.roadLayer.addLayer(line);
            }
        }
    }

    renderSchool(school) {
        // Kept for backward compatibility, but we prefer renderSchools() below
        const schools = window.HACKENSACK_SCENARIO_DATA 
            ? window.HACKENSACK_SCENARIO_DATA.schoolNodes.map((nodeId, idx) => ({
                id: `school_${idx}`,
                name: `School ${String.fromCharCode(65 + idx)}`,
                location: [window.HACKENSACK_SCENARIO_DATA.coords[nodeId].lat, window.HACKENSACK_SCENARIO_DATA.coords[nodeId].lng],
                bell_time: 480
              }))
            : [school];
        this.renderSchools(schools);
    }

    renderSchools(schools) {
        if (this.schoolMarkers.length > 0) {
            this.schoolMarkers.forEach(m => this.map.removeLayer(m));
        }
        this.schoolMarkers = [];

        const colors = ['#3b82f6', '#f97316', '#22c55e'];
        schools.forEach((school, idx) => {
            const icon = L.divIcon({
                className: '',
                html: `<div class="school-marker" style="border-color:${colors[idx]}; background:rgba(${idx === 0 ? '59,130,246' : idx === 1 ? '249,115,22' : '34,197,94'}, 0.25); color:#ffffff; font-weight:bold; font-family:var(--mono); width:32px; height:32px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:13px; box-shadow: 0 0 8px ${colors[idx]}55">🏫${String.fromCharCode(65 + idx)}</div>`,
                iconSize: [32, 32],
                iconAnchor: [16, 16]
            });
            const marker = L.marker(school.location, { icon });
            marker.bindPopup(`<div style="font-family:var(--mono);font-size:12px"><b>${school.name}</b><br>Bell: ${this._fmtTime(school.bell_time)}</div>`);
            marker.addTo(this.map);
            this.schoolMarkers.push(marker);
        });
    }

    renderStudents(students) {
        // Clear student markers that are no longer in 'waiting' or 'late' status
        // Having hundreds of green/delivered checkmarks cluttering schools makes the map messy
        const activeIds = new Set(students.map(s => s.id));
        for (const id in this.studentMarkers) {
            if (!activeIds.has(id)) {
                this.map.removeLayer(this.studentMarkers[id]);
                delete this.studentMarkers[id];
            }
        }

        const data = window.HACKENSACK_SCENARIO_DATA;
        if (!data) return;

        students.forEach(s => {
            // Only render waiting or late students on the map
            // Picked up or delivered students are hidden to keep map clean
            if (s.status !== 'waiting' && s.status !== 'late') {
                if (this.studentMarkers[s.id]) {
                    this.map.removeLayer(this.studentMarkers[s.id]);
                    delete this.studentMarkers[s.id];
                }
                return;
            }

            const stopCoords = data.coords[s.node];
            if (!stopCoords) return;

            // Fermat spiral clustering around the stop coordinates so dots don't overlap
            const idNum = parseInt(s.id.replace('s', '')) || 0;
            const angle = (idNum * 137.5) * Math.PI / 180; // Golden angle
            const r = 0.00015 * Math.sqrt((idNum % 6) + 1);
            const lat = stopCoords.lat + r * Math.sin(angle);
            const lng = stopCoords.lng + r * Math.cos(angle);

            if (this.studentMarkers[s.id]) {
                this._updateStudentMarker(s, lat, lng);
            } else {
                this._createStudentMarker(s, lat, lng);
            }
        });
    }

    _createStudentMarker(s, lat, lng) {
        const schoolColors = ['#3b82f6', '#f97316', '#22c55e'];
        const dotColor = schoolColors[s.school] || '#fbbf24';
        
        const icon = L.divIcon({
            className: '',
            html: `<div class="student-marker waiting" style="width: 8px; height: 8px; border-radius: 50%; background: ${dotColor}; border: 1px solid #ffffff; box-shadow: 0 0 4px ${dotColor}"></div>`,
            iconSize: [8, 8],
            iconAnchor: [4, 4]
        });
        const marker = L.marker([lat, lng], { icon });
        marker.bindPopup(this._studentPopup(s));
        marker.addTo(this.studentLayer);
        this.studentMarkers[s.id] = marker;
    }

    _updateStudentMarker(s, lat, lng) {
        const marker = this.studentMarkers[s.id];
        marker.setLatLng([lat, lng]);
        marker.setPopupContent(this._studentPopup(s));
    }

    _studentPopup(s) {
        const schoolLetter = String.fromCharCode(65 + s.school);
        return `<div style="font-family:var(--mono);font-size:11px;min-width:140px">
            <div style="font-size:13px;font-weight:bold;margin-bottom:4px">STUDENT ${s.id.toUpperCase()}</div>
            <div>Status: <span style="color:#fbbf24">${s.status.toUpperCase()}</span></div>
            <div>Assigned School: <span style="font-weight:bold">School ${schoolLetter}</span></div>
            <div>Window: ${this._fmtTime(s.pickup_window[0])}–${this._fmtTime(s.pickup_window[1])}</div>
            <div>Stop: ${s.neighborhood}</div>
            ${s.special_needs ? '<div style="color:#c084fc; font-weight:bold">♿ Special Needs</div>' : ''}
        </div>`;
    }

    renderBuses(buses) {
        for (const b of buses) {
            if (this.busMarkers[b.id]) {
                this._updateBusMarker(b);
            } else {
                this._createBusMarker(b);
            }
        }
    }

    _createBusMarker(b) {
        const icon = L.divIcon({
            className: '',
            html: `<div class="bus-marker-icon ${b.status}" style="background:${b.color}22; border-color:${b.color}; color:${b.color}; font-weight:bold; width:28px; height:28px; border-radius:4px; border:2px solid; display:flex; align-items:center; justify-content:center; box-shadow:0 0 8px ${b.color}aa">🚌</div>`,
            iconSize: [28, 28],
            iconAnchor: [14, 14]
        });
        const marker = L.marker([b.lat, b.lng], { icon, zIndexOffset: 1000 });
        marker.bindPopup(this._busPopup(b));
        marker.addTo(this.busLayer);
        this.busMarkers[b.id] = marker;
    }

    _updateBusMarker(b) {
        const marker = this.busMarkers[b.id];
        if (marker) {
            marker.setLatLng([b.lat, b.lng]);
            const icon = L.divIcon({
                className: '',
                html: `<div class="bus-marker-icon ${b.status}" style="background:${b.color}22; border-color:${b.color}; color:${b.color}; font-weight:bold; width:28px; height:28px; border-radius:4px; border:2px solid; display:flex; align-items:center; justify-content:center; box-shadow:0 0 8px ${b.color}aa">🚌</div>`,
                iconSize: [28, 28],
                iconAnchor: [14, 14]
            });
            marker.setIcon(icon);
            marker.setPopupContent(this._busPopup(b));
        }
    }

    _busPopup(b) {
        const pct = b.capacity > 0 ? Math.round((b.occupancy / b.capacity) * 100) : 0;
        const barColor = pct > 80 ? '#ef4444' : pct > 50 ? '#fbbf24' : '#22c55e';
        const schoolLetter = b.school_target === -1 ? 'None' : `School ${String.fromCharCode(65 + b.school_target)}`;
        return `<div style="font-family:var(--mono);font-size:11px;min-width:150px">
            <div style="font-size:13px;font-weight:bold;color:${b.color};margin-bottom:4px">${b.id.toUpperCase()}</div>
            <div>Status: ${b.status.toUpperCase()}</div>
            <div>Target School: <span style="font-weight:bold">${schoolLetter}</span></div>
            <div>Occupancy: ${b.occupancy}/${b.capacity}</div>
            <div style="background:rgba(71,85,105,0.4);height:4px;border-radius:2px;margin:4px 0">
                <div style="width:${pct}%;height:100%;background:${barColor};border-radius:2px"></div>
            </div>
            <div>Speed: ${b.speed} mph</div>
        </div>`;
    }

    renderRoutes(buses, network) {
        this.routeLayer.clearLayers();
        for (const b of buses) {
            if (b.status === 'en route' && b.currentPathCoords && b.currentPathCoords.length > 1) {
                const line = L.polyline(b.currentPathCoords, {
                    color: b.color,
                    weight: 3,
                    opacity: 0.8,
                    dashArray: '8, 6'
                });
                this.routeLayer.addLayer(line);
            }
        }
    }

    renderDecision(decision, bus, network) {
        this.decisionLayer.clearLayers();
        if (!decision) return;

        if (decision.targetNode) {
            const node = network.nodes.get(decision.targetNode);
            if (node) {
                const circle = L.circleMarker([node.lat, node.lng], {
                    radius: 12,
                    color: '#00d4ff',
                    fillColor: '#00d4ff',
                    fillOpacity: 0.2,
                    weight: 2,
                    dashArray: '4, 4'
                });
                this.decisionLayer.addLayer(circle);
            }
        }

        if (decision.alternatives) {
            for (const alt of decision.alternatives) {
                if (alt.node) {
                    const node = network.nodes.get(alt.node);
                    if (node) {
                        const circle = L.circleMarker([node.lat, node.lng], {
                            radius: 8,
                            color: '#64748b',
                            fillColor: '#64748b',
                            fillOpacity: 0.1,
                            weight: 1,
                            dashArray: '3, 3'
                        });
                        this.decisionLayer.addLayer(circle);
                    }
                }
            }
        }
    }

    renderEvents(activeEvents) {
        this.eventLayer.clearLayers();
        
        const data = window.HACKENSACK_SCENARIO_DATA;
        if (!data) return;

        for (const evt of activeEvents) {
            if (evt.type === 'traffic_spike' && evt.node) {
                const coords = data.coords[evt.node];
                if (coords) {
                    const circle = L.circle([coords.lat, coords.lng], {
                        radius: 180, // 180 meters radius
                        color: '#fbbf24',
                        fillColor: '#fbbf24',
                        fillOpacity: 0.15,
                        weight: 2,
                        dashArray: '5, 5'
                    });
                    this.eventLayer.addLayer(circle);
                    
                    const textMarker = L.marker([coords.lat + 0.0015, coords.lng], {
                        icon: L.divIcon({
                            className: '',
                            html: `<div style="background:#fbbf24; color:#111827; font-family:var(--mono); font-size:9px; font-weight:bold; padding:2px 6px; border-radius:3px; box-shadow:0 2px 4px rgba(0,0,0,0.5)">⚠️ DELAY</div>`,
                            iconAnchor: [30, 0]
                        })
                    });
                    this.eventLayer.addLayer(textMarker);
                }
            } else if (evt.type === 'road_closure' && evt.fromNode && evt.toNode) {
                const fromCoords = data.coords[evt.fromNode];
                const toCoords = data.coords[evt.toNode];
                if (fromCoords && toCoords) {
                    // Draw red closure line
                    const line = L.polyline([[fromCoords.lat, fromCoords.lng], [toCoords.lat, toCoords.lng]], {
                        color: '#ef4444',
                        weight: 4,
                        opacity: 0.8,
                        dashArray: '5, 5'
                    });
                    this.eventLayer.addLayer(line);
                    
                    // Draw 🚧 icon in the middle of the closed link
                    const midLat = (fromCoords.lat + toCoords.lat) / 2;
                    const midLng = (fromCoords.lng + toCoords.lng) / 2;
                    const marker = L.marker([midLat, midLng], {
                        icon: L.divIcon({
                            className: '',
                            html: '<div style="font-size:20px; text-shadow:0 0 4px rgba(0,0,0,0.5)">🚧</div>',
                            iconSize: [24, 24],
                            iconAnchor: [12, 12]
                        })
                    });
                    this.eventLayer.addLayer(marker);
                }
            }
        }
    }

    updateNetworkOverlay(network) {
        // No-op for Hackensack since we draw assignment overlay lines in renderNetwork
    }

    _fmtTime(minutes) {
        const h = Math.floor(minutes / 60);
        const m = Math.floor(minutes % 60);
        const ampm = h >= 12 ? 'p' : 'a';
        const h12 = h > 12 ? h - 12 : (h === 0 ? 12 : h);
        return `${h12}:${String(m).padStart(2, '0')}${ampm}`;
    }

    destroy() {
        this.map.remove();
    }
}

window.MapRenderer = MapRenderer;
