# New Trading Symbols Setup Summary

## Symbols Added Successfully ✓

The following 8 new symbols have been added to the trading system:

1. **AAVE** (Aave) - DeFi lending protocol
2. **ADA** (Cardano) - Smart contract platform
3. **ATOM** (Cosmos) - Interoperability protocol  
4. **AVAX** (Avalanche) - High-performance smart contract platform
5. **DOT** (Polkadot) - Multi-chain protocol
6. **LINK** (Chainlink) - Decentralized oracle network
7. **MATIC** (Polygon) - Ethereum scaling solution
8. **UNI** (Uniswap) - Decentralized exchange protocol

Total symbols now: **11** (including BTC, ETH, SOL)

## Automated Processes Running

### 1. Historical Data Backfill ⏳

**Status**: Running automatically every 5 minutes

- **Task**: `backfill_historical_candles`
- **Schedule**: Every 5 minutes via Celery Beat
- **Target**: 180 days of 1-minute candles (259,200 candles per symbol)
- **Rate**: 10,000 candles per run (20 batches × 500 candles)
- **Progress**: 
  - AAVE: ~1,630 candles fetched (as of last check)
  - Other symbols: Just started

**Estimated Time**: 
- Each symbol needs 26 runs to complete (26 × 10,000 = 260,000 candles)
- At 5-minute intervals = ~2 hours per symbol
- With 8 new symbols processing sequentially = **12-16 hours** for full backfill

The backfill will continue automatically in the background until all symbols reach 259,200 candles.

### 2. Real-Time Data Fetching ✓

**Status**: Active for all symbols

- **Task**: `fetch_1min_candles`
- **Schedule**: Every 1 minute via Celery Beat
- **Action**: Fetches latest 1-minute candles for ALL active symbols
- **Result**: New symbols are getting real-time data immediately

### 3. Indicator Computation ✓

**Status**: Active for all symbols

- **Task**: `compute_indicators`
- **Schedule**: Every 2 minutes via Celery Beat
- **Indicators Computed**:
  - RSI (Relative Strength Index)
  - MACD (Moving Average Convergence Divergence)
  - Bollinger Bands
  - SMA (Simple Moving Averages)
- **Fix Applied**: Indicators now properly **merge** instead of overwriting each other

### 4. Signal Generation ✓

**Status**: Active for all symbols

- **Task**: `generate_signals`
- **Schedule**: Every 5 minutes via Celery Beat
- **Process**: Evaluates all 33 strategy-symbol combinations
- **Status**: Working correctly (currently no signals due to neutral RSI values)

## Strategy Optimization Setup

### Optimization Script Created

**Location**: `/opt/trading/setup_new_symbols.py`

**Features**:
- Checks which symbols have enough data (minimum 10,000 candles)
- Gets all active strategies from database
- Runs grid search optimization for each strategy-symbol pair
- Saves optimized parameters to `strategy_overrides` table
- Skips already-optimized combinations
- Provides detailed progress reporting

**To Run Manually**:
```bash
cd /opt/trading
source venv/bin/activate
PYTHONPATH=/opt/trading python3 setup_new_symbols.py
```

**When to Run**:
- Wait until symbols have at least 10,000 candles (~7 days of data)
- For optimal results, wait for full 180-day backfill
- Can be re-run safely - skips already-optimized pairs

### Optimization Parameters

The script uses these parameter ranges for grid search:

```python
{
    "rsi_period": [10, 14, 20],
    "rsi_oversold": [25, 30, 35],
    "rsi_overbought": [65, 70, 75],
    "sma_fast": [10, 20, 30],
    "sma_slow": [40, 50, 60],
    "macd_fast": [10, 12, 15],
    "macd_slow": [24, 26, 30],
    "macd_signal": [7, 9, 12],
}
```

This creates **2,187** parameter combinations per strategy-symbol pair.
With grid search using 30 days of data, each optimization takes ~3-5 minutes.

## Manual Optimization Process

If you want to optimize strategies immediately (before full backfill completes):

### Option 1: Use the Automation Script

```bash
cd /opt/trading
source venv/bin/activate
PYTHONPATH=/opt/trading python3 setup_new_symbols.py
```

