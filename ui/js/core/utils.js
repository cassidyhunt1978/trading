// js/core/utils.js — Toast, modal, formatters, and toggle helpers
// Merged from app-utils.js + utils.js

// ─── Toast Notification ──────────────────────────────────────────────────────
function showToast(message, type = 'info', duration = 4000) {
    const existing = document.querySelector('.toast');
    if (existing) existing.remove();

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), duration);
}

// ─── Modal System (legacy – works with existing HTML structure) ───────────────
function openModal(title, content) {
    document.getElementById('modal-title').textContent = title;
    document.getElementById('modal-body').innerHTML = content;
    document.getElementById('modal-overlay').classList.add('active');
}

function closeModal(event) {
    if (event && event.target !== event.currentTarget) return;
    document.getElementById('modal-overlay').classList.remove('active');
    // Destroy MarketMind chart terminal if open
    if (window._chartEngine || window._engine) {
        import('/chart-terminal/src/terminal_init.js')
            .then(m => m.destroyChartTerminal())
            .catch(() => {});
    }
    const chartCss = document.getElementById('chart-terminal-css');
    if (chartCss) chartCss.remove();
    const modalBody = document.getElementById('modal-body');
    if (modalBody) modalBody.style.padding = '';
    if (window.chartInstance) {
        window.chartInstance.destroy();
        window.chartInstance = null;
    }
}

// ─── Collapsible Card Helpers ─────────────────────────────────────────────────
function togglePosition(posId) {
    const details = document.getElementById(`${posId}-details`);
    if (details) {
        details.classList.toggle('collapsed');
        const positions = JSON.parse(localStorage.getItem('collapsed-positions') || '{}');
        positions[posId] = details.classList.contains('collapsed');
        localStorage.setItem('collapsed-positions', JSON.stringify(positions));
    }
}

function toggleSignal(signalId) {
    const details = document.getElementById(`${signalId}-details`);
    if (details) {
        details.classList.toggle('collapsed');
        const signals = JSON.parse(localStorage.getItem('collapsed-signals') || '{}');
        signals[signalId] = details.classList.contains('collapsed');
        localStorage.setItem('collapsed-signals', JSON.stringify(signals));
    }
}

function restorePositionStates() {
    const positions = JSON.parse(localStorage.getItem('collapsed-positions') || '{}');
    Object.keys(positions).forEach(posId => {
        if (positions[posId]) {
            const details = document.getElementById(`${posId}-details`);
            if (details) details.classList.add('collapsed');
        }
    });
}

function restoreSignalStates() {
    const signals = JSON.parse(localStorage.getItem('collapsed-signals') || '{}');
    Object.keys(signals).forEach(signalId => {
        if (signals[signalId]) {
            const details = document.getElementById(`${signalId}-details`);
            if (details) details.classList.add('collapsed');
        }
    });
}

// ─── Number Formatters ────────────────────────────────────────────────────────
function formatCurrency(value, decimals = 2) {
    return new Intl.NumberFormat('en-US', {
        style: 'currency', currency: 'USD',
        minimumFractionDigits: decimals, maximumFractionDigits: decimals
    }).format(value);
}

function formatPercent(value, decimals = 2, showSign = true) {
    const sign = showSign && value > 0 ? '+' : '';
    return `${sign}${value.toFixed(decimals)}%`;
}

function formatCompact(value) {
    if (Math.abs(value) >= 1000000) return (value / 1000000).toFixed(1) + 'M';
    if (Math.abs(value) >= 1000) return (value / 1000).toFixed(1) + 'K';
    return value.toFixed(0);
}

function formatDateTime(ds) { return new Date(ds).toLocaleString(); }
function formatDate(ds)     { return new Date(ds).toLocaleDateString(); }
function formatTime(ds)     { return new Date(ds).toLocaleTimeString(); }

function timeAgo(dateString) {
    const seconds = Math.floor((Date.now() - new Date(dateString)) / 1000);
    for (const [label, secs] of [
        ['year',31536000],['month',2592000],['day',86400],
        ['hour',3600],['minute',60],['second',1]
    ]) {
        const c = Math.floor(seconds / secs);
        if (c >= 1) return `${c} ${label}${c !== 1 ? 's' : ''} ago`;
    }
    return 'just now';
}

function debounce(func, wait) {
    let timeout;
    return function(...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func(...args), wait);
    };
}

// ─── System Health Indicator (runs on every page via realtime.js) ─────────────
function updateSystemTabIndicator(healthScore) {
    const indicator = document.getElementById('system-health-indicator');
    if (!indicator) return;
    if (healthScore === 100) {
        indicator.className = 'inline-block w-2 h-2 rounded-full ml-1.5 bg-green-500';
        indicator.title = '100% — All systems operational';
    } else if (healthScore >= 90) {
        indicator.className = 'inline-block w-2 h-2 rounded-full ml-1.5 bg-yellow-500 animate-pulse';
        indicator.title = `${healthScore}% — Minor issues detected`;
    } else if (healthScore >= 70) {
        indicator.className = 'inline-block w-2 h-2 rounded-full ml-1.5 bg-orange-500 animate-pulse';
        indicator.title = `${healthScore}% — Issues detected`;
    } else {
        indicator.className = 'inline-block w-2 h-2 rounded-full ml-1.5 bg-red-500 animate-pulse';
        indicator.title = `${healthScore}% — Critical issues`;
    }
}

async function checkSystemHealthBackground() {
    try {
        const ports = [8011, 8012, 8013, 8014, 8015, 8016, 8017, 8018, 8019, 8020];
        const results = await Promise.all(ports.map(async port => {
            try {
                const r = await fetch(`http://${window.API_HOST}:${port}/health`, {
                    signal: AbortSignal.timeout(2000)
                });
                return r.ok ? 1 : 0;
            } catch { return 0; }
        }));
        const onlineCount = results.reduce((s, v) => s + v, 0);
        const apiHealth = Math.round((onlineCount / 10) * 100);

        try {
            const dbResp = await fetch(`http://${window.API_HOST}:8019/test/database`);
            const dbData = await dbResp.json();
            if (dbData.status === 'success') {
                const totalCandles = dbData.candle_counts.reduce((s, i) => s + i.count, 0);
                const symbolCount  = dbData.symbols || dbData.candle_counts.length;
                const target       = symbolCount * 180 * 24 * 60;
                const dbHealth     = Math.min(100, Math.round((totalCandles / target) * 100));
                updateSystemTabIndicator(Math.round(apiHealth * 0.6 + dbHealth * 0.4));
            } else {
                updateSystemTabIndicator(apiHealth);
            }
        } catch {
            updateSystemTabIndicator(apiHealth);
        }
    } catch (e) {
        console.warn('Background health check failed', e);
        updateSystemTabIndicator(50);
    }
}

// Expose for legacy callers
window.showToast  = showToast;
window.openModal  = openModal;
window.closeModal = closeModal;
window.togglePosition  = togglePosition;
window.toggleSignal    = toggleSignal;
window.restorePositionStates = restorePositionStates;
window.restoreSignalStates   = restoreSignalStates;
window.checkSystemHealthBackground  = checkSystemHealthBackground;
window.updateSystemTabIndicator     = updateSystemTabIndicator;
