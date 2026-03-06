// Ensemble Backtest Module
// Handles all ensemble backtest functionality

class EnsembleManager {
    constructor() {
        this.bestOptimizedParams = null;
    }

    /**
     * Initialize ensemble modal when opened
     */
    async initModal() {
        await this.loadSymbols();
        this.setDefaultDates();
        this.setupFormHandler();
    }

    /**
     * Load symbols into dropdown
     */
    async loadSymbols() {
        const select = document.getElementById('eb-symbol');
        if (!select || select.options.length > 1) return;

        try {
            const data = await api.getSymbols();
            if (data.symbols && data.symbols.length > 0) {
                select.innerHTML = data.symbols.map(s => 
                    `<option value="${s.symbol}">${s.name} (${s.symbol})</option>`
                ).join('');

                // Load optimized params for first symbol
                await this.loadOptimizedParams(data.symbols[0].symbol);
                
                // Setup change handler
                select.onchange = () => this.loadOptimizedParams(select.value);
            }
        } catch (error) {
            console.error('Error loading symbols:', error);
            select.innerHTML = '<option value="">Error loading symbols</option>';
        }
    }

    /**
     * Set default date range (last 30 days)
     */
    setDefaultDates() {
        const endDate = new Date();
        const startDate = new Date();
        startDate.setDate(startDate.getDate() - 30);

        const endInput = document.getElementById('eb-end-date');
        const startInput = document.getElementById('eb-start-date');
        
        if (endInput) endInput.value = endDate.toISOString().split('T')[0];
        if (startInput) startInput.value = startDate.toISOString().split('T')[0];
    }

    /**
     * Load optimized parameters for symbol
     */
    async loadOptimizedParams(symbol) {
        try {
            const data = await api.getOptimizedParams(symbol);
            
            if (data && data.symbol && !data.message) {
                // Apply to form
                document.getElementById('eb-min-score').value = data.min_weighted_score;
                document.getElementById('eb-lookback').value = data.lookback_days;
                document.getElementById('eb-cluster-window').value = data.signal_cluster_window_minutes;
                document.getElementById('eb-position-size').value = data.position_size_pct;
                document.getElementById('eb-stop-loss').value = data.stop_loss_pct;
                document.getElementById('eb-take-profit').value = data.take_profit_pct;
                
                const date = formatDate(data.optimized_at);
                showToast(`Loaded optimized parameters for ${symbol} (${date})`, 'success');
            }
        } catch (error) {
            console.error('Error loading optimized params:', error);
        }
    }

    /**
     * Setup form submission handler
     */
    setupFormHandler() {
        const form = document.getElementById('ensemble-backtest-form');
        if (!form || form.dataset.handlerSet) return;
        
        form.dataset.handlerSet = 'true';
        form.addEventListener('submit', (e) => this.runBacktest(e));
    }

    /**
     * Run ensemble backtest
     */
    async runBacktest(e) {
        e.preventDefault();
        
        const params = {
            symbol: document.getElementById('eb-symbol').value,
            start_date: document.getElementById('eb-start-date').value,
            end_date: document.getElementById('eb-end-date').value,
            initial_capital: parseFloat(document.getElementById('eb-capital').value),
            min_weighted_score: parseFloat(document.getElementById('eb-min-score').value),
            lookback_days: parseInt(document.getElementById('eb-lookback').value),
            signal_cluster_window_minutes: parseInt(document.getElementById('eb-cluster-window').value),
            position_size_pct: parseFloat(document.getElementById('eb-position-size').value),
            stop_loss_pct: parseFloat(document.getElementById('eb-stop-loss').value),
            take_profit_pct: parseFloat(document.getElementById('eb-take-profit').value)
        };

        this.showProgress();
        
        try {
            const result = await api.runEnsembleBacktest(params);
            this.displayResults(result);
            showToast('Backtest completed!', 'success');
        } catch (error) {
            console.error('Backtest error:', error);
            showToast(`Backtest failed: ${error.message}`, 'error');
            this.hideProgress();
        }
    }

