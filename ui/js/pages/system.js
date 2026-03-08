// pages/system.js — System health page

function toggleHealthDetails(section) {
    const details = document.getElementById(`${section}-details`);
    if (details) details.classList.toggle('hidden');
}

function updateHealthBar(barId, textId, percentage, label, colorClass = 'from-green-500 to-green-400') {
            const bar = document.getElementById(barId);
            const text = document.getElementById(textId);
            
            bar.style.width = `${percentage}%`;
            bar.className = `bg-gradient-to-r ${colorClass} h-6 rounded-full flex items-center justify-center text-xs font-bold transition-all duration-500`;
            text.textContent = label;
        }

async function loadSystemLayersIntegrated() {
            // Helper to update layer bar
            const updateLayer = (num, active, status) => {
                const bar = document.getElementById(`layer${num}-bar`);
                const statusEl = document.getElementById(`layer${num}-status`);
                const width = active ? '100%' : '0%';
                const color = active ? 'bg-gradient-to-r from-green-500 to-green-400' : 'bg-gradient-to-r from-red-500 to-red-400';
                
                bar.style.width = width;
                bar.className = `h-4 rounded-full transition-all duration-500 ${color}`;
                statusEl.textContent = status;
                statusEl.className = `text-xs ${active ? 'text-green-400' : 'text-red-400'}`;
            };
            
            // Layer 1: Symbol Collection - Check OHLCV API
            try {
                const ohlcvResp = await fetch(`http://${window.API_HOST}:8012/health`, { signal: AbortSignal.timeout(2000) });
                if (ohlcvResp.ok) {
                    const symbolsResp = await fetch(`http://${window.API_HOST}:8012/symbols`);
                    const symbolsData = await symbolsResp.json();
                    const count = symbolsData.symbols?.length || 0;
                    updateLayer(1, true, `✓ ${count} symbols`);
                } else {
                    updateLayer(1, false, '✗ Offline');
                }
            } catch (e) {
                updateLayer(1, false, '✗ Offline');
            }
            
            // Layer 2: Strategy Optimization - Check Optimization API
            try {
                const optResp = await fetch(`http://${window.API_HOST}:8014/health`, { signal: AbortSignal.timeout(2000) });
                updateLayer(2, optResp.ok, optResp.ok ? '✓ Active' : '✗ Offline');
            } catch (e) {
                updateLayer(2, false, '✗ Offline');
            }
            
            // Layer 3: Trust Scoring - Check Signal API
            try {
                const signalResp = await fetch(`http://${window.API_HOST}:8015/health`, { signal: AbortSignal.timeout(2000) });
                updateLayer(3, signalResp.ok, signalResp.ok ? '✓ Tracking' : '✗ Offline');
            } catch (e) {
                updateLayer(3, false, '✗ Offline');
            }
            
            // Layer 4: Regime Detection - Check regimes endpoint with longer timeout
            try {
                const regimeResp = await fetch(`http://${window.API_HOST}:8015/regimes`, { signal: AbortSignal.timeout(5000) });
                if (regimeResp.ok) {
                    try {
                        const regimeData = await regimeResp.json();
                        const count = regimeData.length || 0;
                        updateLayer(4, true, `✓ ${count} regimes`);
                    } catch {
                        // JSON parse error, but API responded - consider it working
                        updateLayer(4, true, '✓ Active');
                    }
                } else {
                    updateLayer(4, false, '✗ Error');
                }
            } catch (e) {
                // Only mark offline if it's a clear network/timeout error
                updateLayer(4, false, '✗ Offline');
            }
            
            // Layer 5: AI Orchestration - Check AI API
            try {
                const aiResp = await fetch(`http://${window.API_HOST}:8011/health`, { signal: AbortSignal.timeout(2000) });
                updateLayer(5, aiResp.ok, aiResp.ok ? '✓ Running' : '✗ Offline');
            } catch (e) {
                updateLayer(5, false, '✗ Offline');
            }
            
            // Layer 6: Ensemble Voting - Check Signal API ensemble endpoint
            try {
                const ensembleResp = await fetch(`http://${window.API_HOST}:8015/signals/ensemble?min_weighted_score=55&period_days=14`, { 
                    signal: AbortSignal.timeout(3000) 
                });
                if (ensembleResp.ok) {
                    const ensembleData = await ensembleResp.json();
                    const count = ensembleData.ensemble_signals?.length || 0;
                    updateLayer(6, true, `✓ ${count} signals`);
                } else {
                    updateLayer(6, false, '✗ Error');
                }
            } catch (e) {
                updateLayer(6, false, '✗ Offline');
            }
            
            // Layer 7: Accounting & P&L - Check Portfolio API (fixed endpoint)
            try {
                const portfolioResp = await fetch(`http://${window.API_HOST}:8016/health`, { signal: AbortSignal.timeout(2000) });
                if (portfolioResp.ok) {
                    // Try to get portfolio data
                    try {
                        const portfolioData = await fetch(`http://${window.API_HOST}:8016/portfolio?mode=paper`, { signal: AbortSignal.timeout(2000) });
                        const data = await portfolioData.json();
                        const positions = data.positions?.length || 0;
                        updateLayer(7, true, `✓ ${positions} positions`);
                    } catch {
                        updateLayer(7, true, '✓ Active');
                    }
                } else {
                    updateLayer(7, false, '✗ Offline');
                }
            } catch (e) {
                updateLayer(7, false, '✗ Offline');
            }
            
            // Layer 8: Goal Management - Check portfolio snapshots with single request
            try {
                const portfolioResp = await fetch(`http://${window.API_HOST}:8016/portfolio?mode=paper`, { signal: AbortSignal.timeout(5000) });
                if (portfolioResp.ok) {
                    try {
                        const portfolioData = await portfolioResp.json();
                        const targetMet = portfolioData.daily_target_met ? 'Met' : 'Tracking';
                        updateLayer(8, true, `✓ ${targetMet}`);
                    } catch {
                        // JSON parse error, but API responded - consider it working
                        updateLayer(8, true, '✓ Active');
                    }
                } else {
                    updateLayer(8, false, '✗ Error');
                }
            } catch (e) {
                // Only mark offline if it's a clear network/timeout error
                updateLayer(8, false, '✗ Offline');
            }
        }

