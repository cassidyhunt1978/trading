// pages/strategies.js — Strategies page

// ─── State variables ──────────────────────────────────────────────────────────
let allStrategies = [];
let currentStrategyFilter = 'all';
let currentStrategyId = null;
let strategyChart = null;
let backtestTrades = [];
let backtestDateRange = null;
let mostRecentBacktestId = null;

// ─── Load & Render ────────────────────────────────────────────────────────────
async function loadStrategies() {
    try {
        const response = await fetch(`http://${window.API_HOST}:8015/strategies`);
        const data = await response.json();
        allStrategies = data.strategies || [];
        renderStrategies();
    } catch (error) {
        console.error('Error loading strategies:', error);
    }
}

function renderStrategies() {
    const grid = document.getElementById('strategies-grid');
    let filtered = allStrategies;
    if (currentStrategyFilter === 'active') {
        filtered = allStrategies.filter(s => s.enabled);
    } else if (currentStrategyFilter === 'inactive') {
        filtered = allStrategies.filter(s => !s.enabled);
    }
    filtered.sort((a, b) => {
        if (!a.last_signal_at && !b.last_signal_at) return 0;
        if (!a.last_signal_at) return 1;
        if (!b.last_signal_at) return -1;
        return new Date(b.last_signal_at) - new Date(a.last_signal_at);
    });
    if (filtered.length === 0) {
        grid.innerHTML = `<div class="col-span-full text-center py-10 text-gray-400"><p class="text-lg">No ${currentStrategyFilter === 'all' ? '' : currentStrategyFilter + ' '}strategies found</p></div>`;
        return;
    }
    grid.innerHTML = filtered.map(s => {
        let orbColor = 'bg-gray-500';
        let orbPulse = '';
        if (s.enabled) {
            if (!s.signals_24h || s.signals_24h === 0) {
                orbColor = 'bg-yellow-500';
                orbPulse = 'health-pulse';
            } else {
                orbColor = 'bg-green-500';
            }
        } else {
            orbColor = 'bg-red-500';
            orbPulse = 'health-pulse';
        }
        let optIcon = '';
        if (s.last_optimized) {
            const daysSince = Math.floor((Date.now() - new Date(s.last_optimized).getTime()) / (1000 * 60 * 60 * 24));
            if (daysSince === 0) optIcon = '<span class="text-xs" title="Optimized today">✅</span>';
            else if (daysSince <= 3) optIcon = '<span class="text-xs" title="Optimized recently">🔄</span>';
            else if (daysSince <= 7) optIcon = '<span class="text-xs text-yellow-500" title="Optimization aging">⚡</span>';
            else optIcon = '<span class="text-xs text-orange-500" title="Needs optimization">⚠️</span>';
        } else {
            optIcon = '<span class="text-xs text-red-500" title="Never optimized">❗</span>';
        }
        const ensembleBadge = s.promoted_count > 0
            ? '<span class="text-lg" title="In Filtered Ensemble">🏅</span>'
            : '<span class="text-lg opacity-40" title="Not in Ensemble">🎗️</span>';
        let lastSignalDisplay = '';
        if (s.last_signal_at) {
            const signalTime = new Date(s.last_signal_at);
            const minutesAgo = Math.floor((Date.now() - signalTime.getTime()) / (1000 * 60));
            if (minutesAgo < 1) lastSignalDisplay = '<span class="text-green-400" title="Last signal: Just now">🟢 Now</span>';
            else if (minutesAgo < 60) lastSignalDisplay = `<span class="text-green-400" title="Last signal: ${minutesAgo}m ago">🟢 ${minutesAgo}m</span>`;
            else if (minutesAgo < 1440) { const hours = Math.floor(minutesAgo / 60); lastSignalDisplay = `<span class="text-yellow-400" title="Last signal: ${hours}h ago">🟡 ${hours}h</span>`; }
            else { const days = Math.floor(minutesAgo / 1440); lastSignalDisplay = `<span class="text-gray-500" title="Last signal: ${days}d ago">⚪ ${days}d</span>`; }
        } else {
            lastSignalDisplay = '<span class="text-gray-600" title="No signals yet">⚫ None</span>';
        }
        return `
        <div class="symbol-card p-4 ${s.enabled ? '' : 'opacity-60'}" data-strategy-id="${s.id}">
            <div class="flex justify-between items-start mb-3">
                <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-1.5 mb-1">
                        <h3 class="text-lg font-bold truncate">${s.name}</h3>
                        ${ensembleBadge}
                    </div>
                    <div class="flex items-center gap-2 text-xs text-gray-500">
                        <span>${s.created_by === 'AI' ? '🤖 AI' : '👤 Manual'}</span>
                        ${optIcon}
                    </div>
                </div>
                <div class="${orbColor} ${orbPulse} w-3 h-3 rounded-full flex-shrink-0"></div>
            </div>
            <div class="grid grid-cols-3 gap-2 text-sm mb-3">
                <div><div class="text-gray-400 text-xs">Signals</div><div class="font-bold text-blue-400">${s.signals_24h || 0}</div></div>
                <div><div class="text-gray-400 text-xs">Positions</div><div class="font-bold text-purple-400">${s.open_positions_count || 0}</div></div>
                <div><div class="text-gray-400 text-xs">Indicators</div><div class="font-bold">${getIndicatorsFromLogic(s.indicator_logic).length}</div></div>
            </div>
            <div class="bg-gray-900 rounded px-2 py-1.5 mb-3 text-xs">
                <span class="text-gray-400">Last signal: </span>${lastSignalDisplay}
            </div>
            <div class="flex justify-between items-center">
                <div class="flex gap-2">
                    <button onclick="viewStrategyDetails(${s.id})" class="text-2xl hover:scale-110 transition-transform" title="View chart & details">📊</button>
                    <button onclick="toggleStrategy(${s.id}, event)" class="text-2xl hover:scale-110 transition-transform ${s.enabled ? 'text-yellow-400' : 'text-green-400'}" title="${s.enabled ? 'Pause' : 'Activate'} strategy">${s.enabled ? '⏸️' : '▶️'}</button>
                </div>
                <button onclick="deleteStrategy(${s.id})" class="text-red-400 hover:text-red-300 text-xl" title="Delete strategy">🗑️</button>
            </div>
        </div>`;
    }).join('');
}

