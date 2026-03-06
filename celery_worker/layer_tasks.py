"""
Layer Enhancements for Trading System
Celery tasks for automated optimization, AI orchestration, and goal management
"""

import requests
import psycopg2
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional
import json
import structlog

from shared.database import get_connection
from shared.config import get_settings

logger = structlog.get_logger()
settings = get_settings()


# ============================================================================
# LAYER 2: AUTOMATED PER-SYMBOL OPTIMIZATION
# ============================================================================

def queue_strategy_optimization(strategy_id: int, symbol: str, priority: int = 50):
    """Add a strategy-symbol combo to the optimization queue"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO optimization_queue 
                    (strategy_id, symbol, priority, status, requested_at)
                    VALUES (%s, %s, %s, 'pending', NOW())
                    ON CONFLICT (strategy_id, symbol, status)
                    DO UPDATE SET priority = GREATEST(optimization_queue.priority, EXCLUDED.priority)
                """, (strategy_id, symbol, priority))
        
        logger.info("optimization_queued", strategy_id=strategy_id, symbol=symbol, priority=priority)
        return True
    except Exception as e:
        logger.error("queue_optimization_error", error=str(e))
        return False


def run_symbol_optimization(strategy_id: int, symbol: str) -> Dict:
    """Run optimization for a specific strategy-symbol combination"""
    try:
        # Mark as running
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE optimization_queue
                    SET status = 'running', started_at = NOW()
                    WHERE strategy_id = %s AND symbol = %s AND status = 'pending'
                """, (strategy_id, symbol))
        
        # Get strategy config from Strategy Config API
        response = requests.get(
            f"http://{settings.service_host}:{settings.port_strategy_config_api}/strategies/{strategy_id}/config",
            timeout=10
        )
        
        if response.status_code != 200:
            raise Exception(f"Failed to get strategy config: {response.text}")
        
        strategy_config = response.json()
        tunable_params = strategy_config.get('tunable_parameters', [])
        
        if not tunable_params:
            # No tunable parameters, mark as completed
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE optimization_queue
                        SET status = 'completed', 
                            completed_at = NOW(),
                            result = %s
                        WHERE strategy_id = %s AND symbol = %s
                    """, (json.dumps({'skipped': 'no_tunable_params'}), strategy_id, symbol))
            
            return {'status': 'skipped', 'reason': 'no_tunable_parameters'}
        
        # Build parameter ranges for optimization
        param_ranges = {}
        for param in tunable_params:
            # Test min, mid, max values
            min_val = param['min_value']
            max_val = param['max_value']
            mid_val = (min_val + max_val) / 2
            param_ranges[param['name']] = [min_val, mid_val, max_val]
        
        # Run optimization via Optimization API
        optimization_request = {
            'strategy_id': strategy_id,
            'symbol': symbol,
            'method': 'grid_search',
            'parameter_ranges': param_ranges,
            'start_date': (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d'),
            'end_date': datetime.now().strftime('%Y-%m-%d'),
            'initial_capital': 1000.0
        }
        
        response = requests.post(
            f"http://{settings.service_host}:{settings.port_optimization_api}/optimize",
            json=optimization_request,
            timeout=120  # Optimization can take time
        )
        
        if response.status_code != 200:
            raise Exception(f"Optimization failed: {response.text}")
        
        result = response.json()
        
        # Mark as completed
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE optimization_queue
                    SET status = 'completed', 
                        completed_at = NOW(),
                        result = %s
                    WHERE strategy_id = %s AND symbol = %s
                """, (json.dumps(result), strategy_id, symbol))
        
        logger.info("optimization_completed", 
                   strategy_id=strategy_id, 
                   symbol=symbol,
                   score=result.get('best_score'))
        
        return result
        
    except Exception as e:
        # Mark as failed
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE optimization_queue
                    SET status = 'failed', 
                        completed_at = NOW(),
                        error_message = %s
                    WHERE strategy_id = %s AND symbol = %s
                """, (str(e), strategy_id, symbol))
        
        logger.error("optimization_failed", strategy_id=strategy_id, symbol=symbol, error=str(e))
        return {'status': 'error', 'error': str(e)}


