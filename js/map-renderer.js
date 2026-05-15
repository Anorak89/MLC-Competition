class MapRenderer {
    constructor(containerId) {
        this.map = L.map(containerId, {
            zoomControl: true,
            attributionControl: false,
            preferCanvas: true
        }).setView([40.9448, -74.0718], 14);

        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
            maxZoom: 19
        }).addTo(this.map);

        this.roadLayer = L.layerGroup().addTo(this.map);
        this.studentLayer = L.layerGroup().addTo(this.map);
        this.busLayer = L.layerGroup().addTo(this.map);
        this.routeLayer = L.layerGroup().addTo(this.map);
        this.eventLayer = L.layerGroup().addTo(this.map);
        this.decisionLayer = L.layerGroup().addTo(this.map);

        this.studentMarkers = {};
        this.busMarkers = {};
        this.routeLines = {};
        this.schoolMarker = null;
        this.eventOverlays = {};
    }

    renderNetwork(network) {
        this.roadLayer.clearLayers();
        for (const [eId, edge] of network.edges) {
            const from = network.nodes.get(edge.from);
            const to = network.nodes.get(edge.to);
            const isClosed = network.closedEdges.has(eId);
            const hasTraffic = network.trafficMultipliers.has(eId);
            let color = 'rgba(71, 85, 105, 0.35)';
            let weight = 1.5;
            if (hasTraffic) { color = 'rgba(251, 191, 36, 0.6)'; weight = 2.5; }
            if (isClosed) { color = 'rgba(239, 68, 68, 0.7)'; weight = 3; }

            const line = L.polyline([[from.lat, from.lng], [to.lat, to.lng]], {
                color, weight, opacity: 0.8, className: isClosed ? 'road-closed' : ''
            });
            line._edgeId = eId;
            this.roadLayer.addLayer(line);
        }
    }

    renderSchool(school) {
        if (this.schoolMarker) this.map.removeLayer(this.schoolMarker);
        const icon = L.divIcon({
            className: '',
            html: `<div class="school-marker">🏫</div>`,
            iconSize: [32, 32],
            iconAnchor: [16, 16]
        });
        this.schoolMarker = L.marker(school.location, { icon }).addTo(this.map);
        this.schoolMarker.bindPopup(`<div style="font-family:var(--mono);font-size:12px"><b>${school.name}</b><br>Bell: ${this._fmtTime(school.bell_time)}</div>`);
    }

    renderStudents(students) {
        for (const s of students) {
            if (this.studentMarkers[s.id]) {
                this._updateStudentMarker(s);
            } else {
                this._createStudentMarker(s);
            }
        }
    }

    _createStudentMarker(s) {
        const statusConfig = {
            'waiting': { emoji: '🟡', cls: 'waiting' },
            'picked-up': { emoji: '🟢', cls: 'picked-up' },
            'late': { emoji: '🔴', cls: 'late' },
            'absent': { emoji: '⚫', cls: 'absent' },
            'delivered': { emoji: '✅', cls: 'picked-up' }
        };
        const cfg = statusConfig[s.status] || statusConfig['waiting'];
        const icon = L.divIcon({
            className: '',
            html: `<div class="student-marker ${cfg.cls}" data-sid="${s.id}">${s.special_needs ? '♿' : cfg.emoji}</div>`,
            iconSize: [22, 22],
            iconAnchor: [11, 11]
        });
        const marker = L.marker([s.lat, s.lng], { icon });
        marker.bindPopup(this._studentPopup(s));
        marker.addTo(this.studentLayer);
        this.studentMarkers[s.id] = marker;
    }

    _updateStudentMarker(s) {
        const statusConfig = {
            'waiting': { emoji: '🟡', cls: 'waiting' },
            'picked-up': { emoji: '🟢', cls: 'picked-up' },
            'late': { emoji: '🔴', cls: 'late' },
            'absent': { emoji: '⚫', cls: 'absent' },
            'delivered': { emoji: '✅', cls: 'picked-up' }
        };
        const cfg = statusConfig[s.status] || statusConfig['waiting'];
        const marker = this.studentMarkers[s.id];
        const icon = L.divIcon({
            className: '',
            html: `<div class="student-marker ${cfg.cls}" data-sid="${s.id}">${s.special_needs ? '♿' : cfg.emoji}</div>`,
            iconSize: [22, 22],
            iconAnchor: [11, 11]
        });
        marker.setIcon(icon);
        marker.setPopupContent(this._studentPopup(s));
    }

    _studentPopup(s) {
        return `<div style="font-family:var(--mono);font-size:11px;min-width:140px">
            <div style="font-size:13px;font-weight:bold;margin-bottom:4px">${s.id.toUpperCase()}</div>
            <div>Status: <span style="color:${s.status === 'waiting' ? '#fbbf24' : s.status === 'late' ? '#ef4444' : '#22c55e'}">${s.status}</span></div>
            <div>Window: ${this._fmtTime(s.pickup_window[0])}–${this._fmtTime(s.pickup_window[1])}</div>
            <div>Neighborhood: ${s.neighborhood}</div>
            ${s.special_needs ? '<div style="color:#c084fc">♿ Special Needs</div>' : ''}
            ${s.pickupTime ? `<div>Picked up: ${this._fmtTime(s.pickupTime)}</div>` : ''}
            ${s.rideTime ? `<div>Ride time: ${s.rideTime.toFixed(1)}min</div>` : ''}
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
            html: `<div class="bus-marker-icon ${b.status}" style="background:${b.color}22;border-color:${b.color};color:${b.color}">🚌</div>`,
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
        marker.setLatLng([b.lat, b.lng]);
        const icon = L.divIcon({
            className: '',
            html: `<div class="bus-marker-icon ${b.status}" style="background:${b.color}22;border-color:${b.color};color:${b.color}">🚌</div>`,
            iconSize: [28, 28],
            iconAnchor: [14, 14]
        });
        marker.setIcon(icon);
        marker.setPopupContent(this._busPopup(b));
    }

    _busPopup(b) {
        const pct = b.capacity > 0 ? Math.round((b.occupancy / b.capacity) * 100) : 0;
        const barColor = pct > 80 ? '#ef4444' : pct > 50 ? '#fbbf24' : '#22c55e';
        return `<div style="font-family:var(--mono);font-size:11px;min-width:150px">
            <div style="font-size:13px;font-weight:bold;color:${b.color};margin-bottom:4px">${b.id.toUpperCase()}</div>
            <div>Status: ${b.status}</div>
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
            if (b.currentPathCoords && b.currentPathCoords.length > 1) {
                const line = L.polyline(b.currentPathCoords, {
                    color: b.color, weight: 3, opacity: 0.7, dashArray: '8, 6'
                });
                this.routeLayer.addLayer(line);
            }
        }
    }

    renderDecision(decision, bus, network) {
        this.decisionLayer.clearLayers();
        if (!decision || !decision.alternatives) return;

        if (decision.targetNode) {
            const node = network.nodes.get(decision.targetNode);
            if (node) {
                const circle = L.circleMarker([node.lat, node.lng], {
                    radius: 12, color: '#00d4ff', fillColor: '#00d4ff', fillOpacity: 0.2, weight: 2, dashArray: '4, 4'
                });
                this.decisionLayer.addLayer(circle);
            }
        }

        for (const alt of decision.alternatives) {
            if (alt.node) {
                const node = network.nodes.get(alt.node);
                if (node) {
                    const circle = L.circleMarker([node.lat, node.lng], {
                        radius: 8, color: '#64748b', fillColor: '#64748b', fillOpacity: 0.1, weight: 1, dashArray: '3, 3'
                    });
                    this.decisionLayer.addLayer(circle);
                }
            }
        }
    }

    renderEvents(activeEvents) {
        this.eventLayer.clearLayers();
        for (const evt of activeEvents) {
            switch (evt.type) {
                case 'traffic_spike':
                    const circle = L.circle(evt.location, {
                        radius: evt.radius * 111000,
                        color: '#fbbf24', fillColor: '#fbbf24', fillOpacity: 0.1, weight: 2, dashArray: '5, 5'
                    });
                    this.eventLayer.addLayer(circle);
                    break;
                case 'road_closure':
                    if (evt.edge) {
                        const mid = [(evt.edge[0][0] + evt.edge[1][0]) / 2, (evt.edge[0][1] + evt.edge[1][1]) / 2];
                        const marker = L.marker(mid, {
                            icon: L.divIcon({
                                className: '', html: '<div style="font-size:20px;text-align:center">🚧</div>',
                                iconSize: [24, 24], iconAnchor: [12, 12]
                            })
                        });
                        this.eventLayer.addLayer(marker);
                    }
                    break;
                case 'weather':
                    break;
            }
        }
    }

    updateNetworkOverlay(network) {
        this.roadLayer.eachLayer(layer => {
            if (layer._edgeId) {
                const eId = layer._edgeId;
                const isClosed = network.closedEdges.has(eId);
                const hasTraffic = network.trafficMultipliers.has(eId);
                let color = 'rgba(71, 85, 105, 0.35)';
                let weight = 1.5;
                if (hasTraffic) { color = 'rgba(251, 191, 36, 0.6)'; weight = 2.5; }
                if (isClosed) { color = 'rgba(239, 68, 68, 0.7)'; weight = 3; }
                layer.setStyle({ color, weight });
            }
        });
    }

    _fmtTime(minutes) {
        const h = Math.floor(minutes / 60);
        const m = Math.floor(minutes % 60);
        return `${h > 12 ? h - 12 : h}:${String(m).padStart(2, '0')}${h >= 12 ? 'p' : 'a'}`;
    }

    destroy() {
        this.map.remove();
    }
}

window.MapRenderer = MapRenderer;
