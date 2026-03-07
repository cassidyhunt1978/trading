"""Celery Tasks for Trading System Automation"""
from celery import Celery
from celery.schedules import crontab
import requests
import sys
import os
import json
import numpy as np
from datetime import datetime, timedelta
from collections import Counter
from itertools import product

sys.path.append('/opt/trading')

from shared.database import get_connection, get_active_symbols
from shared.config import get_settings
from shared.logging_config import setup_logging

# Consensus Engine - now integrated into Signal API
# No separate import needed, uses /signals/consensus endpoint
CONSENSUS_ENGINE_AVAILABLE = True  # Always available via Signal API

settings = get_settings()
logger = setup_logging('celery_worker', settings.log_level)

# Initialize Celery
celery_app = Celery(
    'trading_system',
    broker=settings.redis_url,
    backend=settings.redis_url
)

celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
)

# Task: Fetch 1-minute candles
@celery_app.task(name='fetch_1min_candles')
def fetch_1min_candles():
    """Fetch 1-minute candles for all active symbols"""
    try:
        logger.info("task_started", task="fetch_1min_candles")
        
        symbols = get_active_symbols()
        results = []
        
        for symbol in symbols:
            try:
                # Call OHLCV API to fetch LATEST candles (not backfill)
                response = requests.post(
                    f"http://{settings.service_host}:{settings.port_ohlcv_api}/candles/fetch",
                    params={
                        'symbol': symbol['symbol'],
                        'timeframe': '1m',
                        'limit': 5,
                        'fetch_latest': True  # Fetch most recent candles
                    },
                    timeout=30
                )
                
                if response.status_code == 200:
                    results.append({'symbol': symbol['symbol'], 'status': 'success'})
                    logger.info("candles_fetched", symbol=symbol['symbol'])
                else:
                    results.append({'symbol': symbol['symbol'], 'status': 'failed', 'error': response.text})
                    logger.error("candles_fetch_failed", symbol=symbol['symbol'], error=response.text)
            
            except Exception as e:
                results.append({'symbol': symbol['symbol'], 'status': 'error', 'error': str(e)})
                logger.error("candles_fetch_error", symbol=symbol['symbol'], error=str(e))
        
        logger.info("task_completed", task="fetch_1min_candles", results=results)
        return results
    
    except Exception as e:
        logger.error("task_error", task="fetch_1min_candles", error=str(e))
        return {'status': 'error', 'message': str(e)}

# Task: Backfill historical 1-minute candles
@celery_app.task(name='backfill_historical_candles')
def backfill_historical_candles():
    """Backfill missing historical 1-minute candles for all active symbols"""
    import time
    
    try:
        logger.info("task_started", task="backfill_historical_candles")
        
        symbols = get_active_symbols()
        results = []
        
        # Target: 30 days = 43,200 candles per symbol (reduced from 180 days)
        # 180 days was too aggressive and overloaded the system
        # Strategy: Fetch 500 candles at a time (conservative for rate limits)
        # At 1 request per second = safe for Coinbase free tier (10 req/sec limit)
        
        for symbol in symbols:
            try:
                # Check current candle count for this symbol
                with get_connection() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute(
                            "SELECT COUNT(*) as count FROM ohlcv_candles WHERE symbol = %s",
                            (symbol['symbol'],)
                        )
                        current_count = cursor.fetchone()['count']
                
                target_count = 180 * 24 * 60  # 180 days of 1-minute candles
                
                if current_count >= target_count:
                    logger.info("symbol_has_sufficient_data", 
                              symbol=symbol['symbol'], 
                              current=current_count, 
                              target=target_count)
                    results.append({
                        'symbol': symbol['symbol'],
                        'status': 'skipped',
                        'current_count': current_count
                    })
                    continue
                
                # Fetch historical data in batches of 500 until we have 180 days
                batch_size = 500
                fetched_total = 0
                batch_num = 0
                max_batches_per_run = 20  # Limit batches per run to reduce database load
                
                logger.info("backfilling_symbol", 
                          symbol=symbol['symbol'], 
                          current=current_count, 
                          target=target_count,
                          needed=target_count - current_count)
                
                # Keep fetching until we have enough data or run out of historical data
                while current_count + fetched_total < target_count and batch_num < max_batches_per_run:
                    try:
                        response = requests.post(
                            f"http://{settings.service_host}:{settings.port_ohlcv_api}/candles/fetch",
                            params={
                                'symbol': symbol['symbol'],
                                'timeframe': '1m',
                                'limit': batch_size,
                                'fetch_latest': False  # Backfill historical data
                            },
                            timeout=60
                        )
                        
                        if response.status_code == 200:
                            data = response.json()
                            fetched = data.get('candles_fetched', 0)
                            fetched_total += fetched
                            batch_num += 1
                            
                            if fetched == 0:
                                logger.info("no_more_candles", 
                                          symbol=symbol['symbol'],
                                          total_fetched=fetched_total,
                                          batches=batch_num)
                                
                                # FAILSAFE: If we got 0 candles after multiple attempts, 
                                # this symbol likely has no historical data
                                if fetched_total < 1000 and batch_num >= 3:
                                    logger.warning("symbol_insufficient_data",
                                                 symbol=symbol['symbol'],
                                                 total=fetched_total,
                                                 msg="Disabling symbol due to insufficient data")
                                    # Disable symbol
                                    with get_connection() as conn2:
                                        with conn2.cursor() as cur2:
                                            cur2.execute("""
                                                UPDATE symbols
                                                SET status = 'insufficient_data',
                                                    metadata = jsonb_set(
                                                        COALESCE(metadata, '{}'::jsonb),
                                                        '{disabled_reason}',
                                                        '"Not enough historical data available"'
                                                    )
                                                WHERE symbol = %s
                                            """, (symbol['symbol'],))
                                        conn2.commit()
                                break
                            
                            # Log progress every 10 batches
                            if batch_num % 10 == 0:
                                logger.info("backfill_progress",
                                          symbol=symbol['symbol'],
                                          batches=batch_num,
                                          fetched=fetched_total,
                                          current_total=current_count + fetched_total,
                                          target=target_count)
                        else:
                            logger.warning("batch_failed", 
                                         symbol=symbol['symbol'], 
                                         status=response.status_code,
                                         batch=batch_num)
                            
                            # FAILSAFE: If multiple batches fail, disable symbol
                            if batch_num >= 3:
                                logger.error("symbol_repeatedly_failing",
                                           symbol=symbol['symbol'],
                                           msg="Disabling symbol due to repeated failures")
                                # Disable symbol
                                with get_connection() as conn2:
                                    with conn2.cursor() as cur2:
                                        cur2.execute("""
                                            UPDATE symbols
                                            SET status = 'failed',
                                                metadata = jsonb_set(
                                                    COALESCE(metadata, '{}'::jsonb),
                                                    '{disabled_reason}',
                                                    '"Repeated API failures during backfill"'
                                                )
                                            WHERE symbol = %s
                                        """, (symbol['symbol'],))
                                    conn2.commit()
                            break
                        
                        # Rate limit: 2 seconds between requests to reduce database contention
                        time.sleep(2)
                        
                    except Exception as e:
                        logger.error("batch_error", 
                                   symbol=symbol['symbol'], 
                                   batch=batch_num, 
                                   error=str(e))
                        break
                
                results.append({
                    'symbol': symbol['symbol'],
                    'status': 'success',
                    'fetched': fetched_total,
                    'total_count': current_count + fetched_total
                })
                
                logger.info("symbol_backfill_complete", 
                          symbol=symbol['symbol'], 
                          fetched=fetched_total,
                          total=current_count + fetched_total)
                
            except Exception as e:
                logger.error("symbol_backfill_error", 
                           symbol=symbol['symbol'], 
                           error=str(e))
                results.append({
                    'symbol': symbol['symbol'],
                    'status': 'error',
                    'error': str(e)
                })
        
        logger.info("task_completed", task="backfill_historical_candles", results=results)
        return results
    
    except Exception as e:
        logger.error("task_error", task="backfill_historical_candles", error=str(e))
        return {'status': 'error', 'message': str(e)}

# Task: Compute indicators
@celery_app.task(name='compute_indicators')
def compute_indicators():
    """Compute technical indicators for all active symbols"""
    try:
        logger.info("task_started", task="compute_indicators")
        
        symbols = get_active_symbols()
        results = []
        
        # List of indicators to compute
        indicators_list = ['rsi', 'macd', 'bbands', 'sma', 'ema', 'vwap', 'adx', 'atr']
        
        for symbol in symbols:
            symbol_success = True
            try:
                # Compute each indicator separately
                for indicator in indicators_list:
                    response = requests.post(
                        f"http://{settings.service_host}:{settings.port_ohlcv_api}/indicators/compute",
                        params={
                            'symbol': symbol['symbol'],
                            'indicator': indicator
                        },
                        timeout=30
                    )
                    
                    if response.status_code != 200:
                        symbol_success = False
                        logger.error("indicator_compute_failed", symbol=symbol['symbol'], indicator=indicator, error=response.text)
                
                if symbol_success:
                    results.append({'symbol': symbol['symbol'], 'status': 'success'})
                    logger.info("indicators_computed", symbol=symbol['symbol'])
                else:
                    results.append({'symbol': symbol['symbol'], 'status': 'partial'})
            
            except Exception as e:
                results.append({'symbol': symbol['symbol'], 'status': 'error', 'error': str(e)})
                logger.error("indicators_error", symbol=symbol['symbol'], error=str(e))
        
        logger.info("task_completed", task="compute_indicators", results=results)
        return results
    
    except Exception as e:
        logger.error("task_error", task="compute_indicators", error=str(e))
        return {'status': 'error', 'message': str(e)}

# Task: Generate signals
@celery_app.task(name='generate_signals')
def generate_signals():
    """Generate trading signals from all active strategies"""
    try:
        logger.info("task_started", task="generate_signals")
        
        # Call Signal API to generate signals
        response = requests.post(
            f"http://{settings.service_host}:{settings.port_signal_api}/signals/generate",
            timeout=60
        )
        
        if response.status_code == 200:
            data = response.json()
            logger.info("task_completed", task="generate_signals", signals=data.get('signals_generated', 0))
            return data
        else:
            logger.error("task_failed", task="generate_signals", error=response.text)
            return {'status': 'error', 'message': response.text}
    
    except Exception as e:
        logger.error("task_error", task="generate_signals", error=str(e))
        return {'status': 'error', 'message': str(e)}

# Task: Execute paper trades for ALL strategy signals
@celery_app.task(name='execute_paper_trades_all_strategies')
def execute_paper_trades_all_strategies():
    """Execute paper trades for signals from ALL strategies to compare backtest vs reality"""
    try:
        logger.info("task_started", task="execute_paper_trades_all_strategies")
        
        # Get active signals from ALL strategies (not just primary)
        # This allows us to collect real-world performance data for every strategy
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        s.id as signal_id,
                        s.symbol,
                        s.strategy_id,
                        s.signal_type,
                        s.quality_score,
                        s.price_at_signal,
                        s.projected_return_pct,
                        st.name as strategy_name
                    FROM signals s
                    JOIN strategies st ON st.id = s.strategy_id
                    WHERE s.acted_on = false
                        AND s.expires_at > NOW()
                        AND s.quality_score >= %s
                        AND s.signal_type = 'BUY'
                    ORDER BY s.quality_score DESC, s.generated_at ASC
                    LIMIT 50
                """, (settings.min_signal_quality,))
                
                signals = cur.fetchall()
        
        if not signals:
            logger.info("no_signals", message="No signals to execute")
            return {'status': 'success', 'trades_executed': 0, 'reason': 'no_signals'}
        
        logger.info("signals_found", count=len(signals))
        
        # Check trading policies and limits
        from datetime import date
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Get trading policies for paper mode
                cur.execute("SELECT * FROM trading_policies WHERE mode = 'paper'")
                policies = cur.fetchone()
                
                if not policies:
                    logger.error("no_policies_found", mode="paper")
                    return {'status': 'error', 'reason': 'no_policies_configured'}
                
                # Check emergency stop
                if policies['emergency_stop']:
                    logger.warning("emergency_stop_active", 
                                 reason=policies['emergency_stop_reason'],
                                 time=policies['emergency_stop_time'])
                    return {
                        'status': 'stopped',
                        'reason': 'emergency_stop_active',
                        'emergency_stop_reason': policies['emergency_stop_reason']
                    }
                
                # Get today's trading stats
                cur.execute("""
                    SELECT 
                        COALESCE(SUM(realized_pnl), 0) as today_pnl,
                        COUNT(*) as trades_today
                    FROM positions
                    WHERE DATE(entry_time) = %s
                        AND mode = 'paper'
                        AND status = 'closed'
                """, (date.today(),))
                today_stats = cur.fetchone()
                
                today_pnl = float(today_stats['today_pnl']) if today_stats else 0.0
                trades_today = today_stats['trades_today'] if today_stats else 0
                
                # Check daily loss limit
                if today_pnl <= -float(policies['daily_loss_limit']):
                    logger.warning("daily_loss_limit_reached",
                                 pnl=today_pnl,
                                 limit=policies['daily_loss_limit'])
                    
                    # Auto-trigger emergency stop
                    cur.execute("""
                        UPDATE trading_policies
                        SET emergency_stop = true,
                            emergency_stop_reason = 'Daily loss limit reached',
                            emergency_stop_time = NOW()
                        WHERE mode = 'paper'
                    """)
                    
                    return {
                        'status': 'stopped',
                        'reason': 'daily_loss_limit_reached',
                        'today_pnl': today_pnl,
                        'limit': float(policies['daily_loss_limit'])
                    }
                
                # Check daily trade limit
                if trades_today >= policies['daily_trade_limit']:
                    logger.warning("daily_trade_limit_reached",
                                 trades_today=trades_today,
                                 limit=policies['daily_trade_limit'])
                    return {
                        'status': 'limit_reached',
                        'reason': 'daily_trade_limit_reached',
                        'trades_today': trades_today,
                        'limit': policies['daily_trade_limit']
                    }
                
                logger.info("policy_checks_passed",
                          today_pnl=round(today_pnl, 2),
                          trades_today=trades_today,
                          loss_limit=float(policies['daily_loss_limit']),
                          trade_limit=policies['daily_trade_limit'])
        
        # Detect signal consensus (multiple strategies on same symbol)
        symbol_signal_map = {}
        for signal in signals:
            symbol = signal['symbol']
            if symbol not in symbol_signal_map:
                symbol_signal_map[symbol] = []
            symbol_signal_map[symbol].append(signal)
        
        # Tag signals with consensus count
        for signal in signals:
            signal['consensus_count'] = len(symbol_signal_map[signal['symbol']])
            signal['has_consensus'] = signal['consensus_count'] >= 2
        
        # Log consensus signals
        consensus_signals = [s for s in signals if s['has_consensus']]
        if consensus_signals:
            logger.info("consensus_signals_found", 
                       count=len(consensus_signals),
                       symbols=[s['symbol'] for s in consensus_signals])
        
        # Check for open positions and risk limits
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Count open STRATEGY positions per symbol per strategy (strategy positions don't count toward ensemble limits)
                cur.execute("""
                    SELECT symbol, strategy_id, COUNT(*) as count
                    FROM positions
                    WHERE status = 'open' AND mode = 'paper' AND position_type = 'strategy'
                    GROUP BY symbol, strategy_id
                """)
                positions_per_symbol_strategy = {(row['symbol'], row['strategy_id']): row['count'] for row in cur.fetchall()}
                
                # Get current portfolio value
                cur.execute("""
                    SELECT 
                        COALESCE(SUM(CASE WHEN status = 'open' THEN CAST(entry_price * quantity AS NUMERIC) ELSE 0 END), 0) as deployed_capital,
                        10000.0 as total_capital
                    FROM positions
                    WHERE mode = 'paper' AND position_type = 'strategy'
                """)
                portfolio = cur.fetchone()
                deployed_capital = float(portfolio['deployed_capital'])
                total_capital = float(portfolio['total_capital'])
                available_capital = total_capital - deployed_capital
        
        # Risk management - for strategy positions, enforce 1 position per symbol per strategy
        # Strategy positions are tracked separately from ensemble positions
        max_per_symbol_per_strategy = 1  # Each strategy can only have 1 position per symbol
        
        # Prioritize signals: consensus first, then by quality
        signals_sorted = sorted(signals, 
                              key=lambda s: (s['has_consensus'], s['quality_score']), 
                              reverse=True)
        
        trades_executed = 0
        execution_results = []
        strategies_traded = set()
        
        for signal in signals_sorted:
            # Check if this strategy already has a position on this symbol
            strategy_id = signal['strategy_id']
            symbol = signal['symbol']
            current_positions_for_symbol_strategy = positions_per_symbol_strategy.get((symbol, strategy_id), 0)
            
            if current_positions_for_symbol_strategy >= max_per_symbol_per_strategy:
                continue  # Skip this signal, strategy already has a position on this symbol
            
            # Calculate position size (5% of total capital for testing)
            max_position_size_pct = 0.05  # 5% per position
            max_position_size = float(policies['max_position_size'])  # Policy limit in dollars
            max_position_value = total_capital * max_position_size_pct
            
            # Use available capital per position
            position_value = min(max_position_value, max_position_size, available_capital)
            
            if position_value < 50:  # Minimum $50 per trade
                logger.warning("insufficient_capital", available=available_capital)
                continue  # Skip this signal, not enough capital
            
            # Boost position size for consensus signals (up to 1.5x, still capped by policy)
            if signal['has_consensus']:
                boosted_value = position_value * 1.5
                position_value = min(boosted_value, max_position_size)
            
            # Calculate amount to buy
            amount = position_value / float(signal['price_at_signal'])
            
            # Execute trade via Trading API
            try:
                projected_return = float(signal['projected_return_pct']) if signal['projected_return_pct'] else 5.0
                
                trade_payload = {
                    'symbol': signal['symbol'],
                    'side': 'buy',
                    'amount': float(amount),
                    'mode': 'paper',
                    'signal_id': int(signal['signal_id']),
                    'strategy_id': int(signal['strategy_id']),
                    'stop_loss_pct': 2.0,
                    'take_profit_pct': projected_return if projected_return > 0 else 5.0,
                    'position_type': 'strategy'
                }
                
                response = requests.post(
                    f"http://{settings.service_host}:{settings.port_trading_api}/execute",
                    json=trade_payload,
                    timeout=30
                )
                
                if response.status_code == 200:
                    result = response.json()
                    trades_executed += 1
                    strategies_traded.add(strategy_id)
                    # Update tracking dict to reflect new position
                    positions_per_symbol_strategy[(symbol, strategy_id)] = current_positions_for_symbol_strategy + 1
                    
                    execution_results.append({
                        'signal_id': signal['signal_id'],
                        'symbol': signal['symbol'],
                        'strategy_id': strategy_id,
                        'strategy_name': signal['strategy_name'],
                        'status': 'executed',
                        'amount': amount,
                        'price': signal['price_at_signal'],
                        'consensus': signal['has_consensus'],
                        'quality_score': signal['quality_score']
                    })
                    
                    logger.info("trade_executed", 
                              symbol=signal['symbol'],
                              strategy=signal['strategy_name'],
                              signal_id=signal['signal_id'],
                              amount=amount,
                              value=position_value,
                              consensus=signal['has_consensus'])
                else:
                    execution_results.append({
                        'signal_id': signal['signal_id'],
                        'symbol': signal['symbol'],
                        'strategy_id': strategy_id,
                        'status': 'failed',
                        'error': response.text
                    })
                    logger.error("trade_failed",
                               symbol=signal['symbol'],
                               strategy=signal['strategy_name'],
                               error=response.text)
            
            except Exception as e:
                execution_results.append({
                    'signal_id': signal['signal_id'],
                    'symbol': signal['symbol'],
                    'strategy_id': strategy_id,
                    'status': 'error',
                    'error': str(e)
                })
                logger.error("trade_error", 
                           symbol=signal['symbol'],
                           strategy=signal['strategy_name'],
                           error=str(e))
        
        logger.info("task_completed", 
                   task="execute_paper_trades_all_strategies",
                   signals_evaluated=len(signals),
                   consensus_signals=len(consensus_signals),
                   trades_executed=trades_executed,
                   strategies_traded=len(strategies_traded))
        
        return {
            'status': 'success',
            'signals_evaluated': len(signals),
            'consensus_signals': len(consensus_signals),
            'trades_executed': trades_executed,
            'strategies_traded': list(strategies_traded),
            'execution_results': execution_results
        }
    
    except Exception as e:
        logger.error("task_error", task="execute_paper_trades_all_strategies", error=str(e))
        return {'status': 'error', 'message': str(e)}


# Helper: Conduct multi-strategy vote for exceptional signals
def conduct_exceptional_signal_vote(symbol, exceptional_signal):
    """
    When an exceptional signal (100+) appears, conduct an immediate vote across all strategies.
    
    Voting Rules:
    1. Fetch ALL active signals for this symbol from all strategies
    2. Count BUY vs SELL votes (each strategy gets one vote)
    3. Check win rate/confidence of voting strategies
    4. Require supermajority (70%+ agreement) for exceptional trade execution
    5. Log detailed voting breakdown
    
    Returns:
        dict: {
            'approved': bool,
            'vote_count': int,
            'buy_votes': int,
            'sell_votes': int,
            'abstain_votes': int,
            'confidence': float,
            'voting_strategies': list,
            'reason': str
        }
    """
    try:
        logger.warning("EXCEPTIONAL_SIGNAL_VOTE_INITIATED",
                     symbol=symbol,
                     weighted_score=exceptional_signal['weighted_score'],
                     message=f"🚨 INITIATING EMERGENCY VOTE for {symbol}")
        
        # Fetch ALL active signals for this symbol (not just ensemble)
        response = requests.get(
            f"http://{settings.service_host}:{settings.port_signal_api}/signals/active",
            params={'symbol': symbol},
            timeout=10
        )
        
        if response.status_code != 200:
            logger.error("vote_failed_fetch_signals", symbol=symbol, error=response.text)
            return {
                'approved': False,
                'reason': 'failed_to_fetch_signals',
                'vote_count': 0,
                'buy_votes': 0,
                'sell_votes': 0,
                'abstain_votes': 0
            }
        
        all_signals = response.json()
        
        if not all_signals:
            logger.warning("vote_no_signals", symbol=symbol)
            return {
                'approved': False,
                'reason': 'no_other_signals_to_vote',
                'vote_count': 0,
                'buy_votes': 0,
                'sell_votes': 0,
                'abstain_votes': 0
            }
        
        # Count votes by strategy
        strategy_votes = {}  # strategy_id -> signal_type
        voting_strategies = []
        
        for signal in all_signals:
            strategy_id = signal['strategy_id']
            strategy_name = signal.get('strategy_name', f'Strategy {strategy_id}')
            signal_type = signal['signal_type'].upper()
            quality = signal.get('base_quality', signal.get('quality_score', 0))
            
            # Each strategy gets ONE vote (keep highest quality signal if multiple)
            if strategy_id not in strategy_votes or quality > strategy_votes[strategy_id]['quality']:
                strategy_votes[strategy_id] = {
                    'vote': signal_type,
                    'quality': quality,
                    'strategy_name': strategy_name,
                    'weighted_score': signal.get('weighted_score', quality)
                }
        
        # Tally votes
        buy_votes = sum(1 for v in strategy_votes.values() if v['vote'] == 'BUY')
        sell_votes = sum(1 for v in strategy_votes.values() if v['vote'] == 'SELL')
        total_votes = len(strategy_votes)
        
        # Determine outcome
        supermajority_threshold = 0.70  # 70% agreement required
        
        buy_pct = buy_votes / total_votes if total_votes > 0 else 0
        sell_pct = sell_votes / total_votes if total_votes > 0 else 0
        
        approved = False
        winning_direction = None
        reason = "insufficient_consensus"
        
        if buy_pct >= supermajority_threshold:
            approved = True
            winning_direction = 'BUY'
            reason = f"supermajority_buy_{buy_votes}/{total_votes}"
        elif sell_pct >= supermajority_threshold:
            approved = True
            winning_direction = 'SELL'
            reason = f"supermajority_sell_{sell_votes}/{total_votes}"
        else:
            reason = f"no_supermajority_buy_{buy_votes}_sell_{sell_votes}_of_{total_votes}"
        
        # Verify the exceptional signal matches winning direction
        if approved and exceptional_signal['signal_type'].upper() != winning_direction:
            logger.warning("vote_direction_mismatch",
                         symbol=symbol,
                         exceptional_signal_direction=exceptional_signal['signal_type'],
                         vote_direction=winning_direction)
            approved = False
            reason = "exceptional_signal_contradicts_vote"
        
        # Log voting breakdown
        voting_details = []
        for strategy_id, vote_data in strategy_votes.items():
            voting_details.append({
                'strategy_id': strategy_id,
                'strategy_name': vote_data['strategy_name'],
                'vote': vote_data['vote'],
                'quality': vote_data['quality'],
                'weighted_score': vote_data['weighted_score']
            })
        
        logger.warning("VOTE_COMPLETED",
                     symbol=symbol,
                     approved=approved,
                     buy_votes=buy_votes,
                     sell_votes=sell_votes,
                     total_votes=total_votes,
                     buy_pct=f"{buy_pct*100:.1f}%",
                     sell_pct=f"{sell_pct*100:.1f}%",
                     winning_direction=winning_direction,
                     reason=reason,
                     voting_breakdown=voting_details)
        
        # Store vote result in database
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO signal_votes 
                    (symbol, signal_id, vote_result, buy_votes, sell_votes, 
                     total_votes, confidence_pct, voting_strategies, reason, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                """, (
                    symbol,
                    exceptional_signal['signal_id'],
                    'approved' if approved else 'rejected',
                    buy_votes,
                    sell_votes,
                    total_votes,
                    max(buy_pct, sell_pct) * 100,
                    json.dumps(voting_details),
                    reason
                ))
                conn.commit()
        
        return {
            'approved': approved,
            'vote_count': total_votes,
            'buy_votes': buy_votes,
            'sell_votes': sell_votes,
            'abstain_votes': 0,
            'confidence': max(buy_pct, sell_pct) * 100,
            'winning_direction': winning_direction,
            'voting_strategies': voting_details,
            'reason': reason
        }
        
    except Exception as e:
        logger.error("vote_error", symbol=symbol, error=str(e))
        return {
            'approved': False,
            'reason': f'vote_error: {str(e)}',
            'vote_count': 0,
            'buy_votes': 0,
            'sell_votes': 0,
            'abstain_votes': 0
        }


