// Application Initialization
// Handles DOMContentLoaded setup and periodic refresh intervals

document.addEventListener('DOMContentLoaded', () => {
    console.log('Trading UI initialized');
    
    // Run initial health check in background
    if (window.checkSystemHealthBackground) {
        window.checkSystemHealthBackground();
    }
    
    // Check for saved tab in localStorage, default to portfolio
    const savedTab = localStorage.getItem('activeTab') || 'portfolio';
    
    // Activate the saved/default tab
    document.querySelectorAll('.tab-content').forEach(tab => {
        tab.classList.remove('active');
    });
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    document.getElementById(`tab-${savedTab}`).classList.add('active');
    document.querySelector(`button[onclick="showTab('${savedTab}')"]`).classList.add('active');
    
    // Load data for the initial tab
    if (savedTab === 'symbols' && window.loadSymbols) {
        window.loadSymbols();
    } else if (savedTab === 'portfolio') {
        window.loadPositions && window.loadPositions();
        window.loadEnsembleSignals && window.loadEnsembleSignals();
        window.loadPnlCard && window.loadPnlCard('paper');
        // Dashboard widgets: equity curve, top symbols, top strategies
        setTimeout(() => { window.loadTopDashboard && window.loadTopDashboard(); }, 800);
    } else if (savedTab === 'strategies') {
        window.loadStrategies && window.loadStrategies();
        window.loadStrategyPerformance && window.loadStrategyPerformance();
    } else if (savedTab === 'policies') {
        window.loadPolicies && window.loadPolicies();
    } else if (savedTab === 'system') {
        window.loadSystemHealth && window.loadSystemHealth();
    }

    // Always load portfolio widgets on DOMContentLoaded regardless of current tab
    // (They're lightweight reads and make the dashboard useful immediately)
    if (savedTab !== 'portfolio') {
        setTimeout(() => { window.loadTopDashboard && window.loadTopDashboard(); }, 2000);
    }
    
    // Refresh symbols data every 60 seconds when on Symbols tab
    setInterval(() => {
        const symbolsTab = document.getElementById('tab-symbols');
        if (symbolsTab && symbolsTab.classList.contains('active')) {
            window.loadSymbols && window.loadSymbols();
        }
    }, 60000);
    
    // Refresh portfolio data every 15 seconds when on Portfolio tab
    setInterval(() => {
        const portfolioTab = document.getElementById('tab-portfolio');
        if (portfolioTab && portfolioTab.classList.contains('active')) {
            window.loadPositions && window.loadPositions();
        }
    }, 15000);

    // Refresh dashboard widgets (equity, top symbols/strats) every 5 minutes
    setInterval(() => {
        window.loadTopDashboard && window.loadTopDashboard();
    }, 300000);

    // Also load dashboard widgets when switching to portfolio tab
    const _origShowTabInit = window.showTab;
    if (typeof _origShowTabInit === 'function') {
        window.showTab = function(name) {
            _origShowTabInit.call(this, ...arguments);
            if (name === 'portfolio') {
                setTimeout(() => { window.loadTopDashboard && window.loadTopDashboard(); }, 300);
            }
        };
    }
    
    // Refresh system data every 30 seconds when on System tab
    setInterval(() => {
        const systemTab = document.getElementById('tab-system');
        if (systemTab && systemTab.classList.contains('active')) {
            window.loadSystemHealth && window.loadSystemHealth();
        }
    }, 30000);
    
    // Background health check every 60 seconds (updates tab indicator)
    setInterval(() => {
        if (window.checkSystemHealthBackground) {
            window.checkSystemHealthBackground();
        }
    }, 60000);
});
