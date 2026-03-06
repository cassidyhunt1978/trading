#!/usr/bin/env python3
"""
Phase 4: Market Regime Detection
Create market_regime table to store regime classifications for each symbol
"""
import sys
sys.path.append('/opt/trading')

from shared.database import get_connection

def create_market_regime_table():
    """Create table for storing market regime classifications"""
    
    print("=" * 70)
    print("Phase 4: Market Regime Detection")
    print("=" * 70)
    
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Create market_regime table
            print("1. Creating market_regime table...")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS market_regime (
                    id SERIAL PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    regime TEXT NOT NULL,  -- 'trending_up', 'trending_down', 'ranging', 'volatile'
                    confidence NUMERIC(5,2) NOT NULL,  -- 0-100
                    atr NUMERIC(20,8),  -- Average True Range
                    adx NUMERIC(10,4),  -- Average Directional Index
                    trend_slope NUMERIC(10,6),  -- Linear regression slope
                    volatility_pct NUMERIC(10,4),  -- Volatility percentage
                    detected_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    metadata JSONB  -- Additional metrics
                );
            """)
            print("   ✓ Table created")
            
            # Create indexes
            print("2. Creating indexes...")
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_market_regime_symbol 
                ON market_regime(symbol);
            """)
            
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_market_regime_updated 
                ON market_regime(updated_at DESC);
            """)
            
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_market_regime_symbol_unique
                ON market_regime(symbol);
            """)
            print("   ✓ Indexes created")
            
            # Add regime_preference column to strategies table
            print("3. Adding regime_preference to strategies table...")
            cur.execute("""
                ALTER TABLE strategies 
                ADD COLUMN IF NOT EXISTS regime_preference TEXT[];
            """)
            print("   ✓ Column added")
            
    print("=" * 70)
    print("✅ Phase 4 table setup complete!")
    print("=" * 70)

if __name__ == "__main__":
    create_market_regime_table()
