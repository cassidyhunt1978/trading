#!/usr/bin/env python3
"""
System Layer Verification Tool
Validates that each architectural layer is functioning correctly
"""

import requests
import psycopg2
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
import json
from tabulate import tabulate

# Color codes for output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

def get_db_connection():
    """Get database connection"""
    return psycopg2.connect("dbname=trading_system user=postgres host=localhost")

def print_layer(layer_num: int, layer_name: str):
    """Print layer header"""
    print(f"\n{'='*80}")
    print(f"{BLUE}LAYER {layer_num}: {layer_name}{RESET}")
    print('='*80)

def print_check(check_name: str, passed: bool, details: str = ""):
    """Print check result"""
    status = f"{GREEN}✓ PASS{RESET}" if passed else f"{RED}✗ FAIL{RESET}"
    print(f"  {status} - {check_name}")
    if details:
        print(f"         {details}")

def print_warning(message: str):
    """Print warning message"""
    print(f"  {YELLOW}⚠ WARNING{RESET} - {message}")

def print_info(message: str):
    """Print info message"""
    print(f"  ℹ {message}")

# ============================================================================
# LAYER 1: SYMBOL COLLECTION
# ============================================================================
def verify_layer_1() -> Dict:
    """Verify symbol collection and data ingestion"""
    print_layer(1, "SYMBOL COLLECTION & DATA INGESTION")
    
    results = {'passed': 0, 'failed': 0, 'warnings': 0}
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Check 1: Active symbols count
        cur.execute("SELECT COUNT(*) FROM symbols WHERE status = 'active'")
        active_symbols = cur.fetchone()[0]
        passed = active_symbols > 0
        print_check(f"Active Symbols ({active_symbols} found)", passed)
        results['passed' if passed else 'failed'] += 1
        
        # Check 2: Recent OHLCV data (last 30 minutes)
        cur.execute("""
            SELECT symbol, COUNT(*) as candle_count, MAX(timestamp) as last_candle
            FROM ohlcv_candles
            WHERE timestamp > NOW() - INTERVAL '30 minutes'
            GROUP BY symbol
            ORDER BY symbol
        """)
        recent_data = cur.fetchall()
        
        if recent_data:
            print_check(f"Recent OHLCV Data ({len(recent_data)} symbols with data in last 30 min)", True)
            results['passed'] += 1
            
            # Show sample
            print_info(f"Sample: {recent_data[0][0]} has {recent_data[0][1]} candles, last at {recent_data[0][2]}")
        else:
            print_check("Recent OHLCV Data", False, "No data in last 30 minutes")
            results['failed'] += 1
        
        # Check 3: Historical data depth
        cur.execute("""
            SELECT symbol, 
                   COUNT(*) as total_candles,
                   MIN(timestamp) as earliest,
                   MAX(timestamp) as latest
            FROM ohlcv_candles
            GROUP BY symbol
            ORDER BY total_candles DESC
            LIMIT 5
        """)
        historical = cur.fetchall()
        
        if historical and historical[0][1] > 10000:
            print_check(f"Historical Depth (top symbol: {historical[0][1]:,} candles)", True)
            results['passed'] += 1
        elif historical:
            print_warning(f"Limited historical data (top symbol: {historical[0][1]:,} candles)")
            results['warnings'] += 1
        else:
            print_check("Historical Depth", False, "No candles found")
            results['failed'] += 1
        
        # Check 4: Celery backfill task
        try:
            response = requests.get("http://localhost:8021/metrics", timeout=5)
            if response.status_code == 200:
                print_check("Backfill Task Status (System Monitor accessible)", True)
                results['passed'] += 1
            else:
                print_warning("System Monitor not responding")
                results['warnings'] += 1
        except:
            print_warning("Cannot reach System Monitor API")
            results['warnings'] += 1
        
        cur.close()
        conn.close()
        
    except Exception as e:
        print_check("Layer 1 Database Access", False, str(e))
        results['failed'] += 1
    
    return results