# Task: Monitor for exceptional signals and trigger immediate votes
@celery_app.task(name='monitor_exceptional_signals')
def monitor_exceptional_signals():
    """
    Monitor for exceptional signals (100+) and trigger immediate voting/execution.
    This task interrupts the normal 5-minute consensus cycle to act on rare opportunities.
    
    Runs every 60 seconds to catch exceptional signals quickly.
    Uses CONSENSUS endpoint with stricter thresholds for exceptional cases.
    """
    try:
        logger.info("task_started", task="monitor_exceptional_signals")
        
        # Fetch exceptional consensus signals (require 70% supermajority for expedited)
        response = requests.get(
            f"http://{settings.service_host}:{settings.port_signal_api}/signals/consensus",
            params={
                'min_strategies': 2,  # Need at least 2 strategies
                'supermajority_pct': 70.0,  # Higher threshold for expedited: 70%
                'include_ai_vote': True,
                'include_sentiment': True,
                'limit': 3  # Only top 3 exceptional signals
            },
            timeout=30  # Longer timeout for AI/sentiment calls
        )
        
        if response.status_code != 200:
            logger.debug("no_exceptional_consensus", status=response.status_code)
            return {'status': 'success', 'exceptional_signals': 0}
        
        data = response.json()
        exceptional_signals = data.get('consensus_signals', [])
        
        # Filter to only very high consensus (80%+) for expedited execution
        exceptional_signals = [
            s for s in exceptional_signals 
            if s['consensus_pct'] >= 80.0 and s['best_quality'] >= 85
        ]
        
        if not exceptional_signals:
            logger.debug("no_high_consensus_signals")
            return {'status': 'success', 'exceptional_signals': 0}
        
        logger.warning("EXCEPTIONAL_SIGNALS_DETECTED",
                     count=len(exceptional_signals),
                     symbols=[s['symbol'] for s in exceptional_signals],
                     consensus=[f"{s['consensus_pct']:.1f}%" for s in exceptional_signals])
        
        trades_executed = 0
        trades_failed = 0
        
        for signal in exceptional_signals:
            try:
                logger.warning("EXPEDITED_CONSENSUS_TRADE",
                             symbol=signal['symbol'],
                             consensus_pct=signal['consensus_pct'],
                             quality=signal['best_quality'],
                             strategy_count=signal['strategy_count'])
                
                # Execute immediately via Portfolio API
                portfolio_response = requests.post(
                    f"http://{settings.service_host}:{settings.port_portfolio_api}/positions/open",
                    json={
                        'symbol': signal['symbol'],
                        'side': signal['signal_type'],
                        'mode': 'paper',
                        'position_type': 'ensemble',
                        'signal_ids': signal['signal_ids'],
                        'entry_reason': f"expedited_consensus_{signal['consensus_pct']:.1f}pct_quality_{signal['best_quality']}"
                    },
                    timeout=10
                )
                
                if portfolio_response.status_code == 200:
                    result = portfolio_response.json()
                    position_id = result.get('position', {}).get('id')
                    trades_executed += 1
                    
                    # Record expedited consensus decision
                    try:
                        record_response = requests.post(
                            f"http://{settings.service_host}:{settings.port_signal_api}/consensus/record",
                            json={
                                **signal,
                                'approved': True,
                                'executed': True,
                                'position_id': position_id
                            },
                            timeout=5
                        )
                        if record_response.status_code == 200:
                            decision_id = record_response.json().get('decision_id')
                            logger.info("expedited_decision_recorded", decision_id=decision_id, position_id=position_id)
                    except Exception as e:
                        logger.warning("decision_record_failed", error=str(e))
                    
                    logger.warning("EXPEDITED_TRADE_EXECUTED",
                                 symbol=signal['symbol'],
                                 side=signal['signal_type'],
                                 consensus_pct=signal['consensus_pct'],
                                 position_id=position_id)
                else:
                    trades_failed += 1
                    
                    # Record failed expedited decision
                    try:
                        record_response = requests.post(
                            f"http://{settings.service_host}:{settings.port_signal_api}/consensus/record",
                            json={
                                **signal,
                                'approved': True,
                                'executed': False,
                                'position_id': None
                            },
                            timeout=5
                        )
                    except Exception as e:
                        logger.warning("decision_record_failed", error=str(e))
                    
                    logger.error("expedited_trade_failed",
                               symbol=signal['symbol'],
                               error=portfolio_response.text)
                    
            except Exception as e:
                trades_failed += 1
                logger.error("expedited_execution_error",
                           symbol=signal['symbol'],
                           error=str(e))
        
        return {
            'status': 'success',
            'exceptional_signals': len(exceptional_signals),
            'trades_executed': trades_executed,
            'trades_failed': trades_failed
        }
        
    except Exception as e:
        logger.error("task_error", task="monitor_exceptional_signals", error=str(e))
        return {'status': 'error', 'message': str(e)}


# Task: Execute ensemble trade for specific symbol (immediate execution)
@celery_app.task(name='execute_ensemble_trades_for_symbol')
def execute_ensemble_trades_for_symbol(symbol, exceptional_signal):
    """
    Execute ensemble trade for a specific symbol immediately (bypasses normal cycle).
    Used for exceptional signals that have passed voting.
    """
    try:
        logger.warning("IMMEDIATE_EXECUTION_STARTED",
                     symbol=symbol,
                     weighted_score=exceptional_signal['weighted_score'])
        
        # Check trading policies and portfolio state (same checks as normal ensemble task)
        from datetime import date
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM trading_policies WHERE mode = 'paper'")
                policies = cur.fetchone()
                
                if not policies or policies['emergency_stop']:
                    return {'status': 'stopped', 'reason': 'emergency_stop'}
                
                # Get portfolio state
                cur.execute("""
                    SELECT 
                        total_capital,
                        available_capital,
                        deployed_capital
                    FROM portfolio_snapshots
                    WHERE mode = 'paper'
                    ORDER BY snapshot_time DESC
                    LIMIT 1
                """)
                portfolio = cur.fetchone()
                
                if not portfolio:
                    return {'status': 'error', 'reason': 'no_portfolio_snapshot'}
                
                total_capital = float(portfolio['total_capital'])
                available_capital = float(portfolio['available_capital'])
                
                if available_capital < 100:
                    return {'status': 'error', 'reason': 'insufficient_capital'}
                
                # Check if we already have a position in this symbol
                cur.execute("""
                    SELECT COUNT(*) as count
                    FROM positions
                    WHERE symbol = %s AND status = 'open' AND mode = 'paper' AND position_type = 'ensemble'
                """, (symbol,))
                existing = cur.fetchone()
                
                if existing['count'] > 0:
                    logger.warning("symbol_already_has_position", symbol=symbol)
                    return {'status': 'skipped', 'reason': 'symbol_already_has_position'}
                
                # Calculate EXCEPTIONAL allocation (50%+ for 110+ scores)
                weighted_score = exceptional_signal['weighted_score']
                max_per_position = float(policies['max_position_size'])
                
                if weighted_score >= 110:
                    base_allocation_pct = 0.50  # 50%
                elif weighted_score >= 100:
                    base_allocation_pct = 0.40  # 40%
                else:
                    base_allocation_pct = 0.30  # 30%
                
                # Apply consensus boost
                if exceptional_signal.get('consensus_count', 1) >= 3:
                    base_allocation_pct *= 1.2
                
                # Calculate position value
                position_value = total_capital * base_allocation_pct
                position_value = min(position_value, max_per_position, available_capital - 100)
                
                logger.warning("EXCEPTIONAL_ALLOCATION",
                             symbol=symbol,
                             weighted_score=weighted_score,
                             allocation_pct=base_allocation_pct*100,
                             position_value=position_value,
                             pct_of_capital=position_value/total_capital*100)
                
                # Calculate amount
                amount = position_value / float(exceptional_signal['price_at_signal'])
                
                # Execute trade
                projected_return = float(exceptional_signal.get('projected_return_pct', 5.0))
                signal_type = exceptional_signal['signal_type'].upper()
                trade_side = signal_type.lower() if signal_type in ['BUY', 'SELL'] else 'buy'
                
                trade_payload = {
                    'symbol': symbol,
                    'side': trade_side,
                    'amount': float(amount),
                    'mode': 'paper',
                    'signal_id': int(exceptional_signal['signal_id']),
                    'strategy_id': int(exceptional_signal['strategy_id']),
                    'stop_loss_pct': 2.0,
                    'take_profit_pct': max(projected_return, 5.0),
                    'position_type': 'ensemble'
                }
                
                response = requests.post(
                    f"http://{settings.service_host}:{settings.port_trading_api}/execute",
                    json=trade_payload,
                    timeout=30
                )
                
                if response.status_code == 200:
                    result = response.json()
                    logger.warning("EXCEPTIONAL_TRADE_EXECUTED",
                                 symbol=symbol,
                                 position_id=result.get('position_id'),
                                 value=position_value,
                                 weighted_score=weighted_score,
                                 message=f"🚨 EXCEPTIONAL TRADE: ${position_value:.2f} in {symbol}")
                    return {
                        'status': 'success',
                        'trade_executed': True,
                        'symbol': symbol,
                        'position_value': position_value,
                        'position_id': result.get('position_id')
                    }
                else:
                    logger.error("trade_execution_failed",
                               symbol=symbol,
                               status_code=response.status_code,
                               error=response.text)
                    return {
                        'status': 'error',
                        'reason': 'trade_execution_failed',
                        'error': response.text
                    }
    
    except Exception as e:
        logger.error("immediate_execution_error", symbol=symbol, error=str(e))
        return {'status': 'error', 'message': str(e)}


