"""Signal API - Real-time Trading Signal Generation"""
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.database import get_connection, get_candles, get_active_strategies
from shared.config import get_settings
from shared.logging_config import setup_logging

settings = get_settings()
logger = setup_logging('signal_api', settings.log_level)

app = FastAPI(title="Signal API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Signal(BaseModel):
    id: int
    symbol: str
    strategy_id: int
    signal_type: str
    quality_score: int
    quality_breakdown: Dict
    projected_return_pct: float
    projected_timeframe_minutes: int
    price_at_signal: float
    generated_at: datetime
    expires_at: Optional[datetime] = None
    acted_on: bool = False

@app.get("/")
def root():
    return {"service": "Signal API", "status": "running", "version": "1.0.0"}

@app.get("/health")
def health():
    return {"status": "healthy"}

def check_has_performance_data() -> bool:
    """Check if strategy_performance table has sufficient data
    
    Returns True if we have at least one strategy with 5+ trades
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(*) as count
                    FROM strategy_performance
                    WHERE total_trades >= 5
                """)
                result = cur.fetchone()
                return result['count'] > 0 if result else False
    except Exception as e:
        logger.error("performance_check_error", error=str(e))
        return False

@app.get("/signals/active", response_model=List[Signal])
def get_active_signals(min_quality: int = Query(60, ge=0, le=100)):
    """Get active signals above quality threshold"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT * FROM signals
                    WHERE NOT acted_on 
                    AND expires_at > NOW()
                    AND quality_score >= %s
                    ORDER BY quality_score DESC, generated_at DESC
                    LIMIT 20
                """, (min_quality,))
                
                signals = [dict(row) for row in cur.fetchall()]
        
        logger.info("active_signals_fetched", count=len(signals))
        return signals
    
    except Exception as e:
        logger.error("fetch_signals_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/signals/recent", response_model=List[Signal])
def get_recent_signals(
    strategy_id: Optional[int] = Query(None),
    symbol: Optional[str] = Query(None),
    hours: int = Query(24, ge=1, le=168),
    min_quality: int = Query(0, ge=0, le=100),
    limit: int = Query(50, ge=1, le=500)
):
    """Get recent signals (including expired), filterable by symbol and/or strategy"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                conditions = [
                    "generated_at > NOW() - INTERVAL '%s hours'",
                    "quality_score >= %s",
                ]
                params = [hours, min_quality]
                if strategy_id:
                    conditions.append("strategy_id = %s")
                    params.append(strategy_id)
                if symbol:
                    conditions.append("symbol = %s")
                    params.append(symbol.upper())
                params.append(limit)
                where_clause = ' AND '.join(conditions)
                cur.execute(
                    f"SELECT * FROM signals WHERE {where_clause}"
                    f" ORDER BY generated_at DESC LIMIT %s",
                    params
                )
                
                signals = [dict(row) for row in cur.fetchall()]
        
        logger.info("recent_signals_fetched", count=len(signals), strategy_id=strategy_id)
        return signals
    
    except Exception as e:
        logger.error("fetch_recent_signals_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/signals/generate")
async def generate_signals(
    symbol: Optional[str] = None,
    force: bool = False
):
    """Generate new trading signals"""
    try:
        # Get active strategies
        strategies = get_active_strategies()
        
        if not strategies:
            return {
                "status": "warning",
                "message": "No active strategies found",
                "signals_generated": 0
            }
        
        # Get symbols to analyze (all or specific)
        if symbol:
            symbols_to_analyze = [symbol]
        else:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT symbol FROM symbols WHERE status = 'active'")
                    symbols_to_analyze = [row['symbol'] for row in cur.fetchall()]
        
        signals_generated = 0
        
        for sym in symbols_to_analyze:
            # Get recent candles
            end_date = datetime.now()
            start_date = end_date - timedelta(hours=24)
            candles = get_candles(sym, start_date, end_date, limit=100)
            
            if len(candles) < 10:
                logger.warning("insufficient_data", symbol=sym)
                continue
            
            # Evaluate each strategy
            for strategy in strategies:
                signal = evaluate_strategy(sym, strategy, candles)
                
                if signal and (signal['quality_score'] >= settings.min_signal_quality or force):
                    # Save signal
                    with get_connection() as conn:
                        with conn.cursor() as cur:
                            import psycopg2.extras
                            cur.execute("""
                                INSERT INTO signals 
                                (symbol, strategy_id, signal_type, quality_score, 
                                 quality_breakdown, projected_return_pct, 
                                 projected_timeframe_minutes, price_at_signal, 
                                 generated_at, expires_at)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW() + INTERVAL '30 minutes')
                                RETURNING id
                            """, (
                                signal['symbol'],
                                signal['strategy_id'],
                                signal['signal_type'],
                                signal['quality_score'],
                                psycopg2.extras.Json(signal['quality_breakdown']),
                                signal['projected_return_pct'],
                                signal['projected_timeframe_minutes'],
                                signal['price_at_signal']
                            ))
                            signals_generated += 1
        
        logger.info("signals_generated", count=signals_generated)
        
        return {
            "status": "success",
            "signals_generated": signals_generated,
            "symbols_analyzed": len(symbols_to_analyze),
            "strategies_evaluated": len(strategies)
        }
    
    except Exception as e:
        logger.error("generate_signals_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

def get_strategy_parameters(strategy_id: int, symbol: str) -> Dict:
    """Get strategy parameters with symbol-specific overrides applied"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Get baseline parameters
            cur.execute("""
                SELECT parameters, risk_management
                FROM strategies
                WHERE id = %s
            """, (strategy_id,))
            
            strategy_data = cur.fetchone()
            if not strategy_data:
                return {}
            
            baseline_params = dict(strategy_data['parameters'] or {})
            baseline_risk = dict(strategy_data['risk_management'] or {})
            
            # Check for symbol-specific overrides
            cur.execute("""
                SELECT parameter_overrides, risk_overrides
                FROM strategy_overrides
                WHERE strategy_id = %s AND symbol = %s
            """, (strategy_id, symbol))
            
            override = cur.fetchone()
            
            if override:
                # Merge overrides with baseline
                param_overrides = dict(override['parameter_overrides'] or {})
                risk_overrides = dict(override['risk_overrides'] or {})
                
                merged_params = {**baseline_params, **param_overrides}
                merged_risk = {**baseline_risk, **risk_overrides}
            else:
                merged_params = baseline_params
                merged_risk = baseline_risk
            
            return {
                **merged_params,
                'risk_management': merged_risk
            }

# ─── Charts-format condition evaluator ──────────────────────────────────────
# Charts strategies store entry conditions as:
#   { "entry": { "direction": "long", "logic": "AND",
#                "conditions": [{"id":"ema_cross_up","enabled":true,"params":{...}}] },
#     "source": "charts_import" }
# The legacy evaluator only reads buy_conditions[], so charts strategies never fired.
# These helpers translate charts condition IDs to available indicator data.

def _ema_for_candles(candles: List[Dict], period: int, idx: int = -1) -> Optional[float]:
    """Compute EMA(period) at candle[idx] on-the-fly from closing prices."""
    needed = max(period * 2, period + 10)
    start  = max(0, len(candles) + idx - needed + 1)
    closes = [float(c.get('close', 0)) for c in candles[start: len(candles) + idx + 1 if idx < 0 else idx + 1]]
    if len(closes) < period:
        return None
    k   = 2.0 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = price * k + ema * (1 - k)
    return ema


def _vol_avg(candles: List[Dict], lookback: int = 20) -> Optional[float]:
    """Simple average volume over the previous `lookback` bars (excluding latest)."""
    vols = [float(c.get('volume', 0)) for c in candles[-lookback - 1:-1] if c.get('volume')]
    return sum(vols) / len(vols) if vols else None


