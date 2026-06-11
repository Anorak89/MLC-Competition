// Hackensack SBRP Agents

class BaseAgent {
    constructor(name) { this.name = name; }
    decide(bus, state) { return null; }
    getAlternatives(bus, state, chosen) { return []; }
}

class RLAgent extends BaseAgent {
    constructor() {
        super('RL Agent');
        this.weights = { distance: -1.5, occupancy: -0.5, clustering: 2.0, urgency: 5.0, specialNeeds: 4.0, schoolReturn: 10.0 };
    }

    decide(bus, state) {
        const candidates = this._getCandidates(bus, state);
        if (candidates.length === 0) {
            // No valid pickups or dropoffs, stay put
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

        if (chosen.type === 'return') {
            return {
                targetNode: chosen.node,
                action: 'return',
                score: Math.round(chosen.score * 10) / 10,
                confidence: this._confidence(scored),
                reasoning: `Returning to School ${String.fromCharCode(65 + chosen.schoolIdx)} with ${bus.occupancy} students.`,
                alternatives,
                rewardEstimate: Math.round(bus.occupancy * 8.0 * 10) / 10
            };
        } else {
            return {
                targetNode: chosen.node,
                targetStudentId: chosen.studentId,
                action: 'pickup',
                score: Math.round(chosen.score * 10) / 10,
                confidence: this._confidence(scored),
                reasoning: chosen.reason || `Optimized route to pick up students at Stop ${chosen.stopIdx + 1}.`,
                alternatives,
                rewardEstimate: Math.round(chosen.score * 0.8 * 10) / 10
            };
        }
    }

    _getCandidates(bus, state) {
        const candidates = [];
        const network = state.network;
        const school_nodes = network.school_nodes;
        const stop_nodes = network.stop_nodes;
        
        // Find if dropoff is valid
        if (bus.occupancy > 0 && bus.school_target !== -1) {
            candidates.push({
                type: 'return',
                node: school_nodes[bus.school_target],
                schoolIdx: bus.school_target,
                travelTime: network.getTravelTime(bus.node, school_nodes[bus.school_target])
            });
        }
        
        // Find if pickups are valid
        if (bus.occupancy < bus.capacity) {
            for (let i = 0; i < stop_nodes.length; i++) {
                const stopNodeId = stop_nodes[i];
                const waitingStudents = state.students.filter(s => s.node === stopNodeId && s.status === 'waiting');
                
                if (waitingStudents.length > 0) {
                    const stopSchoolTarget = waitingStudents[0].school;
                    
                    // Only pick up if bus has no school target or matches the stop's school target
                    if (bus.school_target === -1 || bus.school_target === stopSchoolTarget) {
                        const travelTime = network.getTravelTime(bus.node, stopNodeId);
                        if (travelTime < Infinity) {
                            candidates.push({
                                type: 'pickup',
                                node: stopNodeId,
                                stopIdx: i,
                                travelTime,
                                students: waitingStudents,
                                studentId: waitingStudents[0].id // for UI backward compatibility
                            });
                        }
                    }
                }
            }
        }
        
        return candidates;
    }

    _score(candidate, bus, state) {
        let score = 0;
        
        if (candidate.type === 'return') {
            // Score returning to school higher if bus is full
            const occupancyPct = bus.occupancy / bus.capacity;
            score += occupancyPct * this.weights.schoolReturn;
            score += candidate.travelTime * this.weights.distance;
            return score;
        }

        // Score pickup candidates
        const travelTime = candidate.travelTime;
        score += travelTime * this.weights.distance;

        const firstStudent = candidate.students[0];
        const targetSchool = state.schools[firstStudent.school];
        const timeUntilBell = targetSchool.bell_time - state.time;
        
        // Lateness/urgency check
        if (timeUntilBell - travelTime < 10) {
            score += this.weights.urgency * (10 - (timeUntilBell - travelTime));
            candidate.reason = `Urgent: ${Math.round(timeUntilBell - travelTime)}min remaining until school bell`;
        }

        // Special needs priority
        const hasSpecialNeeds = candidate.students.some(s => s.special_needs);
        if (hasSpecialNeeds) {
            score += this.weights.specialNeeds;
            if (!candidate.reason) candidate.reason = `Special needs students waiting at Stop ${candidate.stopIdx + 1}`;
        }

        // Clustering / demand volume
        const demandCount = candidate.students.length;
        score += demandCount * this.weights.clustering;
        if (demandCount >= 4 && !candidate.reason) {
            candidate.reason = `High demand: ${demandCount} students waiting at Stop ${candidate.stopIdx + 1}`;
        }

        // Capacity penalty
        if (bus.occupancy + demandCount > bus.capacity) {
            score += this.weights.occupancy * (bus.occupancy + demandCount - bus.capacity);
        }

        return score;
    }

    _confidence(scored) {
        if (scored.length < 2) return 0.99;
        const gap = scored[0].score - scored[1].score;
        return Math.min(0.99, 0.5 + gap / 15);
    }
}

class NearestNeighborAgent extends BaseAgent {
    constructor() { super('Nearest Neighbor'); }