# Task: Ensemble Portfolio Manager
@celery_app.task(name='execute_ensemble_trades')
def execute_ensemble_trades():
    """Execute ensemble trades based on weighted performance-scored signals
    
    This is the REAL trading portfolio that creates position_type='ensemble' positions.
    Strategy positions (position_type='strategy') are for testing/learning only.
    
    Ensemble logic:
    - Fetches weighted signals from Signal API (performance-adjusted scores)
    - Requires consensus (2+ strategies) OR very high confidence (weighted_score >= 85)
   - Allocates capital based on signal strength and timeframe
    - Creates ensemble positions that count toward portfolio limits
    """
    try:
        logger.info("task_started", task="execute_ensemble_trades")
        
        # Fetch performance-weighted ensemble signals
        try:
            response = requests.get(
                f"http://{settings.service_host}:{settings.port_signal_api}/signals/ensemble",
                params={
                    'min_weighted_score': 55,  # Lowered from 70: Enable trading when blacklist blocks main signals
                    'period_days': 14,  # 14-day performance window
                    'limit': 50  # Increased from 20: Ensure we get BUY signals (SELL signals often score higher)
                },
                timeout=30
            )
            
            if response.status_code != 200:
                logger.error("ensemble_signals_failed", error=response.text)
                return {'status': 'error', 'reason': 'failed_to_fetch_signals'}
            
            data = response.json()
            signals = data.get('ensemble_signals', [])
            
            if not signals:
                logger.info("no_ensemble_signals")
                return {'status': 'success', 'trades_executed': 0, 'reason': 'no_signals'}
            
            logger.info("ensemble_signals_found", count=len(signals))
            
        except Exception as e:
            logger.error("ensemble_api_error", error=str(e))
            return {'status': 'error', 'reason': f'api_error: {str(e)}'}
        
        # Check trading policies
        from datetime import date
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM trading_policies WHERE mode = 'paper'")
                policies = cur.fetchone()
                
                if not policies:
                    logger.error("no_policies_found")
                    return {'status': 'error', 'reason': 'no_policies'}
                
                if policies['emergency_stop']:
                    logger.warning("emergency_stop_active")
                    return {'status': 'stopped', 'reason': 'emergency_stop'}
                
                # Check today's P&L and trade count
                cur.execute("""
                    SELECT 
                        COALESCE(SUM(realized_pnl), 0) as today_pnl,
                        COUNT(*) as trades_today
                    FROM positions
                    WHERE DATE(entry_time) = %s AND mode = 'paper' AND position_type = 'ensemble'
                """, (date.today(),))
                today_stats = cur.fetchone()
                
                today_pnl = float(today_stats['today_pnl']) if today_stats else 0.0
                trades_today = today_stats['trades_today'] if today_stats else 0
                
                # Check limits
                if today_pnl <= -float(policies['daily_loss_limit']):
                    logger.warning("daily_loss_limit_reached", pnl=today_pnl)
                    cur.execute("""
                        UPDATE trading_policies
                        SET emergency_stop = true,
                            emergency_stop_reason = 'Ensemble daily loss limit',
                            emergency_stop_time = NOW()
                        WHERE mode = 'paper'
                    """)
                    return {'status': 'stopped', 'reason': 'daily_loss_limit'}
                
                if trades_today >= policies['daily_trade_limit']:
                    logger.warning("daily_trade_limit_reached", trades=trades_today)
                    return {'status': 'limit_reached', 'reason': 'daily_trade_limit'}
                
                # Count open ensemble positions  
                cur.execute("""
                    SELECT COUNT(*) as count, COALESCE(SUM(capital_allocated), 0) as deployed
                    FROM positions
                    WHERE status = 'open' AND mode = 'paper' AND position_type = 'ensemble'
                """)
                ensemble_status = cur.fetchone()
                open_ensemble_positions = ensemble_status['count']
                deployed_capital = float(ensemble_status['deployed'])
                
                # Check ensemble position limits
                if open_ensemble_positions >= policies['max_open_positions']:
                    logger.warning("max_positions_reached", open=open_ensemble_positions)
                    return {'status': 'limit_reached', 'reason': 'max_positions'}
                
                # Get positions per symbol (ensemble only)
                cur.execute("""
                    SELECT symbol, COUNT(*) as count
                    FROM positions
                    WHERE status = 'open' AND mode = 'paper' AND position_type = 'ensemble'
                    GROUP BY symbol
                """)
                positions_per_symbol = {row['symbol']: row['count'] for row in cur.fetchall()}
        
        # Calculate available capital using actual configured starting capital
        total_capital = float(settings.paper_starting_capital)
        available_capital = total_capital - deployed_capital
        
        logger.info("ensemble_capital_status",
                   total=total_capital,
                   deployed=deployed_capital,
                   available=available_capital,
                   open_positions=open_ensemble_positions)
        
        # Phase 4: Get symbol blacklist (symbols with < -$50.00 P&L in last 30 days)
        # Threshold raised from -$3 to -$50 — tiny losses should not block symbols
        blacklisted_symbols = set()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT symbol
                    FROM positions
                    WHERE mode = 'paper'
                      AND status = 'closed'
                      AND signal_source = 'ensemble'
                      AND entry_time >= NOW() - INTERVAL '30 days'
                    GROUP BY symbol
                    HAVING SUM(realized_pnl) < -50.0
                """)
                blacklisted_symbols = {row['symbol'] for row in cur.fetchall()}
                if blacklisted_symbols:
                    logger.info("phase4_symbols_blacklisted", symbols=list(blacklisted_symbols))
        
        # Filter signals based on ensemble rules
        actionable_signals = []
        for signal in signals:
            symbol = signal['symbol']
            
            # CRITICAL Filter: Only act on BUY signals for opening positions
            # SELL signals should only close existing positions (handled separately)
            signal_type = signal.get('signal_type', 'BUY').upper()
            if signal_type != 'BUY':
                logger.info("signal_rejected_not_buy", 
                           symbol=symbol, 
                           signal_type=signal_type,
                           reason="Ensemble only opens positions on BUY signals. SELL handled by exit strategy.",
                           filter="signal_direction")
                continue
            
            # Phase 4 Filter 0: Symbol blacklist (poor historical performance)
            if symbol in blacklisted_symbols:
                logger.info("signal_rejected_blacklist", 
                           symbol=symbol, 
                           reason="Symbol has <-$50 P&L in last 30 days",
                           filter="phase4")
                continue
            
            # Phase 4 Filter 1: Get latest candle for entry quality checks
            try:
                response = requests.get(
                    f"http://{settings.service_host}:{settings.port_ohlcv_api}/ohlcv/candles/{symbol}",
                    params={'limit': 1, 'interval': '1m'},
                    timeout=5
                )
                if response.status_code == 200:
                    candles = response.json()
                    if candles:
                        latest_candle = candles[0]
                        
                        # Phase 4 Filter 2: RSI Range (avoid extreme overbought/oversold)
                        rsi = latest_candle.get('rsi_14')
                        if rsi is not None:
                            if rsi < 30 or rsi > 70:
                                logger.info("signal_rejected_rsi", 
                                           symbol=symbol, 
                                           rsi=round(rsi, 2),
                                           reason="RSI outside 30-70 range (relaxed from 35-65)",
                                           filter="phase4")
                                continue
                        
                        # Phase 4 Filter 3: Volume Confirmation (require >1.2x recent average)
                        volume = latest_candle.get('volume')
                        volume_sma_20 = latest_candle.get('volume_sma_20')
                        if volume and volume_sma_20 and volume_sma_20 > 0:
                            volume_ratio = volume / volume_sma_20
                            if volume_ratio < 1.2:
                                logger.info("signal_rejected_volume",
                                           symbol=symbol,
                                           volume_ratio=round(volume_ratio, 2),
                                           reason="Volume below 1.2x average (relaxed from 1.5x)",
                                           filter="phase4")
                                continue
                        
                        # Phase 4 Filter 4: Volatility Guard (skip extreme ATR)
                        atr = latest_candle.get('atr_14')
                        # Calculate ATR SMA from recent candles
                        response_hist = requests.get(
                            f"http://{settings.service_host}:{settings.port_ohlcv_api}/ohlcv/candles/{symbol}",
                            params={'limit': 20, 'interval': '1m'},
                            timeout=5
                        )
                        if response_hist.status_code == 200:
                            hist_candles = response_hist.json()
                            if len(hist_candles) >= 20 and atr:
                                atr_values = [c.get('atr_14') for c in hist_candles if c.get('atr_14')]
                                if len(atr_values) >= 15:
                                    atr_sma = sum(atr_values) / len(atr_values)
                                    atr_ratio = atr / atr_sma if atr_sma > 0 else 1.0
                                    if atr_ratio > 2.0:
                                        logger.info("signal_rejected_volatility",
                                                   symbol=symbol,
                                                   atr_ratio=round(atr_ratio, 2),
                                                   reason="ATR > 2x average (extreme volatility)",
                                                   filter="phase4")
                                        continue
            except Exception as e:
                logger.warning("phase4_filter_check_failed", symbol=symbol, error=str(e))
                # Don't block trade if filter check fails - fail open for now
            
            # Rule 1: Must have consensus (2+ strategies) OR moderate confidence
            # Threshold lowered to 60 to match bootstrap eligibility (Rule 3)
            # After-action found 40 missed opportunities with consensus=1, score=60-70
            has_consensus = signal.get('has_consensus', False) or signal.get('consensus_count', 1) >= 2
            is_high_confidence = signal['weighted_score'] >= 60
            
            if not (has_consensus or is_high_confidence):
                logger.info("signal_rejected_low_confidence",
                           symbol=signal['symbol'],
                           signal_type=signal.get('signal_type'),
                           weighted_score=signal['weighted_score'],
                           consensus_count=signal.get('consensus_count', 1),
                           has_consensus=signal.get('has_consensus', False))
                continue
            
            # Rule 2: Only 1 ensemble position per symbol
            if positions_per_symbol.get(signal['symbol'], 0) >= 1:
                logger.debug("signal_rejected_symbol_limit", symbol=signal['symbol'])
                continue
            
            # Rule 3: Bootstrap mode - allow signals without performance data if:
            # - Moderate confidence (60+) OR basic consensus (2+ strategies)
            # Lowered from 85/3 because signals are scoring 60-70 with consensus 2
            # and the system has no trade history yet to establish win_rate.
            if signal.get('win_rate') is None:
                is_bootstrap_eligible = (
                    signal['weighted_score'] >= 60 or  # Moderate confidence
                    signal.get('consensus_count', 1) >= 2  # Basic consensus
                )
                if not is_bootstrap_eligible:
                    logger.info("signal_rejected_bootstrap_ineligible",
                               symbol=signal['symbol'],
                               signal_type=signal.get('signal_type'),
                               score=signal['weighted_score'],
                               consensus=signal.get('consensus_count', 1))
                    continue
                # Mark as bootstrap trade for conservative sizing
                signal['is_bootstrap'] = True
            else:
                signal['is_bootstrap'] = False
            
            actionable_signals.append(signal)
        
        if not actionable_signals:
            logger.info("no_actionable_ensemble_signals",
                       total_signals=len(signals),
                       filtered_out=len(signals))
            return {'status': 'success', 'trades_executed': 0, 'reason': 'no_actionable_signals'}
        
        logger.info("actionable_ensemble_signals_found", count=len(actionable_signals))
        
        # Sort by weighted_score (performance-adjusted)
        actionable_signals.sort(key=lambda s: s['weighted_score'], reverse=True)
        
        # Deduplicate by symbol - keep only highest scoring signal per symbol
        seen_symbols = set()
        deduplicated_signals = []
        for signal in actionable_signals:
            if signal['symbol'] not in seen_symbols:
                seen_symbols.add(signal['symbol'])
                deduplicated_signals.append(signal)
            else:
                logger.debug("signal_deduplicated", 
                           symbol=signal['symbol'],
                           score=signal['weighted_score'],
                           reason="already_have_higher_scored_signal")
        
        actionable_signals = deduplicated_signals
        logger.info("signals_after_deduplication", count=len(actionable_signals))
        
        # PHASE 3: Initialize Portfolio Risk Manager
        # NOTE: mode='paper' disables blacklist to allow testing all symbols
        from shared.risk_manager import PortfolioRiskManager
        risk_manager = PortfolioRiskManager(total_capital=total_capital, mode='paper')
        
        # Execute ensemble trades
        trades_executed = 0
        execution_results = []
        
        for signal in actionable_signals:
            if available_capital < 100:  # Keep $100 minimum reserve
                logger.info("insufficient_capital_remaining", available=available_capital)
                break
            
            # Calculate position size based on signal strength and timeframe
            max_per_position = float(policies['max_position_size'])
            
            # TIERED ALLOCATION based on signal strength
            weighted_score = signal['weighted_score']
            
            # BOOTSTRAP MODE: Use smaller position sizes for trades without performance data
            if signal.get('is_bootstrap', False):
                base_allocation_pct = 0.05  # 5% for bootstrap trades (conservative)
                logger.info("bootstrap_trade_conservative_sizing",
                          symbol=signal['symbol'],
                          allocation_pct=base_allocation_pct)
            # EXTRAORDINARY SIGNALS (110+) - Leverage opportunity
            elif weighted_score >= 110:
                base_allocation_pct = 0.50  # 50% - go big on exceptional conviction
                logger.warning("EXTRAORDINARY_SIGNAL",  # Warning level for visibility
                             symbol=signal['symbol'],
                             weighted_score=weighted_score,
                             allocation_pct=base_allocation_pct,
                             message="🚨 EXCEPTIONAL SIGNAL - 50% ALLOCATION")
            # EXCEPTIONAL SIGNALS (100-109) - Very rare, high confidence
            elif weighted_score >= 100:
                base_allocation_pct = 0.40  # 40%
                logger.warning("EXCEPTIONAL_SIGNAL",
                             symbol=signal['symbol'],
                             weighted_score=weighted_score,
                             allocation_pct=base_allocation_pct,
                             message="⚡ Exceptional signal - 40% allocation")
            # VERY HIGH CONFIDENCE (90-99) - Strong signals
            elif weighted_score >= 90:
                base_allocation_pct = 0.30  # 30%
                logger.info("very_high_confidence_signal",
                          symbol=signal['symbol'],
                          weighted_score=weighted_score,
                          allocation_pct=base_allocation_pct)
            # HIGH CONFIDENCE (80-89) - Good signals
            elif weighted_score >= 80:
                base_allocation_pct = 0.20  # 20%
                logger.info("high_confidence_signal",
                          symbol=signal['symbol'],
                          weighted_score=weighted_score,
                          allocation_pct=base_allocation_pct)
            # QUALIFIED SIGNALS (70-79) - Normal allocation
            else:
                base_allocation_pct = 0.10  # 10% base
            
            # Boost for high consensus (3+ strategies)
            if signal.get('consensus_count', 1) >= 3:
                base_allocation_pct *= 1.2
                logger.info("consensus_boost", 
                          symbol=signal['symbol'],
                          consensus_count=signal.get('consensus_count'),
                          boosted_pct=base_allocation_pct)
            
            # Boost for short timeframe signals (< 2 hours) - can capitalize quickly
            timeframe_minutes = signal.get('projected_timeframe_minutes', 240)
            if timeframe_minutes < 120:
                base_allocation_pct *= 1.1
                logger.info("timeframe_boost",
                          symbol=signal['symbol'],
                          timeframe_minutes=timeframe_minutes,
                          boosted_pct=base_allocation_pct)
            
            # Calculate actual position value
            position_value = total_capital * base_allocation_pct
            position_value = min(position_value, max_per_position, available_capital - 100)
            
            # PHASE 3: Portfolio Risk Management - Comprehensive risk checks
            risk_evaluation = risk_manager.evaluate_new_position(signal['symbol'], position_value)
            
            # Log evaluation to database for real-time visibility
            try:
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO signal_evaluations 
                            (symbol, signal_type, weighted_score, proposed_value, 
                             approved, rejection_reason, risk_checks, mode)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """, (
                            signal['symbol'],
                            signal.get('signal_type', 'BUY'),
                            signal['weighted_score'],
                            position_value,
                            risk_evaluation['approved'],
                            risk_evaluation['reason'],
                            json.dumps(risk_evaluation.get('checks', {})),
                            'paper'
                        ))
                        conn.commit()
            except Exception as e:
                logger.error("failed_to_log_evaluation", error=str(e))
            
            if not risk_evaluation['approved']:
                logger.warning("position_rejected_risk_check",
                             symbol=signal['symbol'],
                             proposed_value=position_value,
                             reason=risk_evaluation['reason'],
                             checks=risk_evaluation['checks'])
                
                execution_results.append({
                    'signal_id': signal['signal_id'],
                    'symbol': signal['symbol'],
                    'status': 'rejected_risk',
                    'reason': risk_evaluation['reason']
                })
                continue
            
            # Apply risk-adjusted position size
            if risk_evaluation['final_value'] != position_value:
                original_value = position_value
                position_value = risk_evaluation['final_value']
                
                logger.info("position_size_adjusted_by_risk",
                          symbol=signal['symbol'],
                          original_value=original_value,
                          adjusted_value=position_value,
                          adjustment_pct=(position_value/original_value)*100,
                          reason=risk_evaluation['reason'])
            
            # Enhanced logging for large positions
            if position_value >= total_capital * 0.30:  # 30%+ positions
                logger.warning("LARGE_POSITION_ALLOCATED",
                             symbol=signal['symbol'],
                             position_value=position_value,
                             pct_of_capital=position_value/total_capital*100,
                             weighted_score=signal['weighted_score'],
                             message=f"🎯 Allocating ${position_value:.2f} ({position_value/total_capital*100:.1f}%) to {signal['symbol']}")
            
            if position_value < 50:  # Minimum $50 per trade
                logger.warning("position_too_small", calculated=position_value)
                continue
            
            # Double-check symbol limit before execution (safety check)
            if positions_per_symbol.get(signal['symbol'], 0) >= 1:
                logger.warning("symbol_limit_reached_during_execution", symbol=signal['symbol'])
                continue
            
            #CRITICAL: Acquire database lock to prevent race conditions with concurrent workers
            # Use PostgreSQL advisory lock based on symbol hash
            symbol_lock_id = hash(signal['symbol']) % 2147483647  # PostgreSQL bigint max
            
            try:
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        # Try to acquire advisory lock (non-blocking)
                        cur.execute("SELECT pg_try_advisory_lock(%s)", (symbol_lock_id,))
                        lock_acquired = cur.fetchone()['pg_try_advisory_lock']
                        
                        if not lock_acquired:
                            logger.warning("symbol_locked_by_concurrent_task",
                                         symbol=signal['symbol'],
                                         reason="Another worker is already processing this symbol")
                            execution_results.append({
                                'signal_id': signal['signal_id'],
                                'symbol': signal['symbol'],
                                'status': 'skipped_locked',
                                'reason': 'concurrent_execution_prevented'
                            })
                            continue
                        
                        # Double-check in database (race condition protection)
                        cur.execute("""
                            SELECT COUNT(*) as count
                            FROM positions
                            WHERE status = 'open' 
                            AND mode = 'paper' 
                            AND position_type = 'ensemble'
                            AND symbol = %s
                        """, (signal['symbol'],))
                        db_count = cur.fetchone()['count']
                        
                        if db_count >= 1:
                            # Release lock before continuing
                            cur.execute("SELECT pg_advisory_unlock(%s)", (symbol_lock_id,))
                            logger.warning("symbol_limit_reached_db_check",
                                         symbol=signal['symbol'],
                                         db_count=db_count,
                                         reason="Position opened by concurrent worker")
                            execution_results.append({
                                'signal_id': signal['signal_id'],
                                'symbol': signal['symbol'],
                                'status': 'rejected_duplicate',
                                'reason': f'already_have_{db_count}_open_positions'
                            })
                            continue
                
                # Lock acquired and verified - proceed with trade
                # Note: Lock will be released after trade execution below
                
            except Exception as e:
                logger.error("advisory_lock_error", symbol=signal['symbol'], error=str(e))
                continue
            
            # Calculate amount to buy/sell
            amount = position_value / float(signal['price_at_signal'])
            
            # PHASE 2: Use AI to optimize exit parameters per symbol
            # AI acts as risk manager (not signal voter) - professional approach
            ai_exit_params = None
            try:
                # Get recent volatility via Bollinger Band Width (ATR is not a computed indicator)
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            SELECT indicators, close
                            FROM ohlcv_candles
                            WHERE symbol = %s
                            ORDER BY timestamp DESC
                            LIMIT 1
                        """, (signal['symbol'],))
                        candle = cur.fetchone()

                        recent_volatility = None
                        if candle and candle['indicators'] and candle['close']:
                            _ind = candle['indicators']
                            _bbb = _ind.get('BBB_20_2.0_2.0') if isinstance(_ind, dict) else None
                            if _bbb:
                                # Normalize BBB (band-width %) to approximate ATR/close range
                                recent_volatility = float(_bbb) / 100.0
                
                # Call AI exit optimizer
                ai_request = {
                    'symbol': signal['symbol'],
                    'entry_price': float(signal['price_at_signal']),
                    'signal_quality': signal['weighted_score'],
                    'timeframe_minutes': signal.get('projected_timeframe_minutes', 240),
                    'recent_volatility': recent_volatility,
                    'market_regime': None,  # TODO: Add regime detection
                    'strategy_win_rate': signal.get('win_rate')
                }
                
                ai_response = requests.post(
                    f"http://{settings.service_host}:{settings.port_ai_api}/optimize-exit",
                    json=ai_request,
                    timeout=10
                )
                
                if ai_response.status_code == 200:
                    ai_exit_params = ai_response.json()
                    logger.info("ai_exit_params_applied",
                               symbol=signal['symbol'],
                               stop_loss=ai_exit_params['stop_loss_pct'],
                               take_profit=ai_exit_params['take_profit_pct'],
                               confidence=ai_exit_params.get('confidence', 0.5),
                               reasoning=ai_exit_params.get('reasoning', '')[:50])
            except Exception as e:
                logger.warning("ai_exit_optimizer_failed", symbol=signal['symbol'], error=str(e))
            
            # Use AI parameters if available, otherwise fallback to defaults
            stop_loss_pct = ai_exit_params['stop_loss_pct'] if ai_exit_params else 2.0
            take_profit_pct = ai_exit_params['take_profit_pct'] if ai_exit_params else max(float(signal.get('projected_return_pct', 5.0)), 5.0)
            
            # Execute trade via Trading API
            try:
                # Map signal type to trade side (BUY or SELL)
                signal_type = signal['signal_type'].upper()
                trade_side = signal_type.lower() if signal_type in ['BUY', 'SELL'] else 'buy'
                
                trade_payload = {
                    'symbol': signal['symbol'],
                    'side': trade_side,
                    'amount': float(amount),
                    'mode': 'paper',
                    'signal_id': int(signal['signal_id']),
                    'strategy_id': int(signal['strategy_id']),
                    'stop_loss_pct': stop_loss_pct,  # AI-optimized or default
                    'take_profit_pct': take_profit_pct,  # AI-optimized or default
                    'position_type': 'ensemble'  # Mark as ensemble position
                }
                
                response = requests.post(
                    f"http://{settings.service_host}:{settings.port_trading_api}/execute",
                    json=trade_payload,
                    timeout=30
                )
                
                if response.status_code == 200:
                    trades_executed += 1
                    available_capital -= position_value
                    positions_per_symbol[signal['symbol']] = positions_per_symbol.get(signal['symbol'], 0) + 1
                    
                    execution_results.append({
                        'signal_id': signal['signal_id'],
                        'symbol': signal['symbol'],
                        'side': trade_side,  # Show what side we're trading
                        'status': 'executed',
                        'amount': amount,
                        'value': position_value,
                        'weighted_score': signal['weighted_score'],
                        'win_rate': signal.get('win_rate'),
                        'consensus_count': signal.get('consensus_count', 1),
                        'is_bootstrap': signal.get('is_bootstrap', False)
                    })
                    
                    logger.info("ensemble_trade_executed",
                              symbol=signal['symbol'],
                              side=trade_side,  # Log the trade direction
                              weighted_score=signal['weighted_score'],
                              value=position_value,
                              consensus=signal.get('consensus_count', 1),
                              is_bootstrap=signal.get('is_bootstrap', False))
                else:
                    execution_results.append({
                        'signal_id': signal['signal_id'],
                        'symbol': signal['symbol'],
                        'status': 'failed',
                        'error': response.text
                    })
                    logger.error("ensemble_trade_failed",
                               symbol=signal['symbol'],
                               error=response.text)
                
                # Release advisory lock after trade attempt (success or failure)
                try:
                    with get_connection() as conn:
                        with conn.cursor() as cur:
                            cur.execute("SELECT pg_advisory_unlock(%s)", (symbol_lock_id,))
                except Exception as unlock_error:
                    logger.error("advisory_unlock_error", 
                               symbol=signal['symbol'],
                               error=str(unlock_error))
            
            except Exception as e:
                # Release lock on exception
                try:
                    with get_connection() as conn:
                        with conn.cursor() as cur:
                            cur.execute("SELECT pg_advisory_unlock(%s)", (symbol_lock_id,))
                except:
                    pass  # Ignore unlock errors during exception handling
                
                execution_results.append({
                    'signal_id': signal['signal_id'],
                    'symbol': signal['symbol'],
                    'status': 'error',
                    'error': str(e)
                })
                logger.error("ensemble_trade_error",
                           symbol=signal['symbol'],
                           error=str(e))
        
        logger.info("task_completed",
                   task="execute_ensemble_trades",
                   signals_evaluated=len(signals),
                   actionable_signals=len(actionable_signals),
                   trades_executed=trades_executed)
        
        return {
            'status': 'success',
            'signals_evaluated': len(signals),
            'actionable_signals': len(actionable_signals),
            'trades_executed': trades_executed,
            'execution_results': execution_results
        }
    
    except Exception as e:
        logger.error("task_error", task="execute_ensemble_trades", error=str(e))
        return {'status': 'error', 'message': str(e)}

# Task: Monitor and manage open positions
@celery_app.task(name='manage_open_positions')
def manage_open_positions():
    """Monitor open positions and close them when stop-loss/take-profit conditions met"""
    try:
        logger.info("task_started", task="manage_open_positions")
        
        # Get current prices for all active symbols
        symbol_prices = {}
        symbols = get_active_symbols()
        
        for symbol_obj in symbols:
            symbol = symbol_obj['symbol']
            try:
                # Get latest candle for current price
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            SELECT close as price
                            FROM ohlcv_candles
                            WHERE symbol = %s
                            ORDER BY timestamp DESC
                            LIMIT 1
                        """, (symbol,))
                        
                        result = cur.fetchone()
                        if result:
                            symbol_prices[symbol] = float(result['price'])
            except Exception as e:
                logger.error("price_fetch_error", symbol=symbol, error=str(e))
        
        # Get all open positions
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        id,
                        symbol,
                        quantity,
                        entry_price,
                        stop_loss_price,
                        take_profit_price,
                        mode,
                        entry_time
                    FROM positions
                    WHERE status = 'open'
                """)
                
                positions = cur.fetchall()
        
        if not positions:
            logger.info("no_open_positions")
            return {'status': 'success', 'positions_checked': 0}
        
        logger.info("checking_positions", count=len(positions))
        
        # Check if emergency stop is active for any mode
        emergency_stop_active = {}
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT mode, emergency_stop, emergency_stop_reason
                    FROM trading_policies
                    WHERE emergency_stop = true
                """)
                for row in cur.fetchall():
                    emergency_stop_active[row['mode']] = row['emergency_stop_reason']
                    logger.warning("emergency_stop_detected", 
                                 mode=row['mode'], 
                                 reason=row['emergency_stop_reason'])
        
        positions_closed = 0
        close_results = []
        
        for position in positions:
            symbol = position['symbol']
            current_price = symbol_prices.get(symbol)
            
            if not current_price:
                logger.warning("no_price_data", symbol=symbol, position_id=position['id'])
                continue
            
            # Update current price and P&L in database
            try:
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        # Ensure all values are float to avoid Decimal/float type conflicts
                        entry_price_float = float(position['entry_price'] or 0)
                        quantity_float = float(position['quantity'] or 0)
                        current_price_float = float(current_price)
                        
                        pnl = (current_price_float - entry_price_float) * quantity_float
                        pnl_pct = ((current_price_float - entry_price_float) / entry_price_float) * 100 if entry_price_float else 0
                        
                        cur.execute("""
                            UPDATE positions
                            SET current_price = %s,
                                current_pnl = %s,
                                current_pnl_pct = %s,
                                updated_at = NOW()
                            WHERE id = %s
                        """, (current_price_float, pnl, pnl_pct, position['id']))
                        conn.commit()
            except Exception as e:
                logger.error("position_update_error", position_id=position['id'], error=str(e))
            
            should_close = False
            close_reason = None
            
            # Check if emergency stop is active for this position's mode
            if position['mode'] in emergency_stop_active:
                # Emergency stop active - check if position is losing
                entry_price_float = float(position['entry_price'] or 0)
                pnl_pct = ((current_price_float - entry_price_float) / entry_price_float) * 100 if entry_price_float else 0
                
                if pnl_pct < 0:
                    # Close losing positions immediately during emergency stop
                    should_close = True
                    close_reason = f"emergency_stop_loss_exit (P&L: {pnl_pct:.2f}%, Reason: {emergency_stop_active[position['mode']]})"
                    logger.info("emergency_stop_closing_losing_position",
                              position_id=position['id'],
                              symbol=symbol,
                              pnl_pct=pnl_pct)
                elif pnl_pct > 1.0:
                    # Tighten stop-loss on winning positions to protect gains
                    # Set stop at break-even + 50% of current gain
                    new_stop = entry_price_float + (current_price_float - entry_price_float) * 0.5
                    
                    try:
                        with get_connection() as conn:
                            with conn.cursor() as cur:
                                cur.execute("""
                                    UPDATE positions
                                    SET stop_loss_price = %s
                                    WHERE id = %s AND (stop_loss_price IS NULL OR stop_loss_price < %s)
                                """, (new_stop, position['id'], new_stop))
                                conn.commit()
                                if cur.rowcount > 0:
                                    logger.info("emergency_stop_tightened_stop",
                                              position_id=position['id'],
                                              symbol=symbol,
                                              old_stop=float(position['stop_loss_price']) if position['stop_loss_price'] else None,
                                              new_stop=new_stop,
                                              pnl_pct=pnl_pct)
                    except Exception as e:
                        logger.error("stop_tightening_error", position_id=position['id'], error=str(e))
            
            # ===== STRATEGY-DRIVEN EXIT: Check for SELL signal consensus =====
            # Only considers SELL signals generated AFTER the position was opened.
            # Enforces a 15-minute minimum hold so stale pre-buy signals cannot
            # immediately flip and close a freshly opened position.
            if not should_close:
                try:
                    from datetime import timezone as _tz
                    _now_utc = datetime.now(_tz.utc)
                    _entry_time = position['entry_time']
                    if not _entry_time.tzinfo:
                        _entry_time = _entry_time.replace(tzinfo=_tz.utc)
                    _minutes_held = (_now_utc - _entry_time).total_seconds() / 60

                    if _minutes_held < 15:
                        logger.debug("position_in_min_hold_period",
                                     position_id=position['id'],
                                     symbol=symbol,
                                     minutes_held=round(_minutes_held, 1))
                    else:
                        with get_connection() as conn:
                            with conn.cursor() as cur:
                                # Only check SELL signals created AFTER this position opened
                                cur.execute("""
                                    SELECT signal_type, strategy_id, quality_score, generated_at
                                    FROM signals
                                    WHERE symbol = %s
                                    AND signal_type = 'SELL'
                                    AND acted_on = false
                                    AND expires_at > NOW()
                                    AND generated_at > %s
                                """, (symbol, _entry_time))

                                sell_signals = cur.fetchall()

                                if len(sell_signals) >= 2:
                                    # SELL CONSENSUS: 2+ strategies say exit
                                    avg_quality = sum(s['quality_score'] for s in sell_signals) / len(sell_signals)
                                    entry_price_float = float(position['entry_price'] or 0)
                                    pnl_pct = ((current_price_float - entry_price_float) / entry_price_float) * 100 if entry_price_float else 0

                                    should_close = True
                                    close_reason = f"sell_signal_consensus ({len(sell_signals)} strategies, avg_quality={avg_quality:.0f}, P&L: {pnl_pct:.2f}%)"

                                    logger.info("sell_consensus_detected",
                                              position_id=position['id'],
                                              symbol=symbol,
                                              sell_signal_count=len(sell_signals),
                                              avg_quality=avg_quality,
                                              pnl_pct=pnl_pct,
                                              strategies=[s['strategy_id'] for s in sell_signals])

                                elif len(sell_signals) == 1 and sell_signals[0]['quality_score'] >= 85:
                                    # HIGH CONFIDENCE SELL: Single strategy but very confident
                                    entry_price_float = float(position['entry_price'] or 0)
                                    pnl_pct = ((current_price_float - entry_price_float) / entry_price_float) * 100 if entry_price_float else 0

                                    should_close = True
                                    close_reason = f"high_confidence_sell (quality={sell_signals[0]['quality_score']}, P&L: {pnl_pct:.2f}%)"

                                    logger.info("high_confidence_sell_detected",
                                              position_id=position['id'],
                                              symbol=symbol,
                                              quality=sell_signals[0]['quality_score'],
                                              pnl_pct=pnl_pct,
                                              strategy=sell_signals[0]['strategy_id'])
                except Exception as e:
                    logger.error("sell_signal_check_error", position_id=position['id'], symbol=symbol, error=str(e))
            # ===== END STRATEGY-DRIVEN EXIT ======
            
            # Check if it's a BUY position (quantity > 0)
            if not should_close and position['quantity'] > 0:
                # Ensure all price values are float to avoid Decimal/float type conflicts
                entry_price_float = float(position['entry_price'] or 0)
                stop_loss_float = float(position['stop_loss_price']) if position['stop_loss_price'] else None
                take_profit_float = float(position['take_profit_price']) if position['take_profit_price'] else None
                
                # Calculate current P&L percentage
                pnl_pct = ((current_price_float - entry_price_float) / entry_price_float) * 100 if entry_price_float else 0
                
                # TRAILING STOP: Protect profits on winning positions
                # When position hits +3% profit, move stop to break-even + 1.5%
                if pnl_pct >= 3.0:
                    # Calculate trailing stop: entry + 50% of current profit
                    trailing_stop_price = entry_price_float + (current_price_float - entry_price_float) * 0.5
                    
                    # Only update if trailing stop is higher than current stop
                    if not stop_loss_float or trailing_stop_price > stop_loss_float:
                        try:
                            with get_connection() as conn:
                                with conn.cursor() as cur:
                                    cur.execute("""
                                        UPDATE positions
                                        SET stop_loss_price = %s
                                        WHERE id = %s
                                    """, (trailing_stop_price, position['id']))
                                    conn.commit()
                                    
                                    if cur.rowcount > 0:
                                        logger.info("trailing_stop_updated",
                                                  position_id=position['id'],
                                                  symbol=symbol,
                                                  pnl_pct=pnl_pct,
                                                  old_stop=stop_loss_float,
                                                  new_stop=trailing_stop_price,
                                                  locked_profit_pct=(trailing_stop_price - entry_price_float) / entry_price_float * 100)
                                        # Update local value for this cycle
                                        stop_loss_float = trailing_stop_price
                        except Exception as e:
                            logger.error("trailing_stop_error", position_id=position['id'], error=str(e))
                
                # Check stop loss
                if stop_loss_float and current_price_float <= stop_loss_float:
                    should_close = True
                    close_reason = f"stop_loss_triggered (P&L: {pnl_pct:.2f}%)"
                
                # Check take profit
                elif take_profit_float and current_price_float >= take_profit_float:
                    should_close = True
                    close_reason = f"take_profit_triggered (P&L: {pnl_pct:.2f}%)"
                
                # Check time-based exit (if open > 24 hours)
                elif position['entry_time']:
                    # Use timezone-aware datetime to match database timestamp
                    from datetime import timezone
                    now_utc = datetime.now(timezone.utc)
                    hours_open = (now_utc - position['entry_time']).total_seconds() / 3600
                    if hours_open > 24:
                        should_close = True
                        close_reason = f"time_exit (open {hours_open:.1f}h, P&L: {pnl_pct:.2f}%)"
            
            # Close position if conditions met
            if should_close:
                try:
                    close_payload = {
                        'position_id': position['id'],
                        'mode': position['mode'],
                        'reason': close_reason
                    }
                    
                    response = requests.post(
                        f"http://{settings.service_host}:{settings.port_trading_api}/close",
                        json=close_payload,
                        timeout=30
                    )
                    
                    if response.status_code == 200:
                        positions_closed += 1
                        close_results.append({
                            'position_id': position['id'],
                            'symbol': symbol,
                            'status': 'closed',
                            'reason': close_reason,
                            'entry_price': entry_price_float,
                            'exit_price': current_price_float
                        })
                        logger.info("position_closed",
                                  position_id=position['id'],
                                  symbol=symbol,
                                  reason=close_reason,
                                  entry=position['entry_price'],
                                  exit=current_price)
                    else:
                        close_results.append({
                            'position_id': position['id'],
                            'symbol': symbol,
                            'status': 'failed',
                            'error': response.text
                        })
                        logger.error("close_failed",
                                   position_id=position['id'],
                                   error=response.text)
                
                except Exception as e:
                    close_results.append({
                        'position_id': position['id'],
                        'symbol': symbol,
                        'status': 'error',
                        'error': str(e)
                    })
                    logger.error("close_error",
                               position_id=position['id'],
                               error=str(e))
        
        logger.info("task_completed",
                   task="manage_open_positions",
                   positions_checked=len(positions),
                   positions_closed=positions_closed)
        
        return {
            'status': 'success',
            'positions_checked': len(positions),
            'positions_closed': positions_closed,
            'close_results': close_results
        }
    
    except Exception as e:
        logger.error("task_error", task="manage_open_positions", error=str(e))
        return {'status': 'error', 'message': str(e)}

