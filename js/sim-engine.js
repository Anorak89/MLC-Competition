class RoadNetwork {
    constructor() {
        this.nodes = new Map();
        this.edges = new Map();
        this.adjacency = new Map();
        this.trafficMultipliers = new Map();
        this.closedEdges = new Set();
        this.globalSpeedMultiplier = 1.0;
    }

    generateForBounds(bounds, density) {
        const [[latMin, lngMin], [latMax, lngMax]] = bounds;
        const rows = density || 12;
        const cols = Math.round(rows * 1.3);
        const latStep = (latMax - latMin) / (rows - 1);
        const lngStep = (lngMax - lngMin) / (cols - 1);
        let nodeId = 0;
        const grid = [];

        for (let r = 0; r < rows; r++) {
            grid[r] = [];
            for (let c = 0; c < cols; c++) {
                const jitter = 0.0008;
                const lat = latMin + r * latStep + (Math.random() - 0.5) * jitter;
                const lng = lngMin + c * lngStep + (Math.random() - 0.5) * jitter;
                const id = `n${nodeId++}`;
                this.nodes.set(id, { id, lat, lng, row: r, col: c });
                this.adjacency.set(id, []);
                grid[r][c] = id;
            }
        }

        for (let r = 0; r < rows; r++) {
            for (let c = 0; c < cols; c++) {
                const from = grid[r][c];
                if (c < cols - 1) this._addRoadEdge(from, grid[r][c + 1]);
                if (r < rows - 1) this._addRoadEdge(from, grid[r + 1][c]);
                if (r < rows - 1 && c < cols - 1 && Math.random() < 0.25) {
                    this._addRoadEdge(from, grid[r + 1][c + 1]);
                }
                if (r < rows - 1 && c > 0 && Math.random() < 0.15) {
                    this._addRoadEdge(from, grid[r + 1][c - 1]);
                }
            }
        }
    }

    _addRoadEdge(fromId, toId) {
        const from = this.nodes.get(fromId);
        const to = this.nodes.get(toId);
        const dist = this._haversine(from.lat, from.lng, to.lat, to.lng);
        const speed = 25 + Math.random() * 15;
        const travelTime = (dist / speed) * 60;
        const isOneWay = Math.random() < 0.1;
        const edgeId = `${fromId}-${toId}`;
        const edgeData = { id: edgeId, from: fromId, to: toId, distance: dist, speed, travelTime, isOneWay };
        this.edges.set(edgeId, edgeData);
        this.adjacency.get(fromId).push({ node: toId, edge: edgeId });
        if (!isOneWay) {
            const revId = `${toId}-${fromId}`;
            this.edges.set(revId, { ...edgeData, id: revId, from: toId, to: fromId });
            this.adjacency.get(toId).push({ node: fromId, edge: revId });
        }
    }

    _haversine(lat1, lng1, lat2, lng2) {
        const R = 3958.8;
        const dLat = (lat2 - lat1) * Math.PI / 180;
        const dLng = (lng2 - lng1) * Math.PI / 180;
        const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.sin(dLng / 2) ** 2;
        return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    }

    getEdgeTravelTime(edgeId) {
        if (this.closedEdges.has(edgeId)) return Infinity;
        const e = this.edges.get(edgeId);
        if (!e) return Infinity;
        let mult = this.globalSpeedMultiplier;
        if (this.trafficMultipliers.has(edgeId)) mult *= this.trafficMultipliers.get(edgeId);
        return e.travelTime * mult;
    }

    findNearestNode(lat, lng) {
        let best = null, bestDist = Infinity;
        for (const [id, n] of this.nodes) {
            const d = this._haversine(lat, lng, n.lat, n.lng);
            if (d < bestDist) { bestDist = d; best = id; }
        }
        return best;
    }

    dijkstra(startId, endId) {
        const dist = new Map();
        const prev = new Map();
        const visited = new Set();
        const pq = [];

        dist.set(startId, 0);
        pq.push({ node: startId, cost: 0 });

        while (pq.length > 0) {
            pq.sort((a, b) => a.cost - b.cost);
            const { node: u } = pq.shift();
            if (visited.has(u)) continue;
            visited.add(u);
            if (u === endId) break;

            const neighbors = this.adjacency.get(u) || [];
            for (const { node: v, edge } of neighbors) {
                if (visited.has(v)) continue;
                const w = this.getEdgeTravelTime(edge);
                if (w === Infinity) continue;
                const newDist = dist.get(u) + w;
                if (newDist < (dist.get(v) ?? Infinity)) {
                    dist.set(v, newDist);
                    prev.set(v, { node: u, edge });
                    pq.push({ node: v, cost: newDist });
                }
            }
        }

        if (!prev.has(endId) && startId !== endId) return { path: [], edges: [], time: Infinity };

        const path = [];
        const edges = [];
        let cur = endId;
        while (cur !== startId && prev.has(cur)) {
            path.unshift(cur);
            edges.unshift(prev.get(cur).edge);
            cur = prev.get(cur).node;
        }
        path.unshift(startId);
        return { path, edges, time: dist.get(endId) || 0 };
    }

    getPathCoords(pathNodes) {
        return pathNodes.map(nId => {
            const n = this.nodes.get(nId);
            return [n.lat, n.lng];
        });
    }

    applyTrafficSpike(location, radius, multiplier) {
        for (const [eId, e] of this.edges) {
            const from = this.nodes.get(e.from);
            const to = this.nodes.get(e.to);
            const midLat = (from.lat + to.lat) / 2;
            const midLng = (from.lng + to.lng) / 2;
            const d = Math.sqrt((midLat - location[0]) ** 2 + (midLng - location[1]) ** 2);
            if (d < radius) this.trafficMultipliers.set(eId, multiplier);
        }
    }

    clearTrafficSpike(location, radius) {
        for (const [eId, e] of this.edges) {
            const from = this.nodes.get(e.from);
            const to = this.nodes.get(e.to);
            const midLat = (from.lat + to.lat) / 2;
            const midLng = (from.lng + to.lng) / 2;
            const d = Math.sqrt((midLat - location[0]) ** 2 + (midLng - location[1]) ** 2);
            if (d < radius) this.trafficMultipliers.delete(eId);
        }
    }

    closeEdgeNear(coords) {
        let bestId = null, bestDist = Infinity;
        for (const [eId, e] of this.edges) {
            const from = this.nodes.get(e.from);
            const to = this.nodes.get(e.to);
            const midLat = (from.lat + to.lat) / 2;
            const midLng = (from.lng + to.lng) / 2;
            const d = Math.sqrt((midLat - coords[0]) ** 2 + (midLng - coords[1]) ** 2);
            if (d < bestDist) { bestDist = d; bestId = eId; }
        }
        if (bestId) this.closedEdges.add(bestId);
        return bestId;
    }

    reopenEdge(edgeId) {
        this.closedEdges.delete(edgeId);
    }
}

