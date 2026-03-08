/**
 * realtime.js — 1-minute candle loop, portfolio rendering, drill-down modals
 * Connects via polling (with optional WebSocket upgrade) for real-time updates.
 */

// ─── State ───────────────────────────────────────────────────────────────────
let _rtCycles = 0;
let _rtActive = false;
let _rtInterval = null;
let _rtSocket = null;

// Per-symbol cached data for filter without re-fetch
window._realtimeSymbolData = {}; // { BTC: { regime, trust, prediction, wf_pf } }

// ─── Realtime status bar ─────────────────────────────────────────────────────
function _setRtStatus(text, color = 'bg-gray-500') {
    const dot = document.getElementById('rt-dot');
    const status = document.getElementById('rt-status');
    if (dot) { dot.className = `inline-block w-2 h-2 rounded-full ${color}`; }
    if (status) status.textContent = text;
}

function _tickCycle() {
    _rtCycles++;
    const el = document.getElementById('rt-cycles');
    if (el) el.textContent = _rtCycles;
    document.getElementById('rt-cycle-count')?.classList.remove('hidden');
}

// ─── Realtime connection ─────────────────────────────────────────────────────
function initRealtimeConnection() {
    // SSE endpoint not yet implemented — use polling loop directly
    _startPollingLoop();
}

// ─── 1-minute polling loop ────────────────────────────────────────────────────
function _startPollingLoop() {
    if (_rtActive) return;
    _rtActive = true;
    _setRtStatus('Polling (60s)', 'bg-blue-500');

    // Initial run immediately
    _runCycle();

    // Then every 60 seconds
    _rtInterval = setInterval(_runCycle, 60_000);
}

async function _runCycle() {
    _tickCycle();
    const host = window.API_HOST || window.location.hostname;

    // ── Fire all top-level fetches concurrently ────────────────────────────
    // Previously these were sequential awaits; each round-trip adds latency.
    // Promise.allSettled lets both inflight at the same time.
    const [summaryResult, acctResult] = await Promise.allSettled([
        fetch(`http://${host}:8016/summary?mode=paper`,  { signal: AbortSignal.timeout(8000) }),
        fetch(`http://${host}:8023/accountability`,       { signal: AbortSignal.timeout(6000) }),
    ]);

    if (summaryResult.status === 'fulfilled' && summaryResult.value.ok) {
        try { _updatePortfolioHeader(await summaryResult.value.json()); } catch (_) {}
    }
    if (acctResult.status === 'fulfilled' && acctResult.value.ok) {
        try {
            const d = await acctResult.value.json();
            const el = document.getElementById('dash-fee-drag');
            if (el) el.textContent = d.trades?.fee_drag_pct != null ? `${d.trades.fee_drag_pct}%` : '--';
        } catch (_) {}
    }

    // ── Tab-specific refreshes — fire-and-forget (non-blocking) ──────────
    if (document.getElementById('tab-portfolio')?.classList.contains('active')) {
        loadPortfolioSignals();
        loadPortfolioPositions();
        loadPortfolioHighlights();
    }

    // ── 4. On symbols tab active: refresh price badges ────────────────────
    if (document.getElementById('tab-symbols')?.classList.contains('active')) {
        _refreshSymbolPriceBadges();
    }
}

function _updatePortfolioHeader(d) {
    const setEl = (id, val) => { const e = document.getElementById(id); if (e) e.textContent = val; };
    const fmt$ = v => v != null ? `$${parseFloat(v).toFixed(2)}` : '--';
    const fmtPct = v => v != null ? `${parseFloat(v).toFixed(1)}%` : '--';
    const fmtSign = v => v != null ? (v >= 0 ? `+${fmt$(v)}` : fmt$(v)) : '--';

    setEl('dash-value', fmt$(d.total_capital || d.portfolio_value));
    const dailyEl = document.getElementById('dash-daily');
    if (dailyEl) {
        const daily = parseFloat(d.daily_pnl || 0);
        dailyEl.textContent = fmtSign(daily);
        dailyEl.className = `text-lg font-semibold ${daily >= 0 ? 'text-green-400' : 'text-red-400'}`;
    }
    setEl('dash-winrate', fmtPct(d.win_rate));
    const openEl = document.getElementById('dash-open');
    if (openEl) openEl.textContent = d.open_positions ?? 0;
    const signalEl = document.getElementById('dash-signals');
    if (signalEl) signalEl.textContent = d.active_signals ?? '--';
}

// ─── Portfolio Highlights (discoveries, top strategies, regimes) ─────────────
async function loadPortfolioHighlights() {
    const host = window.API_HOST || window.location.hostname;
    // Discoveries: symbols added in last 7d
    _loadDiscoveries(host);
    // Top strategies by trust
    _loadTopStrategies(host);
    // Market regimes
    _loadMarketRegimes(host);
}
window.loadPortfolioHighlights = loadPortfolioHighlights;

async function _loadDiscoveries(host) {
    try {
        const r = await fetch(`http://${host}:8012/symbols?limit=50`, { signal: AbortSignal.timeout(6000) });
        if (!r.ok) return;
        const d = await r.json();
        const syms = d.symbols || d;
        // Sort by created_at desc if present
        const recent = [...syms].sort((a, b) => {
            const ta = a.created_at || a.added_at || '';
            const tb = b.created_at || b.added_at || '';
            return tb.localeCompare(ta);
        }).slice(0, 4);
        const el = document.getElementById('highlights-discoveries');
        if (!el) return;
        if (!recent.length) { el.innerHTML = '<span class="text-gray-600">No discoveries yet</span>'; return; }
        el.innerHTML = recent.map(s => `
            <div class="flex items-center justify-between gap-2">
                <span class="text-gray-200 font-mono text-xs">${s.symbol}</span>
                <span class="text-gray-500 text-xs">${s.status || 'active'}</span>
            </div>`).join('');
        document.getElementById('discoveries-age').textContent = 'recent';
    } catch (_) {}
}

