"""Portfolio Risk Manager - Phase 3
Professional risk management: correlation, concentration, drawdown protection
"""
from typing import Dict, List, Optional, Tuple
from shared.database import get_connection
from shared.logging_config import setup_logging
from datetime import date

logger = setup_logging('risk_manager', 'INFO')

class PortfolioRiskManager:
    """Manages portfolio-level risk checks before opening positions"""
    
    def __init__(self, total_capital: float = 10000.0, mode: str = 'paper'):
        self.total_capital = total_capital
        self.mode = mode
        
        # Risk thresholds
        self.max_correlated_capital_pct = 0.40  # Max 40% in correlated assets
        self.max_deployed_capital_pct = 0.80    # Max 80% deployed (20% reserve)
        self.correlation_threshold = 0.7         # High correlation cutoff
        self.drawdown_warning_pct = 0.05        # 5% daily loss → reduce sizing
        self.drawdown_stop_pct = 0.10           # 10% daily loss → stop trading
        self.symbol_blacklist_threshold = -5.0  # < -$5 P&L → blacklist (LIVE ONLY)
    
    def check_correlation_risk(self, new_symbol: str, proposed_value: float) -> Dict:
        """Check if new position would create excessive correlation risk
        
        Returns:
            approved: bool - Whether to allow the trade
            size_adjustment: float - Multiplier for position size (1.0 = full, 0.5 = half, 0 = skip)
            reason: str - Explanation
            correlated_symbols: List[str] - Symbols with high correlation
        """
        try:
            # Get open ensemble positions
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT symbol, capital_allocated
                        FROM positions
                        WHERE status = 'open'
                        AND mode = 'paper'
                        AND position_type = 'ensemble'
                    """)
                    open_positions = cur.fetchall()
            
            if not open_positions:
                return {
                    'approved': True,
                    'size_adjustment': 1.0,
                    'reason': 'No existing positions - no correlation risk',
                    'correlated_symbols': []
                }
            
            # Get correlation data
            correlations = self._get_correlation_matrix([p['symbol'] for p in open_positions] + [new_symbol])
            
            # Check correlation with each open position
            highly_correlated = []
            total_correlated_capital = 0.0
            
            for position in open_positions:
                symbol = position['symbol']
                capital = float(position['capital_allocated'])
                
                corr = correlations.get((new_symbol, symbol), 0.0)
                
                if abs(corr) >= self.correlation_threshold:
                    highly_correlated.append(symbol)
                    total_correlated_capital += capital
            
            # Calculate total with new position
            total_with_new = total_correlated_capital + proposed_value
            correlated_pct = total_with_new / self.total_capital
            
            # Determine action
            if len(highly_correlated) == 0:
                return {
                    'approved': True,
                    'size_adjustment': 1.0,
                    'reason': 'Low correlation with existing positions',
                    'correlated_symbols': []
                }
            
            elif len(highly_correlated) == 1 and correlated_pct < self.max_correlated_capital_pct:
                return {
                    'approved': True,
                    'size_adjustment': 0.75,  # Reduce to 75%
                    'reason': f'Moderately correlated with {highly_correlated[0]} - reducing size',
                    'correlated_symbols': highly_correlated
                }
            
            elif len(highly_correlated) >= 2:
                # Too many correlated positions
                if total_correlated_capital > self.total_capital * 0.30:  # >30% already deployed
                    return {
                        'approved': False,
                        'size_adjustment': 0.0,
                        'reason': f'High correlation with {len(highly_correlated)} positions: {", ".join(highly_correlated)}',
                        'correlated_symbols': highly_correlated
                    }
                else:
                    return {
                        'approved': True,
                        'size_adjustment': 0.5,  # Half size
                        'reason': f'Correlated with multiple positions - using 50% size',
                        'correlated_symbols': highly_correlated
                    }
            
            elif correlated_pct >= self.max_correlated_capital_pct:
                # Would exceed concentration limit
                return {
                    'approved': False,
                    'size_adjustment': 0.0,
                    'reason': f'Would exceed {self.max_correlated_capital_pct*100:.0f}% correlated capital limit',
                    'correlated_symbols': highly_correlated
                }
            
            else:
                return {
                    'approved': True,
                    'size_adjustment': 1.0,
                    'reason': 'Acceptable correlation risk',
                    'correlated_symbols': highly_correlated
                }
        
        except Exception as e:
            logger.error("correlation_check_error", error=str(e))
            # Fail open - allow trade with warning
            return {
                'approved': True,
                'size_adjustment': 1.0,
                'reason': f'Correlation check failed: {str(e)[:50]}',
                'correlated_symbols': []
            }
    
    def check_drawdown_protection(self) -> Dict:
        """Check if today's losses require risk reduction"""
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT COALESCE(SUM(realized_pnl), 0) as today_pnl
                        FROM positions
                        WHERE DATE(entry_time) = %s
                        AND mode = 'paper'
                        AND position_type = 'ensemble'
                        AND status = 'closed'
                    """, (date.today(),))
                    
                    result = cur.fetchone()
                    today_pnl = float(result['today_pnl'])
            
            drawdown_pct = abs(today_pnl / self.total_capital)
            
            if today_pnl >= 0:
                return {
                    'approved': True,
                    'size_adjustment': 1.0,
                    'emergency_stop': False,
                    'reason': f'Positive P&L today: ${today_pnl:+.2f}'
                }
            
            elif drawdown_pct >= self.drawdown_stop_pct:
                # Severe drawdown - stop trading
                return {
                    'approved': False,
                    'size_adjustment': 0.0,
                    'emergency_stop': True,
                    'reason': f'Daily loss {drawdown_pct:.1%} exceeds {self.drawdown_stop_pct:.0%} limit - STOP TRADING'
                }
            
            elif drawdown_pct >= self.drawdown_warning_pct:
                # Moderate drawdown - reduce sizing
                return {
                    'approved': True,
                    'size_adjustment': 0.5,  # Half size
                    'emergency_stop': False,
                    'reason': f'Daily loss {drawdown_pct:.1%} - reducing position sizes 50%'
                }
            
            else:
                return {
                    'approved': True,
                    'size_adjustment': 1.0,
                    'emergency_stop': False,
                    'reason': f'Minor daily loss: ${today_pnl:+.2f}'
                }
        
        except Exception as e:
            logger.error("drawdown_check_error", error=str(e))
            return {
                'approved': True,
                'size_adjustment': 1.0,
                'emergency_stop': False,
                'reason': f'Drawdown check failed: {str(e)[:50]}'
            }
    
    def check_portfolio_heat(self) -> Dict:
        """Check total deployed capital limits"""
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT COALESCE(SUM(capital_allocated), 0) as deployed
                        FROM positions
                        WHERE status = 'open'
                        AND mode = 'paper'
                        AND position_type = 'ensemble'
                    """)
                    
                    result = cur.fetchone()
                    deployed = float(result['deployed'])
            
            deployed_pct = deployed / self.total_capital
            available = self.total_capital - deployed
            
            if deployed_pct >= self.max_deployed_capital_pct:
                return {
                    'approved': False,
                    'available_capital': available,
                    'reason': f'Deployed {deployed_pct:.1%} exceeds {self.max_deployed_capital_pct:.0%} limit'
                }
            elif deployed_pct >= 0.70:  # Warning at 70%
                return {
                    'approved': True,
                    'available_capital': available,
                    'reason': f'High deployment {deployed_pct:.1%} - {available:.2f} available'
                }
            else:
                return {
                    'approved': True,
                    'available_capital': available,
                    'reason': f'Deployed {deployed_pct:.1%} - ${available:.2f} available'
                }
        
        except Exception as e:
            logger.error("portfolio_heat_error", error=str(e))
            return {
                'approved': True,
                'available_capital': self.total_capital * 0.2,
                'reason': f'Portfolio heat check failed: {str(e)[:50]}'
            }
    
    def check_symbol_blacklist(self, symbol: str) -> Dict:
        """Check if symbol is blacklisted due to poor performance
        
        BLACKLIST NOW ACTIVE IN PAPER MODE!
        
        Root cause identified: Bootstrap performance inflation caused system
        to hyper-focus on worst performers. Signal generator showed ETC/GRT/SNX
        with 100% win rates based on 2-3 trades, when actual performance was
        terrible (0-18% real win rate, losing -$5 to -$19 each).
        
        Blacklist protects against this inverse selection trap.
        """
        try:
            # BLACKLIST NOW ACTIVE IN BOTH MODES
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT SUM(realized_pnl) as total_pnl, COUNT(*) as trade_count
                        FROM positions
                        WHERE symbol = %s
                        AND mode = %s
                        AND position_type = 'ensemble'
                        AND status = 'closed'
                        AND entry_time >= NOW() - INTERVAL '30 days'
                    """, (symbol, self.mode))
                    
                    result = cur.fetchone()
                    
                    if not result or result['trade_count'] == 0:
                        return {
                            'approved': True,
                            'reason': f'{symbol}: No recent history'
                        }
                    
                    total_pnl = float(result['total_pnl'])
                    trade_count = result['trade_count']
                    
                    if total_pnl < self.symbol_blacklist_threshold:
                        return {
                            'approved': False,
                            'reason': f'{symbol}: Poor performer (${total_pnl:.2f} in {trade_count} trades)'
                        }
                    else:
                        return {
                            'approved': True,
                            'reason': f'{symbol}: Acceptable history (${total_pnl:.2f})'
                        }
        
        except Exception as e:
            logger.error("blacklist_check_error", symbol=symbol, error=str(e))
            return {
                'approved': True,
                'reason': f'Blacklist check failed: {str(e)[:50]}'
            }
    
    def evaluate_new_position(self, symbol: str, proposed_value: float) -> Dict:
        """Comprehensive risk check before opening a new position
        
        Returns dict with:
            approved: bool
            final_value: float (adjusted position size)
            checks: Dict (results of each check)
            reason: str
        """
        checks = {}
        adjustments = []
        
        # Check 1: Symbol blacklist
        checks['blacklist'] = self.check_symbol_blacklist(symbol)
        if not checks['blacklist']['approved']:
            return {
                'approved': False,
                'final_value': 0.0,
                'checks': checks,
                'reason': checks['blacklist']['reason']
            }
        
        # Check 2: Drawdown protection
        checks['drawdown'] = self.check_drawdown_protection()
        if checks['drawdown']['emergency_stop']:
            return {
                'approved': False,
                'final_value': 0.0,
                'checks': checks,
                'reason': checks['drawdown']['reason']
            }
        adjustments.append(checks['drawdown']['size_adjustment'])
        
        # Check 3: Portfolio heat
        checks['portfolio_heat'] = self.check_portfolio_heat()
        if not checks['portfolio_heat']['approved']:
            return {
                'approved': False,
                'final_value': 0.0,
                'checks': checks,
                'reason': checks['portfolio_heat']['reason']
            }
        
        # Check 4: Correlation risk
        checks['correlation'] = self.check_correlation_risk(symbol, proposed_value)
        if not checks['correlation']['approved']:
            return {
                'approved': False,
                'final_value': 0.0,
                'checks': checks,
                'reason': checks['correlation']['reason']
            }
        adjustments.append(checks['correlation']['size_adjustment'])
        
        # Calculate final position size (apply all adjustments)
        final_value = proposed_value
        for adj in adjustments:
            final_value *= adj
        
        # Build reason summary
        reasons = []
        if checks['drawdown']['size_adjustment'] < 1.0:
            reasons.append(f"drawdown protection: {checks['drawdown']['size_adjustment']*100:.0f}% size")
        if checks['correlation']['size_adjustment'] < 1.0:
            reasons.append(f"correlation risk: {checks['correlation']['size_adjustment']*100:.0f}% size")
        
        reason_str = " | ".join(reasons) if reasons else "All risk checks passed"
        
        return {
            'approved': True,
            'final_value': final_value,
            'checks': checks,
            'reason': reason_str
        }
    
    def _get_correlation_matrix(self, symbols: List[str]) -> Dict[Tuple[str, str], float]:
        """Get price correlations between symbols (simplified version)
        
        In production, this would calculate actual rolling correlations.
        For now, use known crypto correlations.
        """
        # Simplified correlation data (crypto assets tend to move together)
        # In production: calculate from historical price data
        
        known_correlations = {
            # DeFi tokens (high correlation)
            ('AAVE', 'COMP'): 0.85,
            ('AAVE', 'UNI'): 0.80,
            ('COMP', 'UNI'): 0.82,
            ('SNX', 'AAVE'): 0.75,
            ('SNX', 'COMP'): 0.73,
            
            # Layer 1s (high correlation)
            ('ADA', 'DOT'): 0.88,
            ('ADA', 'ALGO'): 0.82,
            ('DOT', 'ALGO'): 0.85,
            
            # Mixed (moderate correlation)
            ('ETH', 'AAVE'): 0.65,
            ('ETC', 'ETH'): 0.70,
            ('GRT', 'AAVE'): 0.60,
            
            # Everything has some correlation with Bitcoin
            ('BTC', 'ETH'): 0.75,
            ('BTC', 'ADA'): 0.70,
            ('BTC', 'DOT'): 0.68,
        }
        
        result = {}
        for i, sym1 in enumerate(symbols):
            for sym2 in symbols[i+1:]:
                # Check both orders
                corr = known_correlations.get((sym1, sym2), 
                      known_correlations.get((sym2, sym1), 0.5))  # Default moderate correlation
                result[(sym1, sym2)] = corr
                result[(sym2, sym1)] = corr
        
        return result
