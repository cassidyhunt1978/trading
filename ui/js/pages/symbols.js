// pages/symbols.js — Symbols page
// Depends on: symbol-manager.js (loaded by this page)


function renderSymbolCardsFromCache() {
            const hideZeros = document.getElementById('hide-zeros-toggle')?.checked ?? true;
            let symbols = window._symbolsCache || [];
            if (hideZeros) {
                // Hide symbols with no meaningful activity
                symbols = symbols.filter(s =>
                    s.best_trust_factor > 0.01 ||
                    s.strategy_trades >= 5 ||
                    s.trades_30d >= 1
                );
            }
            // Max 20 cards shown; rest hidden but still loaded
            renderSymbolCards(symbols);
        }

async function runFullCycle(btn) {
            if (btn) { btn.disabled = true; btn.textContent = '⏳ Running…'; }
            try {
                const r = await fetch(`http://${window.API_HOST}:8017/run-cycle`, { method: 'POST' });
                const d = await r.json();
                if (btn) { btn.textContent = d.status === 'triggered' ? '✅ Triggered' : '❌ Error'; }
            } catch(e) {
                if (btn) { btn.textContent = '❌ Failed'; }
                console.error('run-cycle error', e);
            }
            setTimeout(() => { if (btn) { btn.disabled = false; btn.textContent = '⚡ Run Full Cycle'; } }, 4000);
        }

function renderSymbolCards(symbols) {
            const grid1 = document.getElementById('symbols-grid');
            if (!grid1) return;
            const html = symbols.map(s => `
                <div class="symbol-card">
                    <!-- Header -->
                    <div class="flex items-start justify-between mb-3">
                        <div>
                            <div class="text-3xl font-bold">${s.symbol}</div>
                            <div class="text-sm text-gray-400">${s.name}</div>
                        </div>
                        <div class="text-right">
                            <div class="text-2xl font-bold" id="price-${s.symbol}">$--</div>
                            <div class="text-sm" id="change-${s.symbol}">--</div>
                        </div>
                    </div>

                    <!-- Trust + PF badge row -->
                    <div class="flex items-center gap-2 mb-3 flex-wrap">
                        ${(() => {
                            const pct = Math.round((s.best_trust_factor || 0) * 100);
                            const col = pct >= 70 ? 'bg-green-900 text-green-300' : pct >= 40 ? 'bg-yellow-900 text-yellow-300' : 'bg-gray-700 text-gray-400';
                            return `<span class="px-2 py-0.5 rounded text-xs font-bold ${col}" title="Best strategy trust factor">🎯 Trust ${pct}%</span>`;
                        })()}
                        ${s.best_profit_factor > 0 ? `<span class="px-2 py-0.5 rounded text-xs bg-blue-900 text-blue-300" title="Best profit factor">PF ${(s.best_profit_factor).toFixed(2)}</span>` : ''}
                        ${s.strategy_trades > 0 ? `<span class="px-2 py-0.5 rounded text-xs bg-gray-700 text-gray-400">${s.strategy_trades} bt-trades</span>` : '<span class="px-2 py-0.5 rounded text-xs bg-gray-800 text-gray-600">no backtest</span>'}
                    </div>
                    
                    <!-- Stats -->
                    <div class="grid grid-cols-3 gap-2 mb-4">
                        <div class="stat-box">
                            <div class="stat-label">24h Vol</div>
                            <div class="stat-value text-xs" id="vol-${s.symbol}">--</div>
                        </div>
                        <div class="stat-box">
                            <div class="stat-label">Candles</div>
                            <div class="stat-value" id="candles-${s.symbol}">0</div>
                        </div>
                        <div class="stat-box">
                            <div class="stat-label">Signals</div>
                            <div class="stat-value" id="signals-${s.symbol}">0</div>
                        </div>
                    </div>
                    
                    <!-- Win Rates -->
                    <div class="bg-gray-800 rounded-lg p-3 mb-4">
                        <div class="text-xs text-gray-400 mb-2 font-semibold">Win Rates</div>
                        <div class="grid grid-cols-3 gap-2 text-xs">
                            <div>
                                <div class="text-gray-400">24h</div>
                                <div class="font-bold" id="win24-${s.symbol}">0% (0W/0L)</div>
                            </div>
                            <div>
                                <div class="text-gray-400">7d</div>
                                <div class="font-bold" id="win7-${s.symbol}">0% (0W/0L)</div>
                            </div>
                            <div>
                                <div class="text-gray-400">30d</div>
                                <div class="font-bold" id="win30-${s.symbol}">90% (9W/1L)</div>
                            </div>
                        </div>
                    </div>
                    
                    <!-- Signal Counts -->
                    <div class="flex items-center justify-between text-xs mb-4">
                        <span class="text-gray-400">Signals (24h):</span>
                        <div class="flex gap-2">
                            <span class="bg-green-900 text-green-400 px-2 py-1 rounded font-bold">
                                ↑ <span id="buy-${s.symbol}">0</span>
                            </span>
                            <span class="bg-red-900 text-red-400 px-2 py-1 rounded font-bold">
                                ↓ <span id="sell-${s.symbol}">0</span>
                            </span>
                        </div>
                    </div>
                    
                    <!-- Action Buttons -->
                    <div class="grid grid-cols-4 gap-2">
                        <button onclick="showChart('${s.symbol}')" class="action-btn bg-blue-900 hover:bg-blue-800 text-blue-300 border-blue-700">
                            📊 Chart
                        </button>
                        <button onclick="showSignals('${s.symbol}')" class="action-btn bg-purple-900 hover:bg-purple-800 text-purple-300 border-purple-700">
                            🎯 Signals
                        </button>
                        <button onclick="showBacktest('${s.symbol}')" class="action-btn bg-green-900 hover:bg-green-800 text-green-300 border-green-700">
                            📈 Test
                        </button>
                        <button onclick="showDetails('${s.symbol}')" class="action-btn bg-gray-700 hover:bg-gray-600 text-gray-300 border-gray-600">
                            ⚙️ Info
                        </button>
                    </div>
                </div>
            `).join('');
            grid1.innerHTML = html;
        }