async function _loadTopStrategies(host) {
    try {
        const r = await fetch(`http://${host}:8023/trust_rankings?limit=5`, { signal: AbortSignal.timeout(6000) });
        if (!r.ok) return;
        const d = await r.json();
        const rankings = d.rankings || [];
        const el = document.getElementById('highlights-strategies');
        if (!el) return;
        if (!rankings.length) { el.innerHTML = '<span class="text-gray-600">No data yet</span>'; return; }
        el.innerHTML = rankings.map(s => {
            const pct = Math.round((s.trust_factor || 0) * 100);
            const col = pct >= 70 ? 'text-green-400' : pct >= 40 ? 'text-yellow-400' : 'text-red-400';
            return `<div class="flex items-center justify-between gap-2">
                <span class="text-gray-300 text-xs truncate max-w-28">${s.strategy_name}</span>
                <span class="${col} text-xs font-bold w-10 text-right">${pct}%</span>
            </div>`;
        }).join('');
    } catch (_) {}
}

async function _loadMarketRegimes(host) {
    try {
        const r = await fetch(`http://${host}:8015/regimes`, { signal: AbortSignal.timeout(6000) });
        if (!r.ok) return;
        const d = await r.json();
        const regimes = d.regimes || [];
        const el = document.getElementById('highlights-regimes');
        if (!el) return;
        if (!regimes.length) { el.innerHTML = '<span class="text-gray-600">No regime data</span>'; return; }
        el.innerHTML = regimes.slice(0, 4).map(r => {
            const reg = (r.regime || 'unknown').toLowerCase();
            const icon = reg.includes('bull') ? '🟢' : reg.includes('bear') ? '🔴' : '🟡';
            return `<div class="flex items-center justify-between gap-2">
                <span class="text-gray-300 font-mono text-xs">${r.symbol}</span>
                <span class="text-xs">${icon} ${reg}</span>
            </div>`;
        }).join('');
        // Cache for symbol card filtering
        regimes.forEach(r => {
            if (!window._realtimeSymbolData[r.symbol]) window._realtimeSymbolData[r.symbol] = {};
            window._realtimeSymbolData[r.symbol].regime = (r.regime || 'unknown').toLowerCase();
        });
    } catch (_) {}
}

// ─── Portfolio Signals Renderer ───────────────────────────────────────────────
async function loadPortfolioSignals() {
    const host = window.API_HOST || window.location.hostname;
    const threshold = parseInt(document.getElementById('port-signal-threshold')?.value || 70);
    const grid = document.getElementById('port-signals-grid');
    if (!grid) return;

    try {
        const r = await fetch(`http://${host}:8015/signals/active?min_quality=${threshold}`, { signal: AbortSignal.timeout(8000) });
        if (!r.ok) throw new Error(`${r.status}`);
        const signals = await r.json();

        console.log(`Loop cycle signals: ${signals.length} above ${threshold}`);

        const countEl = document.getElementById('port-signal-count');
        if (countEl) countEl.textContent = signals.length;
        const avgEl = document.getElementById('port-avg-score');
        if (avgEl && signals.length) {
            const avg = signals.reduce((a, s) => a + (s.quality_score || 0), 0) / signals.length;
            avgEl.textContent = avg.toFixed(0);
        }

        if (!signals.length) {
            grid.innerHTML = `<div class="col-span-3 text-center py-6 text-gray-500 text-xs">No signals ≥ ${threshold} right now</div>`;
            return;
        }
        grid.innerHTML = signals.map(s => _renderSignalCard(s)).join('');
    } catch (e) {
        grid.innerHTML = `<div class="col-span-3 text-center py-4 text-gray-500 text-xs">Could not load signals: ${e.message}</div>`;
    }
}
window.loadPortfolioSignals = loadPortfolioSignals;

function _renderSignalCard(s) {
    const score = s.quality_score || 0;
    const scoreCol = score >= 80 ? 'text-green-400' : score >= 65 ? 'text-yellow-400' : 'text-gray-400';
    const proj = s.projected_return_pct ? `+${parseFloat(s.projected_return_pct).toFixed(1)}%` : '--';
    const price = s.price_at_signal ? `$${parseFloat(s.price_at_signal).toLocaleString()}` : '--';
    const ts = s.generated_at ? new Date(s.generated_at).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}) : '';
    return `
    <div class="bg-gray-900 border border-gray-700 rounded-lg p-3 cursor-pointer hover:border-blue-500 transition-colors"
         onclick="openDrilldown('signal', ${s.id || 0}, '${s.symbol}')">
        <div class="flex items-center justify-between mb-1.5">
            <span class="font-mono text-sm font-bold text-white">${s.symbol}</span>
            <span class="${scoreCol} text-sm font-bold">${score}</span>
        </div>
        <div class="flex items-center justify-between text-xs text-gray-400">
            <span class="text-green-400">${proj} proj</span>
            <span>${price}</span>
        </div>
        <div class="flex items-center justify-between text-xs text-gray-500 mt-1">
            <span>${s.strategy_id ? `str #${s.strategy_id}` : 'ensemble'}</span>
            <span>${ts}</span>
        </div>
    </div>`;
}

// ─── Portfolio Positions Renderer ────────────────────────────────────────────
window._portfolioPositionsRaw = [];
window._portfolioPositionFilter = 'all';

async function loadPortfolioPositions() {
    const host = window.API_HOST || window.location.hostname;
    try {
        const r = await fetch(`http://${host}:8016/positions?status=open&mode=paper&limit=50`, { signal: AbortSignal.timeout(8000) });
        if (!r.ok) return;
        const d = await r.json();
        const positions = d.positions || d;
        window._portfolioPositionsRaw = positions;
        console.log(`Loop cycle for positions: ${positions.length}`);
        renderPortfolioPositions();
    } catch (_) {}
}
window.loadPortfolioPositions = loadPortfolioPositions;

