"""Strategy Config API - Expose strategy parameters and manage overrides"""
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Optional, Union, Any
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.database import get_connection
from shared.config import get_settings
from shared.logging_config import setup_logging

settings = get_settings()
logger = setup_logging('strategy_config_api', settings.log_level)

app = FastAPI(title="Strategy Config API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ParameterSpec(BaseModel):
    name: str
    type: str  # 'int', 'float', 'bool'
    current_value: Union[int, float, bool, str]
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    step: Optional[float] = None
    description: Optional[str] = None

class StrategyConfig(BaseModel):
    strategy_id: int
    strategy_name: str
    parameters: Dict
    risk_management: Dict
    tunable_parameters: List[ParameterSpec]

class OverrideCreate(BaseModel):
    strategy_id: int
    symbol: str
    parameter_overrides: Optional[Dict] = {}
    risk_overrides: Optional[Dict] = {}

@app.get("/")
def root():
    return {"service": "Strategy Config API", "status": "running", "version": "1.0.0"}

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.get("/strategies/{strategy_id}/config", response_model=StrategyConfig)
def get_strategy_config(strategy_id: int):
    """Get strategy configuration with tunable parameters"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, name, parameters, risk_management, indicator_logic
                    FROM strategies
                    WHERE id = %s
                """, (strategy_id,))
                
                strategy = cur.fetchone()
                
                if not strategy:
                    raise HTTPException(status_code=404, detail="Strategy not found")
                
                strategy = dict(strategy)
        
        # Extract tunable parameters based on strategy type
        tunable = extract_tunable_parameters(strategy)
        
        return {
            "strategy_id": strategy['id'],
            "strategy_name": strategy['name'],
            "parameters": strategy['parameters'],
            "risk_management": strategy['risk_management'] or {},
            "tunable_parameters": tunable
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error("config_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/strategies/{strategy_id}/overrides")
def get_strategy_overrides(strategy_id: int, symbol: Optional[str] = None):
    """Get symbol-specific overrides for a strategy"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                if symbol:
                    cur.execute("""
                        SELECT * FROM strategy_overrides
                        WHERE strategy_id = %s AND symbol = %s
                    """, (strategy_id, symbol))
                    override = cur.fetchone()
                    return {"override": dict(override) if override else None}
                else:
                    cur.execute("""
                        SELECT * FROM strategy_overrides
                        WHERE strategy_id = %s
                        ORDER BY optimization_score DESC NULLS LAST
                    """, (strategy_id,))
                    overrides = [dict(row) for row in cur.fetchall()]
                    return {"overrides": overrides, "count": len(overrides)}
    
    except Exception as e:
        logger.error("overrides_fetch_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/strategies/overrides")
def create_or_update_override(override: OverrideCreate):
    """Create or update symbol-specific parameter overrides"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                import psycopg2.extras
                
                cur.execute("""
                    INSERT INTO strategy_overrides 
                        (strategy_id, symbol, parameter_overrides, risk_overrides)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (strategy_id, symbol) 
                    DO UPDATE SET
                        parameter_overrides = EXCLUDED.parameter_overrides,
                        risk_overrides = EXCLUDED.risk_overrides,
                        updated_at = NOW()
                    RETURNING id
                """, (
                    override.strategy_id,
                    override.symbol,
                    psycopg2.extras.Json(override.parameter_overrides),
                    psycopg2.extras.Json(override.risk_overrides)
                ))
                
                result = cur.fetchone()
                override_id = result['id']
        
        logger.info("override_saved", 
                   strategy_id=override.strategy_id,
                   symbol=override.symbol,
                   override_id=override_id)
        
        return {
            "status": "success",
            "override_id": override_id,
            "strategy_id": override.strategy_id,
            "symbol": override.symbol
        }
    
    except Exception as e:
        logger.error("override_save_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/strategies/overrides/{override_id}")
def delete_override(override_id: int):
    """Delete a symbol-specific override"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    DELETE FROM strategy_overrides
                    WHERE id = %s
                    RETURNING strategy_id, symbol
                """, (override_id,))
                
                result = cur.fetchone()
                
                if not result:
                    raise HTTPException(status_code=404, detail="Override not found")
                
                result = dict(result)
        
        logger.info("override_deleted", override_id=override_id)
        
        return {
            "status": "success",
            "message": "Override deleted",
            "strategy_id": result['strategy_id'],
            "symbol": result['symbol']
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error("override_delete_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

def extract_tunable_parameters(strategy: Dict) -> List[Dict]:
    """Extract tunable parameters from strategy configuration"""
    tunable = []
    params = strategy.get('parameters') or {}
    risk = strategy.get('risk_management') or {}
    
    # RSI parameters (check if they exist in params)
    if 'rsi_period' in params:
        tunable.append({
            "name": "rsi_period",
            "type": "int",
            "current_value": params['rsi_period'],
            "min_value": 7,
            "max_value": 30,
            "step": 1,
            "description": "RSI calculation period"
        })
    
    if 'rsi_oversold' in params:
        tunable.append({
            "name": "rsi_oversold",
            "type": "int",
            "current_value": params['rsi_oversold'],
            "min_value": 10,
            "max_value": 40,
            "step": 5,
            "description": "RSI oversold threshold (buy signal)"
        })
    
    if 'rsi_overbought' in params:
        tunable.append({
            "name": "rsi_overbought",
            "type": "int",
            "current_value": params['rsi_overbought'],
            "min_value": 60,
            "max_value": 90,
            "step": 5,
            "description": "RSI overbought threshold (sell signal)"
        })
    
    # MACD parameters
    if 'macd_fast' in params:
        tunable.append({
            "name": "macd_fast",
            "type": "int",
            "current_value": params['macd_fast'],
            "min_value": 8,
            "max_value": 20,
            "step": 2,
            "description": "MACD fast EMA period"
        })
    
    if 'macd_slow' in params:
        tunable.append({
            "name": "macd_slow",
            "type": "int",
            "current_value": params['macd_slow'],
            "min_value": 20,
            "max_value": 40,
            "step": 2,
            "description": "MACD slow EMA period"
        })
    
    if 'macd_signal' in params:
        tunable.append({
            "name": "macd_signal",
            "type": "int",
            "current_value": params['macd_signal'],
            "min_value": 6,
            "max_value": 15,
            "step": 1,
            "description": "MACD signal line period"
        })
    
    # SMA parameters  
    if 'sma_period' in params:
        tunable.append({
            "name": "sma_period",
            "type": "int",
            "current_value": params['sma_period'],
            "min_value": 10,
            "max_value": 50,
            "step": 5,
            "description": "SMA period"
        })
    
    # EMA parameters
    if 'ema_period' in params:
        tunable.append({
            "name": "ema_period",
            "type": "int",
            "current_value": params['ema_period'],
            "min_value": 10,
            "max_value": 50,
            "step": 5,
            "description": "EMA period"
        })
    
    # Bollinger Bands parameters
    if 'bb_period' in params:
        tunable.append({
            "name": "bb_period",
            "type": "int",
            "current_value": params['bb_period'],
            "min_value": 10,
            "max_value": 40,
            "step": 5,
            "description": "Bollinger Bands period"
        })
    
    if 'bb_std' in params:
        tunable.append({
            "name": "bb_std",
            "type": "float",
            "current_value": params['bb_std'],
            "min_value": 1.5,
            "max_value": 3.0,
            "step": 0.5,
            "description": "Bollinger Bands standard deviation"
        })
    
    # Williams %R parameters
    if 'williams_period' in params:
        tunable.append({
            "name": "williams_period",
            "type": "int",
            "current_value": params['williams_period'],
            "min_value": 7,
            "max_value": 30,
            "step": 1,
            "description": "Williams %R period"
        })
    
    # CCI parameters
    if 'cci_period' in params:
        tunable.append({
            "name": "cci_period",
            "type": "int",
            "current_value": params['cci_period'],
            "min_value": 10,
            "max_value": 40,
            "step": 5,
            "description": "CCI period"
        })
    
    # ADX parameters
    if 'adx_period' in params:
        tunable.append({
            "name": "adx_period",
            "type": "int",
            "current_value": params['adx_period'],
            "min_value": 7,
            "max_value": 30,
            "step": 1,
            "description": "ADX period"
        })
    
    # Stochastic parameters
    if 'stoch_period' in params:
        tunable.append({
            "name": "stoch_period",
            "type": "int",
            "current_value": params['stoch_period'],
            "min_value": 7,
            "max_value": 30,
            "step": 1,
            "description": "Stochastic %K period"
        })
    
    if 'stoch_smooth' in params:
        tunable.append({
            "name": "stoch_smooth",
            "type": "int",
            "current_value": params['stoch_smooth'],
            "min_value": 1,
            "max_value": 10,
            "step": 1,
            "description": "Stochastic %D smoothing period"
        })
    
    # ROC parameters
    if 'roc_period' in params:
        tunable.append({
            "name": "roc_period",
            "type": "int",
            "current_value": params['roc_period'],
            "min_value": 5,
            "max_value": 30,
            "step": 1,
            "description": "Rate of Change period"
        })
    
    # ATR parameters
    if 'atr_period' in params:
        tunable.append({
            "name": "atr_period",
            "type": "int",
            "current_value": params['atr_period'],
            "min_value": 7,
            "max_value": 30,
            "step": 1,
            "description": "ATR period"
        })
    
    # Risk management parameters (common to all strategies)
    if 'stop_loss_pct' in risk:
        tunable.append({
            "name": "stop_loss_pct",
            "type": "float",
            "current_value": risk['stop_loss_pct'],
            "min_value": 1.0,
            "max_value": 10.0,
            "step": 0.5,
            "description": "Stop loss percentage"
        })
    
    if 'take_profit_pct' in risk:
        tunable.append({
            "name": "take_profit_pct",
            "type": "float",
            "current_value": risk['take_profit_pct'],
            "min_value": 2.0,
            "max_value": 20.0,
            "step": 1.0,
            "description": "Take profit percentage"
        })
    
    return tunable

@app.get("/primary-strategies")
def get_primary_strategies():
    """Get the primary strategy for each symbol"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        so.symbol,
                        so.strategy_id,
                        s.name as strategy_name,
                        so.optimization_score,
                        so.updated_at
                    FROM strategy_overrides so
                    JOIN strategies s ON s.id = so.strategy_id
                    WHERE so.is_primary = true
                    ORDER BY so.symbol
                """)
                
                primaries = [dict(row) for row in cur.fetchall()]
        
        logger.info("primary_strategies_fetched", count=len(primaries))
        return {
            "status": "success",
            "primary_strategies": primaries
        }
    
    except Exception as e:
        logger.error("fetch_primary_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/primary-strategies/{symbol}/set")
def set_primary_strategy(symbol: str, strategy_id: int):
    """Set the primary strategy for a symbol"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # First, check if an override exists for this strategy-symbol combo
                cur.execute("""
                    SELECT id FROM strategy_overrides
                    WHERE strategy_id = %s AND symbol = %s
                """, (strategy_id, symbol))
                
                override = cur.fetchone()
                
                if not override:
                    raise HTTPException(
                        status_code=404, 
                        detail=f"No override found for strategy {strategy_id} on {symbol}. Run optimization first."
                    )
                
                # Unset any existing primary for this symbol
                cur.execute("""
                    UPDATE strategy_overrides
                    SET is_primary = false
                    WHERE symbol = %s AND is_primary = true
                """, (symbol,))
                
                # Set new primary
                cur.execute("""
                    UPDATE strategy_overrides
                    SET is_primary = true, updated_at = NOW()
                    WHERE strategy_id = %s AND symbol = %s
                    RETURNING id
                """, (strategy_id, symbol))
                
                result = cur.fetchone()
        
        logger.info("primary_strategy_set", 
                   symbol=symbol, 
                   strategy_id=strategy_id)
        
        return {
            "status": "success",
            "symbol": symbol,
            "strategy_id": strategy_id,
            "message": f"Primary strategy set for {symbol}"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error("set_primary_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/primary-strategies/{symbol}")
def get_symbol_primary_strategy(symbol: str):
    """Get the primary strategy for a specific symbol"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        so.strategy_id,
                        s.name as strategy_name,
                        s.description,
                        so.parameter_overrides,
                        so.risk_overrides,
                        so.optimization_score,
                        so.updated_at
                    FROM strategy_overrides so
                    JOIN strategies s ON s.id = so.strategy_id
                    WHERE so.symbol = %s AND so.is_primary = true
                """, (symbol,))
                
                primary = cur.fetchone()
                
                if not primary:
                    return {
                        "status": "success",
                        "symbol": symbol,
                        "primary_strategy": None,
                        "message": "No primary strategy set for this symbol"
                    }
                
                return {
                    "status": "success",
                    "symbol": symbol,
                    "primary_strategy": dict(primary)
                }
    
    except Exception as e:
        logger.error("get_symbol_primary_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/performance/comparison")
def compare_backtest_vs_paper():
    """Compare backtest results vs paper trading performance for primary strategies"""
    try:
        from datetime import timedelta
        logger.info("performance_comparison_requested")
        
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Get primary strategies
                cur.execute("""
                    SELECT 
                        so.symbol,
                        so.strategy_id,
                        s.name as strategy_name,
                        so.optimization_score as backtest_score,
                        so.parameter_overrides
                    FROM strategy_overrides so
                    JOIN strategies s ON s.id = so.strategy_id
                    WHERE so.is_primary = true
                """)
                
                primaries = cur.fetchall()
                
                if not primaries:
                    return {
                        "status": "warning",
                        "message": "No primary strategies set",
                        "comparisons": []
                    }
                
                comparisons = []
                
                for primary in primaries:
                    symbol = primary['symbol']
                    strategy_id = primary['strategy_id']
                    
                    # Get paper trading results for this strategy/symbol
                    cur.execute("""
                        SELECT 
                            COUNT(*) as total_trades,
                            SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) as winning_trades,
                            AVG(realized_pnl) as avg_pnl,
                            AVG(realized_pnl_pct) as avg_pnl_pct,
                            SUM(realized_pnl) as total_pnl,
                            MIN(entry_time) as first_trade,
                            MAX(exit_time) as last_trade
                        FROM positions
                        WHERE symbol = %s
                            AND strategy_id = %s
                            AND mode = 'paper'
                            AND status = 'closed'
                    """, (symbol, strategy_id))
                    
                    paper = cur.fetchone()
                    
                    # Get latest backtest results for this strategy/symbol
                    cur.execute("""
                        SELECT 
                            total_return_pct,
                            total_trades,
                            winning_trades,
                            losing_trades,
                            win_rate,
                            avg_return_per_trade,
                            max_drawdown_pct,
                            sharpe_ratio,
                            run_date
                        FROM backtests
                        WHERE strategy_id = %s
                            AND symbol = %s
                        ORDER BY run_date DESC
                        LIMIT 1
                    """, (strategy_id, symbol))
                    
                    backtest = cur.fetchone()
                    
                    # Calculate paper trading metrics
                    paper_total = paper['total_trades'] if paper and paper['total_trades'] else 0
                    paper_winning = paper['winning_trades'] if paper and paper['winning_trades'] else 0
                    paper_win_rate = (paper_winning / paper_total * 100) if paper_total > 0 else 0
                    paper_avg_pnl_pct = float(paper['avg_pnl_pct']) if paper and paper['avg_pnl_pct'] else 0
                    paper_total_pnl = float(paper['total_pnl']) if paper and paper['total_pnl'] else 0
                    
                    # Calculate days trading
                    days_trading = 0
                    if paper and paper['first_trade'] and paper['last_trade']:
                        days_trading = (paper['last_trade'] - paper['first_trade']).days + 1
                    
                    # Daily return calculation
                    daily_return_pct = 0
                    if days_trading > 0 and paper_total_pnl != 0:
                        # Assuming $10,000 starting capital
                        daily_return_pct = (paper_total_pnl / 10000.0 / days_trading) * 100
                    
                    # Backtest metrics
                    backtest_return = float(backtest['total_return_pct']) if backtest and backtest['total_return_pct'] else 0
                    backtest_win_rate = float(backtest['win_rate']) if backtest and backtest['win_rate'] else 0
                    backtest_trades = backtest['total_trades'] if backtest and backtest['total_trades'] else 0
                    
                    # Performance delta (paper vs backtest)
                    win_rate_delta = paper_win_rate - backtest_win_rate if backtest else 0
                    
                    # Status assessment
                    status = "⚫ No Data"
                    if paper_total >= 5:  # Need at least 5 trades for meaningful comparison
                        if paper_win_rate >= backtest_win_rate - 5:  # Within 5% is good
                            if daily_return_pct >= 0.05:  # Meeting 0.05% daily goal
                                status = "✅ Excellent"
                            else:
                                status = "✓ Good"
                        elif paper_win_rate >= backtest_win_rate - 15:  # Within 15%
                            status = "⚠️ Warning"
                        else:
                            status = "❌ Poor"
                    elif paper_total > 0:
                        status = "🔵 Early (need more trades)"
                    
                    comparisons.append({
                        "symbol": symbol,
                        "strategy_id": strategy_id,
                        "strategy_name": primary['strategy_name'],
                        "status": status,
                        "backtest": {
                            "return_pct": round(backtest_return, 2),
                            "win_rate": round(backtest_win_rate, 1),
                            "total_trades": backtest_trades,
                            "optimization_score": float(primary['backtest_score']) if primary['backtest_score'] else 0
                        },
                        "paper_trading": {
                            "total_trades": paper_total,
                            "winning_trades": paper_winning,
                            "win_rate": round(paper_win_rate, 1),
                            "avg_return_pct": round(paper_avg_pnl_pct, 2),
                            "total_pnl": round(paper_total_pnl, 2),
                            "days_trading": days_trading,
                            "daily_return_pct": round(daily_return_pct, 4)
                        },
                        "delta": {
                            "win_rate": round(win_rate_delta, 1)
                        },
                        "meets_goal": daily_return_pct >= 0.05  # 0.05% daily goal
                    })
                
                # Calculate system-wide metrics
                total_daily_return = sum(c['paper_trading']['daily_return_pct'] for c in comparisons)
                strategies_meeting_goal = sum(1 for c in comparisons if c['meets_goal'])
                
                return {
                    "status": "success",
                    "comparisons": comparisons,
                    "summary": {
                        "primary_strategies": len(comparisons),
                        "total_daily_return_pct": round(total_daily_return, 4),
                        "strategies_meeting_goal": strategies_meeting_goal,
                        "system_meeting_goal": total_daily_return >= 0.05
                    }
                }
    
    except Exception as e:
        logger.error("performance_comparison_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/strategies/combinations")
def analyze_strategy_combinations(min_trades: int = Query(5, ge=1)):
    """Analyze which strategy combinations work well together"""
    try:
        logger.info("strategy_combinations_requested")
        
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Find signals where multiple strategies agreed on same symbol/time
                # Group signals by symbol and approximate time window (5 minutes)
                cur.execute("""
                    WITH signal_windows AS (
                        SELECT 
                            symbol,
                            date_trunc('minute', generated_at) as time_window,
                            signal_type,
                            array_agg(DISTINCT strategy_id ORDER BY strategy_id) as strategies,
                            array_agg(quality_score ORDER BY quality_score DESC) as quality_scores,
                            COUNT(DISTINCT strategy_id) as strategy_count
                        FROM signals
                        WHERE generated_at > NOW() - INTERVAL '7 days'
                            AND signal_type = 'BUY'
                        GROUP BY symbol, date_trunc('minute', generated_at), signal_type
                        HAVING COUNT(DISTINCT strategy_id) >= 2
                    )
                    SELECT * FROM signal_windows
                    ORDER BY strategy_count DESC, time_window DESC
                    LIMIT 100
                """)
                
                consensus_events = cur.fetchall()
                
                # Get closed positions to see which consensus signals resulted in profits
                cur.execute("""
                    SELECT 
                        p.symbol,
                        p.strategy_id,
                        s.name as strategy_name,
                        p.signal_id,
                        p.entry_time,
                        p.realized_pnl,
                        p.realized_pnl_pct,
                        sig.generated_at as signal_time
                    FROM positions p
                    JOIN strategies s ON s.id = p.strategy_id
                    LEFT JOIN signals sig ON sig.id = p.signal_id
                    WHERE p.mode = 'paper'
                        AND p.status = 'closed'
                        AND p.entry_time > NOW() - INTERVAL '7 days'
                    ORDER BY p.entry_time DESC
                """)
                
                positions = cur.fetchall()
                
                # Build map of what strategies had positions at what times
                from collections import defaultdict
                strategy_pairs = defaultdict(lambda: {'together': 0, 'wins': 0, 'losses': 0, 'total_pnl': 0.0})
                
                # For each position, find other positions in similar time window
                for i, pos1 in enumerate(positions):
                    for pos2 in positions[i+1:]:
                        # Same symbol and within 10 minutes?
                        if pos1['symbol'] == pos2['symbol']:
                            if pos1['entry_time'] and pos2['entry_time']:
                                time_diff = abs((pos1['entry_time'] - pos2['entry_time']).total_seconds())
                                if time_diff <= 600:  # 10 minutes
                                    # These two strategies traded together
                                    str1 = pos1['strategy_id']
                                    str2 = pos2['strategy_id']
                                    pair_key = tuple(sorted([str1, str2]))
                                    
                                    strategy_pairs[pair_key]['together'] += 1
                                    
                                    # Did both win?
                                    if pos1['realized_pnl'] and pos2['realized_pnl']:
                                        if pos1['realized_pnl'] > 0 and pos2['realized_pnl'] > 0:
                                            strategy_pairs[pair_key]['wins'] += 1
                                            strategy_pairs[pair_key]['total_pnl'] += float(pos1['realized_pnl']) + float(pos2['realized_pnl'])
                                        elif pos1['realized_pnl'] < 0 or pos2['realized_pnl'] < 0:
                                            strategy_pairs[pair_key]['losses'] += 1
                                            strategy_pairs[pair_key]['total_pnl'] += float(pos1['realized_pnl']) + float(pos2['realized_pnl'])
                
                # Get strategy names
                cur.execute("SELECT id, name FROM strategies")
                strategy_names = {row['id']: row['name'] for row in cur.fetchall()}
                
                # Format results
                combinations = []
                for pair, stats in strategy_pairs.items():
                    if stats['together'] >= min_trades:
                        win_rate = (stats['wins'] / stats['together'] * 100) if stats['together'] > 0 else 0
                        
                        combinations.append({
                            'strategy_1_id': pair[0],
                            'strategy_1_name': strategy_names.get(pair[0], 'Unknown'),
                            'strategy_2_id': pair[1],
                            'strategy_2_name': strategy_names.get(pair[1], 'Unknown'),
                            'times_together': stats['together'],
                            'both_won': stats['wins'],
                            'either_lost': stats['losses'],
                            'win_rate': round(win_rate, 1),
                            'combined_pnl': round(stats['total_pnl'], 2),
                            'recommendation': 'Strong' if win_rate >= 70 and stats['together'] >= 10 else 'Good' if win_rate >= 60 else 'Neutral'
                        })
                
                # Sort by win rate and frequency
                combinations.sort(key=lambda x: (x['win_rate'], x['times_together']), reverse=True)
                
                # Find most common consensus signals
                consensus_summary = []
                for event in consensus_events[:20]:
                    consensus_summary.append({
                        'symbol': event['symbol'],
                        'time': event['time_window'].isoformat(),
                        'strategies': event['strategies'],
                        'strategy_count': event['strategy_count'],
                        'avg_quality': round(sum(event['quality_scores']) / len(event['quality_scores']), 1) if event['quality_scores'] else 0
                    })
                
                return {
                    "status": "success",
                    "strategy_combinations": combinations[:20],  # Top 20
                    "recent_consensus_signals": consensus_summary,
                    "analysis": {
                        "total_pairs_found": len(combinations),
                        "high_performing_pairs": len([c for c in combinations if c['win_rate'] >= 70]),
                        "total_consensus_events": len(consensus_events)
                    }
                }
    
    except Exception as e:
        logger.error("strategy_combinations_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/performance/all-strategies")
def compare_all_strategies():
    """Compare backtest vs paper trading for ALL strategies (not just primaries)"""
    try:
        logger.info("all_strategies_performance_requested")
        
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Get all strategies that have been tested in paper trading
                cur.execute("""
                    SELECT DISTINCT
                        s.id as strategy_id,
                        s.name as strategy_name,
                        s.enabled
                    FROM strategies s
                    JOIN positions p ON p.strategy_id = s.id
                    WHERE p.mode = 'paper'
                    ORDER BY s.name
                """)
                
                strategies = cur.fetchall()
                
                comparisons = []
                
                for strategy in strategies:
                    strategy_id = strategy['strategy_id']
                    
                    # Get paper trading results across ALL symbols
                    cur.execute("""
                        SELECT 
                            symbol,
                            COUNT(*) as total_trades,
                            SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) as winning_trades,
                            AVG(realized_pnl_pct) as avg_pnl_pct,
                            SUM(realized_pnl) as total_pnl,
                            MIN(entry_time) as first_trade,
                            MAX(exit_time) as last_trade
                        FROM positions
                        WHERE strategy_id = %s
                            AND mode = 'paper'
                            AND status = 'closed'
                        GROUP BY symbol
                    """, (strategy_id,))
                    
                    paper_by_symbol = cur.fetchall()
                    
                    if not paper_by_symbol:
                        continue  # Skip strategies with no paper trades yet
                    
                    # Aggregate paper results
                    total_paper_trades = sum(p['total_trades'] for p in paper_by_symbol)
                    total_paper_wins = sum(p['winning_trades'] for p in paper_by_symbol)
                    paper_win_rate = (total_paper_wins / total_paper_trades * 100) if total_paper_trades > 0 else 0
                    total_paper_pnl = sum(float(p['total_pnl']) for p in paper_by_symbol if p['total_pnl'])
                    avg_paper_pnl_pct = sum(float(p['avg_pnl_pct']) for p in paper_by_symbol if p['avg_pnl_pct']) / len(paper_by_symbol)
                    
                    # Calculate trading period
                    first_trade = min((p['first_trade'] for p in paper_by_symbol if p['first_trade']), default=None)
                    last_trade = max((p['last_trade'] for p in paper_by_symbol if p['last_trade']), default=None)
                    days_trading = 0
                    if first_trade and last_trade:
                        days_trading = (last_trade - first_trade).days + 1
                    
                    # Daily return
                    daily_return_pct = 0
                    if days_trading > 0:
                        daily_return_pct = (total_paper_pnl / 10000.0 / days_trading) * 100
                    
                    # Get latest backtest across all symbols
                    cur.execute("""
                        SELECT 
                            AVG(total_return_pct) as avg_return,
                            AVG(win_rate) as avg_win_rate,
                            SUM(total_trades) as total_trades
                        FROM backtests
                        WHERE strategy_id = %s
                            AND run_date > NOW() - INTERVAL '30 days'
                    """, (strategy_id,))
                    
                    backtest = cur.fetchone()
                    
                    backtest_return = float(backtest['avg_return']) if backtest and backtest['avg_return'] else 0
                    backtest_win_rate = float(backtest['avg_win_rate']) if backtest and backtest['avg_win_rate'] else 0
                    
                    # Calculate slippage (performance degradation from backtest to paper)
                    win_rate_slippage = paper_win_rate - backtest_win_rate if backtest else 0
                    
                    # Status
                    status = "⚫ No Data"
                    if total_paper_trades >= 10:
                        if win_rate_slippage >= -5:  # Within 5% of backtest
                            if daily_return_pct >= 0.05:
                                status = "✅ Excellent (low slippage + profitable)"
                            else:
                                status = "✓ Good (low slippage)"
                        elif win_rate_slippage >= -15:
                            status = "⚠️ Moderate slippage"
                        else:
                            status = "❌ High slippage (>15%)"
                    elif total_paper_trades > 0:
                        status = "🔵 Early stage"
                    
                    comparisons.append({
                        "strategy_id": strategy_id,
                        "strategy_name": strategy['strategy_name'],
                        "enabled": strategy['enabled'],
                        "status": status,
                        "backtest": {
                            "avg_return_pct": round(backtest_return, 2),
                            "avg_win_rate": round(backtest_win_rate, 1),
                            "total_trades": backtest['total_trades'] if backtest and backtest['total_trades'] else 0
                        },
                        "paper_trading": {
                            "total_trades": total_paper_trades,
                            "winning_trades": total_paper_wins,
                            "win_rate": round(paper_win_rate, 1),
                            "avg_return_pct": round(avg_paper_pnl_pct, 2),
                            "total_pnl": round(total_paper_pnl, 2),
                            "days_trading": days_trading,
                            "daily_return_pct": round(daily_return_pct, 4)
                        },
                        "slippage": {
                            "win_rate": round(win_rate_slippage, 1),
                            "severity": "Low" if win_rate_slippage >= -5 else "Moderate" if win_rate_slippage >= -15 else "High"
                        },
                        "meets_goal": daily_return_pct >= 0.05
                    })
                
                # Sort by paper trading win rate (real performance)
                comparisons.sort(key=lambda x: (x['paper_trading']['win_rate'], x['paper_trading']['total_trades']), reverse=True)
                
                # Summary
                total_strategies = len(comparisons)
                low_slippage = len([c for c in comparisons if c['slippage']['severity'] == 'Low' and c['paper_trading']['total_trades'] >= 10])
                meeting_goal = len([c for c in comparisons if c['meets_goal']])
                
                return {
                    "status": "success",
                    "comparisons": comparisons,
                    "summary": {
                        "total_strategies_tested": total_strategies,
                        "low_slippage_strategies": low_slippage,
                        "strategies_meeting_goal": meeting_goal,
                        "recommendation": f"Focus on {low_slippage} strategies with low slippage"
                    }
                }
    
    except Exception as e:
        logger.error("all_strategies_performance_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
# Trading Policies & Safeguards

@app.get("/policies/status")
async def get_trading_status(mode: str = Query("paper")):
    """Get current trading status with limits and usage"""
    try:
        from datetime import date
        
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Get policies
                cur.execute("SELECT * FROM trading_policies WHERE mode = %s", (mode,))
                policies = cur.fetchone()
                
                if not policies:
                    raise HTTPException(status_code=404, detail=f"No policies for mode: {mode}")
                
                # Get today's stats
                cur.execute("""
                    SELECT * FROM daily_trading_stats
                    WHERE date = %s AND mode = %s
                """, (date.today(), mode))
                daily_stats = cur.fetchone()
                
                # Get current open positions (only count ensemble positions for limits)
                cur.execute("""
                    SELECT 
                        COUNT(*) as total_open,
                        COUNT(DISTINCT symbol) as symbols_count
                    FROM positions
                    WHERE status = 'open' AND mode = %s AND position_type = 'ensemble'
                """, (mode,))
                positions = cur.fetchone()
                
                # Get positions per symbol (only ensemble positions)
                cur.execute("""
                    SELECT symbol, COUNT(*) as count
                    FROM positions
                    WHERE status = 'open' AND mode = %s AND position_type = 'ensemble'
                    GROUP BY symbol
                """, (mode,))
                per_symbol = {row['symbol']: row['count'] for row in cur.fetchall()}
                
                # Calculate today's P&L (only count ensemble positions for trade limit)
                cur.execute("""
                    SELECT 
                        COALESCE(SUM(realized_pnl), 0) as today_pnl,
                        COUNT(*) as trades_today
                    FROM positions
                    WHERE DATE(entry_time) = %s
                        AND mode = %s
                        AND position_type = 'ensemble'
                        AND status = 'closed'
                """, (date.today(), mode))
                today = cur.fetchone()
                
                # Check consecutive losses
                cur.execute("""
                    WITH recent_trades AS (
                        SELECT realized_pnl,
                               ROW_NUMBER() OVER (ORDER BY exit_time DESC) as rn
                        FROM positions
                        WHERE mode = %s
                            AND status = 'closed'
                            AND exit_time IS NOT NULL
                        ORDER BY exit_time DESC
                        LIMIT 20
                    )
                    SELECT COUNT(*) as consecutive_losses
                    FROM recent_trades
                    WHERE rn <= (
                        SELECT COALESCE(MIN(rn), 21) 
                        FROM recent_trades 
                        WHERE realized_pnl > 0
                    )
                    AND realized_pnl < 0
                """, (mode,))
                losses_row = cur.fetchone()
                consecutive_losses = losses_row['consecutive_losses'] if losses_row else 0
                
                # Calculate real market costs
                total_round_trip_cost = (
                    float(policies['expected_slippage_pct']) +
                    float(policies['expected_spread_pct']) +
                    float(policies['exchange_fee_pct'])
                ) * 2  # Entry + exit
                
                # Check limit statuses
                daily_pnl = float(today['today_pnl']) if today else 0
                trades_today = today['trades_today'] if today else 0
                total_open = positions['total_open'] if positions else 0
                
                daily_loss_limit = float(policies['daily_loss_limit'])
                daily_trade_limit = policies['daily_trade_limit']
                max_open_positions = policies['max_open_positions']
                max_per_symbol = policies['max_positions_per_symbol']
                
                # Status checks
                limits_hit = {
                    "emergency_stop": policies['emergency_stop'],
                    "daily_loss_limit_hit": daily_pnl <= -daily_loss_limit,
                    "daily_trade_limit_hit": trades_today >= daily_trade_limit,
                    "max_positions_hit": total_open >= max_open_positions,
                    "consecutive_losses_warning": consecutive_losses >= policies['alert_consecutive_losses']
                }
                
                trading_allowed = not any([
                    limits_hit["emergency_stop"],
                    limits_hit["daily_loss_limit_hit"],
                    limits_hit["daily_trade_limit_hit"],
                    limits_hit["max_positions_hit"]
                ])
                
                return {
                    "status": "success",
                    "mode": mode,
                    "trading_allowed": trading_allowed,
                    "limits_hit": limits_hit,
                    "emergency_stop": {
                        "active": policies['emergency_stop'],
                        "reason": policies['emergency_stop_reason'],
                        "time": policies['emergency_stop_time'].isoformat() if policies['emergency_stop_time'] else None
                    },
                    "daily_limits": {
                        "loss_limit": float(daily_loss_limit),
                        "current_pnl": round(daily_pnl, 2),
                        "remaining": round(daily_loss_limit + daily_pnl, 2),
                        "trade_limit": daily_trade_limit,
                        "trades_today": trades_today,
                        "trades_remaining": max(0, daily_trade_limit - trades_today)
                    },
                    "position_limits": {
                        "max_open": max_open_positions,
                        "current_open": total_open,
                        "remaining": max(0, max_open_positions - total_open),
                        "max_per_symbol": max_per_symbol,
                        "by_symbol": per_symbol
                    },
                    "market_costs": {
                        "slippage_pct": float(policies['expected_slippage_pct']),
                        "spread_pct": float(policies['expected_spread_pct']),
                        "exchange_fee_pct": float(policies['exchange_fee_pct']),
                        "total_round_trip_pct": round(total_round_trip_cost, 2),
                        "breakeven_move_required": f">{total_round_trip_cost:.2f}%"
                    },
                    "alerts": {
                        "consecutive_losses": consecutive_losses,
                        "threshold": policies['alert_consecutive_losses'],
                        "email_enabled": policies['email_alerts_enabled'],
                        "alerts_sent_today": policies['alerts_sent_today']
                    },
                    "policies": {
                        "max_position_size": float(policies['max_position_size']),
                        "alert_daily_profit_pct": float(policies['alert_daily_profit_pct']),
                        "alert_daily_loss_pct": float(policies['alert_daily_loss_pct']),
                        "alert_drawdown_pct": float(policies['alert_drawdown_pct'])
                    }
                }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_status_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/policies/emergency-stop")
async def toggle_emergency_stop(
    mode: str = Query("paper"),
    enabled: bool = Query(...),
    reason: Optional[str] = Query(None)
):
    """Toggle emergency stop"""
    try:
        logger.warning("emergency_stop_toggled", mode=mode, enabled=enabled, reason=reason)
        
        with get_connection() as conn:
            with conn.cursor() as cur:
                if enabled:
                    cur.execute("""
                        UPDATE trading_policies
                        SET emergency_stop = true,
                            emergency_stop_reason = %s,
                            emergency_stop_time = NOW(),
                            updated_at = NOW()
                        WHERE mode = %s
                        RETURNING *
                    """, (reason or "Manual emergency stop", mode))
                else:
                    cur.execute("""
                        UPDATE trading_policies
                        SET emergency_stop = false,
                            emergency_stop_reason = NULL,
                            emergency_stop_time = NULL,
                            updated_at = NOW()
                        WHERE mode = %s
                        RETURNING *
                    """, (mode,))
                
                updated = cur.fetchone()
        
        return {
            "status": "success",
            "emergency_stop": enabled,
            "mode": mode,
            "reason": reason,
            "policies": dict(updated) if updated else None
        }
    
    except Exception as e:
        logger.error("emergency_stop_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/policies/{mode}")
def get_trading_policies(mode: str = "paper"):
    """Get trading policies for paper or live mode"""
    try:
        logger.info("get_policies_requested", mode=mode)
        
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT * FROM trading_policies
                    WHERE mode = %s
                    LIMIT 1
                """, (mode,))
                
                policy = cur.fetchone()
                
                if not policy:
                    raise HTTPException(status_code=404, detail=f"No policies found for mode: {mode}")
                
                return {"status": "success", "policies": dict(policy)}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_policies_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/policies/{mode}")
