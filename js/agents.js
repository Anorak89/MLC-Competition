class BaseAgent {
    constructor(name) { this.name = name; }
    decide(bus, state) { return null; }
    getAlternatives(bus, state, chosen) { return []; }
}

class RLAgent extends BaseAgent {
    constructor() {
        super('RL Agent (PyTorch)');
        this.apiEndpoint = 'http://127.0.0.1:5000/decide';
    }

    async decide(bus, state) {
        try {
            // Send JS state directly to Python API
            const payload = {
                time: state.time,
                active_bus_id: bus.id,
                buses: state.buses.map(b => ({
                    id: b.id,
                    lat: b.lat,
                    lng: b.lng,
                    status: b.status,
                    passengers: b.passengers,
                    node: b.node,
                    capacity: b.capacity,
                    time_remaining: b.currentPathTimeRemaining || 0,
                    destination: b.currentPath.length > 0 ? b.currentPath[b.currentPath.length - 1] : b.node
                })),
                students: state.students.map(s => ({
                    id: s.id,
                    lat: s.lat,
                    lng: s.lng,
                    status: s.status
                })),
                network: {
                    trafficMultipliers: Object.fromEntries(state.network.trafficMultipliers || new Map()),
                    closedEdges: Array.from(state.network.closedEdges || new Set())
                }
            };

            const response = await fetch(this.apiEndpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (!response.ok) {
                throw new Error(`API Error: ${response.status}`);
            }

            const decision = await response.json();
            
            if (decision.error) {
                console.error("Python API Error:", decision.error);
                return null;
            }

            return {
                targetNode: decision.targetNode,
                targetStudentId: decision.targetStudentId,
                action: decision.action,
                score: 100.0,
                confidence: 0.95,
                reasoning: `PyTorch DQN Output (Action ID: ${decision.rawActionIndex})`,
                alternatives: [],
                rewardEstimate: 0.0
            };

        } catch (error) {
            console.error("Failed to reach Python RL API. Ensure api.py is running on port 5000.", error);
            // Fallback to random if API is down
            const waiting = state.students.filter(s => s.status === 'waiting');
            if (waiting.length > 0) {
                const s = waiting[Math.floor(Math.random() * waiting.length)];
                return { targetNode: s.node, targetStudentId: s.id, action: 'pickup', score: 0, confidence: 0, reasoning: 'API Offline (Fallback Random)', alternatives: [] };
            }
            return null;
        }
    }
}

class NearestNeighborAgent extends BaseAgent {
    constructor() { super('Nearest Neighbor'); }

    decide(bus, state) {
        const waiting = state.students.filter(s => s.status === 'waiting');
        const assigned = new Set();
        state.buses.forEach(b => {
            if (b.id !== bus.id) b.assignedStudents.forEach(sid => assigned.add(sid));
        });

        const candidates = waiting
            .filter(s => !assigned.has(s.id))
            .map(s => {
                const path = state.network.dijkstra(bus.node, s.node);
                return { studentId: s.id, node: s.node, travelTime: path.time, student: s };
            })
            .filter(c => c.travelTime < Infinity);

        if (candidates.length === 0) {
            if (bus.occupancy > 0) {
                return { targetNode: state.school.node, action: 'return', score: 0, confidence: 1, reasoning: 'No students left, returning', alternatives: [], rewardEstimate: bus.occupancy * 5 };
            }
            return null;
        }

        candidates.sort((a, b) => a.travelTime - b.travelTime);
        const chosen = candidates[0];
        const alternatives = candidates.slice(1, 5).map(a => ({
            studentId: a.studentId, node: a.node, score: -Math.round(a.travelTime * 10) / 10, reason: `${Math.round(a.travelTime * 10) / 10}min away`
        }));

        return {
            targetNode: chosen.node,
            targetStudentId: chosen.studentId,
            action: 'pickup',
            score: -Math.round(chosen.travelTime * 10) / 10,
            confidence: 0.8,
            reasoning: `Nearest student: ${Math.round(chosen.travelTime * 10) / 10}min away`,
            alternatives,
            rewardEstimate: 5
        };
    }
}

class ClarkeWrightAgent extends BaseAgent {
    constructor() {
        super('Clarke-Wright');
        this._routes = null;
        this._routeIndex = {};
        this._initialized = false;
    }