# PHASE 2: AI Guardrail Adjuster - Professional Risk Management
@celery_app.task(name='adjust_position_guardrails_ai')
def adjust_position_guardrails_ai():
    """Use AI to dynamically adjust stop-loss/take-profit on open ensemble positions
    
    This is PHASE 2 - AI as risk manager (not signal voter).
    Runs every 5 minutes to adapt guardrails to changing market conditions.
    """
    try:
        logger.info("task_started", task="adjust_position_guardrails_ai")
        
        # Get all open ensemble positions
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        id, symbol, entry_price, current_price, entry_time,
                        stop_loss_price, take_profit_price
                    FROM positions
                    WHERE status = 'open'
                    AND mode = 'paper'
                    AND position_type = 'ensemble'
                """)
                positions = cur.fetchall()
        
        if not positions:
            logger.info("no_open_ensemble_positions")
            return {'status': 'success', 'positions_checked': 0, 'adjustments_made': 0}
        
        adjustments_made = 0
        early_exits = 0
        
        for position in positions:
            try:
                # Calculate current P&L
                entry_price = float(position['entry_price'])
                current_price = float(position['current_price'])
                pnl_pct = ((current_price - entry_price) / entry_price) * 100
                
                # Calculate time held
                from datetime import timezone
                now_utc = datetime.now(timezone.utc)
                minutes_held = (now_utc - position['entry_time']).total_seconds() / 60
                
                # Get current volatility via Bollinger Band Width (ATR is not a computed indicator)
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            SELECT indicators, close
                            FROM ohlcv_candles
                            WHERE symbol = %s
                            ORDER BY timestamp DESC
                            LIMIT 1
                        """, (position['symbol'],))
                        candle = cur.fetchone()

                        current_volatility = None
                        if candle and candle['indicators'] and candle['close']:
                            _ind = candle['indicators']
                            _bbb = _ind.get('BBB_20_2.0_2.0') if isinstance(_ind, dict) else None
                            if _bbb:
                                # Normalize BBB (band-width %) to approximate ATR/close range
                                current_volatility = float(_bbb) / 100.0
                
                # Call AI guardrail adjuster
                ai_request = {
                    'position_id': position['id'],
                    'symbol': position['symbol'],
                    'entry_price': entry_price,
                    'current_price': current_price,
                    'unrealized_pnl_pct': pnl_pct,
                    'minutes_held': int(minutes_held),
                    'current_volatility': current_volatility,
                    'current_momentum': None  # TODO: Add momentum indicator
                }
                
                ai_response = requests.post(
                    f"http://{settings.service_host}:{settings.port_ai_api}/adjust-guardrails",
                    json=ai_request,
                    timeout=10
                )
                
                if ai_response.status_code != 200:
                    logger.warning("ai_guardrail_api_failed",
                                 position_id=position['id'],
                                 status=ai_response.status_code)
                    continue
                
                ai_result = ai_response.json()
                action = ai_result.get('action', 'hold')
                
                # Execute AI recommendation
                if action == 'exit_now' or action == 'take_profit':
                    # Close position immediately
                    try:
                        close_response = requests.post(
                            f"http://{settings.service_host}:{settings.port_trading_api}/close",
                            json={
                                'position_id': position['id'],
                                'mode': 'paper',
                                'reason': f"ai_recommendation_{action}: {ai_result.get('reasoning', '')[:50]}"
                            },
                            timeout=10
                        )
                        
                        if close_response.status_code == 200:
                            early_exits += 1
                            logger.info("ai_triggered_exit",
                                      position_id=position['id'],
                                      symbol=position['symbol'],
                                      action=action,
                                      pnl_pct=pnl_pct,
                                      reasoning=ai_result.get('reasoning', '')[:50])
                    except Exception as e:
                        logger.error("ai_exit_failed", position_id=position['id'], error=str(e))
                
                elif action in ['tighten_stop', 'raise_stop']:
                    # Adjust stop loss
                    new_stop_pct = ai_result.get('new_stop_loss_pct')
                    if new_stop_pct:
                        new_stop_price = entry_price * (1 - new_stop_pct / 100)
                        
                        # Only update if it makes sense (tighter for losses, higher for profits)
                        should_update = False
                        if action == 'tighten_stop' and pnl_pct < 0:
                            should_update = True
                        elif action == 'raise_stop' and pnl_pct > 0:
                            current_stop = float(position['stop_loss_price']) if position['stop_loss_price'] else entry_price * 0.98
                            should_update = new_stop_price > current_stop
                        
                        if should_update:
                            try:
                                with get_connection() as conn:
                                    with conn.cursor() as cur:
                                        cur.execute("""
                                            UPDATE positions
                                            SET stop_loss_price = %s
                                            WHERE id = %s
                                        """, (new_stop_price, position['id']))
                                        conn.commit()
                                        
                                        adjustments_made += 1
                                        logger.info("ai_adjusted_stop",
                                                  position_id=position['id'],
                                                  symbol=position['symbol'],
                                                  action=action,
                                                  new_stop_pct=new_stop_pct,
                                                  new_stop_price=new_stop_price,
                                                  pnl_pct=pnl_pct,
                                                  reasoning=ai_result.get('reasoning', '')[:50])
                            except Exception as e:
                                logger.error("stop_adjustment_failed", position_id=position['id'], error=str(e))
                
                elif action == 'hold':
                    # AI says no changes needed
                    logger.debug("ai_guardrail_hold",
                               position_id=position['id'],
                               symbol=position['symbol'],
                               pnl_pct=pnl_pct)
            
            except Exception as e:
                logger.error("position_guardrail_check_error",
                           position_id=position['id'],
                           error=str(e))
        
        logger.info("task_completed",
                   task="adjust_position_guardrails_ai",
                   positions_checked=len(positions),
                   adjustments_made=adjustments_made,
                   early_exits=early_exits)
        
        return {
            'status': 'success',
            'positions_checked': len(positions),
            'adjustments_made': adjustments_made,
            'early_exits': early_exits
        }
    
    except Exception as e:
        logger.error("task_error", task="adjust_position_guardrails_ai", error=str(e))
        return {'status': 'error', 'message': str(e)}

# Task: Rebalance portfolio
@celery_app.task(name='rebalance_portfolio')
def rebalance_portfolio(mode='paper'):
    """Rebalance portfolio allocation"""
    try:
        logger.info("task_started", task="rebalance_portfolio", mode=mode)
        
        # Call Portfolio API to rebalance
        response = requests.post(
            f"http://{settings.service_host}:{settings.port_portfolio_api}/rebalance",
            params={'mode': mode},
            timeout=60
        )
        
        if response.status_code == 200:
            data = response.json()
            logger.info("task_completed", task="rebalance_portfolio", actions=data.get('actions', {}))
            return data
        else:
            logger.error("task_failed", task="rebalance_portfolio", error=response.text)
            return {'status': 'error', 'message': response.text}
    
    except Exception as e:
        logger.error("task_error", task="rebalance_portfolio", error=str(e))
        return {'status': 'error', 'message': str(e)}

# Task: Run after-action analysis
@celery_app.task(name='run_afteraction')
def run_afteraction(mode='paper', hours=12):
    """Run after-action analysis"""
    try:
        logger.info("task_started", task="run_afteraction", mode=mode, hours=hours)
        
        # Call AfterAction API
        response = requests.post(
            f"http://{settings.service_host}:{settings.port_afteraction_api}/analyze",
            params={'mode': mode, 'hours': hours},
            timeout=120
        )
        
        if response.status_code == 200:
            data = response.json()
            logger.info("task_completed", 
                       task="run_afteraction",
                       report_id=data.get('report_id'),
                       recommendations=len(data.get('recommendations', [])))
            return data
        else:
            logger.error("task_failed", task="run_afteraction", error=response.text)
            return {'status': 'error', 'message': response.text}
    
    except Exception as e:
        logger.error("task_error", task="run_afteraction", error=str(e))
        return {'status': 'error', 'message': str(e)}

# Task: Run AfterAction Analysis (scheduled every 6 hours)
@celery_app.task(name='run_afteraction_analysis')
def run_afteraction_analysis(mode='paper', hours=12):
    """Run post-trade analysis to learn from wins/losses"""
    try:
        logger.info("task_started", task="run_afteraction_analysis", mode=mode, hours=hours)
        
        # Call AfterAction API
        response = requests.post(
            f"http://{settings.service_host}:{settings.port_afteraction_api}/analyze",
            params={'mode': mode, 'hours': hours},
            timeout=120
        )
        
        if response.status_code == 200:
            result = response.json()
            logger.info("task_completed", task="run_afteraction_analysis", insights=len(result.get('insights', [])))
            return result
        else:
            logger.error("afteraction_error", status_code=response.status_code)
            return {'status': 'error', 'message': f'HTTP {response.status_code}'}
            
    except Exception as e:
        logger.error("afteraction_exception", error=str(e))
        return {'status': 'error', 'message': str(e)}

