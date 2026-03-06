# AfterAction API Fix - Issue Resolution

## Problem
The AfterAction API was returning 500 errors when accessing `/stats` and `/analyze` endpoints because:

1. **Missing Table**: The `afteraction_reports` table didn't exist in the database
2. **Schema Mismatch**: The schema definition in `schema.sql` didn't match what the API code expected

## Root Cause
- The API code was trying to query `afteraction_reports` table which hadn't been created yet
- The schema file had an old/different version of the table structure (using `report_date`, `report_time`, `wins`, `losses` vs `period_start`, `period_end`, `winning_trades`, `losing_trades`)

## Fix Applied

### 1. Updated AfterAction API (`/opt/trading/services/afteraction_api/main.py`)
- Added `CREATE TABLE IF NOT EXISTS` statement to `/stats` endpoint
- Table now automatically creates itself on first call
- Schema matches what the API code expects:
  ```sql
  CREATE TABLE IF NOT EXISTS afteraction_reports (
      id SERIAL PRIMARY KEY,
      mode TEXT NOT NULL,
      period_start TIMESTAMP NOT NULL,
      period_end TIMESTAMP NOT NULL,
      total_trades_analyzed INTEGER DEFAULT 0,
      winning_trades INTEGER DEFAULT 0,
      losing_trades INTEGER DEFAULT 0,
      missed_opportunities INTEGER DEFAULT 0,
      false_signals INTEGER DEFAULT 0,
      recommendations JSONB,
      regime_detected TEXT,
      created_at TIMESTAMP DEFAULT NOW()
  )
  ```

### 2. Updated Schema File (`/opt/trading/config/schema.sql`)
- Replaced old table definition with correct one matching API code
- Future database setups will have the correct schema from the start

### 3. Restarted AfterAction API
- Service restarted to pick up code changes
- Table will be auto-created on first stats request

## Verification

Run the test script:
```bash
bash /opt/trading/quick_test_afteraction.sh
```

Or test manually:
```bash
# Health check
curl http://localhost:8018/health

# Stats (previously returned 500 error)
curl http://localhost:8018/stats

# Reports
curl http://localhost:8018/reports?limit=5
```

## UI Testing

1. Refresh the UI page (http://your-ip:8010)
2. Go to System tab
3. Scroll to "📊 AfterAction Analysis" section
4. Click **Refresh** button - should load without errors
5. Click **Run Analysis** button - should trigger analysis

The stats should now show:
- Total Reports: 0 (initially)
- Win Rate: 0% (initially)
- Missed Opportunities: 0
- False Signals: 0

After running the first analysis, these numbers will populate with real data.

## Why 500 Errors Happened

When the API tried to query a non-existent table:
```sql
SELECT COUNT(*) as total_reports, ...
FROM afteraction_reports  -- <-- Table didn't exist!
```

PostgreSQL threw an error: `relation "afteraction_reports" does not exist`

FastAPI caught this exception and returned HTTP 500 Internal Server Error.

## Prevention

The fix ensures the table is created automatically, so:
- ✅ No manual database setup required
- ✅ Safe to call `/stats` even if table doesn't exist
- ✅ Table uses correct schema matching API code
- ✅ Future deployments will have correct schema

## Files Modified

1. `/opt/trading/services/afteraction_api/main.py` (lines 459-487)
2. `/opt/trading/config/schema.sql` (lines 210-232)

## Status

✅ **FIXED** - AfterAction API should now work without 500 errors