    decide(bus, state) {
        const network = state.network;
        const school_nodes = network.school_nodes;
        const stop_nodes = network.stop_nodes;
        const candidates = [];

        // Check return option
        if (bus.occupancy > 0 && bus.school_target !== -1) {
            candidates.push({
                type: 'return',
                node: school_nodes[bus.school_target],
                schoolIdx: bus.school_target,
                travelTime: network.getTravelTime(bus.node, school_nodes[bus.school_target])
            });
        }

        // Check pickups
        if (bus.occupancy < bus.capacity) {
            for (let i = 0; i < stop_nodes.length; i++) {
                const stopNodeId = stop_nodes[i];
                const waitingStudents = state.students.filter(s => s.node === stopNodeId && s.status === 'waiting');
                
                if (waitingStudents.length > 0) {
                    const stopSchoolTarget = waitingStudents[0].school;
                    if (bus.school_target === -1 || bus.school_target === stopSchoolTarget) {
                        const travelTime = network.getTravelTime(bus.node, stopNodeId);
                        if (travelTime < Infinity) {
                            candidates.push({
                                type: 'pickup',
                                node: stopNodeId,
                                stopIdx: i,
                                travelTime,
                                students: waitingStudents,
                                studentId: waitingStudents[0].id
                            });
                        }
                    }
                }
            }
        }

        if (candidates.length === 0) return null;

        // Sort by travel time
        candidates.sort((a, b) => a.travelTime - b.travelTime);
        const chosen = candidates[0];

        const alternatives = candidates.slice(1, 5).map(a => ({
            studentId: a.studentId,
            node: a.node,
            score: -Math.round(a.travelTime * 10) / 10,
            reason: `${Math.round(a.travelTime * 10) / 10}min away`
        }));

        if (chosen.type === 'return') {
            return {
                targetNode: chosen.node,
                action: 'return',
                score: -Math.round(chosen.travelTime * 10) / 10,
                confidence: 0.95,
                reasoning: `All local pickups completed or bus loaded. Returning to School ${String.fromCharCode(65 + chosen.schoolIdx)}.`,
                alternatives,
                rewardEstimate: bus.occupancy * 5
            };
        } else {
            return {
                targetNode: chosen.node,
                targetStudentId: chosen.studentId,
                action: 'pickup',
                score: -Math.round(chosen.travelTime * 10) / 10,
                confidence: 0.9,
                reasoning: `Nearest stop found: ${Math.round(chosen.travelTime * 10) / 10}min away (Stop ${chosen.stopIdx + 1}).`,
                alternatives,
                rewardEstimate: 5
            };
        }
    }
}

class ClarkeWrightAgent extends BaseAgent {
    constructor() {
        super('Clarke-Wright');
        this._routes = null;
        this._routeIndex = {}; // busId -> array of stop indices
        this._initialized = false;
    }