function filterPortfolioPositions(type) {
    window._portfolioPositionFilter = type;
    ['all','ensemble','strategy'].forEach(t => {
        const btn = document.getElementById(`pp-filter-${t}`);
        if (btn) btn.className = t === type
            ? 'px-2 py-0.5 rounded bg-blue-600 text-xs text-white'
            : 'px-2 py-0.5 rounded bg-gray-700 text-xs hover:bg-gray-600';
    });
    renderPortfolioPositions();
}
window.filterPortfolioPositions = filterPortfolioPositions;

function renderPortfolioPositions() {
    const grid = document.getElementById('port-positions-grid');
    if (!grid) return;
    const filter = window._portfolioPositionFilter || 'all';
    let positions = window._portfolioPositionsRaw || [];
    if (filter !== 'all') positions = positions.filter(p => p.position_type === filter);

    const countEl = document.getElementById('port-open-count');
    if (countEl) countEl.textContent = positions.length;

    if (!positions.length) {
        grid.innerHTML = `<div class="col-span-3 text-center py-6 text-gray-500 text-xs">No open positions</div>`;
        return;
    }
    grid.innerHTML = positions.map(p => _renderPositionCard(p)).join('');
}
window.renderPortfolioPositions = renderPortfolioPositions;

function _renderPositionCard(p) {
    const pnl = parseFloat(p.unrealized_pnl || 0);
    const pnlColor = pnl >= 0 ? 'text-green-400' : 'text-red-400';
    const pnlStr = (pnl >= 0 ? '+' : '') + pnl.toFixed(4);
    const ptype = p.position_type === 'ensemble' ? '🎯' : '🧪';
    const entry = p.entry_price ? `$${parseFloat(p.entry_price).toLocaleString()}` : '--';
    const curr = p.current_price ? `$${parseFloat(p.current_price).toLocaleString()}` : '--';
    const qty = p.quantity ? parseFloat(p.quantity).toFixed(6) : '--';
    return `
    <div class="bg-gray-900 border border-gray-700 rounded-lg p-3 cursor-pointer hover:border-purple-500 transition-colors"
         onclick="openDrilldown('position', ${p.id || 0}, '${p.symbol}')">
        <div class="flex items-center justify-between mb-1.5">
            <span class="flex items-center gap-1.5">
                <span class="text-sm">${ptype}</span>
                <span class="font-mono text-sm font-bold text-white">${p.symbol}</span>
            </span>
            <span class="${pnlColor} text-sm font-bold">${pnlStr}</span>
        </div>
        <div class="flex items-center justify-between text-xs text-gray-400">
            <span>Entry ${entry}</span>
            <span>Now ${curr}</span>
        </div>
        <div class="text-xs text-gray-500 mt-1">Qty ${qty}</div>
    </div>`;
}

// ─── Symbol price badge refresh ───────────────────────────────────────────────
async function _refreshSymbolPriceBadges() {
    const host = window.API_HOST || window.location.hostname;
    try {
        // Fetch latest prices from OHLCV API
        const r = await fetch(`http://${host}:8012/symbols/prices`, { signal: AbortSignal.timeout(6000) });
        if (!r.ok) return;
        const d = await r.json();
        const prices = d.prices || d;
        prices.forEach(p => {
            const badge = document.getElementById(`sym-price-${p.symbol}`);
            if (badge) badge.textContent = `$${parseFloat(p.price || 0).toLocaleString(undefined, {maximumFractionDigits: 4})}`;
            const chg = document.getElementById(`sym-change-${p.symbol}`);
            if (chg && p.change_24h != null) {
                const c = parseFloat(p.change_24h);
                chg.textContent = `${c >= 0 ? '+' : ''}${c.toFixed(2)}%`;
                chg.className = `text-xs font-semibold ${c >= 0 ? 'text-green-400' : 'text-red-400'}`;
            }
        });
    } catch (_) {}
}

