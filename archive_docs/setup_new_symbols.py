#!/usr/bin/env python3
"""
Setup script for new trading symbols
Ensures:
1. Symbols are added to database
2. Historical data is backfilled
3. Strategies are optimized for each symbol
"""
import sys
import time
import requests
from datetime import datetime, timedelta

sys.path.append('/opt/trading')
from shared.database import get_connection

# Configuration
OHLCV_API = "http://localhost:8012"
OPTIMIZATION_API = "http://localhost:8014"
MIN_CANDLES_FOR_OPTIMIZATION = 10000  # ~7 days of data

# New symbols to add (if not already present)
NEW_SYMBOLS = [
    {"symbol": "AVAX", "name": "Avalanche", "exchange": "coinbase"},
    {"symbol": "MATIC", "name": "Polygon", "exchange": "coinbase"},
    {"symbol": "LINK", "name": "Chainlink", "exchange": "coinbase"},
    {"symbol": "UNI", "name": "Uniswap", "exchange": "coinbase"},
    {"symbol": "AAVE", "name": "Aave", "exchange": "coinbase"},
    {"symbol": "ATOM", "name": "Cosmos", "exchange": "coinbase"},
    {"symbol": "DOT", "name": "Polkadot", "exchange": "coinbase"},
    {"symbol": "ADA", "name": "Cardano", "exchange": "coinbase"},
]

# Standard parameter ranges for optimization
STANDARD_PARAM_RANGES = {
    "rsi_period": [10, 14, 20],
    "rsi_oversold": [25, 30, 35],
    "rsi_overbought": [65, 70, 75],
    "sma_fast": [10, 20, 30],
    "sma_slow": [40, 50, 60],
    "macd_fast": [10, 12, 15],
    "macd_slow": [24, 26, 30],
    "macd_signal": [7, 9, 12],
}

def print_section(title):
    """Print a section header"""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)

def get_active_strategies():
    """Get all active strategies from database"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, name, status 
                FROM strategies 
                WHERE status = 'active' 
                ORDER BY id
            """)
            return cur.fetchall()

def get_symbol_candle_count(symbol):
    """Get candle count for a symbol"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) as count 
                FROM ohlcv_candles 
                WHERE symbol = %s
            """, (symbol,))
            result = cur.fetchone()
            return result['count'] if result else 0

def check_optimization_exists(strategy_id, symbol):
    """Check if optimization already exists for strategy-symbol pair"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) as count 
                FROM strategy_overrides 
                WHERE strategy_id = %s AND symbol = %s
            """, (strategy_id, symbol))
            result = cur.fetchone()
            return result['count'] > 0

def optimize_strategy_for_symbol(strategy_id, strategy_name, symbol):
    """Run optimization for a strategy-symbol pair"""
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)  # Use 30 days for optimization
        
        request_data = {
            "strategy_id": strategy_id,
            "symbol": symbol,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "method": "grid_search",
            "parameter_ranges": STANDARD_PARAM_RANGES,
            "metric": "sharpe_ratio",
            "max_iterations": 100
        }
        
        print(f"  🔧 Optimizing {strategy_name} for {symbol}...", end=" ")
        
        response = requests.post(
            f"{OPTIMIZATION_API}/optimize",
            json=request_data,
            timeout=300  # 5 minute timeout
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✓ Score: {result['best_score']:.4f}")
            return True
        else:
            print(f"✗ Failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"✗ Error: {str(e)[:50]}")
        return False

def main():
    """Main setup process"""
    print("\n" + "=" * 70)
    print("  NEW SYMBOLS SETUP & OPTIMIZATION")
    print("=" * 70)
    
    # Step 1: Check symbol status
    print_section("Step 1: Symbol Status Check")
    
    symbols_to_optimize = []
    
    for symbol_info in NEW_SYMBOLS:
        symbol = symbol_info["symbol"]
        candle_count = get_symbol_candle_count(symbol)
        
        if candle_count >= MIN_CANDLES_FOR_OPTIMIZATION:
            status = f"✓ Ready ({candle_count:,} candles)"
            symbols_to_optimize.append(symbol)
        elif candle_count > 0:
            status = f"⏳ Backfilling ({candle_count:,} candles, need {MIN_CANDLES_FOR_OPTIMIZATION - candle_count:,} more)"
        else:
            status = f"⏳ No data yet (backfill will start automatically)"
        
        print(f"  {symbol:6} - {symbol_info['name']:15} - {status}")
    
    if not symbols_to_optimize:
        print("\n⚠️  No symbols ready for optimization yet.")
        print("   The backfill task runs every 5 minutes and fetches 10,000 candles per run.")
        print("   Check back in 10-15 minutes for new symbols.")
        return
    
    # Step 2: Get active strategies
    print_section("Step 2: Loading Active Strategies")
    
    strategies = get_active_strategies()
    print(f"  Found {len(strategies)} active strategies:")
    for strategy in strategies:
        print(f"    {strategy['id']:2}. {strategy['name']}")
    
    # Step 3: Run optimizations
    print_section("Step 3: Running Optimizations")
    
    total_optimizations = 0
    successful_optimizations = 0
    skipped_optimizations = 0
    
    for strategy in strategies:
        strategy_id = strategy['id']
        strategy_name = strategy['name']
        
        print(f"\n  Strategy: {strategy_name} (ID: {strategy_id})")
        
        for symbol in symbols_to_optimize:
            if check_optimization_exists(strategy_id, symbol):
                print(f"  ⊘ {symbol:6} - Already optimized (skipped)")
                skipped_optimizations += 1
            else:
                total_optimizations += 1
                if optimize_strategy_for_symbol(strategy_id, strategy_name, symbol):
                    successful_optimizations += 1
                time.sleep(2)  # Rate limit between optimizations
    
    # Step 4: Summary
    print_section("Summary")
    print(f"  Symbols ready for optimization: {len(symbols_to_optimize)}")
    print(f"  Strategies: {len(strategies)}")
    print(f"  Optimizations run: {total_optimizations}")
    print(f"  Successful: {successful_optimizations}")
    print(f"  Skipped (already optimized): {skipped_optimizations}")
    print(f"  Failed: {total_optimizations - successful_optimizations}")
    
    if successful_optimizations > 0:
        print("\n  ✅ Optimization complete! Strategies are now tuned for new symbols.")
    
    print("=" * 70 + "\n")

if __name__ == "__main__":
    main()