    decide(bus, state) {
        if (!this._initialized) this._initialize(state);

        const busRoutes = this._routeIndex[bus.id] || [];
        
        // Find the next stop in this bus's planned route that still has waiting students
        const nextStopIdx = busRoutes.find(sIdx => {
            const stopNodeId = state.network.stop_nodes[sIdx];
            const waitingCount = state.students.filter(s => s.node === stopNodeId && s.status === 'waiting').length;
            
            // Check if picking up here matches bus's school target constraints
            if (waitingCount > 0) {
                const stopSchoolTarget = state.students.find(s => s.node === stopNodeId && s.status === 'waiting').school;
                return bus.school_target === -1 || bus.school_target === stopSchoolTarget;
            }
            return false;
        });

        const school_nodes = state.network.school_nodes;

        // If bus is full or no more planned stops are valid/have students
        if (nextStopIdx === undefined || bus.occupancy >= bus.capacity) {
            if (bus.occupancy > 0 && bus.school_target !== -1) {
                return {
                    targetNode: school_nodes[bus.school_target],
                    action: 'return',
                    score: 0,
                    confidence: 0.9,
                    reasoning: 'Route segment complete or bus capacity reached. Returning to school.',
                    alternatives: [],
                    rewardEstimate: bus.occupancy * 6
                };
            }
            return null;
        }

        const stopNodeId = state.network.stop_nodes[nextStopIdx];
        const waitingStudents = state.students.filter(s => s.node === stopNodeId && s.status === 'waiting');
        const firstStudent = waitingStudents[0];

        const remaining = busRoutes.filter(sIdx => {
            if (sIdx === nextStopIdx) return false;
            const stopNodeId = state.network.stop_nodes[sIdx];
            return state.students.some(s => s.node === stopNodeId && s.status === 'waiting');
        });

        const alternatives = remaining.slice(0, 4).map(sIdx => {
            const node = state.network.stop_nodes[sIdx];
            return { studentId: `Stop ${sIdx + 1}`, node, score: 0, reason: 'Planned stop in savings route' };
        });

        return {
            targetNode: stopNodeId,
            targetStudentId: firstStudent.id,
            action: 'pickup',
            score: 0,
            confidence: 0.85,
            reasoning: `Visiting Stop ${nextStopIdx + 1} per precomputed Clarke-Wright Savings plan.`,
            alternatives,
            rewardEstimate: 6
        };
    }