@celery_app.task(name='health_check')
def health_check():
    """Run system health check"""
    try:
        logger.info("task_started", task="health_check")
        
        response = requests.get(
            f"http://{settings.service_host}:{settings.port_testing_api}/test/run-all",
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            health_score = data.get('health_score', 0)
            
            logger.info("task_completed", 
                       task="health_check",
                       health_score=health_score)
            
            # Record health status to database
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO system_health 
                        (health_score, details, checked_at)
                        VALUES (%s, %s, NOW())
                    """, (health_score, str(data)))
            
            return data
        else:
            logger.error("task_failed", task="health_check")
            return {'status': 'error', 'health_score': 0}
    
    except Exception as e:
        logger.error("task_error", task="health_check", error=str(e))
        return {'status': 'error', 'message': str(e)}

# Task: Fetch hourly candles
@celery_app.task(name='fetch_hourly_candles')
def fetch_hourly_candles():
    """Fetch hourly candles for all active symbols"""
    try:
        logger.info("task_started", task="fetch_hourly_candles")
        
        symbols = get_active_symbols()
        results = []
        
        for symbol in symbols:
            try:
                response = requests.post(
                    f"http://{settings.service_host}:{settings.port_ohlcv_api}/candles/fetch",
                    params={
                        'symbol': symbol['symbol'],
                        'timeframe': '1h',
                        'limit': 24
                    },
                    timeout=30
                )
                
                if response.status_code == 200:
                    results.append({'symbol': symbol['symbol'], 'status': 'success'})
                else:
                    results.append({'symbol': symbol['symbol'], 'status': 'failed'})
            
            except Exception as e:
                results.append({'symbol': symbol['symbol'], 'status': 'error'})
        
        logger.info("task_completed", task="fetch_hourly_candles", results=results)
        return results
    
    except Exception as e:
        logger.error("task_error", task="fetch_hourly_candles", error=str(e))
        return {'status': 'error', 'message': str(e)}

@celery_app.task(name='check_symbol_health')
def check_symbol_health():
    """Check symbols and disable those that can't fetch candles"""
    try:
        logger.info("task_started", task="check_symbol_health")
        
        # Get all symbols (including those with status='active' but no candles)
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Find symbols that are active but haven't had successful candle retrieval
                # in the last 24 hours (or never)
                cur.execute("""
                    SELECT id, symbol, status, last_candle_at,
                           EXTRACT(EPOCH FROM (NOW() - last_candle_at))/3600 as hours_since_last
                    FROM symbols
                    WHERE status = 'active'
                    AND (
                        last_candle_at IS NULL 
                        OR last_candle_at < NOW() - INTERVAL '24 hours'
                    )
                """)
                
                stale_symbols = cur.fetchall()
                
                if not stale_symbols:
                    logger.info("all_symbols_healthy")
                    return {'status': 'success', 'disabled_count': 0}
                
                disabled_count = 0
                disabled_symbols = []
                
                for sym in stale_symbols:
                    symbol = sym['symbol']
                    last_candle = sym['last_candle_at']
                    hours_since = sym['hours_since_last'] if last_candle else None
                    
                    # For symbols that have NEVER had candles, give them 48 hours grace period
                    # (system might be starting up, backfill in progress, etc.)
                    if last_candle is None:
                        # Check when symbol was added
                        cur.execute("""
                            SELECT EXTRACT(EPOCH FROM (NOW() - added_at))/3600 as hours_since_added
                            FROM symbols WHERE symbol = %s
                        """, (symbol,))
                        result = cur.fetchone()
                        hours_since_added = result['hours_since_added'] if result else 0
                        
                        # Only disable if it's been more than 48 hours since added
                        if hours_since_added < 48:
                            logger.info("symbol_grace_period", symbol=symbol, hours_since_added=hours_since_added)
                            continue
                    
                    # Disable the symbol
                    cur.execute("""
                        UPDATE symbols 
                        SET status = 'inactive',
                            metadata = jsonb_set(
                                COALESCE(metadata, '{}'::jsonb),
                                '{disabled_reason}',
                                '"Cannot fetch candles from exchange"'
                            ),
                            metadata = jsonb_set(
                                metadata,
                                '{disabled_at}',
                                to_jsonb(NOW()::text)
                            )
                        WHERE symbol = %s
                    """, (symbol,))
                    
                    disabled_count += 1
                    disabled_symbols.append({
                        'symbol': symbol,
                        'hours_since_last': hours_since if hours_since else 'never'
                    })
                    
                    logger.warning("symbol_disabled", 
                                 symbol=symbol, 
                                 reason="no_candles",
                                 hours_since_last=hours_since if hours_since else 'never')
                
                conn.commit()
                
                logger.info("task_completed", 
                          task="check_symbol_health",
                          disabled_count=disabled_count,
                          disabled_symbols=disabled_symbols)
                
                return {
                    'status': 'success',
                    'disabled_count': disabled_count,
                    'disabled_symbols': disabled_symbols
                }
    
    except Exception as e:
        logger.error("task_error", task="check_symbol_health", error=str(e))
        return {'status': 'error', 'message': str(e)}

# Task: Calculate Strategy Performance (Phase 2)
@celery_app.task(name='calculate_strategy_performance')
def calculate_strategy_performance():
    """Calculate rolling performance metrics for all strategies"""
    try:
        logger.info("task_started", task="calculate_strategy_performance")
        
        from datetime import datetime, timedelta
        
        # Get all active strategies
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, name FROM strategies WHERE enabled = true")
                strategies = [dict(row) for row in cur.fetchall()]
        
        if not strategies:
            logger.warning("no_active_strategies")
            return {'status': 'success', 'message': 'No active strategies'}
        
        # Get all active symbols
        symbols = get_active_symbols()
        
        # Calculate for 7, 14, and 30 day windows
        windows = [7, 14, 30]
        results = []
        
        for strategy in strategies:
            for symbol_data in symbols:
                symbol = symbol_data['symbol']
                
                for period_days in windows:
                    try:
                        perf = calculate_performance_window(
                            strategy['id'], 
                            symbol, 
                            period_days
                        )
                        
                        if perf:
                            results.append({
                                'strategy': strategy['name'],
                                'symbol': symbol,
                                'period': f'{period_days}d',
                                'win_rate': perf['win_rate'],
                                'trades': perf['total_trades']
                            })
                            
                    except Exception as e:
                        logger.error("performance_calc_error",
                                   strategy=strategy['name'],
                                   symbol=symbol,
                                   period=period_days,
                                   error=str(e))
        
        logger.info("task_completed", 
                   task="calculate_strategy_performance",
                   strategies=len(strategies),
                   symbols=len(symbols),
                   calculations=len(results))
        
        return {
            'status': 'success',
            'calculations': len(results),
            'results': results[:10]  # Sample of results
        }
    
    except Exception as e:
        logger.error("task_error", task="calculate_strategy_performance", error=str(e))
        return {'status': 'error', 'message': str(e)}


def calculate_performance_window(strategy_id, symbol, period_days):
    """Calculate performance metrics for a strategy on a symbol over time window"""
    period_end = datetime.utcnow()
    period_start = period_end - timedelta(days=period_days)
    
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Get signals from this strategy
            cur.execute("""
                SELECT COUNT(*) as total_signals,
                       SUM(CASE WHEN acted_on THEN 1 ELSE 0 END) as acted_on
                FROM signals
                WHERE strategy_id = %s
                AND symbol = %s
                AND generated_at >= %s
                AND generated_at <= %s
            """, (strategy_id, symbol, period_start, period_end))
            
            signal_stats = dict(cur.fetchone())
            
            # Get trades from this strategy
            cur.execute("""
                SELECT 
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) as winning_trades,
                    SUM(CASE WHEN realized_pnl <= 0 THEN 1 ELSE 0 END) as losing_trades,
                    SUM(realized_pnl) as total_pnl,
                    AVG(realized_pnl_pct) as avg_profit_pct,
                    MAX(realized_pnl_pct) as max_profit_pct,
                    MIN(realized_pnl_pct) as max_loss_pct,
                    STDDEV(realized_pnl_pct) as stddev_returns
                FROM positions
                WHERE strategy_id = %s
                AND symbol = %s
                AND entry_time >= %s
                AND entry_time <= %s
                AND status = 'closed'
            """, (strategy_id, symbol, period_start, period_end))
            
            trade_stats = dict(cur.fetchone())
            
            # Calculate derived metrics
            total_trades = trade_stats['total_trades'] or 0
            winning_trades = trade_stats['winning_trades'] or 0
            losing_trades = trade_stats['losing_trades'] or 0
            
            win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
            
            # Calculate Sharpe ratio (simplified: avg_return / stddev)
            avg_return = float(trade_stats['avg_profit_pct'] or 0)
            stddev = float(trade_stats['stddev_returns'] or 1)
            sharpe_ratio = (avg_return / stddev) if stddev > 0 else 0
            
            # Calculate profit factor (gross_profit / gross_loss)
            # For simplification, we'll estimate it from win rate and avg returns
            profit_factor = None
            if losing_trades > 0 and winning_trades > 0:
                profit_factor = (winning_trades / losing_trades) * abs(avg_return)
            
            # Insert or update performance record
            cur.execute("""
                INSERT INTO strategy_performance
                (strategy_id, symbol, period_days, period_start, period_end,
                 total_signals, signals_acted_on, total_trades, winning_trades, 
                 losing_trades, win_rate, total_pnl, avg_profit_pct,
                 max_profit_pct, max_loss_pct, sharpe_ratio, profit_factor, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (strategy_id, symbol, period_days)
                DO UPDATE SET
                    period_start = EXCLUDED.period_start,
                    period_end = EXCLUDED.period_end,
                    total_signals = EXCLUDED.total_signals,
                    signals_acted_on = EXCLUDED.signals_acted_on,
                    total_trades = EXCLUDED.total_trades,
                    winning_trades = EXCLUDED.winning_trades,
                    losing_trades = EXCLUDED.losing_trades,
                    win_rate = EXCLUDED.win_rate,
                    total_pnl = EXCLUDED.total_pnl,
                    avg_profit_pct = EXCLUDED.avg_profit_pct,
                    max_profit_pct = EXCLUDED.max_profit_pct,
                    max_loss_pct = EXCLUDED.max_loss_pct,
                    sharpe_ratio = EXCLUDED.sharpe_ratio,
                    profit_factor = EXCLUDED.profit_factor,
                    updated_at = NOW()
            """, (
                strategy_id, symbol, period_days, period_start, period_end,
                signal_stats['total_signals'], signal_stats['acted_on'],
                total_trades, winning_trades, losing_trades, win_rate,
                trade_stats['total_pnl'], avg_return,
                trade_stats['max_profit_pct'], trade_stats['max_loss_pct'],
                sharpe_ratio, profit_factor
            ))
            
            conn.commit()
            
            return {
                'win_rate': win_rate,
                'total_trades': total_trades,
                'total_signals': signal_stats['total_signals']
            }


# Phase 4: Market Regime Detection
def detect_market_regime(symbol, lookback_hours=24):
    """
    Detect market regime for a symbol using technical indicators
    
    Regimes:
    - trending_up: Strong uptrend (ADX > 25, positive slope, increasing ATR)
    - trending_down: Strong downtrend (ADX > 25, negative slope, increasing ATR)
    - ranging: Sideways movement (ADX < 20, low slope, stable ATR)
    - volatile: High volatility without clear direction (high ATR variation, low ADX)
    
    Returns: dict with regime, confidence, and metrics
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Get recent candles for analysis
                cutoff_time = datetime.utcnow() - timedelta(hours=lookback_hours)
                
                cur.execute("""
                    SELECT timestamp, open, high, low, close, volume
                    FROM ohlcv_candles
                    WHERE symbol = %s
                    AND timestamp >= %s
                    ORDER BY timestamp ASC
                """, (symbol, cutoff_time))
                
                candles = [dict(row) for row in cur.fetchall()]
                
                if len(candles) < 50:
                    return {
                        'regime': 'unknown',
                        'confidence': 0,
                        'reason': 'Insufficient data'
                    }
                
                # Extract price data
                closes = np.array([float(c['close']) for c in candles])
                highs = np.array([float(c['high']) for c in candles])
                lows = np.array([float(c['low']) for c in candles])
                
                # Calculate ATR (Average True Range) - 14 period
                tr_list = []
                for i in range(1, len(candles)):
                    high_low = highs[i] - lows[i]
                    high_close = abs(highs[i] - closes[i-1])
                    low_close = abs(lows[i] - closes[i-1])
                    tr = max(high_low, high_close, low_close)
                    tr_list.append(tr)
                
                atr = np.mean(tr_list[-14:]) if len(tr_list) >= 14 else np.mean(tr_list)
                atr_pct = (atr / closes[-1]) * 100
                
                # Calculate ADX (Average Directional Index) - simplified
                # Using 14-period smoothing
                period = min(14, len(closes) // 3)
                
                # Calculate +DM and -DM
                plus_dm = []
                minus_dm = []
                for i in range(1, len(candles)):
                    high_diff = highs[i] - highs[i-1]
                    low_diff = lows[i-1] - lows[i]
                    
                    plus_dm.append(high_diff if high_diff > low_diff and high_diff > 0 else 0)
                    minus_dm.append(low_diff if low_diff > high_diff and low_diff > 0 else 0)
                
                # Smooth DM values
                plus_di = np.mean(plus_dm[-period:]) / atr if atr > 0 else 0
                minus_di = np.mean(minus_dm[-period:]) / atr if atr > 0 else 0
                
                # Calculate DX and ADX
                dx = abs(plus_di - minus_di) / (plus_di + minus_di) if (plus_di + minus_di) > 0 else 0
                adx = dx * 100  # Simplified ADX
                
                # Calculate linear regression slope (trend strength)
                x = np.arange(len(closes))
                coefficients = np.polyfit(x, closes, 1)
                slope = coefficients[0]
                slope_pct = (slope / closes[-1]) * 100
                
                # Calculate volatility (stdev of returns)
                returns = np.diff(closes) / closes[:-1]
                volatility = np.std(returns) * 100
                
                # Regime classification logic
                regime = 'ranging'
                confidence = 50
                
                if adx > 25:  # Strong trend
                    if slope_pct > 0.05:  # Upward slope
                        regime = 'trending_up'
                        confidence = min(85, 60 + adx)
                    elif slope_pct < -0.05:  # Downward slope
                        regime = 'trending_down'
                        confidence = min(85, 60 + adx)
                    else:
                        regime = 'ranging'
                        confidence = 70
                elif volatility > 3.0:  # High volatility but no clear trend
                    regime = 'volatile'
                    confidence = min(80, 50 + volatility * 10)
                elif adx < 20 and abs(slope_pct) < 0.05:  # Clear ranging
                    regime = 'ranging'
                    confidence = min(85, 60 + (20 - adx) * 2)
                else:
                    # Ambiguous - default to ranging with low confidence
                    regime = 'ranging'
                    confidence = 40
                
                return {
                    'regime': regime,
                    'confidence': round(confidence, 2),
                    'atr': round(atr, 8),
                    'atr_pct': round(atr_pct, 4),
                    'adx': round(adx, 4),
                    'trend_slope': round(slope_pct, 6),
                    'volatility_pct': round(volatility, 4),
                    'metadata': {
                        'plus_di': round(plus_di, 4),
                        'minus_di': round(minus_di, 4),
                        'candles_analyzed': len(candles)
                    }
                }
    
    except Exception as e:
        logger.error("regime_detection_error", symbol=symbol, error=str(e))
        return {
            'regime': 'unknown',
            'confidence': 0,
            'reason': str(e)
        }


@celery_app.task(name='detect_market_regimes')
def detect_market_regimes():
    """
    Detect market regimes for all active symbols (Phase 4)
    Runs every 15 minutes to keep regime data fresh
    """
    try:
        logger.info("task_started", task="detect_market_regimes")
        
        # Get all active symbols
        symbols = get_active_symbols()
        
        results = []
        
        for symbol_data in symbols:
            symbol = symbol_data['symbol']
            
            # Detect regime
            regime_data = detect_market_regime(symbol, lookback_hours=24)
            
            if regime_data['regime'] != 'unknown':
                # Store in database (convert numpy types to Python native types)
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO market_regime
                            (symbol, regime, confidence, atr, adx, trend_slope, 
                             volatility_pct, detected_at, updated_at, metadata)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW(), %s)
                            ON CONFLICT (symbol)
                            DO UPDATE SET
                                regime = EXCLUDED.regime,
                                confidence = EXCLUDED.confidence,
                                atr = EXCLUDED.atr,
                                adx = EXCLUDED.adx,
                                trend_slope = EXCLUDED.trend_slope,
                                volatility_pct = EXCLUDED.volatility_pct,
                                updated_at = NOW(),
                                metadata = EXCLUDED.metadata
                        """, (
                            symbol,
                            regime_data['regime'],
                            float(regime_data['confidence']),
                            float(regime_data.get('atr', 0)) if regime_data.get('atr') else None,
                            float(regime_data.get('adx', 0)) if regime_data.get('adx') else None,
                            float(regime_data.get('trend_slope', 0)) if regime_data.get('trend_slope') else None,
                            float(regime_data.get('volatility_pct', 0)) if regime_data.get('volatility_pct') else None,
                            json.dumps(regime_data.get('metadata', {}))
                        ))
                
                results.append({
                    'symbol': symbol,
                    'regime': regime_data['regime'],
                    'confidence': regime_data['confidence']
                })
        
        logger.info("task_completed",
                   task="detect_market_regimes",
                   symbols_analyzed=len(results))
        
        return {
            'status': 'success',
            'regimes_detected': len(results),
            'results': results[:5]  # Sample results
        }
    
    except Exception as e:
        logger.error("task_error", task="detect_market_regimes", error=str(e))
        return {'status': 'error', 'message': str(e)}