async def update_trading_policies(
    mode: str,
    daily_loss_limit: Optional[float] = Query(None),
    daily_trade_limit: Optional[int] = Query(None),
    max_position_size: Optional[float] = Query(None),
    max_open_positions: Optional[int] = Query(None),
    max_positions_per_symbol: Optional[int] = Query(None),
    alert_daily_profit_pct: Optional[float] = Query(None),
    alert_daily_loss_pct: Optional[float] = Query(None),
    alert_drawdown_pct: Optional[float] = Query(None),
    alert_consecutive_losses: Optional[int] = Query(None),
    email_alerts_enabled: Optional[bool] = Query(None),
    alert_email: Optional[str] = Query(None)
):
    """Update trading policies"""
    try:
        logger.info("update_policies_requested", mode=mode)
        
        updates = []
        params = []
        
        if daily_loss_limit is not None:
            updates.append("daily_loss_limit = %s")
            params.append(daily_loss_limit)
        if daily_trade_limit is not None:
            updates.append("daily_trade_limit = %s")
            params.append(daily_trade_limit)
        if max_position_size is not None:
            updates.append("max_position_size = %s")
            params.append(max_position_size)
        if max_open_positions is not None:
            updates.append("max_open_positions = %s")
            params.append(max_open_positions)
        if max_positions_per_symbol is not None:
            updates.append("max_positions_per_symbol = %s")
            params.append(max_positions_per_symbol)
        if alert_daily_profit_pct is not None:
            updates.append("alert_daily_profit_pct = %s")
            params.append(alert_daily_profit_pct)
        if alert_daily_loss_pct is not None:
            updates.append("alert_daily_loss_pct = %s")
            params.append(alert_daily_loss_pct)
        if alert_drawdown_pct is not None:
            updates.append("alert_drawdown_pct = %s")
            params.append(alert_drawdown_pct)
        if alert_consecutive_losses is not None:
            updates.append("alert_consecutive_losses = %s")
            params.append(alert_consecutive_losses)
        if email_alerts_enabled is not None:
            updates.append("email_alerts_enabled = %s")
            params.append(email_alerts_enabled)
        if alert_email is not None:
            updates.append("alert_email = %s")
            params.append(alert_email)
        
        if not updates:
            raise HTTPException(status_code=400, detail="No updates provided")
        
        updates.append("updated_at = NOW()")
        params.append(mode)
        
        with get_connection() as conn:
            with conn.cursor() as cur:
                query = f"UPDATE trading_policies SET {', '.join(updates)} WHERE mode = %s RETURNING *"
                cur.execute(query, params)
                
                updated = cur.fetchone()
                
                if not updated:
                    raise HTTPException(status_code=404, detail=f"No policies found for mode: {mode}")
        
        logger.info("policies_updated", mode=mode)
        return {"status": "success", "policies": dict(updated)}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error("update_policies_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/performance")