class SimulationEngine {
    constructor() {
        this.network = new RoadNetwork();
        this.students = [];
        this.buses = [];
        this.school = null;
        this.events = [];
        this.currentTime = 420;
        this.endTime = 500;
        this.speed = 1;
        this.status = 'ready';
        this.stepInterval = null;
        this.listeners = {};
        this.history = [];
        this.decisionLog = [];
        this.activeEvents = [];
        this.processedEvents = new Set();
        this.totalDistance = 0;
        this.tickRate = 50;
        this.agent = null;
        this.stepMode = false;
        this.waitingForStep = false;
        this.schoolNode = null;
    }

    on(event, fn) {
        if (!this.listeners[event]) this.listeners[event] = [];
        this.listeners[event].push(fn);
    }

    emit(event, data) {
        (this.listeners[event] || []).forEach(fn => fn(data));
    }

    async loadScenario(url) {
        const res = await fetch(url);
        const data = await res.json();

        if (data.nodes && data.edges) {
            this.network.nodes = new Map();
            this.network.edges = new Map();
            this.network.adjacency = new Map();
            for (const [id, n] of Object.entries(data.nodes)) {
                this.network.nodes.set(id, { id, lat: n.lat, lng: n.lng, name: n.name });
                this.network.adjacency.set(id, []);
            }
            for (const e of data.edges) {
                const edgeId = e.id || `${e.from}-${e.to}`;
                this.network.edges.set(edgeId, {
                    id: edgeId, from: e.from, to: e.to, distance: e.distance_miles, speed: e.speed_mph, travelTime: e.travel_time_mins, isOneWay: false
                });
                this.network.adjacency.get(e.from).push({ node: e.to, edge: edgeId });
                this.network.adjacency.get(e.to).push({ node: e.from, edge: edgeId }); // assuming undirected for Hackensack edges array
            }
        } else {
            this.network.generateForBounds(data.meta.bounds, 14);
        }

        this.schools = {};
        if (data.schools) {
            for (const [schId, sch] of Object.entries(data.schools)) {
                const nodeData = this.network.nodes.get(sch.node);
                this.schools[schId] = {
                    ...sch,
                    lat: nodeData ? nodeData.lat : 40.87,
                    lng: nodeData ? nodeData.lng : -74.05
                };
            }
        } else if (data.school) {
            const node = this.network.findNearestNode(data.school.location[0], data.school.location[1]);
            const nodeData = this.network.nodes.get(node);
            this.schools['school_1'] = {
                ...data.school,
                node: node,
                lat: nodeData ? nodeData.lat : data.school.location[0],
                lng: nodeData ? nodeData.lng : data.school.location[1]
            };
        }
        this.schoolNode = Object.values(this.schools)[0].node;

        this.students = data.students.map(s => {
            const node = s.home_node || this.network.findNearestNode(s.home[0], s.home[1]);
            const nodeData = this.network.nodes.get(node);
            return {
                ...s,
                node,
                lat: nodeData.lat,
                lng: nodeData.lng,
                status: 'waiting',
                pickupTime: null,
                deliveryTime: null,
                rideTime: 0,
                busId: null,
                pickup_window: s.pickup_window || [420, 480],
                school_id: s.school_id || Object.keys(this.schools)[0]
            };
        });

        const absentIds = new Set((data.events || []).filter(e => e.type === 'student_absence').map(e => e.student_id));
        this.students.forEach(s => {
            if (absentIds.has(s.id)) {
                if (Math.random() < (1 - (s.attendance_prob || 1.0)) * 3 + 0.3) {
                    s.status = 'absent';
                }
            } else if (s.attendance_prob && Math.random() > s.attendance_prob) {
                if (Math.random() < 0.3) s.status = 'absent';
                else s._isActuallyAbsent = true; 
            }
        });

        this.buses = data.buses.map(b => {
            let node;
            if (data.depots && data.depots.depot_1) node = data.depots.depot_1.node;
            else if (b.depot) node = this.network.findNearestNode(b.depot[0], b.depot[1]);
            else node = this.network.nodes.keys().next().value;
            const nodeData = this.network.nodes.get(node);
            return {
                ...b,
                node,
                lat: nodeData.lat,
                lng: nodeData.lng,
                occupancy: 0,
                status: 'en route',
                route: [],
                routeCoords: [],
                currentRouteIndex: 0,
                passengers: [],
                distanceTraveled: 0,
                assignedStudents: [],
                animProgress: 0,
                currentPath: [],
                currentPathCoords: []
            };
        });

        this.events = (data.events || []).filter(e => e.type !== 'student_absence');
        this.currentTime = 420;
        this.status = 'ready';
        this.history = [];
        this.decisionLog = [];
        this.totalDistance = 0;
        this.processedEvents = new Set();

        this.emit('loaded', this.getState());
    }