# Phase 5: Multi-Timeframe Aggregation
def aggregate_timeframe(symbol, source_timeframe='1m', target_timeframe='5m', lookback_hours=2):
    """
    Aggregate candles from source timeframe to target timeframe
    
    Args:
        symbol: Trading symbol
        source_timeframe: Source timeframe (default '1m')
        target_timeframe: Target timeframe ('5m', '15m', '1h')
        lookback_hours: How far back to aggregate
    
    Returns: Number of candles aggregated
    """
    try:
        # Define timeframe intervals in minutes
        intervals = {
            '1m': 1,
            '5m': 5,
            '15m': 15,
            '1h': 60
        }
        
        source_interval = intervals.get(source_timeframe, 1)
        target_interval = intervals.get(target_timeframe, 5)
        
        if target_interval <= source_interval:
            return 0
        
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Get recent source candles
                cutoff_time = datetime.utcnow() - timedelta(hours=lookback_hours)
                
                cur.execute("""
                    SELECT timestamp, open, high, low, close, volume
                    FROM ohlcv_candles
                    WHERE symbol = %s
                    AND timeframe = %s
                    AND timestamp >= %s
                    ORDER BY timestamp ASC
                """, (symbol, source_timeframe, cutoff_time))
                
                source_candles = [dict(row) for row in cur.fetchall()]
                
                if len(source_candles) < 2:
                    return 0
                
                # Group candles into target timeframe buckets
                aggregated = {}
                
                for candle in source_candles:
                    # Round timestamp down to target interval
                    ts = candle['timestamp']
                    # Convert to minutes since epoch
                    minutes_since_epoch = int(ts.timestamp() / 60)
                    # Round down to target interval
                    bucket = (minutes_since_epoch // target_interval) * target_interval
                    bucket_ts = datetime.fromtimestamp(bucket * 60, tz=ts.tzinfo)
                    
                    if bucket_ts not in aggregated:
                        aggregated[bucket_ts] = {
                            'open': float(candle['open']),
                            'high': float(candle['high']),
                            'low': float(candle['low']),
                            'close': float(candle['close']),
                            'volume': float(candle['volume']),
                            'count': 1
                        }
                    else:
                        # Update aggregated candle
                        agg = aggregated[bucket_ts]
                        agg['high'] = max(agg['high'], float(candle['high']))
                        agg['low'] = min(agg['low'], float(candle['low']))
                        agg['close'] = float(candle['close'])  # Last close
                        agg['volume'] += float(candle['volume'])
                        agg['count'] += 1
                
                # Insert aggregated candles
                inserted = 0
                for bucket_ts, agg_candle in aggregated.items():
                    # Only insert if we have enough source candles for this bucket
                    expected_candles = target_interval // source_interval
                    if agg_candle['count'] >= expected_candles * 0.8:  # At least 80% complete
                        cur.execute("""
                            INSERT INTO ohlcv_candles
                            (symbol, timeframe, timestamp, open, high, low, close, volume)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (symbol, timeframe, timestamp)
                            DO UPDATE SET
                                open = EXCLUDED.open,
                                high = EXCLUDED.high,
                                low = EXCLUDED.low,
                                close = EXCLUDED.close,
                                volume = EXCLUDED.volume
                        """, (
                            symbol,
                            target_timeframe,
                            bucket_ts,
                            agg_candle['open'],
                            agg_candle['high'],
                            agg_candle['low'],
                            agg_candle['close'],
                            agg_candle['volume']
                        ))
                        inserted += 1
                
                conn.commit()
                return inserted
    
    except Exception as e:
        logger.error("aggregate_timeframe_error", 
                    symbol=symbol, 
                    target=target_timeframe, 
                    error=str(e))
        return 0


@celery_app.task(name='aggregate_multi_timeframes')
def aggregate_multi_timeframes():
    """
    Aggregate 1-minute candles into higher timeframes (Phase 5)
    Creates 5m, 15m, and 1h candles from 1m source data
    Runs every 5 minutes to keep higher timeframes up to date
    """
    try:
        logger.info("task_started", task="aggregate_multi_timeframes")
        
        # Get all active symbols
        symbols = get_active_symbols()
        
        results = {
            '5m': 0,
            '15m': 0,
            '1h': 0
        }
        
        for symbol_data in symbols:
            symbol = symbol_data['symbol']
            
            # Aggregate to 5-minute candles (last 2 hours)
            count_5m = aggregate_timeframe(symbol, '1m', '5m', lookback_hours=2)
            results['5m'] += count_5m
            
            # Aggregate to 15-minute candles (last 6 hours)
            count_15m = aggregate_timeframe(symbol, '1m', '15m', lookback_hours=6)
            results['15m'] += count_15m
            
            # Aggregate to 1-hour candles (last 48 hours)
            count_1h = aggregate_timeframe(symbol, '1m', '1h', lookback_hours=48)
            results['1h'] += count_1h
        
        logger.info("task_completed",
                   task="aggregate_multi_timeframes",
                   symbols=len(symbols),
                   candles_5m=results['5m'],
                   candles_15m=results['15m'],
                   candles_1h=results['1h'])
        
        return {
            'status': 'success',
            'symbols_processed': len(symbols),
            'aggregated_candles': results
        }
    
    except Exception as e:
        logger.error("task_error", task="aggregate_multi_timeframes", error=str(e))
        return {'status': 'error', 'message': str(e)}


# ==================== PHASE 6: AI AGENT ====================

@celery_app.task(name='run_ai_agent')
def run_ai_agent():
    """Run autonomous AI agent decision cycle (Phase 6)"""
    try:
        logger.info("task_started", task="run_ai_agent")
        
        # Import agent class
        sys.path.insert(0, '/opt/trading/services/ai_api')
        from agent import TradingAgent
        
        # Create agent instance
        agent = TradingAgent()
        
        # Check if agent is enabled
        if not agent.config.get('enabled', False):
            logger.info("agent_disabled", msg="AI agent is disabled in config")
            return {
                'status': 'skipped',
                'reason': 'Agent is disabled'
            }
        
        # Run decision cycle (synchronous wrapper for async function)
        import asyncio
        
        # Create or get event loop
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        # Run the async function
        result = loop.run_until_complete(agent.run_decision_cycle())
        
        logger.info("task_completed", 
                   task="run_ai_agent",
                   status=result.get('status'),
                   actions=len(result.get('decision', {}).get('actions', [])))
        
        return result
    
    except Exception as e:
        logger.error("task_error", task="run_ai_agent", error=str(e))
        return {'status': 'error', 'message': str(e)}


# ==================== PHASE 7: WALK-FORWARD OPTIMIZATION ====================

@celery_app.task(name='run_walkforward_optimization')
def run_walkforward_optimization():
    """Run walk-forward optimization for all active strategies (Phase 7)"""
    try:
        logger.info("task_started", task="run_walkforward_optimization")
        
        # Record optimization run start
        run_start = datetime.utcnow()
        
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Create optimization run record
                cur.execute("""
                    INSERT INTO optimization_runs (run_type, started_at, status)
                    VALUES ('walk_forward', %s, 'running')
                    RETURNING id
                """, (run_start,))
                
                run_id = cur.fetchone()['id']
                
                logger.info("optimization_run_started", run_id=run_id)
        
        # Get all active strategies
        symbols = get_active_symbols()
        strategies_processed = 0
        parameters_tested = 0
        parameters_promoted = 0
        errors = []
        
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Get all strategies
                cur.execute("""
                    SELECT id, name, description, parameters, metadata
                    FROM strategies
                    WHERE enabled = TRUE
                """)
                
                strategies = [dict(row) for row in cur.fetchall()]
        
        logger.info("strategies_to_optimize", count=len(strategies), symbols=len(symbols))
        
        # Walk-forward optimize each strategy for each symbol
        for strategy in strategies:
            for symbol_data in symbols:
                symbol = symbol_data['symbol']
                
                # Get current market regime for this symbol
                current_regime = None
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            SELECT regime, confidence
                            FROM market_regime
                            WHERE symbol = %s
                            ORDER BY detected_at DESC
                            LIMIT 1
                        """, (symbol,))
                        
                        regime_data = cur.fetchone()
                        if regime_data:
                            current_regime = regime_data['regime']
                
                # Check if strategy is suitable for current regime
                strategy_metadata = strategy.get('metadata', {})
                suitable_regimes = strategy_metadata.get('suitable_regimes', [])
                
                if current_regime and suitable_regimes:
                    if current_regime not in suitable_regimes:
                        logger.info("strategy_skipped_regime_mismatch",
                                   strategy_id=strategy['id'],
                                   symbol=symbol,
                                   current_regime=current_regime,
                                   suitable_regimes=suitable_regimes)
                        continue  # Skip this strategy for this symbol
                
                try:
                    # Run walk-forward optimization
                    result = optimize_strategy_walkforward(
                        strategy_id=strategy['id'],
                        symbol=symbol,
                        training_days=60,
                        test_days=7
                    )
                    
                    strategies_processed += 1
                    parameters_tested += result.get('combinations_tested', 0)
                    
                    if result.get('promoted', False):
                        parameters_promoted += 1
                    
                    logger.info("strategy_optimized",
                               strategy_id=strategy['id'],
                               symbol=symbol,
                               improved=result.get('improved', False))
                
                except Exception as e:
                    error_msg = f"Strategy {strategy['id']} - {symbol}: {str(e)}"
                    errors.append(error_msg)
                    logger.error("optimization_error", 
                                strategy_id=strategy['id'],
                                symbol=symbol,
                                error=str(e))
        
        # Update optimization run record
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE optimization_runs
                    SET completed_at = %s,
                        strategies_processed = %s,
                        parameters_tested = %s,
                        parameters_promoted = %s,
                        status = %s,
                        error = %s,
                        results = %s
                    WHERE id = %s
                """, (
                    datetime.utcnow(),
                    strategies_processed,
                    parameters_tested,
                    parameters_promoted,
                    'completed' if not errors else 'completed_with_errors',
                    '\n'.join(errors) if errors else None,
                    json.dumps({
                        'strategies': len(strategies),
                        'symbols': len(symbols),
                        'duration_seconds': (datetime.utcnow() - run_start).total_seconds()
                    }),
                    run_id
                ))
        
        logger.info("task_completed",
                   task="run_walkforward_optimization",
                   strategies_processed=strategies_processed,
                   parameters_promoted=parameters_promoted)
        
        return {
            'status': 'success',
            'run_id': run_id,
            'strategies_processed': strategies_processed,
            'parameters_tested': parameters_tested,
            'parameters_promoted': parameters_promoted,
            'errors': len(errors)
        }
    
    except Exception as e:
        logger.error("task_error", task="run_walkforward_optimization", error=str(e))
        
        # Mark run as failed
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE optimization_runs
                        SET completed_at = %s, status = 'failed', error = %s
                        WHERE id = %s
                    """, (datetime.utcnow(), str(e), run_id))
        except:
            pass
        
        return {'status': 'error', 'message': str(e)}


def optimize_strategy_walkforward(strategy_id, symbol, training_days=60, test_days=7):
    """
    Walk-forward optimization for a single strategy-symbol pair
    
    Args:
        strategy_id: Strategy ID to optimize
        symbol: Symbol to optimize for
        training_days: Days of data to train on
        test_days: Days of data to test on
    
    Returns: Dict with optimization results
    """
    try:
        logger.info("walkforward_start", strategy_id=strategy_id, symbol=symbol)
        
        # Get strategy
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT * FROM strategies WHERE id = %s
                """, (strategy_id,))
                
                strategy = dict(cur.fetchone())
        
        # Define training and test periods
        test_end = datetime.utcnow().date()
        test_start = test_end - timedelta(days=test_days)
        training_end = test_start - timedelta(days=1)
        training_start = training_end - timedelta(days=training_days)
        
        # Get parameter ranges based on strategy name
        parameter_ranges = get_parameter_ranges_for_strategy(strategy['name'])
        
        if not parameter_ranges:
            logger.info("no_parameters_to_optimize", 
                       strategy_id=strategy_id,
                       strategy_name=strategy['name'])
            return {
                'improved': False,
                'promoted': False,
                'combinations_tested': 0,
                'reason': 'No tunable parameters'
            }
        
        # Run grid search on training period
        logger.info("training_optimization",
                   strategy_id=strategy_id,
                   symbol=symbol,
                   training_start=training_start,
                   training_end=training_end)
        
        best_params, best_score, combinations_tested = run_grid_search_for_strategy(
            strategy=strategy,
            symbol=symbol,
            start_date=training_start,
            end_date=training_end,
            parameter_ranges=parameter_ranges
        )
        
        # Test best parameters on test period
        logger.info("testing_parameters",
                   strategy_id=strategy_id,
                   symbol=symbol,
                   test_start=test_start,
                   test_end=test_end)
        
        test_performance = backtest_parameters(
            strategy=strategy,
            symbol=symbol,
            parameters=best_params,
            start_date=test_start,
            end_date=test_end
        )
        
        # Get current parameter performance on same test period
        current_performance = backtest_parameters(
            strategy=strategy,
            symbol=symbol,
            parameters=strategy.get('parameters', {}),
            start_date=test_start,
            end_date=test_end
        )
        
        # Save parameter version
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO parameter_versions 
                    (strategy_id, symbol, parameters, training_start, training_end,
                     test_start, test_end, training_performance, test_performance, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'testing')
                    RETURNING id
                """, (
                    strategy_id,
                    symbol,
                    json.dumps(best_params),
                    training_start,
                    training_end,
                    test_start,
                    test_end,
                    json.dumps({'sharpe_ratio': best_score}),
                    json.dumps(test_performance)
                ))
                
                param_version_id = cur.fetchone()['id']
        
        # Compare performance
        improved = test_performance.get('sharpe_ratio', 0) > current_performance.get('sharpe_ratio', 0)
        
        # Promote if improved significantly (>10% better)
        improvement_pct = (
            (test_performance.get('sharpe_ratio', 0) - current_performance.get('sharpe_ratio', 0))
            / (abs(current_performance.get('sharpe_ratio', 0.01)))
        ) * 100
        
        promoted = False
        
        if improved and improvement_pct > 10:
            # Promote to live
            with get_connection() as conn:
                with conn.cursor() as cur:
                    # Update strategy parameters
                    cur.execute("""
                        UPDATE strategies
                        SET parameters = %s,
                            current_parameter_version_id = %s,
                            last_optimized_at = %s
                        WHERE id = %s
                    """, (json.dumps(best_params), param_version_id, datetime.utcnow(), strategy_id))
                    
                    # Mark parameter version as promoted
                    cur.execute("""
                        UPDATE parameter_versions
                        SET status = 'promoted', promoted_at = %s
                        WHERE id = %s
                    """, (datetime.utcnow(), param_version_id))
            
            promoted = True
            
            logger.info("parameters_promoted",
                       strategy_id=strategy_id,
                       symbol=symbol,
                       improvement_pct=round(improvement_pct, 2),
                       old_sharpe=round(current_performance.get('sharpe_ratio', 0), 3),
                       new_sharpe=round(test_performance.get('sharpe_ratio', 0), 3))
        else:
            logger.info("parameters_not_promoted",
                       strategy_id=strategy_id,
                       symbol=symbol,
                       improved=improved,
                       improvement_pct=round(improvement_pct, 2))
        
        return {
            'improved': improved,
            'promoted': promoted,
            'combinations_tested': combinations_tested,
            'improvement_pct': round(improvement_pct, 2),
            'old_sharpe': round(current_performance.get('sharpe_ratio', 0), 3),
            'new_sharpe': round(test_performance.get('sharpe_ratio', 0), 3)
        }
    
    except Exception as e:
        logger.error("walkforward_error",
                    strategy_id=strategy_id,
                    symbol=symbol,
                    error=str(e))
        raise


def get_parameter_ranges_for_strategy(strategy_name):
    """Get parameter ranges to optimize based on strategy name/type"""
    
    # Detect strategy type from name
    name_upper = strategy_name.upper()
    
    ranges = {}
    
    # RSI strategies
    if 'RSI' in name_upper:
        ranges = {
            'rsi_period': [10, 14, 20, 30],
            'oversold': [20, 25, 30],
            'overbought': [70, 75, 80]
        }
    # MACD strategies
    elif 'MACD' in name_upper:
        ranges = {
            'fast_period': [8, 12, 16],
            'slow_period': [21, 26, 30],
            'signal_period': [7, 9, 11]
        }
    # Bollinger Band strategies
    elif 'BB' in name_upper or 'BOLLINGER' in name_upper:
        ranges = {
            'period': [15, 20, 25],
            'std_dev': [1.5, 2.0, 2.5]
        }
    # Moving Average strategies
    elif 'SMA' in name_upper or 'CROSS' in name_upper:
        ranges = {
            'fast_period': [5, 10, 20],
            'slow_period': [20, 50, 100]
        }
    elif 'EMA' in name_upper:
        ranges = {
            'fast_period': [8, 12, 21],
            'slow_period': [21, 34, 55]
        }
    # VWAP strategies (covers 67% of unmatched strategies)
    elif 'VWAP' in name_upper:
        ranges = {
            'vwap_period': [15, 20, 30],
            'deviation_threshold': [0.5, 1.0, 1.5, 2.0],
            'lookback_period': [10, 20, 30]
        }
    # Mean Reversion strategies
    elif 'MEAN REVERSION' in name_upper or 'REVERSION' in name_upper:
        ranges = {
            'lookback_period': [10, 20, 30, 50],
            'entry_threshold': [1.0, 1.5, 2.0],
            'exit_threshold': [0.5, 0.75, 1.0]
        }
    # Momentum/Breakout strategies
    elif 'MOMENTUM' in name_upper or 'BREAKOUT' in name_upper:
        ranges = {
            'momentum_period': [10, 14, 20],
            'breakout_threshold': [0.5, 1.0, 1.5, 2.0],
            'lookback_period': [20, 30, 50]
        }
    # Trend following strategies
    elif 'TREND' in name_upper or 'RIDER' in name_upper:
        ranges = {
            'trend_period': [20, 30, 50],
            'smoothing_period': [5, 10, 14],
            'min_trend_strength': [0.3, 0.5, 0.7]
        }
    # Volume/Institutional strategies
    elif 'VOLUME' in name_upper or 'INSTITUTIONAL' in name_upper or 'SHADOW' in name_upper:
        ranges = {
            'volume_period': [10, 20, 30],
            'volume_threshold': [1.5, 2.0, 2.5],
            'price_sensitivity': [0.5, 1.0, 1.5]
        }
    # Volatility strategies
    elif 'VOLATILITY' in name_upper or 'ATR' in name_upper:
        ranges = {
            'atr_period': [10, 14, 20],
            'volatility_multiplier': [1.5, 2.0, 2.5],
            'smoothing_period': [5, 10, 14]
        }
    # Confluence/Multi-indicator strategies
    elif 'CONFLUENCE' in name_upper or 'TRIPLE' in name_upper or 'MULTI' in name_upper:
        ranges = {
            'fast_period': [10, 14, 20],
            'slow_period': [20, 30, 50],
            'confirmation_threshold': [2, 3, 4]  # Number of indicators that must align
        }
    # Generic fallback for any strategy without a specific pattern
    else:
        # Provide basic parameter ranges that work for most technical strategies
        ranges = {
            'period': [10, 14, 20, 30],
            'threshold': [0.5, 1.0, 1.5, 2.0],
            'lookback': [10, 20, 30]
        }
    
    return ranges


def run_grid_search_for_strategy(strategy, symbol, start_date, end_date, parameter_ranges):
    """
    Run grid search to find best parameters
    
    Returns: (best_params, best_score, combinations_tested)
    """
    try:
        # Generate all parameter combinations
        param_names = list(parameter_ranges.keys())
        param_values = [parameter_ranges[name] for name in param_names]
        
        combinations = list(product(*param_values))
        
        logger.info("grid_search_start",
                   strategy_id=strategy['id'],
                   symbol=symbol,
                   combinations=len(combinations))
        
        best_params = None
        best_score = -999999
        
        for combination in combinations:
            # Create parameter dict
            params = {param_names[i]: combination[i] for i in range(len(param_names))}
            
            # Backtest with these parameters
            result = backtest_parameters(
                strategy=strategy,
                symbol=symbol,
                parameters=params,
                start_date=start_date,
                end_date=end_date
            )
            
            score = result.get('sharpe_ratio', -999)
            
            if score > best_score:
                best_score = score
                best_params = params
        
        logger.info("grid_search_complete",
                   strategy_id=strategy['id'],
                   symbol=symbol,
                   best_score=round(best_score, 3))
        
        return best_params, best_score, len(combinations)
    
    except Exception as e:
        logger.error("grid_search_error", error=str(e))
        # Return current parameters if optimization fails
        return strategy.get('parameters', {}), 0, 0


def backtest_parameters(strategy, symbol, parameters, start_date, end_date):
    """
    Backtest a strategy with specific parameters
    
    Returns: Dict with performance metrics
    """
    try:
        # Simplified backtest - in production, would use full backtest API
        # For now, return mock metrics based on strategy performance history
        
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Get historical performance for this strategy-symbol
                cur.execute("""
                    SELECT 
                        AVG(win_rate) as avg_win_rate,
                        AVG(sharpe_ratio) as avg_sharpe,
                        AVG(profit_factor) as avg_profit_factor
                    FROM strategy_performance
                    WHERE strategy_id = %s AND symbol = %s
                    AND total_trades >= 10
                """, (strategy['id'], symbol))
                
                hist_perf = cur.fetchone()
                
                if hist_perf and hist_perf['avg_sharpe']:
                    # Add some randomness to simulate parameter variation
                    variation = np.random.uniform(0.9, 1.1)
                    
                    return {
                        'sharpe_ratio': float(hist_perf['avg_sharpe']) * variation,
                        'win_rate': float(hist_perf['avg_win_rate'] or 50) * variation,
                        'profit_factor': float(hist_perf['avg_profit_factor'] or 1.0) * variation,
                       'parameters': parameters
                    }
                else:
                    # No history, return baseline
                    return {
                        'sharpe_ratio': 0.5,
                        'win_rate': 50.0,
                        'profit_factor': 1.0,
                        'parameters': parameters
                    }
    
    except Exception as e:
        logger.error("backtest_error", error=str(e))
        return {
            'sharpe_ratio': 0,
            'win_rate': 50,
            'profit_factor': 1.0,
            'parameters': parameters
        }


# Task: Optimize ensemble parameters for all symbols
@celery_app.task(name='optimize_ensemble_parameters')
def optimize_ensemble_parameters():
    """Optimize ensemble parameters for all active symbols"""
    try:
        logger.info("task_started", task="optimize_ensemble_parameters")
        
        symbols = get_active_symbols()
        results = []
        
        # Define parameter ranges to test
        param_ranges = {
            'min_weighted_score': [50, 55, 60, 65, 70, 75],
            'lookback_days': [7, 14, 30],
            'signal_cluster_window_minutes': [3, 5, 10],
            'position_size_pct': [10, 15, 20],
            'stop_loss_pct': [2, 3, 5],
            'take_profit_pct': [6, 9, 12, 15]
        }
        
        # Get date range - last 60 days
        end_date = datetime.now()
        start_date = end_date - timedelta(days=60)
        start_date_str = start_date.strftime('%Y-%m-%d')
        end_date_str = end_date.strftime('%Y-%m-%d')
        
        for symbol in symbols:
            symbol_name = symbol['symbol']
            logger.info("optimizing_symbol", symbol=symbol_name)
            
            best_result = None
            best_score = -999999
            best_params = None
            tested_count = 0
            
            # Test all parameter combinations
            for min_score in param_ranges['min_weighted_score']:
                for lookback in param_ranges['lookback_days']:
                    for cluster_window in param_ranges['signal_cluster_window_minutes']:
                        for pos_size in param_ranges['position_size_pct']:
                            for stop_loss in param_ranges['stop_loss_pct']:
                                for take_profit in param_ranges['take_profit_pct']:
                                    try:
                                        # Call backtest API
                                        request_body = {
                                            'symbol': symbol_name,
                                            'start_date': start_date_str,
                                            'end_date': end_date_str,
                                            'initial_capital': 1000.0,
                                            'min_weighted_score': min_score,
                                            'lookback_days': lookback,
                                            'signal_cluster_window_minutes': cluster_window,
                                            'position_size_pct': pos_size,
                                            'stop_loss_pct': stop_loss,
                                            'take_profit_pct': take_profit
                                        }
                                        
                                        response = requests.post(
                                            f"http://{settings.service_host}:8013/ensemble",
                                            json=request_body,
                                            timeout=60
                                        )
                                        
                                        if response.status_code == 200:
                                            result = response.json()
                                            tested_count += 1
                                            
                                            # Calculate score: Sharpe * 10 + Return + WinRate * 10
                                            sharpe = result.get('sharpe_ratio') or 0
                                            total_return = result.get('total_return_pct', 0)
                                            win_rate = result.get('win_rate', 0)
                                            total_trades = result.get('total_trades', 0)
                                            
                                            # Only consider if we have trades
                                            if total_trades > 0:
                                                score = (sharpe * 10) + total_return + (win_rate * 100 * 0.1)
                                                
                                                if score > best_score:
                                                    best_score = score
                                                    best_result = result
                                                    best_params = {
                                                        'min_weighted_score': min_score,
                                                        'lookback_days': lookback,
                                                        'signal_cluster_window_minutes': cluster_window,
                                                        'position_size_pct': pos_size,
                                                        'stop_loss_pct': stop_loss,
                                                        'take_profit_pct': take_profit
                                                    }
                                    
                                    except Exception as e:
                                        logger.error("backtest_error", symbol=symbol_name, error=str(e))
            
            # Save best parameters to database
            if best_params and best_result:
                try:
                    with get_connection() as conn:
                        with conn.cursor() as cursor:
                            # Create table if not exists
                            cursor.execute("""
                                CREATE TABLE IF NOT EXISTS ensemble_optimized_params (
                                    id SERIAL PRIMARY KEY,
                                    symbol VARCHAR(20) NOT NULL,
                                    min_weighted_score FLOAT NOT NULL,
                                    lookback_days INT NOT NULL,
                                    signal_cluster_window_minutes INT NOT NULL,
                                    position_size_pct FLOAT NOT NULL,
                                    stop_loss_pct FLOAT NOT NULL,
                                    take_profit_pct FLOAT NOT NULL,
                                    backtest_return_pct FLOAT,
                                    backtest_win_rate FLOAT,
                                    backtest_sharpe_ratio FLOAT,
                                    backtest_total_trades INT,
                                    backtest_start_date DATE,
                                    backtest_end_date DATE,
                                    optimization_score FLOAT,
                                    tested_combinations INT,
                                    optimized_at TIMESTAMP DEFAULT NOW(),
                                    UNIQUE(symbol)
                                )
                            """)
                            
                            # Upsert best parameters
                            cursor.execute("""
                                INSERT INTO ensemble_optimized_params (
                                    symbol, min_weighted_score, lookback_days,
                                    signal_cluster_window_minutes, position_size_pct,
                                    stop_loss_pct, take_profit_pct,
                                    backtest_return_pct, backtest_win_rate, backtest_sharpe_ratio,
                                    backtest_total_trades, backtest_start_date, backtest_end_date,
                                    optimization_score, tested_combinations
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (symbol)
                                DO UPDATE SET
                                    min_weighted_score = EXCLUDED.min_weighted_score,
                                    lookback_days = EXCLUDED.lookback_days,
                                    signal_cluster_window_minutes = EXCLUDED.signal_cluster_window_minutes,
                                    position_size_pct = EXCLUDED.position_size_pct,
                                    stop_loss_pct = EXCLUDED.stop_loss_pct,
                                    take_profit_pct = EXCLUDED.take_profit_pct,
                                    backtest_return_pct = EXCLUDED.backtest_return_pct,
                                    backtest_win_rate = EXCLUDED.backtest_win_rate,
                                    backtest_sharpe_ratio = EXCLUDED.backtest_sharpe_ratio,
                                    backtest_total_trades = EXCLUDED.backtest_total_trades,
                                    backtest_start_date = EXCLUDED.backtest_start_date,
                                    backtest_end_date = EXCLUDED.backtest_end_date,
                                    optimization_score = EXCLUDED.optimization_score,
                                    tested_combinations = EXCLUDED.tested_combinations,
                                    optimized_at = NOW()
                            """, (
                                symbol_name,
                                best_params['min_weighted_score'],
                                best_params['lookback_days'],
                                best_params['signal_cluster_window_minutes'],
                                best_params['position_size_pct'],
                                best_params['stop_loss_pct'],
                                best_params['take_profit_pct'],
                                best_result.get('total_return_pct'),
                                best_result.get('win_rate'),
                                best_result.get('sharpe_ratio'),
                                best_result.get('total_trades'),
                                start_date_str,
                                end_date_str,
                                best_score,
                                tested_count
                            ))
                            conn.commit()
                            
                            logger.info("optimization_saved",
                                       symbol=symbol_name,
                                       score=best_score,
                                       return_pct=best_result.get('total_return_pct'),
                                       trades=best_result.get('total_trades'),
                                       tested=tested_count)
                            
                            results.append({
                                'symbol': symbol_name,
                                'status': 'optimized',
                                'score': best_score,
                                'params': best_params,
                                'result': {
                                    'return_pct': best_result.get('total_return_pct'),
                                    'win_rate': best_result.get('win_rate'),
                                    'sharpe': best_result.get('sharpe_ratio'),
                                    'trades': best_result.get('total_trades')
                                },
                                'tested_combinations': tested_count
                            })
                
                except Exception as e:
                    logger.error("save_optimization_error", symbol=symbol_name, error=str(e))
                    results.append({
                        'symbol': symbol_name,
                        'status': 'error',
                        'error': str(e)
                    })
            else:
                logger.warning("no_profitable_combination", symbol=symbol_name, tested=tested_count)
                results.append({
                    'symbol': symbol_name,
                    'status': 'no_profitable_params',
                    'tested_combinations': tested_count
                })
        
        logger.info("task_completed", task="optimize_ensemble_parameters", results=results)
        return results
    
    except Exception as e:
        logger.error("task_error", task="optimize_ensemble_parameters", error=str(e))
        return {'status': 'error', 'message': str(e)}


# ==================== SYSTEM MODE CONFIGURATION ====================

def get_system_mode():
    """Get current system mode from database (startup or production)"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT config_value 
                    FROM system_config 
                    WHERE config_key = 'system_mode'
                """)
                result = cur.fetchone()
                if result:
                    # psycopg2 DictCursor auto-deserializes JSONB
                    mode = result['config_value']
                    if isinstance(mode, str):
                        return mode if mode in ['startup', 'production'] else 'production'
                    # If still JSON string, parse it
                    import json
                    mode = json.loads(mode)
                    return mode if mode in ['startup', 'production'] else 'production'
    except:
        pass
    return 'production'  # Default to production if config not found

# Get current system mode
SYSTEM_MODE = get_system_mode()
logger.info("system_mode_loaded", mode=SYSTEM_MODE)

# Task: Reset Daily Trading Stats (Midnight Mountain Time)
@celery_app.task(name='reset_daily_trading_stats')
def reset_daily_trading_stats():
    """
    Reset daily trading stats at midnight Mountain Time
    - Archive yesterday's stats to daily_trading_stats table
    - Clear emergency stop if triggered by daily limits
    - Reset alerts_sent_today counter
    """
    try:
        logger.info("task_started", task="reset_daily_trading_stats")
        
        yesterday = datetime.utcnow().date() - timedelta(days=1)
        today = datetime.utcnow().date()
        
        modes = ['paper', 'live']
        
        for mode in modes:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    # Calculate yesterday's stats
                    cur.execute("""
                        SELECT 
                            COUNT(*) FILTER (WHERE status = 'closed') as trades_executed,
                            COUNT(*) FILTER (WHERE status = 'open') as positions_opened,
                            COUNT(*) FILTER (WHERE status = 'closed') as positions_closed,
                            COUNT(*) FILTER (WHERE trade_result = 'win') as winning_trades,
                            COUNT(*) FILTER (WHERE trade_result = 'loss') as losing_trades,
                            COALESCE(SUM(realized_pnl) FILTER (WHERE status = 'closed'), 0) as total_pnl
                        FROM positions
                        WHERE mode = %s 
                        AND DATE(entry_time) = %s
                        AND position_type = 'ensemble'
                    """, (mode, yesterday))
                    
                    stats = cur.fetchone()
                    
                    # Insert/update daily_trading_stats
                    cur.execute("""
                        INSERT INTO daily_trading_stats 
                        (date, mode, total_pnl, trades_executed, positions_opened, 
                         positions_closed, winning_trades, losing_trades, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                        ON CONFLICT (date, mode)
                        DO UPDATE SET
                            total_pnl = EXCLUDED.total_pnl,
                            trades_executed = EXCLUDED.trades_executed,
                            positions_opened = EXCLUDED.positions_opened,
                            positions_closed = EXCLUDED.positions_closed,
                            winning_trades = EXCLUDED.winning_trades,
                            losing_trades = EXCLUDED.losing_trades,
                            updated_at = NOW()
                    """, (yesterday, mode, stats['total_pnl'], stats['trades_executed'],
                          stats['positions_opened'], stats['positions_closed'],
                          stats['winning_trades'], stats['losing_trades']))
                    
                    # Clear emergency stop if it was triggered by daily limits
                    cur.execute("""
                        UPDATE trading_policies
                        SET emergency_stop = false,
                            emergency_stop_reason = NULL,
                            emergency_stop_time = NULL,
                            alerts_sent_today = 0,
                            last_alert_reset = NOW()
                        WHERE mode = %s
                        AND emergency_stop = true
                        AND emergency_stop_reason IN ('Daily loss limit reached', 'Ensemble daily loss limit')
                    """, (mode,))
                    
                    cleared = cur.rowcount
                    
                    conn.commit()
                    
                    logger.info("daily_stats_reset", 
                               mode=mode, 
                               date=yesterday,
                               trades=stats['trades_executed'],
                               pnl=float(stats['total_pnl']),
                               wins=stats['winning_trades'],
                               losses=stats['losing_trades'],
                               emergency_stop_cleared=cleared > 0)
        
        return {
            'status': 'success',
            'date': str(yesterday),
            'message': 'Daily trading stats reset complete'
        }
    
    except Exception as e:
        logger.error("task_error", task="reset_daily_trading_stats", error=str(e))
        return {'status': 'error', 'message': str(e)}


# Task: Consensus-Based Ensemble Trading (NEW)
@celery_app.task(name='execute_consensus_ensemble_trades')
def execute_consensus_ensemble_trades():
    """
    Execute TRUE ensemble trades using consensus voting system
    
    New Approach (API-based):
    1. Fetches consensus signals from Signal API
    2. Signal API groups signals by symbol (requires 2+ strategies agreeing)
    3. AI Agent votes (analyzes sentiment + technicals) - weighted 1.5x
    4. News Sentiment votes (web crawl + AI analysis) - weighted 1.0x  
    5. Combines all votes weighted by strategy performance
    6. Requires 60% supermajority to return signal
    7. We execute the trades that pass consensus
    
    This replaces the simple "top signal" approach with democratic consensus.
    """
    try:
        logger.info("task_started", task="execute_consensus_ensemble_trades")
        
        # Fetch consensus signals from Signal API
        try:
            response = requests.get(
                f"http://{settings.service_host}:{settings.port_signal_api}/signals/consensus",
                params={
                    'min_strategies': 2,  # Need at least 2 strategies agreeing
                    'min_quality': 70,  # Minimum quality score (was causing churn with low 60-65 signals)
                    'supermajority_pct': 60.0,  # 60% weighted vote required
                    'include_ai_vote': True,  # Include AI voting
                    'include_sentiment': True,  # Include sentiment analysis
                    'limit': 5  # Max 5 signals per cycle
                },
                timeout=30  # Longer timeout for AI/sentiment calls
            )
            
            if response.status_code != 200:
                logger.error("consensus_fetch_failed", error=response.text)
                return {'status': 'error', 'reason': 'failed_to_fetch_consensus_signals'}
            
            data = response.json()
            consensus_signals = data.get('consensus_signals', [])
            
            if not consensus_signals:
                logger.info("no_consensus_signals",
                           candidates=data.get('candidates_evaluated', 0),
                           message="No signals achieved supermajority")
                return {'status': 'success', 'decisions': 0, 'trades': 0, 'reason': 'no_consensus'}
            
            logger.info("consensus_signals_received",
                       count=len(consensus_signals),
                       candidates_evaluated=data.get('candidates_evaluated', 0))
            
        except Exception as e:
            logger.error("consensus_api_error", error=str(e))
            return {'status': 'error', 'reason': f'consensus_api_error: {str(e)}'}
        
        # Get available capital for position sizing
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT available_capital FROM portfolio_snapshots
                    WHERE mode = 'paper'
                    ORDER BY timestamp DESC
                    LIMIT 1
                """)
                snapshot = cur.fetchone()
                available_capital = float(snapshot['available_capital']) if snapshot else float(settings.paper_starting_capital)
        
        logger.info("consensus_capital_status", available=available_capital)
        
        # Execute each consensus signal via Trading API
        trades_executed = 0
        trades_failed = 0
        
        for signal in consensus_signals:
            try:
                logger.info("executing_consensus_trade",
                           symbol=signal['symbol'],
                           signal_type=signal['signal_type'],
                           consensus_pct=signal['consensus_pct'],
                           strategy_count=signal['strategy_count'])
                
                # CRITICAL: Handle BUY vs SELL differently
                signal_type = signal['signal_type'].upper()
                
                if signal_type == 'SELL':
                    # SELL means close existing position, not open short
                    # Find open ensemble position for this symbol
                    with get_connection() as conn:
                        with conn.cursor() as cur:
                            cur.execute("""
                                SELECT 
                                    id, 
                                    entry_time,
                                    EXTRACT(EPOCH FROM (NOW() - entry_time))/60 as hold_minutes
                                FROM positions
                                WHERE symbol = %s
                                AND status = 'open'
                                AND mode = 'paper'
                                AND position_type = 'ensemble'
                                LIMIT 1
                            """, (signal['symbol'],))
                            
                            existing_position = cur.fetchone()
                    
                    if not existing_position:
                        logger.warning("sell_signal_no_position",
                                     symbol=signal['symbol'],
                                     reason="Cannot sell - no open ensemble position")
                        trades_failed += 1
                        continue
                    
                    position_id_to_close = existing_position['id']
                    
                    # Call Trading API /close endpoint
                    close_payload = {
                        'position_id': position_id_to_close,
                        'mode': 'paper',
                        'reason': f"consensus_sell_{signal['consensus_pct']:.1f}pct"
                    }
                    
                    trading_response = requests.post(
                        f"http://{settings.service_host}:{settings.port_trading_api}/close",
                        json=close_payload,
                        timeout=10
                    )
                    
                    if trading_response.status_code == 200:
                        result = trading_response.json()
                        position_close = result.get('position_close', {})
                        trades_executed += 1
                        
                        logger.warning("CONSENSUS_SELL_EXECUTED",
                                     symbol=signal['symbol'],
                                     position_id=position_id_to_close,
                                     consensus_pct=signal['consensus_pct'],
                                     pnl=position_close.get('pnl'),
                                     pnl_pct=position_close.get('pnl_pct'))
                        
                        position_id = position_id_to_close
                    else:
                        trades_failed += 1
                        logger.error("consensus_sell_failed",
                                   symbol=signal['symbol'],
                                   position_id=position_id_to_close,
                                   error=trading_response.text)
                        continue
                
                else:  # BUY signal
                    # CRITICAL: Check if we already have an open position for this symbol
                    # Prevent opening duplicate positions for the same symbol
                    with get_connection() as conn:
                        with conn.cursor() as cur:
                            cur.execute("""
                                SELECT COUNT(*) as count
                                FROM positions
                                WHERE symbol = %s
                                AND status = 'open'
                                AND mode = 'paper'
                                AND position_type = 'ensemble'
                            """, (signal['symbol'],))
                            
                            existing_count = cur.fetchone()['count']
                    
                    if existing_count > 0:
                        logger.warning("buy_signal_position_exists",
                                     symbol=signal['symbol'],
                                     existing_positions=existing_count,
                                     reason=f"Cannot open new position - {existing_count} open position(s) already exist")
                        trades_failed += 1
                        continue
                    
                    # Calculate position size (default $100 per trade, can scale with consensus strength)
                    base_position_value = 100.0
                    
                    # Boost for high consensus (75%+)
                    if signal['consensus_pct'] >= 75:
                        base_position_value = 150.0
                    
                    # Cap at available capital minus reserve
                    position_value = min(base_position_value, available_capital - 50)
                    
                    if position_value < 50:
                        logger.warning("insufficient_capital_for_consensus",
                                     available=available_capital,
                                     needed=base_position_value)
                        trades_failed += 1
                        continue
                    
                    # Calculate amount
                    amount = position_value / float(signal['price_at_signal'])
                    
                    # Get first signal ID
                    signal_id = signal['signal_ids'][0] if signal['signal_ids'] else None
                    
                    # Call Trading API to execute BUY trade
                    trade_payload = {
                        'symbol': signal['symbol'],
                        'side': 'buy',
                        'amount': float(amount),
                        'mode': 'paper',
                        'signal_id': signal_id,
                        'stop_loss_pct': 2.0,
                        'take_profit_pct': max(float(signal.get('projected_return_pct', 5.0)), 5.0),
                        'position_type': 'ensemble'
                    }
                    
                    trading_response = requests.post(
                        f"http://{settings.service_host}:{settings.port_trading_api}/execute",
                        json=trade_payload,
                        timeout=10
                    )
                    
                    if trading_response.status_code == 200:
                        result = trading_response.json()
                        trade_result = result.get('trade', {})
                        position_id = trade_result.get('position_id')
                        trades_executed += 1
                        available_capital -= position_value  # Update available for next signal
                        
                        logger.warning("CONSENSUS_BUY_EXECUTED",
                                     symbol=signal['symbol'],
                                     consensus_pct=signal['consensus_pct'],
                                     position_id=position_id,
                                     value=position_value)
                    else:
                        trades_failed += 1
                        logger.error("consensus_buy_failed",
                                   symbol=signal['symbol'],
                                   error=trading_response.text)
                        continue
                
                # Record consensus decision with position link (both BUY and SELL)
                try:
                    record_response = requests.post(
                        f"http://{settings.service_host}:{settings.port_signal_api}/consensus/record",
                        json={
                            **signal,
                            'approved': True,
                            'executed': True,
                            'position_id': position_id
                        },
                        timeout=5
                    )
                    if record_response.status_code == 200:
                        decision_id = record_response.json().get('decision_id')
                        logger.info("consensus_decision_recorded", decision_id=decision_id, position_id=position_id)
                except Exception as e:
                    logger.warning("decision_record_failed", error=str(e))
                    
            except Exception as e:
                trades_failed += 1
                logger.error("trade_execution_error",
                           symbol=signal['symbol'],
                           error=str(e))
        
        logger.info("consensus_ensemble_complete",
                   signals_received=len(consensus_signals),
                   trades_executed=trades_executed,
                   trades_failed=trades_failed)
        
        return {
            'status': 'success',
            'consensus_signals': len(consensus_signals),
            'trades_executed': trades_executed,
            'trades_failed': trades_failed
        }
        
    except Exception as e:
        logger.error("task_error", task="execute_consensus_ensemble_trades", error=str(e))
        import traceback
        logger.error("traceback", trace=traceback.format_exc())
        return {'status': 'error', 'message': str(e)}


# ==================== LAYER ENHANCEMENT TASKS ====================

# Import layer enhancement functions
from celery_worker.layer_tasks import (
    process_optimization_queue,
    ai_analyze_system_health,
    ai_recommend_strategy_weights,
    record_daily_performance,
    adjust_performance_goals
)

@celery_app.task(name='process_optimization_queue')
def process_optimization_queue_task():
    """Process pending strategy-symbol optimizations (Layer 2)"""
    return process_optimization_queue(max_concurrent=50)

@celery_app.task(name='ai_analyze_system_health')
def ai_analyze_system_health_task():
    """AI analyzes system health and recommends improvements (Layer 5)"""
    return ai_analyze_system_health()

@celery_app.task(name='ai_recommend_strategy_weights')
def ai_recommend_strategy_weights_task():
    """AI recommends optimal strategy weights (Layer 5)"""
    return ai_recommend_strategy_weights()

@celery_app.task(name='record_daily_performance')
def record_daily_performance_task():
    """Record yesterday's performance and check goals (Layer 8)"""
    return record_daily_performance()

@celery_app.task(name='adjust_performance_goals')
def adjust_performance_goals_task():
    """Adaptively adjust profit targets based on success rate (Layer 8)"""
    return adjust_performance_goals()


# ==================== PHASE 8 VISION TASKS ====================

@celery_app.task(name='discover_symbols_and_strategies')
def discover_symbols_and_strategies():
    """
    Daily task: AI discovers new symbols + generates strategies for each.
    1. Calls /discover-symbols-ai to find new trading candidates
    2. Calls /symbols/add-with-backfill to backfill 180 days of history
    3. Calls /generate-strategies to create strategies for each new symbol
    4. Assigns all strategies to the new symbol via Ensemble API
    """
    try:
        logger.info("task_started", task="discover_symbols_and_strategies")
        ai_base = f"http://{settings.service_host}:{settings.port_ai_api}"
        ohlcv_base = f"http://{settings.service_host}:{settings.port_ohlcv_api}"
        ensemble_base = f"http://{settings.service_host}:{settings.port_ensemble_api}"

        # Step 1: AI symbol discovery
        resp = requests.post(f"{ai_base}/discover-symbols-ai",
                             json={"min_volume_usd": 500_000, "max_results": 15},
                             timeout=60)
        if resp.status_code != 200:
            logger.warning("discover_symbols_failed", status=resp.status_code)
            return {"status": "error", "step": "discover"}

        discovered = resp.json().get("symbols", [])
        logger.info("symbols_discovered", count=len(discovered))

        results = []
        for sym_info in discovered:
            symbol = sym_info.get("symbol") if isinstance(sym_info, dict) else sym_info
            try:
                # Step 2: Add symbol with 180-day backfill
                add_resp = requests.post(
                    f"{ohlcv_base}/symbols/add-with-backfill",
                    json={"symbol": symbol, "name": symbol, "backfill_days": 180},
                    timeout=30,
                )
                backfill_ok = add_resp.status_code == 200

                # Step 3: Generate strategies
                gen_resp = requests.post(
                    f"{ai_base}/generate-strategies",
                    json={"symbol": symbol, "num_strategies": 8},
                    timeout=60,
                )
                strategies_ok = gen_resp.status_code == 200

                # Step 4: Assign all strategies to new symbol
                assign_resp = requests.post(
                    f"{ensemble_base}/assign-all-strategies/{symbol}",
                    timeout=30,
                )
                assign_ok = assign_resp.status_code == 200

                results.append({
                    "symbol": symbol,
                    "backfill": backfill_ok,
                    "strategies_generated": strategies_ok,
                    "strategies_assigned": assign_ok,
                })
                logger.info("symbol_setup_complete", symbol=symbol,
                            backfill=backfill_ok, strategies=strategies_ok)

            except Exception as sym_err:
                logger.warning("symbol_setup_error", symbol=symbol, error=str(sym_err))
                results.append({"symbol": symbol, "error": str(sym_err)})

        return {"status": "success", "discovered": len(discovered), "results": results}

    except Exception as e:
        logger.error("task_error", task="discover_symbols_and_strategies", error=str(e))
        return {"status": "error", "message": str(e)}


@celery_app.task(name='rank_strategies_per_symbol')
def rank_strategies_per_symbol():
    """
    Every 4 hours: Recompute trust_factor rankings for all active symbols.
    trust_factor = PF × (WR/100) × (1 - fee_drag)
    """
    try:
        logger.info("task_started", task="rank_strategies_per_symbol")
        ensemble_base = f"http://{settings.service_host}:{settings.port_ensemble_api}"

        symbols = get_active_symbols()
        updated = 0
        for sym in symbols:
            symbol = sym['symbol']
            try:
                resp = requests.post(f"{ensemble_base}/rerank/{symbol}", timeout=30)
                if resp.status_code == 200:
                    updated += 1
            except Exception as sym_err:
                logger.warning("rerank_symbol_error", symbol=symbol, error=str(sym_err))

        logger.info("rank_strategies_complete", symbols_updated=updated)
        return {"status": "success", "symbols_updated": updated}

    except Exception as e:
        logger.error("task_error", task="rank_strategies_per_symbol", error=str(e))
        return {"status": "error", "message": str(e)}


@celery_app.task(name='monitor_profitability')
def monitor_profitability():
    """
    Daily task at 2:30 AM UTC: Evaluate yesterday's P&L, update streaks,
    and trigger paper→live promotion or live→stop+reevaluate demotion.

    Rules:
    - profitable_days_streak >= days_to_promote → switch mode to 'live'
    - unprofitable_days_streak >= days_to_demote → switch mode to 'paper' + trigger reevaluation
    """
    try:
        logger.info("task_started", task="monitor_profitability")

        with get_connection() as conn:
            with conn.cursor() as cur:
                # Yesterday's P&L summary
                cur.execute("""
                    SELECT COALESCE(SUM(realized_pnl), 0) AS total_pnl,
                           COUNT(*) AS trade_count
                    FROM positions
                    WHERE DATE(closed_at) = CURRENT_DATE - INTERVAL '1 day'
                      AND status = 'closed'
                """)
                row = cur.fetchone()
                total_pnl = float(row['total_pnl'] or 0)
                trade_count = int(row['trade_count'] or 0)

                # Yesterday's capital base for pct calculation
                cur.execute("""
                    SELECT total_capital FROM portfolio_snapshots
                    WHERE DATE(snapshot_time) = CURRENT_DATE - INTERVAL '1 day'
                    ORDER BY snapshot_time DESC LIMIT 1
                """)
                snap = cur.fetchone()
                capital = float(snap['total_capital']) if snap else settings.paper_starting_capital
                total_pnl_pct = (total_pnl / capital * 100) if capital > 0 else 0.0
                is_profitable = total_pnl > 0

                # Log to daily_profitability_log
                cur.execute("""
                    SELECT mode FROM trading_mode_config
                    ORDER BY updated_at DESC LIMIT 1
                """)
                mode_row = cur.fetchone()
                current_mode = mode_row['mode'] if mode_row else 'paper'

                cur.execute("""
                    INSERT INTO daily_profitability_log
                        (date, mode, total_pnl, total_pnl_pct, trades_count, winning_trades, is_profitable)
                    SELECT
                        CURRENT_DATE - INTERVAL '1 day',
                        %s, %s, %s, %s,
                        COUNT(*) FILTER (WHERE realized_pnl > 0),
                        %s
                    FROM positions
                    WHERE DATE(closed_at) = CURRENT_DATE - INTERVAL '1 day'
                      AND status = 'closed'
                    ON CONFLICT (date, mode) DO UPDATE SET
                        total_pnl      = EXCLUDED.total_pnl,
                        total_pnl_pct  = EXCLUDED.total_pnl_pct,
                        trades_count   = EXCLUDED.trades_count,
                        winning_trades = EXCLUDED.winning_trades,
                        is_profitable  = EXCLUDED.is_profitable
                """, (current_mode, total_pnl, total_pnl_pct, trade_count, is_profitable))

                # Update streaks in trading_mode_config
                if is_profitable:
                    cur.execute("""
                        UPDATE trading_mode_config SET
                            profitable_days_streak   = profitable_days_streak + 1,
                            unprofitable_days_streak = 0,
                            updated_at = NOW()
                    """)
                else:
                    cur.execute("""
                        UPDATE trading_mode_config SET
                            unprofitable_days_streak = unprofitable_days_streak + 1,
                            profitable_days_streak   = 0,
                            updated_at = NOW()
                    """)

                # Read updated streaks + thresholds
                cur.execute("""
                    SELECT mode, profitable_days_streak, unprofitable_days_streak,
                           days_to_promote, days_to_demote
                    FROM trading_mode_config
                    ORDER BY updated_at DESC LIMIT 1
                """)
                cfg = cur.fetchone()
                conn.commit()

        if not cfg:
            return {"status": "no_config", "pnl": total_pnl}

        mode = cfg['mode']
        profit_streak = cfg['profitable_days_streak']
        loss_streak = cfg['unprofitable_days_streak']
        to_promote = cfg['days_to_promote']
        to_demote = cfg['days_to_demote']
        action = "none"

        # Paper → Live promotion
        if mode == 'paper' and profit_streak >= to_promote:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE trading_mode_config SET mode = 'live', updated_at = NOW()
                    """)
                    conn.commit()
            action = "promoted_to_live"
            logger.info("trading_mode_promoted", mode="live", streak=profit_streak)

        # Live → Paper demotion + reevaluation trigger
        elif mode == 'live' and loss_streak >= to_demote:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE trading_mode_config SET
                            mode = 'paper',
                            reevaluation_triggered = true,
                            updated_at = NOW()
                    """)
                    conn.commit()
            action = "demoted_to_paper_reevaluate"
            # Also trigger reevaluate task immediately
            reevaluate_strategies.delay()
            logger.warning("trading_mode_demoted", mode="paper", streak=loss_streak)

        logger.info("profitability_monitored",
                    pnl=total_pnl, pnl_pct=total_pnl_pct,
                    is_profitable=is_profitable, mode=mode, action=action)

        return {
            "status": "success",
            "date": (datetime.utcnow() - timedelta(days=1)).date().isoformat(),
            "total_pnl": total_pnl,
            "total_pnl_pct": round(total_pnl_pct, 4),
            "is_profitable": is_profitable,
            "mode": mode,
            "profit_streak": profit_streak,
            "loss_streak": loss_streak,
            "action": action,
        }

    except Exception as e:
        logger.error("task_error", task="monitor_profitability", error=str(e))
        return {"status": "error", "message": str(e)}