def process_optimization_queue(max_concurrent: int = 1):
    """Process pending optimizations from the queue"""
    try:
        logger.info("processing_optimization_queue", max_concurrent=max_concurrent)
        
        processed = 0
        
        while processed < max_concurrent:
            # Get next pending optimization
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT strategy_id, symbol
                        FROM optimization_queue
                        WHERE status = 'pending'
                        ORDER BY priority DESC, requested_at ASC
                        LIMIT 1
                        FOR UPDATE SKIP LOCKED
                    """)
                    
                    row = cur.fetchone()
                    if not row:
                        break  # No more pending optimizations
                    
                    strategy_id = row['strategy_id']
                    symbol = row['symbol']
            
            # Run optimization
            run_symbol_optimization(strategy_id, symbol)
            processed += 1
        
        logger.info("optimization_queue_processed", count=processed)
        return {'processed': processed}
        
    except Exception as e:
        logger.error("process_queue_error", error=str(e))
        return {'error': str(e)}


# ============================================================================
# LAYER 5: AI ORCHESTRATION
# ============================================================================

def ai_analyze_system_health() -> Dict:
    """Let AI analyze overall system health and make recommendations"""
    try:
        # Gather system metrics
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Get recent performance
                cur.execute("""
                    SELECT 
                        COUNT(*) as total_positions,
                        COUNT(*) FILTER (WHERE realized_pnl > 0) as wins,
                        AVG(realized_pnl) as avg_pnl,
                        SUM(realized_pnl) as total_pnl
                    FROM positions
                    WHERE status = 'closed'
                    AND mode = 'paper'
                    AND exit_time > NOW() - INTERVAL '7 days'
                """)
                recent_perf = dict(cur.fetchone())
                
                # Get signal generation stats
                cur.execute("""
                    SELECT 
                        COUNT(*) as total_signals,
                        COUNT(DISTINCT strategy_id) as active_strategies,
                        COUNT(DISTINCT symbol) as active_symbols,
                        AVG(quality_score) as avg_quality
                    FROM signals
                    WHERE generated_at > NOW() - INTERVAL '24 hours'
                """)
                signal_stats = dict(cur.fetchone())
                
                # Get blacklist status
                cur.execute("""
                    SELECT symbol, COUNT(*) as bad_count
                    FROM positions
                    WHERE status = 'closed'
                    AND mode = 'paper'
                    AND realized_pnl < 0
                    AND exit_time > NOW() - INTERVAL '30 days'
                    GROUP BY symbol
                    HAVING COUNT(*) > 3
                    ORDER BY COUNT(*) DESC
                """)
                problematic_symbols = [dict(row) for row in cur.fetchall()]
        
        # Ask AI for analysis
        analysis_request = {
            'recent_performance': recent_perf,
            'signal_stats': signal_stats,
            'problematic_symbols': problematic_symbols[:10],
            'question': 'Analyze system health and recommend improvements'
        }
        
        response = requests.post(
            f"http://{settings.service_host}:{settings.port_ai_api}/analyze",
            json=analysis_request,
            timeout=30
        )
        
        if response.status_code != 200:
            raise Exception(f"AI analysis failed: {response.text}")
        
        ai_response = response.json()
        
        # Log AI recommendation
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO ai_orchestration_log
                    (decision_type, decision, reasoning, confidence, created_at)
                    VALUES (%s, %s, %s, %s, NOW())
                """, (
                    'system_health_analysis',
                    json.dumps(ai_response.get('recommendation', {})),
                    ai_response.get('reasoning', ''),
                    ai_response.get('confidence', 50.0)
                ))
        
        logger.info("ai_analysis_completed", confidence=ai_response.get('confidence'))
        return ai_response
        
    except Exception as e:
        logger.error("ai_analysis_error", error=str(e))
        return {'error': str(e)}


def ai_recommend_strategy_weights() -> Dict:
    """AI recommends weight adjustments for strategies based on performance"""
    try:
        # Get strategy performance data
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        s.id,
                        s.name,
                        COUNT(sp.id) as symbols_traded,
                        AVG(sp.win_rate) as avg_win_rate,
                        AVG(sp.sharpe_ratio) as avg_sharpe,
                        SUM(sp.total_trades) as total_trades
                    FROM strategies s
                    LEFT JOIN strategy_performance sp ON s.id = sp.strategy_id
                    WHERE s.enabled = true
                    AND sp.period_days = 14
                    GROUP BY s.id, s.name
                    HAVING SUM(sp.total_trades) > 5
                    ORDER BY AVG(sp.sharpe_ratio) DESC NULLS LAST
                """)
                strategy_performance = [dict(row) for row in cur.fetchall()]
        
        # Ask AI to recommend weights
        weight_request = {
            'strategy_performance': strategy_performance,
            'question': 'Recommend optimal weights for ensemble voting based on this performance data'
        }
        
        response = requests.post(
            f"http://{settings.service_host}:{settings.port_ai_api}/analyze",
            json=weight_request,
            timeout=30
        )
        
        if response.status_code != 200:
            raise Exception(f"AI weight recommendation failed: {response.text}")
        
        ai_response = response.json()
        
        # Log recommendation
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO ai_orchestration_log
                    (decision_type, decision, reasoning, confidence, created_at)
                    VALUES (%s, %s, %s, %s, NOW())
                """, (
                    'strategy_weight_recommendation',
                    json.dumps(ai_response.get('recommendation', {})),
                    ai_response.get('reasoning', ''),
                    ai_response.get('confidence', 50.0)
                ))
        
        logger.info("ai_weight_recommendation", confidence=ai_response.get('confidence'))
        return ai_response
        
    except Exception as e:
        logger.error("ai_weight_error", error=str(e))
        return {'error': str(e)}