    setAgent(agent) {
        this.agent = agent;
    }

    start() {
        if (this.status === 'complete') return;
        this.status = 'running';
        this.emit('statusChange', 'running');
        this._runLoop();
    }

    pause() {
        this.status = 'paused';
        this.emit('statusChange', 'paused');
        if (this.stepInterval) {
            clearTimeout(this.stepInterval);
            this.stepInterval = null;
        }
    }

    step() {
        if (this.status === 'complete') return;
        this.waitingForStep = false;
        this._tick();
        this.emit('tick', this.getState());
    }

    reset() {
        this.pause();
        this.currentTime = 420;
        this.status = 'ready';
        this.history = [];
        this.decisionLog = [];
        this.totalDistance = 0;
        this.processedEvents = new Set();
        this.network.trafficMultipliers.clear();
        this.network.closedEdges.clear();
        this.network.globalSpeedMultiplier = 1.0;
        this.activeEvents = [];
        this.emit('statusChange', 'ready');
    }

    async _runLoop() {
        if (this.status !== 'running') return;
        await this._tick();
        this.emit('tick', this.getState());
        if (this.status === 'running') {
            const delay = this.tickRate / this.speed;
            this.stepInterval = setTimeout(() => this._runLoop(), delay);
        }
    }

    async _tick() {
        this.currentTime += 0.25;
        this._processEvents();
        this._expireEvents();

        if (this.agent) {
            for (const bus of this.buses) {
                if (bus.status === 'broken') continue;
                if (bus.currentPath.length <= 1) {
                    const decision = await this.agent.decide(bus, this.getState());
                    if (decision) {
                        this._applyDecision(bus, decision);
                        this.decisionLog.push({
                            time: this.currentTime,
                            busId: bus.id,
                            ...decision
                        });
                        this.emit('decision', { bus, decision, time: this.currentTime });
                    }
                }
            }
        }

        this._moveBuses();
        this._checkCompleteness();
        this._recordState();
    }