function getIndicatorsFromLogic(logic) {
    const indicators = new Set();
    if (logic && logic.buy_conditions) logic.buy_conditions.forEach(c => indicators.add(c.indicator));
    if (logic && logic.sell_conditions) logic.sell_conditions.forEach(c => indicators.add(c.indicator));
    return Array.from(indicators);
}

function filterStrategies(filter) {
    currentStrategyFilter = filter;
    document.getElementById('filter-all-strategies').className =
        filter === 'all' ? 'px-4 py-2 rounded bg-blue-600 hover:bg-blue-700' : 'px-4 py-2 rounded bg-gray-700 hover:bg-gray-600';
    document.getElementById('filter-active-strategies').className =
        filter === 'active' ? 'px-4 py-2 rounded bg-blue-600 hover:bg-blue-700' : 'px-4 py-2 rounded bg-gray-700 hover:bg-gray-600';
    document.getElementById('filter-inactive-strategies').className =
        filter === 'inactive' ? 'px-4 py-2 rounded bg-blue-600 hover:bg-blue-700' : 'px-4 py-2 rounded bg-gray-700 hover:bg-gray-600';
    renderStrategies();
}

// ─── Performance Section ──────────────────────────────────────────────────────
async function loadStrategyPerformance() {
    // Guard: performance section may not be present on this page
    const symbolFilter = document.getElementById('perf-symbol-filter');
    if (!symbolFilter) return;
    const periodFilter = document.getElementById('perf-period-filter');
    if (!periodFilter) return;

    try {
        const symbol = symbolFilter.value;
        const periodDays = periodFilter.value;
        let url = `http://${window.API_HOST}:8020/performance?period_days=${periodDays}&limit=20&min_trades=0`;
        if (symbol) url += `&symbol=${symbol}`;
        const response = await fetch(url);
        const data = await response.json();
        if (data.status === 'success') {
            const totalEl = document.getElementById('perf-total-strategies');
            const winEl = document.getElementById('perf-avg-winrate');
            const tradesEl = document.getElementById('perf-total-trades');
            const bestEl = document.getElementById('perf-best-strategy');
            if (totalEl) totalEl.textContent = data.summary.total_strategies;
            if (winEl) winEl.textContent = `${data.summary.avg_win_rate}%`;
            if (tradesEl) tradesEl.textContent = data.summary.total_trades;
            if (bestEl) bestEl.textContent = data.summary.top_strategy || '-';
            const cardsGrid = document.getElementById('performance-cards-grid');
            if (cardsGrid) {
                if (data.performances.length === 0) {
                    cardsGrid.innerHTML = `<div class="col-span-full symbol-card p-6 text-center text-gray-500">No performance data yet.</div>`;
                    return;
                }
                cardsGrid.innerHTML = data.performances.map((perf, index) => {
                    const winRateColor = perf.win_rate >= 60 ? 'text-green-400' : perf.win_rate >= 50 ? 'text-yellow-400' : 'text-red-400';
                    const pnlColor = perf.total_pnl >= 0 ? 'text-green-400' : 'text-red-400';
                    const medal = index === 0 ? '🥇' : index === 1 ? '🥈' : index === 2 ? '🥉' : '';
                    const rank = medal || `#${index + 1}`;
                    return `<div class="symbol-card p-4 relative"><div class="absolute top-2 right-2 text-2xl">${rank}</div><h4 class="font-bold">${perf.strategy_name}</h4><div class="text-sm text-gray-400">${perf.symbol}</div><div class="${winRateColor} font-bold text-2xl">${perf.win_rate !== null ? perf.win_rate.toFixed(1) + '%' : 'N/A'}</div><div class="text-xs text-gray-500">${perf.total_trades} trades</div></div>`;
                }).join('');
            }
        }
    } catch (error) {
        console.error('Error loading strategy performance:', error);
    }
}

async function populatePerformanceSymbolFilter() {
    const select = document.getElementById('perf-symbol-filter');
    if (!select) return;
    try {
        const response = await fetch(`http://${window.API_HOST}:8012/symbols`);
        const data = await response.json();
        const symbols = data.symbols || [];
        const currentValue = select.value;
        select.innerHTML = '<option value="">All Symbols</option>' + symbols.map(s => `<option value="${s.symbol}">${s.symbol}</option>`).join('');
        if (currentValue && symbols.find(s => s.symbol === currentValue)) select.value = currentValue;
    } catch (error) {
        console.error('Error loading symbols for filter:', error);
    }
}

// ─── Create Strategy ──────────────────────────────────────────────────────────
function showCreateStrategy() {
    document.getElementById('create-strategy-modal').classList.add('active');
    updateParameterFields();
}

function closeCreateStrategy() {
    document.getElementById('create-strategy-modal').classList.remove('active');
    document.getElementById('strategy-form').reset();
}

function updateParameterFields() {
    const buyIndicator = document.getElementById('buy-indicator').value;
    const sellIndicator = document.getElementById('sell-indicator').value;
    const paramFields = document.getElementById('parameter-fields');
    let fieldsHtml = '<div class="grid grid-cols-2 gap-3">';
    const indicators = new Set([buyIndicator.split('_')[0], sellIndicator.split('_')[0]]);
    if (indicators.has('RSI')) {
        fieldsHtml += `
            <div><label class="block text-xs text-gray-400 mb-1">RSI Period</label><input type="number" id="param-rsi_period" value="14" min="7" max="30" class="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-sm"></div>
            <div><label class="block text-xs text-gray-400 mb-1">RSI Oversold</label><input type="number" id="param-rsi_oversold" value="30" min="10" max="40" class="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-sm"></div>
            <div><label class="block text-xs text-gray-400 mb-1">RSI Overbought</label><input type="number" id="param-rsi_overbought" value="70" min="60" max="90" class="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-sm"></div>`;
    }
    if (indicators.has('MACD')) {
        fieldsHtml += `
            <div><label class="block text-xs text-gray-400 mb-1">MACD Fast</label><input type="number" id="param-macd_fast" value="12" min="8" max="20" class="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-sm"></div>
            <div><label class="block text-xs text-gray-400 mb-1">MACD Slow</label><input type="number" id="param-macd_slow" value="26" min="20" max="40" class="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-sm"></div>
            <div><label class="block text-xs text-gray-400 mb-1">MACD Signal</label><input type="number" id="param-macd_signal" value="9" min="6" max="15" class="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-sm"></div>`;
    }
    if (indicators.has('SMA')) {
        fieldsHtml += `<div><label class="block text-xs text-gray-400 mb-1">SMA Period</label><input type="number" id="param-sma_period" value="20" min="10" max="50" class="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-sm"></div>`;
    }
    fieldsHtml += '</div>';
    paramFields.innerHTML = fieldsHtml;
}