def _eval_charts_cond(cid: str, params: Dict, candles: List[Dict],
                      curr: Dict, prev: Dict,
                      c_ind: Dict, p_ind: Dict) -> Optional[bool]:
    """Evaluate a single charts condition. Returns True/False or None if data missing."""
    c_close = float(curr.get('close', 0))
    p_close = float(prev.get('close', 0))

    if cid == 'ema_cross_up':
        fast, slow = params.get('fast', 9), params.get('slow', 21)
        cf, cs = _ema_for_candles(candles, fast, -1), _ema_for_candles(candles, slow, -1)
        pf, ps = _ema_for_candles(candles, fast, -2), _ema_for_candles(candles, slow, -2)
        if None in (cf, cs, pf, ps): return None
        return cf > cs and pf <= ps

    elif cid == 'ema_cross_down':
        fast, slow = params.get('fast', 9), params.get('slow', 21)
        cf, cs = _ema_for_candles(candles, fast, -1), _ema_for_candles(candles, slow, -1)
        pf, ps = _ema_for_candles(candles, fast, -2), _ema_for_candles(candles, slow, -2)
        if None in (cf, cs, pf, ps): return None
        return cf < cs and pf >= ps

    elif cid == 'ema_above_slow':
        fast, slow = params.get('fast', 9), params.get('slow', 21)
        cf, cs = _ema_for_candles(candles, fast), _ema_for_candles(candles, slow)
        if None in (cf, cs): return None
        return cf > cs

    elif cid == 'ema_below_slow':
        fast, slow = params.get('fast', 9), params.get('slow', 21)
        cf, cs = _ema_for_candles(candles, fast), _ema_for_candles(candles, slow)
        if None in (cf, cs): return None
        return cf < cs

    elif cid == 'ema_slope_up':
        period   = params.get('period', 21)
        lookback = params.get('lookback', 3)
        curr_e   = _ema_for_candles(candles, period, -1)
        prev_e   = _ema_for_candles(candles, period, -1 - lookback)
        if None in (curr_e, prev_e): return None
        return curr_e > prev_e

    elif cid == 'ema_slope_down':
        period   = params.get('period', 21)
        lookback = params.get('lookback', 3)
        curr_e   = _ema_for_candles(candles, period, -1)
        prev_e   = _ema_for_candles(candles, period, -1 - lookback)
        if None in (curr_e, prev_e): return None
        return curr_e < prev_e

    elif cid == 'price_above_ema':
        period = params.get('period', 21)
        ema    = _ema_for_candles(candles, period)
        if ema is None: return None
        return c_close > ema

    elif cid == 'price_below_ema':
        period = params.get('period', 21)
        ema    = _ema_for_candles(candles, period)
        if ema is None: return None
        return c_close < ema

    elif cid == 'macd_hist_pos':
        v = c_ind.get('MACDh_12_26_9')
        if v is None: return None
        return float(v) > 0

    elif cid == 'macd_hist_neg':
        v = c_ind.get('MACDh_12_26_9')
        if v is None: return None
        return float(v) < 0

    elif cid == 'macd_above_signal':
        m = c_ind.get('MACD_12_26_9'); s = c_ind.get('MACDs_12_26_9')
        if None in (m, s): return None
        return float(m) > float(s)

    elif cid == 'macd_below_signal':
        m = c_ind.get('MACD_12_26_9'); s = c_ind.get('MACDs_12_26_9')
        if None in (m, s): return None
        return float(m) < float(s)

    elif cid == 'rsi_in_zone':
        period = params.get('period', 14)
        rsi = c_ind.get(f'RSI_{period}')
        if rsi is None: return None
        return params.get('min', 40) <= float(rsi) <= params.get('max', 65)

    elif cid == 'rsi_oversold':
        period = params.get('period', 14)
        rsi = c_ind.get(f'RSI_{period}')
        if rsi is None: return None
        return float(rsi) < params.get('level', 30)

    elif cid == 'rsi_overbought':
        period = params.get('period', 14)
        rsi = c_ind.get(f'RSI_{period}')
        if rsi is None: return None
        return float(rsi) > params.get('level', 70)

    elif cid == 'price_above_vwap':
        vwap = c_ind.get('VWAP_D') or c_ind.get('VWAP')
        if vwap is None: return None
        return c_close > float(vwap)

    elif cid == 'price_below_vwap':
        vwap = c_ind.get('VWAP_D') or c_ind.get('VWAP')
        if vwap is None: return None
        return c_close < float(vwap)

    elif cid == 'volume_spike':
        mult    = params.get('multiplier', 1.5)
        avg_vol = _vol_avg(candles, 20)
        if avg_vol is None or avg_vol == 0: return None
        return float(curr.get('volume', 0)) > avg_vol * mult

    elif cid == 'higher_high':
        lookback = params.get('lookback', 5)
        prev_highs = [float(c.get('high', 0)) for c in candles[-lookback - 1:-1]]
        if not prev_highs: return None
        return float(curr.get('high', 0)) > max(prev_highs)

    elif cid == 'lower_low':
        lookback = params.get('lookback', 5)
        prev_lows = [float(c.get('low', 0)) for c in candles[-lookback - 1:-1]]
        if not prev_lows: return None
        return float(curr.get('low', 0)) < min(prev_lows)

    elif cid == 'adx_trending':
        # ADX pre-computed or skip (ADX requires DM+/DM- over many bars)
        period    = params.get('period', 14)
        threshold = params.get('threshold', 25)
        adx = c_ind.get(f'ADX_{period}') or c_ind.get('ADX_14')
        if adx is None: return None  # not pre-computed — skip
        return float(adx) > threshold

    elif cid == 'adx_above':
        period    = params.get('period', 14)
        threshold = params.get('threshold', 25)
        adx = c_ind.get(f'ADX_{period}') or c_ind.get('ADX_14')
        if adx is None: return None
        return float(adx) > threshold

    elif cid == 'bb_squeeze':
        period  = params.get('period', 20)
        k       = params.get('k', 2.0)
        pct     = params.get('pct', 0.5)
        bbu = c_ind.get(f'BBU_{period}_{float(k)}') or c_ind.get(f'BBU_{period}_{k}')
        bbl = c_ind.get(f'BBL_{period}_{float(k)}') or c_ind.get(f'BBL_{period}_{k}')
        bbm = c_ind.get(f'BBM_{period}_{float(k)}') or c_ind.get(f'BBM_{period}_{k}')
        if None in (bbu, bbl, bbm) or float(bbm) == 0: return None
        bw = (float(bbu) - float(bbl)) / float(bbm)
        # "squeeze" = bandwidth below pct of typical range → BB are tight
        lb = params.get('lookback', 20)
        return bw < pct  # simplified: narrow band = squeeze

    # Gate conditions — treat as pass-through (always True) since they can't be
    # evaluated without a full bar-level scan.
    elif cid in ('regime_tradeable', 'forecast_clears_fees', 'atr_breakout',
                 'vol_expansion', 'regime_is'):
        return True  # cannot evaluate these without full bar history — do not block

    return None  # unknown condition — skip


