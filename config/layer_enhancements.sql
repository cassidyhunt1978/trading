-- Market Regime Detection Table
-- Stores current market regime for each symbol

CREATE TABLE IF NOT EXISTS market_regime (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) UNIQUE NOT NULL,
    regime VARCHAR(50) NOT NULL, -- trending_up, trending_down, ranging, volatile
    confidence FLOAT NOT NULL, -- 0-100
    atr FLOAT, -- Average True Range
    adx FLOAT, -- Average Directional Index
    trend_slope FLOAT, -- Price trend slope
    volatility_pct FLOAT, -- Volatility percentage
    detected_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    metadata JSONB, -- Additional regime metrics
    CONSTRAINT regime_confidence_range CHECK (confidence >= 0 AND confidence <= 100)
);

CREATE INDEX IF NOT EXISTS idx_market_regime_symbol ON market_regime(symbol);
CREATE INDEX IF NOT EXISTS idx_market_regime_updated ON market_regime(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_market_regime_regime ON market_regime(regime);

-- Performance Goals Table (Layer 8)
-- Tracks adaptive profit targets and system performance goals

CREATE TABLE IF NOT EXISTS performance_goals (
    id SERIAL PRIMARY KEY,
    goal_type VARCHAR(50) NOT NULL, -- daily, weekly, monthly
    target_profit_pct FLOAT NOT NULL, -- Target profit percentage
    baseline_pct FLOAT NOT NULL DEFAULT 0.05, -- Starting baseline (0.05% daily)
    current_streak INT DEFAULT 0, -- Consecutive days meeting goal
    best_streak INT DEFAULT 0, -- Best streak achieved
    times_met INT DEFAULT 0, -- Total times goal met
    times_missed INT DEFAULT 0, -- Total times goal missed
    last_adjustment_date DATE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    metadata JSONB, -- Additional goal tracking data
    CONSTRAINT goal_profit_positive CHECK (target_profit_pct > 0)
);

CREATE INDEX IF NOT EXISTS idx_performance_goals_type ON performance_goals(goal_type);
CREATE INDEX IF NOT EXISTS idx_performance_goals_updated ON performance_goals(updated_at DESC);

-- Daily Performance Tracking (Layer 8)
-- Tracks actual daily performance against goals

CREATE TABLE IF NOT EXISTS daily_performance (
    id SERIAL PRIMARY KEY,
    trade_date DATE UNIQUE NOT NULL,
    mode VARCHAR(10) DEFAULT 'paper',
    starting_capital FLOAT NOT NULL,
    ending_capital FLOAT NOT NULL,
    realized_pnl FLOAT NOT NULL,
    return_pct FLOAT NOT NULL,
    trades_executed INT DEFAULT 0,
    win_count INT DEFAULT 0,
    loss_count INT DEFAULT 0,
    win_rate FLOAT DEFAULT 0,
    daily_goal_pct FLOAT,
    goal_met BOOLEAN DEFAULT false,
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT daily_perf_capital_positive CHECK (starting_capital > 0 AND ending_capital > 0)
);

CREATE INDEX IF NOT EXISTS idx_daily_performance_date ON daily_performance(trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_daily_performance_goal_met ON daily_performance(goal_met);

-- Strategy Optimization Queue (Layer 2)
-- Tracks which strategy-symbol combinations need optimization

CREATE TABLE IF NOT EXISTS optimization_queue (
    id SERIAL PRIMARY KEY,
    strategy_id INT REFERENCES strategies(id),
    symbol VARCHAR(20) NOT NULL,
    priority INT DEFAULT 50, -- 1-100, higher = more urgent
    status VARCHAR(20) DEFAULT 'pending', -- pending, running, completed, failed
    requested_at TIMESTAMP DEFAULT NOW(),
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    result JSONB, -- Optimization results
    error_message TEXT,
    UNIQUE(strategy_id, symbol, status)
);

CREATE INDEX IF NOT EXISTS idx_optimization_queue_status ON optimization_queue(status);
CREATE INDEX IF NOT EXISTS idx_optimization_queue_priority ON optimization_queue(priority DESC);

-- AI Orchestration Decisions (Layer 5)
-- Tracks AI system-level decisions and recommendations

CREATE TABLE IF NOT EXISTS ai_orchestration_log (
    id SERIAL PRIMARY KEY,
    decision_type VARCHAR(50) NOT NULL, -- symbol_selection, strategy_weight, risk_adjustment, system_alert
    decision JSONB NOT NULL, -- The actual decision/recommendation
    reasoning TEXT, -- AI's explanation
    confidence FLOAT, -- 0-100
    executed BOOLEAN DEFAULT false,
    executed_at TIMESTAMP,
    outcome JSONB, -- Results after execution
    created_at TIMESTAMP DEFAULT NOW(),
    metadata JSONB
);

CREATE INDEX IF NOT EXISTS idx_ai_orchestration_type ON ai_orchestration_log(decision_type);
CREATE INDEX IF NOT EXISTS idx_ai_orchestration_created ON ai_orchestration_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_orchestration_executed ON ai_orchestration_log(executed);

-- Insert initial daily goal
INSERT INTO performance_goals (goal_type, target_profit_pct, baseline_pct)
VALUES ('daily', 0.05, 0.05)
ON CONFLICT DO NOTHING;

-- Add regime column to strategy_performance if not exists
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_name = 'strategy_performance' 
        AND column_name = 'regime'
    ) THEN
        ALTER TABLE strategy_performance 
        ADD COLUMN regime VARCHAR(50);
        
        CREATE INDEX idx_strategy_performance_regime 
        ON strategy_performance(regime);
    END IF;
END $$;

COMMENT ON TABLE market_regime IS 'Tracks current market regime (trending/ranging/volatile) for each symbol';
COMMENT ON TABLE performance_goals IS 'Adaptive profit targets that adjust based on system performance';
COMMENT ON TABLE daily_performance IS 'Daily P&L and performance tracking against goals';
COMMENT ON TABLE optimization_queue IS 'Queue for automated per-symbol strategy optimization';
COMMENT ON TABLE ai_orchestration_log IS 'AI system-level decisions and recommendations';
