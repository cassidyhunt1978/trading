// Tab Management System
// Handles tab switching and loading associated data

function showTab(tabName) {
    // Save current tab to localStorage
    localStorage.setItem('activeTab', tabName);
    
    // Hide all tabs
    document.querySelectorAll('.tab-content').forEach(tab => {
        tab.classList.remove('active');
    });
    
    // Remove active class from all buttons
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    
    // Show selected tab
    document.getElementById(`tab-${tabName}`).classList.add('active');
    
    // Set active button
    event.target.classList.add('active');
    
    // Load data for specific tabs
    if (tabName === 'symbols') {
        window.loadSymbols && window.loadSymbols();
    } else if (tabName === 'portfolio') {
        window.loadPositions && window.loadPositions();
        window.loadEnsembleSignals && window.loadEnsembleSignals();
    } else if (tabName === 'strategies') {
        window.loadStrategies && window.loadStrategies();
        window.loadStrategyPerformance && window.loadStrategyPerformance();
        window.populatePerformanceSymbolFilter && window.populatePerformanceSymbolFilter();
    } else if (tabName === 'policies') {
        window.loadPolicies && window.loadPolicies();
    } else if (tabName === 'system') {
        // Clear old data before loading fresh
        const insightsDiv = document.getElementById('aa-recent-insights');
        if (insightsDiv) {
            insightsDiv.innerHTML = '<div class="text-center py-4 text-gray-500">Loading...</div>';
        }
        
        window.loadSystemHealth && window.loadSystemHealth();
        window.loadAfterActionStats && window.loadAfterActionStats();
        
        // Auto-run diagnostics only if system is not healthy
        setTimeout(() => {
            const overallScore = document.getElementById('overall-score');
            const overallHealth = parseInt(overallScore?.textContent) || 0;
            if (overallHealth < 90) {
                window.runSystemTests && window.runSystemTests();
            }
        }, 800);
    }
}

// Export function globally
window.showTab = showTab;