def evaluate_charts_strategy(symbol: str, strategy: Dict, candles: List[Dict]) -> Optional[Dict]:
    """Evaluate a charts-imported strategy (source='charts_import').

    The indicator_logic has the shape:
        { "entry": { "direction", "logic", "conditions": [...] },
          "exit": {...}, "risk": {...}, "source": "charts_import" }
    """
    try:
        if len(candles) < 2:
            return None

        indicator_logic = strategy.get('indicator_logic', {})
        entry = indicator_logic.get('entry', {})
        conditions = [c for c in entry.get('conditions', []) if c.get('enabled', True)]
        if not conditions:
            return None

        logic     = entry.get('logic', 'AND').upper()
        direction = entry.get('direction', 'long').lower()

        curr  = candles[-1]
        prev  = candles[-2]
        c_ind = curr.get('indicators') or {}
        p_ind = prev.get('indicators') or {}

        current_price = float(curr.get('close', 0))

        results = []
        for cond in conditions:
            r = _eval_charts_cond(
                cond.get('id', ''), cond.get('params', {}),
                candles, curr, prev, c_ind, p_ind
            )
            results.append(r)

        # Definitive results only (exclude None = data missing)
        known = [r for r in results if r is not None]
        if not known:
            return None

        if logic == 'AND':
            fired = all(known) and len(known) == len(results)  # all must be true + no unknowns
        else:  # OR
            fired = any(known)

        if not fired:
            return None

        signal_type = 'BUY' if direction == 'long' else 'SELL'

        # Quality: boosts for RSI confirmation
        quality_score = 68
        rsi = c_ind.get('RSI_14')
        if rsi is not None:
            rsi = float(rsi)
            if signal_type == 'BUY' and rsi < 50:
                quality_score = min(88, 68 + int((50 - rsi) * 0.8))
            elif signal_type == 'SELL' and rsi > 50:
                quality_score = min(88, 68 + int((rsi - 50) * 0.8))

        return {
            'symbol':                    symbol,
            'strategy_id':               strategy['id'],
            'signal_type':               signal_type,
            'quality_score':             quality_score,
            'quality_breakdown':         {'backtest': 25, 'sentiment': 15,
                                          'historical': 18, 'ai_intuition': 10},
            'projected_return_pct':      2.5 if signal_type == 'BUY' else -2.0,
            'projected_timeframe_minutes': 120,
            'price_at_signal':           current_price,
        }

    except Exception as e:
        logger.error('evaluate_charts_strategy_error', symbol=symbol,
                     strategy=strategy.get('name'), error=str(e))
        return None


def evaluate_strategy(symbol: str, strategy: Dict, candles: List[Dict]) -> Optional[Dict]:
    """Evaluate a strategy against recent candles using dynamic indicator_logic"""
    try:
        if len(candles) == 0:
            return None

        # Route charts-imported strategies to dedicated evaluator
        indicator_logic = strategy.get('indicator_logic', {})
        if indicator_logic.get('source') == 'charts_import':
            return evaluate_charts_strategy(symbol, strategy, candles)

        latest_candle = candles[-1]
        current_price = float(latest_candle['close'])
        
        # Get strategy parameters with symbol overrides
        params = get_strategy_parameters(strategy['id'], symbol)
        
        # Get indicators from latest candle
        indicators = latest_candle.get('indicators', {})
        
        if not indicators:
            return None
        
        # Parse indicator_logic from strategy
        buy_conditions = indicator_logic.get('buy_conditions', [])
        sell_conditions = indicator_logic.get('sell_conditions', [])
        
        signal_type = None
        quality_score = 50
        
        # Helper function to get indicator value from candle
        def get_indicator_value(indicator_name: str, indicators: Dict, params: Dict) -> Optional[float]:
            """Map indicator name to actual value in candle indicators"""
            indicator = indicator_name.upper()
            
            # RSI - use period from params
            if indicator == 'RSI':
                rsi_period = params.get('rsi_period', 14)
                key = f'RSI_{rsi_period}'
                return indicators.get(key)
            
            # MACD
            elif indicator == 'MACD':
                return indicators.get('MACD_12_26_9')
            elif indicator == 'MACD_SIGNAL' or indicator == 'MACDS':
                return indicators.get('MACDs_12_26_9')
            elif indicator == 'MACD_HISTOGRAM' or indicator == 'MACDH':
                return indicators.get('MACDh_12_26_9')
            
            # Bollinger Bands
            elif indicator == 'BB_UPPER' or indicator == 'BBU':
                bb_period = params.get('bb_period', 20)
                bb_std = params.get('bb_std', 2.0)
                return indicators.get(f'BBU_{bb_period}_{bb_std}')
            elif indicator == 'BB_LOWER' or indicator == 'BBL':
                bb_period = params.get('bb_period', 20)
                bb_std = params.get('bb_std', 2.0)
                return indicators.get(f'BBL_{bb_period}_{bb_std}')
            elif indicator == 'BB_MIDDLE' or indicator == 'BBM':
                bb_period = params.get('bb_period', 20)
                bb_std = params.get('bb_std', 2.0)
                return indicators.get(f'BBM_{bb_period}_{bb_std}')
            
            # SMA
            elif indicator == 'SMA' or indicator == 'SMA_20':
                return indicators.get('SMA_20')
            elif indicator == 'SMA_50':
                return indicators.get('SMA_50')
            
            # EMA
            elif indicator == 'EMA' or indicator == 'EMA_12':
                return indicators.get('EMA_12')
            elif indicator == 'EMA_26':
                return indicators.get('EMA_26')
            
            # ATR
            elif indicator == 'ATR':
                atr_period = params.get('atr_period', 14)
                return indicators.get(f'ATR_{atr_period}', indicators.get('ATR_14'))
            
            # VWAP (Volume Weighted Average Price)
            elif indicator == 'VWAP':
                return indicators.get('VWAP_D')
            
            # Price-based (from candle, not indicators)
            elif indicator == 'CLOSE':
                return float(latest_candle.get('close', 0))
            elif indicator == 'OPEN':
                return float(latest_candle.get('open', 0))
            elif indicator == 'HIGH':
                return float(latest_candle.get('high', 0))
            elif indicator == 'LOW':
                return float(latest_candle.get('low', 0))
            
            return None
        
        # Helper function to evaluate a condition
        def evaluate_condition(condition: Dict, indicators: Dict, params: Dict) -> bool:
            """Evaluate a single condition"""
            indicator = condition.get('indicator', '').upper()
            operator = condition.get('operator', '')
            threshold = condition.get('value')
            
            # Get the indicator value
            indicator_value = get_indicator_value(indicator, indicators, params)
            
            if indicator_value is None:
                return False
            
            # Handle special case: comparing against another indicator (e.g., close > BB_UPPER)
            if isinstance(threshold, str):
                threshold_value = get_indicator_value(threshold, indicators, params)
                if threshold_value is None:
                    return False
                threshold = threshold_value
            else:
                threshold = float(threshold)
                
                # Override threshold with parameter values for RSI
                if indicator == 'RSI':
                    if operator == '<':
                        threshold = float(params.get('rsi_oversold', threshold))
                    elif operator == '>':
                        threshold = float(params.get('rsi_overbought', threshold))
            
            # Evaluate based on operator
            if operator == '<':
                return indicator_value < threshold
            elif operator == '>':
                return indicator_value > threshold
            elif operator == '<=':
                return indicator_value <= threshold
            elif operator == '>=':
                return indicator_value >= threshold
            elif operator == '==' or operator == '=':
                return abs(indicator_value - threshold) < 0.01
            
            return False
        
        # Check BUY conditions (all must be true)
        if buy_conditions:
            buy_signal = True
            for condition in buy_conditions:
                if not evaluate_condition(condition, indicators, params):
                    buy_signal = False
                    break
            
            if buy_signal:
                signal_type = "BUY"
                # Calculate quality based on how extreme the conditions are
                # Tightened after after-action: 4 false signals with good scores
                rsi_value = get_indicator_value('RSI', indicators, params)
                if rsi_value is not None:
                    rsi_oversold = float(params.get('rsi_oversold', 30))
                    if rsi_value < rsi_oversold:
                        # More extreme = higher quality, but cap at 95 (was 100)
                        quality_score = min(95, 70 + int((rsi_oversold - rsi_value) * 2))
                    else:
                        quality_score = 65  # Reduced from 70
                else:
                    quality_score = 65  # Reduced from 70
        
        # Check SELL conditions (all must be true)
        if not signal_type and sell_conditions:
            sell_signal = True
            for condition in sell_conditions:
                if not evaluate_condition(condition, indicators, params):
                    sell_signal = False
                    break
            
            if sell_signal:
                signal_type = "SELL"
                # Calculate quality based on how extreme the conditions are
                # Tightened after after-action: 4 false signals with good scores
                rsi_value = get_indicator_value('RSI', indicators, params)
                if rsi_value is not None:
                    rsi_overbought = float(params.get('rsi_overbought', 70))
                    if rsi_value > rsi_overbought:
                        # More extreme = higher quality, but cap at 90 (was 100)
                        quality_score = min(90, 65 + int((rsi_value - rsi_overbought) * 2))
                    else:
                        quality_score = 60  # Reduced from 65
                else:
                    quality_score = 60  # Reduced from 65
        
        # Only return BUY/SELL signals
        if not signal_type:
            return None
        
        # Calculate quality breakdown
        quality_breakdown = {
            "backtest": 25,  # Would come from backtests table
            "sentiment": 15,  # Would come from sentiment analysis
            "historical": 18,  # Would come from pattern analysis
            "ai_intuition": 10,  # Would come from AI API
            "price_action": 7   # Based on current momentum
        }
        
        return {
            "symbol": symbol,
            "strategy_id": strategy['id'],
            "signal_type": signal_type,
            "quality_score": quality_score,
            "quality_breakdown": quality_breakdown,
            "projected_return_pct": 2.5 if signal_type == "BUY" else -2.0,
            "projected_timeframe_minutes": 120,
            "price_at_signal": current_price
        }
    
    except Exception as e:
        logger.error("evaluate_strategy_error", symbol=symbol, strategy=strategy.get('name'), error=str(e))
        return None