// ─── Toggle & Delete ──────────────────────────────────────────────────────────
async function toggleStrategy(id, event) {
    if (event) event.stopPropagation();
    try {
        const response = await fetch(`http://${window.API_HOST}:8015/strategies/${id}/toggle`, { method: 'PUT' });
        const data = await response.json();
        if (data.status === 'success') {
            const strategy = allStrategies.find(s => s.id === id);
            const newState = !strategy.enabled;
            showToast(`Strategy ${newState ? 'activated' : 'paused'}`, 'success');
            loadStrategies();
        }
    } catch (error) {
        console.error('Error toggling strategy:', error);
        showToast('Failed to toggle strategy', 'error');
    }
}

async function deleteStrategy(id) {
    if (!confirm('Delete this strategy? This will also delete associated signals.')) return;
    try {
        const response = await fetch(`http://${window.API_HOST}:8015/strategies/${id}`, { method: 'DELETE' });
        const data = await response.json();
        if (data.status === 'success') loadStrategies();
    } catch (error) {
        console.error('Error deleting strategy:', error);
    }
}

// ─── Strategy Detail Modal ────────────────────────────────────────────────────
async function viewStrategyDetails(strategyId) {
    const strategy = allStrategies.find(s => s.id === strategyId);
    if (!strategy) return;
    currentStrategyId = strategyId;
    backtestTrades = [];
    backtestDateRange = null;
    mostRecentBacktestId = null;
    document.getElementById('strategy-details-modal').classList.add('active');
    document.getElementById('strategy-detail-name').textContent = strategy.name;
    await populateStrategySymbolDropdown();
    const dropdown = document.getElementById('strategy-detail-symbol');
    dropdown.value = dropdown.options[0]?.value || 'BTC';
    const symbol = dropdown.value;
    loadRecentBacktest(strategyId, symbol).then(() => {
        loadStrategyPerformanceChart();
    });
}

function closeStrategyDetails() {
    document.getElementById('strategy-details-modal').classList.remove('active');
    const resetBtn = document.getElementById('reset-zoom-btn');
    if (resetBtn) resetBtn.classList.add('hidden');
    if (strategyChart) {
        strategyChart.destroy();
        strategyChart = null;
    }
    currentStrategyId = null;
}

async function populateStrategySymbolDropdown() {
    try {
        const response = await fetch(`http://${window.API_HOST}:8012/symbols`);
        const data = await response.json();
        const symbols = data.symbols || [];
        const dropdown = document.getElementById('strategy-detail-symbol');
        dropdown.innerHTML = symbols.map(s => `<option value="${s.symbol}">${s.name} (${s.symbol})</option>`).join('');
    } catch (error) {
        document.getElementById('strategy-detail-symbol').innerHTML =
            '<option value="BTC">Bitcoin (BTC)</option><option value="ETH">Ethereum (ETH)</option>';
    }
}

async function loadRecentBacktest(strategyId, symbol) {
    try {
        const response = await fetch(`http://${window.API_HOST}:8013/results?strategy_id=${strategyId}&symbol=${symbol}&limit=1`);
        const data = await response.json();
        if (data.results && data.results.length > 0) {
            const backtest = data.results[0];
            mostRecentBacktestId = backtest.id;
            backtestTrades = backtest.trades || [];
            backtestDateRange = { start_date: backtest.start_date, end_date: backtest.end_date };
            const metricsEl = document.getElementById('backtest-metrics');
            if (metricsEl) {
                metricsEl.classList.remove('hidden');
                document.getElementById('bt-winrate').textContent = backtest.win_rate + '%';
                document.getElementById('bt-trades').textContent = backtest.total_trades;
                const btReturn = document.getElementById('bt-return');
                btReturn.textContent = backtest.total_return_pct + '%';
                btReturn.className = backtest.total_return_pct >= 0 ? 'font-bold text-green-400' : 'font-bold text-red-400';
                document.getElementById('bt-drawdown').textContent = backtest.max_drawdown_pct + '%';
                const btPnl = backtest.ending_capital - backtest.starting_capital;
                const pnlEl = document.getElementById('backtest-pnl');
                if (pnlEl) pnlEl.innerHTML = `<span class="${btPnl >= 0 ? 'text-green-400' : 'text-red-400'}">$${btPnl.toFixed(2)}</span>`;
            }
            return true;
        } else {
            const metricsEl = document.getElementById('backtest-metrics');
            if (metricsEl) metricsEl.classList.add('hidden');
            backtestTrades = [];
            backtestDateRange = null;
            mostRecentBacktestId = null;
            return false;
        }
    } catch (error) {
        console.error('[Backtest] Error loading recent backtest:', error);
        return false;
    }
}

async function onSymbolChange() {
    if (!currentStrategyId) return;
    await loadRecentBacktest(currentStrategyId, document.getElementById('strategy-detail-symbol').value);
    loadStrategyPerformanceChart();
}

function viewSignalDetails(signalId) {
    showToast(`Signal #${signalId} details coming soon.`, 'info');
}