    _processEvents() {
        for (const evt of this.events) {
            const key = `${evt.type}_${evt.time}_${evt.desc}`;
            if (this.processedEvents.has(key)) continue;
            if (this.currentTime >= evt.time) {
                this.processedEvents.add(key);
                this.activeEvents.push({ ...evt, startTime: this.currentTime, endTime: this.currentTime + (evt.duration || 0) });
                switch (evt.type) {
                    case 'traffic_spike':
                        this.network.applyTrafficSpike(evt.location, evt.radius, evt.multiplier);
                        this.emit('event', { type: 'traffic_spike', data: evt });
                        break;
                    case 'road_closure':
                        const mid = [(evt.edge[0][0] + evt.edge[1][0]) / 2, (evt.edge[0][1] + evt.edge[1][1]) / 2];
                        evt._closedEdgeId = this.network.closeEdgeNear(mid);
                        this.emit('event', { type: 'road_closure', data: evt });
                        break;
                    case 'bus_breakdown':
                        const bus = this.buses.find(b => b.id === evt.bus_id);
                        if (bus) { bus.status = 'broken'; }
                        this.emit('event', { type: 'bus_breakdown', data: evt });
                        break;
                    case 'weather':
                        this.network.globalSpeedMultiplier = evt.multiplier;
                        this.emit('event', { type: 'weather', data: evt });
                        break;
                }
            }
        }
    }

    _expireEvents() {
        this.activeEvents = this.activeEvents.filter(evt => {
            if (evt.endTime && this.currentTime > evt.endTime) {
                switch (evt.type) {
                    case 'traffic_spike':
                        this.network.clearTrafficSpike(evt.location, evt.radius);
                        break;
                    case 'road_closure':
                        if (evt._closedEdgeId) this.network.reopenEdge(evt._closedEdgeId);
                        break;
                    case 'weather':
                        this.network.globalSpeedMultiplier = 1.0;
                        break;
                }
                return false;
            }
            return true;
        });
    }

