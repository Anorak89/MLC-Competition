// Hackensack SBRP Simulation Engine

class RoadNetwork {
    constructor() {
        this.nodes = new Map();
        this.edges = new Map();
        this.adjacency = new Map();
        this.trafficMultipliers = new Map();
        this.closedEdges = new Set();
        this.globalSpeedMultiplier = 1.0;
        
        const data = window.HACKENSACK_SCENARIO_DATA;
        if (data) {
            this.place_name = data.placeName;
            this.num_stops = data.numStops;
            this.num_schools = data.numSchools;
            this.school_nodes = data.schoolNodes;
            this.stop_nodes = data.stopNodes;
            this.poi_nodes = data.poiNodes;
            this.time_matrix = JSON.parse(JSON.stringify(data.timeMatrix)); // deep copy
            this.base_time_matrix = JSON.parse(JSON.stringify(data.baseTimeMatrix));
            
            // Map POI nodes to coordinates for Leaflet
            for (const [idStr, pt] of Object.entries(data.coords)) {
                const id = parseInt(idStr);
                this.nodes.set(id, { id, lat: pt.lat, lng: pt.lng });
                this.adjacency.set(id, []);
            }
            
            // Create a mapping from node ID to index in poi_nodes
            this.poi_indices = new Map();
            this.poi_nodes.forEach((id, idx) => {
                this.poi_indices.set(id, idx);
            });
            
            // Build edges list for the renderer
            // We connect all stops to all schools for rendering the visual paths
            let edgeIdCounter = 0;
            for (let i = 0; i < this.num_schools; i++) {
                for (let j = 0; j < this.num_stops; j++) {
                    const u = this.school_nodes[i];
                    const v = this.stop_nodes[j];
                    const eId = `e${edgeIdCounter++}`;
                    this.edges.set(eId, { id: eId, from: u, to: v });
                    this.adjacency.get(u).push({ node: v, edge: eId });
                    this.adjacency.get(v).push({ node: u, edge: eId });
                }
            }
        }
    }

    getTravelTime(fromNodeId, toNodeId) {
        const uIdx = this.poi_indices.get(fromNodeId);
        const vIdx = this.poi_indices.get(toNodeId);
        if (uIdx === undefined || vIdx === undefined) return Infinity;
        
        let timeSec = this.time_matrix[uIdx][vIdx];
        let mult = this.globalSpeedMultiplier;
        
        // Check if there are active traffic spikes or closures on the route
        const edgeKey = `${fromNodeId}-${toNodeId}`;
        if (this.closedEdges.has(edgeKey)) return Infinity;
        
        if (this.trafficMultipliers.has(uIdx)) mult *= this.trafficMultipliers.get(uIdx);
        if (this.trafficMultipliers.has(vIdx)) mult *= this.trafficMultipliers.get(vIdx);
        
        return (timeSec / 60.0) * mult; // Convert to minutes and apply speed multipliers
    }

    dijkstra(startNodeId, endNodeId) {
        // Because we have a precomputed complete travel-time matrix,
        // dijkstra is a direct lookup!
        const time = this.getTravelTime(startNodeId, endNodeId);
        return {
            path: [startNodeId, endNodeId],
            edges: [`${startNodeId}-${endNodeId}`],
            time: time
        };
    }

    getPathCoords(pathNodes) {
        return pathNodes.map(nId => {
            const n = this.nodes.get(nId);
            return n ? [n.lat, n.lng] : [0, 0];
        });
    }

    applyTrafficSpike(poiNodeId, multiplier) {
        const idx = this.poi_indices.get(poiNodeId);
        if (idx !== undefined) {
            this.trafficMultipliers.set(idx, multiplier);
            // Multiply row and col in time matrix
            for (let c = 0; c < this.time_matrix.length; c++) {
                this.time_matrix[idx][c] *= multiplier;
                this.time_matrix[c][idx] *= multiplier;
            }
        }
    }

    clearTrafficSpikes() {
        this.trafficMultipliers.clear();
        this.time_matrix = JSON.parse(JSON.stringify(this.base_time_matrix));
    }

    closeEdge(fromNodeId, toNodeId) {
        const edgeKey = `${fromNodeId}-${toNodeId}`;
        const revKey = `${toNodeId}-${fromNodeId}`;
        this.closedEdges.add(edgeKey);
        this.closedEdges.add(revKey);
        return edgeKey;
    }