async function loadStrategySignals(strategyId) {
    const container = document.getElementById('strategy-signals');
    if (!container) return;
    container.innerHTML = '<div class="text-center text-gray-400">Loading...</div>';
    const symbol = document.getElementById('strategy-detail-symbol').value;
    try {
        const response = await fetch(`http://${window.API_HOST}:8015/signals/recent?strategy_id=${strategyId}&hours=24&min_quality=0`);
        const signals = await response.json();
        if (!signals || signals.length === 0) {
            container.innerHTML = '<div class="text-center text-gray-400">No recent signals (24h)</div>';
            return;
        }
        const strategySignals = signals.filter(sig => sig.symbol === symbol);
        if (strategySignals.length === 0) {
            container.innerHTML = `<div class="text-center text-gray-400">No signals for ${symbol} yet</div>`;
            return;
        }
        container.innerHTML = `<div class="space-y-2">${strategySignals.slice(0, 10).map(sig => {
            const isExpired = new Date(sig.expires_at) < new Date();
            return `<div onclick="jumpToSignal(${sig.id})" class="flex justify-between items-center p-2 bg-gray-700 rounded cursor-pointer hover:bg-gray-600 ${isExpired ? 'opacity-60' : ''}">
                <div><div class="font-semibold">${sig.symbol}</div><div class="text-xs text-gray-400">${new Date(sig.generated_at).toLocaleString()}</div></div>
                <div class="text-right"><div class="font-semibold ${sig.signal_type === 'BUY' ? 'text-green-400' : 'text-red-400'}">${sig.signal_type}</div><div class="text-xs text-gray-400">Q: ${sig.quality_score}%</div></div>
            </div>`;
        }).join('')}</div>`;
    } catch (error) {
        container.innerHTML = '<div class="text-center text-red-400">Failed to load signals</div>';
    }
}