@app.get("/signals/stats")
def get_signal_stats():
    """Get signal generation statistics"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Total signals
                cur.execute("SELECT COUNT(*) as count FROM signals")
                total = cur.fetchone()['count']
                
                # Active signals
                cur.execute("""
                    SELECT COUNT(*) as count FROM signals
                    WHERE NOT acted_on AND expires_at > NOW()
                """)
                active = cur.fetchone()['count']
                
                # Signals by type
                cur.execute("""
                    SELECT signal_type, COUNT(*) as count
                    FROM signals
                    WHERE generated_at > NOW() - INTERVAL '24 hours'
                    GROUP BY signal_type
                """)
                by_type = {row['signal_type']: row['count'] for row in cur.fetchall()}
                
                # Average quality
                cur.execute("""
                    SELECT AVG(quality_score) as avg_quality
                    FROM signals
                    WHERE generated_at > NOW() - INTERVAL '24 hours'
                """)
                avg_quality = cur.fetchone()['avg_quality'] or 0
        
        return {
            "status": "success",
            "total_signals": total,
            "active_signals": active,
            "signals_24h_by_type": by_type,
            "avg_quality_24h": float(avg_quality)
        }
    
    except Exception as e:
        logger.error("stats_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

# Strategy Management Endpoints
@app.get("/strategies")
def get_strategies():
    """Get all strategies with enriched data"""
    try:
        strategies = get_active_strategies()
        
        # Add signal counts and optimization status for each
        with get_connection() as conn:
            with conn.cursor() as cur:
                for strategy in strategies:
                    strategy_id = strategy['id']
                    
                    # Get 24h signal count and last signal timestamp
                    cur.execute("""
                        SELECT 
                            COUNT(*) as count,
                            MAX(generated_at) as last_signal_at
                        FROM signals
                        WHERE strategy_id = %s 
                        AND generated_at > NOW() - INTERVAL '24 hours'
                    """, (strategy_id,))
                    signal_data = cur.fetchone()
                    strategy['signals_24h'] = signal_data['count']
                    strategy['last_signal_at'] = signal_data['last_signal_at'].isoformat() if signal_data['last_signal_at'] else None
                    
                    # Get optimization status (lightweight)
                    cur.execute("""
                        SELECT 
                            MAX(created_at) as last_optimized,
                            COUNT(*) FILTER (WHERE status = 'promoted') as promoted_count
                        FROM parameter_versions
                        WHERE strategy_id = %s
                    """, (strategy_id,))
                    opt_data = cur.fetchone()
                    strategy['last_optimized'] = opt_data['last_optimized'].isoformat() if opt_data['last_optimized'] else None
                    strategy['promoted_count'] = opt_data['promoted_count']
                    
                    # Get open positions count
                    cur.execute("""
                        SELECT COUNT(*) as count
                        FROM positions
                        WHERE strategy_id = %s AND status = 'open'
                    """, (strategy_id,))
                    strategy['open_positions_count'] = cur.fetchone()['count']
        
        return {"status": "success", "strategies": strategies}
    except Exception as e:
        logger.error("get_strategies_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/strategies/create")
async def create_strategy(
    name: str = Query(...),
    description: str = Query(""),
    indicator_logic: str = Query(...),
    parameters: str = Query("{}"),
    created_by: str = Query("manual")
):
    """Create a new strategy"""
    try:
        import json
        import psycopg2.extras
        
        logic = json.loads(indicator_logic)
        params = json.loads(parameters)
        
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO strategies (name, description, indicator_logic, parameters, created_by)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                """, (name, description, psycopg2.extras.Json(logic), 
                      psycopg2.extras.Json(params), created_by))
                
                strategy_id = cur.fetchone()['id']
        
        logger.info("strategy_created", id=strategy_id, name=name)
        return {"status": "success", "strategy_id": strategy_id}
    
    except Exception as e:
        logger.error("create_strategy_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/strategies/{strategy_id}/toggle")
async def toggle_strategy(strategy_id: int):
    """Enable/disable a strategy"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE strategies 
                    SET enabled = NOT enabled
                    WHERE id = %s
                    RETURNING enabled
                """, (strategy_id,))
                
                result = cur.fetchone()
                if not result:
                    raise HTTPException(status_code=404, detail="Strategy not found")
                
                enabled = result['enabled']
        
        logger.info("strategy_toggled", id=strategy_id, enabled=enabled)
        return {"status": "success", "enabled": enabled}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error("toggle_strategy_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/strategies/{strategy_id}")
