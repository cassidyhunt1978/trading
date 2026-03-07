// P&L Card  JavaScript Functions
let currentPnlMode = 'paper';
let pnlChartInstance = null;

// Debounce mechanism to prevent rapid consecutive loads
let lastLoadTime = 0;
const MIN_LOAD_INTERVAL = 2000; // Minimum 2 seconds between loads
let isLoading = false;

async function switchPnlMode(mode) {
    console.log(`[MODE SWITCH] Switching from ${currentPnlMode} to ${mode}`);
    currentPnlMode = mode;
    
    // Update button styles
    document.getElementById('pnl-mode-paper').className = 
        mode === 'paper' 
        ? 'px-4 py-2 rounded-lg font-semibold transition-all bg-blue-600 text-white shadow-lg'
        : 'px-4 py-2 rounded-lg font-semibold transition-all bg-gray-700 hover:bg-gray-600 text-gray-300';
    
    document.getElementById('pnl-mode-live').className = 
        mode === 'live' 
        ? 'px-4 py-2 rounded-lg font-semibold transition-all bg-red-600 text-white shadow-lg'
        : 'px-4 py-2 rounded-lg font-semibold transition-all bg-gray-700 hover:bg-gray-600 text-gray-300';
    
    // Update label
    document.getElementById('pnl-mode-label').textContent = 
        mode === 'paper' ? 'Paper Trading Mode (Simulated)' : '🔴 Live Trading Mode (Real Money)';
    
    // Keep timezone info visible
    const tzInfo = document.getElementById('pnl-timezone-info');
    if (tzInfo) {
        const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
        const now = new Date();
        const tzAbbr = now.toLocaleTimeString('en-US', { timeZoneName: 'short' }).split(' ').pop();
        tzInfo.textContent = `Today: ${tz.split('/').pop()} (${tzAbbr})`;
    }
    
    // Toggle live breakdown visibility
    const liveBreakdown = document.getElementById('pnl-live-breakdown');
    if (liveBreakdown) {
        if (mode === 'live') {
            liveBreakdown.classList.remove('hidden');
        } else {
            liveBreakdown.classList.add('hidden');
        }
    }
    
    // Show notification about mode change
    if (window.showNotification) {
        window.showNotification(
            `Switched to ${mode === 'live' ? '🔴 LIVE' : '📋 PAPER'} trading mode`, 
            'info'
        );
    }
    
    // Reload data for selected mode
    console.log(`[MODE SWITCH] Loading data for mode: ${mode}`);
    await loadPnlCard(mode);
    console.log(`[MODE SWITCH] Data loaded for mode: ${mode}`);
}

