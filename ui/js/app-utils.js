// Application Utilities - Toast, Modal, Formatters
// Extends the utils.js created earlier with app-specific overrides

// Toast Notification (app-specific implementation)
function showToast(message, type = 'info') {
    const existing = document.querySelector('.toast');
    if (existing) existing.remove();
    
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);
    
    setTimeout(() => toast.remove(), 4000);
}

// Modal System (legacy - works with existing HTML structure)
function openModal(title, content) {
    document.getElementById('modal-title').textContent = title;
    document.getElementById('modal-body').innerHTML = content;
    document.getElementById('modal-overlay').classList.add('active');
}

function closeModal(event) {
    if (event && event.target !== event.currentTarget) return;
    document.getElementById('modal-overlay').classList.remove('active');
    if (window.chartInstance) {
        window.chartInstance.destroy();
        window.chartInstance = null;
    }
}

// Test modal function for debugging
window.testModal = function() {
    console.log('Test modal called');
    const modal = document.getElementById('ensemble-backtest-modal');
    console.log('Modal element:', modal);
    if (modal) {
        modal.classList.add('active');
        console.log('Active class added');
    }
};

// Toggle and Restore Functions for Collapsible Cards
function togglePosition(posId) {
    const details = document.getElementById(`${posId}-details`);
    if (details) {
        details.classList.toggle('collapsed');
        
        // Save state to localStorage
        const positions = JSON.parse(localStorage.getItem('collapsed-positions') || '{}');
        positions[posId] = details.classList.contains('collapsed');
        localStorage.setItem('collapsed-positions', JSON.stringify(positions));
    }
}

function toggleSignal(signalId) {
    const details = document.getElementById(`${signalId}-details`);
    if (details) {
        details.classList.toggle('collapsed');
        
        // Save state to localStorage
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
            if (details) {
                details.classList.add('collapsed');
            }
        }
    });
}

function restoreSignalStates() {
    const signals = JSON.parse(localStorage.getItem('collapsed-signals') || '{}');
    Object.keys(signals).forEach(signalId => {
        if (signals[signalId]) {
            const details = document.getElementById(`${signalId}-details`);
            if (details) {
                details.classList.add('collapsed');
            }
        }
    });
}

// Export functions globally
window.showToast = showToast;
window.openModal = openModal;
window.closeModal = closeModal;
window.togglePosition = togglePosition;
window.toggleSignal = toggleSignal;
window.restorePositionStates = restorePositionStates;
window.restoreSignalStates = restoreSignalStates;