async function loadStrategyPerformanceChart() {
    if (!currentStrategyId) return;
    const symbol = document.getElementById('strategy-detail-symbol').value;
    const chartCanvas = document.getElementById('strategy-chart');
    const loadingDiv = document.getElementById('chart-loading');
    loadingDiv.style.display = 'block';
    chartCanvas.style.display = 'none';
    try {
        const MAX_DAYS = 14;
        let candlesUrl;
        if (backtestTrades.length > 0 && backtestDateRange) {
            const endDate = backtestDateRange.end_date.split('T')[0];
            const tomorrow = new Date();
            tomorrow.setDate(tomorrow.getDate() + 1);
            const extendedEndDate = tomorrow.toISOString().split('T')[0];
            const startDateObj = new Date(endDate);
            startDateObj.setDate(startDateObj.getDate() - MAX_DAYS);
            const startDate = startDateObj.toISOString().split('T')[0];
            candlesUrl = `http://${window.API_HOST}:8012/candles?symbol=${symbol}&start_date=${startDate}&end_date=${extendedEndDate}`;
        } else {
            candlesUrl = `http://${window.API_HOST}:8012/candles?symbol=${symbol}&days_back=7&limit=10000`;
        }
        const ohlcvResponse = await fetch(candlesUrl);
        if (!ohlcvResponse.ok) {
            loadingDiv.textContent = `Error loading candles: ${ohlcvResponse.statusText}`;
            return;
        }
        const candles = await ohlcvResponse.json();
        if (!candles || !Array.isArray(candles) || candles.length === 0) {
            loadingDiv.textContent = 'No price data available';
            return;
        }
        const signalsResponse = await fetch(`http://${window.API_HOST}:8015/signals/recent?strategy_id=${currentStrategyId}&hours=48&min_quality=0`);
        const paperSignals = await signalsResponse.json();
        const [paperPosResponse, livePosResponse] = await Promise.all([
            fetch(`http://${window.API_HOST}:8016/positions?mode=paper`),
            fetch(`http://${window.API_HOST}:8016/positions?mode=live`)
        ]);
        const paperPosData = await paperPosResponse.json();
        const livePosData = await livePosResponse.json();
        const paperTrades = paperPosData.positions ? paperPosData.positions.filter(p => p.strategy_id === currentStrategyId && p.symbol === symbol) : [];
        const liveTrades = livePosData.positions ? livePosData.positions.filter(p => p.strategy_id === currentStrategyId && p.symbol === symbol) : [];
        const calculatePnL = (positions) => positions.filter(p => p.realized_pnl).reduce((sum, p) => sum + parseFloat(p.realized_pnl), 0);
        const paperPnL = calculatePnL(paperTrades);
        const livePnL = calculatePnL(liveTrades);
        const paperPnlEl = document.getElementById('paper-pnl');
        const livePnlEl = document.getElementById('live-pnl');
        if (paperPnlEl) paperPnlEl.innerHTML = `<span class="${paperPnL >= 0 ? 'text-green-400' : 'text-red-400'}">$${paperPnL.toFixed(2)}</span>`;
        if (livePnlEl) livePnlEl.innerHTML = `<span class="${livePnL >= 0 ? 'text-green-400' : 'text-red-400'}">$${livePnL.toFixed(2)}</span>`;
        const MATCH_WINDOW_MS = 5 * 60 * 1000;
        const allSignals = [
            ...backtestTrades.map(t => ({ time: new Date(t.entry_time).getTime(), type: t.side.toUpperCase(), price: t.entry_price, source: 'backtest', data: t })),
            ...paperSignals.filter(s => s.symbol === symbol).map(s => ({ time: new Date(s.generated_at).getTime(), type: s.signal_type, price: s.price_at_signal, source: 'paper', data: s })),
            ...liveTrades.map(p => ({ time: new Date(p.entry_time).getTime(), type: p.side.toUpperCase(), price: p.entry_price, source: 'live', data: p }))
        ].sort((a, b) => a.time - b.time);
        const signalGroups = [];
        allSignals.forEach(signal => {
            let group = signalGroups.find(g => Math.abs(g.baseTime - signal.time) <= MATCH_WINDOW_MS && g.type === signal.type);
            if (!group) {
                group = { baseTime: signal.time, type: signal.type, backtest: null, paper: null, live: null };
                signalGroups.push(group);
            }
            group[signal.source] = signal;
        });
        const perfectMatches = signalGroups.filter(g => g.backtest && g.paper && g.live).length;
        const backtestPaperMatch = signalGroups.filter(g => g.backtest && g.paper && !g.live).length;
        const liveOnly = signalGroups.filter(g => !g.backtest && !g.paper && g.live).length;
        const backtestOnly = signalGroups.filter(g => g.backtest && !g.paper && !g.live).length;
        const paperOnly = signalGroups.filter(g => !g.backtest && g.paper && !g.live).length;
        const alertBanner = document.getElementById('signal-alert-banner');
        if (alertBanner) {
            if (liveOnly > 0) {
                alertBanner.className = 'bg-red-900 border-2 border-red-500 rounded-lg p-4 mb-4';
                alertBanner.innerHTML = `<div class="flex items-center gap-3"><div class="text-3xl">🚨</div><div><div class="font-bold text-red-400">LIVE DIVERGENCE ALERT</div><div class="text-sm text-red-300">${liveOnly} live signal(s) without validation</div></div></div>`;
            } else if (perfectMatches > 0 || backtestPaperMatch > 0) {
                alertBanner.className = 'bg-green-900 border-2 border-green-500 rounded-lg p-4 mb-4';
                alertBanner.innerHTML = `<div class="flex items-center gap-3"><div class="text-3xl">✅</div><div><div class="font-bold text-green-400">Perfect Alignment</div><div class="text-sm text-green-300">${perfectMatches} perfect matches</div></div></div>`;
            } else { alertBanner.className = 'hidden'; }
        }
        const compTable = document.getElementById('signal-comparison-table');
        if (compTable) {
            if (signalGroups.length === 0) {
                compTable.innerHTML = '<div class="text-center text-gray-400 py-4">No signals to compare</div>';
            } else {
                const alignRate = Math.round(((perfectMatches + backtestPaperMatch) / signalGroups.length) * 100);
                compTable.innerHTML = `<div class="mb-2 text-xs text-gray-400">${alignRate}% alignment | ${perfectMatches} perfect | ${backtestPaperMatch} validated | ${liveOnly} risk</div>
                <table class="w-full text-xs"><thead><tr class="border-b border-gray-700 text-gray-400"><th class="text-left py-1 px-2">Time</th><th class="text-left py-1 px-1">BT</th><th class="text-left py-1 px-1">Paper</th><th class="text-left py-1 px-1">Live</th><th class="text-left py-1 px-2">Status</th></tr></thead>
                <tbody>${signalGroups.map(g => {
                    let status, statusColor;
                    if (g.backtest && g.paper && g.live) { status = '✅ Perfect'; statusColor = 'text-green-400'; }
                    else if (g.backtest && g.paper) { status = '🟢 Validated'; statusColor = 'text-blue-400'; }
                    else if (g.live && !g.backtest && !g.paper) { status = '🚨 LIVE RISK'; statusColor = 'text-red-400 font-bold'; }
                    else if (g.backtest && !g.paper) { status = '⚠️ Not triggered'; statusColor = 'text-purple-400'; }
                    else if (g.paper && !g.backtest) { status = '🔍 Paper-only'; statusColor = 'text-cyan-400'; }
                    else { status = '❓'; statusColor = 'text-gray-400'; }
                    return `<tr class="border-b border-gray-800 hover:bg-gray-700 cursor-pointer" onclick="jumpToTimestamp(${g.baseTime})">
                        <td class="py-1 px-2">${new Date(g.baseTime).toLocaleString('en-US',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'})}</td>
                        <td class="py-1 px-1">${g.backtest ? `<span class="text-purple-400">${g.type}</span>` : '<span class="text-gray-600">-</span>'}</td>
                        <td class="py-1 px-1">${g.paper ? `<span class="text-blue-400">${g.type}</span>` : '<span class="text-gray-600">-</span>'}</td>
                        <td class="py-1 px-1">${g.live ? `<span class="text-red-400">${g.type}</span>` : '<span class="text-gray-600">-</span>'}</td>
                        <td class="py-1 px-2 ${statusColor}">${status}</td>
                    </tr>`;
                }).join('')}</tbody></table>`;
            }
        }
        const labels = candles.map(c => new Date(c.timestamp).toLocaleTimeString());
        const prices = candles.map(c => parseFloat(c.close));
        const minPrice = Math.min(...prices);
        const maxPrice = Math.max(...prices);
        const signalOffset = (maxPrice - minPrice) * 0.0625;
        const goldBuy=new Array(candles.length).fill(null), goldSell=new Array(candles.length).fill(null);
        const greenBuy=new Array(candles.length).fill(null), greenSell=new Array(candles.length).fill(null);
        const purpleBuy=new Array(candles.length).fill(null), purpleSell=new Array(candles.length).fill(null);
        const blueBuy=new Array(candles.length).fill(null), blueSell=new Array(candles.length).fill(null);
        const redBuy=new Array(candles.length).fill(null), redSell=new Array(candles.length).fill(null);
        signalGroups.forEach(group => {
            let closestIdx = 0, minDiff = Math.abs(new Date(candles[0].timestamp).getTime() - group.baseTime);
            candles.forEach((c, idx) => { const diff = Math.abs(new Date(c.timestamp).getTime() - group.baseTime); if (diff < minDiff) { minDiff = diff; closestIdx = idx; } });
            const isBuy = group.type === 'BUY';
            const position = isBuy ? prices[closestIdx] - signalOffset : prices[closestIdx] + signalOffset;
            let arr;
            if (group.backtest && group.paper && group.live) arr = isBuy ? goldBuy : goldSell;
            else if (group.backtest && group.paper) arr = isBuy ? greenBuy : greenSell;
            else if (group.backtest && !group.paper && !group.live) arr = isBuy ? purpleBuy : purpleSell;
            else if (!group.backtest && group.paper && !group.live) arr = isBuy ? blueBuy : blueSell;
            else if (!group.backtest && !group.paper && group.live) arr = isBuy ? redBuy : redSell;
            if (arr) arr[closestIdx] = position;
        });
        const signalIndexMap = {};
        paperSignals.filter(s => s.symbol === symbol).forEach(sig => {
            const sigTime = new Date(sig.generated_at).getTime();
            let closestIdx = 0, minDiff = Math.abs(new Date(candles[0].timestamp).getTime() - sigTime);
            candles.forEach((c, idx) => { const diff = Math.abs(new Date(c.timestamp).getTime() - sigTime); if (diff < minDiff) { minDiff = diff; closestIdx = idx; } });
            signalIndexMap[sig.id] = closestIdx;
        });
        window.currentSignalIndexMap = signalIndexMap;
        window.currentChartCandles = candles;
        if (strategyChart) { strategyChart.destroy(); }
        loadingDiv.style.display = 'none';
        chartCanvas.style.display = 'block';
        const ctx = chartCanvas.getContext('2d');
        strategyChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels,
                datasets: [
                    { label: 'Price', data: prices, borderColor: 'rgb(59,130,246)', backgroundColor: 'rgba(59,130,246,0.1)', tension: 0.1, pointRadius: 0, borderWidth: 2, order: 2 },
                    { label: '🟡 Perfect ▲', data: goldBuy, backgroundColor: 'rgb(250,204,21)', borderColor: 'rgb(234,179,8)', pointStyle: 'triangle', pointRadius: 18, pointHoverRadius: 22, borderWidth: 4, showLine: false, order: 0 },
                    { label: '🟡 Perfect ▼', data: goldSell, backgroundColor: 'rgb(250,204,21)', borderColor: 'rgb(234,179,8)', pointStyle: 'triangle', pointRotation: 180, pointRadius: 18, pointHoverRadius: 22, borderWidth: 4, showLine: false, order: 0 },
                    { label: '🟢 Validated ▲', data: greenBuy, backgroundColor: 'rgb(34,197,94)', borderColor: 'rgb(22,163,74)', pointStyle: 'triangle', pointRadius: 15, pointHoverRadius: 18, borderWidth: 3, showLine: false, order: 1 },
                    { label: '🟢 Validated ▼', data: greenSell, backgroundColor: 'rgb(34,197,94)', borderColor: 'rgb(22,163,74)', pointStyle: 'triangle', pointRotation: 180, pointRadius: 15, pointHoverRadius: 18, borderWidth: 3, showLine: false, order: 1 },
                    { label: '🟣 BT-only ▲', data: purpleBuy, backgroundColor: 'rgb(168,85,247)', borderColor: 'rgb(147,51,234)', pointStyle: 'triangle', pointRadius: 12, pointHoverRadius: 15, borderWidth: 2, showLine: false, order: 1 },
                    { label: '🟣 BT-only ▼', data: purpleSell, backgroundColor: 'rgb(168,85,247)', borderColor: 'rgb(147,51,234)', pointStyle: 'triangle', pointRotation: 180, pointRadius: 12, pointHoverRadius: 15, borderWidth: 2, showLine: false, order: 1 },
                    { label: '🔵 Paper ▲', data: blueBuy, backgroundColor: 'rgb(59,130,246)', borderColor: 'rgb(37,99,235)', pointStyle: 'triangle', pointRadius: 12, pointHoverRadius: 15, borderWidth: 2, showLine: false, order: 1 },
                    { label: '🔵 Paper ▼', data: blueSell, backgroundColor: 'rgb(59,130,246)', borderColor: 'rgb(37,99,235)', pointStyle: 'triangle', pointRotation: 180, pointRadius: 12, pointHoverRadius: 15, borderWidth: 2, showLine: false, order: 1 },
                    { label: '🔴 LIVE ▲', data: redBuy, backgroundColor: 'rgb(239,68,68)', borderColor: 'rgb(220,38,38)', pointStyle: 'triangle', pointRadius: 18, pointHoverRadius: 22, borderWidth: 4, showLine: false, order: 0 },
                    { label: '🔴 LIVE ▼', data: redSell, backgroundColor: 'rgb(239,68,68)', borderColor: 'rgb(220,38,38)', pointStyle: 'triangle', pointRotation: 180, pointRadius: 18, pointHoverRadius: 22, borderWidth: 4, showLine: false, order: 0 }
                ]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                interaction: { intersect: false, mode: 'index' },
                plugins: {
                    legend: { display: true, position: 'top', align: 'start', labels: { color: 'rgb(156,163,175)', usePointStyle: true, font: { size: 10 }, filter: item => !item.text.includes('Price') } },
                    tooltip: { backgroundColor: 'rgba(31,41,55,0.9)', titleColor: 'rgb(229,231,235)', bodyColor: 'rgb(229,231,235)', borderColor: 'rgb(75,85,99)', borderWidth: 1 },
                    zoom: { pan: { enabled: true, mode: 'x', modifierKey: null }, zoom: { wheel: { enabled: false }, pinch: { enabled: false }, mode: 'x' }, limits: { x: { min: 0, max: labels.length - 1 } } }
                },
                scales: {
                    x: { type: 'category', min: Math.max(0, labels.length - 90), max: labels.length - 1, ticks: { color: 'rgb(156,163,175)', maxTicksLimit: 12 }, grid: { color: 'rgba(75,85,99,0.3)' } },
                    y: { ticks: { color: 'rgb(156,163,175)' }, grid: { color: 'rgba(75,85,99,0.3)' }, beginAtZero: false }
                }
            }
        });
        chartCanvas.addEventListener('mousemove', (e) => {
            const rect = chartCanvas.getBoundingClientRect();
            strategyChart.crosshair = { x: e.clientX - rect.left, y: e.clientY - rect.top };
            strategyChart.update('none');
        });
        chartCanvas.addEventListener('mouseout', () => { strategyChart.crosshair = null; strategyChart.update('none'); });
        const resetBtn = document.getElementById('reset-zoom-btn');
        if (resetBtn) resetBtn.classList.remove('hidden');
    } catch (error) {
        console.error('Error loading chart:', error);
        loadingDiv.textContent = 'Failed to load chart data';
        loadingDiv.style.display = 'block';
    }
}