This will:
1. Check which symbols have enough data
2. Optimize all strategies for ready symbols
3. Skip symbols still backfilling

### Option 2: Manual Optimization via API

For a specific strategy-symbol pair:

```bash
curl -X POST http://localhost:8014/optimize \
  -H "Content-Type: application/json" \
  -d '{
    "strategy_id": 1,
    "symbol": "AAVE",
    "start_date": "2026-01-15T00:00:00",
    "end_date": "2026-02-15T00:00:00",
    "method": "grid_search",
    "parameter_ranges": {
      "rsi_period": [10, 14, 20],
      "rsi_oversold": [25, 30, 35],
      "rsi_overbought": [65, 70, 75]
    },
    "metric": "sharpe_ratio",
    "max_iterations": 100
  }'
```

## Monitoring Progress

### Check Backfill Status

```bash
sudo -u postgres psql -d trading_system -c \
  "SELECT symbol, COUNT(*) as candles 
   FROM ohlcv_candles 
   GROUP BY symbol 
   ORDER BY symbol;"
```

### Check Celery Logs

```bash
# Backfill progress
tail -f /opt/trading/logs/celery_worker.log | grep backfill

# Indicator computation
tail -f /opt/trading/logs/celery_worker.log | grep compute_indicators

# Signal generation
tail -f /opt/trading/logs/celery_worker.log | grep generate_signals
```

### Check Optimization Status

```bash
sudo -u postgres psql -d trading_system -c \
  "SELECT strategy_id, symbol, created_at 
   FROM strategy_overrides 
   ORDER BY created_at DESC 
   LIMIT 20;"
```

## System Health Check

All services are running and healthy:

- ✅ **OHLCV API** (port 8012) - Fetching market data
- ✅ **Signal API** (port 8015) - Generating signals  
- ✅ **Optimization API** (port 8014) - Ready for optimizations
- ✅ **Celery Workers** - Processing background tasks
- ✅ **Celery Beat** - Scheduling automated tasks
- ✅ **UI Server** (port 8010) - Displaying data

## Summary

✅ **What's Done**:
1. 8 new symbols added to database
2. Backfill task running automatically
3. Real-time data fetching active
4. Indicators computing with merge fix applied
5. Signal generation working correctly
6. Optimization API ready and tested

⏳ **What's In Progress**:
1. Historical data backfill (will complete in 12-16 hours)
2. Indicators being computed for new candles as they arrive

📋 **What's Ready When You Are**:
1. Strategy optimization script ready to run
2. Can optimize strategies once symbols have 10,000+ candles
3. For best results, wait for full 180-day backfill

## Next Steps

**Immediate** (Do Now):
- ✅ System will automatically handle data collection
- ✅ No action required - everything is automated

**In 2-4 Hours** (When AAVE has 20,000+ candles):
```bash
cd /opt/trading && python3 setup_new_symbols.py
```
This will optimize strategies for AAVE (the fastest-backfilling symbol).

**In 12-16 Hours** (When all symbols complete backfill):
```bash
cd /opt/trading && python3 setup_new_symbols.py
```
This will optimize strategies for all remaining symbols.

**Optional**: Set up a cron job to run optimization weekly:
```bash
# Add to crontab
0 2 * * 0 cd /opt/trading && /opt/trading/venv/bin/python3 setup_new_symbols.py >> /opt/trading/logs/optimization.log 2>&1
```

## Verification Commands

Check everything is working:

```bash
# Count symbols
echo "Symbols: $(sudo -u postgres psql -d trading_system -t -c 'SELECT COUNT(*) FROM symbols WHERE status = '\''active'\'';')"

# Check backfill progress
sudo -u postgres psql -d trading_system -c "SELECT symbol, COUNT(*) FROM ohlcv_candles GROUP BY symbol ORDER BY symbol;"

# Check running processes
ps aux | grep -E "celery|ohlcv_api|signal_api|optimization_api" | grep -v grep | wc -l
echo "Should see 10+ processes running"

# Test APIs
curl -s http://localhost:8012/health && echo " ← OHLCV API"
curl -s http://localhost:8014/health && echo " ← Optimization API"
curl -s http://localhost:8015/health && echo " ← Signal API"
```

All systems operational! 🚀
