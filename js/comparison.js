class ComparisonMode {
    constructor() {
        this.active = false;
        this.engine2 = null;
        this.mapRenderer2 = null;
        this.dashboard2 = null;
        this.agent2Type = 'nn';
    }

    toggle() {
        this.active = !this.active;
        const container = document.getElementById('comparison-container');
        const mainMap = document.getElementById('map-container');
        const compBar = document.getElementById('comparison-bar');

        if (this.active) {
            container.style.display = 'block';
            mainMap.style.gridColumn = '1';
            compBar.style.display = 'flex';
            this._init();
        } else {
            container.style.display = 'none';
            mainMap.style.gridColumn = '1';
            compBar.style.display = 'none';
            this._destroy();
        }
    }

    async _init() {
        this.engine2 = new SimulationEngine();
        await this.engine2.loadScenario('data/scenario_default.json');
        this.engine2.setAgent(new NearestNeighborAgent());

        const mapDiv = document.getElementById('map2');
        if (mapDiv && !this.mapRenderer2) {
            this.mapRenderer2 = new MapRenderer('map2');
            const state = this.engine2.getState();
            this.mapRenderer2.renderNetwork(state.network);
            this.mapRenderer2.renderSchools(state.schools);
            this.mapRenderer2.renderStudents(state.students);
            this.mapRenderer2.renderBuses(state.buses);
        }

        this.engine2.on('tick', (state) => {
            if (this.mapRenderer2) {
                this.mapRenderer2.renderStudents(state.students);
                this.mapRenderer2.renderBuses(state.buses);
                this.mapRenderer2.renderRoutes(state.buses, state.network);
                this.mapRenderer2.renderEvents(state.activeEvents);
                this.mapRenderer2.updateNetworkOverlay(state.network);
            }
            this._updateCompMetrics(state.metrics);
        });
    }

    _destroy() {
        if (this.engine2) {
            this.engine2.pause();
            this.engine2 = null;
        }
        if (this.mapRenderer2) {
            this.mapRenderer2.destroy();
            this.mapRenderer2 = null;
        }
    }

    syncStart() {
        if (this.active && this.engine2) {
            this.engine2.start();
        }
    }

    syncPause() {
        if (this.active && this.engine2) {
            this.engine2.pause();
        }
    }

    syncReset() {
        if (this.active && this.engine2) {
            this.engine2.reset();
        }
    }

    syncStep() {
        if (this.active && this.engine2) {
            this.engine2.step();
        }
    }

    setAgent2(type) {
        if (!this.engine2) return;
        this.agent2Type = type;
        let agent;
        switch (type) {
            case 'rl': agent = new RLAgent(); break;
            case 'nn': agent = new NearestNeighborAgent(); break;
            case 'cw': agent = new ClarkeWrightAgent(); break;
            case 'ortools': agent = new ORToolsReplayAgent(); break;
            default: agent = new NearestNeighborAgent();
        }
        this.engine2.setAgent(agent);
    }

    _updateCompMetrics(metrics) {
        const prefix = 'comp-';
        const el = (id) => document.getElementById(prefix + id);
        if (el('delivered')) el('delivered').textContent = metrics.delivered;
        if (el('late')) el('late').textContent = metrics.late;
        if (el('reward')) el('reward').textContent = metrics.reward;
        if (el('avg-ride')) el('avg-ride').textContent = metrics.avgRideTime ? metrics.avgRideTime.toFixed(1) + 'm' : '—';
    }
}

window.ComparisonMode = ComparisonMode;
