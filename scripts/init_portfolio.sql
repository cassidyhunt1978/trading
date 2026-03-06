-- Initialize portfolio snapshots for paper and live modes
-- This creates the initial portfolio state with starting capital

-- Paper mode: Start with $1000
INSERT INTO portfolio_snapshots (
    timestamp,
    mode,
    total_capital,
    deployed_capital,
    available_capital,
    open_positions,
    total_pnl,
    total_pnl_pct,
    daily_pnl,
    daily_pnl_pct,
    daily_target_met,
    consecutive_days_target_met,
    positions_snapshot
) VALUES (
    NOW(),
    'paper',
    1000.00,
    0,
    1000.00,
    0,
    0,
    0,
    0,
    0,
    false,
    0,
    '[]'::jsonb
)
ON CONFLICT DO NOTHING;

-- Live mode: Start with $0 (will sync from exchange)
INSERT INTO portfolio_snapshots (
    timestamp,
    mode,
    total_capital,
    deployed_capital,
    available_capital,
    open_positions,
    total_pnl,
    total_pnl_pct,
    daily_pnl,
    daily_pnl_pct,
    daily_target_met,
    consecutive_days_target_met,
    positions_snapshot
) VALUES (
    NOW(),
    'live',
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    false,
    0,
    '[]'::jsonb
)
ON CONFLICT DO NOTHING;

-- Verify
SELECT 
    mode,
    total_capital,
    available_capital,
    open_positions,
    TO_CHAR(timestamp, 'YYYY-MM-DD HH24:MI:SS') as snapshot_time
FROM portfolio_snapshots
ORDER BY timestamp DESC;