async function loadSymbolStats() {
            try {
                const response = await fetch(`http://${window.API_HOST}:8016/symbols/stats?mode=paper`);
                if (!response.ok) {
                    console.warn('Failed to load symbol stats');
                    return;
                }
                
                const data = await response.json();
                const stats = data.symbols || [];
                
                stats.forEach(stat => {
                    const symbol = stat.symbol;
                    
                    // Update 24h win rate
                    const win24El = document.getElementById(`win24-${symbol}`);
                    if (win24El) {
                        const rate24 = stat.trades_24h > 0 ? ((stat.wins_24h / stat.trades_24h) * 100).toFixed(0) : 0;
                        const color24 = rate24 >= 50 ? 'text-green-400' : rate24 >= 40 ? 'text-yellow-400' : 'text-red-400';
                        win24El.textContent = `${rate24}% (${stat.wins_24h}W/${stat.losses_24h}L)`;
                        win24El.className = `font-bold ${color24}`;
                    }
                    
                    // Update 7d win rate
                    const win7El = document.getElementById(`win7-${symbol}`);
                    if (win7El) {
                        const rate7 = stat.trades_7d > 0 ? ((stat.wins_7d / stat.trades_7d) * 100).toFixed(0) : 0;
                        const color7 = rate7 >= 50 ? 'text-green-400' : rate7 >= 40 ? 'text-yellow-400' : 'text-red-400';
                        win7El.textContent = `${rate7}% (${stat.wins_7d}W/${stat.losses_7d}L)`;
                        win7El.className = `font-bold ${color7}`;
                    }
                    
                    // Update 30d win rate
                    const win30El = document.getElementById(`win30-${symbol}`);
                    if (win30El) {
                        const rate30 = stat.trades_30d > 0 ? ((stat.wins_30d / stat.trades_30d) * 100).toFixed(0) : 0;
                        const color30 = rate30 >= 50 ? 'text-green-400' : rate30 >= 40 ? 'text-yellow-400' : 'text-red-400';
                        win30El.textContent = `${rate30}% (${stat.wins_30d}W/${stat.losses_30d}L)`;
                        win30El.className = `font-bold ${color30}`;
                    }
                });
                
            } catch (error) {
                console.error('Error loading symbol stats:', error);
            }
        }

