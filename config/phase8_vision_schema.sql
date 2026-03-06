-- =================================================================
-- Phase 8: Vision Schema - Compounding Small-Account System
-- Run with: psql -U postgres -d trading_system -f config/phase8_vision_schema.sql
-- =================================================================

-- -----------------------------------------------------------------
-- 1. symbol_strategies: per-symbol strategy assignment + trust ranking
-- -----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS symbol_strategies (
    id SERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    strategy_id INTEGER REFERENCES strategies(id),
    trust_factor NUMERIC(10, 6) DEFAULT 0.0,   -- PF * WR * (1 - fee_drag)
    profit_factor NUMERIC(10, 4) DEFAULT 0.0,
    win_rate NUMERIC(5, 2) DEFAULT 0.0,
    total_trades INTEGER DEFAULT 0,
    fee_drag_pct NUMERIC(5, 4) DEFAULT 0.0010,  -- 0.10% taker fee
    last_backtest_at TIMESTAMPTZ,
    last_backtest_result JSONB,
    rank INTEGER DEFAULT 999,   -- 1 = best performing
    status TEXT DEFAULT 'active', -- active, paused, retired
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(symbol, strategy_id)
);

CREATE INDEX IF NOT EXISTS idx_symbol_strategies_symbol ON symbol_strategies(symbol);
CREATE INDEX IF NOT EXISTS idx_symbol_strategies_trust  ON symbol_strategies(trust_factor DESC);
CREATE INDEX IF NOT EXISTS idx_symbol_strategies_rank   ON symbol_strategies(symbol, rank ASC);

-- -----------------------------------------------------------------
-- 2. trading_mode_config: paper->live switch state machine
-- -----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trading_mode_config (
    id SERIAL PRIMARY KEY,
    mode TEXT NOT NULL DEFAULT 'paper',        -- 'paper' or 'live'
    profitable_days_streak INTEGER DEFAULT 0,
    unprofitable_days_streak INTEGER DEFAULT 0,
    days_to_promote INTEGER DEFAULT 7,         -- consecutive profitable days -> go live
    days_to_demote INTEGER DEFAULT 5,          -- consecutive unprofitable days -> stop+reevaluate
    target_daily_pct NUMERIC(5, 4) DEFAULT 0.005,  -- 0.5% daily target
    last_evaluated_at TIMESTAMPTZ,
    reevaluation_triggered BOOLEAN DEFAULT FALSE,
    notes TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO trading_mode_config (mode, profitable_days_streak, unprofitable_days_streak)
VALUES ('paper', 0, 0)
ON CONFLICT DO NOTHING;

-- -----------------------------------------------------------------
-- 3. ensemble_decisions: log every ensemble voting decision
-- -----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ensemble_decisions (
    id SERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    decision TEXT NOT NULL,                -- BUY, SELL, HOLD
    total_signals INTEGER DEFAULT 0,
    buy_votes_weighted NUMERIC(10, 4) DEFAULT 0,
    sell_votes_weighted NUMERIC(10, 4) DEFAULT 0,
    ai_weight_adjustment NUMERIC(6, 4) DEFAULT 1.0,  -- AI multiplier
    signals_considered JSONB,             -- [{signal_id, strategy, weight, vote}]
    threshold_met BOOLEAN DEFAULT FALSE,
    executed BOOLEAN DEFAULT FALSE,
    position_id INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ensemble_decisions_symbol ON ensemble_decisions(symbol);
CREATE INDEX IF NOT EXISTS idx_ensemble_decisions_time   ON ensemble_decisions(created_at DESC);

-- -----------------------------------------------------------------
-- 4. discovered_symbols_queue: AI-discovered symbols pending onboarding
-- -----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS discovered_symbols_queue (
    id SERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    name TEXT,
    exchange TEXT DEFAULT 'coinbase',
    discovery_source TEXT,    -- 'ai_market_scan', 'ccxt_volume', 'manual'
    discovery_reason TEXT,
    confidence_score INTEGER DEFAULT 50, -- 0-100
    status TEXT DEFAULT 'pending',       -- pending, added, rejected, failed
    processed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(symbol)
);

-- -----------------------------------------------------------------
-- 5. daily_profitability_log: daily P&L tracking for paper/live switch
-- -----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS daily_profitability_log (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    mode TEXT NOT NULL,     -- 'paper' or 'live'
    total_pnl NUMERIC(20, 8) DEFAULT 0,
    total_pnl_pct NUMERIC(10, 4) DEFAULT 0,
    trades_count INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    is_profitable BOOLEAN DEFAULT FALSE,
    starting_capital NUMERIC(20, 8),
    ending_capital NUMERIC(20, 8),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(date, mode)
);

-- -----------------------------------------------------------------
-- 6. charts_strategies: strategies imported from chart component
-- -----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS charts_strategies (
    id SERIAL PRIMARY KEY,
    source_file TEXT,               -- filename/chart identifier from charts repo
    strategy_name TEXT NOT NULL,
    entry_rules JSONB,              -- chart-exported entry logic
    exit_rules JSONB,               -- chart-exported exit logic
    risk_params JSONB,              -- stop-loss, take-profit from chart
    backtest_summary JSONB,         -- PF, WR, trades from chart backtest
    profit_factor NUMERIC(10, 4),
    win_rate NUMERIC(5, 2),
    total_trades INTEGER DEFAULT 0,
    strategy_id INTEGER REFERENCES strategies(id),  -- linked DB strategy after import
    imported_at TIMESTAMPTZ DEFAULT NOW(),
    status TEXT DEFAULT 'pending'   -- pending, assigned, rejected
);

CREATE INDEX IF NOT EXISTS idx_charts_strategies_pf ON charts_strategies(profit_factor DESC);

-- -----------------------------------------------------------------
-- 7. Extend ohlcv_candles: ensure timeframe column exists
--    (already handled in existing schema, but safe to add)
-- -----------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='ohlcv_candles' AND column_name='timeframe'
    ) THEN
        ALTER TABLE ohlcv_candles ADD COLUMN timeframe TEXT DEFAULT '1m';
    END IF;
END $$;

-- Unique constraint for (symbol, timeframe, timestamp) if not already present
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'ohlcv_candles_symbol_timeframe_timestamp_key'
    ) THEN
        ALTER TABLE ohlcv_candles
            ADD CONSTRAINT ohlcv_candles_symbol_timeframe_timestamp_key
            UNIQUE (symbol, timeframe, timestamp);
    END IF;