async function loadSystemHealth() {
            // Check API services (now including System Monitor on 8021)
            const ports = [8011, 8012, 8013, 8014, 8015, 8016, 8017, 8018, 8019, 8020, 8021];
            const apiNames = {
                8011: 'AI', 8012: 'OHLCV', 8013: 'Backtest', 
                8014: 'Optimization', 8015: 'Signal', 8016: 'Portfolio',
                8017: 'Trading', 8018: 'AfterAction', 8019: 'Testing',
                8020: 'Config', 8021: 'Monitor'
            };
            
            let onlineCount = 0;
            const apiStatuses = [];
            
            for (const port of ports) {
                try {
                    const response = await fetch(`http://${window.API_HOST}:${port}/health`, { 
                        signal: AbortSignal.timeout(2000) 
                    });
                    
                    if (response.ok) {
                        apiStatuses.push({ name: apiNames[port], online: true });
                        onlineCount++;
                    } else {
                        apiStatuses.push({ name: apiNames[port], online: false });
                    }
                } catch (error) {
                    apiStatuses.push({ name: apiNames[port], online: false });
                }
            }
            
            // Update API card
            document.getElementById('apis-online').textContent = onlineCount;
            document.getElementById('apis-offline').textContent = 11 - onlineCount;
            
            // Show first 5 APIs in summary
            const summaryHtml = apiStatuses.slice(0, 5).map(api => {
                const dot = api.online ? '●' : '○';
                const color = api.online ? 'text-green-400' : 'text-red-400';
                return `<div class="flex items-center justify-between">
                    <span>${api.name}</span>
                    <span class="${color}">${dot}</span>
                </div>`;
            }).join('');
            document.getElementById('api-summary').innerHTML = summaryHtml;
            
            // Update API health bar
            const apiHealth = ((onlineCount / 11) * 100).toFixed(0);
            const apiColor = apiHealth >= 90 ? 'from-green-500 to-green-400' : 
                           apiHealth >= 70 ? 'from-yellow-500 to-yellow-400' : 'from-red-500 to-red-400';
            updateHealthBar('api-bar', 'api-text', apiHealth, `${onlineCount}/11 Online`, apiColor);
            document.getElementById('api-health').textContent = `${apiHealth}%`;
            
            // Show all APIs in details section
            const allApisHtml = apiStatuses.map(api => {
                const dot = api.online ? '●' : '○';
                const color = api.online ? 'text-green-400' : 'text-red-400';
                return `<div class="flex items-center justify-between">
                    <span>${api.name}</span>
                    <span class="${color}">${dot}</span>
                </div>`;
            }).join('');
            document.getElementById('api-summary').innerHTML = allApisHtml;
            
            // Load system layers (integrated into health check)
            loadSystemLayersIntegrated();
            
            // Run comprehensive tests first, then load database stats last
            // Database stats updates the tab indicator with overall health (API + DB)
            runSystemTests();
            loadDatabaseStats();
            loadAfterActionStats();
            loadSystemMetrics();
        }