def get_strategy_performance(
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    period_days: Optional[int] = Query(14, description="Time period in days (7, 14, or 30)"),
    min_trades: Optional[int] = Query(3, description="Minimum number of trades required"),
    limit: Optional[int] = Query(50, description="Maximum number of results")
):
    """Get strategy performance metrics (Phase 2)
    
    Returns performance metrics for strategies sorted by win rate.
    Can be filtered by symbol and time period.
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Build query with optional filters
                where_clauses = ["sp.period_days = %s", "sp.total_trades >= %s"]
                params = [period_days, min_trades]
                
                if symbol:
                    where_clauses.append("sp.symbol = %s")
                    params.append(symbol)
                
                where_clause = " AND ".join(where_clauses)
                params.append(limit)
                
                query = f"""
                    SELECT 
                        sp.strategy_id,
                        s.name as strategy_name,
                        sp.symbol,
                        sp.period_days,
                        sp.total_signals,
                        sp.signals_acted_on,
                        sp.total_trades,
                        sp.winning_trades,
                        sp.losing_trades,
                        sp.win_rate,
                        sp.total_pnl,
                        sp.avg_profit_pct,
                        sp.max_profit_pct,
                        sp.max_loss_pct,
                        sp.sharpe_ratio,
                        sp.profit_factor,
                        sp.updated_at,
                        sp.period_start,
                        sp.period_end
                    FROM strategy_performance sp
                    JOIN strategies s ON sp.strategy_id = s.id
                    WHERE {where_clause}
                    ORDER BY sp.win_rate DESC, sp.total_trades DESC
                    LIMIT %s
                """
                
                cur.execute(query, params)
                performances = cur.fetchall()
                
                # Get summary statistics
                cur.execute(f"""
                    SELECT 
                        COUNT(DISTINCT sp.strategy_id) as total_strategies,
                        AVG(sp.win_rate) as avg_win_rate,
                        SUM(sp.total_trades) as total_trades,
                        MAX(sp.win_rate) as max_win_rate
                    FROM strategy_performance sp
                    WHERE {where_clause.replace('LIMIT %s', '')}
                """, params[:-1])  # Exclude limit parameter for summary
                
                summary = cur.fetchone()
                
                # Get top strategy name
                top_strategy = None
                if performances:
                    top_strategy = performances[0]['strategy_name']
        
        return {
            "status": "success",
            "summary": {
                "total_strategies": summary['total_strategies'] or 0,
                "avg_win_rate": round(float(summary['avg_win_rate'] or 0), 2),
                "total_trades": summary['total_trades'] or 0,
                "top_strategy": top_strategy
            },
            "performances": [dict(p) for p in performances],
            "filters": {
                "symbol": symbol,
                "period_days": period_days,
                "min_trades": min_trades
            }
        }
    
    except Exception as e:
        logger.error("get_performance_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    port = 8020  # New port for Strategy Config API
    uvicorn.run("services.strategy_config_api.main:app", host="0.0.0.0", port=port, workers=4)
