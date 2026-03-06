/**
 * Signal Card Renderer
 * Renders ensemble signals in a compact table format grouped by symbol
 */

function renderSignalCard(signal, index) {
    const medal = index === 0 ? '🥇' : index === 1 ? '🥈' : index === 2 ? '🥉' : '';
    // Enhanced color coding for signal strength
    const scoreColor = signal.weighted_score >= 110 ? 'text-red-400 font-bold animate-pulse' :  // Extraordinary
                       signal.weighted_score >= 100 ? 'text-orange-400 font-bold' :          // Exceptional
                       signal.weighted_score >= 90 ? 'text-green-400' :                       // Very High
                       signal.weighted_score >= 75 ? 'text-blue-400' : 'text-yellow-400';     // High/Normal
    const signalId = `sig-${signal.signal_id || index}`;
    
    return `
        <div class="bg-gray-800 rounded-sm overflow-hidden">
            <div class="p-2 cursor-pointer hover:bg-gray-750" onclick="window.toggleSignal('${signalId}')">
                <div class="flex justify-between items-center">
                    <div class="flex items-center gap-2 text-sm">
                        <span class="font-bold">${medal} ${signal.symbol}</span>
                        <span class="px-1.5 py-0.5 bg-${signal.signal_type === 'BUY' ? 'green' : 'red'}-900 text-${signal.signal_type === 'BUY' ? 'green' : 'red'}-300 rounded text-xs font-bold">
                            ${signal.signal_type}
                        </span>
                    </div>
                    <div class="${scoreColor} font-bold text-sm">
                        ${signal.weighted_score.toFixed(0)}
                    </div>
                </div>
            </div>
            <div id="${signalId}-details" class="position-details-compact collapsed">
                <div class="px-2 pb-2 text-xs">
                    <div class="text-gray-400 mb-1">🎯 ${signal.strategy_name}</div>
                    <div class="flex justify-between">
                        <span>Win: <span class="text-white">${signal.win_rate !== null ? signal.win_rate.toFixed(0) + '%' : 'New'}</span></span>
                        <span class="${signal.projected_return_pct >= 0 ? 'text-green-400' : 'text-red-400'}">Return: ${signal.projected_return_pct >= 0 ? '+' : ''}${signal.projected_return_pct.toFixed(1)}%</span>
                        <span>Quality: <span class="text-white">${signal.confidence_level && signal.confidence_level.toLowerCase() !== 'unknown' 
                            ? signal.confidence_level.toUpperCase() 
                            : signal.quality_score ? signal.quality_score.toFixed(0) + '%' : '-'}</span></span>
                    </div>
                </div>
            </div>
        </div>
    `;
}

function renderSignalsList(signals) {
    if (!signals || signals.length === 0) {
        return `
            <div class="text-center py-10 text-gray-400">
                <div class="text-4xl mb-2">🎯</div>
                <div>No signals above threshold</div>
            </div>
        `;
    }
    
    // Group signals by symbol
    const groupedSignals = signals.reduce((acc, signal) => {
        if (!acc[signal.symbol]) {
            acc[signal.symbol] = [];
        }
        acc[signal.symbol].push(signal);
        return acc;
    }, {});
    
    // Sort symbols by highest weighted score
    const sortedSymbols = Object.keys(groupedSignals).sort((a, b) => {
        const maxScoreA = Math.max(...groupedSignals[a].map(s => s.weighted_score));
        const maxScoreB = Math.max(...groupedSignals[b].map(s => s.weighted_score));
        return maxScoreB - maxScoreA;
    });
    
    return `
        <div class="space-y-0.5">
            ${sortedSymbols.map(symbol => {
                const symbolSignals = groupedSignals[symbol];
                const symbolId = `sig-${symbol}`;
                const maxScore = Math.max(...symbolSignals.map(s => s.weighted_score));
                const scoreColor = maxScore >= 90 ? 'text-green-400' : 
                                   maxScore >= 75 ? 'text-blue-400' : 'text-yellow-400';
                const signalType = symbolSignals[0].signal_type; // Assume same type per symbol
                
                return `
                    <div class="bg-gray-800 rounded-sm overflow-hidden">
                        <div class="p-2 cursor-pointer hover:bg-gray-750" onclick="window.toggleSignal('${symbolId}')">
                            <div class="flex justify-between items-center">
                                <div class="flex items-center gap-2 text-sm">
                                    <span class="font-bold">${symbol}</span>
                                    <span class="px-1.5 py-0.5 bg-${signalType === 'BUY' ? 'green' : 'red'}-900 text-${signalType === 'BUY' ? 'green' : 'red'}-300 rounded text-xs font-bold">
                                        ${signalType}
                                    </span>
                                    <span class="text-xs text-gray-400">${symbolSignals.length} signal${symbolSignals.length > 1 ? 's' : ''}</span>
                                </div>
                                <div class="${scoreColor} font-bold text-sm">
                                    ${maxScore.toFixed(0)}
                                </div>
                            </div>
                        </div>
                        <div id="${symbolId}-details" class="position-details-compact collapsed">
                            <div class="px-2 pb-2">
                                ${symbolSignals.map(signal => `
                                    <div class="text-xs py-1.5 border-t border-gray-700 first:border-t-0">
                                        <div class="flex justify-between items-center mb-1">
                                            <span class="text-gray-400">🎯 ${signal.strategy_name}</span>
                                            <span class="font-semibold ${signal.weighted_score >= 110 ? 'text-red-400 animate-pulse' : signal.weighted_score >= 100 ? 'text-orange-400' : signal.weighted_score >= 90 ? 'text-green-400' : signal.weighted_score >= 75 ? 'text-blue-400' : 'text-yellow-400'}">
                                                ${signal.weighted_score >= 110 ? '🚨 ' : signal.weighted_score >= 100 ? '⚡ ' : ''}${signal.weighted_score.toFixed(0)}
                                            </span>
                                        </div>
                                        <div class="flex justify-between text-gray-400">
                                            <span>Win: <span class="text-white">${signal.win_rate !== null ? signal.win_rate.toFixed(0) + '%' : 'New'}</span></span>
                                            <span class="${signal.projected_return_pct >= 0 ? 'text-green-400' : 'text-red-400'}">Return: ${signal.projected_return_pct >= 0 ? '+' : ''}${signal.projected_return_pct.toFixed(1)}%</span>
                                            <span>Quality: <span class="text-white">${signal.confidence_level && signal.confidence_level.toLowerCase() !== 'unknown' 
                                                ? signal.confidence_level.toUpperCase() 
                                                : signal.quality_score ? signal.quality_score.toFixed(0) + '%' : '-'}</span></span>
                                        </div>
                                    </div>
                                `).join('')}
                            </div>
                        </div>
                    </div>
                `;
            }).join('')}
        </div>
    `;
}

function renderSignalsError(message) {
    return `
        <div class="text-center py-10 text-red-400">
            <div class="text-4xl mb-2">⚠️</div>
            <div>Error: ${message}</div>
        </div>
    `;
}

function renderSignalsLoading() {
    return `
        <div class="text-center py-10 text-gray-400">
            <div class="text-4xl mb-2">⏳</div>
            <div>Loading signals...</div>
        </div>
    `;
}