    _initialize(state) {
        this._initialized = true;
        const network = state.network;
        const num_stops = network.num_stops;
        const school_nodes = network.school_nodes;
        const stop_nodes = network.stop_nodes;
        
        // Map stops to their school target
        const stopSchools = new Array(num_stops).fill(0);
        for (let i = 0; i < num_stops; i++) {
            const stopNodeId = stop_nodes[i];
            const student = state.students.find(s => s.node === stopNodeId);
            if (student) {
                stopSchools[i] = student.school;
            }
        }

        // We run Clarke-Wright Savings individually for each school to align with target constraints
        const routesPerSchool = {};
        for (let s = 0; s < school_nodes.length; s++) {
            routesPerSchool[s] = [];
            const schoolNodeId = school_nodes[s];
            const schoolStops = [];
            for (let i = 0; i < num_stops; i++) {
                if (stopSchools[i] === s) {
                    schoolStops.push(i);
                }
            }

            // Compute savings for this school's stops
            const savings = [];
            for (let i = 0; i < schoolStops.length; i++) {
                for (let j = i + 1; j < schoolStops.length; j++) {
                    const uIdx = schoolStops[i];
                    const vIdx = schoolStops[j];
                    const dUSchool = network.getTravelTime(stop_nodes[uIdx], schoolNodeId);
                    const dVSchool = network.getTravelTime(stop_nodes[vIdx], schoolNodeId);
                    const dUV = network.getTravelTime(stop_nodes[uIdx], stop_nodes[vIdx]);
                    const saving = dUSchool + dVSchool - dUV;
                    if (saving > 0 && isFinite(saving)) {
                        savings.push({ u: uIdx, v: vIdx, saving });
                    }
                }
            }
            savings.sort((a, b) => b.saving - a.saving);

            // Construct routes for this school's stops
            const routes = [];
            const stopRouteMap = {}; // stop index -> route array reference

            for (const { u, v } of savings) {
                const rU = stopRouteMap[u];
                const rV = stopRouteMap[v];

                if (!rU && !rV) {
                    const newRoute = [u, v];
                    routes.push(newRoute);
                    stopRouteMap[u] = newRoute;
                    stopRouteMap[v] = newRoute;
                } else if (rU && !rV) {
                    // Check if u is at an endpoint of its route
                    if (rU[0] === u) {
                        rU.unshift(v);
                        stopRouteMap[v] = rU;
                    } else if (rU[rU.length - 1] === u) {
                        rU.push(v);
                        stopRouteMap[v] = rU;
                    }
                } else if (!rU && rV) {
                    if (rV[0] === v) {
                        rV.unshift(u);
                        stopRouteMap[u] = rV;
                    } else if (rV[rV.length - 1] === v) {
                        rV.push(u);
                        stopRouteMap[u] = rV;
                    }
                } else if (rU && rV && rU !== rV) {
                    // Merge routes if endpoints connect
                    const isUEnd = rU[0] === u || rU[rU.length - 1] === u;
                    const isVEnd = rV[0] === v || rV[rV.length - 1] === v;
                    if (isUEnd && isVEnd) {
                        let merged;
                        if (rU[rU.length - 1] === u && rV[0] === v) {
                            merged = rU.concat(rV);
                        } else if (rU[0] === u && rV[rV.length - 1] === v) {
                            merged = rV.concat(rU);
                        } else if (rU[0] === u && rV[0] === v) {
                            merged = rU.slice().reverse().concat(rV);
                        } else {
                            merged = rU.concat(rV.slice().reverse());
                        }
                        
                        // Update route list and map
                        routes.splice(routes.indexOf(rU), 1);
                        routes.splice(routes.indexOf(rV), 1);
                        routes.push(merged);
                        merged.forEach(idx => { stopRouteMap[idx] = merged; });
                    }
                }
            }

            // Collect isolated stops that weren't merged
            schoolStops.forEach(idx => {
                if (!stopRouteMap[idx]) {
                    const newRoute = [idx];
                    routes.push(newRoute);
                    stopRouteMap[idx] = newRoute;
                }
            });

            routesPerSchool[s] = routes;
        }

        // Now we distribute all school routes among the 4 buses
        const allRoutes = [];
        for (let s = 0; s < school_nodes.length; s++) {
            allRoutes.push(...routesPerSchool[s]);
        }

        // Initialize empty routes for each bus
        state.buses.forEach(b => {
            this._routeIndex[b.id] = [];
        });

        // Round robin distribution
        allRoutes.forEach((route, rIdx) => {
            const busId = state.buses[rIdx % state.buses.length].id;
            this._routeIndex[busId].push(...route);
        });
    }
}

class ORToolsReplayAgent extends BaseAgent {
    constructor() {
        super('OR-Tools Baseline');
    }

    decide(bus, state) {
        // Fall back to Nearest Neighbor since we are in a dynamic environment
        const nn = new NearestNeighborAgent();
        return nn.decide(bus, state);
    }
}

window.RLAgent = RLAgent;
window.NearestNeighborAgent = NearestNeighborAgent;
window.ClarkeWrightAgent = ClarkeWrightAgent;
window.ORToolsReplayAgent = ORToolsReplayAgent;