    /**
     * Show/hide progress indicators
     */
    showProgress() {
        document.getElementById('eb-progress')?.classList.remove('hidden');
        document.getElementById('eb-results')?.classList.add('hidden');
    }

    hideProgress() {
        document.getElementById('eb-progress')?.classList.add('hidden');
    }

    /**
     * Display backtest results
     */
    displayResults(result) {
        this.hideProgress();
        document.getElementById('eb-results')?.classList.remove('hidden');

        // Update metrics
        const returnColor = result.total_return_pct >= 0 ? 'text-green-400' : 'text-red-400';
        document.getElementById('eb-result-return').innerHTML = `<span class="${returnColor}">${formatPercent(result.total_return_pct)}</span>`;
        document.getElementById('eb-result-winrate').textContent = formatPercent(result.win_rate * 100, 1, false);
        document.getElementById('eb-result-trades').textContent = result.total_trades;
        document.getElementById('eb-result-sharpe').textContent = result.sharpe_ratio !== null ? result.sharpe_ratio.toFixed(2) : 'N/A';
        document.getElementById('eb-result-drawdown').textContent = formatPercent(result.max_drawdown_pct);

        // Additional stats
        const buyHoldColor = result.buy_hold_return_pct >= 0 ? 'text-green-400' : 'text-red-400';
        document.getElementById('eb-result-buyhold').innerHTML = `<span class="${buyHoldColor}">${formatPercent(result.buy_hold_return_pct)}</span>`;
        document.getElementById('eb-result-signals').textContent = `${result.signals_acted_on} / ${result.total_signals_considered}`;
        document.getElementById('eb-result-strategies').textContent = result.unique_strategies_used;

        // Trade log
        this.renderTradeLog(result.trades);
    }

    /**
     * Render trade log table
     */
    renderTradeLog(trades) {
        const table = document.getElementById('eb-result-trades-table');
        if (!table) return;

        if (!trades || trades.length === 0) {
            table.innerHTML = '<tr><td colspan="7" class="text-center py-4 text-gray-400">No trades executed</td></tr>';
            return;
        }

        const recentTrades = trades.slice(-10).reverse();
        table.innerHTML = recentTrades.map(trade => {
            const pnlColor = getPnLColor(trade.pnl_pct);
            const sideColor = trade.side === 'buy' ? 'text-green-400' : 'text-red-400';
            const sideBadge = trade.side.toUpperCase();

            return `
                <tr class="border-b border-gray-700 hover:bg-gray-750">
                    <td class="py-2 px-2 text-xs">${formatDateTime(trade.entry_time)}</td>
                    <td class="py-2 px-2 text-xs">${formatDateTime(trade.exit_time)}</td>
                    <td class="py-2 px-2 text-center"><span class="${sideColor} font-semibold text-xs">${sideBadge}</span></td>
                    <td class="py-2 px-2 text-right">${formatCurrency(trade.entry_price)}</td>
                    <td class="py-2 px-2 text-right">${formatCurrency(trade.exit_price)}</td>
                    <td class="py-2 px-2 text-right ${pnlColor} font-semibold">${formatPercent(trade.pnl_pct)}</td>
                    <td class="py-2 px-2 text-xs text-gray-400">${trade.close_reason}</td>
                </tr>
            `;
        }).join('');
    }

    /**
     * Optimize parameters for current symbol
     */
    async optimizeParameters() {
        showToast('Parameter optimization starting... This will take a few minutes.', 'info');
        // Implementation would go here - keeping existing logic
        // For now, point to window function
        if (window.optimizeEnsembleParameters) {
            window.optimizeEnsembleParameters();
        }
    }