function resetChartZoom() {
    if (strategyChart && window.currentChartCandles) {
        const total = window.currentChartCandles.length;
        strategyChart.zoomScale('x', { min: Math.max(0, total - 90), max: total - 1 }, 'default');
    }
}

function jumpToSignal(signalId) {
    if (!strategyChart || !window.currentSignalIndexMap || !window.currentChartCandles) return;
    const signalIdx = window.currentSignalIndexMap[signalId];
    if (signalIdx === undefined) return;
    const total = window.currentChartCandles.length;
    const min = Math.max(0, signalIdx - 45);
    const max = Math.min(total - 1, signalIdx + 45);
    strategyChart.zoomScale('x', { min, max }, 'default');
    showToast('Jumped to signal on chart', 'success');
}

function jumpToTimestamp(timestamp) {
    if (!strategyChart || !window.currentChartCandles) return;
    const candles = window.currentChartCandles;
    let closestIdx = 0, minDiff = Math.abs(new Date(candles[0].timestamp).getTime() - timestamp);
    candles.forEach((c, idx) => { const diff = Math.abs(new Date(c.timestamp).getTime() - timestamp); if (diff < minDiff) { minDiff = diff; closestIdx = idx; } });
    const total = candles.length;
    const min = Math.max(0, closestIdx - 45);
    const max = Math.min(total - 1, closestIdx + 45);
    strategyChart.zoomScale('x', { min, max }, 'default');
    showToast('Jumped to signal on chart', 'success');
}

