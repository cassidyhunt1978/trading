// pages/portfolio.js — Portfolio page initialisation
// Core functions live in: pnl_card.js, realtime.js (loaded by base.html)

document.addEventListener('DOMContentLoaded', () => {
    window.initRealtimeConnection && window.initRealtimeConnection();
    window.checkSystemHealthBackground && window.checkSystemHealthBackground();

    window.loadPnlCard && window.loadPnlCard('paper');
    window.loadPortfolioHighlights && window.loadPortfolioHighlights();
    window.loadPortfolioPositions && window.loadPortfolioPositions();
    window.loadMiniEquity && window.loadMiniEquity(30);
    window.refreshDashboardHeader && window.refreshDashboardHeader();
    window.loadPortfolioSignals && window.loadPortfolioSignals();

    // Periodic refresh
    setInterval(() => {
        window.loadPortfolioPositions && window.loadPortfolioPositions();
    }, 15000);
    setInterval(() => {
        window.loadPnlCard && window.loadPnlCard('paper');
        window.loadMiniEquity && window.loadMiniEquity(30);
        window.refreshDashboardHeader && window.refreshDashboardHeader();
    }, 60000);
    setInterval(() => {
        window.loadPortfolioHighlights && window.loadPortfolioHighlights();
        window.loadPortfolioSignals && window.loadPortfolioSignals();
    }, 120000);
    setInterval(() => {
        window.checkSystemHealthBackground && window.checkSystemHealthBackground();
    }, 60000);
});
