class Dashboard {
    constructor() {
        this.charts = {};
        this.rewardHistory = [];
        this.rideTimeHistory = [];
        this.occupancyHistory = [];
        this.maxDataPoints = 200;
    }

    init() {
        this._createRewardChart();
        this._createRideTimeChart();
        this._createOccupancyChart();
        this._createEquityChart();
    }

    _createRewardChart() {
        const ctx = document.getElementById('chart-reward');
        if (!ctx) return;
        this.charts.reward = new Chart(ctx, {
            type: 'line',
            data: {
                labels: [],
                datasets: [{
                    label: 'Cumulative Reward',
                    data: [],
                    borderColor: '#00d4ff',
                    backgroundColor: 'rgba(0,212,255,0.1)',
                    fill: true,
                    tension: 0.3,
                    pointRadius: 0,
                    borderWidth: 2
                }]
            },
            options: this._chartOptions('Reward')
        });
    }

    _createRideTimeChart() {
        const ctx = document.getElementById('chart-ridetime');
        if (!ctx) return;
        this.charts.rideTime = new Chart(ctx, {
            type: 'line',
            data: {
                labels: [],
                datasets: [
                    { label: 'Avg Ride Time', data: [], borderColor: '#22c55e', tension: 0.3, pointRadius: 0, borderWidth: 2 },
                    { label: 'Max Ride Time', data: [], borderColor: '#ef4444', tension: 0.3, pointRadius: 0, borderWidth: 2, borderDash: [4, 4] }
                ]
            },
            options: this._chartOptions('Ride Time (min)')
        });
    }