async def delete_strategy(strategy_id: int):
    """Delete a strategy"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM strategies WHERE id = %s RETURNING id", (strategy_id,))
                
                if cur.rowcount == 0:
                    raise HTTPException(status_code=404, detail="Strategy not found")
        
        logger.info("strategy_deleted", id=strategy_id)
        return {"status": "success"}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error("delete_strategy_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/signals/ensemble")
async def get_ensemble_signals(
    min_weighted_score: float = Query(70.0, ge=0.0, le=200.0, description="Minimum weighted score threshold"),
    period_days: int = Query(14, ge=7, le=30, description="Performance lookback period (7, 14, or 30 days)"),
    limit: int = Query(10, ge=1, le=50, description="Maximum number of signals to return")
):
    """Get performance-weighted ensemble signals (Phase 3)
    
    This endpoint aggregates all active signals and weights them by recent strategy performance.
    Signals from strategies with higher win rates get boosted scores.
    
    Formula: weighted_score = base_quality * (1 + (win_rate - 0.5))
    
    Example:
    - Strategy with 75% win rate and 70 quality signal: 70 * (1 + (0.75 - 0.5)) = 87.5
    - Strategy with 50% win rate and 70 quality signal: 70 * (1 + (0.50 - 0.5)) = 70.0
    - Strategy with 30% win rate and 70 quality signal: 70 * (1 + (0.30 - 0.5)) = 56.0
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Get all active signals (not acted on, not expired)
                cur.execute("""
                    SELECT 
                        s.*,
                        st.name as strategy_name
                    FROM signals s
                    JOIN strategies st ON s.strategy_id = st.id
                    WHERE s.acted_on = false
                    AND s.expires_at > NOW()
                    ORDER BY s.quality_score DESC
                """)
                
                signals = [dict(row) for row in cur.fetchall()]
                
                if not signals:
                    return {
                        "status": "success",
                        "ensemble_signals": [],
                        "total_active_signals": 0,
                        "filtered_signals": 0,
                        "parameters": {
                            "min_weighted_score": min_weighted_score,
                            "period_days": period_days,
                            "limit": limit
                        }
                    }
                
                # CONSENSUS DETECTION: Count how many strategies agree on same symbol+direction
                # Group signals by (symbol, signal_type) to detect consensus
                signal_groups = {}
                for signal in signals:
                    key = (signal['symbol'], signal['signal_type'])
                    if key not in signal_groups:
                        signal_groups[key] = []
                    signal_groups[key].append(signal)
                
                # Tag each signal with consensus information
                for signal in signals:
                    key = (signal['symbol'], signal['signal_type'])
                    consensus_count = len(signal_groups[key])
                    signal['consensus_count'] = consensus_count
                    signal['has_consensus'] = consensus_count >= 2
                
                # Log discovered consensus
                consensus_groups = {k: v for k, v in signal_groups.items() if len(v) >= 2}
                if consensus_groups:
                    logger.info("consensus_detected",
                               groups=[(symbol, direction, len(sigs)) for (symbol, direction), sigs in consensus_groups.items()])
                
                # For live signals, always use the configured threshold (no bootstrap mode)
                # Bootstrap mode is only for backtests to allow historical testing
                effective_threshold = min_weighted_score
                
                # Get performance data for all strategies
                strategy_ids = list(set(s['strategy_id'] for s in signals))
                
                cur.execute("""
                    SELECT 
                        strategy_id,
                        symbol,
                        win_rate,
                        total_trades,
                        total_signals,
                        sharpe_ratio,
                        profit_factor
                    FROM strategy_performance
                    WHERE strategy_id = ANY(%s)
                    AND period_days = %s
                """, (strategy_ids, period_days))
                
                performance_data = {}
                for row in cur.fetchall():
                    key = (row['strategy_id'], row['symbol'])
                    performance_data[key] = dict(row)
                
                # Calculate weighted scores
                ensemble_signals = []
                
                for signal in signals:
                    key = (signal['strategy_id'], signal['symbol'])
                    perf = performance_data.get(key)
                    
                    base_quality = signal['quality_score']
                    
                    # BALANCED FIX: Require minimum 5 trades for performance weighting
                    # Was 10: Too restrictive, blocked most strategy-symbol combos
                    # Was 3: Too permissive, caused fake 100% win rates (bootstrap trap)
                    # Now 5: Balance between statistical relevance and allowing learned performance
                    if perf and perf['win_rate'] is not None and perf['total_trades'] >= 5:
                        # Have performance data with statistically meaningful sample
                        win_rate = float(perf['win_rate']) / 100.0  # Convert percentage to decimal
                        weight_multiplier = 1 + (win_rate - 0.5)
                        weighted_score = base_quality * weight_multiplier
                        
                        confidence_level = "high" if win_rate >= 0.60 else "medium" if win_rate >= 0.50 else "low"
                    else:
                        # No performance data or insufficient trades - use base quality only
                        # (Conservative: don't inflate scores from tiny samples)
                        weighted_score = base_quality
                        win_rate = None
                        confidence_level = "unknown"
                    
                    # Only include signals above threshold (uses effective_threshold in bootstrap mode)
                    if weighted_score >= effective_threshold:
                        ensemble_signals.append({
                            "signal_id": signal['id'],
                            "strategy_id": signal['strategy_id'],
                            "strategy_name": signal['strategy_name'],
                            "symbol": signal['symbol'],
                            "signal_type": signal['signal_type'],
                            "base_quality": base_quality,
                            "weighted_score": round(weighted_score, 2),
                            "win_rate": round(win_rate * 100, 2) if win_rate is not None else None,
                            "confidence_level": confidence_level,
                            "price_at_signal": float(signal['price_at_signal']),
                            "projected_return_pct": float(signal['projected_return_pct']),
                            "projected_timeframe_minutes": signal['projected_timeframe_minutes'],
                            "generated_at": signal['generated_at'].isoformat(),
                            "expires_at": signal['expires_at'].isoformat() if signal['expires_at'] else None,
                            "has_consensus": signal['has_consensus'],
                            "consensus_count": signal['consensus_count'],
                            "performance_data": {
                                "total_trades": perf['total_trades'] if perf else 0,
                                "sharpe_ratio": float(perf['sharpe_ratio']) if perf and perf['sharpe_ratio'] else None,
                                "profit_factor": float(perf['profit_factor']) if perf and perf['profit_factor'] else None
                            }
                        })
                
                # Sort by weighted score descending
                ensemble_signals.sort(key=lambda x: x['weighted_score'], reverse=True)
                
                # Apply limit
                ensemble_signals = ensemble_signals[:limit]
                
                logger.info("ensemble_signals_generated",
                           total_active=len(signals),
                           filtered=len(ensemble_signals),
                           min_weighted_score=min_weighted_score)
                
                return {
                    "status": "success",
                    "ensemble_signals": ensemble_signals,
                    "total_active_signals": len(signals),
                    "filtered_signals": len(ensemble_signals),
                    "parameters": {
                        "min_weighted_score": min_weighted_score,
                        "period_days": period_days,
                        "limit": limit
                    }
                }
    
    except Exception as e:
        logger.error("ensemble_signals_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/signals/consensus")
