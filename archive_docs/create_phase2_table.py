#!/usr/bin/env python3
"""Create strategy_performance table for Phase 2"""
import sys
sys.path.append('/opt/trading')

from shared.database import get_connection

print("="*70)
print("Phase 2: Strategy Performance Tracking")
print("="*70)

try:
    with get_connection() as conn:
        with conn.cursor() as cur:
            print("\n1. Creating strategy_performance table...")
            
            cur.execute("""
                CREATE TABLE IF NOT EXISTS strategy_performance (
                    id SERIAL PRIMARY KEY,
                    strategy_id INTEGER REFERENCES strategies(id),
                    symbol TEXT NOT NULL,
                    period_days INTEGER NOT NULL,  -- 7, 14, or 30 day window
                    period_start TIMESTAMPTZ NOT NULL,
                    period_end TIMESTAMPTZ NOT NULL,
                    
                    -- Signal metrics
                    total_signals INTEGER DEFAULT 0,
                    signals_acted_on INTEGER DEFAULT 0,
                    
                    -- Trade metrics
                    total_trades INTEGER DEFAULT 0,
                    winning_trades INTEGER DEFAULT 0,
                    losing_trades INTEGER DEFAULT 0,
                    win_rate NUMERIC(5,2) DEFAULT 0,
                    
                    -- Profitability metrics
                    total_pnl NUMERIC(20,8) DEFAULT 0,
                    avg_profit_pct NUMERIC(10,4) DEFAULT 0,
                    max_profit_pct NUMERIC(10,4) DEFAULT 0,
                    max_loss_pct NUMERIC(10,4) DEFAULT 0,
                    
                    -- Risk metrics
                    sharpe_ratio NUMERIC(10,4),
                    profit_factor NUMERIC(10,4),
                    
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    
                    UNIQUE(strategy_id, symbol, period_days)
                )
            """)
            print("   ✓ Table created")
            
            print("\n2. Creating indexes...")
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_strategy_perf_strategy 
                ON strategy_performance(strategy_id)
            """)
            
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_strategy_perf_symbol 
                ON strategy_performance(symbol)
            """)
            
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_strategy_perf_win_rate 
                ON strategy_performance(win_rate DESC)
            """)
            
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_strategy_perf_updated 
                ON strategy_performance(updated_at DESC)
            """)
            print("   ✓ Indexes created")
            
            conn.commit()
            
            print("\n" + "="*70)
            print("✅ Phase 2 table setup complete!")
            print("="*70)
            print("\nNext steps:")
            print("  1. Add calculation function")
            print("  2. Add Celery scheduled task")
            print("  3. Add UI display")
            
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