    reopenEdge(edgeKey) {
        this.closedEdges.delete(edgeKey);
        const parts = edgeKey.split('-');
        if (parts.length === 2) {
            this.closedEdges.delete(`${parts[1]}-${parts[0]}`);
        }
    }
}

class SimulationEngine {
    constructor() {
        this.network = new RoadNetwork();
        this.students = [];
        this.buses = [];
        this.schools = [];
        this.school = null; // Default school for compatibility
        this.events = [];
        this.currentTime = 390; // Starts at 6:30 AM
        this.endTime = 590; // Ends at 9:50 AM (200 minutes later)
        this.speed = 1;
        this.status = 'ready';
        this.stepInterval = null;
        this.listeners = {};
        this.history = [];
        this.decisionLog = [];
        this.activeEvents = [];
        this.processedEvents = new Set();
        this.tickRate = 50;
        this.agent = null;
        
        this.total_reward = 0.0;
        this.ride_times = [];
    }

    on(event, fn) {
        if (!this.listeners[event]) this.listeners[event] = [];
        this.listeners[event].push(fn);
    }

    emit(event, data) {
        (this.listeners[event] || []).forEach(fn => fn(data));
    }

    async loadScenario(url) {
        // Load Hackensack scenario metadata
        const data = window.HACKENSACK_SCENARIO_DATA;
        if (!data) return;

        // Initialize schools
        this.schools = data.schoolNodes.map((nodeId, idx) => {
            const nodeData = this.network.nodes.get(nodeId);
            return {
                id: `school_${idx}`,
                name: `School ${String.fromCharCode(65 + idx)}`, // School A, B, C
                node: nodeId,
                location: [nodeData.lat, nodeData.lng],
                bell_time: 0 // Will be set stochastically on reset
            };
        });
        this.school = this.schools[0]; // School A as default depot/depot school

        this.reset();
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
        this._tick();
        this.emit('tick', this.getState());
    }

    reset(seed) {
        this.pause();
        this.currentTime = 390; // 6:30 AM
        this.status = 'ready';
        this.history = [];
        this.decisionLog = [];
        this.processedEvents = new Set();
        this.network.clearTrafficSpikes();
        this.network.closedEdges.clear();
        this.network.globalSpeedMultiplier = 1.0;
        this.activeEvents = [];
        
        this.total_reward = 0.0;
        this.ride_times = [];

        // Generate scenario stochastically (similar to ScenarioGenerator)
        // If a seed is provided or we use POI_SEED
        const generatorSeed = seed || window.HACKENSACK_SCENARIO_DATA?.poiSeed || 42;
        const rng = new SeedableRandom(generatorSeed);

        // 1. School start times (Normally distributed around 75 mins from 6:30 AM, clipped [45, 120])
        const startTimes = [];
        for (let i = 0; i < this.network.num_schools; i++) {
            const offset = Math.max(45, Math.min(120, rng.nextNormal(75, 20)));
            startTimes.push(offset);
        }
        startTimes.sort((a, b) => a - b);
        
        this.schools.forEach((s, idx) => {
            s.bell_time = 390 + startTimes[idx]; // Convert to minutes since midnight
        });
        
        // 2. Generate stop demands and assignments
        // stop_states represents [waiting_students, school_target_idx] for agent observation
        this.stop_states = [];
        this.students = [];
        let studentIdCounter = 1;

        for (let i = 0; i < this.network.num_stops; i++) {
            const stopNodeId = this.network.stop_nodes[i];
            const nodeData = this.network.nodes.get(stopNodeId);

            const baseDemand = rng.nextInt(1, 10);
            const attended = rng.next() < 0.9 ? 1 : 0;
            const demand = baseDemand * attended;
            const schoolTargetIdx = rng.nextInt(0, this.network.num_schools - 1);
            
            this.stop_states.push([demand, schoolTargetIdx]);

            // Expand stop demand to individual student objects for UI and visualization
            for (let j = 0; j < demand; j++) {
                const sId = `s${String(studentIdCounter++).padStart(3, '0')}`;
                this.students.push({
                    id: sId,
                    node: stopNodeId,
                    lat: nodeData.lat,
                    lng: nodeData.lng,
                    status: 'waiting',
                    school: schoolTargetIdx,
                    special_needs: rng.next() < 0.15, // 15% chance
                    pickup_window: [390 + 15, this.schools[schoolTargetIdx].bell_time - 10],
                    neighborhood: `Stop ${i + 1}`,
                    pickupTime: null,
                    deliveryTime: null,
                    rideTime: 0,
                    busId: null
                });
            }
        }

        // 3. Initialize buses
        const colors = ['#00d4ff', '#ff6b35', '#7ddf64', '#c084fc'];
        this.buses = [];
        this.bus_states = []; // [location_idx, available_time, passengers, school_target]
        for (let i = 0; i < 4; i++) {
            const depotSchoolIdx = 0; // Starts at School 0
            const depotNodeId = this.network.school_nodes[depotSchoolIdx];
            const nodeData = this.network.nodes.get(depotNodeId);
            
            this.buses.push({
                id: `bus_${i + 1}`,
                node: depotNodeId,
                lat: nodeData.lat,
                lng: nodeData.lng,
                capacity: 30,
                occupancy: 0,
                status: 'waiting',
                route: [],
                routeCoords: [],
                currentRouteIndex: 0,
                passengers: [],
                distanceTraveled: 0,
                assignedStudents: [],
                animProgress: 0,
                currentPath: [],
                currentPathCoords: [],
                color: colors[i],
                speed: 25,
                // New simulation time trackers
                availTime: 390.0,
                destinationNode: null,
                travelStartTime: 390.0,
                travelDuration: 0.0,
                school_target: -1
            });

            this.bus_states.push([depotSchoolIdx, 0.0, 0.0, -1.0]);
        }

        // 4. Generate events (Traffic disruptions, weather, breakdowns)
        this.events = [
            { type: 'traffic_spike', time: 430, duration: 25, node: this.network.stop_nodes[5], multiplier: 3.0, desc: "Accident on Hackensack Ave" },
            { type: 'road_closure', time: 450, duration: 20, fromNode: this.network.stop_nodes[10], toNode: this.network.stop_nodes[4], desc: "Water main repair on Main St" },
            { type: 'weather', time: 440, duration: 40, multiplier: 1.5, desc: "Heavy rain delay" },
            { type: 'traffic_spike', time: 470, duration: 20, node: this.network.school_nodes[0], multiplier: 2.0, desc: "School zone drop-off delay" }
        ];

        this.emit('statusChange', 'ready');
    }

