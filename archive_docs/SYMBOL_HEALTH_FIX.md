# Symbol Health Check & UI Fixes

## Issues Fixed

### 1. MATIC Symbol Issue
**Problem**: MATIC is not available on Coinbase exchange, so candles can't be retrieved.
**Solution**: 
- Manually disabled MATIC symbol with reason: "Not available on Coinbase exchange"
- Added automatic symbol health checking to detect and disable such symbols

### 2. UI Showing Only 3 Symbols
**Problem**: Strategy detail dropdown and main dashboard only showed 3 hardcoded symbols (BTC, ETH, SOL)
**Solution**: 
- Updated UI to fetch symbols dynamically from OHLCV API `/symbols` endpoint
- UI now displays all 10 active symbols (excluding MATIC)

## Changes Implemented

### 1. OHLCV API - Track Successful Candle Retrieval
**File**: `/opt/trading/services/ohlcv_api/main.py`

**Changes**:
- Added code to update `last_candle_at` timestamp when candles are successfully fetched
- Enhanced error logging to include symbol name in exchange errors

```python
# Update last_candle_at timestamp on successful fetch
if candles_saved > 0:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE symbols 
                SET last_candle_at = NOW()
                WHERE symbol = %s
            """, (symbol,))
            conn.commit()
    logger.info("last_candle_updated", symbol=symbol)
```

### 2. Celery Task - Automatic Symbol Health Check
**File**: `/opt/trading/celery_worker/tasks.py`

**New Task**: `check_symbol_health()`

**Functionality**:
- Runs every 6 hours (scheduled via Celery Beat)
- Identifies symbols that haven't had successful candle retrieval in 24+ hours
- Provides 48-hour grace period for newly added symbols (allows time for backfill)
- Automatically disables unhealthy symbols with reason in metadata
- Logs all actions for audit trail

**Logic**:
```python
# Find symbols that are active but haven't had candles in 24+ hours
# For symbols with NEVER fetched candles:
#   - Check when symbol was added
#   - Only disable if added > 48 hours ago (grace period)
# For symbols with stale candles (>24h old):
#   - Disable immediately
# Update symbol status to 'inactive' with disabled_reason in metadata
```

**Schedule**: Every 6 hours (midnight, 6am, noon, 6pm UTC)

### 3. UI - Dynamic Symbol Loading
**File**: `/opt/trading/ui/index_final.html`

**Changes**:
- Replaced hardcoded 3-symbol array with API call to fetch all active symbols
- Added fallback to hardcoded symbols if API fails (graceful degradation)
- UI now displays all 10 active symbols instead of just 3

**Before**:
```javascript
function loadSymbols() {
    const symbols = [
        { symbol: 'BTC', name: 'Bitcoin' },
        { symbol: 'ETH', name: 'Ethereum' },
        { symbol: 'SOL', name: 'Solana' }
    ];
    // ...
}
```

**After**:
```javascript
async function loadSymbols() {
    try {
        const response = await fetch(`http://${API_HOST}:8012/symbols`);
        const data = await response.json();
        
        if (data.status === 'success' && data.symbols && data.symbols.length > 0) {
            const symbols = data.symbols.map(s => ({
                symbol: s.symbol,
                name: s.name || s.symbol
            }));
            renderSymbolCards(symbols);
            symbols.forEach(s => loadSymbolData(s.symbol));
        }
    } catch (error) {
        // Fallback to hardcoded if API fails
    }
}
```

## Current Symbol Status

| Symbol | Status | Reason |
|--------|--------|--------|
| BTC | Active | Available on Coinbase |
| ETH | Active | Available on Coinbase |
| SOL | Active | Available on Coinbase |
| AVAX | Active | Available on Coinbase |
| LINK | Active | Available on Coinbase |
| UNI | Active | Available on Coinbase |
| AAVE | Active | Available on Coinbase |
| ATOM | Active | Available on Coinbase |
| DOT | Active | Available on Coinbase |
| ADA | Active | Available on Coinbase |
| **MATIC** | **Inactive** | **Not available on Coinbase exchange** |

## Testing

### Manual Test of Symbol Health Check
```bash
cd /opt/trading && source venv/bin/activate
python3 -c "
from celery_worker.tasks import check_symbol_health
result = check_symbol_health()
print(result)
"
```

**Expected Result**: 
- Symbols within grace period (< 48 hours since added) are not disabled
- Symbols > 48 hours old with no candles are automatically disabled

### Verify UI Shows All Symbols
1. Open browser to `http://your-server-ip`
2. Check that 10 symbol cards are displayed (not just 3)
3. Verify MATIC is not shown (since it's inactive)

### Verify API Returns Active Symbols Only
```bash
curl http://localhost:8012/symbols
```

**Expected**: JSON with 10 symbols (MATIC excluded)

## Automatic Maintenance

The system now automatically maintains symbol health:

1. **Every 60 seconds**: Fetch 1-minute candles for all active symbols
2. **On Success**: Update `last_candle_at` timestamp
3. **Every 6 hours**: Check symbol health
4. **If symbol can't fetch candles for 24+ hours**: Automatically disable it

This ensures that:
- Symbols like MATIC (not on exchange) are automatically removed
- Symbol list stays clean and only shows tradeable assets
- UI always displays current active symbols without manual updates
- Trading strategies only use symbols with available data

## Services Restarted

- ✅ OHLCV API (port 8012) - with last_candle_at tracking
- ✅ Celery Workers (9 processes) - with new health check task
- ✅ Celery Beat Scheduler - with 6-hour health check schedule
- ✅ UI Server (port 80) - updated to dynamic symbol loading

## Future Enhancements

1. **Email Notifications**: Alert when symbols are auto-disabled
2. **Dashboard Tab**: Show symbol health status and history
3. **Manual Re-enable**: API endpoint to re-enable disabled symbols
4. **Exchange Fallback**: Try alternate exchanges if primary fails
5. **Symbol Metrics**: Track candle fetch success rate per symbol