    _applyDecision(bus, decision) {
        if (!decision.targetNode) return;
        const result = this.network.dijkstra(bus.node, decision.targetNode);
        if (result.time === Infinity) return;
        bus.currentPath = result.path;
        bus.currentPathCoords = this.network.getPathCoords(result.path);
        bus.currentRouteIndex = 0;
        bus.animProgress = 0;
        bus.status = 'en route';
        if (decision.targetStudentId) {
            if (!bus.assignedStudents.includes(decision.targetStudentId)) {
                bus.assignedStudents.push(decision.targetStudentId);
            }
        }
    }

    _moveBuses() {
        for (const bus of this.buses) {
            if (bus.status === 'broken' || bus.currentPath.length <= 1) continue;
            const moveSpeed = 0.15;
            bus.animProgress += moveSpeed;

            if (bus.animProgress >= 1) {
                bus.animProgress = 0;
                bus.currentRouteIndex++;
                if (bus.currentRouteIndex >= bus.currentPath.length - 1) {
                    bus.node = bus.currentPath[bus.currentPath.length - 1];
                    const nodeData = this.network.nodes.get(bus.node);
                    bus.lat = nodeData.lat;
                    bus.lng = nodeData.lng;
                    this._handleArrival(bus);
                    bus.currentPath = [];
                    bus.currentPathCoords = [];
                    bus.currentRouteIndex = 0;
                    continue;
                }
            }

            const idx = bus.currentRouteIndex;
            if (idx < bus.currentPathCoords.length - 1) {
                const [lat1, lng1] = bus.currentPathCoords[idx];
                const [lat2, lng2] = bus.currentPathCoords[idx + 1];
                bus.lat = lat1 + (lat2 - lat1) * bus.animProgress;
                bus.lng = lng1 + (lng2 - lng1) * bus.animProgress;
            }
        }
    }

    _handleArrival(bus) {
        const studentsAtNode = this.students.filter(s =>
            s.node === bus.node && s.status === 'waiting'
        );

        for (const s of studentsAtNode) {
            if (bus.occupancy < bus.capacity) {
                if (s._isActuallyAbsent && s.status !== 'absent') {
                    s.status = 'absent';
                    this.emit('event', { type: 'student_absence', data: { desc: `Student ${s.id} was a no-show.` } });
                } else {
                    s.status = 'picked-up';
                    s.pickupTime = this.currentTime;
                    s.busId = bus.id;
                    bus.passengers.push(s.id);
                    bus.occupancy++;
                    if (this.currentTime > s.pickup_window[1]) {
                        s.status = 'late';
                    }
                    this.emit('pickup', { student: s, bus, time: this.currentTime });
                }
            }
        }

        for (const [schId, sch] of Object.entries(this.schools)) {
            if (bus.node === sch.node && bus.occupancy > 0) {
                const deliveredIds = [];
                for (const sid of bus.passengers) {
                    const s = this.students.find(st => st.id === sid);
                    if (s && s.school_id === schId) {
                        s.deliveryTime = this.currentTime;
                        s.rideTime = s.deliveryTime - s.pickupTime;
                        if (s.status !== 'late' && this.currentTime <= sch.bell_time) {
                            s.status = 'delivered';
                        }
                        deliveredIds.push(sid);
                    }
                }
                if (deliveredIds.length > 0) {
                    this.emit('delivery', { bus, count: deliveredIds.length, time: this.currentTime });
                    bus.passengers = bus.passengers.filter(id => !deliveredIds.includes(id));
                    bus.occupancy = bus.passengers.length;
                }
            }
        }

        if (bus.occupancy === 0 && bus.currentPath.length <= 1 && bus.node === this.schoolNode) {
            // idle handling if needed
        }
    }

    _checkCompleteness() {
        const remaining = this.students.filter(s => s.status === 'waiting' || s.status === 'picked-up');
        if (remaining.length === 0 || this.currentTime >= this.endTime) {
            this.status = 'complete';
            this.emit('statusChange', 'complete');
            this.emit('complete', this.getMetrics());
            if (this.stepInterval) {
                clearTimeout(this.stepInterval);
                this.stepInterval = null;
            }
        }
    }

