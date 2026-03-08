// Application Initialization
// Handles DOMContentLoaded setup and periodic refresh intervals

document.addEventListener('DOMContentLoaded', () => {
    console.log('Trading UI initialized');

    // ─ Real-time SSE/polling module ─────────────────────────────────────
    window.initRealtimeConnection && window.initRealtimeConnection();

    // Run initial health check in background
    if (window.checkSystemHealthBackground) {
        window.checkSystemHealthBackground();
    }

    // Check for saved tab in localStorage, default to portfolio
    const savedTab = localStorage.getItem('activeTab') || 'portfolio';

    // Activate the saved/default tab
    document.querySelectorAll('.tab-content').forEach(tab => tab.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    document.getElementById(`tab-${savedTab}`)?.classList.add('active');
    document.querySelector(`button[onclick="showTab('${savedTab}')"]`)?.classList.add('active');

    // ─ Portfolio tab init ─────────────────────────────────────────────────
    if (savedTab === 'portfolio') {
        _initPortfolio();
    } else if (savedTab === 'symbols') {
        window.loadSymbols && window.loadSymbols();
    } else if (savedTab === 'strategies') {
        window.loadStrategies && window.loadStrategies();
        window.loadStrategyPerformance && window.loadStrategyPerformance();
    } else if (savedTab === 'policies') {
        window.loadPolicies && window.loadPolicies();
    } else if (savedTab === 'system') {
        window.loadSystemHealth && window.loadSystemHealth();
    }

    // ─ Tab switch hook ────────────────────────────────────────────────────
    const _origShowTab = window.showTab;
    if (typeof _origShowTab === 'function') {
        window.showTab = function(name) {
            _origShowTab.apply(this, arguments);
            if (name === 'portfolio') {
                setTimeout(_initPortfolio, 300);
            }
        };
    }

    // ─ Periodic refresh ──────────────────────────────────────────────────
    // Dashboard: refresh compact header + equity every 60 s
    setInterval(() => {
        const tab = document.getElementById('tab-portfolio');
        if (tab?.classList.contains('active')) {
            window.refreshDashboardHeader && window.refreshDashboardHeader();
            window.loadMiniEquity && window.loadMiniEquity(30);
        }
    }, 60000);

    // Symbol cards: refresh every 2 minutes — use loadSymbols so signals fetched once
    setInterval(() => {
        const tab = document.getElementById('tab-portfolio');
        if (tab?.classList.contains('active')) {
            window.loadSymbolStats && window.loadSymbolStats();
        }
    }, 120000);

    // Symbols tab: refresh every 60 s when active
    setInterval(() => {
        if (document.getElementById('tab-symbols')?.classList.contains('active')) {
            window.loadSymbols && window.loadSymbols();
        }
    }, 60000);

    // Positions: refresh every 15 s on portfolio tab
    setInterval(() => {
        if (document.getElementById('tab-portfolio')?.classList.contains('active')) {
            window.loadPositions && window.loadPositions();
        }
    }, 15000);

    // System tab
    setInterval(() => {
        if (document.getElementById('tab-system')?.classList.contains('active')) {
            window.loadSystemHealth && window.loadSystemHealth();
        }
    }, 30000);

    // Background health check badge
    setInterval(() => { window.checkSystemHealthBackground && window.checkSystemHealthBackground(); }, 60000);
});

/** Initialise the portfolio tab (dashboard) */
function _initPortfolio() {
    // Load pnl card internals (updates hidden spans used by dash header)
    window.loadPnlCard && window.loadPnlCard('paper');
    window.loadPositions && window.loadPositions();
    // Highlights row: discoveries / strategies / regimes
    window.loadPortfolioHighlights && window.loadPortfolioHighlights();
    // Mini equity + compact header stats (fire immediately, no artificial delay)
    window.loadMiniEquity && window.loadMiniEquity(30);
    window.refreshDashboardHeader && window.refreshDashboardHeader();
}
window._initPortfolio = _initPortfolio;
