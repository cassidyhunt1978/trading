#!/usr/bin/env python3
"""
Phase 5: Multi-Timeframe Confirmation
Add timeframe column and create aggregated candles
"""
import sys
sys.path.append('/opt/trading')

from shared.database import get_connection

def setup_multi_timeframe():
    """Add timeframe support to ohlcv_candles table"""
    
    print("=" * 70)
    print("Phase 5: Multi-Timeframe Confirmation Setup")
    print("=" * 70)
    
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Check current schema
            print("1. Checking ohlcv_candles schema...")
            cur.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'ohlcv_candles'
                ORDER BY ordinal_position
            """)
            columns = [row['column_name'] for row in cur.fetchall()]
            print(f"   Current columns: {columns}")
            
            # Add timeframe column if it doesn't exist
            if 'timeframe' not in columns:
                print("2. Adding timeframe column...")
                cur.execute("""
                    ALTER TABLE ohlcv_candles
                    ADD COLUMN timeframe TEXT DEFAULT '1m';
                """)
                print("   ✓ Timeframe column added")
            else:
                print("2. Timeframe column already exists")
            
            # Update existing rows to have '1m' timeframe
            print("3. Updating existing candles to 1m timeframe...")
            cur.execute("""
                UPDATE ohlcv_candles
                SET timeframe = '1m'
                WHERE timeframe IS NULL OR timeframe = '';
            """)
            updated = cur.rowcount
            print(f"   ✓ Updated {updated} candles")
            
            # Create indexes for efficient timeframe queries
            print("4. Creating timeframe indexes...")
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_ohlcv_timeframe
                ON ohlcv_candles(symbol, timeframe, timestamp DESC);
            """)
            print("   ✓ Timeframe index created")
            
            # Drop old unique constraint if exists and recreate with timeframe
            print("5. Updating unique constraint to include timeframe...")
            try:
                cur.execute("""
                    ALTER TABLE ohlcv_candles
                    DROP CONSTRAINT IF EXISTS ohlcv_candles_symbol_timestamp_key;
                """)
                cur.execute("""
                    ALTER TABLE ohlcv_candles
                    ADD CONSTRAINT ohlcv_candles_symbol_timeframe_timestamp_key
                    UNIQUE (symbol, timeframe, timestamp);
                """)
                print("   ✓ Unique constraint updated")
            except Exception as e:
                print(f"   ⚠ Constraint update: {e}")
    
    print("=" * 70)
    print("✅ Phase 5 multi-timeframe setup complete!")
    print("=" * 70)

if __name__ == "__main__":
    setup_multi_timeframe()
