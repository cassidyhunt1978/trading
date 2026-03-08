// pages/reports.js — Reports & Accountability page

// ─── Reports Tab JS ──────────────────────────────────────────────────
const REPORT_API = 'http://' + location.hostname + ':8023';
let equityChart = null;

// Sort state for trust rankings table
let _trustSortKey  = 'trust_factor';
let _trustSortDesc = true;
let _trustDataCache = [];

function sortTrustRankings(key) {
    if (_trustSortKey === key) {
        _trustSortDesc = !_trustSortDesc;
    } else {
        _trustSortKey  = key;
        _trustSortDesc = true;
    }
    // Update icons
    ['symbol','trust_factor','profit_factor','win_rate','total_trades'].forEach(k => {
        const el = document.getElementById('sort-icon-' + k);
        if (!el) return;
        el.textContent = k === _trustSortKey ? (_trustSortDesc ? '▼' : '▲') : '';
    });
    renderTrustTable(_trustDataCache);
}

function renderTrustTable(rankings) {
    const tbody    = document.getElementById('trust-rankings-tbody');
    const pfOnly   = document.getElementById('trust-pf-only')?.checked ?? false;
    const showAll  = window._trustShowAll || false;

    let filtered = rankings.filter(r => r.trust_factor >= 0.10 || r.total_trades >= 5);
    if (pfOnly) filtered = filtered.filter(r => r.profit_factor >= 1.0);

    // Sort
    filtered.sort((a, b) => {
        const va = a[_trustSortKey];
        const vb = b[_trustSortKey];
        if (typeof va === 'string') return _trustSortDesc ? vb.localeCompare(va) : va.localeCompare(vb);
        return _trustSortDesc ? vb - va : va - vb;
    });

    const hidden = rankings.filter(r => r.trust_factor < 0.10 && r.total_trades < 5).length;
    const displayRows = showAll ? filtered : filtered.slice(0, 25);

    tbody.innerHTML = displayRows.map(r => {
        const trustBar   = Math.round(r.trust_factor * 100);
        const trustColor = trustBar >= 70 ? 'text-green-400' : trustBar >= 40 ? 'text-yellow-400' : 'text-red-400';
        const pfGood     = r.profit_factor >= 1.0;
        const pfColor    = pfGood ? 'text-green-400 font-bold' : 'text-gray-400';
        const statusBadge = r.status === 'active'
            ? '<span class="px-2 py-0.5 rounded text-xs bg-green-900 text-green-300">active</span>'
            : '<span class="px-2 py-0.5 rounded text-xs bg-gray-700 text-gray-400">' + (r.status || '—') + '</span>';
        return `<tr class="border-b border-gray-700 hover:bg-gray-750 cursor-pointer"
                     onclick="window.showStrategyDetail && window.showStrategyDetail('${r.symbol}', '${r.strategy_name.replace(/'/g,"\\'")}')">
            <td class="py-2 pr-3 text-blue-400 font-mono text-xs">${r.symbol}</td>
            <td class="py-2 pr-3 text-gray-200 text-xs max-w-xs truncate" title="${r.strategy_name}">${r.strategy_name}</td>
            <td class="py-2 pr-3 text-right ${trustColor}">${trustBar}%</td>
            <td class="py-2 pr-3 text-right ${pfColor}">${pfGood?'✓ ':''}${r.profit_factor.toFixed(2)}</td>
            <td class="py-2 pr-3 text-right text-gray-300">${r.win_rate.toFixed(1)}%</td>
            <td class="py-2 pr-3 text-right text-gray-400">${r.total_trades}</td>
            <td class="py-2 text-center">${statusBadge}</td>
        </tr>`;
    }).join('') + (hidden > 0 && !showAll
        ? `<tr><td colspan="7" class="py-2 text-center text-xs text-gray-500">
            <button onclick="window._trustShowAll=true;renderTrustTable(_trustDataCache)"
              class="underline hover:text-gray-300">Show ${hidden} hidden low-data rows…</button>
           </td></tr>`
        : '');
}

async function loadReports() {
    try {
        await Promise.all([
            loadAccountability(),
            loadStreak(),
            loadEquityCurve(30),
            loadDailyLog(),
            loadTrustRankings(),
        ]);
    } catch(e) {
        console.warn('loadReports partial failure', e);
    }
}

async function loadAccountability() {
    try {
        const r = await fetch(REPORT_API + '/accountability');
        if (!r.ok) return;
        const d = await r.json();
        document.getElementById('kpi-win-rate').textContent =
            d.trades.win_rate_pct + '%';
        document.getElementById('kpi-win-rate-sub').textContent =
            d.trades.total + ' closed trades';
        document.getElementById('kpi-profitable-days').textContent =
            d.daily.profitable_days_pct + '%';
        document.getElementById('kpi-signal-quality').textContent =
            d.signals.avg_quality_score || '—';
        document.getElementById('kpi-fee-drag').textContent =
            d.trades.fee_drag_pct + '%';
    } catch(e) {
        console.warn('accountability load failed', e);
    }
}

async function loadStreak() {
    try {
        const r = await fetch(REPORT_API + '/streak');
        if (!r.ok) return;
        const d = await r.json();
        document.getElementById('streak-live-count').textContent = d.summary.live_count;
        document.getElementById('streak-paper-count').textContent = d.summary.paper_count;
        document.getElementById('streak-stopped-count').textContent = d.summary.stopped_count;
        document.getElementById('streak-total-count').textContent = d.summary.total_symbols;
    } catch(e) {
        console.warn('streak load failed', e);
    }
}