async function loadDatabaseStats() {
            try {
                const response = await fetch(`http://${window.API_HOST}:8019/test/database`, { signal: AbortSignal.timeout(10000) });
                const data = await response.json();
                
                if (data.status === 'success') {
                    // Update database card
                    document.getElementById('db-tables').textContent = data.tables;
                    document.getElementById('db-symbols').textContent = data.symbols;
                    
                    // Calculate total candles
                    const totalCandles = data.candle_counts.reduce((sum, item) => sum + item.count, 0);
                    document.getElementById('db-candles').textContent = totalCandles.toLocaleString();
                    
                    // Update timestamp
                    const now = new Date();
                    document.getElementById('db-update-time').textContent = `Last updated: ${now.toLocaleTimeString()}`;
                    
                    // Calculate database health based on data completeness (dynamic symbol count)
                    const symbolCount = data.symbols || data.candle_counts.length;
                    const targetPerSymbol = 180 * 24 * 60; // 180 days of 1-minute candles
                    const target = targetPerSymbol * symbolCount;
                    const dbHealth = Math.min(100, ((totalCandles / target) * 100)).toFixed(0);
                    const dbColor = dbHealth >= 80 ? 'from-purple-500 to-purple-400' : 
                                   dbHealth >= 50 ? 'from-yellow-500 to-yellow-400' : 'from-red-500 to-red-400';
                    updateHealthBar('database-bar', 'database-text', dbHealth, `${dbHealth}% Complete`, dbColor);
                    document.getElementById('db-health').textContent = `${dbHealth}%`;
                    
                    // Show backfill status with details
                    const backfillStatus = document.getElementById('backfill-status');
                    const completeSymbols = data.candle_counts.filter(s => s.count >= targetPerSymbol).length;
                    const backfillingSymbols = symbolCount - completeSymbols;
                    
                    if (parseInt(dbHealth) < 100) {
                        const remaining = (target - totalCandles).toLocaleString();
                        backfillStatus.textContent = `⟳ Backfilling ${backfillingSymbols} symbol${backfillingSymbols !== 1 ? 's' : ''}: ${remaining} candles remaining`;
                        backfillStatus.className = 'mt-2 text-xs text-center text-blue-400';
                    } else {
                        backfillStatus.textContent = `✓ All ${symbolCount} symbols have 180 days of historical data`;
                        backfillStatus.className = 'mt-2 text-xs text-center text-green-400';
                    }
                    
                    // Update overall health (weighted: 60% API, 40% DB since DB takes time to fill)
                    const apiHealthVal = parseInt(document.getElementById('api-health').textContent) || 0;
                    const overallHealth = ((apiHealthVal * 0.6) + (parseInt(dbHealth) * 0.4)).toFixed(0);
                    const overallColor = overallHealth >= 90 ? 'from-green-500 to-green-400' : 
                                        overallHealth >= 70 ? 'from-yellow-500 to-yellow-400' : 'from-red-500 to-red-400';
                    updateHealthBar('overall-bar', 'overall-text', overallHealth, `${overallHealth}% Healthy`, overallColor);
                    document.getElementById('overall-score').textContent = `${overallHealth}%`;
                    
                    // Update system tab indicator with overall health
                    updateSystemTabIndicator(parseInt(overallHealth));
                }
            } catch (error) {
                console.error('Error loading database stats:', error);
            }
        }

