/**
 * Position Card Renderer
 * Renders trading positions in a consistent card format
 */

function renderPositionCard(position) {
    const isOpen = position.status === 'open';
    const pnl = isOpen ? (parseFloat(position.current_pnl) || 0) : (parseFloat(position.realized_pnl) || 0);
    const pnlPct = isOpen ? (parseFloat(position.current_pnl_pct) || 0) : (parseFloat(position.realized_pnl_pct) || 0);
    const currentPrice = isOpen ? (parseFloat(position.current_price) || 0).toFixed(2) : (parseFloat(position.exit_price) || 0).toFixed(2);
    
    // Position type badge
    const positionType = position.position_type || 'strategy';
    const isEnsemble = positionType === 'ensemble';
    const typeBadge = isEnsemble 
        ? '<span class="px-2 py-1 bg-purple-900 text-purple-300 rounded text-xs font-bold" title="Ensemble: Real trading position">🎯 ENSEMBLE</span>'
        : '<span class="px-2 py-1 bg-gray-700 text-gray-400 rounded text-xs" title="Strategy: Test position for learning">🧪 TEST</span>';
    
    return `
        <div class="symbol-card p-4">
            <div class="flex justify-between items-start mb-3">
                <div class="flex-1">
                    <h3 class="text-lg font-bold">${position.symbol}</h3>
                    <div class="text-sm text-gray-400">${getStrategyName(position.strategy_id) || 'Unknown'}</div>
                    <div class="text-xs text-gray-500 mt-1">${new Date(position.entry_time).toLocaleString()}</div>
                </div>
                <div class="flex flex-col items-end gap-1">
                    <span class="px-2 py-1 ${isOpen ? 'bg-green-900 text-green-300' : 'bg-gray-700 text-gray-300'} rounded text-xs font-bold">
                        ${isOpen ? 'OPEN' : 'CLOSED'}
                    </span>
                    ${typeBadge}
                    <span class="px-2 py-1 ${position.mode === 'paper' ? 'bg-blue-900 text-blue-300' : 'bg-orange-900 text-orange-300'} rounded text-xs">
                        ${position.mode.toUpperCase()}
                    </span>
                </div>
            </div>
            
            <div class="grid grid-cols-3 gap-2 text-sm mb-3">
                <div>
                    <div class="text-xs text-gray-500">Side</div>
                    <div class="font-bold ${position.quantity > 0 ? 'text-green-400' : 'text-red-400'}">
                        ${position.quantity > 0 ? 'BUY' : 'SELL'}
                    </div>
                </div>
                <div>
                    <div class="text-xs text-gray-500">Entry</div>
                    <div class="font-bold">$${parseFloat(position.entry_price).toFixed(2)}</div>
                </div>
                <div>
                    <div class="text-xs text-gray-500">${isOpen ? 'Current' : 'Exit'}</div>
                    <div class="font-bold">$${currentPrice}</div>
                </div>
            </div>
            
            <div class="flex justify-between items-center">
                <div class="${pnl >= 0 ? 'text-green-400' : 'text-red-400'} font-bold text-lg">
                    ${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)} (${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(2)}%)
                </div>
                ${isOpen ? 
                    `<button onclick="closePosition(${position.id}, '${position.mode}')" class="px-3 py-1 bg-red-600 hover:bg-red-700 rounded text-xs font-semibold">Close</button>` : 
                    `<div class="text-xs text-gray-500">${position.minutes_held || 0}m</div>`
                }
            </div>
        </div>
    `;
}

function renderPaperPositionCard(position) {
    const pnl = parseFloat(position.current_pnl) || 0;
    const pnlPct = parseFloat(position.current_pnl_pct) || 0;
    
    return `
        <div class="symbol-card p-4 bg-blue-950 bg-opacity-30">
            <div class="flex justify-between items-start mb-3">
                <div>
                    <h3 class="text-lg font-bold">${position.symbol}</h3>
                    <div class="text-sm text-gray-400">${position.strategy_name || 'Unknown'}</div>
                </div>
                <span class="px-2 py-1 bg-green-900 text-green-300 rounded text-xs font-bold">
                    BUY
                </span>
            </div>
            
            <div class="grid grid-cols-2 gap-2 text-sm mb-3">
                <div>
                    <div class="text-xs text-gray-500">Entry</div>
                    <div class="font-bold">$${parseFloat(position.entry_price).toFixed(2)}</div>
                </div>
                <div>
                    <div class="text-xs text-gray-500">Current</div>
                    <div class="font-bold">$${parseFloat(position.current_price || position.entry_price).toFixed(2)}</div>
                </div>
            </div>
            
            <div class="${pnl >= 0 ? 'text-green-400' : 'text-red-400'} font-bold text-lg text-center">
                ${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)} (${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(2)}%)
            </div>
        </div>
    `;
}