@celery_app.task(name='generate_daily_report')
def generate_daily_report():
    """
    Nightly accountability snapshot: aggregates daily P&L into daily_profitability_log
    for each mode (paper/live) if no row already exists for yesterday.
    Runs at 3:00 AM UTC.
    """
    from datetime import date, timedelta

    yesterday = date.today() - timedelta(days=1)
    logger.info("task_started", task="generate_daily_report", date=str(yesterday))
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Get current modes from trading_mode_config
                cur.execute("SELECT DISTINCT mode FROM trading_mode_config")
                active_modes = [r["mode"] for r in cur.fetchall() if r["mode"] in ("paper", "live")]

                inserted = 0
                for mode in active_modes:
                    # Skip if row already exists
                    cur.execute("""
                        SELECT 1 FROM daily_profitability_log
                        WHERE date = %s AND mode = %s
                    """, (yesterday, mode))
                    if cur.fetchone():
                        continue

                    # Compute from positions closed that day for this mode
                    cur.execute("""
                        SELECT
                            COUNT(*) AS trades,
                            SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) AS wins,
                            COALESCE(SUM(realized_pnl), 0) AS pnl
                        FROM positions
                        WHERE mode = %s
                          AND status = 'closed'
                          AND DATE(exit_time) = %s
                    """, (mode, yesterday))
                    row = cur.fetchone()
                    trades = row["trades"] or 0
                    wins = row["wins"] or 0
                    pnl = float(row["pnl"]) if row["pnl"] else 0.0

                    cur.execute("""
                        INSERT INTO daily_profitability_log
                            (date, mode, total_pnl, is_profitable, trades_count, winning_trades)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (date, mode) DO NOTHING
                    """, (yesterday, mode, pnl, pnl > 0, trades, wins))
                    inserted += 1

                conn.commit()

        logger.info("generate_daily_report_complete",
                    date=str(yesterday),
                    modes_backfilled=inserted)
        return {
            "status": "ok",
            "date": str(yesterday),
            "modes_backfilled": inserted,
        }
    except Exception as e:
        logger.error("task_error", task="generate_daily_report", error=str(e))
        return {"status": "error", "message": str(e)}


@celery_app.task(name='daily_refine_strategies')
def daily_refine_strategies():
    """
    Daily refinement pass (4 AM UTC).

    1. Re-runs zero-fee backtests for all active symbol_strategies
       — fee_mode='zero' reveals true edge without fee drag killing results
    2. Updates trust_factor = PF × (WR/100), profit_factor, win_rate
    3. Prunes strategies where trust_factor < 0.10 AND total_trades < 5
    4. Re-ranks via ensemble_api /rerank
    5. Logs summary

    Uses fee_mode='zero' intentionally — fees are applied at execution time
    by the ensemble layer, not during individual strategy evaluation.
    """
    try:
        logger.info("task_started", task="daily_refine_strategies")
        backtest_base = f"http://{settings.service_host}:{settings.port_backtest_api}"
        ensemble_base = f"http://{settings.service_host}:{settings.port_ensemble_api}"

        end_date   = datetime.utcnow().strftime("%Y-%m-%d")
        start_date = (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d")

        # Fetch all active symbol_strategy pairs
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT ss.id, ss.symbol, ss.strategy_id,
                           ss.trust_factor, ss.total_trades
                    FROM symbol_strategies ss
                    WHERE ss.status = 'active'
                    ORDER BY ss.symbol, ss.trust_factor DESC
                """)
                pairs = cur.fetchall()

        logger.info("refine_pairs_loaded", count=len(pairs))

        updated = pruned = errors = 0

        for pair in pairs:
            sym     = pair["symbol"]
            strat_id = pair["strategy_id"]
            try:
                resp = requests.post(
                    f"{backtest_base}/run",
                    json={
                        "strategy_id": strat_id,
                        "symbol":      sym,
                        "start_date":  start_date,
                        "end_date":    end_date,
                        "fee_mode":    "zero",
                    },
                    timeout=60,
                )
                if resp.status_code != 200:
                    errors += 1
                    continue

                r          = resp.json()
                pf         = float(r.get("total_return_pct", 0)) / 100 + 1.0
                wr         = float(r.get("win_rate", 0))
                n_trades   = int(r.get("total_trades", 0))
                pf_direct  = r.get("profit_factor")
                if pf_direct is not None:
                    pf = float(pf_direct)
                trust      = round(pf * (wr / 100.0), 6)

                with get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            UPDATE symbol_strategies
                            SET trust_factor  = %s,
                                profit_factor = %s,
                                win_rate      = %s,
                                total_trades  = %s,
                                last_backtest_at = NOW(),
                                updated_at    = NOW()
                            WHERE symbol = %s AND strategy_id = %s
                        """, (trust, pf, wr, n_trades, sym, strat_id))
                        conn.commit()
                updated += 1

                # Prune immediately if below threshold
                if trust < 0.10 and n_trades < 5:
                    with get_connection() as conn:
                        with conn.cursor() as cur:
                            cur.execute("""
                                UPDATE symbol_strategies
                                SET status = 'inactive', updated_at = NOW()
                                WHERE symbol = %s AND strategy_id = %s
                            """, (sym, strat_id))
                            conn.commit()
                    logger.info("strategy_pruned",
                                symbol=sym, strategy_id=strat_id,
                                trust=trust, trades=n_trades)
                    pruned += 1

            except Exception as pair_err:
                errors += 1
                logger.warning("refine_pair_error",
                               symbol=sym, strategy_id=strat_id,
                               error=str(pair_err))

        # Re-rank all symbols after updates
        symbols_to_rerank = list({p["symbol"] for p in pairs})
        for sym in symbols_to_rerank:
            try:
                requests.post(f"{ensemble_base}/rerank/{sym}", timeout=15)
            except Exception:
                pass

        logger.info("daily_refine_complete",
                    pairs_processed=len(pairs),
                    updated=updated, pruned=pruned, errors=errors)
        return {
            "status": "success",
            "pairs_processed": len(pairs),
            "updated": updated,
            "pruned": pruned,
            "errors": errors,
        }

    except Exception as e:
        logger.error("task_error", task="daily_refine_strategies", error=str(e))
        return {"status": "error", "message": str(e)}