async function runBacktest() {
    if (!currentStrategyId) return;
    const symbol = document.getElementById('strategy-detail-symbol').value;
    showToast('Running backtest...', 'info');
    try {
        const response = await fetch(`http://${window.API_HOST}:8013/run`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ strategy_id: currentStrategyId, symbol, start_date: new Date(Date.now() - 30*86400000).toISOString().split('T')[0], end_date: new Date().toISOString().split('T')[0], initial_capital: 1000.0, position_size_pct: 100.0 })
        });
        if (!response.ok) throw new Error('Backtest failed');
        const result = await response.json();
        backtestTrades = result.trades || [];
        backtestDateRange = { start_date: result.start_date, end_date: result.end_date };
        const metricsEl = document.getElementById('backtest-metrics');
        if (metricsEl) {
            metricsEl.classList.remove('hidden');
            document.getElementById('bt-winrate').textContent = result.win_rate + '%';
            document.getElementById('bt-trades').textContent = result.total_trades;
            const btReturn = document.getElementById('bt-return');
            btReturn.textContent = result.total_return_pct + '%';
            btReturn.className = result.total_return_pct >= 0 ? 'font-bold text-green-400' : 'font-bold text-red-400';
            document.getElementById('bt-drawdown').textContent = result.max_drawdown_pct + '%';
        }
        showToast(`Backtest complete: ${result.win_rate}% win rate`, 'success');
        loadStrategyPerformanceChart();
    } catch (error) {
        showToast('Backtest failed: ' + error.message, 'error');
    }
}

// ─── Bulk Optimization ────────────────────────────────────────────────────────
function bulkOptimizeAll() {
    const today = new Date().toISOString().split('T')[0];
    const monthAgo = new Date(Date.now() - 30*24*60*60*1000).toISOString().split('T')[0];
    const content = `
        <div class="space-y-4">
            <p class="text-gray-400 text-sm">Runs backtests for all active strategies across all active symbols.</p>
            <div class="bg-gray-800 rounded-lg p-4 text-sm text-gray-300 space-y-1">
                <div>• 1-2 parameter combinations tested per strategy</div>
                <div>• Best parameters automatically saved</div>
            </div>
            <div class="grid grid-cols-2 gap-3">
                <div><label class="block text-sm text-gray-400 mb-2">Start Date</label><input type="date" id="bulk-start" value="${monthAgo}" class="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2"></div>
                <div><label class="block text-sm text-gray-400 mb-2">End Date</label><input type="date" id="bulk-end" value="${today}" class="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2"></div>
            </div>
            <div><label class="block text-sm text-gray-400 mb-2">Initial Capital ($)</label><input type="number" id="bulk-capital" value="1000" step="100" class="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2"></div>
            <div id="bulk-progress" style="display:none;">
                <div class="bg-gray-800 rounded-lg p-4">
                    <div class="flex justify-between text-sm mb-2"><span id="bulk-status">Starting...</span><span id="bulk-count">0 / 0</span></div>
                    <div class="bg-gray-700 rounded-full h-4 overflow-hidden"><div id="bulk-bar" class="bg-gradient-to-r from-purple-600 to-blue-600 h-full transition-all duration-300" style="width:0%"></div></div>
                </div>
                <div id="bulk-results" class="mt-4 max-h-96 overflow-y-auto space-y-2"></div>
            </div>
            <div class="flex gap-2">
                <button onclick="startBulkOptimization()" id="bulk-start-btn" class="flex-1 bg-purple-600 hover:bg-purple-700 py-3 rounded-lg font-bold text-lg">🚀 Start Bulk Optimization</button>
                <button onclick="closeModal()" class="px-6 bg-gray-600 hover:bg-gray-700 py-3 rounded-lg font-semibold">Cancel</button>
            </div>
        </div>`;
    openModal('Bulk Strategy Optimization', content);
}