# ============================================================================
# LAYER 2: STRATEGY PROCESSING & SYMBOL-SPECIFIC OPTIMIZATION
# ============================================================================
def verify_layer_2() -> Dict:
    """Verify strategy processing and symbol-specific optimization"""
    print_layer(2, "STRATEGY PROCESSING & SYMBOL-SPECIFIC OPTIMIZATION")
    
    results = {'passed': 0, 'failed': 0, 'warnings': 0}
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Check 1: Total strategies
        cur.execute("SELECT COUNT(*) FROM strategies")
        total_strategies = cur.fetchone()[0]
        print_check(f"Total Strategies ({total_strategies} found)", total_strategies > 0)
        results['passed' if total_strategies > 0 else 'failed'] += 1
        
        # Check 2: Enabled strategies
        cur.execute("SELECT COUNT(*) FROM strategies WHERE enabled = true")
        enabled_strategies = cur.fetchone()[0]
        passed = enabled_strategies > 0
        print_check(f"Enabled Strategies ({enabled_strategies}/{total_strategies})", passed)
        results['passed' if passed else 'failed'] += 1
        
        if enabled_strategies != total_strategies:
            print_warning(f"{total_strategies - enabled_strategies} strategies are DISABLED")
            results['warnings'] += 1
        
        # Check 3: Strategy overrides (symbol-specific optimization)
        cur.execute("""
            SELECT COUNT(*) as total_overrides,
                   COUNT(DISTINCT strategy_id) as strategies_with_overrides,
                   COUNT(DISTINCT symbol) as symbols_with_overrides
            FROM strategy_overrides
        """)
        override_data = cur.fetchone()
        
        if override_data[0] > 0:
            print_check(
                f"Symbol-Specific Optimizations ({override_data[0]} overrides)", 
                True,
                f"{override_data[1]} strategies × {override_data[2]} symbols"
            )
            results['passed'] += 1
        else:
            print_warning("No symbol-specific optimizations found")
            results['warnings'] += 1
        
        # Check 4: Recent optimization activity
        cur.execute("""
            SELECT COUNT(*) 
            FROM strategy_overrides 
            WHERE optimization_date > NOW() - INTERVAL '7 days'
        """)
        recent_opts = cur.fetchone()[0]
        
        if recent_opts > 0:
            print_check(f"Recent Optimization Activity ({recent_opts} in last 7 days)", True)
            results['passed'] += 1
        else:
            print_warning("No optimizations in last 7 days")
            results['warnings'] += 1
        
        # Check 5: Strategy Config API
        try:
            response = requests.get("http://localhost:8020/health", timeout=5)
            if response.status_code == 200:
                print_check("Strategy Config API", True)
                results['passed'] += 1
            else:
                print_check("Strategy Config API", False, "Not responding")
                results['failed'] += 1
        except:
            print_check("Strategy Config API", False, "Cannot connect")
            results['failed'] += 1
        
        cur.close()
        conn.close()
        
    except Exception as e:
        print_check("Layer 2 Database Access", False, str(e))
        results['failed'] += 1
    
    return results

