// Utility Functions
// Toast notifications, formatters, and common helpers

/**
 * Show toast notification
 * @param {string} message - Message to display
 * @param {string} type - 'success' | 'error' | 'info' | 'warning'
 * @param {number} duration - Duration in ms (default: 4000)
 */
function showToast(message, type = 'info', duration = 4000) {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);
    
    setTimeout(() => toast.remove(), duration);
}

/**
 * Format number as currency
 */
function formatCurrency(value, decimals = 2) {
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals
    }).format(value);
}

/**
 * Format percentage
 */
function formatPercent(value, decimals = 2, showSign = true) {
    const sign = showSign && value > 0 ? '+' : '';
    return `${sign}${value.toFixed(decimals)}%`;
}

/**
 * Format number with abbreviations (1.5K, 2.3M, etc)
 */
function formatCompact(value) {
    if (Math.abs(value) >= 1000000) {
        return (value / 1000000).toFixed(1) + 'M';
    } else if (Math.abs(value) >= 1000) {
        return (value / 1000).toFixed(1) + 'K';
    }
    return value.toFixed(0);
}

/**
 * Format date/time
 */
function formatDateTime(dateString) {
    return new Date(dateString).toLocaleString();
}

function formatDate(dateString) {
    return new Date(dateString).toLocaleDateString();
}

function formatTime(dateString) {
    return new Date(dateString).toLocaleTimeString();
}

/**
 * Calculate time ago
 */
function timeAgo(dateString) {
    const date = new Date(dateString);
    const seconds = Math.floor((new Date() - date) / 1000);
    
    const intervals = [
        { label: 'year', seconds: 31536000 },
        { label: 'month', seconds: 2592000 },
        { label: 'day', seconds: 86400 },
        { label: 'hour', seconds: 3600 },
        { label: 'minute', seconds: 60 },
        { label: 'second', seconds: 1 }
    ];
    
    for (const interval of intervals) {
        const count = Math.floor(seconds / interval.seconds);
        if (count >= 1) {
            return `${count} ${interval.label}${count !== 1 ? 's' : ''} ago`;
        }
    }
    
    return 'just now';
}

/**
 * Debounce function calls
 */
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

/**
 * Throttle function calls
 */
function throttle(func, limit) {
    let inThrottle;
    return function(...args) {
        if (!inThrottle) {
            func.apply(this, args);
            inThrottle = true;
            setTimeout(() => inThrottle = false, limit);
        }
    };
}

/**
 * Copy text to clipboard
 */
async function copyToClipboard(text) {
    try {
        await navigator.clipboard.writeText(text);
        showToast('Copied to clipboard', 'success');
        return true;
    } catch (error) {
        console.error('Failed to copy:', error);
        showToast('Failed to copy', 'error');
        return false;
    }
}

/**
 * Download data as JSON file
 */
function downloadJSON(data, filename = 'data.json') {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

/**
 * Download data as CSV file
 */
function downloadCSV(data, filename = 'data.csv') {
    if (!Array.isArray(data) || data.length === 0) {
        showToast('No data to download', 'error');
        return;
    }
    
    // Convert objects to CSV
    const headers = Object.keys(data[0]);
    const csvContent = [
        headers.join(','),
        ...data.map(row => headers.map(header => {
            const value = row[header];
            // Escape commas and quotes
            if (typeof value === 'string' && (value.includes(',') || value.includes('"'))) {
                return `"${value.replace(/"/g, '""')}"`;
            }
            return value;
        }).join(','))
    ].join('\n');
    
    const blob = new Blob([csvContent], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

/**
 * Get color for PnL value
 */
function getPnLColor(value) {
    if (value > 0) return 'text-green-400';
    if (value < 0) return 'text-red-400';
    return 'text-gray-400';
}

/**
 * Get badge HTML for status
 */
function getStatusBadge(status) {
    const badges = {
        open: '<span class="px-2 py-1 bg-green-900 text-green-300 rounded text-xs">OPEN</span>',
        closed: '<span class="px-2 py-1 bg-gray-700 text-gray-300 rounded text-xs">CLOSED</span>',
        active: '<span class="px-2 py-1 bg-blue-900 text-blue-300 rounded text-xs">ACTIVE</span>',
        inactive: '<span class="px-2 py-1 bg-gray-700 text-gray-300 rounded text-xs">INACTIVE</span>',
        paper: '<span class="px-2 py-1 bg-blue-900 text-blue-300 rounded text-xs">PAPER</span>',
        live: '<span class="px-2 py-1 bg-purple-900 text-purple-300 rounded text-xs">LIVE</span>'
    };
    return badges[status] || `<span class="px-2 py-1 bg-gray-700 text-gray-300 rounded text-xs">${status}</span>`;
}

/**
 * Validate form fields
 */
function validateForm(formId) {
    const form = document.getElementById(formId);
    if (!form) return false;
    
    const required = form.querySelectorAll('[required]');
    let isValid = true;
    
    required.forEach(field => {
        if (!field.value || field.value.trim() === '') {
            field.classList.add('border-red-500');
            isValid = false;
        } else {
            field.classList.remove('border-red-500');
        }
    });
    
    if (!isValid) {
        showToast('Please fill in all required fields', 'error');
    }
    
    return isValid;
}

/**
 * Loading spinner HTML
 */
function getLoadingSpinner(message = 'Loading...') {
    return `
        <div class="flex items-center justify-center gap-3 py-8">
            <div class="animate-spin text-2xl">⏳</div>
            <div class="text-gray-400">${message}</div>
        </div>
    `;
}

/**
 * Empty state HTML
 */
function getEmptyState(message = 'No data available', icon = '📭') {
    return `
        <div class="text-center py-10 text-gray-500">
            <div class="text-4xl mb-2">${icon}</div>
            <div>${message}</div>
        </div>
    `;
}

// Export all functions to window
Object.assign(window, {
    showToast,
    formatCurrency,
    formatPercent,
    formatCompact,
    formatDateTime,
    formatDate,
    formatTime,
    timeAgo,
    debounce,
    throttle,
    copyToClipboard,
    downloadJSON,
    downloadCSV,
    getPnLColor,
    getStatusBadge,
    validateForm,
    getLoadingSpinner,
    getEmptyState
});
