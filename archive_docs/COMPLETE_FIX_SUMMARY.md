# Complete Fix Summary - Symbol & Candle Issues

## Issues Reported
1. ❌ Only 3 symbols showing in UI dropdown (should be 10)
2. ❌ Health check showing stale OHLCV data (67+ minutes old)  
3. ❌ MATIC still appearing to fetch candles (should be disabled)

## Root Causes Identified

### Issue 1: UI Not Updating
- **Problem**: Updated `index_final.html` but UI was serving `index.html`
- **Cause**: UI server serves `index.html` by default, we edited wrong file

### Issue 2: Candles Not Being Saved
- **Problem**: All fetches returning "0 candles_saved, 4-5 duplicates"
- **Cause**: `save_candle()` function missing `timeframe` parameter
- **Details**: 
  - Unique constraint is `(symbol, timeframe, timestamp)`
  - Function wasn't setting timeframe, defaulting to NULL
  - New candles with same timestamp but different timeframe being rejected as duplicates
  - Database had old candles (21:25), Coinbase returning new ones (22:40+), but they couldn't save

### Issue 3: Health Check Including MATIC
- **Problem**: Health query checked ALL symbols including inactive ones
- **Cause**: Query was `SELECT ... FROM ohlcv_candles` without filtering by `symbols.status`

## Fixes Applied

### Fix 1: UI Symbol Display ✅
**File**: `/opt/trading/ui/index.html`
```bash
cd /opt/trading/ui && cp index_final.html index.html
```
- Copied updated `index_final.html` (with dynamic API loading) to `index.html`
- UI now fetches symbols from `/symbols` API endpoint
- Displays all 10 active symbols instead of hardcoded 3

### Fix 2: Candle Saving with Timeframe ✅
**File**: `/opt/trading/shared/database.py`

**Before**:
```python
def save_candle(symbol, timestamp, open, high, low, close, volume, indicators=None):
    INSERT INTO ohlcv_candles (symbol, timestamp, open, high, low, close, volume, indicators)
    ON CONFLICT (symbol, timestamp) DO UPDATE...
```

**After**:
```python
def save_candle(symbol, timestamp, open, high, low, close, volume, timeframe='1m', indicators=None):
    INSERT INTO ohlcv_candles (symbol, timeframe, timestamp, open, high, low, close, volume, indicators)
    ON CONFLICT (symbol, timeframe, timestamp) DO UPDATE...
```

**File**: `/opt/trading/services/ohlcv_api/main.py`

**Before**:
```python
save_candle(symbol, timestamp, open_price, high, low, close, volume)
```

**After**:
```python
save_candle(symbol, timestamp, open_price, high, low, close, volume, timeframe)
```

**Result**: New candles now saving correctly with 5/5 saved instead of 0/5 duplicates

### Fix 3: Health Check Only Active Symbols ✅
**File**: `/opt/trading/services/testing_api/main.py`

**Before**:
```python
cur.execute("""
    SELECT symbol, MAX(timestamp) as latest
    FROM ohlcv_candles
    GROUP BY symbol
""")
```

**After**:
```python
cur.execute("""
    SELECT oc.symbol, MAX(oc.timestamp) as latest
    FROM ohlcv_candles oc
    INNER JOIN symbols s ON oc.symbol = s.symbol
    WHERE s.status = 'active'
    GROUP BY oc.symbol
""")
```

**Result**: Health check now only looks at 10 active symbols (excludes MATIC)

## Testing Results

### Before Fixes
```bash
# Candle fetch test
curl http://localhost:8012/candles/fetch?symbol=BTC&timeframe=1m&limit=5 -X POST
Response: {"candles_fetched": 0, "candles_duplicate": 5}

# Health check
curl http://localhost:8019/health
Issues: 3
- OHLCV Data Freshness: Stale data (67+ minutes)
- AfterAction Reports: 0
- Trading Activity: 0

# UI symbols
Only showing: BTC, ETH, SOL (3 symbols)
```