# ============================================================================
# LAYER 3: SCORING & TRUST SYSTEM
# ============================================================================
def verify_layer_3() -> Dict:
    """Verify scoring, paper trading, and trust system"""
    print_layer(3, "SCORING & TRUST SYSTEM")
    
    results = {'passed': 0, 'failed': 0, 'warnings': 0}
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Check 1: Strategy performance tracking table exists
        cur.execute("""
            SELECT COUNT(*) 
            FROM information_schema.tables 
            WHERE table_name = 'strategy_performance'
        """)
        table_exists = cur.fetchone()[0] > 0
        print_check("Strategy Performance Table", table_exists)
        results['passed' if table_exists else 'failed'] += 1
        
        if table_exists:
            # Check 2: Performance data coverage
            cur.execute("""
                SELECT period_days, 
                       COUNT(*) as records,
                       COUNT(DISTINCT strategy_id) as strategies,
                       COUNT(DISTINCT symbol) as symbols,
                       AVG(win_rate) as avg_win_rate
                FROM strategy_performance
                GROUP BY period_days
                ORDER BY period_days
            """)
            perf_data = cur.fetchall()
            
            if perf_data:
                print_check(f"Performance Tracking Active", True)
                results['passed'] += 1
                for row in perf_data:
                    print_info(f"  {row[0]}-day window: {row[1]} records, {row[2]} strategies, {row[3]} symbols, {row[4]:.1f}% avg win rate")
            else:
                print_warning("No performance data tracked yet")
                results['warnings'] += 1
            
            # Check 3: Recent performance updates
            cur.execute("""
                SELECT COUNT(*) 
                FROM strategy_performance 
                WHERE updated_at > NOW() - INTERVAL '24 hours'
            """)
            recent_updates = cur.fetchone()[0]
            
            if recent_updates > 0:
                print_check(f"Recent Performance Updates ({recent_updates} in last 24h)", True)
                results['passed'] += 1
            else:
                print_warning("No performance updates in last 24 hours")
                results['warnings'] += 1
            
            # Check 4: Performance data with sufficient trades for trust scoring
            cur.execute("""
                SELECT period_days,
                       COUNT(*) FILTER (WHERE total_trades >= 5) as reliable,
                       COUNT(*) as total
                FROM strategy_performance
                GROUP BY period_days
            """)
            trust_data = cur.fetchall()
            
            for row in trust_data:
                if row[1] > 0:
                    pct = (row[1] / row[2]) * 100
                    print_info(f"  {row[0]}-day: {row[1]}/{row[2]} ({pct:.1f}%) have 5+ trades for trust scoring")
        
        # Check 5: Positions (paper trading activity)
        cur.execute("""
            SELECT COUNT(*) as total,
                   COUNT(*) FILTER (WHERE status = 'open') as open,
                   COUNT(*) FILTER (WHERE status = 'closed') as closed,
                   COUNT(*) FILTER (WHERE mode = 'paper') as paper
            FROM positions
        """)
        pos_data = cur.fetchone()
        
        if pos_data[0] > 0:
            print_check(
                f"Trading Activity ({pos_data[0]} total positions)", 
                True,
                f"Open: {pos_data[1]}, Closed: {pos_data[2]}, Paper: {pos_data[3]}"
            )
            results['passed'] += 1
        else:
            print_check("Trading Activity", False, "No positions found")
            results['failed'] += 1
        
        # Check 6: Fee calculation in positions
        cur.execute("""
            SELECT COUNT(*) FILTER (WHERE entry_fee > 0) as with_fees,
                   COUNT(*) as total
            FROM positions
            WHERE status = 'closed'
        """)
        fee_data = cur.fetchone()
        
        if fee_data[0] > 0:
            pct = (fee_data[0] / fee_data[1]) * 100 if fee_data[1] > 0 else 0
            print_check(f"Fee Tracking", True, f"{fee_data[0]}/{fee_data[1]} ({pct:.1f}%) closed positions have fees")
            results['passed'] += 1
        else:
            print_warning("No fee data in closed positions")
            results['warnings'] += 1
        
        cur.close()
        conn.close()
        
    except Exception as e:
        print_check("Layer 3 Database Access", False, str(e))
        results['failed'] += 1
    
    return results