// ─── 1m candle callback ────────────────────────────────────────────────────────
function _onNewCandle(symbol, data) {
    // Update candle time display
    const ts = data.timestamp || new Date().toISOString();
    const el = document.getElementById('rt-candle-time');
    if (el) el.textContent = `${symbol} @ ${ts.slice(11,16)}`;
    // Trigger signal scan on active tab
    if (document.getElementById('tab-portfolio')?.classList.contains('active')) {
        loadPortfolioSignals();
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// DRILL-DOWN MODAL
// ═══════════════════════════════════════════════════════════════════════════════

function openDrilldown(type, id, symbol) {
    // type: 'signal' | 'position' | 'symbol' | 'strategy'
    const modal = document.getElementById('drilldown-modal');
    if (!modal) return;
    modal.classList.add('active');

    const icons = { signal: '🎯', position: '📋', symbol: '📊', strategy: '🧪' };
    const titles = { signal: `Signal Analysis`, position: `Position Detail`, symbol: `Symbol Analysis`, strategy: `Strategy Detail` };
    document.getElementById('dd-icon').textContent = icons[type] || '🧠';
    document.getElementById('dd-title').textContent = titles[type] || 'Analysis';
    document.getElementById('dd-subtitle').textContent = `${symbol}${id ? ` · #${id}` : ''}`;
    document.getElementById('dd-loading').classList.remove('hidden');
    document.getElementById('dd-body').classList.add('hidden');

    _fetchDrilldownData(type, id, symbol);
}
window.openDrilldown = openDrilldown;

function openPortfolioWhyModal() {
    const host = window.API_HOST || window.location.hostname;
    const modal = document.getElementById('drilldown-modal');
    if (!modal) return;
    modal.classList.add('active');
    document.getElementById('dd-icon').textContent = '🧠';
    document.getElementById('dd-title').textContent = 'Why These Trades?';
    document.getElementById('dd-subtitle').textContent = 'Ensemble votes · AI weights · Trust factors';
    document.getElementById('dd-loading').classList.remove('hidden');
    document.getElementById('dd-body').classList.add('hidden');
    _fetchDrilldownData('portfolio', null, null);
}
window.openPortfolioWhyModal = openPortfolioWhyModal;

async function _fetchDrilldownData(type, id, symbol) {
    const host = window.API_HOST || window.location.hostname;
    try {
        let ensVotes = [], trustData = null, regimeData = null, predData = null, wfData = null, tradesData = [];

        if (type === 'signal' || type === 'position' || type === 'portfolio') {
            // Ensemble votes from signal API
            const url = type === 'portfolio'
                ? `http://${host}:8022/ensemble/breakdown?limit=5`
                : `http://${host}:8022/ensemble/breakdown?symbol=${symbol}&limit=10`;
            try {
                const r = await fetch(url, { signal: AbortSignal.timeout(6000) });
                if (r.ok) { const d = await r.json(); ensVotes = d.votes || d.signals || []; }
            } catch (_) {}
        }

        if (symbol) {
            // Trust score
            try {
                const r = await fetch(`http://${host}:8023/trust_score/${encodeURIComponent(symbol)}`, { signal: AbortSignal.timeout(6000) });
                if (r.ok) trustData = await r.json();
            } catch (_) {}

            // Regime
            try {
                const r = await fetch(`http://${host}:8015/regimes`, { signal: AbortSignal.timeout(6000) });
                if (r.ok) {
                    const d = await r.json();
                    regimeData = (d.regimes || []).find(r => r.symbol === symbol) || null;
                }
            } catch (_) {}

            // Price prediction
            try {
                const r = await fetch(`http://${host}:8011/predict?symbol=${encodeURIComponent(symbol)}&horizon=24`, { signal: AbortSignal.timeout(8000) });
                if (r.ok) predData = await r.json();
            } catch (_) {}

            // Walk-forward (from report API)
            try {
                const r = await fetch(`http://${host}:8023/walkforward/${encodeURIComponent(symbol)}`, { signal: AbortSignal.timeout(8000) });
                if (r.ok) wfData = await r.json();
            } catch (_) {}

            // Recent trades
            try {
                const r = await fetch(`http://${host}:8016/positions?symbol=${encodeURIComponent(symbol)}&status=closed&limit=5`, { signal: AbortSignal.timeout(6000) });
                if (r.ok) { const d = await r.json(); tradesData = d.positions || d; }
            } catch (_) {}
        }

        _renderDrilldown({ type, ensVotes, trustData, regimeData, predData, wfData, tradesData, symbol });
    } catch (e) {
        document.getElementById('dd-loading').innerHTML = `<div class="text-red-400 text-xs">${e.message}</div>`;
    }
}

function _renderDrilldown({ type, ensVotes, trustData, regimeData, predData, wfData, tradesData, symbol }) {
    document.getElementById('dd-loading').classList.add('hidden');
    const body = document.getElementById('dd-body');
    body.classList.remove('hidden');

    // ── Ensemble votes ──
    const ensSection = document.getElementById('dd-ensemble-section');
    const ensVotesEl = document.getElementById('dd-ensemble-votes');
    if (ensVotes.length && ensVotesEl) {
        ensSection.classList.remove('hidden');
        ensVotesEl.innerHTML = ensVotes.map(v => {
            const score = v.quality_score || v.score || 0;
            const col = score >= 80 ? 'bg-green-500' : score >= 60 ? 'bg-yellow-500' : 'bg-red-500';
            const name = v.strategy_name || v.symbol || `Signal #${v.id || '?'}`;
            const type_label = v.signal_type || v.side || 'BUY';
            return `<div class="flex items-center gap-2 text-xs">
                <div class="flex-1 truncate text-gray-300">${name}</div>
                <span class="text-gray-500">${type_label}</span>
                <div class="w-20 bg-gray-800 rounded-full h-1.5 overflow-hidden">
                    <div class="${col} h-full rounded-full" style="width:${Math.min(100,score)}%"></div>
                </div>
                <span class="text-gray-300 w-8 text-right font-mono">${score}</span>
            </div>`;
        }).join('');
    } else {
        ensSection.classList.add('hidden');
    }

    // ── Trust score ──
    const trustSection = document.getElementById('dd-trust-section');
    const trustBars = document.getElementById('dd-trust-bars');
    if (trustData && trustBars) {
        trustSection.classList.remove('hidden');
        const ts = trustData;
        const bars = [
            { label: 'Backtest PF',   val: Math.min(100, (ts.backtest_pf || 0) * 50),    raw: ts.backtest_pf },
            { label: 'Walk-Fwd PF',   val: Math.min(100, (ts.walkfwd_pf || 0) * 50),     raw: ts.walkfwd_pf },
            { label: 'Regime Align',  val: Math.round((ts.regime_alignment || 0) * 100),  raw: null },
            { label: 'Prediction Acc',val: Math.round((ts.prediction_accuracy || 0) * 100), raw: null },
            { label: 'Overall Trust', val: Math.round((ts.trust_score || 0) * 100),        raw: null },
        ];
        trustBars.innerHTML = bars.map(b => {
            const col = b.val >= 70 ? 'bg-green-500' : b.val >= 40 ? 'bg-yellow-500' : 'bg-red-500';
            const display = b.raw != null ? b.raw.toFixed(2) : `${b.val}%`;
            return `<div>
                <div class="flex justify-between text-xs mb-0.5">
                    <span class="text-gray-400">${b.label}</span>
                    <span class="font-semibold text-gray-200">${display}</span>
                </div>
                <div class="w-full bg-gray-800 rounded-full h-1.5 overflow-hidden">
                    <div class="${col} h-full rounded-full" style="width:${b.val}%"></div>
                </div>
            </div>`;
        }).join('');
    } else {
        trustSection.classList.add('hidden');
    }

    // ── Regime ──
    const regimeSection = document.getElementById('dd-regime-section');
    const regimeDetail = document.getElementById('dd-regime-detail');
    if (regimeData && regimeDetail) {
        regimeSection.classList.remove('hidden');
        const reg = (regimeData.regime || 'unknown').toLowerCase();
        const icon = reg.includes('bull') ? '🟢' : reg.includes('bear') ? '🔴' : '🟡';
        regimeDetail.innerHTML = `
            <div class="flex items-center gap-3">
                <span class="text-3xl">${icon}</span>
                <div>
                    <div class="font-bold capitalize text-gray-100">${reg}</div>
                    <div class="text-xs text-gray-400 mt-0.5">
                        Volatility: ${regimeData.volatility_regime || 'n/a'} · 
                        Trend: ${regimeData.trend_slope != null ? parseFloat(regimeData.trend_slope).toFixed(4) : 'n/a'}
                    </div>
                </div>
            </div>`;
    } else {
        regimeSection.classList.add('hidden');
    }

    // ── Prediction ──
    const predSection = document.getElementById('dd-prediction-section');
    const predDetail = document.getElementById('dd-prediction-detail');
    if (predData && predDetail) {
        predSection.classList.remove('hidden');
        const dir = predData.direction || (predData.predicted_change > 0 ? 'UP' : 'DOWN');
        const conf = predData.confidence || predData.accuracy_rate;
        const horizStr = predData.horizon_hours || '24h';
        const confStr = conf != null ? `${(parseFloat(conf)*100).toFixed(1)}% acc` : '';
        predDetail.innerHTML = `
            <div class="flex items-center gap-3">
                <span class="text-2xl">${dir === 'UP' ? '📈' : '📉'}</span>
                <div>
                    <div class="font-bold text-gray-100">${dir} over ${horizStr}h</div>
                    <div class="text-xs text-gray-400 mt-0.5">${confStr}
                        ${predData.true_count != null ? `· ${predData.true_count}/${(predData.true_count||0)+(predData.false_count||0)} correct` : ''}
                    </div>
                </div>
            </div>`;
    } else {
        predSection.classList.add('hidden');
    }

    // ── Walk-forward ──
    const wfSection = document.getElementById('dd-walkforward-section');
    const wfDetail = document.getElementById('dd-walkforward-detail');
    if (wfData && wfDetail) {
        wfSection.classList.remove('hidden');
        const folds = wfData.folds || wfData.windows || [];
        const avgPF = folds.length ? (folds.reduce((a, f) => a + (parseFloat(f.profit_factor || f.pf || 0)), 0) / folds.length) : (wfData.avg_profit_factor || 0);
        const avgWR = folds.length ? (folds.reduce((a, f) => a + (parseFloat(f.win_rate || 0)), 0) / folds.length) : (wfData.avg_win_rate || 0);
        wfDetail.innerHTML = `
            <div class="grid grid-cols-3 gap-3 text-xs text-center">
                <div><div class="text-gray-400">Folds</div><div class="font-bold text-gray-100 text-base">${folds.length || wfData.num_windows || 0}</div></div>
                <div><div class="text-gray-400">Avg PF</div><div class="font-bold text-${avgPF >= 1.2 ? 'green' : 'red'}-400 text-base">${avgPF.toFixed(2)}</div></div>
                <div><div class="text-gray-400">Avg Win</div><div class="font-bold text-gray-100 text-base">${(avgWR*100).toFixed(1)}%</div></div>
            </div>`;
    } else {
        wfSection.classList.add('hidden');
    }

    // ── Recent trades ──
    const trSection = document.getElementById('dd-trades-section');
    const trList = document.getElementById('dd-trades-list');
    if (tradesData.length && trList) {
        trSection.classList.remove('hidden');
        trList.innerHTML = tradesData.map(t => {
            const pnl = parseFloat(t.realized_pnl || 0);
            const col = pnl >= 0 ? 'text-green-400' : 'text-red-400';
            const ts = t.exit_time ? new Date(t.exit_time).toLocaleDateString() : '?';
            return `<div class="flex items-center justify-between text-xs py-1 border-b border-gray-800 last:border-0">
                <span class="text-gray-400">${ts}</span>
                <span class="text-gray-300">${t.strategy_name || 'unknown'}</span>
                <span class="${col} font-semibold">${pnl >= 0 ? '+' : ''}${pnl.toFixed(4)}</span>
            </div>`;
        }).join('');
    } else {
        trSection.classList.add('hidden');
    }
}

function closeDrilldown(event) {
    if (event && event.target !== event.currentTarget) return;
    document.getElementById('drilldown-modal')?.classList.remove('active');
}
window.closeDrilldown = closeDrilldown;

// ═══════════════════════════════════════════════════════════════════════════════
// SYMBOL ANALYSIS MODAL (chart + strategy overlay + prediction + walk-forward)
// ═══════════════════════════════════════════════════════════════════════════════

let _saSymbol = null;
let _saChart = null;

function openSymbolAnalysis(symbol) {
    _saSymbol = symbol;
    const modal = document.getElementById('symbol-analysis-modal');
    if (!modal) return;
    modal.classList.add('active');
    document.getElementById('sa-title').textContent = symbol;
    switchSaTab('chart');
    _loadSaStrategies(symbol);
    loadChartWithStrategy();
}
window.openSymbolAnalysis = openSymbolAnalysis;

function closeSymbolAnalysis(event) {
    if (event && event.target !== event.currentTarget) return;
    if (_saChart) { _saChart.destroy(); _saChart = null; }
    document.getElementById('symbol-analysis-modal')?.classList.remove('active');
}
window.closeSymbolAnalysis = closeSymbolAnalysis;

function switchSaTab(tab) {
    ['chart','predict','walkfwd','news'].forEach(t => {
        document.getElementById(`sa-pane-${t}`)?.classList.toggle('hidden', t !== tab);
        const btn = document.getElementById(`sa-tab-${t}`);
        if (btn) {
            btn.className = t === tab
                ? 'sa-tab sa-tab-active px-4 py-2 text-xs font-semibold'
                : 'sa-tab px-4 py-2 text-xs font-semibold text-gray-400 hover:text-white';
        }
    });
    if (tab === 'predict') _loadSaPrediction(_saSymbol);
    if (tab === 'walkfwd') _loadSaWalkforward(_saSymbol);
    if (tab === 'news') _loadSaNews(_saSymbol);
}
window.switchSaTab = switchSaTab;

async function _loadSaStrategies(symbol) {
    const host = window.API_HOST || window.location.hostname;
    const sel = document.getElementById('sa-strategy-select');
    if (!sel) return;
    try {
        const r = await fetch(`http://${host}:8023/trust_rankings?symbol=${encodeURIComponent(symbol)}&limit=20`, { signal: AbortSignal.timeout(6000) });
        if (!r.ok) return;
        const d = await r.json();
        const strategies = d.rankings || [];
        sel.innerHTML = `<option value="">None (price only)</option>` +
            strategies.map(s => `<option value="${s.strategy_id || s.strategy_name}">${s.strategy_name} (trust ${Math.round((s.trust_factor||0)*100)}%)</option>`).join('');
    } catch (_) {}
}

async function loadChartWithStrategy() {
    const host = window.API_HOST || window.location.hostname;
    const symbol = _saSymbol;
    const tf = document.getElementById('sa-timeframe-select')?.value || '15m';
    const stratId = document.getElementById('sa-strategy-select')?.value;
    const loading = document.getElementById('sa-chart-loading');
    const legend = document.getElementById('sa-signal-legend');
    if (loading) loading.style.display = 'flex';
    if (legend) legend.classList.add('hidden');

    try {
        // Fetch OHLCV data
        const r = await fetch(`http://${host}:8012/candles?symbol=${encodeURIComponent(symbol)}&timeframe=${tf}&limit=300`, { signal: AbortSignal.timeout(10000) });
        if (!r.ok) throw new Error(`OHLCV ${r.status}`);
        const d = await r.json();
        const candles = d.candles || d;

        // Optionally fetch signal scan
        let signals = [];
        if (stratId) {
            try {
                const sr = await fetch(`http://${host}:8015/signals/scan?symbol=${encodeURIComponent(symbol)}&strategy=${encodeURIComponent(stratId)}&timeframe=${tf}&limit=300`, { signal: AbortSignal.timeout(8000) });
                if (sr.ok) { const sd = await sr.json(); signals = sd.signals || []; }
            } catch (_) {}
        }

        console.log(`Chart loaded for ${symbol} tf=${tf}: ${candles.length} candles, ${signals.length} signals`);
        _renderSaChart(candles, signals, symbol, tf);
        if (loading) loading.style.display = 'none';
        if (legend && signals.length) {
            legend.classList.remove('hidden');
            const sc = document.getElementById('sa-signal-count');
            if (sc) sc.textContent = `${signals.length} signals found`;
        }
    } catch (e) {
        if (loading) { loading.style.display = 'flex'; loading.textContent = `Error: ${e.message}`; }
    }
}
window.loadChartWithStrategy = loadChartWithStrategy;

function _renderSaChart(candles, signals, symbol, tf) {
    const canvas = document.getElementById('sa-chart-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    const labels = candles.map(c => c.timestamp || c.time);
    const prices = candles.map(c => parseFloat(c.close || c.c || 0));

    // Signal overlay points
    const buyPoints = new Array(prices.length).fill(null);
    const sellPoints = new Array(prices.length).fill(null);
    signals.forEach(sig => {
        const idx = candles.findIndex(c => c.timestamp === sig.generated_at || c.time === sig.generated_at);
        const realIdx = idx >= 0 ? idx : candles.findIndex(c => Math.abs(new Date(c.timestamp||c.time) - new Date(sig.generated_at)) < 120000);
        if (realIdx >= 0) {
            const price = prices[realIdx];
            if ((sig.signal_type || '').toUpperCase() === 'BUY') buyPoints[realIdx] = price;
            else sellPoints[realIdx] = price;
        }
    });

    if (_saChart) _saChart.destroy();
    _saChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [
                {
                    label: `${symbol} Close`,
                    data: prices,
                    borderColor: '#3b82f6',
                    borderWidth: 1.5,
                    pointRadius: 0,
                    tension: 0.1,
                    fill: { target: 'origin', above: 'rgba(59,130,246,0.05)' }
                },
                {
                    label: 'Buy Signal',
                    data: buyPoints,
                    borderColor: 'transparent',
                    backgroundColor: '#10b981',
                    pointRadius: 6,
                    pointStyle: 'triangle',
                    showLine: false,
                },
                {
                    label: 'Sell Signal',
                    data: sellPoints,
                    borderColor: 'transparent',
                    backgroundColor: '#ef4444',
                    pointRadius: 6,
                    pointStyle: 'triangle',
                    rotation: 180,
                    showLine: false,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { display: false },
                tooltip: { callbacks: { label: (c) => `${c.dataset.label}: $${c.parsed.y?.toLocaleString(undefined,{maximumFractionDigits:4}) || ''}` } },
                zoom: { zoom: { wheel: { enabled: true }, pinch: { enabled: true }, mode: 'x' }, pan: { enabled: true, mode: 'x' } },
            },
            scales: {
                x: { ticks: { display: false }, grid: { color: 'rgba(255,255,255,0.04)' } },
                y: { ticks: { color: '#9ca3af', font: { size: 10 }, callback: v => '$' + v.toLocaleString(undefined, {maximumFractionDigits: 2}) }, grid: { color: 'rgba(255,255,255,0.06)' } },
            },
        },
    });
}

// Export current chart strategy to DB
async function exportCurrentChartStrategy() {
    const host = window.API_HOST || window.location.hostname;
    const symbol = _saSymbol;
    const stratId = document.getElementById('sa-strategy-select')?.value;
    const tf = document.getElementById('sa-timeframe-select')?.value || '15m';
    if (!symbol || !stratId) { showToast('Select a strategy to export', 'warning'); return; }

    try {
        const r = await fetch(`http://${host}:8023/import_charts_strategy`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symbol, strategy_id: stratId, timeframe: tf, source: 'chart_export' }),
            signal: AbortSignal.timeout(8000),
        });
        if (r.ok) {
            showToast(`Strategy exported for ${symbol} — refinement triggered`, 'success');
        } else {
            showToast(`Export failed: ${r.status}`, 'error');
        }
    } catch (e) {
        showToast(`Export error: ${e.message}`, 'error');
    }
}
window.exportCurrentChartStrategy = exportCurrentChartStrategy;