async function loadPnlCard(mode = 'paper') {
    // Debounce: Prevent rapid consecutive loads
    const now = Date.now();
    if (isLoading || (now - lastLoadTime) < MIN_LOAD_INTERVAL) {
        console.log(`[PNL CARD] Skipping load - too soon (${Math.floor((now - lastLoadTime)/1000)}s since last)`);
        return;
    }
    
    isLoading = true;
    lastLoadTime = now;
    
    try {
        console.log(`[PNL CARD] Loading P&L card for mode: ${mode}`);
        // For live mode, check if portfolio exists first
        let portfolio = {};
        let portfolioExists = false;
        
        // Fetch portfolio state (suppress console errors for expected 404s)
        try {
            const portfolioUrl = `http://${window.API_HOST}:8016/portfolio?mode=${mode}`;
            console.log(`[PNL CARD] Fetching portfolio from: ${portfolioUrl}`);
            const portfolioResponse = await fetch(portfolioUrl);
            
            if (portfolioResponse.ok) {
                const data = await portfolioResponse.json();
                // Check if it's an error response
                if (data.detail && data.detail.includes('No portfolio found')) {
                    portfolioExists = false;
                } else {
                    portfolio = data;
                    portfolioExists = true;
                }
            }
        } catch (error) {
            // Portfolio fetch failed - this is expected for live mode if not started
            console.log(`Portfolio not found for ${mode} mode - this is normal if ${mode} trading hasn't started yet`);
        }
        
        // For live mode without portfolio, fetch live balance instead
        if (mode === 'live' && !portfolioExists) {
            // Fetch live balance
            let liveBalance = 0;
            try {
                const balanceResponse = await fetch(`http://${window.API_HOST}:8016/balance/live`);
                const balanceData = await balanceResponse.json();
                
                if (balanceData.status === 'success' && balanceData.balances && balanceData.balances.USD) {
                    liveBalance = balanceData.balances.USD.total || 0;
                    console.log(`[PNL CARD] Live USD balance: $${liveBalance}`);
                }
            } catch (error) {
                console.error('[PNL CARD] Error fetching live balance:', error);
            }
            
            await loadLiveBalances();
            
            // Show live balance as both portfolio value and total capital
            document.getElementById('pnl-portfolio-value').textContent = `$${liveBalance.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
            document.getElementById('pnl-portfolio-value').className = 'text-3xl font-bold text-blue-400 mb-1';
            document.getElementById('pnl-portfolio-change').textContent = 'Live trading not started - No positions yet';
            document.getElementById('pnl-portfolio-change').className = 'text-sm text-gray-400';
            document.getElementById('pnl-starting-capital').textContent = `Exchange Balance: $${liveBalance.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
            document.getElementById('pnl-total-capital').textContent = `$${liveBalance.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
            document.getElementById('pnl-available-capital').textContent = `$${liveBalance.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
            document.getElementById('pnl-deployed-capital').textContent = '$0.00 invested';
            document.getElementById('pnl-capital-source').textContent = 'Kraken';
            document.getElementById('pnl-available-pct').textContent = '100.0%';
            document.getElementById('pnl-open-positions').textContent = '0';
            document.getElementById('pnl-unrealized').textContent = '$0.00';
            document.getElementById('pnl-unrealized').className = 'text-lg font-bold text-gray-400';
            document.getElementById('pnl-unrealized-pct').textContent = '0.00%';
            document.getElementById('pnl-unrealized-pct').className = 'text-xs text-gray-400 mt-auto';
            document.getElementById('pnl-daily').textContent = '$0.00';
            document.getElementById('pnl-daily').className = 'text-lg font-bold text-gray-400';
            document.getElementById('pnl-daily-pct').textContent = '0.00%';
            document.getElementById('pnl-daily-pct').className = 'text-xs text-gray-400 mt-auto';
            document.getElementById('pnl-total').textContent = '$0.00';
            document.getElementById('pnl-total').className = 'text-lg font-bold text-gray-400';
            document.getElementById('pnl-total-pct').textContent = '0.00%';
            document.getElementById('pnl-total-pct').className = 'text-xs text-gray-400 mt-auto';
            document.getElementById('pnl-win-rate').textContent = '0%';
            document.getElementById('pnl-win-rate').className = 'text-lg font-bold text-gray-400';
            document.getElementById('pnl-win-ratio').textContent = '0W/0L';
            document.getElementById('pnl-avg-trade').textContent = '$0.00';
            document.getElementById('pnl-avg-trade').className = 'text-base font-bold text-gray-400';
            document.getElementById('pnl-trades-today').textContent = '0 today';
            document.getElementById('pnl-progress-bar').style.width = '100%';
            document.getElementById('pnl-progress-bar').className = 'bg-green-500 h-2 rounded-full transition-all';
            return;
        }
        
        // If we get here and still no portfolio, something is wrong
        if (!portfolioExists) {
            console.error(`No portfolio data available for ${mode} mode`);
            return;
        }
        
        // Fetch positions for stats (ensemble only - actual portfolio trades)
        const positionsResponse = await fetch(`http://${window.API_HOST}:8016/positions?mode=${mode}&status=closed&position_type=ensemble`);
        const positionsData = await positionsResponse.json();
        const closedPositions = positionsData.positions || [];
        
        // Fetch open positions (ensemble only)
        const openResponse = await fetch(`http://${window.API_HOST}:8016/positions?mode=${mode}&status=open&position_type=ensemble`);
        const openData = await openResponse.json();
        const openPositions = openData.positions || [];
        
        // Calculate metrics
        const totalCapital = portfolio.total_capital || 0;
        
        // Calculate actual deployed capital from open ensemble positions
        const deployedCapital = openPositions.reduce((sum, p) => sum + (parseFloat(p.capital_allocated) || 0), 0);
        
        // Calculate available capital as total - deployed (don't trust API's available_capital which includes all position types)
        const availableCapital = totalCapital - deployedCapital;
        
        const dailyPnl = portfolio.daily_pnl || 0;
        const dailyPnlPct = portfolio.daily_pnl_pct || 0;
        const totalPnl = portfolio.total_pnl || 0;
        const totalPnlPct = portfolio.total_pnl_pct || 0;
        
        // Calculate unrealized P&L from open positions
        const unrealizedPnl = openPositions.reduce((sum, p) => sum + (p.current_pnl || 0), 0);
        
        // Calculate realized P&L from all closed ensemble trades (price movement + fees)
        const realizedPnl = closedPositions.reduce((sum, p) => {
            const pnl = p.realized_pnl || p.current_pnl || 0;
            const fees = (p.entry_fee || 0) + (p.exit_fee || 0);
            return sum + (pnl - fees);
        }, 0);
        
        // Calculate TRUE Account Value: Starting Capital + All P&L (realized + unrealized)
        // Use the portfolio's total_capital as the starting capital (this is set from config)
        let startingCapital = totalCapital;
        
        if (mode === 'live') {
            // For live mode, fetch actual exchange balance
            try {
                const balanceResponse = await fetch(`http://${window.API_HOST}:8016/balance/live`);
                const balanceData = await balanceResponse.json();
                
                if (balanceData.status === 'success' && balanceData.balances && balanceData.balances.USD) {
                    startingCapital = balanceData.balances.USD.total || 0;
                    console.log(`[PNL CARD] Using live USD balance as starting capital: $${startingCapital}`);
                } else {
                    console.warn('[PNL CARD] Could not fetch live USD balance, using totalCapital from portfolio');
                }
            } catch (error) {
                console.error('[PNL CARD] Error fetching live balance:', error);
            }
        }
        
        const totalAccountPnl = realizedPnl + unrealizedPnl;
        const portfolioValue = startingCapital + totalAccountPnl;
        const portfolioValueChange = (totalAccountPnl / startingCapital) * 100;
        
        // Calculate unrealized P&L percentage
        const unrealizedPnlPct = deployedCapital > 0 ? ((unrealizedPnl / deployedCapital) * 100) : 0;
        
        // Today's P&L: positions that CLOSED today + unrealized from open positions
        // Use LOCAL timezone (not UTC) so "today" matches user's calendar day
        const now = new Date();
        const year = now.getFullYear();
        const month = String(now.getMonth() + 1).padStart(2, '0');
        const day = String(now.getDate()).padStart(2, '0');
        const today = `${year}-${month}-${day}`;
        const timezoneName = Intl.DateTimeFormat().resolvedOptions().timeZone;
        // Filter positions that closed today in LOCAL timezone
        const closedToday = closedPositions.filter(p => {
            if (!p.exit_time) return false;
            // Convert UTC exit_time to local date
            const exitDate = new Date(p.exit_time);
            const exitLocalDate = `${exitDate.getFullYear()}-${String(exitDate.getMonth() + 1).padStart(2, '0')}-${String(exitDate.getDate()).padStart(2, '0')}`;
            return exitLocalDate === today;
        });
        
        // Calculate today's realized P&L (from closed positions)
        const todayRealizedPnl = closedToday.reduce((sum, p) => {
            const pnl = p.realized_pnl || p.current_pnl || 0;
            const fees = (p.entry_fee || 0) + (p.exit_fee || 0);
            return sum + (pnl - fees);
        }, 0);
        
        // Today's total P&L = closed today + unrealized from open positions
        const todayTotalPnl = todayRealizedPnl + unrealizedPnl;
        const todayTotalPnlPct = totalCapital > 0 ? ((todayTotalPnl / totalCapital) * 100) : 0;
        
        // Win rate calculation for positions that closed today
        const wins = closedToday.filter(p => {
            const pnl = (p.realized_pnl || p.current_pnl || 0) - ((p.entry_fee || 0) + (p.exit_fee || 0));
            return pnl > 0;
        }).length;
        const losses = closedToday.filter(p => {
            const pnl = (p.realized_pnl || p.current_pnl || 0) - ((p.entry_fee || 0) + (p.exit_fee || 0));
            return pnl <= 0;
        }).length;
        const winRate = closedToday.length > 0 ? ((wins / closedToday.length) * 100).toFixed(1) : 0;
        
        // Average trade (from positions closed today, including fees)
        const avgTrade = closedToday.length > 0 
            ? closedToday.reduce((sum, p) => {
                const pnl = (p.realized_pnl || p.current_pnl || 0) - ((p.entry_fee || 0) + (p.exit_fee || 0));
                return sum + pnl;
            }, 0) / closedToday.length
            : 0;
        
        // Update UI
        document.getElementById('pnl-total-capital').textContent = `$${totalCapital.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
        document.getElementById('pnl-available-capital').textContent = `$${availableCapital.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
        
        // True Account Value (starting capital + all realized and unrealized P&L)
        const portfolioValueColor = totalAccountPnl >= 0 ? 'text-blue-400' : 'text-orange-400';
        document.getElementById('pnl-portfolio-value').textContent = `$${portfolioValue.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
        document.getElementById('pnl-portfolio-value').className = `text-3xl font-bold ${portfolioValueColor} mb-1`;
        const portfolioChangeColor = totalAccountPnl >= 0 ? 'text-green-400' : 'text-red-400';
        document.getElementById('pnl-portfolio-change').textContent = `${totalAccountPnl >= 0 ? '+' : ''}$${totalAccountPnl.toFixed(2)} (${portfolioValueChange >= 0 ? '+' : ''}${portfolioValueChange.toFixed(2)}%) • Realized: $${realizedPnl.toFixed(2)} | Unrealized: $${unrealizedPnl.toFixed(2)}`;
        document.getElementById('pnl-portfolio-change').className = `text-sm ${portfolioChangeColor}`;
        
        // Update starting capital display
        document.getElementById('pnl-starting-capital').textContent = 
            `${mode === 'live' ? 'Exchange Balance' : 'Started'}: $${startingCapital.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
        
        // Set capital source label
        document.getElementById('pnl-capital-source').textContent = 
            mode === 'paper' ? 'Simulated Capital' : 'Live Exchange Balance';
        
        // Set available capital percentage
        const availablePct = totalCapital > 0 ? ((availableCapital / totalCapital) * 100).toFixed(1) : 0;
        document.getElementById('pnl-available-pct').textContent = `${availablePct}% of total`;
        
        // Open Positions
        document.getElementById('pnl-open-positions').textContent = openPositions.length;
        document.getElementById('pnl-deployed-capital').textContent = `$${deployedCapital.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})} invested`;
        
        // Unrealized P&L
        const unrealizedColor = unrealizedPnl >= 0 ? 'text-green-400' : 'text-red-400';
        document.getElementById('pnl-unrealized').textContent = `$${unrealizedPnl.toFixed(2)}`;
        document.getElementById('pnl-unrealized').className = `text-lg font-bold ${unrealizedColor}`;
        document.getElementById('pnl-unrealized-pct').textContent = `${unrealizedPnl >= 0 ? '+' : ''}${unrealizedPnlPct.toFixed(2)}%`;
        document.getElementById('pnl-unrealized-pct').className = `text-xs ${unrealizedColor} mt-auto`;
        
        // Today's P&L (use calculated todayTotalPnl which includes closed today + unrealized)
        const dailyColor = todayTotalPnl >= 0 ? 'text-green-400' : 'text-red-400';
        document.getElementById('pnl-daily').textContent = `$${todayTotalPnl.toFixed(2)}`;
        document.getElementById('pnl-daily').className = `text-lg font-bold ${dailyColor}`;
        document.getElementById('pnl-daily-pct').textContent = `${todayTotalPnl >= 0 ? '+' : ''}${todayTotalPnlPct.toFixed(2)}%`;
        document.getElementById('pnl-daily-pct').className = `text-xs ${dailyColor} mt-auto`;
        
        // Total P&L (use calculated totalAccountPnl which includes fees)
        const totalColor = totalAccountPnl >= 0 ? 'text-green-400' : 'text-red-400';
        document.getElementById('pnl-total').textContent = `$${totalAccountPnl.toFixed(2)}`;
        document.getElementById('pnl-total').className = `text-lg font-bold ${totalColor}`;
        document.getElementById('pnl-total-pct').textContent = `${totalAccountPnl >= 0 ? '+' : ''}${portfolioValueChange.toFixed(2)}%`;
        document.getElementById('pnl-total-pct').className = `text-xs ${totalColor} mt-auto`;
        
        // Win rate
        const winRateColor = winRate >= 50 ? 'text-green-400' : winRate >= 40 ? 'text-yellow-400' : 'text-red-400';
        document.getElementById('pnl-win-rate').textContent = `${winRate}%`;
        document.getElementById('pnl-win-rate').className = `text-lg font-bold ${winRateColor}`;
        document.getElementById('pnl-win-ratio').textContent = `${wins}W/${losses}L`;
        
        // Average trade
        document.getElementById('pnl-avg-trade').textContent = `$${avgTrade.toFixed(2)}`;
        document.getElementById('pnl-avg-trade').className = `text-base font-bold ${avgTrade >= 0 ? 'text-green-400' : 'text-red-400'}`;
        document.getElementById('pnl-trades-today').textContent = `${closedToday.length} closed today`;
        
        // Today's Trade Activity Summary
        const totalFees = closedToday.reduce((sum, p) => sum + (p.entry_fee || 0) + (p.exit_fee || 0), 0);
        const avgPositionSize = closedToday.length > 0 
            ? closedToday.reduce((sum, p) => sum + (p.capital_allocated || 0), 0) / closedToday.length
            : 0;
        
        document.getElementById('pnl-trades-count').textContent = closedToday.length;
        document.getElementById('pnl-total-fees').textContent = `$${totalFees.toFixed(2)}`;
        document.getElementById('pnl-avg-size').textContent = `$${avgPositionSize.toFixed(2)}`;
        
        // Display open positions
        updateOpenPositionsList(openPositions);
        
        // Load and display real-time signal evaluations
        await loadSignalEvaluations();
        
        // Load and display symbol blacklist (Phase 3 risk manager)
        await loadBlacklistData();
        
        // If live mode, fetch and display live balances
        if (mode === 'live') {
            await loadLiveBalances();
        }
        
    } catch (error) {
        console.error('Error loading P&L card:', error);
    } finally {
        isLoading = false;
    }
}

async function loadLiveBalances() {
    try {
        const response = await fetch(`http://${window.API_HOST}:8016/balance/live`);
        const data = await response.json();
        
        if (data.status === 'success' && data.balances) {
            const balancesDiv = document.getElementById('pnl-live-balances');
            balancesDiv.innerHTML = Object.entries(data.balances)
                .filter(([currency, amounts]) => amounts.total > 0.01)
                .map(([currency, amounts]) => `
                    <div class="bg-gray-800 rounded p-2">
                        <div class="font-semibold text-gray-300">${currency}</div>
                        <div class="text-xs text-gray-400">
                            ${amounts.total.toFixed(currency === 'BTC' || currency === 'ETH' ? 6 : 2)} 
                            <span class="text-gray-500">(${amounts.free.toFixed(currency === 'BTC' || currency === 'ETH' ? 6 : 2)} free)</span>
                        </div>
                    </div>
                `).join('');
        } else {
            document.getElementById('pnl-live-balances').innerHTML = 
                '<div class="col-span-2 text-center text-gray-500 text-xs">Live balance unavailable</div>';
        }
    } catch (error) {
        console.error('Error loading live balances:', error);
        document.getElementById('pnl-live-balances').innerHTML = 
            '<div class="col-span-2 text-center text-red-400 text-xs">Error loading balances</div>';
    }
}

function updateOpenPositionsList(positions) {
    const listDiv = document.getElementById('pnl-positions-list');
    const countSpan = document.getElementById('pnl-positions-count');
    
    countSpan.textContent = `${positions.length} open`;
    
    if (positions.length === 0) {
        listDiv.innerHTML = '<div class="text-center text-gray-500 text-xs py-4">No open positions</div>';
        return;
    }
    
    listDiv.innerHTML = positions.map(p => {
        const currentPnl = p.current_pnl || 0;
        const currentPnlPct = p.current_pnl_pct || 0;
        const pnlColor = currentPnl >= 0 ? 'text-green-400' : 'text-red-400';
        const bgColor = currentPnl >= 0 ? 'bg-green-900/20 border-green-700' : 'bg-red-900/20 border-red-700';
        const mode = p.mode || currentPnlMode;
        
        return `
            <div class="bg-gray-900 rounded-lg p-3 border ${bgColor}">
                <div class="flex justify-between items-start mb-1">
                    <div class="flex items-center gap-2">
                        <div class="font-semibold text-white text-sm">${p.symbol}</div>
                        <button 
                            onclick="closePositionManually(${p.id}, '${mode}')" 
                            class="text-xs px-2 py-0.5 bg-red-600 hover:bg-red-700 rounded text-white font-semibold transition-all"
                            title="Close position manually">
                            ✕
                        </button>
                    </div>
                    <div class="${pnlColor} font-bold text-sm">${currentPnl >= 0 ? '+' : ''}$${currentPnl.toFixed(2)}</div>
                </div>
                <div class="flex justify-between items-center text-xs">
                    <div class="text-gray-400">
                        Entry: $${(p.entry_price || 0).toFixed(2)} → Current: $${(p.current_price || 0).toFixed(2)} | Qty: ${(p.quantity || 0).toFixed(4)}
                    </div>
                    <div class="${pnlColor}">${currentPnlPct >= 0 ? '+' : ''}${currentPnlPct.toFixed(2)}%</div>
                </div>
            </div>
        `;
    }).join('');
}

// Removed: AI consensus voting is no longer used
// System now uses Phase 1-3 architecture:
// Phase 1: OLD Ensemble (performance-weighted)
// Phase 2: AI Risk Manager (exit optimizer)
// Phase 3: Portfolio Risk (correlation, drawdown, blacklist)

async function loadConsensusVotingData(mode = 'paper') {
    // Stub function - consensus voting removed
    return;
}

// Load real-time signal evaluations from Phase 3 risk manager
async function loadSignalEvaluations() {
    try {
        const response = await fetch(`http://${window.API_HOST}:8016/risk/evaluations?limit=20`);
        if (!response.ok) {
            console.error('[EVALUATIONS] Error fetching evaluations');
            return;
        }
        
        const data = await response.json();
        const evaluations = data.evaluations || [];
        
        const listDiv = document.getElementById('pnl-evaluations-list');
        const countSpan = document.getElementById('pnl-evaluations-count');
        
        countSpan.textContent = evaluations.length > 0 ? `${evaluations.length} recent` : 'None yet';
        
        if (evaluations.length === 0) {
            listDiv.innerHTML = '<div class="text-center text-gray-500 text-xs py-2">No evaluations yet - waiting for signals</div>';
            return;
        }
        
        listDiv.innerHTML = evaluations.map(e => {
            const timestamp = new Date(e.timestamp).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
            const statusIcon = e.approved ? '✅' : '❌';
            const statusColor = e.approved ? 'text-green-400' : 'text-red-400';
            const borderColor = e.approved ? 'border-green-900' : 'border-red-900';
            const bgColor = e.approved ? 'bg-green-900/10' : 'bg-red-900/10';
            
            // Truncate long reasons
            const reason = e.rejection_reason || 'Approved';
            const shortReason = reason.length > 60 ? reason.substring(0, 57) + '...' : reason;
            
            // Build position status line if position exists
            let positionInfo = '';
            if (e.position) {
                const pos = e.position;
                if (pos.status === 'closed') {
                    const pnlColor = pos.realized_pnl >= 0 ? 'text-green-400' : 'text-red-400';
                    const pnlSign = pos.realized_pnl >= 0 ? '+' : '';
                    const exitTime = new Date(pos.exit_time).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
                    const result = pos.trade_result === 'win' ? '🎯' : pos.trade_result === 'loss' ? '❌' : '➖';
                    positionInfo = `
                        <div class="text-xs mt-2 pt-2 border-t border-gray-700">
                            <div class="flex justify-between items-center">
                                <span class="text-gray-400">Position ${result}</span>
                                <span class="${pnlColor} font-semibold">${pnlSign}$${pos.realized_pnl?.toFixed(2) || '0'} (${pnlSign}${pos.realized_pnl_pct?.toFixed(2) || '0'}%)</span>
                            </div>
                            <div class="text-gray-500 text-[10px] mt-0.5">
                                Closed at ${exitTime} · Entry: $${pos.entry_price?.toFixed(2)} → Exit: $${pos.exit_price?.toFixed(2)}
                            </div>
                        </div>
                    `;
                } else if (pos.status === 'open') {
                    const currentPnlColor = (pos.current_pnl || 0) >= 0 ? 'text-green-400' : 'text-red-400';
                    const pnlSign = (pos.current_pnl || 0) >= 0 ? '+' : '';
                    positionInfo = `
                        <div class="text-xs mt-2 pt-2 border-t border-gray-700">
                            <div class="flex justify-between items-center">
                                <span class="text-blue-400">⏳ Position Open</span>
                                <span class="${currentPnlColor} font-semibold">${pnlSign}$${(pos.current_pnl || 0).toFixed(2)} (${pnlSign}${(pos.current_pnl_pct || 0).toFixed(2)}%)</span>
                            </div>
                            <div class="text-gray-500 text-[10px] mt-0.5">
                                Entry: $${pos.entry_price?.toFixed(2)} → Current: $${pos.current_price?.toFixed(2)}
                            </div>
                        </div>
                    `;
                }
            }
            
            return `
                <div class="bg-gray-800 rounded p-2 border ${borderColor} ${bgColor}">
                    <div class="flex justify-between items-start mb-1">
                        <div class="flex items-center gap-2">
                            <span class="${statusColor} text-lg">${statusIcon}</span>
                            <span class="font-semibold text-white text-xs">${e.symbol}</span>
                            <span class="text-xs ${e.signal_type === 'BUY' ? 'text-green-400' : 'text-red-400'}">${e.signal_type}</span>
                        </div>
                        <div class="text-xs text-gray-500">${timestamp}</div>
                    </div>
                    <div class="text-xs text-gray-400 mb-1">
                        Score: ${e.weighted_score?.toFixed(1) || 'N/A'} · Value: $${e.proposed_value?.toFixed(2) || '0'}
                    </div>
                    <div class="text-xs ${statusColor} italic">
                        ${shortReason}
                    </div>
                    ${positionInfo}
                </div>
            `;
        }).join('');
        
        console.log(`[EVALUATIONS] Displayed ${evaluations.length} signal evaluations`);
        
    } catch (error) {
        console.error('[EVALUATIONS] Error loading evaluations:', error);
        document.getElementById('pnl-evaluations-list').innerHTML = 
            '<div class="text-center text-gray-500 text-xs py-2">Not available</div>';
    }
}

// Load symbol blacklist data
async function loadBlacklistData() {
    try {
        const response = await fetch(`http://${window.API_HOST}:8016/risk/blacklist`);
        if (!response.ok) {
            console.error('[BLACKLIST] Error fetching blacklist');
            return;
        }
        
        const data = await response.json();
        const blacklisted = data.blacklisted || [];
        
        const listDiv = document.getElementById('pnl-blacklist-list');
        const countSpan = document.getElementById('pnl-blacklist-count');
        
        // Check if we're in paper trading mode
        const isPaperMode = currentPnlMode === 'paper';
        
        if (isPaperMode) {
            countSpan.textContent = blacklisted.length > 0 ? `${blacklisted.length} tracked` : 'All symbols OK';
            countSpan.className = 'text-xs text-blue-400';
        } else {
            countSpan.textContent = blacklisted.length > 0 ? `${blacklisted.length} blocked` : 'None blocked';
            countSpan.className = 'text-xs text-gray-500';
        }
        
        if (blacklisted.length === 0) {
            if (isPaperMode) {
                listDiv.innerHTML = '<div class="text-center text-blue-400 text-xs py-2">✅ All symbols performing acceptably</div>';
            } else {
                listDiv.innerHTML = '<div class="text-center text-gray-500 text-xs py-2">✅ No symbols blacklisted</div>';
            }
            return;
        }
        
        listDiv.innerHTML = blacklisted.map(b => {
            const pnlColor = 'text-red-400';
            const avgPnl = b.total_pnl / b.trade_count;
            const borderColor = isPaperMode ? 'border-blue-800' : 'border-orange-900';
            const statusText = isPaperMode 
                ? '<span class="text-blue-400 text-xs">⚠️ Poor performer (still tradeable)</span>'
                : '<span class="text-orange-400 text-xs">🚫 BLOCKED</span>';
            
            return `
                <div class="bg-gray-800 rounded p-2 border ${borderColor}">
                    <div class="flex justify-between items-center mb-1">
                        <span class="font-semibold text-white text-xs">${b.symbol}</span>
                        <span class="${pnlColor} font-bold text-xs">$${b.total_pnl.toFixed(2)}</span>
                    </div>
                    <div class="text-xs text-gray-400 mb-1">
                        ${b.trade_count} trades in 30 days · Avg ${avgPnl >= 0 ? '+' : ''}$${avgPnl.toFixed(2)}
                    </div>
                    ${statusText}
                </div>
            `;
        }).join('');
        
        console.log(`[BLACKLIST] Displayed ${blacklisted.length} blacklisted symbols (mode: ${currentPnlMode})`);
        
    } catch (error) {
        console.error('[BLACKLIST] Error loading blacklist data:', error);
        document.getElementById('pnl-blacklist-list').innerHTML = 
            '<div class="text-center text-gray-500 text-xs py-2">Not available</div>';
    }
}

function updateOpenPositionsList(positions) {
    const listDiv = document.getElementById('pnl-positions-list');
    const countSpan = document.getElementById('pnl-positions-count');
    
    countSpan.textContent = `${positions.length} open`;
    
    if (positions.length === 0) {
        listDiv.innerHTML = '<div class="text-center text-gray-500 text-xs py-4">No open positions</div>';
        return;
    }
    
    listDiv.innerHTML = positions.map(p => {
        const currentPnl = p.current_pnl || 0;
        const currentPnlPct = p.current_pnl_pct || 0;
        const pnlColor = currentPnl >= 0 ? 'text-green-400' : 'text-red-400';
        const bgColor = currentPnl >= 0 ? 'bg-green-900/20 border-green-700' : 'bg-red-900/20 border-red-700';
        const mode = p.mode || currentPnlMode;
        
        return `
            <div class="bg-gray-900 rounded-lg p-3 border ${bgColor}">
                <div class="flex justify-between items-start mb-1">
                    <div class="flex items-center gap-2">
                        <div class="font-semibold text-white text-sm">${p.symbol}</div>
                        <button 
                            onclick="closePositionManually(${p.id}, '${mode}')" 
                            class="text-xs px-2 py-0.5 bg-red-600 hover:bg-red-700 rounded text-white font-semibold transition-all"
                            title="Close position manually">
                            ✕
                        </button>
                    </div>
                    <div class="${pnlColor} font-bold text-sm">${currentPnl >= 0 ? '+' : ''}$${currentPnl.toFixed(2)}</div>
                </div>
                <div class="flex justify-between items-center text-xs">
                    <div class="text-gray-400">
                        Entry: $${(p.entry_price || 0).toFixed(2)} → Current: $${(p.current_price || 0).toFixed(2)} | Qty: ${(p.quantity || 0).toFixed(4)}
                    </div>
                    <div class="${pnlColor}">${currentPnlPct >= 0 ? '+' : ''}${currentPnlPct.toFixed(2)}%</div>
                </div>
            </div>
        `;
    }).join('');
}

async function refreshPnlCard() {
    await loadPnlCard(currentPnlMode);
}

// Global variable to track modal positions filter
let modalPositionsFilter = 'ensemble';
let modalAllPositions = [];

async function viewDetailedPnl() {
    try {
        // Build modal HTML with tabs
        const modalHtml = `
            <!-- Mode Indicator -->
            <div class="mb-4 p-3 rounded-lg ${currentPnlMode === 'live' ? 'bg-red-900/30 border border-red-700' : 'bg-blue-900/30 border border-blue-700'}">
                <div class="flex items-center justify-between">
                    <div class="flex items-center gap-2">
                        <span class="text-lg">${currentPnlMode === 'live' ? '🔴' : '📋'}</span>
                        <div>
                            <div class="font-bold ${currentPnlMode === 'live' ? 'text-red-400' : 'text-blue-400'}">
                                ${currentPnlMode === 'live' ? 'LIVE TRADING MODE' : 'PAPER TRADING MODE'}
                            </div>
                            <div class="text-xs text-gray-400">
                                ${currentPnlMode === 'live' ? 'Real money trades on Kraken' : 'Simulated trades - no real money'}
                            </div>
                        </div>
                    </div>
                    <button onclick="location.reload()" class="px-3 py-1 bg-gray-700 hover:bg-gray-600 rounded text-xs">
                        ↻ Refresh All
                    </button>
                </div>
            </div>
            
            <!-- Tab Navigation -->
            <div class="flex gap-2 mb-4 border-b border-gray-700">
                <button onclick="switchDetailsTab('pnl')" id="tab-btn-pnl" class="px-4 py-2 text-sm font-semibold border-b-2 border-blue-500 text-blue-400">
                    📊 P&L Details
                </button>
                <button onclick="switchDetailsTab('signals')" id="tab-btn-signals" class="px-4 py-2 text-sm font-semibold border-b-2 border-transparent text-gray-400 hover:text-gray-300">
                    🎯 Active Signals
                </button>
                <button onclick="switchDetailsTab('positions')" id="tab-btn-positions" class="px-4 py-2 text-sm font-semibold border-b-2 border-transparent text-gray-400 hover:text-gray-300">
                    📋 All Positions
                </button>
            </div>

            <!-- Tab Content: P&L Details -->
            <div id="tab-content-pnl" class="tab-content-section">
                <div id="pnl-details-content">
                    <div class="text-center py-10 text-gray-400">
                        <div class="text-4xl mb-2">⏳</div>
                        <div>Loading P&L details...</div>
                    </div>
                </div>
            </div>

            <!-- Tab Content: Active Signals -->
            <div id="tab-content-signals" class="tab-content-section" style="display: none;">
                <div class="mb-4">
                    <div class="flex justify-between items-center mb-3 flex-wrap gap-3">
                        <div>
                            <p class="text-sm text-gray-400"><span id="modal-ensemble-count">-</span> new opportunities · Avg score: <span id="modal-ensemble-avg-score">-</span></p>
                            <p class="text-xs text-gray-500">New signals waiting to be acted on (not currently open trades)</p>
                        </div>
                        <div class="flex gap-2 items-center">
                            <select id="modal-ensemble-threshold" onchange="loadModalEnsembleSignals()" class="bg-gray-700 px-3 py-2 rounded text-sm border border-gray-600">
                                <option value="60">60+</option>
                                <option value="70" selected>70+</option>
                                <option value="80">80+</option>
                                <option value="90">90+</option>
                            </select>
                            <button onclick="loadModalEnsembleSignals()" class="px-3 py-2 bg-blue-600 hover:bg-blue-700 rounded text-sm">↻</button>
                        </div>
                    </div>
                </div>
                <div id="modal-ensemble-signals-container" class="max-h-[60vh] overflow-y-auto">
                    <div class="text-center py-10 text-gray-400">
                        <div class="text-4xl mb-2">⏳</div>
                        <div>Loading signals...</div>
                    </div>
                </div>
            </div>

            <!-- Tab Content: All Positions -->
            <div id="tab-content-positions" class="tab-content-section" style="display: none;">
                <div class="mb-4">
                    <div class="flex justify-between items-center mb-3">
                        <div class="flex items-center gap-3">
                            <div class="flex gap-1">
                                <button onclick="filterModalPositions('all')" id="modal-filter-all" class="px-2 py-1 rounded bg-gray-700 hover:bg-gray-600 text-xs" title="All">🗂️ All</button>
                                <button onclick="filterModalPositions('ensemble')" id="modal-filter-ensemble" class="px-2 py-1 rounded bg-purple-700 text-white text-xs" title="Ensemble (Real Trading)">🎯 Ensemble</button>
                                <button onclick="filterModalPositions('strategy')" id="modal-filter-strategy" class="px-2 py-1 rounded bg-gray-700 hover:bg-gray-600 text-xs" title="Strategy (Testing)">🧪 Test</button>
                                <button onclick="filterModalPositions('open')" id="modal-filter-open" class="px-2 py-1 rounded bg-gray-700 hover:bg-gray-600" title="Open">🟢</button>
                                <button onclick="filterModalPositions('closed')" id="modal-filter-closed" class="px-2 py-1 rounded bg-gray-700 hover:bg-gray-600" title="Closed">🔴</button>
                            </div>
                        </div>
                        <button onclick="loadModalPositions()" class="px-3 py-2 bg-blue-600 hover:bg-blue-700 rounded text-sm">↻</button>
                    </div>
                    
                    <!-- Portfolio Type Explanation -->
                    <div class="bg-gray-900 rounded p-3 mb-3 text-xs text-gray-400">
                        <div class="flex items-start gap-2">
                            <span class="text-purple-400 font-bold">🎯 Ensemble:</span>
                            <span>Real trading positions created by weighted consensus of strategies</span>
                        </div>
                        <div class="flex items-start gap-2 mt-1">
                            <span class="text-gray-500 font-bold">🧪 Strategy:</span>
                            <span>Test positions for gathering performance data (learning)</span>
                        </div>
                    </div>
                </div>
                <div id="modal-positions-container" class="max-h-[60vh] overflow-y-auto">
                    <div class="text-center py-10 text-gray-400">
                        <div class="text-4xl mb-2">⏳</div>
                        <div>Loading positions...</div>
                    </div>
                </div>
            </div>
        `;
        
        // Show modal
        if (window.openModal) {
            window.openModal(
                `📊 ${currentPnlMode === 'paper' ? 'Paper' : 'Live'} Trading Dashboard`,
                modalHtml
            );
            
            // Load initial data for P&L Details tab (default)
            setTimeout(() => {
                loadModalPnlDetails();
            }, 100);
        }
        
    } catch (error) {
        console.error('Error opening detailed modal:', error);
        if (window.showNotification) {
            window.showNotification('Failed to open details', 'error');
        }
    }
}

// Switch between tabs in the modal
function switchDetailsTab(tabName) {
    // Hide all tab contents
    document.querySelectorAll('.tab-content-section').forEach(section => {
        section.style.display = 'none';
    });
    
    // Remove active class from all tab buttons
    document.querySelectorAll('[id^="tab-btn-"]').forEach(btn => {
        btn.classList.remove('border-blue-500', 'text-blue-400');
        btn.classList.add('border-transparent', 'text-gray-400');
    });
    
    // Show selected tab content
    const selectedContent = document.getElementById(`tab-content-${tabName}`);
    if (selectedContent) {
        selectedContent.style.display = 'block';
    }
    
    // Activate selected tab button
    const selectedBtn = document.getElementById(`tab-btn-${tabName}`);
    if (selectedBtn) {
        selectedBtn.classList.remove('border-transparent', 'text-gray-400');
        selectedBtn.classList.add('border-blue-500', 'text-blue-400');
    }
    
    // Load data for the selected tab if not already loaded
    if (tabName === 'signals') {
        const container = document.getElementById('modal-ensemble-signals-container');
        if (container && container.innerHTML.includes('Loading signals')) {
            loadModalEnsembleSignals();
        }
    } else if (tabName === 'positions') {
        const container = document.getElementById('modal-positions-container');
        if (container && container.innerHTML.includes('Loading positions')) {
            loadModalPositions();
        }
    } else if (tabName === 'pnl') {
        const container = document.getElementById('pnl-details-content');
        if (container && container.innerHTML.includes('Loading P&L')) {
            loadModalPnlDetails();
        }
    }
}

// Load Active Signals for modal
async function loadModalEnsembleSignals() {
    const container = document.getElementById('modal-ensemble-signals-container');
    if (!container) return;
    
    try {
        const minScore = document.getElementById('modal-ensemble-threshold')?.value || 70;
        const response = await fetch(
            `http://${window.API_HOST}:8015/signals/ensemble?min_weighted_score=${minScore}&period_days=14&limit=15`
        );
        const data = await response.json();
        
        if (data.status === 'success') {
            const signals = data.ensemble_signals || [];
            const totalActive = data.total_active_signals || 0;
            
            // Update stats
            document.getElementById('modal-ensemble-count').textContent = signals.length;
            const avgScore = signals.length > 0 
                ? (signals.reduce((sum, s) => sum + s.weighted_score, 0) / signals.length).toFixed(1) : '-';
            document.getElementById('modal-ensemble-avg-score').textContent = avgScore;
            
            // Show helpful message if no signals
            if (signals.length === 0 && totalActive === 0) {
                container.innerHTML = `
                    <div class="text-center py-10 text-gray-400 bg-gray-800 rounded p-6">
                        <div class="text-4xl mb-2">⏰</div>
                        <div class="mb-2">No active signals</div>
                        <div class="text-xs text-gray-500">Signals are generated every 5 minutes</div>
                    </div>
                `;
            } else if (signals.length === 0 && totalActive > 0) {
                container.innerHTML = `
                    <div class="text-center py-10 text-gray-400 bg-gray-800 rounded p-6">
                        <div class="text-4xl mb-2">🎯</div>
                        <div class="mb-2">No signals above threshold (${minScore})</div>
                        <div class="text-xs text-gray-500">${totalActive} active signals exist with lower scores</div>
                        <div class="text-xs text-blue-400 mt-2 cursor-pointer hover:underline" onclick="document.getElementById('modal-ensemble-threshold').value='60'; loadModalEnsembleSignals();">
                            Try lowering threshold to 60
                        </div>
                    </div>
                `;
            } else {
                // Use component renderer if available
                if (window.renderSignalsList) {
                    container.innerHTML = window.renderSignalsList(signals);
                    // Restore collapsed states after rendering
                    setTimeout(() => {
                        if (window.restoreSignalStates) {
                            window.restoreSignalStates();
                        }
                    }, 50);
                } else {
                    // Fallback rendering
                    container.innerHTML = signals.map(s => `
                        <div class="bg-gray-800 rounded p-3 mb-2">
                            <div class="flex justify-between items-center">
                                <div class="font-bold text-lg">${s.symbol}</div>
                                <div class="text-sm text-blue-400">Score: ${s.weighted_score.toFixed(1)}</div>
                            </div>
                        </div>
                    `).join('');
                }
            }
        }
    } catch (error) {
        console.error('Error loading modal ensemble signals:', error);
        container.innerHTML = `
            <div class="text-center py-10 text-red-400 bg-gray-800 rounded p-6">
                <div class="text-4xl mb-2">⚠️</div>
                <div>Error loading signals</div>
                <div class="text-xs text-gray-500 mt-2">${error.message}</div>
            </div>
        `;
    }
}

// Load All Positions for modal
async function loadModalPositions() {
    try {
        console.log(`[MODAL] Loading positions for mode: ${currentPnlMode}, filter: ${modalPositionsFilter}`);
        
        // Build API URL with position_type filter
        let url = `http://${window.API_HOST}:8016/positions?mode=${currentPnlMode}`;
        
        // Add position_type filter based on current filter to get correct dataset
        if (modalPositionsFilter === 'ensemble' || modalPositionsFilter === 'strategy') {
            url += `&position_type=${modalPositionsFilter}`;
        }
        
        console.log(`[MODAL] Fetching from URL: ${url}`);
        const response = await fetch(url);
        const data = await response.json();
        console.log(`[MODAL] Received ${data.positions?.length || 0} positions for mode: ${data.mode}`);
        
        modalAllPositions = data.positions || [];
        
        // Apply current filter
        filterModalPositions(modalPositionsFilter);
        
    } catch (error) {
        console.error('Error loading modal positions:', error);
        const container = document.getElementById('modal-positions-container');
        if (container) {
            container.innerHTML = `
                <div class="text-center py-10 text-red-400 bg-gray-800 rounded p-6">
                    <div class="text-4xl mb-2">⚠️</div>
                    <div>Error loading positions</div>
                    <div class="text-xs text-gray-500 mt-2">${error.message}</div>
                </div>
            `;
        }
    }
}

// Filter positions in modal
async function filterModalPositions(filter) {
    const previousFilter = modalPositionsFilter;
    modalPositionsFilter = filter;
    
    // Update filter button styles
    document.querySelectorAll('[id^="modal-filter-"]').forEach(btn => {
        const f = btn.id.replace('modal-filter-', '');
        if (f === filter) {
            if (f === 'ensemble') {
                btn.className = 'px-2 py-1 rounded bg-purple-700 text-white text-xs';
            } else if (f === 'strategy') {
                btn.className = 'px-2 py-1 rounded bg-blue-700 text-white text-xs';
            } else {
                btn.className = 'px-2 py-1 rounded bg-blue-700 text-white';
            }
        } else {
            if (f === 'ensemble' || f === 'strategy') {
                btn.className = 'px-2 py-1 rounded bg-gray-700 hover:bg-gray-600 text-xs';
            } else {
                btn.className = 'px-2 py-1 rounded bg-gray-700 hover:bg-gray-600';
            }
        }
    });
    
    // If switching between ensemble/strategy/all, reload data with correct position_type filter
    const needsReload = (previousFilter === 'ensemble' || previousFilter === 'strategy') !== 
                        (filter === 'ensemble' || filter === 'strategy');
    
    if (needsReload || (filter === 'ensemble' && previousFilter !== 'ensemble') || 
        (filter === 'strategy' && previousFilter !== 'strategy')) {
        // Reload positions with the new filter
        await loadModalPositions();
        return; // loadModalPositions will call filterModalPositions again
    }
    
    // Filter positions from already loaded data
    let filtered = modalAllPositions;
    if (filter === 'ensemble') {
        // Real trading positions (open only by default)
        filtered = modalAllPositions.filter(p => p.position_type === 'ensemble' && p.status === 'open');
    } else if (filter === 'strategy') {
        // Test/learning positions (open only by default)
        filtered = modalAllPositions.filter(p => p.position_type === 'strategy' && p.status === 'open');
    } else if (filter === 'open') {
        filtered = modalAllPositions.filter(p => p.status === 'open');
    } else if (filter === 'closed') {
        filtered = modalAllPositions.filter(p => p.status === 'closed');
    }
    
    // Display positions
    displayModalPositions(filtered);
}

// Display positions in modal
function displayModalPositions(positions) {
    const container = document.getElementById('modal-positions-container');
    if (!container) return;
    
    // Use component renderer if available
    if (window.renderPositionsList) {
        container.innerHTML = window.renderPositionsList(positions);
        // Restore collapsed states after rendering
        setTimeout(() => {
            if (window.restorePositionStates) {
                window.restorePositionStates();
            }
        }, 50);
    } else {
        // Fallback rendering
        if (positions.length === 0) {
            container.innerHTML = `
                <div class="text-center py-10 text-gray-400 bg-gray-800 rounded p-6">
                    <div class="text-4xl mb-2">📭</div>
                    <div>No positions found</div>
                </div>
            `;
        } else {
            container.innerHTML = positions.map(p => `
                <div class="bg-gray-800 rounded p-3 mb-2">
                    <div class="flex justify-between items-center">
                        <div class="font-bold text-lg">${p.symbol}</div>
                        <div class="text-sm ${p.status === 'open' ? 'text-green-400' : 'text-gray-400'}">${p.status}</div>
                    </div>
                    <div class="text-xs text-gray-400 mt-1">
                        Entry: $${(p.entry_price || 0).toFixed(2)} | 
                        ${p.status === 'open' ? `Current P&L: $${(p.current_pnl || 0).toFixed(2)}` : `Exit: $${(p.exit_price || 0).toFixed(2)}`}
                    </div>
                </div>
            `).join('');
        }
    }
}

// Load P&L Details (original chart and table)
async function loadModalPnlDetails() {
    try {
        console.log(`[MODAL] Loading P&L details for mode: ${currentPnlMode}`);
        
        // Fetch recent closed positions (ensemble only - actual portfolio trades)
        const url = `http://${window.API_HOST}:8016/positions?mode=${currentPnlMode}&status=closed&position_type=ensemble`;
        console.log(`[MODAL] Fetching P&L from URL: ${url}`);
        const response = await fetch(url);
        const data = await response.json();
        console.log(`[MODAL] Received ${data.positions?.length || 0} closed positions for mode: ${data.mode}`);
        const positions = data.positions || [];
        
        // Sort by exit time for cumulative P&L calculation (oldest first)
        const sortedPositions = [...positions].sort((a, b) => new Date(a.exit_time) - new Date(b.exit_time));
        
        // Calculate cumulative P&L for chart (include fees for accurate net P&L)
        let cumulativePnl = 0;
        const chartData = sortedPositions.map((p, idx) => {
            const tradePnl = (p.realized_pnl || p.current_pnl || 0);
            const fees = (p.entry_fee || 0) + (p.exit_fee || 0);
            cumulativePnl += (tradePnl - fees);
            return {
                tradeNumber: idx + 1,
                pnl: cumulativePnl,
                tradePnl: tradePnl,
                fees: fees,
                netPnl: tradePnl - fees,
                time: new Date(p.exit_time).toLocaleString()
            };
        });
        
        // Sort by exit time, most recent first for table display
        positions.sort((a, b) => new Date(b.exit_time) - new Date(a.exit_time));
        
        // Show all trades (no limit)
        const recentTrades = positions;
        
        // Create unique ID for chart canvas
        const chartId = `pnl-chart-${Date.now()}`;
        
        // Build HTML with chart and table
        const contentHtml = `
            <div class="mb-4">
                <div class="bg-gray-900 rounded-lg p-4 border border-gray-700">
                    <h4 class="text-sm font-semibold text-gray-400 mb-3">📈 Cumulative Net P&L (After Fees)</h4>
                    <div style="height: 200px; max-height: 200px;">
                        <canvas id="${chartId}"></canvas>
                    </div>
                </div>
            </div>
            
            <div class="mb-2 flex justify-between items-center">
                <h4 class="text-sm font-semibold text-gray-400">Trade History (All Ensemble Trades)</h4>
                <span class="text-xs text-gray-500">Showing all ${positions.length} closed positions</span>
            </div>
            
            <div class="max-h-[40vh] overflow-y-auto">
                <table class="w-full text-xs">
                    <thead class="sticky top-0 bg-gray-800">
                        <tr class="text-left border-b border-gray-700">
                            <th class="p-2">Symbol</th>
                            <th class="p-2">Entry</th>
                            <th class="p-2">Exit</th>
                            <th class="p-2">Qty</th>
                            <th class="p-2">Fees</th>
                            <th class="p-2">P&L</th>
                            <th class="p-2">P&L%</th>
                            <th class="p-2">Duration</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${recentTrades.map(t => {
                            const pnl = t.realized_pnl || t.current_pnl || 0;
                            const pnlPct = t.realized_pnl_pct || t.current_pnl_pct || 0;
                            const pnlColor = pnl >= 0 ? 'text-green-400' : 'text-red-400';
                            const rowBg = pnl >= 0 ? 'bg-green-900/10 hover:bg-green-900/20' : 'bg-red-900/10 hover:bg-red-900/20';
                            
                            const entryFee = t.entry_fee || 0;
                            const exitFee = t.exit_fee || 0;
                            const totalFees = entryFee + exitFee;
                            
                            const entryTime = new Date(t.entry_time);
                            const exitTime = new Date(t.exit_time);
                            const duration = Math.round((exitTime - entryTime) / 60000); // minutes
                            
                            // Format prices with appropriate precision
                            const formatPrice = (price) => {
                                if (price < 1) return price.toFixed(4);
                                if (price < 10) return price.toFixed(3);
                                return price.toFixed(2);
                            };
                            
                            return `
                                <tr class="border-b border-gray-800 ${rowBg}">
                                    <td class="p-2 font-semibold">${t.symbol}</td>
                                    <td class="p-2">$${formatPrice(t.entry_price || 0)}</td>
                                    <td class="p-2">$${formatPrice(t.exit_price || 0)}</td>
                                    <td class="p-2">${(t.quantity || 0).toFixed(4)}</td>
                                    <td class="p-2 text-red-400">-$${totalFees.toFixed(2)}</td>
                                    <td class="p-2 ${pnlColor} font-bold">${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}</td>
                                    <td class="p-2 ${pnlColor}">${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(2)}%</td>
                                    <td class="p-2 text-gray-400">${duration}m</td>
                                </tr>
                            `;
                        }).join('')}
                    </tbody>
                </table>
                ${recentTrades.length === 0 ? '<div class="text-center text-gray-500 py-8">No trades yet</div>' : ''}
            </div>
            
            <div class="mt-4 pt-4 border-t border-gray-700 grid grid-cols-4 gap-4 text-center">
                <div>
                    <div class="text-xs text-gray-500">Total Trades</div>
                    <div class="text-lg font-bold">${positions.length}</div>
                </div>
                <div>
                    <div class="text-xs text-gray-500">Total Fees Paid</div>
                    <div class="text-lg font-bold text-red-400">$${positions.reduce((sum, p) => sum + (p.entry_fee || 0) + (p.exit_fee || 0), 0).toFixed(2)}</div>
                </div>
                <div>
                    <div class="text-xs text-gray-500">Wins / Losses</div>
                    <div class="text-lg font-bold">
                        <span class="text-green-400">${positions.filter(p => (p.realized_pnl || p.current_pnl || 0) > 0).length}</span> / 
                        <span class="text-red-400">${positions.filter(p => (p.realized_pnl || p.current_pnl || 0) <= 0).length}</span>
                    </div>
                </div>
                <div>
                    <div class="text-xs text-gray-500">Net P&L</div>
                    <div class="text-lg font-bold ${positions.reduce((sum, p) => sum + (p.realized_pnl || p.current_pnl || 0) - (p.entry_fee || 0) - (p.exit_fee || 0), 0) >= 0 ? 'text-green-400' : 'text-red-400'}">
                        $${positions.reduce((sum, p) => sum + (p.realized_pnl || p.current_pnl || 0) - (p.entry_fee || 0) - (p.exit_fee || 0), 0).toFixed(2)}
                    </div>
                </div>
            </div>
        `;
        
        // Update the P&L Details tab content
        const container = document.getElementById('pnl-details-content');
        if (container) {
            container.innerHTML = contentHtml;
            
            // Wait for DOM to update, then create chart
            setTimeout(() => {
                const ctx = document.getElementById(chartId);
                if (ctx && window.Chart) {
                    // Destroy previous chart instance if exists
                    if (pnlChartInstance) {
                        pnlChartInstance.destroy();
                        pnlChartInstance = null;
                    }
                    
                    // Create new chart with fixed animation settings
                    pnlChartInstance = new Chart(ctx, {
                        type: 'line',
                        data: {
                            labels: chartData.map(d => d.tradeNumber),
                            datasets: [{
                                label: 'Cumulative P&L',
                                data: chartData.map(d => d.pnl),
                                borderWidth: 2,
                                fill: true,
                                tension: 0.3,
                                pointRadius: 2,
                                pointHoverRadius: 4,
                                segment: {
                                    borderColor: (ctx) => {
                                        // Color segment based on whether P&L is positive or negative
                                        const value = ctx.p1.parsed.y;
                                        return value >= 0 ? 'rgb(74, 222, 128)' : 'rgb(248, 113, 113)';
                                    },
                                    backgroundColor: (ctx) => {
                                        const value = ctx.p1.parsed.y;
                                        return value >= 0 ? 'rgba(74, 222, 128, 0.1)' : 'rgba(248, 113, 113, 0.1)';
                                    }
                                },
                                borderColor: 'rgb(74, 222, 128)',
                                backgroundColor: 'rgba(74, 222, 128, 0.1)',
                                pointBackgroundColor: (ctx) => {
                                    const value = ctx.parsed.y;
                                    return value >= 0 ? 'rgb(74, 222, 128)' : 'rgb(248, 113, 113)';
                                },
                                pointBorderColor: (ctx) => {
                                    const value = ctx.parsed.y;
                                    return value >= 0 ? 'rgb(74, 222, 128)' : 'rgb(248, 113, 113)';
                                }
                            }]
                        },
                        options: {
                            responsive: true,
                            maintainAspectRatio: false,
                            animation: {
                                duration: 750,
                                easing: 'easeInOutQuart',
                                loop: false,
                                animateRotate: false,
                                animateScale: false
                            },
                            plugins: {
                                legend: {
                                    display: false
                                },
                                tooltip: {
                                    enabled: true,
                                    mode: 'index',
                                    intersect: false,
                                    callbacks: {
                                        title: (items) => `Trade #${items[0].label}`,
                                        label: (item) => {
                                            const dataPoint = chartData[item.dataIndex];
                                            return [
                                                `Trade P&L: $${dataPoint.tradePnl.toFixed(2)}`,
                                                `Fees: -$${dataPoint.fees.toFixed(2)}`,
                                                `Net: $${dataPoint.netPnl.toFixed(2)}`,
                                                `Cumulative: $${dataPoint.pnl.toFixed(2)}`
                                            ];
                                        }
                                    }
                                }
                            },
                            interaction: {
                                mode: 'nearest',
                                axis: 'x',
                                intersect: false
                            },
                            scales: {
                                y: {
                                    beginAtZero: true,
                                    ticks: {
                                        callback: (value) => '$' + value.toFixed(2),
                                        color: 'rgb(156, 163, 175)',
                                        maxTicksLimit: 8
                                    },
                                    grid: {
                                        color: 'rgba(75, 85, 99, 0.3)',
                                        drawBorder: false
                                    }
                                },
                                x: {
                                    title: {
                                        display: true,
                                        text: 'Trade Number',
                                        color: 'rgb(156, 163, 175)'
                                    },
                                    ticks: {
                                        color: 'rgb(156, 163, 175)',
                                        maxTicksLimit: 20,
                                        autoSkip: true
                                    },
                                    grid: {
                                        color: 'rgba(75, 85, 99, 0.3)',
                                        drawBorder: false
                                    }
                                }
                            }
                        }
                    });
                }
            }, 100);
        }
        
    } catch (error) {
        console.error('Error loading P&L details:', error);
        const container = document.getElementById('pnl-details-content');
        if (container) {
            container.innerHTML = `
                <div class="text-center py-10 text-red-400 bg-gray-800 rounded p-6">
                    <div class="text-4xl mb-2">⚠️</div>
                    <div>Error loading P&L details</div>
                    <div class="text-xs text-gray-500 mt-2">${error.message}</div>
                </div>
            `;
        }
    }
}

// Load system activity status
async function loadSystemActivity() {
    try {
        const response = await fetch(`http://${window.API_HOST}:8021/activity`);
        const data = await response.json();
        
        if (data.status === 'success') {
            // Format time ago helper
            const formatTimeAgo = (seconds) => {
                if (seconds === null || seconds === undefined) return 'Never';
                if (seconds < 60) return `${seconds}s ago`;
                if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
                if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
                return `${Math.floor(seconds / 86400)}d ago`;
            };
            
            // Update candles
            document.getElementById('activity-last-candles').textContent = 
                formatTimeAgo(data.candles.seconds_ago);
            
            // Update signals
            document.getElementById('activity-last-signal').textContent = 
                formatTimeAgo(data.signals.seconds_ago);
            document.getElementById('activity-active-signals').textContent = 
                data.signals.active_count || 0;
            
            // Update trades based on current mode
            const tradeData = currentPnlMode === 'paper' ? data.trades.paper : data.trades.live;
            document.getElementById('activity-last-trade').textContent = 
                formatTimeAgo(tradeData.ensemble.seconds_ago || tradeData.strategy.seconds_ago);
            
            // Update ensemble and strategy trade counts separately
            document.getElementById('activity-ensemble-trades').textContent = 
                tradeData.ensemble.today_count || 0;
            document.getElementById('activity-strategy-trades').textContent = 
                tradeData.strategy.today_count || 0;
            
            // Update workers
            const workerText = `${data.workers.celery_workers}W + ${data.workers.celery_beat ? '1B' : '0B'}`;
            document.getElementById('activity-workers').textContent = workerText;
            
            // Update status indicator
            const statusEl = document.getElementById('system-activity-status');
            if (data.workers.status === 'healthy') {
                statusEl.textContent = '● Online';
                statusEl.className = 'text-xs text-green-400';
            } else {
                statusEl.textContent = '● Degraded';
                statusEl.className = 'text-xs text-yellow-400';
            }
            
            // Highlight if things are stale (>5 minutes)
            if (data.candles.seconds_ago > 300) {
                document.getElementById('activity-last-candles').className = 'text-red-400 font-semibold';
            } else {
                document.getElementById('activity-last-candles').className = 'text-white font-semibold';
            }
            
            if (data.signals.seconds_ago > 300) {
                document.getElementById('activity-last-signal').className = 'text-red-400 font-semibold';
            } else {
                document.getElementById('activity-last-signal').className = 'text-white font-semibold';
            }
        }
    } catch (error) {
        console.error('Error loading system activity:', error);
        document.getElementById('system-activity-status').textContent = '● Error';
        document.getElementById('system-activity-status').className = 'text-xs text-red-400';
    }
}

// Auto-refresh every 30 seconds  
setInterval(() => {
    if (!isLoading) {
        refreshPnlCard();
        loadSystemActivity();
    }
}, 30000);

// Initial load of activity on page load
setTimeout(() => loadSystemActivity(), 1000);

// Close position manually
async function closePositionManually(positionId, mode) {
    // Use modal instead of confirm dialog
    const modalContent = `
        <div style="padding: 20px; text-align: center;">
            <p style="font-size: 16px; margin-bottom: 30px;">
                Are you sure you want to close position #${positionId}?
            </p>
            <div style="display: flex; gap: 10px; justify-content: center;">
                <button onclick="executeClosePosition(${positionId}, '${mode}')" 
                        class="btn btn-danger" 
                        style="padding: 10px 30px; font-size: 14px;">
                    Confirm Close
                </button>
                <button onclick="window.closeModal()" 
                        class="btn btn-secondary" 
                        style="padding: 10px 30px; font-size: 14px;">
                    Cancel
                </button>
            </div>
        </div>
    `;
    
    if (window.openModal) {
        window.openModal('Close Position', modalContent);
    }
}

async function executeClosePosition(positionId, mode) {
    // Close the modal first
    if (window.closeModal) {
        window.closeModal();
    }
    
    try {
        const response = await fetch(`http://${window.API_HOST}:8017/close`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                position_id: positionId,
                mode: mode,
                reason: 'manual_close'
            })
        });
        
        if (response.ok) {
            const result = await response.json();
            const posClose = result.position_close || {};
            const pnl = posClose.pnl || 0;
            const pnlPct = posClose.pnl_pct || 0;
            
            if (window.showNotification) {
                window.showNotification(
                    `Position #${positionId} closed. P&L: ${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)} (${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(2)}%)`,
                    pnl >= 0 ? 'success' : 'info'
                );
            }
            
            // Refresh the P&L card to show updated positions
            await refreshPnlCard();
        } else {
            const error = await response.text();
            throw new Error(error);
        }
    } catch (error) {
        console.error('Error closing position:', error);
        if (window.showNotification) {
            window.showNotification(`Error closing position: ${error.message}`, 'error');
        }
    }
}

// Make modal functions globally accessible
window.switchDetailsTab = switchDetailsTab;
window.loadModalEnsembleSignals = loadModalEnsembleSignals;
window.loadModalPositions = loadModalPositions;
window.filterModalPositions = filterModalPositions;
window.displayModalPositions = displayModalPositions;
window.loadModalPnlDetails = loadModalPnlDetails;
window.closePositionManually = closePositionManually;
window.executeClosePosition = executeClosePosition;

// ─── Force Refresh ────────────────────────────────────────────────────────────
async function forceRefreshSymbol(symbol) {
    const btn = document.getElementById('force-refresh-btn');
    const log = document.getElementById('cycle-log');
    const progress = document.getElementById('cycle-progress');
    const bar = document.getElementById('cycle-progress-bar');

    if (!symbol) symbol = 'BTC';
    btn.disabled = true;
    btn.textContent = `⏳ Refreshing ${symbol}…`;
    log.classList.remove('hidden');
    progress.classList.remove('hidden');
    log.innerHTML = '';
    bar.style.width = '10%';

    const addLog = (msg) => {
        const ts = new Date().toLocaleTimeString();
        log.innerHTML += `<div>[${ts}] ${msg}</div>`;
        log.scrollTop = log.scrollHeight;
    };

    try {
        addLog(`Triggering full refresh for ${symbol}…`);
        bar.style.width = '30%';

        const resp = await fetch(`http://${window.API_HOST}:8016/force-refresh/${symbol}`, {
            method: 'POST'
        });
        bar.style.width = '70%';

        if (!resp.ok) {
            const err = await resp.text();
            addLog(`❌ Error: ${err.slice(0, 120)}`);
            return;
        }

        const data = await resp.json();
        bar.style.width = '90%';

        for (const step of (data.steps || [])) {
            const icon = step.status === 'ok' ? '✅' : '⚠️';
            const detail = step.assigned !== undefined ? ` (${step.assigned} strategies)` : '';
            addLog(`${icon} ${step.step}${detail}`);
        }

        bar.style.width = '100%';
        addLog(`Done — refreshing P&L card…`);
        setTimeout(() => refreshPnlCard(), 1500);
    } catch (e) {
        addLog(`❌ ${e.message}`);
    } finally {
        btn.disabled = false;
        btn.textContent = `⚡ Force Refresh`;
        setTimeout(() => { bar.style.width = '0%'; progress.classList.add('hidden'); }, 3000);
    }
}

window.forceRefreshSymbol = forceRefreshSymbol;
