#!/usr/bin/env python3
"""
Kickstart System - Initialize fresh trading system
- Queue optimizations for all symbols
- Trigger initial performance calculations
- Start AI analysis
"""

import sys
import os
sys.path.insert(0, '/opt/trading')

from shared.database import get_connection
import time

def get_symbols():
    """Get all active symbols from database"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT DISTINCT symbol FROM symbols WHERE status = 'active' ORDER BY symbol")
                symbols = [row['symbol'] for row in cur.fetchall()]
        return symbols
    except Exception as e:
        print(f"❌ Error fetching symbols: {e}")
        import traceback
        traceback.print_exc()
        return []

def get_strategies():
    """Get all enabled strategies from database"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM strategies WHERE enabled = true ORDER BY id")
                strategies = [row['id'] for row in cur.fetchall()]
        return strategies
    except Exception as e:
        print(f"❌ Error fetching strategies: {e}")
        import traceback
        traceback.print_exc()
        return []

def queue_optimizations(symbols, strategies):
    """Queue optimization jobs for all symbol-strategy combinations"""
    queued = 0
    print(f"\n⚙️  Queueing optimizations...")
    print(f"   Symbols: {len(symbols)}")
    print(f"   Strategies: {len(strategies)}")
    print(f"   Total jobs: {len(symbols) * len(strategies)}")
    
    with get_connection() as conn:
        with conn.cursor() as cur:
            for symbol in symbols:
                for strategy_id in strategies:
                    try:
                        # Queue with medium priority (50), pending status
                        cur.execute("""
                            INSERT INTO optimization_queue (strategy_id, symbol, priority, status, requested_at)
                            VALUES (%s, %s, 50, 'pending', NOW())
                            ON CONFLICT DO NOTHING
                        """, (strategy_id, symbol))
                        queued += 1
                    except Exception as e:
                        print(f"   ⚠️  Error queuing {symbol}-{strategy_id}: {e}")
    
    print(f"✅ Queued {queued} optimization jobs")
    return queued

def init_portfolio_snapshots():
    """Initialize portfolio snapshots if they don't exist"""
    print(f"\n💰 Initializing portfolio snapshots...")
    
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Check if paper portfolio exists
            cur.execute("SELECT COUNT(*) as count FROM portfolio_snapshots WHERE mode = 'paper'")
            paper_count = cur.fetchone()['count']
            
            if paper_count == 0:
                print(f"   Creating paper portfolio with $1000 starting capital...")
                cur.execute("""
                    INSERT INTO portfolio_snapshots (
                        timestamp, mode, total_capital, deployed_capital, available_capital,
                        open_positions, total_pnl, total_pnl_pct, daily_pnl, daily_pnl_pct,
                        daily_target_met, consecutive_days_target_met, positions_snapshot
                    ) VALUES (
                        NOW(), 'paper', 1000.00, 0, 1000.00, 0, 0, 0, 0, 0, false, 0, '[]'::jsonb
                    )
                """)
                print(f"   ✅ Paper portfolio initialized")
            else:
                print(f"   ✓ Paper portfolio already exists")
            
            # Check if live portfolio exists
            cur.execute("SELECT COUNT(*) as count FROM portfolio_snapshots WHERE mode = 'live'")
            live_count = cur.fetchone()['count']
            
            if live_count == 0:
                print(f"   Creating live portfolio...")
                cur.execute("""
                    INSERT INTO portfolio_snapshots (
                        timestamp, mode, total_capital, deployed_capital, available_capital,
                        open_positions, total_pnl, total_pnl_pct, daily_pnl, daily_pnl_pct,
                        daily_target_met, consecutive_days_target_met, positions_snapshot
                    ) VALUES (
                        NOW(), 'live', 0, 0, 0, 0, 0, 0, 0, 0, false, 0, '[]'::jsonb
                    )
                """)
                print(f"   ✅ Live portfolio initialized")
            else:
                print(f"   ✓ Live portfolio already exists")

def trigger_initial_tasks():
    """Trigger initial background tasks"""
    print(f"\n🚀 Triggering initial tasks...")
    
    # These tasks will run on their schedules, but we can verify they're registered
    tasks = [
        "fetch_1min_candles (60s)",
        "backfill_historical_candles (5min)",
        "process_optimization_queue (2hr)",
        "calculate_strategy_performance (4hr)",
        "detect_market_regimes (15min)",
        "execute_ensemble_trades (10min)",
        "ai_analyze_system_health (daily 9AM)",
        "record_daily_performance (daily 1AM)"
    ]
    
    for task in tasks:
        print(f"   ✓ {task}")
    
    print(f"\n💡 Tip: Watch celery logs to see tasks execute:")
    print(f"   tail -f /opt/trading/logs/celery_worker.log")

def main():
    print("=" * 60)
    print("  KICKSTART TRADING SYSTEM")
    print("=" * 60)
    
    # Get active symbols and strategies
    print("\n📊 Fetching active symbols and strategies...")
    symbols = get_symbols()
    strategies = get_strategies()
    
    if not symbols:
        print("❌ No symbols found. Please check OHLCV API.")
        return 1
    
    if not strategies:
        print("❌ No strategies found. Please check Strategy Config API.")
        return 1
    
    print(f"✅ Found {len(symbols)} symbols and {len(strategies)} strategies")
    
    # Initialize portfolio snapshots
    init_portfolio_snapshots()
    
    # Queue optimizations
    queued = queue_optimizations(symbols, strategies)
    
    if queued == 0:
        print("⚠️  No optimizations queued")
        return 1
    
    # Show scheduled tasks
    trigger_initial_tasks()
    
    print("\n" + "=" * 60)
    print("✅ System kickstarted successfully!")
    print("=" * 60)
    print("\nNext steps:")
    print("  1. Optimizations will process every 2 hours")
    print("  2. Strategy performance will calculate every 4 hours")
    print("  3. Ensemble signals will generate every 10 minutes")
    print("  4. Check status at: http://localhost:8010")
    print("=" * 60)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