async function _loadSaPrediction(symbol) {
    const host = window.API_HOST || window.location.hostname;
    const el = document.getElementById('sa-prediction-content');
    if (!el || !symbol) return;
    try {
        const r = await fetch(`http://${host}:8011/predict?symbol=${encodeURIComponent(symbol)}&horizon=24`, { signal: AbortSignal.timeout(8000) });
        if (!r.ok) throw new Error(`${r.status}`);
        const d = await r.json();
        const dir = d.direction || (parseFloat(d.predicted_change||0) > 0 ? 'UP' : 'DOWN');
        const conf = d.confidence || d.accuracy_rate;
        const confStr = conf != null ? `${(parseFloat(conf)*100).toFixed(1)}%` : 'N/A';
        const trueCount = d.true_count || 0;
        const falseCount = d.false_count || 0;
        const total = trueCount + falseCount;
        el.innerHTML = `
            <div class="grid grid-cols-2 gap-4">
                <div class="bg-gray-900 rounded-xl p-4 text-center">
                    <div class="text-4xl mb-2">${dir === 'UP' ? '📈' : '📉'}</div>
                    <div class="text-lg font-bold text-gray-100">${dir}</div>
                    <div class="text-xs text-gray-400">next 24h</div>
                </div>
                <div class="bg-gray-900 rounded-xl p-4 text-center">
                    <div class="text-3xl font-bold text-${parseFloat(conf||0) >= 0.6 ? 'green' : 'yellow'}-400">${confStr}</div>
                    <div class="text-xs text-gray-400 mt-1">Historical accuracy</div>
                    ${total > 0 ? `<div class="text-xs text-gray-500 mt-1">${trueCount}/${total} correct</div>` : ''}
                </div>
            </div>
            ${d.predicted_price ? `<div class="mt-4 p-3 bg-gray-900 rounded-lg text-sm">
                <span class="text-gray-400">Predicted price:</span>
                <span class="text-gray-100 font-bold ml-2">$${parseFloat(d.predicted_price).toLocaleString(undefined,{maximumFractionDigits:4})}</span>
            </div>` : ''}`;
    } catch (e) {
        el.innerHTML = `<div class="text-center py-8 text-gray-500 text-sm">Prediction unavailable: ${e.message}</div>`;
    }
}