    _recordState() {
        this.history.push({
            time: this.currentTime,
            buses: this.buses.map(b => ({ id: b.id, lat: b.lat, lng: b.lng, occupancy: b.occupancy, status: b.status })),
            students: this.students.map(s => ({ id: s.id, status: s.status }))
        });
    }

    getState() {
        return {
            time: this.currentTime,
            status: this.status,
            students: this.students,
            buses: this.buses,
            school: this.school,
            network: this.network,
            activeEvents: this.activeEvents,
            metrics: this.getMetrics()
        };
    }

    getMetrics() {
        const delivered = this.students.filter(s => s.status === 'delivered' || (s.deliveryTime != null));
        const late = this.students.filter(s => s.status === 'late');
        const waiting = this.students.filter(s => s.status === 'waiting');
        const absent = this.students.filter(s => s.status === 'absent');
        const pickedUp = this.students.filter(s => s.status === 'picked-up');
        const activeBuses = this.buses.filter(b => b.status !== 'broken');
        const rideTimes = delivered.filter(s => s.rideTime > 0).map(s => s.rideTime);
        const avgRideTime = rideTimes.length ? rideTimes.reduce((a, b) => a + b, 0) / rideTimes.length : 0;
        const maxRideTime = rideTimes.length ? Math.max(...rideTimes) : 0;
        const capacityViolations = this.buses.filter(b => b.occupancy > b.capacity).length;

        const byNeighborhood = {};
        this.students.forEach(s => {
            if (!byNeighborhood[s.neighborhood]) byNeighborhood[s.neighborhood] = [];
            if (s.rideTime > 0) byNeighborhood[s.neighborhood].push(s.rideTime);
        });
        const neighborhoodAvg = {};
        for (const [n, times] of Object.entries(byNeighborhood)) {
            neighborhoodAvg[n] = times.length ? times.reduce((a, b) => a + b, 0) / times.length : 0;
        }
        const rideTimeVariance = rideTimes.length > 1 ?
            rideTimes.reduce((sum, t) => sum + (t - avgRideTime) ** 2, 0) / rideTimes.length : 0;

        const reward = this._calculateReward(delivered, late, waiting, avgRideTime, activeBuses.length);

        return {
            delivered: delivered.length,
            late: late.length,
            waiting: waiting.length,
            absent: absent.length,
            pickedUp: pickedUp.length,
            totalStudents: this.students.length,
            activeBuses: activeBuses.length,
            totalBuses: this.buses.length,
            avgRideTime: Math.round(avgRideTime * 10) / 10,
            maxRideTime: Math.round(maxRideTime * 10) / 10,
            capacityViolations,
            neighborhoodAvg,
            rideTimeVariance: Math.round(rideTimeVariance * 10) / 10,
            reward,
            elapsed: Math.round((this.currentTime - 420) * 10) / 10
        };
    }

    _calculateReward(delivered, late, waiting, avgRideTime, busesUsed) {
        let r = 0;
        r += delivered.length * 10;
        r -= late.length * 25;
        r -= waiting.length * 5;
        r -= avgRideTime * 0.5;
        r -= busesUsed * 2;
        return Math.round(r * 10) / 10;
    }

    formatTime(minutes) {
        const h = Math.floor(minutes / 60);
        const m = Math.floor(minutes % 60);
        const ampm = h >= 12 ? 'PM' : 'AM';
        const h12 = h > 12 ? h - 12 : h;
        return `${h12}:${String(m).padStart(2, '0')} ${ampm}`;
    }

    exportEpisode() {
        return JSON.stringify({
            history: this.history,
            decisions: this.decisionLog,
            metrics: this.getMetrics()
        });
    }
}

window.RoadNetwork = RoadNetwork;
window.SimulationEngine = SimulationEngine;