function renderPositionsList(positions) {
    if (!positions || positions.length === 0) {
        return `
            <div class="text-center py-10 text-gray-400">
                <div class="text-4xl mb-2">📊</div>
                <div>No positions found</div>
            </div>
        `;
    }
    
    // Group positions by symbol
    const groupedPositions = positions.reduce((acc, pos) => {
        if (!acc[pos.symbol]) {
            acc[pos.symbol] = [];
        }
        acc[pos.symbol].push(pos);
        return acc;
    }, {});
    
    // Sort symbols alphabetically
    const sortedSymbols = Object.keys(groupedPositions).sort();
    
    return `
        <div class="space-y-0.5">
            ${sortedSymbols.map(symbol => {
                const symbolPositions = groupedPositions[symbol];
                const symbolId = `pos-${symbol}`;
                
                // Calculate aggregate P&L for this symbol
                const totalPnl = symbolPositions.reduce((sum, pos) => {
                    return sum + parseFloat(pos.current_pnl || pos.realized_pnl || 0);
                }, 0);
                const avgPnlPct = symbolPositions.reduce((sum, pos) => {
                    return sum + parseFloat(pos.current_pnl_pct || pos.realized_pnl_pct || 0);
                }, 0) / symbolPositions.length;
                
                const allOpen = symbolPositions.every(p => p.status === 'open');
                const allClosed = symbolPositions.every(p => p.status === 'closed');
                const mode = symbolPositions[0].mode; // Assume same mode
                
                return `
                    <div class="bg-gray-800 rounded-sm overflow-hidden">
                        <div class="p-2 cursor-pointer hover:bg-gray-750" onclick="window.togglePosition('${symbolId}')">
                            <div class="flex justify-between items-center">
                                <div class="flex items-center gap-2 text-sm">
                                    <span class="font-bold">${symbol}</span>
                                    <span>${allOpen ? '🟢' : allClosed ? '🔴' : '🟡'}</span>
                                    <span class="text-xs">${mode === 'paper' ? '📋' : '💰'}</span>
                                    <span class="text-xs text-gray-400">${symbolPositions.length} position${symbolPositions.length > 1 ? 's' : ''}</span>
                                </div>
                                <div class="${totalPnl >= 0 ? 'text-green-400' : 'text-red-400'} font-bold text-sm">
                                    ${totalPnl >= 0 ? '+' : ''}${avgPnlPct.toFixed(2)}% <span class="text-xs opacity-75">(${totalPnl >= 0 ? '+' : ''}$${totalPnl.toFixed(2)})</span>
                                </div>
                            </div>
                        </div>
                        <div id="${symbolId}-details" class="position-details-compact collapsed">
                            <div class="px-2 pb-2">
                                ${symbolPositions.map(pos => {
                                    const pnl = parseFloat(pos.current_pnl || pos.realized_pnl || 0);
                                    const pnlPct = parseFloat(pos.current_pnl_pct || pos.realized_pnl_pct || 0);
                                    const isOpen = pos.status === 'open';
                                    
                                    return `
                                        <div class="text-xs py-1.5 border-t border-gray-700 first:border-t-0">
                                            <div class="flex justify-between items-center mb-1">
                                                <span class="text-gray-400">🎯 ${pos.strategy_name || 'Unknown Strategy'}</span>
                                                <span class="font-semibold ${pnl >= 0 ? 'text-green-400' : 'text-red-400'}">
                                                    ${pnl >= 0 ? '+' : ''}${pnlPct.toFixed(2)}% (${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)})
                                                </span>
                                            </div>
                                            <div class="flex justify-between text-gray-400">
                                                <span>Entry: <span class="text-white">$${parseFloat(pos.entry_price).toFixed(2)}</span></span>
                                                <span>Current: <span class="text-white">$${parseFloat(pos.current_price || pos.entry_price).toFixed(2)}</span></span>
                                                ${pos.stop_loss_price ? `<span class="text-red-400">SL: $${parseFloat(pos.stop_loss_price).toFixed(2)}</span>` : ''}
                                                ${pos.take_profit_price ? `<span class="text-green-400">TP: $${parseFloat(pos.take_profit_price).toFixed(2)}</span>` : ''}
                                            </div>
                                        </div>
                                    `;
                                }).join('')}
                            </div>
                        </div>
                    </div>
                `;
            }).join('')}
        </div>
    `;
}

function renderPaperPositionsList(positions) {
    if (!positions || positions.length === 0) {
        return `
            <div class="text-center py-10 text-gray-400 symbol-card p-6">
                <div class="text-4xl mb-2">📋</div>
                <div>No active paper positions</div>
            </div>
        `;
    }
    
    return positions.map(position => renderPaperPositionCard(position)).join('');
}

function renderPositionsError(message) {
    return `
        <div class="text-center py-10 text-red-400 symbol-card p-6">
            <div class="text-4xl mb-2">⚠️</div>
            <div>Error: ${message}</div>
        </div>
    `;
}

function renderPositionsLoading() {
    return `
        <div class="text-center py-10 text-gray-400 symbol-card p-6">
            <div class="text-4xl mb-2">⏳</div>
            <div>Loading positions...</div>
        </div>
    `;
}
