-- Consensus Decisions Table
-- Stores details of ensemble consensus voting for transparency

CREATE TABLE IF NOT EXISTS consensus_decisions (
    id SERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    signal_type TEXT NOT NULL,  -- BUY or SELL
    consensus_pct FLOAT NOT NULL,
    strategy_count INTEGER NOT NULL,
    best_quality FLOAT NOT NULL,
    avg_quality FLOAT NOT NULL,
    price_at_signal FLOAT NOT NULL,
    projected_return_pct FLOAT,
    
    -- Voting breakdown
    strategy_votes JSONB NOT NULL,  -- Array of {strategy_name, quality, weight, win_rate}
    ai_vote JSONB,  -- {vote, weight, confidence, reasoning}
    sentiment_vote JSONB,  -- {score, weight, recommendation, sources}
    total_weight FLOAT NOT NULL,
    total_possible FLOAT NOT NULL,
    
    -- Decision outcome
    approved BOOLEAN NOT NULL,  -- Did it pass supermajority?
    executed BOOLEAN DEFAULT false,  -- Did we execute the trade?
    position_id INTEGER,  -- FK to positions table if executed
    
    -- Metadata
    signal_ids INTEGER[],  -- Array of signal IDs that contributed
    generated_at TIMESTAMPTZ NOT NULL,
    decided_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- After-action link
    trade_outcome TEXT,  -- win, loss, pending
    realized_pnl_pct FLOAT,
    afteraction_notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_consensus_decided ON consensus_decisions(decided_at DESC);
CREATE INDEX IF NOT EXISTS idx_consensus_symbol ON consensus_decisions(symbol);
CREATE INDEX IF NOT EXISTS idx_consensus_approved ON consensus_decisions(approved);
CREATE INDEX IF NOT EXISTS idx_consensus_executed ON consensus_decisions(executed);
CREATE INDEX IF NOT EXISTS idx_consensus_position ON consensus_decisions(position_id);