END $$;

-- -----------------------------------------------------------------
-- 8. TimescaleDB Continuous Aggregates for higher timeframes
--    Wrapped in DO block so they silently skip if TimescaleDB
--    time_bucket / continuous aggregates are not available.
-- -----------------------------------------------------------------
DO $ts$
DECLARE
    ts_available BOOLEAN;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM pg_proc WHERE proname = 'time_bucket'
    ) INTO ts_available;

    IF NOT ts_available THEN
        RAISE NOTICE 'TimescaleDB time_bucket not found -- skipping continuous aggregate views';
        RETURN;
    END IF;

    -- 5-minute view
    BEGIN
        EXECUTE $sql$
            CREATE MATERIALIZED VIEW IF NOT EXISTS ohlcv_5m
            WITH (timescaledb.continuous) AS
            SELECT symbol,
                   time_bucket('5 minutes'::interval, timestamp) AS bucket,
                   timeframe,
                   first(open,  timestamp) AS open,
                   MAX(high)  AS high, MIN(low) AS low,
                   last(close, timestamp) AS close,
                   SUM(volume) AS volume
            FROM ohlcv_candles WHERE timeframe = '1m'
            GROUP BY symbol, bucket, timeframe WITH NO DATA
        $sql$;
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'ohlcv_5m view skipped: %', SQLERRM;
    END;

    -- 15-minute view
    BEGIN
        EXECUTE $sql$
            CREATE MATERIALIZED VIEW IF NOT EXISTS ohlcv_15m
            WITH (timescaledb.continuous) AS
            SELECT symbol,
                   time_bucket('15 minutes'::interval, timestamp) AS bucket,
                   timeframe,
                   first(open,  timestamp) AS open,
                   MAX(high) AS high, MIN(low) AS low,
                   last(close, timestamp) AS close,
                   SUM(volume) AS volume
            FROM ohlcv_candles WHERE timeframe = '1m'
            GROUP BY symbol, bucket, timeframe WITH NO DATA
        $sql$;
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'ohlcv_15m view skipped: %', SQLERRM;
    END;

    -- 1-hour view
    BEGIN
        EXECUTE $sql$
            CREATE MATERIALIZED VIEW IF NOT EXISTS ohlcv_1h
            WITH (timescaledb.continuous) AS
            SELECT symbol,
                   time_bucket('1 hour'::interval, timestamp) AS bucket,
                   timeframe,
                   first(open,  timestamp) AS open,
                   MAX(high) AS high, MIN(low) AS low,
                   last(close, timestamp) AS close,
                   SUM(volume) AS volume
            FROM ohlcv_candles WHERE timeframe = '1m'
            GROUP BY symbol, bucket, timeframe WITH NO DATA
        $sql$;
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'ohlcv_1h view skipped: %', SQLERRM;
    END;

    -- 4-hour view
    BEGIN
        EXECUTE $sql$
            CREATE MATERIALIZED VIEW IF NOT EXISTS ohlcv_4h
            WITH (timescaledb.continuous) AS
            SELECT symbol,
                   time_bucket('4 hours'::interval, timestamp) AS bucket,
                   timeframe,
                   first(open,  timestamp) AS open,
                   MAX(high) AS high, MIN(low) AS low,
                   last(close, timestamp) AS close,
                   SUM(volume) AS volume
            FROM ohlcv_candles WHERE timeframe = '1m'
            GROUP BY symbol, bucket, timeframe WITH NO DATA
        $sql$;
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'ohlcv_4h view skipped: %', SQLERRM;
    END;

    -- Daily view
    BEGIN
        EXECUTE $sql$
            CREATE MATERIALIZED VIEW IF NOT EXISTS ohlcv_1d
            WITH (timescaledb.continuous) AS
            SELECT symbol,
                   time_bucket('1 day'::interval, timestamp) AS bucket,
                   timeframe,
                   first(open,  timestamp) AS open,
                   MAX(high) AS high, MIN(low) AS low,
                   last(close, timestamp) AS close,
                   SUM(volume) AS volume
            FROM ohlcv_candles WHERE timeframe = '1m'
            GROUP BY symbol, bucket, timeframe WITH NO DATA
        $sql$;
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'ohlcv_1d view skipped: %', SQLERRM;
    END;

    -- Refresh policies (skip silently if already exist)
    BEGIN
        PERFORM add_continuous_aggregate_policy('ohlcv_5m',
            start_offset => INTERVAL '2 days', end_offset => INTERVAL '1 minute',
            schedule_interval => INTERVAL '5 minutes', if_not_exists => TRUE);
        PERFORM add_continuous_aggregate_policy('ohlcv_15m',
            start_offset => INTERVAL '3 days', end_offset => INTERVAL '5 minutes',
            schedule_interval => INTERVAL '15 minutes', if_not_exists => TRUE);
        PERFORM add_continuous_aggregate_policy('ohlcv_1h',
            start_offset => INTERVAL '7 days', end_offset => INTERVAL '15 minutes',
            schedule_interval => INTERVAL '1 hour', if_not_exists => TRUE);
        PERFORM add_continuous_aggregate_policy('ohlcv_4h',
            start_offset => INTERVAL '14 days', end_offset => INTERVAL '1 hour',
            schedule_interval => INTERVAL '4 hours', if_not_exists => TRUE);
        PERFORM add_continuous_aggregate_policy('ohlcv_1d',
            start_offset => INTERVAL '30 days', end_offset => INTERVAL '4 hours',
            schedule_interval => INTERVAL '1 day', if_not_exists => TRUE);
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'Refresh policies skipped: %', SQLERRM;
    END;

    -- Retention policy (180 days)
    BEGIN
        PERFORM add_retention_policy('ohlcv_candles', INTERVAL '180 days', if_not_exists => TRUE);
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'Retention policy skipped: %', SQLERRM;
    END;

END $ts$;