async function loadAfterActionStats() {
            // Clear old data immediately
            const insightsDiv = document.getElementById('aa-recent-insights');
            if (insightsDiv) {
                insightsDiv.innerHTML = '<div class="text-center py-4 text-gray-500">Loading analysis reports...</div>';
            }
            
            try {
                // Get AfterAction stats
                const response = await fetch(`http://${window.API_HOST}:8018/stats`);
                const data = await response.json();
                
                // Update stats
                document.getElementById('aa-total-reports').textContent = data.total_reports || 0;
                document.getElementById('aa-win-rate').textContent = `${data.avg_win_rate || 0}%`;
                document.getElementById('aa-missed').textContent = data.total_missed_opportunities || 0;
                document.getElementById('aa-false-signals').textContent = data.total_false_signals || 0;
                
                // Update last run time
                if (data.last_run) {
                    const lastRun = new Date(data.last_run);
                    document.getElementById('aa-last-run').textContent = `Last analysis: ${lastRun.toLocaleString()}`;
                }
                
                // Get recent reports
                const reportsResponse = await fetch(`http://${window.API_HOST}:8018/reports?limit=5`);
                const reportsData = await reportsResponse.json();
                const reports = reportsData.reports || [];
                
                // Display insights
                const insightsDiv = document.getElementById('aa-recent-insights');
                
                if (reports && reports.length > 0) {
                    let insightsHtml = '';
                    
                    reports.slice(0, 3).forEach(report => {
                        const winRate = report.winning_trades && report.total_trades_analyzed 
                            ? ((report.winning_trades / report.total_trades_analyzed) * 100).toFixed(1)
                            : 0;
                        
                        // Show when analysis was run (created_at), not the period analyzed
                        const createdDate = new Date(report.created_at).toLocaleString();
                        const missedCount = report.missed_opportunities || 0;
                        const falseCount = report.false_signals || 0;
                        
                        // Build ALL recommendations with full actionable details
                        let recText = '';
                        if (report.recommendations && report.recommendations.length > 0) {
                            recText = '<div class="mt-2 space-y-2">' + report.recommendations.map((rec, idx) => {
                                const priorityColor = rec.priority === 'high' ? 'text-red-400' : 
                                                     rec.priority === 'medium' ? 'text-yellow-400' : 'text-blue-400';
                                const priorityBadge = `<span class="${priorityColor} text-[10px] font-bold uppercase">${rec.priority}</span>`;
                                
                                return `
                                    <div class="bg-gray-800 p-2 rounded border border-gray-600">
                                        <div class="flex items-start gap-2 mb-1">
                                            <span class="text-xs">${idx + 1}.</span>
                                            <div class="flex-1">
                                                <div class="text-xs font-semibold text-blue-300 mb-1">
                                                    ${rec.title} ${priorityBadge}
                                                </div>
                                                <div class="text-[11px] text-gray-400 mb-1">${rec.description}</div>
                                                <div class="text-[11px] text-green-300">
                                                    <span class="font-semibold">✅ Action:</span> ${rec.action}
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                `;
                            }).join('') + '</div>';
                        }
                        
                        insightsHtml += `
                            <div class="bg-gray-700 p-2 rounded mb-2">
                                <div class="flex justify-between items-start mb-1">
                                    <span class="font-semibold text-white text-xs">${createdDate}</span>
                                    <span class="${winRate >= 60 ? 'text-green-400' : winRate >= 40 ? 'text-yellow-400' : 'text-red-400'} font-bold">${winRate}% Win Rate</span>
                                </div>
                                <div class="flex justify-between text-xs mb-1">
                                    <span>${report.total_trades_analyzed} trades analyzed</span>
                                    <span class="text-yellow-400">${missedCount} missed</span>
                                    <span class="text-red-400">${falseCount} false</span>
                                </div>
                                ${recText}
                            </div>
                        `;
                    });
                    
                    insightsDiv.innerHTML = insightsHtml;
                } else {
                    insightsDiv.innerHTML = '<div class="text-center py-2 text-gray-500">No analysis reports yet. Run first analysis!</div>';
                }
                
            } catch (error) {
                console.error('Error loading AfterAction stats:', error);
                document.getElementById('aa-recent-insights').innerHTML = 
                    '<div class="text-center py-2 text-red-400">Failed to load AfterAction data</div>';
            }
        }