async function loadSymbolData(symbol) {
            try {
                const resp = await fetch(`http://${window.API_HOST}:8012/candles?symbol=${symbol}&limit=30`, {
                    signal: AbortSignal.timeout(15000)
                });
                if (!resp || !resp.ok) return;
                const candles = await resp.json();
                const candleEl = document.getElementById(`candles-${symbol}`);
                if (candleEl) candleEl.textContent = candles.length || 0;
                if (candles.length > 0) {
                    const latest = candles[candles.length - 1];
                    const price = latest.close;
                    const priceEl = document.getElementById(`price-${symbol}`);
                    if (priceEl) priceEl.textContent = `$${price.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
                    if (candles.length > 24) {
                        const dayAgo = candles[candles.length - 25];
                        const change = ((price - dayAgo.close) / dayAgo.close) * 100;
                        const changeEl = document.getElementById(`change-${symbol}`);
                        if (changeEl) {
                            changeEl.textContent = `${change >= 0 ? '+' : ''}${change.toFixed(2)}%`;
                            changeEl.className = change >= 0 ? 'text-sm price-up' : 'text-sm price-down';
                        }
                    }
                }
            } catch (e) {
                if (e.name !== 'AbortError') console.warn(`Candles failed for ${symbol}:`, e.message);
            }
        }


// ── loadSymbols: fetch symbols+stats, populate cache, render cards ────────────
async function loadSymbols() {
    try {
        const [symResp, statsResp] = await Promise.allSettled([
            fetch(`http://${window.API_HOST}:8012/symbols`, { signal: AbortSignal.timeout(8000) }),
            fetch(`http://${window.API_HOST}:8016/symbols/stats?mode=paper`, { signal: AbortSignal.timeout(8000) })
        ]);

        const symData   = symResp.status === 'fulfilled'   && symResp.value.ok   ? await symResp.value.json()   : {};
        const statsData = statsResp.status === 'fulfilled' && statsResp.value.ok ? await statsResp.value.json() : {};

        const symbols  = symData.symbols || [];
        const statsMap = {};
        (statsData.symbols || []).forEach(s => { statsMap[s.symbol] = s; });

        const merged = symbols.map(s => ({
            ...s,
            best_trust_factor:  parseFloat(statsMap[s.symbol]?.best_trust_factor  || 0),
            best_profit_factor: parseFloat(statsMap[s.symbol]?.best_profit_factor || 0),
            strategy_trades:    parseInt(statsMap[s.symbol]?.strategy_trades      || 0),
            trades_30d:         parseInt(statsMap[s.symbol]?.trades_30d           || 0),
            pnl_30d:            parseFloat(statsMap[s.symbol]?.pnl_30d            || 0),
        }));
        merged.sort((a, b) => (b.best_trust_factor - a.best_trust_factor) || a.symbol.localeCompare(b.symbol));

        window._symbolsCache = merged;
        renderSymbolCardsFromCache();

        // Background: load per-symbol candle data + signals
        loadSymbolStats();
        symbols.forEach(s => loadSymbolData(s.symbol));
    } catch (error) {
        console.error('Error loading symbols:', error);
        const grid = document.getElementById('symbols-grid');
        if (grid) grid.innerHTML = '<div class="text-red-400 p-4">Failed to load symbols. Check console for details.</div>';
    }
}
window.loadSymbols = loadSymbols;

// ── Init ──────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    window.initRealtimeConnection && window.initRealtimeConnection();
    window.checkSystemHealthBackground && window.checkSystemHealthBackground();
    loadSymbols();

    setInterval(loadSymbols, 60000);
    setInterval(() => { window.checkSystemHealthBackground && window.checkSystemHealthBackground(); }, 60000);
});