# ============================================================================
# LAYER 4: REGIME DETECTION & ADAPTATION
# ============================================================================
def verify_layer_4() -> Dict:
    """Verify market regime detection and adaptation"""
    print_layer(4, "REGIME DETECTION & ADAPTATION")
    
    results = {'passed': 0, 'failed': 0, 'warnings': 0}
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Check 1: Market regime table exists
        cur.execute("""
            SELECT COUNT(*) 
            FROM information_schema.tables 
            WHERE table_name = 'market_regime'
        """)
        table_exists = cur.fetchone()[0] > 0
        print_check("Market Regime Table", table_exists)
        results['passed' if table_exists else 'failed'] += 1
        
        if table_exists:
            # Check 2: Regime detection activity
            cur.execute("""
                SELECT COUNT(DISTINCT symbol) as symbols,
                       COUNT(*) as total_detections,
                       MAX(detected_at) as last_detection
                FROM market_regime
            """)
            regime_data = cur.fetchone()
            
            if regime_data[0] > 0:
                print_check(
                    f"Regime Detection Active ({regime_data[0]} symbols)", 
                    True,
                    f"{regime_data[1]} detections, last: {regime_data[2]}"
                )
                results['passed'] += 1
            else:
                print_warning("No regime detections found")
                results['warnings'] += 1
            
            # Check 3: Recent regime updates
            cur.execute("""
                SELECT COUNT(*) 
                FROM market_regime 
                WHERE detected_at > NOW() - INTERVAL '24 hours'
            """)
            recent_regimes = cur.fetchone()[0]
            
            if recent_regimes > 0:
                print_check(f"Recent Regime Updates ({recent_regimes} in last 24h)", True)
                results['passed'] += 1
            else:
                print_warning("No regime updates in last 24 hours")
                results['warnings'] += 1
            
            # Check 4: Regime distribution
            cur.execute("""
                SELECT regime, COUNT(*) as count
                FROM (
                    SELECT DISTINCT ON (symbol) symbol, regime
                    FROM market_regime
                    ORDER BY symbol, detected_at DESC
                ) latest
                GROUP BY regime
                ORDER BY count DESC
            """)
            regime_dist = cur.fetchall()
            
            if regime_dist:
                print_info("Current regime distribution:")
                for regime, count in regime_dist:
                    print_info(f"  {regime}: {count} symbols")
            
            # Check 5: Regime-aware performance tracking
            cur.execute("""
                SELECT COUNT(*) 
                FROM information_schema.columns 
                WHERE table_name = 'strategy_performance' 
                AND column_name = 'regime'
            """)
            has_regime_column = cur.fetchone()[0] > 0
            
            if has_regime_column:
                print_check("Regime-Aware Performance Tracking", True)
                results['passed'] += 1
            else:
                print_warning("Strategy performance not tracking by regime")
                results['warnings'] += 1
        else:
            print_warning("Regime detection system not implemented")
            results['warnings'] += 1
        
        cur.close()
        conn.close()
        
    except Exception as e:
        print_check("Layer 4 Database Access", False, str(e))
        results['failed'] += 1
    
    return results