async def get_consensus_signals(
    min_strategies: int = Query(2, ge=2, le=5, description="Minimum strategies that must agree"),
    min_quality: int = Query(60, ge=50, le=90, description="Minimum quality score for signals to be considered"),
    supermajority_pct: float = Query(60.0, ge=50.0, le=80.0, description="Required vote percentage for consensus"),
    include_ai_vote: bool = Query(True, description="Include AI agent voting"),
    include_sentiment: bool = Query(True, description="Include news sentiment in voting"),
    limit: int = Query(5, ge=1, le=20, description="Maximum signals to return")
):
    """Get consensus signals with multi-strategy agreement + AI voting
    
    This endpoint implements true ensemble consensus:
    1. Groups signals by symbol - only considers symbols with multiple strategies agreeing
    2. Calls AI API for AI vote on each potential signal
    3. Optionally includes news sentiment analysis
    4. Applies weighted voting (strategies by win rate, AI weighted 1.5x, sentiment 1.0x)
    5. Returns only signals meeting supermajority threshold
    
    Example: Symbol AAVE/USDT with 3 BUY signals
    - Strategy A (70% win rate): weight = 1.2
    - Strategy B (55% win rate): weight = 1.05
    - Strategy C (45% win rate): weight = 0.95
    - AI Agent: weight = 1.5 (if voting BUY)
    - Total FOR: 4.7, Total POSSIBLE: 4.7 = 100% consensus ✓
    """
    try:
        import httpx
        
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Get all active signals grouped by symbol and signal type
                cur.execute("""
                    SELECT 
                        s.*,
                        st.name as strategy_name,
                        st.id as strategy_id
                    FROM signals s
                    JOIN strategies st ON s.strategy_id = st.id
                    WHERE s.acted_on = false
                    AND s.expires_at > NOW()
                    ORDER BY s.symbol, s.signal_type, s.quality_score DESC
                """)
                
                all_signals = [dict(row) for row in cur.fetchall()]
                
                # Filter out low quality signals before processing
                all_signals = [s for s in all_signals if s['quality_score'] >= min_quality]
                
                if not all_signals:
                    return {
                        "status": "success",
                        "consensus_signals": [],
                        "total_grouped": 0,
                        "message": f"No signals meet minimum quality threshold ({min_quality}+)",
                        "parameters": {
                            "min_strategies": min_strategies,
                            "min_quality": min_quality,
                            "supermajority_pct": supermajority_pct,
                            "include_ai_vote": include_ai_vote,
                            "include_sentiment": include_sentiment
                        }
                    }
                
                # Group signals by symbol + signal_type
                from collections import defaultdict
                grouped = defaultdict(list)
                
                for signal in all_signals:
                    key = (signal['symbol'], signal['signal_type'])
                    grouped[key].append(signal)
                
                # Filter to only groups with min_strategies agreement
                consensus_candidates = {}
                for (symbol, signal_type), signals in grouped.items():
                    if len(signals) >= min_strategies:
                        consensus_candidates[(symbol, signal_type)] = signals
                
                # IMPORTANT: Filter out SELL signals if we don't have an ENSEMBLE position
                # SELL signals can only close existing ensemble positions, not strategy positions
                filtered_candidates = {}
                for (symbol, signal_type), signals in consensus_candidates.items():
                    if signal_type.upper() == 'SELL':
                        # Check if we have an open ENSEMBLE position for this symbol
                        # Don't count strategy positions - those are for testing only
                        cur.execute("""
                            SELECT COUNT(*) as count
                            FROM positions
                            WHERE symbol = %s 
                            AND status = 'open'
                            AND mode = 'paper'
                            AND position_type = 'ensemble'
                        """, (symbol,))
                        has_ensemble_position = cur.fetchone()['count'] > 0
                        
                        if not has_ensemble_position:
                            logger.info("sell_signal_filtered_no_ensemble_position",
                                       symbol=symbol,
                                       strategy_count=len(signals),
                                       reason="Cannot sell - no open ENSEMBLE position (strategy positions don't count)")
                            continue  # Skip this SELL signal
                    
                    filtered_candidates[(symbol, signal_type)] = signals
                
                consensus_candidates = filtered_candidates
                
                # CRITICAL: Filter out conflicting BUY/SELL signals for the same symbol
                # If a symbol has both BUY and SELL signals, it indicates market indecision
                # This prevents rapid churn (buy/sell/buy/sell in quick succession)
                symbols_with_signals = {}
                for (symbol, signal_type), signals in consensus_candidates.items():
                    if symbol not in symbols_with_signals:
                        symbols_with_signals[symbol] = []
                    symbols_with_signals[symbol].append((signal_type, signals))
                
                conflict_filtered = {}
                for symbol, signal_types in symbols_with_signals.items():
                    if len(signal_types) > 1:
                        # This symbol has both BUY and SELL signals - conflict!
                        signal_type_names = [st[0] for st in signal_types]
                        
                        logger.warning("conflicting_signals_filtered",
                                     symbol=symbol,
                                     signal_types=signal_type_names,
                                     reason="Symbol has both BUY and SELL signals - market indecision, skipping both")
                        # Skip ALL signals for this symbol to avoid churn
                        continue
                    else:
                        # Only one signal type, safe to include
                        signal_type, signals = signal_types[0]
                        conflict_filtered[(symbol, signal_type)] = signals
                
                consensus_candidates = conflict_filtered
                
                logger.info("consensus_grouping", 
                           total_signals=len(all_signals),
                           symbols_with_consensus=len(consensus_candidates),
                           min_strategies=min_strategies)
                
                if not consensus_candidates:
                    return {
                        "status": "success",
                        "consensus_signals": [],
                        "total_grouped": len(grouped),
                        "message": f"No symbols with {min_strategies}+ agreeing strategies",
                        "parameters": {
                            "min_strategies": min_strategies,
                            "supermajority_pct": supermajority_pct
                        }
                    }
                
                # Get performance data for weighting
                strategy_ids = list(set(s['strategy_id'] for s in all_signals))
                cur.execute("""
                    SELECT 
                        strategy_id,
                        symbol,
                        win_rate,
                        total_trades
                    FROM strategy_performance
                    WHERE strategy_id = ANY(%s)
                    AND period_days = 14
                """, (strategy_ids,))
                
                performance_data = {}
                for row in cur.fetchall():
                    key = (row['strategy_id'], row['symbol'])
                    performance_data[key] = dict(row)
                
                # Process each consensus candidate
                consensus_signals = []
                
                for (symbol, signal_type), signals in consensus_candidates.items():
                    # Calculate strategy votes with performance weighting
                    total_weight = 0.0
                    total_possible = 0.0
                    strategy_votes = []
                    
                    for signal in signals:
                        key = (signal['strategy_id'], symbol)
                        perf = performance_data.get(key)
                        
                        # Calculate weight based on win rate
                        if perf and perf['win_rate'] is not None and perf['total_trades'] >= 3:
                            win_rate = float(perf['win_rate']) / 100.0
                            weight = 1 + (win_rate - 0.5)  # 0.5 to 1.5 range
                        else:
                            weight = 1.0  # Neutral weight for unproven strategies
                        
                        strategy_votes.append({
                            "strategy_name": signal['strategy_name'],
                            "quality": signal['quality_score'],
                            "weight": weight,
                            "win_rate": perf['win_rate'] if perf else None
                        })
                        
                        total_weight += weight
                        total_possible += weight
                    
                    # Get AI vote if enabled
                    ai_vote = None
                    if include_ai_vote:
                        try:
                            # Use best signal for AI voting request
                            best_signal = max(signals, key=lambda s: s['quality_score'])
                            
                            async with httpx.AsyncClient(timeout=10.0) as client:
                                response = await client.post(
                                    f"http://localhost:{settings.port_ai_api}/vote-signal",
                                    json={
                                        "symbol": symbol,
                                        "signal": signal_type,
                                        "quality_score": best_signal['quality_score'],
                                        "strategy_name": best_signal['strategy_name']
                                    }
                                )
                                
                                if response.status_code == 200:
                                    vote_data = response.json()
                                    ai_weight = 1.5  # AI gets 1.5x weight
                                    
                                    # Add AI vote weight (can be negative if AI votes against)
                                    total_weight += vote_data['vote_weight'] * ai_weight
                                    total_possible += ai_weight
                                    
                                    ai_vote = {
                                        "vote": vote_data['vote'],
                                        "weight": vote_data['vote_weight'] * ai_weight,
                                        "confidence": vote_data['confidence'],
                                        "reasoning": vote_data.get('reasoning', '')[:100]
                                    }
                                    
                                    logger.info("ai_vote_received", symbol=symbol, 
                                               vote=vote_data['vote'], 
                                               weight=vote_data['vote_weight'])
                        
                        except Exception as e:
                            logger.warning("ai_vote_error", symbol=symbol, error=str(e))
                            # Continue without AI vote
                    
                    # Get sentiment if enabled
                    sentiment_vote = None
                    if include_sentiment:
                        try:
                            async with httpx.AsyncClient(timeout=10.0) as client:
                                response = await client.get(
                                    f"http://localhost:{settings.port_ai_api}/sentiment/{symbol}"
                                )
                                
                                if response.status_code == 200:
                                    sentiment_data = response.json()
                                    sentiment = sentiment_data.get('sentiment', {})
                                    sentiment_score = sentiment.get('overall_score', 50)
                                    
                                    # Convert sentiment to vote weight
                                    # 0-100 scale: 0=very bearish, 50=neutral, 100=very bullish
                                    # Convert to -1 to +1: (score - 50) / 50
                                    sentiment_weight_raw = (sentiment_score - 50) / 50.0
                                    
                                    # Check if sentiment aligns with signal direction
                                    if signal_type == 'BUY':
                                        sentiment_weight = sentiment_weight_raw if sentiment_weight_raw > 0 else sentiment_weight_raw * 0.5
                                    else:  # SELL
                                        sentiment_weight = -sentiment_weight_raw if sentiment_weight_raw < 0 else -sentiment_weight_raw * 0.5
                                    
                                    sentiment_weight *= 1.0  # Sentiment gets 1.0x multiplier
                                    
                                    total_weight += sentiment_weight
                                    total_possible += 1.0
                                    
                                    sentiment_vote = {
                                        "score": sentiment_score,
                                        "weight": sentiment_weight,
                                        "recommendation": sentiment.get('recommendation', 'neutral'),
                                        "sources": sentiment.get('sources_analyzed', 0)
                                    }
                                    
                                    logger.info("sentiment_received", symbol=symbol, 
                                               score=sentiment_score, weight=sentiment_weight)
                        
                        except Exception as e:
                            logger.warning("sentiment_error", symbol=symbol, error=str(e))
                            # Continue without sentiment
                    
                    # Calculate consensus percentage
                    consensus_pct = (total_weight / total_possible * 100) if total_possible > 0 else 0
                    
                    # Check if meets supermajority threshold
                    if consensus_pct >= supermajority_pct:
                        # Get best signal details
                        best_signal = max(signals, key=lambda s: s['quality_score'])
                        
                        consensus_signals.append({
                            "symbol": symbol,
                            "signal_type": signal_type,
                            "consensus_pct": round(consensus_pct, 2),
                            "strategy_count": len(signals),
                            "best_quality": best_signal['quality_score'],
                            "avg_quality": round(sum(s['quality_score'] for s in signals) / len(signals), 2),
                            "price_at_signal": float(best_signal['price_at_signal']),
                            "projected_return_pct": float(best_signal['projected_return_pct']),
                            "votes": {
                                "strategies": strategy_votes,
                                "ai": ai_vote,
                                "sentiment": sentiment_vote,
                                "total_weight": round(total_weight, 3),
                                "total_possible": round(total_possible, 3)
                            },
                            "generated_at": best_signal['generated_at'].isoformat(),
                            "signal_ids": [s['id'] for s in signals]
                        })
                
                # Sort by consensus percentage descending
                consensus_signals.sort(key=lambda x: x['consensus_pct'], reverse=True)
                
                # Apply limit
                consensus_signals = consensus_signals[:limit]
                
                logger.info("consensus_signals_generated",
                           candidates=len(consensus_candidates),
                           passing_supermajority=len(consensus_signals),
                           supermajority_pct=supermajority_pct)
                
                return {
                    "status": "success",
                    "consensus_signals": consensus_signals,
                    "total_grouped": len(grouped),
                    "candidates_evaluated": len(consensus_candidates),
                    "passing_supermajority": len(consensus_signals),
                    "parameters": {
                        "min_strategies": min_strategies,
                        "min_quality": min_quality,
                        "supermajority_pct": supermajority_pct,
                        "include_ai_vote": include_ai_vote,
                        "include_sentiment": include_sentiment,
                        "limit": limit
                    }
                }
    
    except Exception as e:
        logger.error("consensus_signals_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/regimes")