async function loadSystemMetrics() {
            try {
                const response = await fetch(`http://${window.API_HOST}:8021/metrics`, {
                    signal: AbortSignal.timeout(8000)
                });
                
                if (!response.ok) {
                    throw new Error('Failed to fetch system metrics');
                }
                
                const data = await response.json();
                
                // Update CPU metrics
                const cpuPercent = data.cpu.percent;
                document.getElementById('cpu-percent').textContent = `${cpuPercent}%`;
                document.getElementById('cpu-count').textContent = data.cpu.count;
                document.getElementById('cpu-load-1m').textContent = data.cpu.load_avg_1m;
                document.getElementById('cpu-load-5m').textContent = data.cpu.load_avg_5m;
                
                // Update CPU bar
                const cpuColor = cpuPercent >= 80 ? 'from-red-500 to-red-400' : 
                               cpuPercent >= 60 ? 'from-yellow-500 to-yellow-400' : 'from-blue-500 to-blue-400';
                updateHealthBar('cpu-bar', 'cpu-text', cpuPercent, `${cpuPercent}%`, cpuColor);
                
                // Update Memory metrics
                const memPercent = data.memory.percent;
                document.getElementById('memory-percent').textContent = `${memPercent}%`;
                document.getElementById('memory-used').textContent = `${data.memory.used_gb}GB`;
                document.getElementById('memory-available').textContent = `${data.memory.available_gb}GB`;
                document.getElementById('memory-total').textContent = `${data.memory.total_gb}GB`;
                document.getElementById('swap-used').textContent = `${data.memory.swap_used_gb}GB`;
                document.getElementById('swap-total').textContent = `${data.memory.swap_total_gb}GB`;
                document.getElementById('swap-percent').textContent = `${data.memory.swap_percent}%`;
                
                // Update Memory bar
                const memColor = memPercent >= 90 ? 'from-red-500 to-red-400' : 
                               memPercent >= 75 ? 'from-yellow-500 to-yellow-400' : 'from-green-500 to-green-400';
                updateHealthBar('memory-bar', 'memory-text', memPercent, `${data.memory.used_gb}GB / ${data.memory.total_gb}GB`, memColor);
                
                // Update Disk metrics
                const diskPercent = data.disk.percent;
                document.getElementById('disk-percent').textContent = `${diskPercent}%`;
                document.getElementById('disk-used').textContent = `${data.disk.used_gb}GB`;
                document.getElementById('disk-free').textContent = `${data.disk.free_gb}GB`;
                document.getElementById('disk-total').textContent = `${data.disk.total_gb}GB`;
                
                // Update Disk bar
                const diskColor = diskPercent >= 90 ? 'from-red-500 to-red-400' : 
                                diskPercent >= 75 ? 'from-yellow-500 to-yellow-400' : 'from-purple-500 to-purple-400';
                updateHealthBar('disk-bar', 'disk-text', diskPercent, `${data.disk.used_gb}GB / ${data.disk.total_gb}GB`, diskColor);
                
                // Update Disk I/O
                document.getElementById('disk-read').textContent = `${data.disk_io.read_mb.toLocaleString()}MB`;
                document.getElementById('disk-write').textContent = `${data.disk_io.write_mb.toLocaleString()}MB`;
                
                // Update Process Count
                document.getElementById('process-count').textContent = data.processes;
                
            } catch (error) {
                console.error('Error loading system metrics:', error);
                document.getElementById('cpu-text').textContent = 'Error';
                document.getElementById('memory-text').textContent = 'Error';
                document.getElementById('disk-text').textContent = 'Error';
            }
        }