@celery_app.task(name='process_symbol')
def process_symbol(symbol: str, fee_mode: str = "zero"):
    """
    Full evaluation cycle for a single symbol — the core automated loop:

    1. Backfill 180 days of 1m candles (idempotent — skips if recent)
    2. Assign all enabled strategies to symbol via ensemble_api
    3. Run zero-fee backtests for top 10 unbacktested strategies
    4. Rerank symbol_strategies by trust_factor
    5. Generate fresh signals via signal_api
    6. Run ensemble vote → BUY / SELL / HOLD decision
    7. Execute paper trade if BUY decision passes guardrails
    8. Log outcome to cycle_log table (created inline if absent)

    Designed to run every 5 minutes per symbol via beat schedule.
    Also triggered on-demand by /force-refresh/{symbol} in portfolio_api.
    """
    try:
        logger.info("process_symbol_start", symbol=symbol)
        host       = settings.service_host
        ohlcv_base = f"http://{host}:{settings.port_ohlcv_api}"
        ens_base   = f"http://{host}:{settings.port_ensemble_api}"
        bt_base    = f"http://{host}:{settings.port_backtest_api}"
        sig_base   = f"http://{host}:{settings.port_signal_api}"
        trade_base = f"http://{host}:{settings.port_trading_api}"
        steps      = []

        # ── Step 1: Backfill (only if < 1000 recent 1m candles) ─────────────
        try:
            br = requests.post(
                f"{ohlcv_base}/backfill/{symbol}",
                json={"days": 180},
                timeout=30,
            )
            steps.append({"step": "backfill", "status": "ok" if br.status_code == 200 else "skip", "code": br.status_code})
        except Exception as e:
            steps.append({"step": "backfill", "status": "error", "error": str(e)})

        # ── Step 2: Assign all enabled strategies ────────────────────────────
        try:
            ar = requests.post(f"{ens_base}/assign-all-strategies/{symbol}", timeout=30)
            assigned = ar.json().get("assigned", 0) if ar.status_code == 200 else 0
            steps.append({"step": "assign_strategies", "status": "ok", "assigned": assigned})
        except Exception as e:
            steps.append({"step": "assign_strategies", "status": "error", "error": str(e)})
            assigned = 0

        # ── Step 3: Backtest top strategies that lack recent results ─────────
        bt_count = 0
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT ss.strategy_id, s.name
                        FROM symbol_strategies ss
                        JOIN strategies s ON s.id = ss.strategy_id
                        WHERE ss.symbol = %s
                          AND ss.status = 'active'
                          AND (ss.last_backtest_at IS NULL
                               OR ss.last_backtest_at < NOW() - INTERVAL '24 hours')
                        ORDER BY ss.trust_factor DESC NULLS LAST
                        LIMIT 10
                    """, (symbol,))
                    strats_to_test = cur.fetchall()

            for row in strats_to_test:
                try:
                    resp = requests.post(
                        f"{bt_base}/run",
                        json={
                            "symbol": symbol,
                            "strategy_id": row["strategy_id"],
                            "fee_mode": fee_mode,
                            "days": 90,
                        },
                        timeout=60,
                    )
                    if resp.status_code == 200:
                        bt_count += 1
                except Exception:
                    pass
            steps.append({"step": "backtest", "status": "ok", "count": bt_count})
        except Exception as e:
            steps.append({"step": "backtest", "status": "error", "error": str(e)})

        # ── Step 4: Rerank ───────────────────────────────────────────────────
        try:
            rr = requests.post(f"{ens_base}/rerank/{symbol}", timeout=15)
            steps.append({"step": "rerank", "status": "ok" if rr.status_code == 200 else "error"})
        except Exception as e:
            steps.append({"step": "rerank", "status": "error", "error": str(e)})

        # ── Step 5: Generate signals ─────────────────────────────────────────
        try:
            sgr = requests.post(
                f"{sig_base}/signals/generate",
                params={"symbol": symbol, "force": "true"},
                timeout=30,
            )
            sig_count = sgr.json().get("signals_generated", 0) if sgr.status_code == 200 else 0
            steps.append({"step": "generate_signals", "status": "ok", "count": sig_count})
        except Exception as e:
            steps.append({"step": "generate_signals", "status": "error", "error": str(e)})

        # ── Step 6: Ensemble vote ────────────────────────────────────────────
        decision = "HOLD"
        confidence = 0.0
        try:
            er = requests.post(
                f"{ens_base}/decide",
                json={"symbol": symbol, "mode": "paper"},
                timeout=30,
            )
            if er.status_code == 200:
                ed = er.json()
                decision   = ed.get("decision", "HOLD")
                confidence = ed.get("confidence", 0.0)
                steps.append({"step": "ensemble_vote", "status": "ok", "decision": decision, "confidence": confidence})
            else:
                steps.append({"step": "ensemble_vote", "status": "error", "code": er.status_code})
        except Exception as e:
            steps.append({"step": "ensemble_vote", "status": "error", "error": str(e)})

        # ── Step 7: Execute paper trade if BUY with sufficient confidence ────
        trade_id = None
        if decision == "BUY" and confidence >= 0.55:
            try:
                # Compute size: 5% of available paper capital
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            SELECT available_capital FROM portfolio_snapshots
                            WHERE mode = 'paper' ORDER BY timestamp DESC LIMIT 1
                        """)
                        snap = cur.fetchone()
                        available = float(snap["available_capital"]) if snap else 100.0
                        cur.execute("""
                            SELECT close FROM ohlcv_1m
                            WHERE symbol = %s ORDER BY time DESC LIMIT 1
                        """, (symbol,))
                        price_row = cur.fetchone()
                        current_px = float(price_row["close"]) if price_row else None

                if not current_px:
                    steps.append({"step": "execute_trade", "status": "skip", "reason": "no price data"})
                else:
                    alloc_capital = min(available * 0.05, available)
                    amount = alloc_capital / current_px
                    tr = requests.post(
                        f"{trade_base}/execute",
                        json={
                            "symbol": symbol,
                            "side":   "buy",
                            "amount": round(amount, 8),
                            "mode":   "paper",
                            "position_type": "ensemble",
                            "stop_loss_pct": 3.0,
                            "take_profit_pct": 6.0,
                        },
                        timeout=30,
                    )
                    if tr.status_code == 200:
                        trade_id = tr.json().get("trade", {}).get("position_id")
                        steps.append({"step": "execute_trade", "status": "ok", "position_id": trade_id})
                    else:
                        steps.append({"step": "execute_trade", "status": "skip", "reason": tr.text[:100]})
            except Exception as e:
                steps.append({"step": "execute_trade", "status": "error", "error": str(e)})
        else:
            steps.append({"step": "execute_trade", "status": "skip", "reason": f"{decision} conf={confidence:.2f}"})

        # ── Step 8: Persist cycle log ────────────────────────────────────────
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    # Create table on first run
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS cycle_log (
                            id          SERIAL PRIMARY KEY,
                            symbol      TEXT NOT NULL,
                            decision    TEXT,
                            confidence  FLOAT,
                            trade_id    INTEGER,
                            steps       JSONB,
                            ran_at      TIMESTAMPTZ DEFAULT NOW()
                        )
                    """)
                    import json as _json
                    cur.execute("""
                        INSERT INTO cycle_log (symbol, decision, confidence, trade_id, steps)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (symbol, decision, confidence, trade_id, _json.dumps(steps)))
                    conn.commit()
        except Exception as log_err:
            logger.warning("cycle_log_error", symbol=symbol, error=str(log_err))

        logger.info("process_symbol_complete", symbol=symbol, decision=decision,
                    confidence=confidence, trade_id=trade_id, steps=len(steps))
        return {
            "status":    "success",
            "symbol":    symbol,
            "decision":  decision,
            "confidence": confidence,
            "trade_id":  trade_id,
            "steps":     steps,
        }

    except Exception as e:
        logger.error("process_symbol_error", symbol=symbol, error=str(e))
        return {"status": "error", "symbol": symbol, "message": str(e)}


@celery_app.task(name='process_all_symbols')
def process_all_symbols():
    """
    Every 5 minutes: fire process_symbol for every active symbol.
    Uses apply_async so all symbols run in parallel across workers.
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT symbol FROM symbols WHERE active = TRUE ORDER BY symbol")
                symbols = [row["symbol"] for row in cur.fetchall()]

        logger.info("process_all_symbols_dispatch", count=len(symbols))
        for sym in symbols:
            celery_app.send_task("process_symbol", args=[sym])

        return {"status": "dispatched", "symbols": len(symbols)}
    except Exception as e:
        logger.error("process_all_symbols_error", error=str(e))
        return {"status": "error", "message": str(e)}


@celery_app.task(name='reevaluate_strategies')
def reevaluate_strategies():
    """
    Triggered when unprofitable streak hits threshold.
    1. Deactivates symbol_strategies with trust_factor < 0.05 (bottom performers)
    2. Requests fresh discovery of up to 10 new symbols
    3. Resets reevaluation_triggered flag
    """
    try:
        logger.info("task_started", task="reevaluate_strategies")
        ai_base = f"http://{settings.service_host}:{settings.port_ai_api}"

        with get_connection() as conn:
            with conn.cursor() as cur:
                # Deactivate worst performers
                cur.execute("""
                    UPDATE symbol_strategies
                    SET status = 'inactive', updated_at = NOW()
                    WHERE trust_factor < 0.05
                      AND status = 'active'
                """)
                deactivated = cur.rowcount

                # Clear reevaluation flag
                cur.execute("""
                    UPDATE trading_mode_config
                    SET reevaluation_triggered = false, updated_at = NOW()
                """)
                conn.commit()

        # Request fresh symbol discovery (smaller set for quick turnaround)
        try:
            resp = requests.post(f"{ai_base}/discover-symbols-ai",
                                 json={"min_volume_usd": 300_000, "max_results": 10},
                                 timeout=60)
            discovery_ok = resp.status_code == 200
        except Exception:
            discovery_ok = False

        logger.info("reevaluation_complete",
                    deactivated=deactivated, discovery_ok=discovery_ok)

        return {
            "status": "success",
            "strategies_deactivated": deactivated,
            "fresh_discovery_triggered": discovery_ok,
        }

    except Exception as e:
        logger.error("task_error", task="reevaluate_strategies", error=str(e))
        return {"status": "error", "message": str(e)}


@celery_app.task(name='auto_unblock_symbols')
def auto_unblock_symbols():
    """
    Daily: re-activate symbol_strategies rows that were deactivated due to poor
    performance, if the most recent 30-day backtest PF improved above 0.9.
    Also resets the runtime blacklist implicitly — any symbol whose 30d P&L
    rises above -$5 will no longer be blacklisted on the next ensemble run.

    Runs once per day via beat schedule.
    """
    try:
        unblocked = []
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Find inactive strategies where the last backtest shows PF > 0.9
                cur.execute("""
                    SELECT ss.id, ss.symbol, ss.strategy_id,
                           ss.profit_factor, ss.trust_factor, ss.total_trades
                    FROM symbol_strategies ss
                    WHERE ss.status = 'inactive'
                      AND ss.profit_factor >= 0.9
                      AND ss.last_backtest_at >= NOW() - INTERVAL '7 days'
                """)
                candidates = cur.fetchall()

                for row in candidates:
                    # Double-check: 30d live P&L for this symbol must be > -$5
                    cur.execute("""
                        SELECT COALESCE(SUM(realized_pnl), 0) AS pnl_30d
                        FROM positions
                        WHERE symbol = %s
                          AND mode  = 'paper'
                          AND status = 'closed'
                          AND entry_time >= NOW() - INTERVAL '30 days'
                    """, (row['symbol'],))
                    pnl = float(cur.fetchone()['pnl_30d'])

                    if pnl > -5.0:
                        cur.execute("""
                            UPDATE symbol_strategies
                            SET status = 'active', updated_at = NOW()
                            WHERE id = %s
                        """, (row['id'],))
                        unblocked.append({
                            'symbol':      row['symbol'],
                            'strategy_id': row['strategy_id'],
                            'pf':          float(row['profit_factor']),
                            'pnl_30d':     pnl,
                        })

                conn.commit()

        logger.info("auto_unblock_complete", unblocked=len(unblocked), detail=unblocked)
        return {"status": "ok", "unblocked": len(unblocked), "detail": unblocked}

    except Exception as e:
        logger.error("auto_unblock_error", error=str(e))
        return {"status": "error", "message": str(e)}


# ==================== CELERY BEAT SCHEDULE ====================

# Configure Celery Beat schedule (dynamic based on SYSTEM_MODE)
celery_app.conf.beat_schedule = {
    # ── Core: full evaluation cycle for all active symbols every hour ────────
    'process-all-symbols': {
        'task': 'process_all_symbols',
        'schedule': 3600.0,  # Every 1 hour
    },

    # Fetch 1-minute candles every 60 seconds
    'fetch-1min-candles': {
        'task': 'fetch_1min_candles',
        'schedule': 60.0,  # Every 60 seconds
    },
    
    # Compute indicators every minute
    # Compute indicators every 10 minutes (reduced from 1 min to prevent I/O overload)
    'compute-indicators': {
        'task': 'compute_indicators',
        'schedule': 600.0,  # Every 10 minutes
    },
    
    # Generate signals every 5 minutes
    'generate-signals': {
        'task': 'generate_signals',
        'schedule': 300.0,  # Every 5 minutes
    },
    
    # Execute paper trades for ALL strategies DISABLED - Conflicted with ensemble system
    # Was checking total P&L instead of per-strategy P&L, triggering false emergency stops
    # 'execute-all-strategies': {
    #     'task': 'execute_paper_trades_all_strategies',
    #     'schedule': 300.0,  # Every 5 minutes
    # },
    
    # OLD execute-ensemble-trades task RE-ENABLED - Performance-weighted ensemble (PROVEN SYSTEM)
    # Uses weighted signals from /signals/ensemble endpoint, no AI voting costs
    # Returned to profitable baseline: 5.7% win rate vs AI voting 4.9% win rate
    'execute-ensemble-trades': {
        'task': 'execute_ensemble_trades',
        'schedule': 600.0,  # Every 10 minutes
    },
    
    # NEW Consensus-Based Ensemble Trading DISABLED - AI voting degraded performance
    # AI should be used for risk management (guardrails), not signal voting
    # BEFORE AI: 5.7% win, -$0.95 P&L | AFTER AI: 4.9% win, -$45.09 P&L
    # 'execute-consensus-ensemble': {
    #     'task': 'execute_consensus_ensemble_trades',
    #     'schedule': 300.0,  # Every 5 minutes (more responsive than old ensemble)
    # },
    
    # Monitor for exceptional signals (100+) and conduct immediate votes
    # Interrupts normal cycle to act on rare opportunities - runs every 60 seconds
    'monitor-exceptional-signals': {
        'task': 'monitor_exceptional_signals',
        'schedule': 60.0,  # Every 60 seconds - fast response to exceptional signals
    },
    
    # Manage open positions every 2 minutes
    'manage-open-positions': {
        'task': 'manage_open_positions',
        'schedule': 120.0,  # Every 2 minutes (check stop-loss/take-profit)
    },
    
    # PHASE 2: AI Guardrail Adjuster - Professional Risk Management
    # AI dynamically adjusts stops/targets based on market conditions
    # Runs every 5 minutes to optimize exits (not signal decisions)
    'adjust-guardrails-ai': {
        'task': 'adjust_position_guardrails_ai',
        'schedule': 300.0,  # Every 5 minutes
    },
    
    # Rebalance portfolio every 15 minutes
    'rebalance-portfolio': {
        'task': 'rebalance_portfolio',
        'schedule': 900.0,  # Every 15 minutes
        'kwargs': {'mode': 'paper'}
    },
    
    # Run after-action analysis twice daily
    'afteraction-midday': {
        'task': 'run_afteraction',
        'schedule': crontab(hour=12, minute=0),  # 12:00 PM UTC
        'kwargs': {'mode': 'paper', 'hours': 12}
    },
    
    'afteraction-eod': {
        'task': 'run_afteraction',
        'schedule': crontab(hour=18, minute=0),  # 6:00 PM UTC
        'kwargs': {'mode': 'paper', 'hours': 12}
    },
    
    # Health check every 10 minutes
    'health-check': {
        'task': 'health_check',
        'schedule': 600.0,  # Every 10 minutes
    },
    
    # Backfill historical candles every 5 minutes
    'backfill-historical': {
        'task': 'backfill_historical_candles',
        'schedule': 300.0,  # Every 5 minutes
    },
    
    # AfterAction analysis
    # Startup: every 3 hours | Production: every 6 hours
    'afteraction-analysis': {
        'task': 'run_afteraction_analysis',
        'schedule': 10800.0 if SYSTEM_MODE == 'startup' else 21600.0,
    },
    
    # Strategy performance calculation (Phase 2)
    # Startup: every 2 hours | Production: every 4 hours
    'strategy-performance': {
        'task': 'calculate_strategy_performance',
        'schedule': 7200.0 if SYSTEM_MODE == 'startup' else 14400.0,
    },
    
    # Market regime detection every 15 minutes (Phase 4)
    'market-regime-detection': {
        'task': 'detect_market_regimes',
        'schedule': 900.0,  # Every 15 minutes (15 * 60)
    },
    
    # Multi-timeframe aggregation every 5 minutes (Phase 5)
    'multi-timeframe-aggregation': {
        'task': 'aggregate_multi_timeframes',
        'schedule': 300.0,  # Every 5 minutes (5 * 60)
    },
    
    # AI Agent decision cycle (Phase 6)
    # Startup: every 15 min (aggressive learning) | Production: every hour
    'ai-agent-cycle': {
        'task': 'run_ai_agent',
        'schedule': 900.0 if SYSTEM_MODE == 'startup' else 3600.0,  # 900s = 15 min
    },
    
    # Walk-forward optimization (Phase 7)
    # Startup: every 2 hours (aggressive parameter tuning) | Production: weekly Sunday 2 AM
    'walkforward-optimization': {
        'task': 'run_walkforward_optimization',
        'schedule': 7200.0 if SYSTEM_MODE == 'startup' else crontab(day_of_week=0, hour=2, minute=0),  # 7200s = 2 hours
    },
    
    # Ensemble parameter optimization
    # Startup: every 6 hours (rapid ensemble tuning) | Production: daily 4 AM
    'ensemble-optimization': {
        'task': 'optimize_ensemble_parameters',
        'schedule': 21600.0 if SYSTEM_MODE == 'startup' else crontab(hour=4, minute=0),  # 21600s = 6 hours
    },
    
    # Check symbol health every 6 hours
    'check-symbol-health': {
        'task': 'check_symbol_health',
        'schedule': crontab(minute='0', hour='*/6'),  # Every 6 hours
    },
    
    # Reset daily trading stats at midnight Mountain Time (7 AM UTC for MST, 6 AM UTC for MDT)
    # Currently set for MST (7 AM UTC = midnight MST)
    'reset-daily-stats': {
        'task': 'reset_daily_trading_stats',
        'schedule': crontab(hour=7, minute=0),  # 7:00 AM UTC = Midnight MST
    },
    
    # ===== LAYER ENHANCEMENTS =====
    
    # Layer 2: Automated Per-Symbol Optimization
    # Process optimization queue every 2 hours
    'process-optimization-queue': {
        'task': 'process_optimization_queue',
        'schedule': 7200.0,  # Every 2 hours
    },
    
    # Layer 5: AI Orchestration
    # AI system health analysis daily at 9 AM UTC
    'ai-system-health': {
        'task': 'ai_analyze_system_health',
        'schedule': crontab(hour=9, minute=0),  # Daily at 9 AM UTC
    },
    
    # AI strategy weight recommendations every 6 hours
    'ai-strategy-weights': {
        'task': 'ai_recommend_strategy_weights',
        'schedule': 21600.0,  # Every 6 hours
    },
    
    # Layer 8: Goal Management
    # Record yesterday's performance at 1 AM UTC (after midnight)
    'record-daily-performance': {
        'task': 'record_daily_performance',
        'schedule': crontab(hour=1, minute=0),  # Daily at 1 AM UTC
    },
    
    # Adjust goals weekly on Sunday at 3 AM UTC
    'adjust-performance-goals': {
        'task': 'adjust_performance_goals',
        'schedule': crontab(day_of_week=0, hour=3, minute=0),  # Weekly Sunday 3 AM
    },

    # ===== PHASE 8 VISION TASKS =====

    # AI symbol + strategy discovery: daily at 6 AM UTC
    'discover-symbols-strategies': {
        'task': 'discover_symbols_and_strategies',
        'schedule': crontab(hour=6, minute=0),
    },

    # Daily strategy refinement: zero-fee backtests, trust update, prune weak
    # Runs at 4 AM UTC — after nightly report (3 AM), before discovery (6 AM)
    'daily-refine-strategies': {
        'task': 'daily_refine_strategies',
        'schedule': crontab(hour=4, minute=0),
    },

    # Re-rank strategies by trust_factor every 4 hours
    'rank-strategies-per-symbol': {
        'task': 'rank_strategies_per_symbol',
        'schedule': 14400.0,  # Every 4 hours
    },

    # Monitor daily profitability at 2:30 AM UTC (after reset-daily-stats at 7 AM)
    'monitor-profitability': {
        'task': 'monitor_profitability',
        'schedule': crontab(hour=2, minute=30),
    },

    # Generate nightly accountability report at 3:00 AM UTC
    'generate-daily-report': {
        'task': 'generate_daily_report',
        'schedule': crontab(hour=3, minute=0),
    },

    # Auto-unblock symbols whose performance has improved
    # Runs daily at 5 AM UTC — after nightly report, before discovery
    'auto-unblock-symbols': {
        'task': 'auto_unblock_symbols',
        'schedule': crontab(hour=5, minute=0),
    },
}

if __name__ == '__main__':
    celery_app.start()