# ============================================================================
# LAYER 8: GOAL MANAGEMENT
# ============================================================================

def record_daily_performance():
    """Record daily performance and check if goals were met"""
    try:
        today = date.today()
        yesterday = today - timedelta(days=1)
        
        logger.info("recording_daily_performance", date=yesterday)
        
        # Get yesterday's performance
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Get starting capital (first snapshot of yesterday)
                cur.execute("""
                    SELECT total_value
                    FROM portfolio_snapshots
                    WHERE mode = 'paper'
                    AND DATE(timestamp) = %s
                    ORDER BY timestamp ASC
                    LIMIT 1
                """, (yesterday,))
                
                start_row = cur.fetchone()
                if not start_row:
                    logger.warning("no_starting_capital", date=yesterday)
                    return {'status': 'skipped', 'reason': 'no_data'}
                
                starting_capital = float(start_row[0])
                
                # Get ending capital (last snapshot of yesterday)
                cur.execute("""
                    SELECT total_value
                    FROM portfolio_snapshots
                    WHERE mode = 'paper'
                    AND DATE(timestamp) = %s
                    ORDER BY timestamp DESC
                    LIMIT 1
                """, (yesterday,))
                
                end_row = cur.fetchone()
                ending_capital = float(end_row[0]) if end_row else starting_capital
                
                # Get trades for the day
                cur.execute("""
                    SELECT 
                        COUNT(*) as total_trades,
                        COUNT(*) FILTER (WHERE realized_pnl > 0) as wins,
                        COUNT(*) FILTER (WHERE realized_pnl < 0) as losses,
                        SUM(realized_pnl) as total_pnl
                    FROM positions
                    WHERE status = 'closed'
                    AND mode = 'paper'
                    AND DATE(exit_time) = %s
                """, (yesterday,))
                
                trade_data = dict(cur.fetchone())
                
                # Calculate metrics
                realized_pnl = float(trade_data.get('total_pnl') or 0)
                return_pct = ((ending_capital - starting_capital) / starting_capital) * 100
                win_count = trade_data.get('wins') or 0
                loss_count = trade_data.get('losses') or 0
                total_trades = trade_data.get('total_trades') or 0
                win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0
                
                # Get current daily goal
                cur.execute("""
                    SELECT target_profit_pct
                    FROM performance_goals
                    WHERE goal_type = 'daily'
                    ORDER BY updated_at DESC
                    LIMIT 1
                """)
                
                goal_row = cur.fetchone()
                daily_goal_pct = float(goal_row[0]) if goal_row else 0.05
                goal_met = return_pct >= daily_goal_pct
                
                # Insert daily performance record
                cur.execute("""
                    INSERT INTO daily_performance
                    (trade_date, mode, starting_capital, ending_capital, realized_pnl,
                     return_pct, trades_executed, win_count, loss_count, win_rate,
                     daily_goal_pct, goal_met, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (trade_date) 
                    DO UPDATE SET
                        ending_capital = EXCLUDED.ending_capital,
                        realized_pnl = EXCLUDED.realized_pnl,
                        return_pct = EXCLUDED.return_pct,
                        trades_executed = EXCLUDED.trades_executed,
                        win_count = EXCLUDED.win_count,
                        loss_count = EXCLUDED.loss_count,
                        win_rate = EXCLUDED.win_rate,
                        goal_met = EXCLUDED.goal_met
                """, (
                    yesterday, 'paper', starting_capital, ending_capital,
                    realized_pnl, return_pct, total_trades, win_count,
                    loss_count, win_rate, daily_goal_pct, goal_met
                ))
                
                # Update goal streak
                if goal_met:
                    cur.execute("""
                        UPDATE performance_goals
                        SET current_streak = current_streak + 1,
                            best_streak = GREATEST(best_streak, current_streak + 1),
                            times_met = times_met + 1,
                            updated_at = NOW()
                        WHERE goal_type = 'daily'
                    """)
                else:
                    cur.execute("""
                        UPDATE performance_goals
                        SET current_streak = 0,
                            times_missed = times_missed + 1,
                            updated_at = NOW()
                        WHERE goal_type = 'daily'
                    """)
        
        logger.info("daily_performance_recorded",
                   date=yesterday,
                   return_pct=return_pct,
                   goal_met=goal_met)
        
        return {
            'date': str(yesterday),
            'return_pct': return_pct,
            'goal_pct': daily_goal_pct,
            'goal_met': goal_met,
            'trades': total_trades
        }
        
    except Exception as e:
        logger.error("record_daily_performance_error", error=str(e))
        return {'error': str(e)}