async function runSystemTests() {
            const statusDiv = document.getElementById('health-status');
            
            statusDiv.innerHTML = '<span class="text-yellow-400">⟳ Running tests...</span>';
            
            try {
                const response = await fetch(`http://${window.API_HOST}:8019/test/run-all`);
                const data = await response.json();
                
                // Update health card
                document.getElementById('health-score').textContent = `${data.health_score}/100`;
                document.getElementById('health-tests').textContent = `${data.passed}/${data.total_tests}`;
                
                // Update status with list of failed tests
                const statusColor = data.health_score === 100 ? 'text-green-400' : 
                                  data.health_score >= 75 ? 'text-yellow-400' : 'text-red-400';
                
                if (data.health_score === 100) {
                    statusDiv.innerHTML = '<span class="text-green-400">✓ All systems operational</span>';
                } else {
                    // Get failed tests
                    const failedTests = data.tests.filter(test => test.status === 'FAIL');
                    
                    let failedHtml = `<div class="${statusColor} font-semibold mb-2">⚠ ${failedTests.length} Issue${failedTests.length > 1 ? 's' : ''} Detected:</div>`;
                    failedHtml += '<div class="space-y-1 text-xs">';
                    
                    failedTests.forEach(test => {
                        const errorMsg = test.error ? `: ${test.error.substring(0, 60)}${test.error.length > 60 ? '...' : ''}` : '';
                        failedHtml += `<div class="text-gray-300">• <span class="text-yellow-300">${test.category}</span> - ${test.name}${errorMsg}</div>`;
                    });
                    
                    failedHtml += '</div>';
                    statusDiv.innerHTML = failedHtml;
                }
                
                // Note: Do NOT update tab indicator here - it's updated by loadDatabaseStats
                // which calculates overall health including database backfill status
                
                // Only update overall if diagnostics found real issues
                if (data.health_score < 100) {
                    const overallColor = data.health_score >= 90 ? 'from-green-500 to-green-400' : 
                                        data.health_score >= 70 ? 'from-yellow-500 to-yellow-400' : 'from-red-500 to-red-400';
                    updateHealthBar('overall-bar', 'overall-text', data.health_score, `${data.health_score}% Healthy`, overallColor);
                    document.getElementById('overall-score').textContent = `${data.health_score}%`;
                }
                
            } catch (error) {
                console.error('Error running tests:', error);
                statusDiv.innerHTML = '<span class="text-red-400">⚠ Test failed</span>';
                showToast('Test execution failed', 'error');
            }
        }


// ── Init ──────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    window.checkSystemHealthBackground && window.checkSystemHealthBackground();
    loadSystemHealth();

    setInterval(loadSystemHealth, 30000);
    setInterval(() => { window.checkSystemHealthBackground && window.checkSystemHealthBackground(); }, 60000);
});