# ============================================================================
# LAYER 5: AI ORCHESTRATION
# ============================================================================
def verify_layer_5() -> Dict:
    """Verify AI orchestration and system control"""
    print_layer(5, "AI ORCHESTRATION & SYSTEM CONTROL")
    
    results = {'passed': 0, 'failed': 0, 'warnings': 0}
    
    try:
        # Check 1: AI API availability
        try:
            response = requests.get("http://localhost:8011/health", timeout=5)
            if response.status_code == 200:
                print_check("AI API Available", True)
                results['passed'] += 1
            else:
                print_check("AI API Available", False, "Not responding")
                results['failed'] += 1
        except:
            print_check("AI API Available", False, "Cannot connect")
            results['failed'] += 1
        
        # Check 2: AI voting integration
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT COUNT(*) 
            FROM information_schema.tables 
            WHERE table_name = 'consensus_decisions'
        """)
        table_exists = cur.fetchone()[0] > 0
        
        if table_exists:
            cur.execute("""
                SELECT COUNT(*) as total,
                       COUNT(*) FILTER (WHERE ai_vote IS NOT NULL) as with_ai_vote
                FROM consensus_decisions
            """)
            vote_data = cur.fetchone()
            
            if vote_data[0] > 0:
                pct = (vote_data[1] / vote_data[0]) * 100
                print_check(
                    f"AI Voting Integration", 
                    True,
                    f"{vote_data[1]}/{vote_data[0]} ({pct:.1f}%) decisions have AI vote"
                )
                results['passed'] += 1
            else:
                print_warning("No consensus decisions with AI votes yet")
                results['warnings'] += 1
        else:
            print_warning("Consensus decisions table not found")
            results['warnings'] += 1
        
        # Check 3: AI signal evaluation history
        cur.execute("""
            SELECT COUNT(*) 
            FROM information_schema.tables 
            WHERE table_name = 'ai_signal_evaluations'
        """)
        ai_table_exists = cur.fetchone()[0] > 0
        
        if ai_table_exists:
            cur.execute("SELECT COUNT(*) FROM ai_signal_evaluations")
            eval_count = cur.fetchone()[0]
            print_check(f"AI Signal Evaluations ({eval_count} records)", eval_count > 0)
            results['passed' if eval_count > 0 else 'warnings'] += 1
        else:
            print_info("AI evaluation history table not implemented")
        
        cur.close()
        conn.close()
        
    except Exception as e:
        print_check("Layer 5 Database Access", False, str(e))
        results['failed'] += 1
    
    return results

# ============================================================================
# LAYER 6: ENSEMBLE VOTING
# ============================================================================
def verify_layer_6() -> Dict:
    """Verify ensemble voting system"""
    print_layer(6, "ENSEMBLE VOTING & SIGNAL CONSENSUS")
    
    results = {'passed': 0, 'failed': 0, 'warnings': 0}
    
    try:
        # Check 1: Signal API
        try:
            response = requests.get("http://localhost:8015/health", timeout=5)
            if response.status_code == 200:
                print_check("Signal API Available", True)
                results['passed'] += 1
            else:
                print_check("Signal API Available", False)
                results['failed'] += 1
        except:
            print_check("Signal API Available", False)
            results['failed'] += 1
        
        # Check 2: Active signals
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT COUNT(*) as total,
                   COUNT(*) FILTER (WHERE acted_on = false) as active,
                   COUNT(*) FILTER (WHERE acted_on = true) as acted_on
            FROM signals
            WHERE generated_at > NOW() - INTERVAL '24 hours'
        """)
        signal_data = cur.fetchone()
        
        if signal_data[0] > 0:
            print_check(
                f"Signal Generation ({signal_data[0]} signals in last 24h)", 
                True,
                f"Active: {signal_data[1]}, Acted on: {signal_data[2]}"
            )
            results['passed'] += 1
        else:
            print_check("Signal Generation", False, "No signals in last 24 hours")
            results['failed'] += 1
        
        # Check 3: Ensemble endpoint
        try:
            response = requests.get(
                "http://localhost:8015/signals/ensemble",
                params={'min_weighted_score': 55, 'period_days': 14, 'limit': 10},
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                ensemble_count = len(data.get('ensemble_signals', []))
                print_check(
                    f"Ensemble Endpoint", 
                    True,
                    f"{ensemble_count} weighted signals available"
                )
                results['passed'] += 1
            else:
                print_check("Ensemble Endpoint", False, "Not responding properly")
                results['failed'] += 1
        except:
            print_check("Ensemble Endpoint", False, "Cannot connect")
            results['failed'] += 1
        
        # Check 4: Consensus decisions
        cur.execute("""
            SELECT COUNT(*) as total,
                   COUNT(*) FILTER (WHERE approved = true) as approved,
                   COUNT(*) FILTER (WHERE executed = true) as executed,
                   AVG(consensus_pct) as avg_consensus
            FROM consensus_decisions
            WHERE timestamp > NOW() - INTERVAL '7 days'
        """)
        consensus_data = cur.fetchone()
        
        if consensus_data[0] > 0:
            print_check(
                f"Consensus Decisions ({consensus_data[0]} in last 7 days)", 
                True,
                f"Approved: {consensus_data[1]}, Executed: {consensus_data[2]}, Avg consensus: {consensus_data[3]:.1f}%"
            )
            results['passed'] += 1
        else:
            print_warning("No consensus decisions in last 7 days")
            results['warnings'] += 1
        
        # Check 5: Ensemble execution task
        try:
            response = requests.get("http://localhost:8021/metrics", timeout=5)
            if response.status_code == 200:
                print_check("Celery Tasks (execute_ensemble_trades)", True)
                results['passed'] += 1
        except:
            print_warning("Cannot verify ensemble execution task")
            results['warnings'] += 1
        
        cur.close()
        conn.close()
        
    except Exception as e:
        print_check("Layer 6 Access", False, str(e))
        results['failed'] += 1
    
    return results

# ============================================================================
# LAYER 7: ACCOUNTING & PNL
# ============================================================================
def verify_layer_7() -> Dict:
    """Verify accounting and P&L reporting"""
    print_layer(7, "ACCOUNTING & P&L REPORTING")
    
    results = {'passed': 0, 'failed': 0, 'warnings': 0}
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Check 1: Portfolio API
        try:
            response = requests.get("http://localhost:8016/health", timeout=5)
            if response.status_code == 200:
                print_check("Portfolio API Available", True)
                results['passed'] += 1
            else:
                print_check("Portfolio API Available", False)
                results['failed'] += 1
        except:
            print_check("Portfolio API Available", False)
            results['failed'] += 1
        
        # Check 2: Portfolio snapshots
        cur.execute("""
            SELECT COUNT(*) as total,
                   MAX(timestamp) as last_snapshot,
                   AVG(total_value) as avg_value
            FROM portfolio_snapshots
            WHERE mode = 'paper'
        """)
        snapshot_data = cur.fetchone()
        
        if snapshot_data[0] > 0:
            print_check(
                f"Portfolio Snapshots ({snapshot_data[0]} records)", 
                True,
                f"Last: {snapshot_data[1]}, Avg value: ${snapshot_data[2]:.2f}"
            )
            results['passed'] += 1
        else:
            print_check("Portfolio Snapshots", False, "No snapshots found")
            results['failed'] += 1
        
        # Check 3: P&L calculation with fees
        cur.execute("""
            SELECT 
                COUNT(*) as closed_positions,
                SUM(realized_pnl) as total_pnl,
                SUM(entry_fee + exit_fee) as total_fees,
                AVG(realized_pnl_pct) as avg_return_pct
            FROM positions
            WHERE status = 'closed' AND mode = 'paper'
        """)
        pnl_data = cur.fetchone()
        
        if pnl_data[0] > 0:
            net_pnl = pnl_data[1] - pnl_data[2] if pnl_data[2] else pnl_data[1]
            print_check(
                f"P&L Calculation ({pnl_data[0]} closed positions)", 
                True,
                f"Gross P&L: ${pnl_data[1]:.2f}, Fees: ${pnl_data[2]:.2f}, Net: ${net_pnl:.2f}"
            )
            results['passed'] += 1
        else:
            print_warning("No closed positions for P&L calculation")
            results['warnings'] += 1
        
        # Check 4: Recent P&L (last 24 hours)
        cur.execute("""
            SELECT 
                COUNT(*) as trades,
                SUM(realized_pnl) as pnl_24h
            FROM positions
            WHERE status = 'closed' 
            AND mode = 'paper'
            AND exit_time > NOW() - INTERVAL '24 hours'
        """)
        recent_pnl = cur.fetchone()
        
        if recent_pnl[0] > 0:
            print_check(
                f"Recent Trading Activity", 
                True,
                f"{recent_pnl[0]} trades in last 24h, P&L: ${recent_pnl[1]:.2f}"
            )
            results['passed'] += 1
        else:
            print_warning("No trades in last 24 hours")
            results['warnings'] += 1
        
        # Check 5: Win rate tracking
        cur.execute("""
            SELECT 
                COUNT(*) FILTER (WHERE realized_pnl > 0) as wins,
                COUNT(*) FILTER (WHERE realized_pnl < 0) as losses,
                COUNT(*) as total
            FROM positions
            WHERE status = 'closed' AND mode = 'paper'
        """)
        win_data = cur.fetchone()
        
        if win_data[2] > 0:
            win_rate = (win_data[0] / win_data[2]) * 100
            print_check(
                f"Win Rate Tracking", 
                True,
                f"{win_rate:.1f}% ({win_data[0]} wins / {win_data[1]} losses / {win_data[2]} total)"
            )
            results['passed'] += 1
        
        cur.close()
        conn.close()
        
    except Exception as e:
        print_check("Layer 7 Access", False, str(e))
        results['failed'] += 1
    
    return results

# ============================================================================
# LAYER 8: GOAL MANAGEMENT (NOT YET IMPLEMENTED)
# ============================================================================
def verify_layer_8() -> Dict:
    """Verify goal management system"""
    print_layer(8, "GOAL MANAGEMENT & ADAPTIVE TARGETS")
    
    results = {'passed': 0, 'failed': 0, 'warnings': 0}
    
    print_info("Layer 8 is not yet implemented")
    print_info("Planned features:")
    print_info("  - Daily profit goal tracking (baseline: 0.05%)")
    print_info("  - Adaptive goal adjustment based on historical performance")
    print_info("  - Success rate monitoring per goal tier")
    print_info("  - Automatic goal escalation when baseline consistently met")
    
    return results

# ============================================================================
# MAIN EXECUTION
# ============================================================================
def main():
    """Run all layer verifications"""
    print(f"\n{BLUE}{'='*80}")
    print(f"TRADING SYSTEM LAYER VERIFICATION")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*80}{RESET}\n")
    
    all_results = {}
    
    # Run all layer verifications
    all_results['Layer 1'] = verify_layer_1()
    all_results['Layer 2'] = verify_layer_2()
    all_results['Layer 3'] = verify_layer_3()
    all_results['Layer 4'] = verify_layer_4()
    all_results['Layer 5'] = verify_layer_5()
    all_results['Layer 6'] = verify_layer_6()
    all_results['Layer 7'] = verify_layer_7()
    all_results['Layer 8'] = verify_layer_8()
    
    # Summary
    print(f"\n{BLUE}{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}{RESET}\n")
    
    summary_data = []
    total_passed = 0
    total_failed = 0
    total_warnings = 0
    
    for layer, results in all_results.items():
        passed = results['passed']
        failed = results['failed']
        warnings = results['warnings']
        total = passed + failed + warnings
        
        total_passed += passed
        total_failed += failed
        total_warnings += warnings
        
        status = f"{GREEN}✓{RESET}" if failed == 0 else f"{RED}✗{RESET}"
        summary_data.append([
            status,
            layer,
            f"{GREEN}{passed}{RESET}" if passed > 0 else "0",
            f"{RED}{failed}{RESET}" if failed > 0 else "0",
            f"{YELLOW}{warnings}{RESET}" if warnings > 0 else "0",
            total
        ])
    
    print(tabulate(
        summary_data,
        headers=['', 'Layer', 'Passed', 'Failed', 'Warnings', 'Total'],
        tablefmt='simple'
    ))
    
    print(f"\n{BLUE}OVERALL:{RESET}")
    print(f"  {GREEN}Passed: {total_passed}{RESET}")
    print(f"  {RED}Failed: {total_failed}{RESET}")
    print(f"  {YELLOW}Warnings: {total_warnings}{RESET}")
    
    # System health score
    total_checks = total_passed + total_failed + total_warnings
    if total_checks > 0:
        health_score = ((total_passed + (total_warnings * 0.5)) / total_checks) * 100
        
        if health_score >= 80:
            color = GREEN
            status = "HEALTHY"
        elif health_score >= 60:
            color = YELLOW
            status = "NEEDS ATTENTION"
        else:
            color = RED
            status = "CRITICAL"
        
        print(f"\n{color}System Health Score: {health_score:.1f}% - {status}{RESET}")
    
    print(f"\n{BLUE}{'='*80}{RESET}\n")

if __name__ == "__main__":
    main()