async function _loadSaWalkforward(symbol) {
    const host = window.API_HOST || window.location.hostname;
    const el = document.getElementById('sa-walkfwd-content');
    if (!el || !symbol) return;
    try {
        const r = await fetch(`http://${host}:8023/walkforward/${encodeURIComponent(symbol)}`, { signal: AbortSignal.timeout(8000) });
        if (!r.ok) throw new Error(`${r.status}`);
        const d = await r.json();
        const folds = d.folds || d.windows || [];
        const summary = d.summary || {};
        el.innerHTML = `
            <div class="grid grid-cols-4 gap-2 mb-4">
                ${[
                    ['Folds', folds.length || d.num_windows || 0, 'text-blue-400'],
                    ['Avg PF', parseFloat(summary.avg_profit_factor||d.avg_profit_factor||0).toFixed(2), parseFloat(summary.avg_profit_factor||d.avg_profit_factor||0) >= 1.2 ? 'text-green-400' : 'text-red-400'],
                    ['Avg Win', `${(parseFloat(summary.avg_win_rate||d.avg_win_rate||0)*100).toFixed(1)}%`, 'text-gray-100'],
                    ['Consistency', `${Math.round(parseFloat(summary.consistency||d.consistency||0)*100)}%`, 'text-yellow-400'],
                ].map(([label, val, col]) => `
                    <div class="bg-gray-900 rounded-lg p-3 text-center">
                        <div class="text-xs text-gray-400">${label}</div>
                        <div class="text-lg font-bold ${col}">${val}</div>
                    </div>`).join('')}
            </div>
            ${folds.length ? `
            <div class="overflow-x-auto">
                <table class="w-full text-xs">
                    <thead><tr class="text-gray-500 border-b border-gray-700">
                        <th class="text-left py-1">Period</th>
                        <th class="text-right py-1">PF</th>
                        <th class="text-right py-1">Win%</th>
                        <th class="text-right py-1">Trades</th>
                    </tr></thead>
                    <tbody>
                        ${folds.map(f => `<tr class="border-b border-gray-800">
                            <td class="text-gray-400 py-1">${f.period || f.name || '—'}</td>
                            <td class="text-right ${parseFloat(f.profit_factor||f.pf||0)>=1.2?'text-green-400':'text-red-400'}">${parseFloat(f.profit_factor||f.pf||0).toFixed(2)}</td>
                            <td class="text-right text-gray-300">${(parseFloat(f.win_rate||0)*100).toFixed(1)}%</td>
                            <td class="text-right text-gray-400">${f.trades||f.num_trades||0}</td>
                        </tr>`).join('')}
                    </tbody>
                </table>
            </div>` : ''}`;
    } catch (e) {
        el.innerHTML = `<div class="text-center py-8 text-gray-500 text-sm">Walk-forward data unavailable: ${e.message}</div>`;
    }
}

