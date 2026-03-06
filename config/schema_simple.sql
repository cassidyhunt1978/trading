-- =================================================================
-- Clean Crypto Trading System - Database  Schema (Without TimescaleDB)
-- =================================================================

-- =================================================================
-- OHLCV Data
-- =================================================================
CREATE TABLE IF NOT EXISTS ohlcv_candles (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    open NUMERIC(20, 8) NOT NULL,
    high NUMERIC(20, 8) NOT NULL,
    low NUMERIC(20, 8) NOT NULL,
    close NUMERIC(20, 8) NOT NULL,
    volume NUMERIC(20, 4) NOT NULL,
    indicators JSONB,  -- Pre-computed indicators added as they're discovered
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(symbol, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol_timestamp ON ohlcv_candles(symbol, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_ohlcv_indicators ON ohlcv_candles USING gin(indicators);

-- =================================================================
-- Symbols (Active coins being traded)
-- =================================================================
CREATE TABLE IF NOT EXISTS symbols (
    id SERIAL PRIMARY KEY,
    symbol TEXT UNIQUE NOT NULL,
    name TEXT,
    exchange TEXT DEFAULT 'kraken',
    status TEXT DEFAULT 'active',  -- active, paused, delisted
    market_cap_usd NUMERIC(20, 2),
    volume_24h_usd NUMERIC(20, 2),
    buzz_score INTEGER DEFAULT 0,  -- 0-100 from AI sentiment
    added_at TIMESTAMPTZ DEFAULT NOW(),
    last_candle_at TIMESTAMPTZ,
    metadata JSONB  -- {reddit_mentions, news_articles, twitter_trending}
);

CREATE INDEX IF NOT EXISTS idx_symbols_status ON symbols(status);
CREATE INDEX IF NOT EXISTS idx_symbols_buzz ON symbols(buzz_score DESC);

-- =================================================================
-- Strategies (Indicator combinations and logic)
-- =================================================================
CREATE TABLE IF NOT EXISTS strategies (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    indicator_logic JSONB NOT NULL,  
    parameters JSONB NOT NULL,  -- {RSI_period: 14, VWAP_period: 20, ...}
    risk_management JSONB,  -- {stop_loss_pct: 2.0, take_profit_pct: 5.0, max_hold_minutes: 240}
    created_by TEXT DEFAULT 'AI',  -- 'AI' or 'human'
    enabled BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- =================================================================
-- Backtests (Historical performance of strategies)
-- =================================================================
CREATE TABLE IF NOT EXISTS backtests (
    id SERIAL PRIMARY KEY,
    strategy_id INTEGER REFERENCES strategies(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    start_date TIMESTAMPTZ NOT NULL,
    end_date TIMESTAMPTZ NOT NULL,
    starting_capital NUMERIC(20, 8) NOT NULL,
    ending_capital NUMERIC(20, 8),
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    losing_trades INTEGER DEFAULT 0,
    win_rate NUMERIC(5, 2),
    total_return_pct NUMERIC(10, 4),
    max_drawdown_pct NUMERIC(10, 4),
    sharpe_ratio NUMERIC(10, 4),
    total_fees_paid NUMERIC(20, 8),
    perfect_strategy_return_pct NUMERIC(10, 4),  -- What could've been earned
    trades JSONB,  -- Array of all trades with entry/exit/fees
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_backtests_strategy ON backtests(strategy_id);
CREATE INDEX IF NOT EXISTS idx_backtests_symbol ON backtests(symbol);
CREATE INDEX IF NOT EXISTS idx_backtests_win_rate ON backtests(win_rate DESC);

-- =================================================================
-- Signals (Real-time buy/sell/hold signals)
-- =================================================================
CREATE TABLE IF NOT EXISTS signals (
    id SERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    strategy_id INTEGER REFERENCES strategies(id) ON DELETE CASCADE,
    signal_type TEXT NOT NULL,  -- BUY, SELL, HOLD
    quality_score INTEGER NOT NULL,  -- 0-100
    quality_breakdown JSONB,  -- {"backtest": 28, "sentiment": 20, ...}
    
    projected_return_pct NUMERIC(10, 4),
    projected_timeframe_minutes INTEGER,
    projected_trajectory TEXT,  -- 'vertical' (fast), 'diagonal' (steady), 'horizontal' (slow)
    velocity_score NUMERIC(10, 4),  -- Expected $/hour or %/hour
    
    price_at_signal NUMERIC(20, 8),
    sentiment_summary TEXT,  -- "Strong Reddit buzz, 5 positive news articles"
    ai_reasoning TEXT,  -- Why AI thinks this is a good/bad signal
    
    generated_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ,  -- Signals expire after X minutes
    acted_on BOOLEAN DEFAULT false
);

CREATE INDEX IF NOT EXISTS idx_signals_quality ON signals(quality_score DESC);
CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol);
CREATE INDEX IF NOT EXISTS idx_signals_active ON signals(generated_at DESC) WHERE NOT acted_on;

-- =================================================================
-- Positions (Open and closed trades)
-- =================================================================
CREATE TABLE IF NOT EXISTS positions (
    id SERIAL PRIMARY KEY,
    signal_id INTEGER REFERENCES signals(id) ON DELETE SET NULL,
    symbol TEXT NOT NULL,
    strategy_id INTEGER REFERENCES strategies(id) ON DELETE SET NULL,
    
    mode TEXT NOT NULL,  -- 'paper' or 'live'
    status TEXT NOT NULL,  -- 'open', 'closed', 'stopped_out'
    
    entry_price NUMERIC(20, 8) NOT NULL,
    entry_time TIMESTAMPTZ NOT NULL,
    entry_fee NUMERIC(20, 8),
    
    exit_price NUMERIC(20, 8),
    exit_time TIMESTAMPTZ,
    exit_fee NUMERIC(20, 8),
    
    quantity NUMERIC(20, 8) NOT NULL,
    capital_allocated NUMERIC(20, 8) NOT NULL,
    
    current_price NUMERIC(20, 8),  -- Updated in real-time
    current_pnl NUMERIC(20, 8),  -- Unrealized P&L
    current_pnl_pct NUMERIC(10, 4),
    
    realized_pnl NUMERIC(20, 8),  -- After close
    realized_pnl_pct NUMERIC(10, 4),
    
    stop_loss_price NUMERIC(20, 8),
    take_profit_price NUMERIC(20, 8),
    
    velocity_at_entry NUMERIC(10, 4),  -- Expected velocity
    current_velocity NUMERIC(10, 4),  -- Actual velocity
    velocity_threshold NUMERIC(10, 4),  -- Min acceptable velocity
    
    minutes_held INTEGER,
    max_hold_minutes INTEGER,
    
    trade_result TEXT,  -- 'win', 'loss', 'draw', 'stopped_out', 'rotated'
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol);
CREATE INDEX IF NOT EXISTS idx_positions_mode ON positions(mode);

-- =================================================================
-- Portfolio State (Snapshot of portfolio at any time)
-- =================================================================
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    mode TEXT NOT NULL,  -- 'paper' or 'live'
    
    total_capital NUMERIC(20, 8) NOT NULL,
    deployed_capital NUMERIC(20, 8) NOT NULL,  -- In positions
    available_capital NUMERIC(20, 8) NOT NULL,  -- Cash
    
    open_positions INTEGER DEFAULT 0,
    total_pnl NUMERIC(20, 8),
    total_pnl_pct NUMERIC(10, 4),
    
    daily_pnl NUMERIC(20, 8),
    daily_pnl_pct NUMERIC(10, 4),
    
    daily_target_met BOOLEAN DEFAULT false,  -- Hit 0.05% today?
    consecutive_days_target_met INTEGER DEFAULT 0,
    
    positions_snapshot JSONB  -- Array of current positions
);

CREATE INDEX IF NOT EXISTS idx_portfolio_timestamp ON portfolio_snapshots(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_portfolio_mode ON portfolio_snapshots(mode);

-- =================================================================
-- AfterAction Reports (Twice daily analysis)
-- =================================================================
CREATE TABLE IF NOT EXISTS afteraction_reports (
    id SERIAL PRIMARY KEY,
    report_date DATE NOT NULL,
    report_time TEXT NOT NULL,  -- 'midday' or 'eod'
    
    trades_analyzed INTEGER,
    wins INTEGER,
    losses INTEGER,
    draws INTEGER,
    
    missed_opportunities JSONB,  
    false_signals JSONB,
    regime_changes JSONB,
    trading_logic_flaws JSONB,
    recommendations JSONB,
    
    auto_applied BOOLEAN DEFAULT false,  -- Did system auto-apply recommendations?
    human_review_required BOOLEAN DEFAULT false,
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_afteraction_date ON afteraction_reports(report_date DESC);

-- =================================================================
-- System Health (API status, task status, data freshness)
-- =================================================================
CREATE TABLE IF NOT EXISTS system_health (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    
    api_statuses JSONB NOT NULL,
    celery_task_statuses JSONB NOT NULL,
    data_freshness JSONB,
    
    overall_health_score INTEGER,  -- 0-100
    issues JSONB  -- Array of current problems
);

CREATE INDEX IF NOT EXISTS idx_health_timestamp ON system_health(timestamp DESC);

-- =================================================================
-- Insert initial test symbols
-- =================================================================
INSERT INTO symbols (symbol, name, exchange, status) VALUES
('BTC', 'Bitcoin', 'kraken', 'active'),
('ETH', 'Ethereum', 'kraken', 'active'),
('SOL', 'Solana', 'kraken', 'active')
ON CONFLICT (symbol) DO NOTHING;

-- =================================================================
-- Insert initial paper trading capital
-- =================================================================
INSERT INTO portfolio_snapshots (mode, total_capital, deployed_capital, available_capital, open_positions, timestamp)
VALUES ('paper', 10000, 0, 10000, 0, NOW())
ON CONFLICT DO NOTHING;

-- =================================================================
-- Create a test strategy
-- =================================================================
INSERT INTO strategies (name, description, indicator_logic, parameters, risk_management) VALUES
('Simple RSI Strategy', 'Buy when RSI < 30, Sell when RSI > 70', 
 '{"buy_conditions": [{"indicator": "RSI", "operator": "<", "value": 30}], "sell_conditions": [{"indicator": "RSI", "operator": ">", "value": 70}]}'::jsonb,
 '{"RSI_period": 14}'::jsonb,
 '{"stop_loss_pct": 2.0, "take_profit_pct": 5.0, "max_hold_minutes": 240}'::jsonb)
ON CONFLICT DO NOTHING;