def adjust_performance_goals():
    """Adaptively adjust goals based on recent success rate"""
    try:
        logger.info("adjusting_performance_goals")
        
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Get current goal
                cur.execute("""
                    SELECT id, target_profit_pct, baseline_pct, current_streak, 
                           times_met, times_missed, last_adjustment_date
                    FROM performance_goals
                    WHERE goal_type = 'daily'
                    LIMIT 1
                """)
                
                goal_data = dict(cur.fetchone())
                goal_id = goal_data['id']
                current_target = float(goal_data['target_profit_pct'])
                baseline = float(goal_data['baseline_pct'])
                streak = goal_data['current_streak'] or 0
                times_met = goal_data['times_met'] or 0
                times_missed = goal_data['times_missed'] or 0
                last_adjustment = goal_data.get('last_adjustment_date')
                
                # Get recent performance (last 30 days)
                cur.execute("""
                    SELECT 
                        COUNT(*) as total_days,
                        COUNT(*) FILTER (WHERE goal_met = true) as days_met,
                        AVG(return_pct) as avg_return
                    FROM daily_performance
                    WHERE trade_date > NOW() - INTERVAL '30 days'
                """)
                
                recent = dict(cur.fetchone())
                total_days = recent.get('total_days') or 0
                days_met = recent.get('days_met') or 0
                avg_return = float(recent.get('avg_return') or 0)
                
                if total_days < 10:
                    logger.info("insufficient_data_for_adjustment", days=total_days)
                    return {'status': 'skipped', 'reason': 'insufficient_data'}
                
                success_rate = days_met / total_days
                
                # Adjustment logic
                new_target = current_target
                reason = ''
                
                # Increase goal if consistently meeting it
                if streak >= 7 and success_rate >= 0.70:
                    # Increase by 10% of current value
                    new_target = current_target * 1.10
                    reason = f'7-day streak with {success_rate:.0%} success rate'
                
                # Increase goal if very high success rate
                elif days_met >= 20 and success_rate >= 0.80:
                    new_target = current_target * 1.05
                    reason = f'{days_met} days met with {success_rate:.0%} success rate'
                
                # Decrease goal if consistently missing
                elif times_missed >= 10 and success_rate < 0.30:
                    # Decrease by 20% but not below baseline
                    new_target = max(baseline, current_target * 0.80)
                    reason = f'{times_missed} misses with {success_rate:.0%} success rate'
                
                # Adjust to average if very inconsistent but average is better than target
                elif total_days >= 20 and abs(avg_return - current_target) > current_target * 0.5:
                    if avg_return > current_target:
                        new_target = (current_target + avg_return) / 2
                        reason = f'Adjusting to midpoint between target and actual ({avg_return:.3f}%)'
                
                # Apply adjustment if changed
                if new_target != current_target:
                    cur.execute("""
                        UPDATE performance_goals
                        SET target_profit_pct = %s,
                            last_adjustment_date = %s,
                            updated_at = NOW(),
                            metadata = jsonb_set(
                                COALESCE(metadata, '{}'::jsonb),
                                '{adjustments}',
                                COALESCE(metadata->'adjustments', '[]'::jsonb) || 
                                jsonb_build_object(
                                    'date', %s,
                                    'old_target', %s,
                                    'new_target', %s,
                                    'reason', %s,
                                    'success_rate', %s
                                )::jsonb
                            )
                        WHERE id = %s
                    """, (
                        new_target, date.today(), date.today(),
                        current_target, new_target, reason, success_rate, goal_id
                    ))
                    
                    logger.info("goal_adjusted",
                               old_target=current_target,
                               new_target=new_target,
                               reason=reason)
                    
                    return {
                        'adjusted': True,
                        'old_target': current_target,
                        'new_target': new_target,
                        'reason': reason
                    }
                else:
                    logger.info("no_adjustment_needed",
                               success_rate=success_rate,
                               streak=streak)
                    
                    return {
                        'adjusted': False,
                        'current_target': current_target,
                        'success_rate': success_rate
                    }
        
    except Exception as e:
        logger.error("adjust_goals_error", error=str(e))
        return {'error': str(e)}


# Expose functions for import
__all__ = [
    'queue_strategy_optimization',
    'run_symbol_optimization',
    'process_optimization_queue',
    'ai_analyze_system_health',
    'ai_recommend_strategy_weights',
    'record_daily_performance',
    'adjust_performance_goals'
]