async def get_market_regimes():
    """Get current market regimes for all symbols (Phase 4)
    
    Returns the latest detected market regime for each symbol including:
    - Regime type (trending_up, trending_down, ranging, volatile)
    - Confidence level (0-100)
    - Technical indicators (ATR, ADX, trend slope, volatility)
    - When it was last updated
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        symbol,
                        regime,
                        confidence,
                        atr,
                        adx,
                        trend_slope,
                        volatility_pct,
                        updated_at,
                        metadata
                    FROM market_regime
                    ORDER BY symbol ASC
                """)
                
                regimes = []
                for row in cur.fetchall():
                    regime_data = dict(row)
                    # Convert numeric types
                    for key in ['atr', 'adx', 'trend_slope', 'volatility_pct', 'confidence']:
                        if regime_data.get(key) is not None:
                            regime_data[key] = float(regime_data[key])
                    regimes.append(regime_data)
                
                logger.info("regimes_fetched", count=len(regimes))
                
                return {
                    "status": "success",
                    "regimes": regimes,
                    "total": len(regimes)
                }
    
    except Exception as e:
        logger.error("get_regimes_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/strategies/enriched")
def get_enriched_strategies():
    """Get strategies enriched with optimization status and current positions"""
    try:
        strategies = get_active_strategies()
        
        with get_connection() as conn:
            with conn.cursor() as cur:
                for strategy in strategies:
                    strategy_id = strategy['id']
                    
                    # Get optimization status
                    cur.execute("""
                        SELECT 
                            COUNT(*) as total_optimizations,
                            MAX(created_at) as last_optimized,
                            COUNT(*) FILTER (WHERE status = 'promoted') as promoted_count
                        FROM parameter_versions
                        WHERE strategy_id = %s
                    """, (strategy_id,))
                    opt_data = cur.fetchone()
                    
                    strategy['optimization_status'] = {
                        'total_optimizations': opt_data['total_optimizations'],
                        'last_optimized': opt_data['last_optimized'].isoformat() if opt_data['last_optimized'] else None,
                        'promoted_count': opt_data['promoted_count'],
                        'is_selected': opt_data['promoted_count'] > 0
                    }
                    
                    # Get recent signals (last 24h)
                    cur.execute("""
                        SELECT COUNT(*) as count FROM signals
                        WHERE strategy_id = %s 
                        AND generated_at > NOW() - INTERVAL '24 hours'
                    """, (strategy_id,))
                    strategy['signals_24h'] = cur.fetchone()['count']
                    
                    # Get hypothetical positions (what positions it would have)
                    cur.execute("""
                        SELECT 
                            symbol,
                            direction,
                            generated_at
                        FROM signals
                        WHERE strategy_id = %s
                        AND generated_at > NOW() - INTERVAL '1 hour'
                        ORDER BY generated_at DESC
                        LIMIT 5
                    """, (strategy_id,))
                    strategy['recent_signals'] = [dict(row) for row in cur.fetchall()]
                    
                    # Get actual open positions for this strategy
                    cur.execute("""
                        SELECT 
                            symbol,
                            side,
                            entry_price,
                            quantity,
                            mode
                        FROM positions
                        WHERE strategy_id = %s
                        AND status = 'open'
                    """, (strategy_id,))
                    strategy['open_positions'] = [dict(row) for row in cur.fetchall()]
        
        return {"status": "success", "strategies": strategies}
    except Exception as e:
        logger.error("get_enriched_strategies_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/consensus/record")