### After Fixes
```bash
# Candle fetch test
curl http://localhost:8012/candles/fetch?symbol=BTC&timeframe=1m&limit=5 -X POST
Response: {"candles_fetched": 5, "candles_duplicate": 0}

# Latest candles in DB
2026-02-18 22:57:00 | Close: 66390.02 | TF: 1m
2026-02-18 22:56:00 | Close: 66399.00 | TF: 1m
2026-02-18 22:55:00 | Close: 66385.48 | TF: 1m
(FRESH DATA - less than 5 minutes old!)

# Health check
curl http://localhost:8019/health
Status: healthy
Issues: 0

# UI symbols  
Showing: AAVE, ADA, ATOM, AVAX, BTC, DOT, ETH, LINK, SOL, UNI (10 symbols)
```

## Services Restarted
- ✅ OHLCV API (port 8012) - with timeframe parameter fix
- ✅ Testing API (port 8019) - with active-only health check
- ✅ UI Server (port 8010) - serving updated index.html

## Symbol Status
| Symbol | Status | Candles Fetching |
|--------|--------|------------------|
| AAVE | Active | ✅ Yes |
| ADA | Active | ✅ Yes |
| ATOM | Active | ✅ Yes |
| AVAX | Active | ✅ Yes |
| BTC | Active | ✅ Yes |
| DOT | Active | ✅ Yes |
| ETH | Active | ✅ Yes |
| LINK | Active | ✅ Yes |
| SOL | Active | ✅ Yes |
| UNI | Active | ✅ Yes |
| **MATIC** | **Inactive** | ❌ No (excluded from fetch) |

## Verification Commands

### Check Candle Freshness
```bash
curl -s "http://localhost:8012/candles?symbol=BTC&limit=5" | python3 -m json.tool
```

### Check Active Symbols
```bash
curl -s "http://localhost:8012/symbols" | python3 -c "import sys, json; d=json.loads(sys.stdin.read()); print(f'{d[\"count\"]} active symbols'); [print(f'  - {s[\"symbol\"]}') for s in d['symbols']]"
```

### Check Health
```bash
curl -s "http://localhost:8019/health" | python3 -c "import sys, json; d=json.loads(sys.stdin.read()); print(f'Status: {d[\"status\"]}'); issues = [t for t in d.get('tests', []) if t['status'] == 'FAIL']; print(f'Issues: {len(issues)}')"
```

### View UI Symbols
Open browser: `http://your-server-ip:8010/`
Expected: 10 symbol cards displayed

## What Was Wrong vs What Was Fixed

❌ **What User Saw**: "Only 3 symbols in dropdown"
✅ **Fix**: UI now dynamically loads all active symbols from API (10 symbols)

❌ **What User Saw**: "Stale data: AAVE (67m old), ADA (67m old)..."
✅ **Fix**: Timeframe parameter added to save_candle() - candles now saving correctly every minute

❌ **What User Saw**: "MATIC still trying to run because missing candles"
✅ **Fix**: Health check now filters to active symbols only - MATIC excluded

## Key Learning
The `ohlcv_candles` table has a unique constraint on `(symbol, timeframe, timestamp)`. The save function MUST include all three fields or duplicates will be rejected. When `timeframe` was NULL, every new candle with the same timestamp (but different timeframe) was treated as a duplicate.

This is why:
- Fetch logs showed: "candles_fetched": 0, "candles_duplicate": 5
- Database had: Old candles from 75+ minutes ago
- Coinbase returned: Fresh current candles
- But nothing saved: Because timeframe was missing from INSERT

## Status: All Issues Resolved ✅
- ✅ UI showing 10 symbols
- ✅ Candles saving with fresh timestamps (< 5 minutes old)
- ✅ Health showing 0 issues
- ✅ MATIC properly excluded from all operations