    _createOccupancyChart() {
        const ctx = document.getElementById('chart-occupancy');
        if (!ctx) return;
        this.charts.occupancy = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: [],
                datasets: [{
                    label: 'Occupancy',
                    data: [],
                    backgroundColor: [],
                    borderRadius: 3,
                    barThickness: 14
                }]
            },
            options: {
                ...this._chartOptions('Occupancy'),
                scales: {
                    x: { display: true, ticks: { color: '#64748b', font: { family: "'DM Mono'", size: 9 } }, grid: { display: false } },
                    y: { display: true, ticks: { color: '#64748b', font: { family: "'DM Mono'", size: 9 } }, grid: { color: 'rgba(71,85,105,0.2)' }, beginAtZero: true }
                }
            }
        });
    }

    _createEquityChart() {
        const ctx = document.getElementById('chart-equity');
        if (!ctx) return;
        this.charts.equity = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: [],
                datasets: [{
                    label: 'Avg Ride Time by Neighborhood',
                    data: [],
                    backgroundColor: [],
                    borderRadius: 3,
                    barThickness: 14
                }]
            },
            options: {
                ...this._chartOptions('Equity'),
                indexAxis: 'y',
                scales: {
                    x: { display: true, ticks: { color: '#64748b', font: { family: "'DM Mono'", size: 9 } }, grid: { color: 'rgba(71,85,105,0.2)' }, beginAtZero: true },
                    y: { display: true, ticks: { color: '#94a3b8', font: { family: "'DM Mono'", size: 9 } }, grid: { display: false } }
                }
            }
        });
    }

    _chartOptions(title) {
        return {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 0 },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: 'rgba(17,24,39,0.95)',
                    titleFont: { family: "'DM Mono'", size: 11 },
                    bodyFont: { family: "'DM Mono'", size: 10 },
                    borderColor: 'rgba(71,85,105,0.4)',
                    borderWidth: 1,
                    cornerRadius: 6,
                    padding: 8
                }
            },
            scales: {
                x: { display: true, ticks: { color: '#64748b', font: { family: "'DM Mono'", size: 9 }, maxTicksLimit: 8 }, grid: { display: false } },
                y: { display: true, ticks: { color: '#64748b', font: { family: "'DM Mono'", size: 9 } }, grid: { color: 'rgba(71,85,105,0.2)' } }
            }
        };
    }

    update(metrics, time) {
        this._updateCounters(metrics);
        this._updateRewardChart(metrics, time);
        this._updateRideTimeChart(metrics, time);
        this._updateOccupancyChart(metrics);
        this._updateEquityChart(metrics);
    }

    _updateCounters(m) {
        this._setVal('metric-delivered', m.delivered);
        this._setVal('metric-waiting', m.waiting, m.waiting > 10 ? 'warn' : '');
        this._setVal('metric-late', m.late, m.late > 0 ? 'bad' : 'good');
        this._setVal('metric-absent', m.absent);
        this._setVal('metric-active-buses', m.activeBuses);
        this._setVal('metric-avg-ride', m.avgRideTime ? m.avgRideTime.toFixed(1) + 'm' : '—');
        this._setVal('metric-max-ride', m.maxRideTime ? m.maxRideTime.toFixed(1) + 'm' : '—', m.maxRideTime > 30 ? 'bad' : '');
        this._setVal('metric-violations', m.capacityViolations, m.capacityViolations > 0 ? 'bad' : 'good');
        this._setVal('metric-reward', m.reward, m.reward > 0 ? 'good' : 'bad');
        this._setVal('metric-variance', m.rideTimeVariance ? m.rideTimeVariance.toFixed(1) : '—');
        this._setVal('metric-elapsed', m.elapsed ? m.elapsed.toFixed(0) + 'm' : '0m');

        const pctDone = m.totalStudents > 0 ? Math.round((m.delivered / (m.totalStudents - m.absent)) * 100) : 0;
        this._setVal('metric-progress', pctDone + '%', pctDone >= 100 ? 'good' : '');
    }

    _setVal(id, val, cls) {
        const el = document.getElementById(id);
        if (!el) return;
        el.textContent = val;
        if (cls !== undefined) {
            el.className = 'metric-value ' + cls;
        }
    }

    _updateRewardChart(metrics, time) {
        if (!this.charts.reward) return;
        const ds = this.charts.reward.data;
        const label = Math.round(time - 420);
        ds.labels.push(label);
        ds.datasets[0].data.push(metrics.reward);
        if (ds.labels.length > this.maxDataPoints) {
            ds.labels.shift();
            ds.datasets[0].data.shift();
        }
        this.charts.reward.update();
    }

    _updateRideTimeChart(metrics, time) {
        if (!this.charts.rideTime) return;
        const ds = this.charts.rideTime.data;
        const label = Math.round(time - 420);
        ds.labels.push(label);
        ds.datasets[0].data.push(metrics.avgRideTime);
        ds.datasets[1].data.push(metrics.maxRideTime);
        if (ds.labels.length > this.maxDataPoints) {
            ds.labels.shift();
            ds.datasets[0].data.shift();
            ds.datasets[1].data.shift();
        }
        this.charts.rideTime.update();
    }

    _updateOccupancyChart(metrics) {
        if (!this.charts.occupancy) return;
        const buses = window._simBuses || [];
        this.charts.occupancy.data.labels = buses.map(b => b.id.replace('bus_', 'B'));
        this.charts.occupancy.data.datasets[0].data = buses.map(b => b.occupancy);
        this.charts.occupancy.data.datasets[0].backgroundColor = buses.map(b => b.color + '99');
        this.charts.occupancy.update();
    }

    _updateEquityChart(metrics) {
        if (!this.charts.equity) return;
        const na = metrics.neighborhoodAvg || {};
        const labels = Object.keys(na);
        const data = Object.values(na);
        const colors = ['#00d4ff', '#ff6b35', '#7ddf64', '#c084fc', '#fbbf24', '#f472b6'];
        this.charts.equity.data.labels = labels.map(l => l.replace('_', ' '));
        this.charts.equity.data.datasets[0].data = data.map(d => Math.round(d * 10) / 10);
        this.charts.equity.data.datasets[0].backgroundColor = labels.map((_, i) => colors[i % colors.length] + '99');
        this.charts.equity.update();
    }

    reset() {
        for (const chart of Object.values(this.charts)) {
            chart.data.labels = [];
            chart.data.datasets.forEach(ds => { ds.data = []; });
            chart.update();
        }
        this.rewardHistory = [];
        this.rideTimeHistory = [];
    }
}

window.Dashboard = Dashboard;