async def record_consensus_decision(decision: Dict):
    """Record a consensus decision for transparency and after-action analysis"""
    try:
        import psycopg2.extras
        
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO consensus_decisions (
                        symbol, signal_type, consensus_pct, strategy_count,
                        best_quality, avg_quality, price_at_signal, projected_return_pct,
                        strategy_votes, ai_vote, sentiment_vote,
                        total_weight, total_possible,
                        approved, executed, position_id, signal_ids, generated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    ) RETURNING id
                """, (
                    decision['symbol'],
                    decision['signal_type'],
                    decision['consensus_pct'],
                    decision['strategy_count'],
                    decision['best_quality'],
                    decision['avg_quality'],
                    decision['price_at_signal'],
                    decision.get('projected_return_pct'),
                    psycopg2.extras.Json(decision['votes']['strategies']),
                    psycopg2.extras.Json(decision['votes'].get('ai')),
                    psycopg2.extras.Json(decision['votes'].get('sentiment')),
                    decision['votes']['total_weight'],
                    decision['votes']['total_possible'],
                    decision.get('approved', True),  # If we're recording, it passed
                    decision.get('executed', False),
                    decision.get('position_id'),
                    decision.get('signal_ids', []),
                    decision['generated_at']
                ))
                
                decision_id = cur.fetchone()['id']
                logger.info("consensus_decision_recorded", decision_id=decision_id, symbol=decision['symbol'])
                
                return {
                    "status": "success",
                    "decision_id": decision_id
                }
                
    except Exception as e:
        logger.error("record_consensus_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/consensus/decisions")
async def get_consensus_decisions(
    limit: int = Query(20, ge=1, le=100),
    approved_only: bool = Query(False),
    executed_only: bool = Query(False)
):
    """Get recent consensus decisions with full voting details"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Build WHERE clause
                where_clauses = []
                if approved_only:
                    where_clauses.append("approved = true")
                if executed_only:
                    where_clauses.append("executed = true")
                
                where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
                
                cur.execute(f"""
                    SELECT 
                        cd.*,
                        p.realized_pnl_pct,
                        p.trade_result,
                        p.exit_time
                    FROM consensus_decisions cd
                    LEFT JOIN positions p ON cd.position_id = p.id
                    {where_sql}
                    ORDER BY cd.decided_at DESC
                    LIMIT %s
                """, (limit,))
                
                decisions = [dict(row) for row in cur.fetchall()]
                
                return {
                    "status": "success",
                    "decisions": decisions,
                    "count": len(decisions)
                }
                
    except Exception as e:
        logger.error("get_consensus_decisions_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/consensus/decisions/{decision_id}")
async def get_consensus_decision_detail(decision_id: int):
    """Get detailed view of a specific consensus decision"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        cd.*,
                        p.entry_price as actual_entry_price,
                        p.exit_price,
                        p.realized_pnl_pct,
                        p.trade_result,
                        p.entry_time,
                        p.exit_time,
                        p.hold_duration_minutes
                    FROM consensus_decisions cd
                    LEFT JOIN positions p ON cd.position_id = p.id
                    WHERE cd.id = %s
                """, (decision_id,))
                
                decision = cur.fetchone()
                
                if not decision:
                    raise HTTPException(status_code=404, detail="Decision not found")
                
                decision = dict(decision)
                
                # Get the original signals
                if decision['signal_ids']:
                    cur.execute("""
                        SELECT s.*, st.name as strategy_name
                        FROM signals s
                        JOIN strategies st ON s.strategy_id = st.id
                        WHERE s.id = ANY(%s)
                    """, (decision['signal_ids'],))
                    decision['original_signals'] = [dict(row) for row in cur.fetchall()]
                
                return {
                    "status": "success",
                    "decision": decision
                }
                
    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_consensus_decision_detail_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/consensus/stats")
async def get_consensus_stats():
    """Get statistics about consensus decisions"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        COUNT(*) as total_decisions,
                        COUNT(*) FILTER (WHERE approved = true) as approved_count,
                        COUNT(*) FILTER (WHERE executed = true) as executed_count,
                        COUNT(*) FILTER (WHERE trade_outcome = 'win') as wins,
                        COUNT(*) FILTER (WHERE trade_outcome = 'loss') as losses,
                        AVG(consensus_pct) as avg_consensus_pct,
                        AVG(strategy_count) as avg_strategy_count,
                        AVG(realized_pnl_pct) FILTER (WHERE realized_pnl_pct IS NOT NULL) as avg_return
                    FROM consensus_decisions
                    WHERE decided_at > NOW() - INTERVAL '7 days'
                """)
                
                stats = dict(cur.fetchone())
                
                # Get by symbol
                cur.execute("""
                    SELECT 
                        symbol,
                        COUNT(*) as decision_count,
                        COUNT(*) FILTER (WHERE executed = true) as executed_count,
                        AVG(consensus_pct) as avg_consensus
                    FROM consensus_decisions
                    WHERE decided_at > NOW() - INTERVAL '7 days'
                    GROUP BY symbol
                    ORDER BY decision_count DESC
                    LIMIT 10
                """)
                
                stats['by_symbol'] = [dict(row) for row in cur.fetchall()]
                
                return {
                    "status": "success",
                    "stats": stats
                }
                
    except Exception as e:
        logger.error("get_consensus_stats_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/export_trading_strategy")
def export_trading_strategy(
    symbol: str = Query(..., description="Symbol to get top strategy for, e.g. BTC"),
    limit: int = Query(5, ge=1, le=20, description="Number of top strategies to return"),
):
    """
    Return the top-ranked strategies for a symbol in charts-compatible format.

    The charts StrategyOverlay fetches this endpoint when a symbol is loaded so
    the chart modal can:
      1. Run runSignalScan on the returned strategy rules
      2. Render buy/sell arrows as a strategy overlay on the chart
      3. Let the user toggle each strategy's visibility

    Response shape matches /charts-strategies so both endpoints are interchangeable.
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Top strategies for this symbol ordered by trust_factor DESC
                cur.execute("""
                    SELECT
                        ss.id,
                        ss.symbol,
                        s.name           AS strategy_name,
                        s.indicator_logic,
                        s.parameters,
                        ss.trust_factor,
                        ss.profit_factor,
                        ss.win_rate,
                        ss.total_trades,
                        ss.last_backtest_at,
                        ss.rank
                    FROM symbol_strategies ss
                    JOIN strategies s ON s.id = ss.strategy_id
                    WHERE ss.symbol = %s
                      AND ss.status = 'active'
                      AND s.enabled  = true
                    ORDER BY ss.trust_factor DESC NULLS LAST,
                             ss.profit_factor  DESC NULLS LAST
                    LIMIT %s
                """, (symbol.upper(), limit))
                rows = cur.fetchall()

        if not rows:
            logger.info("export_trading_strategy_empty", symbol=symbol)
            return {"strategies": [], "count": 0, "symbol": symbol}

        import json as _json
        strategies = []
        for row in rows:
            logic = row["indicator_logic"]
            if isinstance(logic, str):
                try:
                    logic = _json.loads(logic)
                except Exception:
                    logic = {}

            # Build chart-compatible entry_rules / exit_rules from indicator_logic
            entry_rules = logic.get("entry") or logic.get("entry_rules") or logic
            exit_rules  = logic.get("exit")  or logic.get("exit_rules")  or {}
            risk_params = logic.get("risk")  or logic.get("risk_params")  or {}

            strategies.append({
                "id":               row["id"],
                "symbol":           row["symbol"],
                "strategy_name":    row["strategy_name"],
                "entry_rules":      entry_rules,
                "exit_rules":       exit_rules,
                "risk_params":      risk_params,
                "backtest_summary": {
                    "profit_factor": float(row["profit_factor"] or 0),
                    "win_rate":      float(row["win_rate"]      or 0),
                    "trade_count":   int(row["total_trades"]    or 0),
                },
                "trust_factor":     float(row["trust_factor"]  or 0),
                "rank":             row["rank"],
                "last_backtest_at": row["last_backtest_at"].isoformat() if row["last_backtest_at"] else None,
            })

        console_log = [{"symbol": s["symbol"], "name": s["strategy_name"],
                        "trust": s["trust_factor"], "pf": s["backtest_summary"]["profit_factor"]}
                       for s in strategies]
        logger.info("export_trading_strategy_ok", symbol=symbol, count=len(strategies),
                    top=console_log[:3])
        return {"strategies": strategies, "count": len(strategies), "symbol": symbol}

    except Exception as e:
        logger.error("export_trading_strategy_error", symbol=symbol, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("services.signal_api.main:app", host="0.0.0.0", port=settings.port_signal_api, workers=4)