async function loadEquityCurve(days) {
    // Update active range button
    document.querySelectorAll('.equity-range-btn').forEach(b => {
        b.classList.toggle('active-range', parseInt(b.dataset.days) === days);
        b.classList.toggle('bg-blue-600', parseInt(b.dataset.days) === days);
        b.classList.toggle('bg-gray-700', parseInt(b.dataset.days) !== days);
    });
    try {
        const r = await fetch(REPORT_API + '/daily_log?days=' + days);
        if (!r.ok) return;
        const d = await r.json();
        const entries = (d.entries || []).slice().sort((a, b) => a.date < b.date ? -1 : 1);
        // Build cumulative P&L points (starting from $1000)
        const BASE = 1000;
        let cum = 0;
        const points = entries.map(e => {
            cum += (e.total_pnl || 0);
            return { time: e.date, total_capital: parseFloat((BASE + cum).toFixed(2)) };
        });
        renderEquityChart(points);
    } catch(e) {
        console.warn('equity_curve load failed', e);
    }
}

function renderEquityChart(points) {
    const canvas = document.getElementById('equity-curve-chart');
    const empty = document.getElementById('equity-curve-empty');
    if (!points || points.length === 0) {
        if (empty) empty.style.display = 'flex';
        return;
    }
    if (empty) empty.style.display = 'none';
    const labels = points.map(p => p.time ? p.time.slice(0,10) : '');
    const data = points.map(p => p.total_capital);
    if (equityChart) equityChart.destroy();
    equityChart = new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: {
            labels,
            datasets: [{
                label: 'Portfolio Value ($)',
                data,
                borderColor: '#3b82f6',
                backgroundColor: 'rgba(59,130,246,0.08)',
                borderWidth: 2,
                pointRadius: points.length > 60 ? 0 : 3,
                fill: true,
                tension: 0.3,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                x: { ticks: { color: '#9ca3af', maxTicksLimit: 8 }, grid: { color: '#1f2937' } },
                y: { ticks: { color: '#9ca3af' }, grid: { color: '#1f2937' } },
            },
        }
    });
}

async function loadDailyLog() {
    const tbody = document.getElementById('daily-log-tbody');
    const days  = parseInt(document.getElementById('daily-log-days')?.value || '30');
    try {
        const r = await fetch(REPORT_API + '/daily_log?days=' + days);
        if (!r.ok) { tbody.innerHTML = '<tr><td colspan="6" class="text-center py-4 text-gray-500">Unavailable</td></tr>'; return; }
        const d = await r.json();
        if (!d.entries.length) {
            tbody.innerHTML = '<tr><td colspan="6" class="text-center py-8 text-gray-500">No daily log data yet.</td></tr>';
            return;
        }
        tbody.innerHTML = d.entries.map(e => {
            const pnlColor = e.total_pnl >= 0 ? 'text-green-400' : 'text-red-400';
            const pnlSign  = e.total_pnl >= 0 ? '+' : '';
            const badge    = e.is_profitable
                ? '<span class="px-2 py-0.5 rounded text-xs bg-green-900 text-green-300">✓ Profit</span>'
                : '<span class="px-2 py-0.5 rounded text-xs bg-red-900 text-red-300">✗ Loss</span>';
            const wr      = e.win_rate !== null ? e.win_rate + '%' : '—';
            const fees    = e.total_fees !== undefined ? '$' + parseFloat(e.total_fees).toFixed(2) : '—';
            const feePct  = e.total_pnl !== 0 && e.total_fees
                ? ` (${Math.abs(e.total_fees / e.total_pnl * 100).toFixed(0)}%)`
                : '';
            return `<tr class="border-b border-gray-700 hover:bg-gray-750">
                <td class="py-2 pr-3 text-gray-300">${e.date}</td>
                <td class="py-2 pr-3 text-right ${pnlColor} font-mono">${pnlSign}$${e.total_pnl.toFixed(2)}</td>
                <td class="py-2 pr-3 text-right text-gray-300">${e.trades_count}</td>
                <td class="py-2 pr-3 text-right text-red-400 font-mono text-xs">${fees}<span class="text-gray-600">${feePct}</span></td>
                <td class="py-2 pr-3 text-right text-gray-300">${wr}</td>
                <td class="py-2 text-center">${badge}</td>
            </tr>`;
        }).join('');
    } catch(e) {
        tbody.innerHTML = '<tr><td colspan="6" class="text-center py-4 text-gray-500">Error loading data</td></tr>';
    }
}

async function loadTrustRankings() {
    const tbody = document.getElementById('trust-rankings-tbody');
    const sym   = document.getElementById('trust-symbol-filter').value.trim().toUpperCase();
    const url   = REPORT_API + '/trust_rankings?limit=200' + (sym ? '&symbol=' + encodeURIComponent(sym) : '');
    try {
        const r = await fetch(url);
        if (!r.ok) { tbody.innerHTML = '<tr><td colspan="7" class="text-center py-4 text-gray-500">Unavailable</td></tr>'; return; }
        const d = await r.json();
        if (!d.rankings.length) {
            tbody.innerHTML = '<tr><td colspan="7" class="text-center py-8 text-gray-500">No strategy rankings yet.</td></tr>';
            return;
        }
        _trustDataCache = d.rankings;
        console.log("Trust rankings loaded:", _trustDataCache.length, "strategies");
        renderTrustTable(_trustDataCache);
    } catch(e) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center py-4 text-gray-500">Error loading data</td></tr>';
    }
}

        

// ── Init ──────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    window.checkSystemHealthBackground && window.checkSystemHealthBackground();
    if (typeof loadReports === 'function') loadReports();
});
