// Symbol Management Functions

async function loadSymbols() {
    try {
        // Check if we're on the symbols tab
        const tbody = document.getElementById('symbolsTableBody');
        const countElement = document.getElementById('activeSymbolCount');
        
        if (!tbody) {
            // Not on symbols tab, skip loading
            return;
        }
        
        const response = await fetch('http://localhost:8012/symbols');
        const data = await response.json();
        
        if (data.status === 'success') {
            renderSymbolsTable(data.symbols);
            if (countElement) {
                countElement.textContent = data.count;
            }
        }
    } catch (error) {
        console.error('Failed to load symbols:', error);
        // Only show toast if on symbols tab
        if (document.getElementById('symbolsTableBody') && typeof showToast !== 'undefined') {
            showToast('Failed to load symbols', 'error');
        }
    }
}

function renderSymbolsTable(symbols) {
    const tbody = document.getElementById('symbolsTableBody');
    
    if (!tbody) return; // Not on symbols tab
    
    if (symbols.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="5" style="text-align: center; padding: 40px; color: #8b92b8;">
                    No symbols found. Click "Add All 15 Symbols" above to get started!
                </td>
            </tr>
        `;
        return;
    }
    
    tbody.innerHTML = symbols.map(symbol => `
        <tr>
            <td><strong style="font-size: 14px;">${symbol.symbol}</strong></td>
            <td>${symbol.name || symbol.symbol}</td>
            <td style="text-transform: capitalize;">${symbol.exchange || 'kraken'}</td>
            <td>
                <span class="status-badge status-${symbol.status || 'active'}">
                    ${symbol.status || 'active'}
                </span>
            </td>
            <td>
                <button onclick="toggleSymbol('${symbol.symbol}')" class="btn-secondary btn-sm">
                    ${(symbol.status || 'active') === 'active' ? 'Deactivate' : 'Activate'}
                </button>
            </td>
        </tr>
    `).join('');
}

function showAddSymbolModal() {
    document.getElementById('addSymbolModal').style.display = 'flex';
}

function closeAddSymbolModal() {
    document.getElementById('addSymbolModal').style.display = 'none';
    document.getElementById('addSymbolForm').reset();
}

// Close modal when clicking outside
window.addEventListener('click', (event) => {
    const modal = document.getElementById('addSymbolModal');
    if (event.target === modal) {
        closeAddSymbolModal();
    }
});

async function addSymbol(event) {
    event.preventDefault();
    
    const symbol = document.getElementById('symbolInput').value.toUpperCase();
    const name = document.getElementById('symbolName').value;
    const exchange = document.getElementById('symbolExchange').value;
    
    try {
        const response = await fetch('http://localhost:8012/symbols/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symbol, name, exchange })
        });
        
        const data = await response.json();
        
        if (data.status === 'success') {
            showToast(`✓ Symbol ${symbol} added successfully!`, 'success');
            closeAddSymbolModal();
            loadSymbols();
        } else {
            showToast('Failed to add symbol', 'error');
        }
    } catch (error) {
        console.error('Failed to add symbol:', error);
        showToast('Failed to add symbol', 'error');
    }
}

async function addSymbolQuick(symbol, name) {
    try {
        const btn = event.target;
        const originalText = btn.textContent;
        btn.disabled = true;
        btn.textContent = '...';
        
        const response = await fetch('http://localhost:8012/symbols/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symbol, name, exchange: 'kraken' })
        });
        
        const data = await response.json();
        
        if (data.status === 'success') {
            btn.textContent = '✓ ' + symbol;
            btn.style.background = '#10b981';
            showToast(`✓ ${symbol} added!`, 'success');
            
            setTimeout(() => {
                loadSymbols();
            }, 500);
        } else {
            btn.disabled = false;
            btn.textContent = originalText;
            showToast(`Failed to add ${symbol}`, 'error');
        }
    } catch (error) {
        console.error('Failed to add symbol:', error);
        const btn = event.target;
        btn.disabled = false;
        btn.textContent = symbol;
        showToast(`Error adding ${symbol}`, 'error');
    }
}

async function addAllPopularSymbols() {
    const symbols = [
        ['XRP','Ripple'], ['DOGE','Dogecoin'], ['LTC','Litecoin'],
        ['BCH','Bitcoin Cash'], ['XLM','Stellar'], ['ALGO','Algorand'],
        ['XTZ','Tezos'], ['ETC','Ethereum Classic'], ['NEAR','Near Protocol'],
        ['FTM','Fantom'], ['GRT','The Graph'], ['CRV','Curve DAO'],
        ['SNX','Synthetix'], ['COMP','Compound'], ['MKR','Maker']
    ];
    
    const btn = event.target;
    btn.disabled = true;
    btn.textContent = 'Adding symbols...';
    
    showToast('Adding 15 symbols, please wait...', 'info');
    
    let added = 0;
    for (const [symbol, name] of symbols) {
        try {
            const response = await fetch('http://localhost:8012/symbols/add', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ symbol, name, exchange: 'kraken' })
            });
            
            if (response.ok) {
                added++;
                btn.textContent = `Added ${added}/15...`;
            }
        } catch (error) {
            console.error(`Failed to add ${symbol}:`, error);
        }
    }
    
    btn.textContent = `✓ Added ${added}/15 symbols`;
    btn.style.background = '#10b981';
    showToast(`✓ Successfully added ${added}/15 symbols!`, 'success');
    
    setTimeout(() => {
        loadSymbols();
        btn.disabled = false;
    }, 2000);
}

async function toggleSymbol(symbol) {
    try {
        const response = await fetch(`http://localhost:8012/symbols/${symbol}/toggle`, {
            method: 'PUT'
        });
        
        const data = await response.json();
        
        if (data.status === 'success') {
            const statusText = data.new_status === 'active' ? 'activated' : 'deactivated';
            showToast(`✓ ${symbol} ${statusText}`, 'success');
            loadSymbols();
        }
    } catch (error) {
        console.error('Failed to toggle symbol:', error);
        showToast('Failed to toggle symbol', 'error');
    }
}

// Initialize symbol management when tab becomes visible
document.addEventListener('tabChanged', (e) => {
    if (e.detail.tab === 'symbols') {
        loadSymbols();
    }
});
// Export functions globally for access from other scripts
window.loadSymbols = loadSymbols;
window.showAddSymbolModal = showAddSymbolModal;
window.closeAddSymbolModal = closeAddSymbolModal;
window.addSymbol = addSymbol;
window.addSymbolQuick = addSymbolQuick;
window.addAllPopularSymbols = addAllPopularSymbols;
window.toggleSymbol = toggleSymbol;
// Also load on page load if symbols tab is active
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        setTimeout(() => {
            if (document.getElementById('symbolsTableBody')) {
                loadSymbols();
            }
        }, 500);
    });
} else {
    setTimeout(() => {
        if (document.getElementById('symbolsTableBody')) {
            loadSymbols();
        }
    }, 500);
}
