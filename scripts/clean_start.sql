-- Clean Start Script
-- Removes old trade data while preserving historical candle data and system configuration

-- Clear positions and trades
TRUNCATE TABLE positions CASCADE;

-- Clear signal data
TRUNCATE TABLE signal_evaluations CASCADE;
TRUNCATE TABLE signal_votes CASCADE;
TRUNCATE TABLE signals CASCADE;

-- Reset strategy performance to start fresh
TRUNCATE TABLE strategy_performance CASCADE;

-- Clear performance goals and daily tracking
TRUNCATE TABLE daily_performance CASCADE;
DELETE FROM performance_goals;
INSERT INTO performance_goals (goal_type, target_profit_pct, baseline_pct, current_streak, best_streak, times_met, times_missed)
VALUES ('daily', 0.05, 0.05, 0, 0, 0, 0);

-- Clear AI orchestration log
TRUNCATE TABLE ai_orchestration_log CASCADE;

-- Clear optimization queue (we'll repopulate it)
TRUNCATE TABLE optimization_queue CASCADE;

-- Clear portfolio snapshots if they exist
DO $$ 
BEGIN
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'portfolio_snapshots') THEN
        EXECUTE 'TRUNCATE TABLE portfolio_snapshots CASCADE';
    END IF;
END $$;

-- Initialize portfolio snapshots for paper and live modes
INSERT INTO portfolio_snapshots (
    timestamp, mode, total_capital, deployed_capital, available_capital,
    open_positions, total_pnl, total_pnl_pct, daily_pnl, daily_pnl_pct,
    daily_target_met, consecutive_days_target_met, positions_snapshot
) VALUES (
    NOW(), 'paper', 1000.00, 0, 1000.00, 0, 0, 0, 0, 0, false, 0, '[]'::jsonb
);

INSERT INTO portfolio_snapshots (
    timestamp, mode, total_capital, deployed_capital, available_capital,
    open_positions, total_pnl, total_pnl_pct, daily_pnl, daily_pnl_pct,
    daily_target_met, consecutive_days_target_met, positions_snapshot
) VALUES (
    NOW(), 'live', 0, 0, 0, 0, 0, 0, 0, 0, false, 0, '[]'::jsonb
);

-- Verify clean state
SELECT 
    'positions' as table_name, COUNT(*) as rows FROM positions
UNION ALL
SELECT 'signals', COUNT(*) FROM signals
UNION ALL
SELECT 'strategy_performance', COUNT(*) FROM strategy_performance
UNION ALL
SELECT 'daily_performance', COUNT(*) FROM daily_performance
UNION ALL
SELECT 'performance_goals', COUNT(*) FROM performance_goals
UNION ALL
SELECT 'optimization_queue', COUNT(*) FROM optimization_queue
UNION ALL
SELECT 'portfolio_snapshots', COUNT(*) FROM portfolio_snapshots
ORDER BY table_name;