async function startBulkOptimization() {
    const startDate = document.getElementById('bulk-start').value;
    const endDate = document.getElementById('bulk-end').value;
    const capital = document.getElementById('bulk-capital').value;
    let symbols = ['BTC', 'ETH', 'SOL'];
    try {
        const resp = await fetch(`http://${window.API_HOST}:8012/symbols`);
        const d = await resp.json();
        if (d.symbols && d.symbols.length > 0) symbols = d.symbols.map(s => s.symbol);
    } catch(e) {}
    const startBtn = document.getElementById('bulk-start-btn');
    const progressDiv = document.getElementById('bulk-progress');
    const statusEl = document.getElementById('bulk-status');
    const countEl = document.getElementById('bulk-count');
    const barEl = document.getElementById('bulk-bar');
    const resultsDiv = document.getElementById('bulk-results');
    startBtn.disabled = true;
    startBtn.innerHTML = '⏳ Running...';
    progressDiv.style.display = 'block';
    try {
        const strategiesResp = await fetch(`http://${window.API_HOST}:8015/strategies`);
        const strategiesData = await strategiesResp.json();
        const strategies = strategiesData.strategies.filter(s => s.enabled);
        if (strategies.length === 0) { showToast('No enabled strategies found', 'error'); startBtn.disabled = false; startBtn.innerHTML = '🚀 Start Bulk Optimization'; return; }
        const totalJobs = strategies.length * symbols.length;
        let completed = 0, successful = 0;
        statusEl.textContent = 'Optimizing strategies...';
        countEl.textContent = `0 / ${totalJobs}`;
        for (const strategy of strategies) {
            for (const symbol of symbols) {
                statusEl.textContent = `[${completed+1}/${totalJobs}] ${strategy.name} on ${symbol}...`;
                try {
                    const configResp = await fetch(`http://${window.API_HOST}:8020/strategies/${strategy.id}/config`);
                    const config = await configResp.json();
                    if (!config.tunable_parameters || config.tunable_parameters.length === 0) {
                        resultsDiv.innerHTML += `<div class="bg-gray-800 p-3 rounded text-sm"><span class="text-gray-400">${strategy.name} on ${symbol}:</span><span class="text-yellow-400"> Skipped (no params)</span></div>`;
                    } else {
                        const paramCombinations = [{}];
                        config.tunable_parameters.forEach(p => paramCombinations[0][p.name] = p.current_value);
                        if (config.tunable_parameters.length > 0) {
                            const fp = config.tunable_parameters[0];
                            const midCombo = {};
                            config.tunable_parameters.forEach(p => midCombo[p.name] = p.name === fp.name ? Math.round((fp.min_value + fp.max_value) / 2) : p.current_value);
                            paramCombinations.push(midCombo);
                        }
                        let bestResult = null, bestScore = -Infinity, bestParams = null;
                        for (const params of paramCombinations) {
                            try {
                                const btResp = await fetch(`http://${window.API_HOST}:8013/run`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ strategy_id: strategy.id, symbol, start_date: startDate, end_date: endDate, initial_capital: parseFloat(capital), parameters_override: params }) });
                                if (btResp.ok) { const result = await btResp.json(); const score = result.total_return_pct * (result.win_rate / 100); if (score > bestScore && result.total_trades > 0) { bestScore = score; bestResult = result; bestParams = params; } }
                            } catch(e) {}
                        }
                        if (bestParams && bestScore > 0) {
                            await fetch(`http://${window.API_HOST}:8020/strategies/overrides`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ strategy_id: strategy.id, symbol, parameter_overrides: bestParams }) });
                            successful++;
                            resultsDiv.innerHTML += `<div class="bg-green-900 border border-green-700 p-3 rounded text-sm"><div class="font-bold">${strategy.name} on ${symbol}</div><div class="text-green-300">✓ ${bestResult.total_return_pct.toFixed(2)}% return | ${bestResult.win_rate.toFixed(1)}% win | ${bestResult.total_trades} trades</div></div>`;
                        } else {
                            resultsDiv.innerHTML += `<div class="bg-gray-800 p-3 rounded text-sm"><span class="text-gray-400">${strategy.name} on ${symbol}:</span><span class="text-red-400"> No profitable combinations</span></div>`;
                        }
                    }
                } catch(error) {
                    resultsDiv.innerHTML += `<div class="bg-red-900 border border-red-700 p-3 rounded text-sm"><span class="text-gray-400">${strategy.name} on ${symbol}:</span><span class="text-red-300"> Error - ${error.message}</span></div>`;
                }
                completed++;
                countEl.textContent = `${completed} / ${totalJobs}`;
                barEl.style.width = `${(completed / totalJobs) * 100}%`;
                resultsDiv.scrollTop = resultsDiv.scrollHeight;
            }
        }
        statusEl.textContent = '✓ Optimization Complete!';
        startBtn.innerHTML = `✓ Complete (${successful} optimized)`;
        showToast(`Bulk optimization complete! ${successful} optimized.`, 'success');
    } catch(error) {
        showToast('Error: ' + error.message, 'error');
        startBtn.disabled = false;
        startBtn.innerHTML = '🚀 Start Bulk Optimization';
    }
}

// ─── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    window.checkSystemHealthBackground && window.checkSystemHealthBackground();
    loadStrategies();
    loadStrategyPerformance();
    setInterval(loadStrategies, 120000);

    const strategyForm = document.getElementById('strategy-form');
    if (strategyForm) {
        strategyForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const name = document.getElementById('strategy-name').value;
            const description = document.getElementById('strategy-desc').value;
            const buyIndicator = document.getElementById('buy-indicator').value;
            const buyOperator = document.getElementById('buy-operator').value;
            const buyValue = parseFloat(document.getElementById('buy-value').value);
            const sellIndicator = document.getElementById('sell-indicator').value;
            const sellOperator = document.getElementById('sell-operator').value;
            const sellValue = parseFloat(document.getElementById('sell-value').value);
            const indicator_logic = {
                buy_conditions: [{ indicator: buyIndicator, operator: buyOperator, value: buyValue }],
                sell_conditions: [{ indicator: sellIndicator, operator: sellOperator, value: sellValue }]
            };
            const parameters = {};
            document.getElementById('parameter-fields').querySelectorAll('input[id^="param-"]').forEach(field => {
                parameters[field.id.replace('param-', '')] = field.type === 'number' ? parseFloat(field.value) : field.value;
            });
            try {
                const response = await fetch(`http://${window.API_HOST}:8015/strategies/create?` + new URLSearchParams({ name, description, indicator_logic: JSON.stringify(indicator_logic), parameters: JSON.stringify(parameters), created_by: 'manual' }), { method: 'POST' });
                const data = await response.json();
                if (data.status === 'success') {
                    showToast('Strategy created successfully!', 'success');
                    closeCreateStrategy();
                    loadStrategies();
                } else {
                    showToast('Failed to create strategy', 'error');
                }
            } catch(error) {
                showToast('Error creating strategy', 'error');
            }
        });
    }
});
