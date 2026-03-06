// Configuration - Global constants and settings
const API_HOST = window.location.hostname;

// Global state
let currentSymbol = null;
let chartInstance = null;

// Export to window for global access
window.API_HOST = API_HOST;
window.currentSymbol = currentSymbol;
window.chartInstance = chartInstance;