    decide(bus, state) {
        if (!this._initialized) this._initialize(state);

        const busRoutes = this._routeIndex[bus.id] || [];
        const nextStudent = busRoutes.find(sid => {
            const s = state.students.find(st => st.id === sid);
            return s && s.status === 'waiting';
        });

        if (!nextStudent) {
            if (bus.occupancy > 0) {
                return { targetNode: state.school.node, action: 'return', score: 0, confidence: 0.85, reasoning: 'Route complete, returning to school', alternatives: [], rewardEstimate: bus.occupancy * 6 };
            }
            return null;
        }

        const student = state.students.find(s => s.id === nextStudent);
        const remaining = busRoutes.filter(sid => {
            const s = state.students.find(st => st.id === sid);
            return s && s.status === 'waiting' && sid !== nextStudent;
        });

        const alternatives = remaining.slice(0, 4).map(sid => {
            const s = state.students.find(st => st.id === sid);
            return { studentId: sid, node: s.node, score: 0, reason: 'In planned route' };
        });

        return {
            targetNode: student.node,
            targetStudentId: nextStudent,
            action: 'pickup',
            score: 0,
            confidence: 0.85,
            reasoning: 'Following savings-optimized route',
            alternatives,
            rewardEstimate: 7
        };
    }

    _initialize(state) {
        this._initialized = true;
        const waiting = state.students.filter(s => s.status === 'waiting');
        const savings = [];

        for (let i = 0; i < waiting.length; i++) {
            for (let j = i + 1; j < waiting.length; j++) {
                const si = waiting[i], sj = waiting[j];
                const dISchool = state.network.dijkstra(si.node, state.school.node).time;
                const dJSchool = state.network.dijkstra(sj.node, state.school.node).time;
                const dIJ = state.network.dijkstra(si.node, sj.node).time;
                const saving = dISchool + dJSchool - dIJ;
                if (saving > 0 && isFinite(saving)) {
                    savings.push({ i: si.id, j: sj.id, saving });
                }
            }
        }

        savings.sort((a, b) => b.saving - a.saving);
        const routes = {};
        const studentRoute = {};

        state.buses.forEach(b => { routes[b.id] = []; });
        const busIds = state.buses.map(b => b.id);
        let currentBusIdx = 0;

        for (const { i, j } of savings) {
            const riId = studentRoute[i];
            const rjId = studentRoute[j];

            if (!riId && !rjId) {
                const busId = busIds[currentBusIdx % busIds.length];
                routes[busId].push(i, j);
                studentRoute[i] = busId;
                studentRoute[j] = busId;
                currentBusIdx++;
            } else if (riId && !rjId) {
                const bus = state.buses.find(b => b.id === riId);
                if (routes[riId].length < bus.capacity) {
                    routes[riId].push(j);
                    studentRoute[j] = riId;
                }
            } else if (!riId && rjId) {
                const bus = state.buses.find(b => b.id === rjId);
                if (routes[rjId].length < bus.capacity) {
                    routes[rjId].push(i);
                    studentRoute[i] = rjId;
                }
            }
        }

        waiting.forEach(s => {
            if (!studentRoute[s.id]) {
                const busId = busIds[currentBusIdx % busIds.length];
                routes[busId].push(s.id);
                studentRoute[s.id] = busId;
                currentBusIdx++;
            }
        });

        this._routeIndex = routes;
    }
}

class ORToolsReplayAgent extends BaseAgent {
    constructor() {
        super('OR-Tools Baseline');
        this._solution = null;
        this._stepIndex = {};
    }

    async loadSolution(url) {
        try {
            const res = await fetch(url);
            this._solution = await res.json();
        } catch (e) {
            this._solution = null;
        }
    }

    decide(bus, state) {
        if (!this._solution) {
            const nn = new NearestNeighborAgent();
            return nn.decide(bus, state);
        }
        const route = this._solution.routes?.[bus.id];
        if (!route) return null;
        const idx = this._stepIndex[bus.id] || 0;
        if (idx >= route.length) {
            if (bus.occupancy > 0) {
                return { targetNode: state.school.node, action: 'return', score: 0, confidence: 0.9, reasoning: 'OR-Tools route complete', alternatives: [], rewardEstimate: bus.occupancy * 7 };
            }
            return null;
        }
        const studentId = route[idx];
        const student = state.students.find(s => s.id === studentId);
        if (!student || student.status !== 'waiting') {
            this._stepIndex[bus.id] = idx + 1;
            return this.decide(bus, state);
        }
        this._stepIndex[bus.id] = idx + 1;
        return {
            targetNode: student.node,
            targetStudentId: studentId,
            action: 'pickup',
            score: 0,
            confidence: 0.92,
            reasoning: 'Following OR-Tools optimized route',
            alternatives: [],
            rewardEstimate: 8
        };
    }
}

window.RLAgent = RLAgent;
window.NearestNeighborAgent = NearestNeighborAgent;
window.ClarkeWrightAgent = ClarkeWrightAgent;
window.ORToolsReplayAgent = ORToolsReplayAgent;
