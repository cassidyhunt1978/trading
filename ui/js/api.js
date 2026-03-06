// API Utility Module
// Centralized API calls with error handling

const API_HOST = window.location.hostname;

class API {
    constructor(baseHost = API_HOST) {
        this.baseHost = baseHost;
        this.services = {
            ai: 8011,
            ohlcv: 8012,
            backtest: 8013,
            optimization: 8014,
            signal: 8015,
            portfolio: 8016,
            trading: 8017,
            afterAction: 8018,
            testing: 8019,
            strategyConfig: 8020
        };
    }

    /**
     * Build URL for a specific service
     */
    url(service, path) {
        const port = typeof service === 'number' ? service : this.services[service];
        return `http://${this.baseHost}:${port}${path}`;
    }

    /**
     * Generic fetch with error handling
     */
    async fetch(service, path, options = {}) {
        const url = this.url(service, path);
        try {
            const response = await fetch(url, {
                headers: {
                    'Content-Type': 'application/json',
                    ...options.headers
                },
                ...options
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            return await response.json();
        } catch (error) {
            console.error(`API Error [${service}${path}]:`, error);
            throw error;
        }
    }

    /**
     * GET request
     */
    async get(service, path, params = {}) {
        const queryString = Object.keys(params).length
            ? '?' + new URLSearchParams(params).toString()
            : '';
        return this.fetch(service, path + queryString, { method: 'GET' });
    }

    /**
     * POST request
     */
    async post(service, path, data = {}) {
        return this.fetch(service, path, {
            method: 'POST',
            body: JSON.stringify(data)
        });
    }

    /**
     * PUT request
     */
    async put(service, path, data = {}) {
        return this.fetch(service, path, {
            method: 'PUT',
            body: JSON.stringify(data)
        });
    }

    /**
     * DELETE request
     */
    async delete(service, path) {
        return this.fetch(service, path, { method: 'DELETE' });
    }

    // Symbols API
    async getSymbols() {
        return this.get('ohlcv', '/symbols');
    }

    async getSymbolDetails(symbol) {
        return this.get('ohlcv', `/symbols/${symbol}`);
    }

    // Strategies API
    async getStrategies() {
        return this.get('strategyConfig', '/strategies');
    }

    async createStrategy(data) {
        return this.post('strategyConfig', '/strategies', data);
    }

    async updateStrategy(strategyId, data) {
        return this.put('strategyConfig', `/strategies/${strategyId}`, data);
    }

    async deleteStrategy(strategyId) {
        return this.delete('strategyConfig', `/strategies/${strategyId}`);
    }

    // Signals API
    async getSignals(params = {}) {
        return this.get('signal', '/signals', params);
    }

    // Backtest API
    async runBacktest(data) {
        return this.post('backtest', '/backtest', data);
    }

    // Ensemble API
    async runEnsembleBacktest(data) {
        return this.post('backtest', '/ensemble', data);
    }

    async getOptimizedParams(symbol) {
        return this.get('backtest', '/ensemble/optimized-params', { symbol });
    }

    async triggerOptimization() {
        return this.post('backtest', '/ensemble/trigger-optimization');
    }

    async getOptimizationStatus() {
        return this.get('backtest', '/ensemble/optimization-status');
    }

    // Portfolio API
    async getPositions(mode = 'paper') {
        return this.get('portfolio', '/positions', { mode });
    }

    async closePosition(positionId, mode, reason = 'manual') {
        return this.post('optimization', '/close', { position_id: positionId, mode, reason });
    }

    // System Health
    async getSystemHealth() {
        const services = Object.keys(this.services);
        const healthChecks = await Promise.allSettled(
            services.map(async (service) => {
                try {
                    const response = await fetch(this.url(service, '/health'), { 
                        method: 'GET',
                        signal: AbortSignal.timeout(2000) // 2s timeout
                    });
                    return { 
                        service, 
                        port: this.services[service],
                        status: response.ok ? 'healthy' : 'unhealthy' 
                    };
                } catch (error) {
                    return { 
                        service, 
                        port: this.services[service],
                        status: 'down',
                        error: error.message 
                    };
                }
            })
        );

        return healthChecks.map(result => result.value || result.reason);
    }
}

// Create global instance
window.api = new API();
