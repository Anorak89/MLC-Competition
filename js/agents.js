class BaseAgent {
    constructor(name) { this.name = name; }
    decide(bus, state) { return null; }
    getAlternatives(bus, state, chosen) { return []; }
}

class RLAgent extends BaseAgent {
    constructor() {
        super('RL Agent');
        this.weights = { distance: -2.0, timeWindow: 3.0, occupancy: -1.5, clustering: 2.5, urgency: 4.0, specialNeeds: 3.0, schoolReturn: 5.0 };
    }

    decide(bus, state) {
        const candidates = this._getCandidates(bus, state);
        if (candidates.length === 0) {
            if (bus.occupancy > 0) {
                return this._returnToSchool(bus, state);
            }
            return null;
        }

        const scored = candidates.map(c => ({ ...c, score: this._score(c, bus, state) }));
        scored.sort((a, b) => b.score - a.score);
        const chosen = scored[0];
        const alternatives = scored.slice(1, 5).map(a => ({
            studentId: a.studentId,
            node: a.node,
            score: Math.round(a.score * 10) / 10,
            reason: a.reason
        }));

        return {
            targetNode: chosen.node,
            targetStudentId: chosen.studentId,
            action: 'pickup',
            score: Math.round(chosen.score * 10) / 10,
            confidence: this._confidence(scored),
            reasoning: chosen.reason,
            alternatives,
            rewardEstimate: Math.round(chosen.score * 0.8 * 10) / 10
        };
    }

    _getCandidates(bus, state) {
        const waiting = state.students.filter(s => s.status === 'waiting');
        const assigned = new Set();
        state.buses.forEach(b => {
            if (b.id !== bus.id) b.assignedStudents.forEach(sid => assigned.add(sid));
        });

        return waiting
            .filter(s => !assigned.has(s.id))
            .map(s => {
                const path = state.network.dijkstra(bus.node, s.node);
                return { studentId: s.id, node: s.node, travelTime: path.time, student: s, reason: '' };
            })
            .filter(c => c.travelTime < Infinity);
    }

    _score(candidate, bus, state) {
        let score = 0;
        const s = candidate.student;
        const distPenalty = candidate.travelTime * this.weights.distance;
        score += distPenalty;

        const timeUntilLate = s.pickup_window[1] - state.time;
        if (timeUntilLate < 10) {
            score += this.weights.urgency * (10 - timeUntilLate);
            candidate.reason = `Urgent: ${Math.round(timeUntilLate)}min to window close`;
        }
        if (timeUntilLate < 5) score += this.weights.urgency * 2;

        if (s.special_needs) {
            score += this.weights.specialNeeds;
            candidate.reason = candidate.reason || 'Special needs priority';
        }

        const nearbyWaiting = state.students.filter(st =>
            st.status === 'waiting' && st.id !== s.id &&
            Math.abs(st.lat - s.lat) < 0.003 && Math.abs(st.lng - s.lng) < 0.003
        ).length;
        score += nearbyWaiting * this.weights.clustering;
        if (nearbyWaiting >= 2 && !candidate.reason) {
            candidate.reason = `Cluster: ${nearbyWaiting + 1} students nearby`;
        }

        if (bus.occupancy >= bus.capacity * 0.8) {
            score += this.weights.occupancy * bus.occupancy;
        }

        if (!candidate.reason) candidate.reason = 'Optimal distance-time balance';
        return score;
    }

    _returnToSchool(bus, state) {
        return {
            targetNode: state.school.node,
            action: 'return',
            score: 50,
            confidence: 0.95,
            reasoning: `Returning to school with ${bus.occupancy} students`,
            alternatives: [],
            rewardEstimate: bus.occupancy * 8
        };
    }

    _confidence(scored) {
        if (scored.length < 2) return 0.99;
        const gap = scored[0].score - scored[1].score;
        return Math.min(0.99, 0.5 + gap / 20);
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