async function _loadSaNews(symbol) {
    const host = window.API_HOST || window.location.hostname;
    const el = document.getElementById('sa-news-content');
    if (!el || !symbol) return;
    try {
        const base = symbol.replace('/USD','').replace('-USD','');
        const r = await fetch(`http://${host}:8011/sentiment?symbol=${encodeURIComponent(base)}&limit=10`, { signal: AbortSignal.timeout(8000) });
        if (!r.ok) throw new Error(`${r.status}`);
        const d = await r.json();
        const items = d.articles || d.news || d.items || [];
        if (!items.length) { el.innerHTML = `<div class="text-center py-8 text-gray-500 text-sm">No news found</div>`; return; }
        el.innerHTML = items.map(n => {
            const sent = (n.sentiment || n.score || 0);
            const sentColor = sent > 0.1 ? 'text-green-400' : sent < -0.1 ? 'text-red-400' : 'text-gray-400';
            const sentIcon = sent > 0.1 ? '🐂' : sent < -0.1 ? '🐻' : '➡️';
            return `<div class="border-b border-gray-700 pb-3 mb-3 last:border-0 last:pb-0 last:mb-0">
                <div class="flex items-start gap-2">
                    <span class="text-base mt-0.5">${sentIcon}</span>
                    <div class="flex-1 min-w-0">
                        <div class="text-sm text-gray-200 font-medium line-clamp-2">${n.title || n.headline || 'No title'}</div>
                        <div class="flex items-center gap-2 mt-1">
                            <span class="${sentColor} text-xs">${typeof sent === 'number' ? (sent > 0 ? '+' : '') + sent.toFixed(2) : sent}</span>
                            <span class="text-xs text-gray-600">${n.source || n.publisher || ''}</span>
                            <span class="text-xs text-gray-600">${n.published_at ? new Date(n.published_at).toLocaleDateString() : ''}</span>
                        </div>
                    </div>
                </div>
            </div>`;
        }).join('');
    } catch (e) {
        el.innerHTML = `<div class="text-center py-8 text-gray-500 text-sm">News unavailable: ${e.message}</div>`;
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// SYMBOL CARD ENHANCEMENT — trust/regime/prediction badges
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * renderSymbolCardEnhancements(sym, container)
 * Called by the main symbol card renderer to inject pro-grade badges.
 */
async function renderSymbolCardEnhancements(symbol, container) {
    const host = window.API_HOST || window.location.hostname;
    const cached = window._realtimeSymbolData[symbol] || {};

    // ── Trust score badge ──
    const trustEl = container.querySelector(`#sym-trust-${symbol}`);
    if (trustEl) {
        try {
            if (!cached.trust) {
                const r = await fetch(`http://${host}:8023/trust_score/${encodeURIComponent(symbol)}`, { signal: AbortSignal.timeout(5000) });
                if (r.ok) { const d = await r.json(); cached.trust = d.trust_score; cached.wf_pf = d.walkfwd_pf; cached.backtest_pf = d.backtest_pf; }
            }
            if (cached.trust != null) {
                const pct = Math.round(cached.trust * 100);
                const col = pct >= 70 ? 'text-green-400' : pct >= 40 ? 'text-yellow-400' : 'text-red-400';
                trustEl.innerHTML = `<span class="${col} font-bold">${pct}%</span>`;
            }
        } catch (_) {}
    }

    // ── Regime badge ──
    const regEl = container.querySelector(`#sym-regime-${symbol}`);
    if (regEl) {
        try {
            if (!cached.regime) {
                const r = await fetch(`http://${host}:8015/regimes`, { signal: AbortSignal.timeout(5000) });
                if (r.ok) {
                    const d = await r.json();
                    const found = (d.regimes || []).find(r => r.symbol === symbol);
                    if (found) cached.regime = (found.regime || 'unknown').toLowerCase();
                }
            }
            if (cached.regime) {
                const icon = cached.regime.includes('bull') ? '🟢' : cached.regime.includes('bear') ? '🔴' : '🟡';
                regEl.innerHTML = `${icon} <span class="capitalize">${cached.regime}</span>`;
            }
        } catch (_) {}
    }

    // ── Walk-forward PF ──
    const wfEl = container.querySelector(`#sym-wf-${symbol}`);
    if (wfEl && cached.wf_pf != null) {
        const pf = parseFloat(cached.wf_pf);
        wfEl.innerHTML = `<span class="${pf >= 1.2 ? 'text-green-400' : 'text-red-400'}">WF ${pf.toFixed(2)}x</span>`;
    }

    window._realtimeSymbolData[symbol] = cached;
}
window.renderSymbolCardEnhancements = renderSymbolCardEnhancements;

// ─── Expose init ──────────────────────────────────────────────────────────────
window.initRealtimeConnection = initRealtimeConnection;
window.loadPortfolioHighlights = loadPortfolioHighlights;