    /**
     * Run full optimization on all symbols
     */
    async runFullOptimization() {
        if (!confirm('This will optimize ALL active symbols with 1,944 combinations each. This takes 30-45 minutes. Continue?')) {
            return;
        }

        try {
            document.getElementById('eb-full-optimize-progress')?.classList.remove('hidden');
            
            const data = await api.triggerOptimization();
            document.getElementById('eb-full-optimize-task-id').textContent = `Task ID: ${data.task_id}`;
            
            showToast('✅ Full optimization started! Check status in 30-45 minutes.', 'success');
            
            setTimeout(() => {
                document.getElementById('eb-full-optimize-progress')?.classList.add('hidden');
            }, 5000);
        } catch (error) {
            console.error('Optimization trigger error:', error);
            showToast(`❌ Error: ${error.message}`, 'error');
            document.getElementById('eb-full-optimize-progress')?.classList.add('hidden');
        }
    }

    /**
     * Show optimization status
     */
    async showStatus() {
        document.getElementById('eb-results')?.classList.add('hidden');
        document.getElementById('eb-optimize-results')?.classList.add('hidden');
        document.getElementById('eb-optimization-status')?.classList.remove('hidden');
        
        await this.refreshStatus();
    }

    /**
     * Refresh optimization status
     */
    async refreshStatus() {
        try {
            const data = await api.getOptimizationStatus();
            const contentEl = document.getElementById('eb-status-content');
            
            if (!data.summary || data.summary.total_symbols === 0) {
                contentEl.innerHTML = getEmptyState(
                    'No optimization runs yet. Click "⚡ Run Now (All)" to start.',
                    '📊'
                );
                return;
            }

            // Render status (simplified version)
            const summary = data.summary;
            contentEl.innerHTML = `
                <div class="bg-gradient-to-br from-blue-900 to-blue-800 border border-blue-700 rounded-lg p-4">
                    <div class="grid grid-cols-4 gap-4 text-center">
                        <div>
                            <div class="text-xs text-blue-200 mb-1">Last Run</div>
                            <div class="font-bold text-white">${formatDate(summary.last_run)}</div>
                        </div>
                        <div>
                            <div class="text-xs text-blue-200 mb-1">Symbols</div>
                            <div class="font-bold text-2xl text-white">${summary.total_symbols}</div>
                        </div>
                        <div>
                            <div class="text-xs text-blue-200 mb-1">Avg Return</div>
                            <div class="font-bold text-xl ${getPnLColor(summary.avg_return)}">${formatPercent(summary.avg_return || 0)}</div>
                        </div>
                        <div>
                            <div class="text-xs text-blue-200 mb-1">Total Tests</div>
                            <div class="font-bold text-xl text-white">${formatCompact(summary.total_tests || 0)}</div>
                        </div>
                    </div>
                </div>
            `;
        } catch (error) {
            console.error('Error loading status:', error);
            showToast('Error loading optimization status', 'error');
        }
    }

    /**
     * Apply optimized parameters to form
     */
    applyOptimizedParameters() {
        if (!this.bestOptimizedParams) {
            showToast('No optimized parameters available', 'error');
            return;
        }

        const p = this.bestOptimizedParams;
        document.getElementById('eb-min-score').value = p.min_weighted_score;
        document.getElementById('eb-lookback').value = p.lookback_days;
        document.getElementById('eb-cluster-window').value = p.signal_cluster_window_minutes;
        document.getElementById('eb-position-size').value = p.position_size_pct;
        document.getElementById('eb-stop-loss').value = p.stop_loss_pct;
        document.getElementById('eb-take-profit').value = p.take_profit_pct;

        document.getElementById('eb-optimize-results')?.classList.add('hidden');
        showToast('Best parameters applied! Click "Run Backtest" to see results.', 'success');
    }

    /**
     * Close optimization results panel
     */
    closeOptimizationResults() {
        document.getElementById('eb-optimize-results')?.classList.add('hidden');
    }
}

// Create global instance
window.ensemble = new EnsembleManager();

// Register modal initialization
modalManager.register('ensemble-backtest', {
    onOpen: async () => {
        await ensemble.initModal();
    }
});
