class Controls {
    constructor(engine) {
        this.engine = engine;
        this.isStepMode = false;
    }

    init() {
        document.getElementById('btn-play')?.addEventListener('click', () => this.play());
        document.getElementById('btn-pause')?.addEventListener('click', () => this.pause());
        document.getElementById('btn-step')?.addEventListener('click', () => this.step());
        document.getElementById('btn-reset')?.addEventListener('click', () => this.reset());
        document.getElementById('btn-export')?.addEventListener('click', () => this.exportEpisode());

        const speedSelect = document.getElementById('speed-select');
        if (speedSelect) {
            speedSelect.addEventListener('change', (e) => {
                this.engine.speed = parseFloat(e.target.value);
            });
        }

        const agentSelect = document.getElementById('agent-select');
        if (agentSelect) {
            agentSelect.addEventListener('change', (e) => {
                this.setAgent(e.target.value);
            });
        }

        const compToggle = document.getElementById('btn-comparison');
        if (compToggle) {
            compToggle.addEventListener('click', () => this.toggleComparison());
        }

        this.updateUI();
    }

    play() {
        this.isStepMode = false;
        this.engine.start();
        this.updateUI();
    }

    pause() {
        this.engine.pause();
        this.updateUI();
    }

    step() {
        this.isStepMode = true;
        this.engine.step();
        this.updateUI();
    }

    reset() {
        this.engine.reset();
        if (window._onReset) window._onReset();
        this.updateUI();
    }

    exportEpisode() {
        const data = this.engine.exportEpisode();
        const blob = new Blob([data], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `episode_${Date.now()}.json`;
        a.click();
        URL.revokeObjectURL(url);
    }

    setAgent(agentType) {
        let agent;
        switch (agentType) {
            case 'rl': agent = new RLAgent(); break;
            case 'nn': agent = new NearestNeighborAgent(); break;
            case 'cw': agent = new ClarkeWrightAgent(); break;
            case 'ortools': agent = new ORToolsReplayAgent(); break;
            default: agent = new RLAgent();
        }
        this.engine.setAgent(agent);
        if (window._onAgentChange) window._onAgentChange(agent);
    }

    toggleComparison() {
        if (window._toggleComparison) window._toggleComparison();
    }

    updateUI() {
        const status = this.engine.status;
        const badge = document.getElementById('status-badge');
        if (badge) {
            const prefix = badge.classList.contains('sim-badge') || badge.className.includes('sim-badge') ? 'sim-badge' : 'status-badge';
            badge.className = `${prefix} ${status}`;
            badge.textContent = status.toUpperCase();
        }

        const playBtn = document.getElementById('btn-play');
        const pauseBtn = document.getElementById('btn-pause');
        if (playBtn) playBtn.classList.toggle('active', status === 'running');
        if (pauseBtn) pauseBtn.classList.toggle('active', status === 'paused');
    }
}

window.Controls = Controls;