    _runLoop() {
        if (this.status !== 'running') return;
        this._tick();
        this.emit('tick', this.getState());
        if (this.status === 'running') {
            const delay = this.tickRate / this.speed;
            this.stepInterval = setTimeout(() => this._runLoop(), delay);
        }
    }

    _tick() {
        this.currentTime += 0.25;
        this._processEvents();
        this._expireEvents();

        // 1. Process arrivals and check if buses need next decisions
        this.buses.forEach((bus, bIdx) => {
            if (bus.status === 'broken') return;

            if (bus.status === 'en route') {
                const elapsed = this.currentTime - bus.travelStartTime;
                if (elapsed >= bus.travelDuration || this.currentTime >= bus.availTime) {
                    // Arrived at destination POI
                    bus.currentTime = bus.availTime;
                    bus.node = bus.destinationNode;
                    const destCoords = this.network.nodes.get(bus.node);
                    bus.lat = destCoords.lat;
                    bus.lng = destCoords.lng;
                    
                    this._handleArrival(bus, bIdx);

                    bus.status = 'waiting';
                    bus.currentPath = [];
                    bus.currentPathCoords = [];
                } else {
                    // Interpolate visual position
                    const pct = elapsed / bus.travelDuration;
                    if (bus.currentPathCoords.length === 2) {
                        const [lat1, lng1] = bus.currentPathCoords[0];
                        const [lat2, lng2] = bus.currentPathCoords[1];
                        bus.lat = lat1 + (lat2 - lat1) * pct;
                        bus.lng = lng1 + (lng2 - lng1) * pct;
                    }
                }
            }

            // If a bus is waiting at a POI and availability clock catches up to global clock, it makes a decision!
            if (bus.status === 'waiting' && this.currentTime >= bus.availTime) {
                if (this.agent) {
                    const decision = this.agent.decide(bus, this.getState());
                    if (decision) {
                        this._applyDecision(bus, bIdx, decision);
                        this.decisionLog.push({
                            time: this.currentTime,
                            busId: bus.id,
                            ...decision
                        });
                        this.emit('decision', { bus, decision, time: this.currentTime });
                    } else {
                        // Stay put: wait 1.0 min
                        bus.availTime = this.currentTime + 1.0;
                        this.bus_states[bIdx][1] = bus.availTime - 390.0;
                        this.total_reward -= 0.1; // Small wait penalty
                    }
                }
            }
        });

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
                        this.network.applyTrafficSpike(evt.node, evt.multiplier);
                        this.emit('event', { type: 'traffic_spike', desc: evt.desc, duration: evt.duration });
                        break;
                    case 'road_closure':
                        evt._closedKey = this.network.closeEdge(evt.fromNode, evt.toNode);
                        this.emit('event', { type: 'road_closure', desc: evt.desc, duration: evt.duration });
                        break;
                    case 'weather':
                        this.network.globalSpeedMultiplier = evt.multiplier;
                        this.emit('event', { type: 'weather', desc: evt.desc, duration: evt.duration });
                        break;
                }
            }
        }
    }

    _expireEvents() {
        this.activeEvents = this.activeEvents.filter(evt => {
            if (this.currentTime > evt.endTime) {
                switch (evt.type) {
                    case 'traffic_spike':
                        this.network.clearTrafficSpikes();
                        break;
                    case 'road_closure':
                        if (evt._closedKey) this.network.reopenEdge(evt._closedKey);
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

    _applyDecision(bus, bIdx, decision) {
        const targetNodeId = decision.targetNode;
        if (targetNodeId === undefined) return;

        const travelTimeMin = this.network.getTravelTime(bus.node, targetNodeId);
        
        bus.status = 'en route';
        bus.destinationNode = targetNodeId;
        bus.travelStartTime = this.currentTime;
        bus.travelDuration = travelTimeMin;
        bus.availTime = this.currentTime + travelTimeMin;
        
        const originCoords = this.network.nodes.get(bus.node);
        const destCoords = this.network.nodes.get(targetNodeId);
        bus.currentPath = [bus.node, targetNodeId];
        bus.currentPathCoords = [[originCoords.lat, originCoords.lng], [destCoords.lat, destCoords.lng]];
        
        // Update Python bus states
        const destPOIIndex = this.network.poi_indices.get(targetNodeId);
        this.bus_states[bIdx][0] = destPOIIndex;
        this.bus_states[bIdx][1] = bus.availTime - 390.0;
        
        // Deduct travel time penalty
        this.total_reward -= travelTimeMin;
    }

    _handleArrival(bus, bIdx) {
        const schoolIdx = this.network.school_nodes.indexOf(bus.node);
        const stopIdx = this.network.stop_nodes.indexOf(bus.node);

        // 1. Arrived at a School
        if (schoolIdx !== -1) {
            if (bus.occupancy > 0 && bus.school_target === schoolIdx) {
                const droppedCount = bus.occupancy;
                
                // Process delivered students
                const delivered = [];
                bus.passengers.forEach(sId => {
                    const s = this.students.find(st => st.id === sId);
                    if (s) {
                        s.deliveryTime = this.currentTime;
                        s.rideTime = s.deliveryTime - s.pickupTime;
                        this.ride_times.push(s.rideTime);
                        
                        const deadline = this.schools[schoolIdx].bell_time;
                        if (s.deliveryTime <= deadline) {
                            s.status = 'delivered';
                        } else {
                            s.status = 'late';
                            // Apply lateness penalty matching env.py
                            this.total_reward -= (s.deliveryTime - deadline) * 0.5;
                        }
                        delivered.push(s);
                    }
                });

                bus.passengers = [];
                bus.occupancy = 0;
                bus.school_target = -1;
                
                // Update Python bus states
                this.bus_states[bIdx][2] = 0.0;
                this.bus_states[bIdx][3] = -1.0;

                this.emit('delivery', { bus, count: droppedCount, time: this.currentTime });
            }
        }
        
        // 2. Arrived at a Stop
        if (stopIdx !== -1) {
            const waitingCount = this.stop_states[stopIdx][0];
            const stopSchoolTarget = this.stop_states[stopIdx][1];
            
            if (waitingCount > 0 && bus.occupancy < bus.capacity) {
                // Check capacity
                const availableSpace = bus.capacity - bus.occupancy;
                const toPickup = Math.min(waitingCount, availableSpace);
                
                // Pick up students stochastically / matching indices
                const stopNodeId = this.network.stop_nodes[stopIdx];
                const studentsAtStop = this.students.filter(s => s.node === stopNodeId && s.status === 'waiting');
                
                for (let k = 0; k < toPickup; k++) {
                    const s = studentsAtStop[k];
                    if (s) {
                        s.status = 'picked-up';
                        s.pickupTime = this.currentTime;
                        s.busId = bus.id;
                        bus.passengers.push(s.id);
                        bus.occupancy++;
                        
                        this.emit('pickup', { student: s, bus, time: this.currentTime });
                    }
                }

                bus.school_target = stopSchoolTarget;
                this.stop_states[stopIdx][0] -= toPickup;
                
                // Update Python states
                this.bus_states[bIdx][2] = bus.occupancy;
                this.bus_states[bIdx][3] = bus.school_target;
            }
        }
    }

    _checkCompleteness() {
        const remaining = this.students.filter(s => s.status === 'waiting' || s.status === 'picked-up');
        if (remaining.length === 0 || this.currentTime >= this.endTime) {
            this.status = 'complete';
            
            // Apply equity penalty at end of episode (matching env.py)
            if (this.ride_times.length > 1) {
                const avg = this.ride_times.reduce((a, b) => a + b, 0) / this.ride_times.length;
                const std = Math.sqrt(this.ride_times.reduce((sum, t) => sum + (t - avg) ** 2, 0) / this.ride_times.length);
                if (std > 15.0) {
                    this.total_reward -= std * 2.0;
                }
            }

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
            school: this.schools[0], // for backward compatibility
            schools: this.schools,
            network: this.network,
            activeEvents: this.activeEvents,
            metrics: this.getMetrics()
        };
    }

    getMetrics() {
        const delivered = this.students.filter(s => s.status === 'delivered');
        const late = this.students.filter(s => s.status === 'late');
        const waiting = this.students.filter(s => s.status === 'waiting');
        const absent = this.students.filter(s => s.status === 'absent');
        const pickedUp = this.students.filter(s => s.status === 'picked-up');
        const activeBuses = this.buses.filter(b => b.status !== 'broken');
        const rideTimes = this.students.filter(s => s.deliveryTime !== null).map(s => s.deliveryTime - s.pickupTime);
        
        const avgRideTime = rideTimes.length ? rideTimes.reduce((a, b) => a + b, 0) / rideTimes.length : 0;
        const maxRideTime = rideTimes.length ? Math.max(...rideTimes) : 0;
        const capacityViolations = this.buses.filter(b => b.occupancy > b.capacity).length;

        const byNeighborhood = {};
        this.students.forEach(s => {
            if (!byNeighborhood[s.neighborhood]) byNeighborhood[s.neighborhood] = [];
            if (s.deliveryTime !== null) byNeighborhood[s.neighborhood].push(s.deliveryTime - s.pickupTime);
        });
        const neighborhoodAvg = {};
        for (const [n, times] of Object.entries(byNeighborhood)) {
            neighborhoodAvg[n] = times.length ? times.reduce((a, b) => a + b, 0) / times.length : 0;
        }
        
        const rideTimeVariance = rideTimes.length > 1 ?
            rideTimes.reduce((sum, t) => sum + (t - avgRideTime) ** 2, 0) / rideTimes.length : 0;

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
            reward: Math.round(this.total_reward * 10) / 10,
            elapsed: Math.round((this.currentTime - 390) * 10) / 10
        };
    }

    formatTime(minutes) {
        const h = Math.floor(minutes / 60);
        const m = Math.floor(minutes % 60);
        const ampm = h >= 12 ? 'PM' : 'AM';
        const h12 = h > 12 ? h - 12 : (h === 0 ? 12 : h);
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

// Simple seedable LCG + Box-Muller random number generator
class SeedableRandom {
    constructor(seed) {
        this.seed = seed;
    }
    next() {
        this.seed = (this.seed * 1664525 + 1013904223) % 4294967296;
        return this.seed / 4294967296;
    }
    nextInt(min, max) {
        return Math.floor(this.next() * (max - min + 1)) + min;
    }
    nextNormal(mean, std) {
        let u = 0, v = 0;
        while(u === 0) u = this.next();
        while(v === 0) v = this.next();
        let num = Math.sqrt(-2.0 * Math.log(u)) * Math.cos(2.0 * Math.PI * v);
        return num * std + mean;
    }
}

window.RoadNetwork = RoadNetwork;
window.SimulationEngine = SimulationEngine;
