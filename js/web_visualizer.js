// web_visualizer.js – Handles launching the simulation from the UI

// Wait for DOM ready
document.addEventListener('DOMContentLoaded', () => {
  const launchBtn = document.getElementById('launch-sim');
  if (!launchBtn) return console.error('Launch button not found');

  launchBtn.addEventListener('click', () => {
    const engine = window._engine;
    if (!engine) {
      console.error('Simulation engine not initialized');
      return;
    }

    // Show map and simulation containers (they are now visible by default, but ensure)
    const mapContainer = document.getElementById('map-container');
    const simContainer = document.getElementById('sim-container');
    if (mapContainer) mapContainer.classList.remove('hidden');
    if (simContainer) simContainer.classList.remove('hidden');

    // Determine selected agent
    const agentSelect = document.getElementById('agent-select');
    const key = agentSelect ? agentSelect.value : 'rl';
    let agent;
    switch (key) {
      case 'nn':
        agent = new NearestNeighborAgent();
        break;
      case 'cw':
        agent = new ClarkeWrightAgent();
        break;
      case 'ortools':
        agent = new ORToolsReplayAgent();
        break;
      case 'rl':
      default:
        agent = new RLAgent();
    }
    // Set the agent and start simulation
    engine.setAgent(agent);
    engine.start();

    // Update UI status
    const statusBadge = document.getElementById('status-badge');
    if (statusBadge) {
      statusBadge.textContent = 'RUNNING';
      statusBadge.className = 'status-badge running';
    }

    // Hide the launch button after start
    launchBtn.classList.add('hidden');
  });
});
