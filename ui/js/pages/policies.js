// pages/policies.js — Trading safeguards / policies page


async function loadPolicies() {
            try {
                const mode = document.getElementById('policy-mode').value;
                const response = await fetch(`http://${window.API_HOST}:8020/policies/status?mode=${mode}`);
                
                if (!response.ok) {
                    throw new Error('Failed to load policies');
                }
                
                const data = await response.json();
                
                // Update emergency stop status
                const emergencyCard = document.getElementById('emergency-stop-card');
                const emergencyBtn = document.getElementById('emergency-btn');
                const emergencyStatus = document.getElementById('emergency-status');
                const emergencyReason = document.getElementById('emergency-reason');
                
                if (data.emergency_stop.active) {
                    emergencyCard.style.borderColor = '#dc2626';
                    emergencyCard.style.backgroundColor = 'rgba(220, 38, 38, 0.1)';
                    emergencyBtn.className = 'px-8 py-3 rounded-lg font-bold text-lg bg-green-600 hover:bg-green-700';
                    emergencyBtn.textContent = '✅ RESUME TRADING';
                    emergencyStatus.textContent = 'Emergency Stop Active';
                    emergencyStatus.className = 'text-sm text-red-400 font-bold';
                    emergencyReason.textContent = data.emergency_stop.reason || '';
                } else {
                    emergencyCard.style.borderColor = '#10b981';
                    emergencyCard.style.backgroundColor = '';
                    emergencyBtn.className = 'px-8 py-3 rounded-lg font-bold text-lg bg-red-600 hover:bg-red-700';
                    emergencyBtn.textContent = '🛑 STOP TRADING';
                    emergencyStatus.textContent = 'All trading active';
                    emergencyStatus.className = 'text-sm text-gray-400';
                    emergencyReason.textContent = '';
                }
                
                // Update today's stats
                const pnl = data.daily_limits.current_pnl;
                const pnlColor = pnl >= 0 ? 'text-green-400' : 'text-red-400';
                document.getElementById('today-pnl').innerHTML = `<span class="${pnlColor}">$${pnl.toFixed(2)}</span>`;
                document.getElementById('today-trades').textContent = data.daily_limits.trades_today;
                document.getElementById('current-open').textContent = data.position_limits.current_open;
                document.getElementById('consecutive-losses').textContent = data.alerts.consecutive_losses;
                
                // Update daily limits with progress bars
                const lossPct = Math.abs(pnl) / data.daily_limits.loss_limit * 100;
                document.getElementById('loss-limit-text').textContent = `$${Math.abs(pnl).toFixed(2)} / $${data.daily_limits.loss_limit}`;
                document.getElementById('loss-limit-bar').style.width = `${Math.min(lossPct, 100)}%`;
                document.getElementById('loss-limit-bar').className = `h-full transition-all ${lossPct >= 100 ? 'bg-red-600' : lossPct >= 75 ? 'bg-orange-500' : 'bg-red-500'}`;
                document.getElementById('edit-daily-loss').value = data.daily_limits.loss_limit;
                
                const tradePct = data.daily_limits.trades_today / data.daily_limits.trade_limit * 100;
                document.getElementById('trade-limit-text').textContent = `${data.daily_limits.trades_today} / ${data.daily_limits.trade_limit}`;
                document.getElementById('trade-limit-bar').style.width = `${Math.min(tradePct, 100)}%`;
                document.getElementById('trade-limit-bar').className = `h-full transition-all ${tradePct >= 100 ? 'bg-red-600' : tradePct >= 75 ? 'bg-yellow-500' : 'bg-blue-500'}`;
                document.getElementById('edit-daily-trades').value = data.daily_limits.trade_limit;
                
                document.getElementById('position-size-text').textContent = `$${data.policies.max_position_size}`;
                document.getElementById('edit-position-size').value = data.policies.max_position_size;
                
                // Update position management
                document.getElementById('max-open-display').textContent = data.position_limits.max_open;
                document.getElementById('edit-max-open').value = data.position_limits.max_open;
                document.getElementById('max-per-symbol-display').textContent = data.position_limits.max_per_symbol;
                document.getElementById('edit-max-per-symbol').value = data.position_limits.max_per_symbol;
                
                // Update market costs
                document.getElementById('cost-slippage').textContent = `${data.market_costs.slippage_pct}%`;
                document.getElementById('cost-spread').textContent = `${data.market_costs.spread_pct}%`;
                document.getElementById('cost-fee').textContent = `${data.market_costs.exchange_fee_pct}%`;
                document.getElementById('cost-total').textContent = `${data.market_costs.total_round_trip_pct}%`;
                document.getElementById('breakeven-required').textContent = data.market_costs.breakeven_move_required;
                
                // Update alert thresholds
                document.getElementById('edit-profit-alert').value = data.policies.alert_daily_profit_pct;
                document.getElementById('edit-loss-alert').value = data.policies.alert_daily_loss_pct;
                document.getElementById('edit-drawdown-alert').value = data.policies.alert_drawdown_pct;
                document.getElementById('edit-consecutive-alert').value = data.alerts.threshold;
                document.getElementById('alerts-sent-today').textContent = data.alerts.alerts_sent_today;
                
                // Update trading status
                const statusCard = document.getElementById('trading-status-card');
                const statusIcon = document.getElementById('status-icon');
                const statusText = document.getElementById('status-text');
                const statusDetail = document.getElementById('status-detail');
                
                if (!data.trading_allowed) {
                    statusCard.style.borderColor = '#dc2626';
                    statusIcon.textContent = '🚫';
                    statusText.textContent = 'Trading Blocked';
                    const reasons = [];
                    if (data.limits_hit.emergency_stop) reasons.push('Emergency stop active');
                    if (data.limits_hit.daily_loss_limit_hit) reasons.push('Daily loss limit reached');
                    if (data.limits_hit.daily_trade_limit_hit) reasons.push('Daily trade limit reached');
                    if (data.limits_hit.max_positions_hit) reasons.push('Max positions reached');
                    statusDetail.textContent = reasons.join(', ');
                    statusDetail.className = 'text-sm text-red-400';
                } else if (data.limits_hit.consecutive_losses_warning) {
                    statusCard.style.borderColor = '#f59e0b';
                    statusIcon.textContent = '⚠️';
                    statusText.textContent = 'Warning State';
                    statusDetail.textContent = `${data.alerts.consecutive_losses} consecutive losses`;
                    statusDetail.className = 'text-sm text-yellow-400';
                } else {
                    statusCard.style.borderColor = '#10b981';
                    statusIcon.textContent = '✅';
                    statusText.textContent = 'Trading Active';
                    statusDetail.textContent = 'All systems operational';
                    statusDetail.className = 'text-sm text-gray-400';
                }
                
            } catch (error) {
                console.error('Error loading policies:', error);
                showToast('Error loading policies', 'error');
            }
        }


// ── Init ──────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    window.checkSystemHealthBackground && window.checkSystemHealthBackground();
    loadPolicies();
});
