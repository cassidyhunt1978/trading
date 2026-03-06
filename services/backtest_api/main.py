"""Backtesting API - Test Strategies Against Historical Data"""
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import sys
import os
import pandas as pd
import numpy as np
import psycopg2.extras

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.database import get_connection, get_candles
from shared.config import get_settings
from shared.logging_config import setup_logging

settings = get_settings()
logger = setup_logging('backtest_api', settings.log_level)

app = FastAPI(title="Backtest API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class BacktestRequest(BaseModel):
    strategy_id: int
    symbol: str
    start_date: str
    end_date: str
    initial_capital: float = 1000.0
    parameters_override: Optional[Dict] = None  # Override strategy parameters
    position_size_pct: float = 100.0  # % of capital per trade
    stop_loss_pct: Optional[float] = 5.0
    take_profit_pct: Optional[float] = 10.0

class BacktestResult(BaseModel):
    backtest_id: int
    strategy_id: int
    symbol: str
    start_date: str
    end_date: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_return_pct: float
    sharpe_ratio: Optional[float]
    max_drawdown_pct: float
    total_fees_paid: float
    ending_capital: float
    perfect_strategy_return_pct: Optional[float]
    trades: list

class EnsembleBacktestRequest(BaseModel):
    symbol: str
    start_date: str
    end_date: str
    initial_capital: float = 1000.0
    min_weighted_score: float = 70.0  # Minimum weighted score to act on signal
    lookback_days: int = 14  # Days to calculate strategy performance
    signal_cluster_window_minutes: int = 5  # Cluster signals within N minutes
    position_size_pct: float = 10.0  # % of capital per trade
    stop_loss_pct: Optional[float] = 3.0
    take_profit_pct: Optional[float] = 9.0

class EnsembleBacktestResult(BaseModel):
    symbol: str
    start_date: str
    end_date: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_return_pct: float
    sharpe_ratio: Optional[float]
    max_drawdown_pct: float
    total_fees_paid: float
    ending_capital: float
    buy_hold_return_pct: float
    total_signals_considered: int
    signals_above_threshold: int
    signals_acted_on: int
    avg_weighted_score: float
    unique_strategies_used: int
    ensemble_parameters: dict
    trades: list

@app.get("/")
def root():
    return {"service": "Backtest API", "status": "running", "version": "1.0.0"}

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.post("/run", response_model=BacktestResult)
async def run_backtest(request: BacktestRequest):
    """Run a backtest for a strategy"""
    try:
        logger.info("backtest_requested", 
                   strategy_id=request.strategy_id,
                   symbol=request.symbol)
        
        # Get strategy
        strategy = get_strategy(request.strategy_id)
        
        # Apply parameter overrides if provided
        if request.parameters_override:
            strategy['parameters'] = {
                **strategy.get('parameters', {}),
                **request.parameters_override
            }
            
            # Also check if stop_loss_pct or take_profit_pct are in parameters_override
            # and use those instead of request defaults
            if 'stop_loss_pct' in request.parameters_override:
                request.stop_loss_pct = request.parameters_override['stop_loss_pct']
            if 'take_profit_pct' in request.parameters_override:
                request.take_profit_pct = request.parameters_override['take_profit_pct']
        
        logger.info("backtest_strategy_params", 
                   strategy_id=request.strategy_id,
                   parameters=strategy['parameters'],
                   stop_loss=request.stop_loss_pct,
                   take_profit=request.take_profit_pct)
        
        # Get historical candles
        candles = get_candles(
            symbol=request.symbol,
            start_date=request.start_date,
            end_date=request.end_date
        )
        
        if len(candles) < 30:
            raise HTTPException(status_code=400, 
                              detail="Insufficient historical data (need at least 30 candles)")
        
        # Run backtest simulation
        result = simulate_backtest(
            strategy=strategy,
            candles=candles,
            initial_capital=request.initial_capital,
            position_size_pct=request.position_size_pct,
            stop_loss_pct=request.stop_loss_pct,
            take_profit_pct=request.take_profit_pct
        )
        
        # Save results to database
        backtest_id = save_backtest_result(
            strategy_id=request.strategy_id,
            symbol=request.symbol,
            start_date=request.start_date,
            end_date=request.end_date,
            result=result
        )
        
        result['backtest_id'] = backtest_id
        result['strategy_id'] = request.strategy_id
        result['symbol'] = request.symbol
        result['start_date'] = request.start_date
        result['end_date'] = request.end_date
        
        logger.info("backtest_complete", 
                   backtest_id=backtest_id, 
                   win_rate=result['win_rate'],
                   total_trades=result['total_trades'],
                   trades_in_result=len(result.get('trades', [])))
        
        return result
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error("backtest_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

def get_strategy(strategy_id: int) -> dict:
    """Get strategy from database"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM strategies WHERE id = %s", (strategy_id,))
            strategy = cur.fetchone()
            
            if not strategy:
                raise HTTPException(status_code=404, detail="Strategy not found")
            
            return dict(strategy)

def simulate_backtest(strategy: dict, candles: List[dict], 
                     initial_capital: float, position_size_pct: float,
                     stop_loss_pct: Optional[float],
                     take_profit_pct: Optional[float]) -> dict:
    """Simulate backtesting a strategy"""
    from shared.fee_tiers import get_kraken_fees, calculate_fee
    
    # Extract strategy parameters
    params = strategy.get('parameters', {})
    
    # Convert to DataFrame
    df = pd.DataFrame(candles)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp')
    
    # Convert all numeric columns from Decimal to float
    numeric_cols = ['open', 'high', 'low', 'close', 'volume']
    for col in numeric_cols:
        if col in df.columns:
            df[col] = df[col].astype(float)
    
    # Compute indicators using strategy parameters
    
    # RSI calculation - use rsi_period from parameters or default to 14
    def calculate_rsi(prices, period=14):
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    rsi_period = int(params.get('rsi_period', 14))
    df['rsi'] = calculate_rsi(df['close'], period=rsi_period)
    
    logger.info("indicators_calculated",
               rsi_period=rsi_period,
               rsi_oversold=params.get('rsi_oversold', 30),
               rsi_overbought=params.get('rsi_overbought', 70),
               rsi_min=df['rsi'].min(),
               rsi_max=df['rsi'].max(),
               rsi_sample=df['rsi'].dropna().head(5).tolist())
    
    # MACD calculation - use macd parameters or defaults
    macd_fast = int(params.get('macd_fast', 12))
    macd_slow = int(params.get('macd_slow', 26))
    macd_signal = int(params.get('macd_signal', 9))
    
    exp1 = df['close'].ewm(span=macd_fast, adjust=False).mean()
    exp2 = df['close'].ewm(span=macd_slow, adjust=False).mean()
    df['macd'] = exp1 - exp2
    df['macd_signal'] = df['macd'].ewm(span=macd_signal, adjust=False).mean()
    
    # SMA calculation - use sma_period or default to 20
    sma_period = int(params.get('sma_period', 20))
    df['sma_20'] = df['close'].rolling(window=sma_period).mean()
    
    # Bollinger Bands calculation
    bb_period = int(params.get('bb_period', 20))
    bb_std_dev = float(params.get('bb_std', 2.0))
    df['bb_middle'] = df['close'].rolling(window=bb_period).mean()
    bb_std = df['close'].rolling(window=bb_period).std()
    df['bb_upper'] = df['bb_middle'] + (bb_std * bb_std_dev)
    df['bb_lower'] = df['bb_middle'] - (bb_std * bb_std_dev)
    
    # Williams %R calculation
    williams_period = int(params.get('williams_period', 14))
    highest_high = df['high'].rolling(window=williams_period).max()
    lowest_low = df['low'].rolling(window=williams_period).min()
    df['williams_r'] = -100 * (highest_high - df['close']) / (highest_high - lowest_low)
    
    # CCI (Commodity Channel Index) calculation
    cci_period = int(params.get('cci_period', 20))
    tp = (df['high'] + df['low'] + df['close']) / 3  # Typical Price
    sma_tp = tp.rolling(window=cci_period).mean()
    mad = tp.rolling(window=cci_period).apply(lambda x: abs(x - x.mean()).mean())
    df['cci'] = (tp - sma_tp) / (0.015 * mad)
    
    # ADX (Average Directional Index) calculation
    adx_period = int(params.get('adx_period', 14))
    high_diff = df['high'].diff()
    low_diff = -df['low'].diff()
    pos_dm = high_diff.where((high_diff > low_diff) & (high_diff > 0), 0)
    neg_dm = low_diff.where((low_diff > high_diff) & (low_diff > 0), 0)
    tr = pd.concat([df['high'] - df['low'], 
                    abs(df['high'] - df['close'].shift()), 
                    abs(df['low'] - df['close'].shift())], axis=1).max(axis=1)
    atr = tr.rolling(window=adx_period).mean()
    pos_di = 100 * (pos_dm.rolling(window=adx_period).mean() / atr)
    neg_di = 100 * (neg_dm.rolling(window=adx_period).mean() / atr)
    dx = 100 * abs(pos_di - neg_di) / (pos_di + neg_di)
    df['adx'] = dx.rolling(window=adx_period).mean()
    df['atr'] = atr
    
    # Stochastic Oscillator calculation
    stoch_period = int(params.get('stoch_period', 14))
    stoch_smooth = int(params.get('stoch_smooth', 3))
    lowest_low_stoch = df['low'].rolling(window=stoch_period).min()
    highest_high_stoch = df['high'].rolling(window=stoch_period).max()
    df['stoch_k'] = 100 * (df['close'] - lowest_low_stoch) / (highest_high_stoch - lowest_low_stoch)
    df['stoch_d'] = df['stoch_k'].rolling(window=stoch_smooth).mean()
    
    # ROC (Rate of Change) calculation
    roc_period = int(params.get('roc_period', 12))
    df['roc'] = ((df['close'] - df['close'].shift(roc_period)) / df['close'].shift(roc_period)) * 100
    
    # EMA calculation
    ema_period = int(params.get('ema_period', 21))
    df['ema'] = df['close'].ewm(span=ema_period, adjust=False).mean()
    
    # Trading state
    capital = initial_capital
    position = None
    trades = []
    equity_curve = [initial_capital]
    total_volume = 0  # Track volume for fee tier calculation
    
    # Get initial fee tier (starts at lowest)
    fees = get_kraken_fees(0)
    maker_fee = fees['maker_fee']
    taker_fee = fees['taker_fee']
    
    for i in range(len(df)):
        candle = df.iloc[i]
        
        # Check if position should be closed (stop loss / take profit)
        if position:
            pnl_pct = ((candle['close'] - position['entry_price']) / position['entry_price']) * 100
            
            should_close = False
            close_reason = None
            
            if stop_loss_pct and pnl_pct <= -stop_loss_pct:
                should_close = True
                close_reason = 'stop_loss'
            elif take_profit_pct and pnl_pct >= take_profit_pct:
                should_close = True
                close_reason = 'take_profit'
            
            if should_close:
                # Close position
                exit_price = candle['close']
                exit_value = position['amount'] * exit_price
                exit_fee = calculate_fee(exit_value, taker_fee)
                
                pnl = exit_value - (position['amount'] * position['entry_price']) - position['entry_fee'] - exit_fee
                capital += exit_value - exit_fee
                
                total_volume += exit_value
                
                position['exit_price'] = exit_price
                position['exit_time'] = candle['timestamp']
                position['exit_fee'] = exit_fee
                position['pnl'] = pnl
                position['pnl_pct'] = pnl_pct
                position['close_reason'] = close_reason
                
                trades.append(position)
                position = None
        
        # Generate signal from strategy
        if not position:
            signal = evaluate_strategy(strategy, candle)
            
            # Log first few signals for debugging
            if i < 50 and signal:
                logger.debug("signal_generated", 
                           timestamp=candle['timestamp'],
                           signal=signal,
                           rsi=candle.get('rsi'),
                           close=candle['close'],
                           params=strategy.get('parameters', {}))
            
            if signal in ['buy', 'sell']:
                # Open position
                entry_price = candle['close']
                position_value = capital * (position_size_pct / 100)
                amount = position_value / entry_price
                entry_fee = calculate_fee(position_value, taker_fee)
                
                capital -= (position_value + entry_fee)
                total_volume += position_value
                
                # Update fee tier based on cumulative volume
                fees = get_kraken_fees(total_volume)
                maker_fee = fees['maker_fee']
                taker_fee = fees['taker_fee']
                
                position = {
                    'entry_price': entry_price,
                    'entry_time': candle['timestamp'],
                    'amount': amount,
                    'entry_fee': entry_fee,
                    'side': signal
                }
        
        # Track equity
        if position:
            current_value = capital + (position['amount'] * candle['close'])
        else:
            current_value = capital
        
        equity_curve.append(current_value)
    
    # Close any remaining position at end
    if position:
        last_candle = df.iloc[-1]
        exit_price = last_candle['close']
        exit_value = position['amount'] * exit_price
        exit_fee = calculate_fee(exit_value, taker_fee)
        
        pnl = exit_value - (position['amount'] * position['entry_price']) - position['entry_fee'] - exit_fee
        capital += exit_value - exit_fee
        
        pnl_pct = ((exit_price - position['entry_price']) / position['entry_price']) * 100
        
        position['exit_price'] = exit_price
        position['exit_time'] = last_candle['timestamp']
        position['exit_fee'] = exit_fee
        position['pnl'] = pnl
        position['pnl_pct'] = pnl_pct
        position['close_reason'] = 'backtest_end'
        
        trades.append(position)
    
    # Calculate metrics
    final_capital = capital
    total_return_pct = ((final_capital - initial_capital) / initial_capital) * 100
    
    # Buy and hold return
    buy_hold_return_pct = ((df.iloc[-1]['close'] - df.iloc[0]['close']) / df.iloc[0]['close']) * 100
    
    # Win rate
    winning_trades = [t for t in trades if t.get('pnl', 0) > 0]
    losing_trades = [t for t in trades if t.get('pnl', 0) <= 0]
    win_rate = (len(winning_trades) / len(trades) * 100) if trades else 0
    
    # Sharpe ratio
    if len(equity_curve) > 1:
        returns = pd.Series(equity_curve).pct_change().dropna()
        sharpe_ratio = (returns.mean() / returns.std()) * np.sqrt(252) if returns.std() > 0 else None
    else:
        sharpe_ratio = None
    
    # Max drawdown
    equity_series = pd.Series(equity_curve)
    running_max = equity_series.expanding().max()
    drawdown = (equity_series - running_max) / running_max * 100
    max_drawdown_pct = abs(drawdown.min()) if len(drawdown) > 0 else 0
    
    # Average trade duration (not stored in DB, just calculated)
    if trades:
        durations = [(t['exit_time'] - t['entry_time']).total_seconds() / 60 for t in trades]
        avg_duration = sum(durations) / len(durations)
    else:
        avg_duration = None
    
    # Total fees
    total_fees_paid = sum(t['entry_fee'] + t.get('exit_fee', 0) for t in trades)
    
    # Convert timestamps in trades to ISO format strings for JSON serialization
    for trade in trades:
        if 'entry_time' in trade and hasattr(trade['entry_time'], 'isoformat'):
            trade['entry_time'] = trade['entry_time'].isoformat()
        if 'exit_time' in trade and hasattr(trade['exit_time'], 'isoformat'):
            trade['exit_time'] = trade['exit_time'].isoformat()
    
    logger.info("backtest_simulation_complete",
               total_trades=len(trades),
               trades_sample=trades[0] if trades else None)
    
    return {
        'starting_capital': float(initial_capital),
        'ending_capital': round(float(final_capital), 2),
        'total_trades': len(trades),
        'winning_trades': len(winning_trades),
        'losing_trades': len(losing_trades),
        'win_rate': round(float(win_rate), 2),
        'total_return_pct': round(float(total_return_pct), 2),
        'sharpe_ratio': round(float(sharpe_ratio), 2) if sharpe_ratio is not None else None,
        'max_drawdown_pct': round(float(max_drawdown_pct), 2),
        'total_fees_paid': round(float(total_fees_paid), 2),
        'perfect_strategy_return_pct': round(float(buy_hold_return_pct), 2),
        'trades': trades
    }

def evaluate_strategy(strategy: dict, candle: pd.Series) -> Optional[str]:
    """Evaluate if strategy generates a signal for this candle"""
    
    # Parse indicator_logic from strategy
    indicator_logic = strategy.get('indicator_logic', {})
    buy_conditions = indicator_logic.get('buy_conditions', [])
    sell_conditions = indicator_logic.get('sell_conditions', [])
    
    # Get parameters to override condition values
    params = strategy.get('parameters', {})
    
    # Check buy conditions
    if buy_conditions:
        buy_signal = True
        for condition in buy_conditions:
            indicator = condition.get('indicator', '').upper()
            operator = condition.get('operator', '')
            raw_value = condition.get('value', 0)
            
            # Check if value is a column name (string) or numeric
            value = None
            value_is_column = False
            try:
                # Try to convert to float
                value = float(raw_value)
            except (ValueError, TypeError):
                # Value is a column name (e.g., 'VWAP', 'SMA', etc.)
                value_is_column = True
                value_column_name = str(raw_value).lower()
            
            # Override numeric value with parameter if available
            if not value_is_column:
                # For RSI < X (oversold), use rsi_oversold parameter
                if indicator == 'RSI' and operator == '<':
                    value = float(params.get('rsi_oversold', value))
                # For RSI > X (overbought), use rsi_overbought parameter  
                elif indicator == 'RSI' and operator == '>':
                    value = float(params.get('rsi_overbought', value))
            
            # Get indicator value from candle
            candle_value = None
            if indicator == 'RSI':
                candle_value = candle.get('rsi')
            elif indicator == 'MACD':
                candle_value = candle.get('macd')
            elif indicator == 'SMA':
                candle_value = candle.get('sma_20')
            elif indicator == 'WILLIAMS_R' or indicator == 'WILLIAMS %R' or indicator == 'WILLIAMS':
                candle_value = candle.get('williams_r')
            elif indicator == 'CCI':
                candle_value = candle.get('cci')
            elif indicator == 'ADX':
                candle_value = candle.get('adx')
            elif indicator == 'STOCHASTIC' or indicator == 'STOCH_K':
                candle_value = candle.get('stoch_k')
            elif indicator == 'STOCH_D':
                candle_value = candle.get('stoch_d')
            elif indicator == 'ROC':
                candle_value = candle.get('roc')
            elif indicator == 'EMA':
                candle_value = candle.get('ema')
            elif indicator == 'ATR':
                candle_value = candle.get('atr')
            elif indicator == 'BB_UPPER':
                candle_value = candle.get('bb_upper')
            elif indicator == 'BB_LOWER':
                candle_value = candle.get('bb_lower')
            elif indicator == 'BB_MIDDLE':
                candle_value = candle.get('bb_middle')
            elif indicator == 'CLOSE':
                candle_value = candle.get('close')
            elif indicator == 'VWAP':
                candle_value = candle.get('vwap')
            
            # Skip if indicator not available
            if candle_value is None or pd.isna(candle_value):
                buy_signal = False
                break
            
            # If value is a column name, get its value from candle
            if value_is_column:
                value = candle.get(value_column_name)
                if value is None or pd.isna(value):
                    buy_signal = False
                    break
            
            # Evaluate condition
            if operator == '<':
                if not (candle_value < value):
                    buy_signal = False
                    break
            elif operator == '>':
                if not (candle_value > value):
                    buy_signal = False
                    break
            elif operator == '=':
                if not (abs(candle_value - value) < 0.01):
                    buy_signal = False
                    break
        
        if buy_signal:
            return 'buy'
    
    # Check sell conditions
    if sell_conditions:
        sell_signal = True
        for condition in sell_conditions:
            indicator = condition.get('indicator', '').upper()
            operator = condition.get('operator', '')
            raw_value = condition.get('value', 0)
            
            # Check if value is a column name (string) or numeric
            value = None
            value_is_column = False
            try:
                # Try to convert to float
                value = float(raw_value)
            except (ValueError, TypeError):
                # Value is a column name (e.g., 'VWAP', 'SMA', etc.)
                value_is_column = True
                value_column_name = str(raw_value).lower()
            
            # Override numeric value with parameter if available
            if not value_is_column:
                # For RSI > X (overbought for sell), use rsi_overbought parameter
                if indicator == 'RSI' and operator == '>':
                    value = float(params.get('rsi_overbought', value))
                # For RSI < X (oversold for sell), use rsi_oversold parameter
                elif indicator == 'RSI' and operator == '<':
                    value = float(params.get('rsi_oversold', value))
            
            # Get indicator value from candle
            candle_value = None
            if indicator == 'RSI':
                candle_value = candle.get('rsi')
            elif indicator == 'MACD':
                candle_value = candle.get('macd')
            elif indicator == 'SMA':
                candle_value = candle.get('sma_20')
            elif indicator == 'WILLIAMS_R' or indicator == 'WILLIAMS %R' or indicator == 'WILLIAMS':
                candle_value = candle.get('williams_r')
            elif indicator == 'CCI':
                candle_value = candle.get('cci')
            elif indicator == 'ADX':
                candle_value = candle.get('adx')
            elif indicator == 'STOCHASTIC' or indicator == 'STOCH_K':
                candle_value = candle.get('stoch_k')
            elif indicator == 'STOCH_D':
                candle_value = candle.get('stoch_d')
            elif indicator == 'ROC':
                candle_value = candle.get('roc')
            elif indicator == 'EMA':
                candle_value = candle.get('ema')
            elif indicator == 'ATR':
                candle_value = candle.get('atr')
            elif indicator == 'BB_UPPER':
                candle_value = candle.get('bb_upper')
            elif indicator == 'BB_LOWER':
                candle_value = candle.get('bb_lower')
            elif indicator == 'BB_MIDDLE':
                candle_value = candle.get('bb_middle')
            elif indicator == 'CLOSE':
                candle_value = candle.get('close')
            elif indicator == 'VWAP':
                candle_value = candle.get('vwap')
            
            # Skip if indicator not available
            if candle_value is None or pd.isna(candle_value):
                sell_signal = False
                break
            
            # If value is a column name, get its value from candle
            if value_is_column:
                value = candle.get(value_column_name)
                if value is None or pd.isna(value):
                    sell_signal = False
                    break
            
            # Evaluate condition
            if operator == '<':
                if not (candle_value < value):
                    sell_signal = False
                    break
            elif operator == '>':
                if not (candle_value > value):
                    sell_signal = False
                    break
            elif operator == '=':
                if not (abs(candle_value - value) < 0.01):
                    sell_signal = False
                    break
        
        if sell_signal:
            return 'sell'
    
    return None

def save_backtest_result(strategy_id: int, symbol: str, start_date: str, 
                         end_date: str, result: dict) -> int:
    """Save backtest result to database"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            import psycopg2.extras
            cur.execute("""
                INSERT INTO backtests
                (strategy_id, symbol, start_date, end_date, starting_capital,
                 total_trades, winning_trades, losing_trades, win_rate,
                 total_return_pct, sharpe_ratio, max_drawdown_pct,
                 total_fees_paid, ending_capital, perfect_strategy_return_pct, trades)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                strategy_id, symbol, start_date, end_date, result.get('starting_capital', 10000),
                result['total_trades'], result['winning_trades'], result['losing_trades'],
                result['win_rate'], result['total_return_pct'], result['sharpe_ratio'],
                result['max_drawdown_pct'], result.get('total_fees_paid', 0),
                result.get('ending_capital', 0), result.get('perfect_strategy_return_pct'),
                psycopg2.extras.Json(result.get('trades', []))
            ))
            
            return cur.fetchone()['id']

@app.get("/results")
def get_backtest_results(
    strategy_id: Optional[int] = None,
    symbol: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100)
):
    """Get backtest results"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                conditions = []
                params = []
                
                if strategy_id:
                    conditions.append("strategy_id = %s")
                    params.append(strategy_id)
                
                if symbol:
                    conditions.append("symbol = %s")
                    params.append(symbol)
                
                where_clause = " AND ".join(conditions) if conditions else "1=1"
                params.append(limit)
                
                cur.execute(f"""
                    SELECT 
                        id, strategy_id, symbol, start_date, end_date,
                        starting_capital, ending_capital,
                        total_trades, winning_trades, losing_trades, win_rate,
                        total_return_pct, sharpe_ratio, max_drawdown_pct,
                        total_fees_paid, perfect_strategy_return_pct, 
                        trades, created_at
                    FROM backtests
                    WHERE {where_clause}
                    ORDER BY created_at DESC
                    LIMIT %s
                """, params)
                
                results = [dict(row) for row in cur.fetchall()]
        
        return {
            "status": "success",
            "count": len(results),
            "results": results
        }
    
    except Exception as e:
        logger.error("results_fetch_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/results/{backtest_id}")
def get_backtest_detail(backtest_id: int):
    """Get detailed backtest result including trade log"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM backtests WHERE id = %s", (backtest_id,))
                result = cur.fetchone()
                
                if not result:
                    raise HTTPException(status_code=404, detail="Backtest not found")
                
                return dict(result)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error("detail_fetch_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/compare")
def compare_strategies(
    strategy_ids: str = Query(..., description="Comma-separated strategy IDs"),
    symbol: str = Query(...),
    start_date: str = Query(...),
    end_date: str = Query(...)
):
    """Compare multiple strategies side-by-side"""
    try:
        ids = [int(sid.strip()) for sid in strategy_ids.split(',')]
        
        comparisons = []
        for strategy_id in ids:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT * FROM backtests
                        WHERE strategy_id = %s 
                        AND symbol = %s
                        AND start_date = %s
                        AND end_date = %s
                        ORDER BY run_at DESC
                        LIMIT 1
                    """, (strategy_id, symbol, start_date, end_date))
                    
                    result = cur.fetchone()
                    if result:
                        comparisons.append(dict(result))
        
        return {
            "status": "success",
            "symbol": symbol,
            "period": f"{start_date} to {end_date}",
            "strategies_compared": len(comparisons),
            "results": comparisons
        }
    
    except Exception as e:
        logger.error("compare_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/stats")
def get_backtest_stats():
    """Get overall backtest statistics"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        COUNT(*) as total_backtests,
                        COUNT(DISTINCT strategy_id) as strategies_tested,
                        COUNT(DISTINCT symbol) as symbols_tested,
                        AVG(win_rate) as avg_win_rate,
                        AVG(total_return_pct) as avg_return_pct,
                        MAX(total_return_pct) as best_return_pct,
                        MIN(total_return_pct) as worst_return_pct
                    FROM backtests
                """)
                
                stats = dict(cur.fetchone())
        
        return {
            "status": "success",
            "total_backtests": stats['total_backtests'],
            "strategies_tested": stats['strategies_tested'],
            "symbols_tested": stats['symbols_tested'],
            "avg_win_rate": round(float(stats['avg_win_rate'] or 0), 2),
            "avg_return_pct": round(float(stats['avg_return_pct'] or 0), 2),
            "best_return_pct": round(float(stats['best_return_pct'] or 0), 2),
            "worst_return_pct": round(float(stats['worst_return_pct'] or 0), 2)
        }
    
    except Exception as e:
        logger.error("stats_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

def calculate_strategy_performance_at_time(strategy_id: int, symbol: str, 
                                          current_time: datetime, lookback_days: int) -> dict:
    """Calculate strategy performance over lookback period ending at current_time
    
    Uses strategy_performance table if available, otherwise returns default values
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Try to get performance from strategy_performance table
                cur.execute("""
                    SELECT 
                        strategy_id,
                        symbol,
                        win_rate,
                        total_trades,
                        total_signals,
                        sharpe_ratio,
                        profit_factor,
                        period_days
                    FROM strategy_performance
                    WHERE strategy_id = %s
                    AND symbol = %s
                    AND period_days = %s
                """, (strategy_id, symbol, lookback_days))
                
                result = cur.fetchone()
                
                if result and result['total_trades'] is not None and result['total_trades'] >= 3:
                    # Have good performance data
                    return {
                        'strategy_id': strategy_id,
                        'total_signals': result['total_trades'],  # Using trades as proxy for signals
                        'winning_signals': int(result['total_trades'] * (result['win_rate'] / 100.0)) if result['win_rate'] else 0,
                        'win_rate': float(result['win_rate']) / 100.0 if result['win_rate'] else 0.5,
                        'avg_return': 0.0  # Not available in strategy_performance
                    }
                else:
                    # No performance data or insufficient trades - return defaults
                    # This allows signals to be evaluated at base quality score
                    return {
                        'strategy_id': strategy_id,
                        'total_signals': 0,
                        'winning_signals': 0,
                        'win_rate': 0.5,  # Neutral 50% win rate
                        'avg_return': 0.0
                    }
                    
    except Exception as e:
        logger.error("performance_calculation_error", 
                    strategy_id=strategy_id, 
                    symbol=symbol, 
                    error=str(e))
        # Fall back to neutral performance
        return {
            'strategy_id': strategy_id,
            'total_signals': 0,
            'winning_signals': 0,
            'win_rate': 0.5,
            'avg_return': 0.0
        }

def check_has_performance_data(symbol: str) -> bool:
    """Check if strategy_performance table has sufficient data for this symbol
    
    Returns True if we have at least one strategy with 5+ trades
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(*) as count
                    FROM strategy_performance
                    WHERE symbol = %s
                    AND total_trades >= 5
                """, (symbol,))
                result = cur.fetchone()
                return result['count'] > 0 if result else False
    except Exception as e:
        logger.error("performance_check_error", symbol=symbol, error=str(e))
        return False

def cluster_signals_by_window(signals: List[dict], window_minutes: int) -> List[List[dict]]:
    """Cluster signals that occur within window_minutes of each other"""
    if not signals:
        return []
    
    # Sort signals by time
    sorted_signals = sorted(signals, key=lambda s: s['generated_at'])
    
    clusters = []
    current_cluster = [sorted_signals[0]]
    
    for signal in sorted_signals[1:]:
        time_diff = (signal['generated_at'] - current_cluster[-1]['generated_at']).total_seconds() / 60
        
        if time_diff <= window_minutes:
            current_cluster.append(signal)
        else:
            clusters.append(current_cluster)
            current_cluster = [signal]
    
    # Add the last cluster
    if current_cluster:
        clusters.append(current_cluster)
    
    return clusters

def ensemble_weighted_vote(signal_cluster: List[dict], 
                          strategy_performances: Dict[int, dict],
                          min_weighted_score: float,
                          bootstrap_mode: bool = False) -> Optional[dict]:
    """Apply weighted voting to a cluster of signals
    
    Args:
        signal_cluster: List of signals in the time cluster
        strategy_performances: Performance data for each strategy
        min_weighted_score: Configured minimum score threshold
        bootstrap_mode: If True, uses permissive threshold (50) instead of configured threshold
    
    Returns the ensemble decision with metadata, or None if no action should be taken
    """
    # Bootstrap mode: use permissive threshold when no performance data exists
    effective_threshold = 50.0 if bootstrap_mode else min_weighted_score
    
    buy_weight = 0.0
    sell_weight = 0.0
    buy_signals = []
    sell_signals = []
    
    for signal in signal_cluster:
        strategy_id = signal['strategy_id']
        base_quality = signal['quality_score']
        
        # Get strategy performance
        perf = strategy_performances.get(strategy_id)
        if not perf or perf['total_signals'] < 3:
            # Not enough performance data, use base quality with neutral weighting
            # This allows signals to be considered at their base quality score
            weighted_score = base_quality
            win_rate = 0.5  # Neutral
        else:
            # Apply weighting formula: weighted_score = base_quality * (1 + (win_rate - 0.5))
            win_rate = perf['win_rate']
            weighted_score = base_quality * (1 + (win_rate - 0.5))
        
        # Store weighted score in signal
        signal['weighted_score'] = weighted_score
        signal['win_rate'] = win_rate if perf and perf['total_signals'] >= 3 else None
        
        # Only consider signals above threshold (uses effective_threshold)
        if weighted_score >= effective_threshold:
            signal_type_lower = signal['signal_type'].lower() if signal['signal_type'] else ''
            if signal_type_lower == 'buy':
                buy_weight += weighted_score
                buy_signals.append(signal)
            elif signal_type_lower == 'sell':
                sell_weight += weighted_score
                sell_signals.append(signal)
    
    # Determine ensemble action
    if buy_weight == 0 and sell_weight == 0:
        return None  # No signals above threshold
    
    if buy_weight > sell_weight:
        action = 'buy'
        weight = buy_weight
        contributing_signals = buy_signals
    else:
        action = 'sell'
        weight = sell_weight
        contributing_signals = sell_signals
    
    # Calculate average values from contributing signals
    avg_quality = sum(s['quality_score'] for s in contributing_signals) / len(contributing_signals)
    avg_weighted_score = sum(s['weighted_score'] for s in contributing_signals) / len(contributing_signals)
    
    return {
        'action': action,
        'total_weight': weight,
        'avg_quality': avg_quality,
        'avg_weighted_score': avg_weighted_score,
        'num_signals': len(contributing_signals),
        'contributing_signals': contributing_signals,
        'timestamp': signal_cluster[0]['generated_at'],
        'price': contributing_signals[0]['price_at_signal']
    }

def simulate_ensemble_backtest(symbol: str, start_date: str, end_date: str,
                               initial_capital: float, position_size_pct: float,
                               stop_loss_pct: Optional[float], take_profit_pct: Optional[float],
                               min_weighted_score: float, lookback_days: int,
                               signal_cluster_window_minutes: int) -> dict:
    """Simulate ensemble backtest using historical signals"""
    from shared.fee_tiers import get_kraken_fees, calculate_fee
    
    try:
        # Fetch all signals in date range for this symbol
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        s.*,
                        st.name as strategy_name,
                        st.enabled
                    FROM signals s
                    JOIN strategies st ON s.strategy_id = st.id
                    WHERE s.symbol = %s
                    AND s.generated_at >= %s
                    AND s.generated_at <= %s
                    AND st.enabled = true
                    ORDER BY s.generated_at ASC
                """, (symbol, start_date, end_date))
                
                signals = [dict(row) for row in cur.fetchall()]
        
        if not signals:
            logger.warning("No signals found for ensemble backtest",
                         symbol=symbol,
                         start_date=start_date,
                         end_date=end_date)
            return {
                'starting_capital': float(initial_capital),
                'ending_capital': float(initial_capital),
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0.0,
                'total_return_pct': 0.0,
                'sharpe_ratio': None,
                'max_drawdown_pct': 0.0,
                'total_fees_paid': 0.0,
                'buy_hold_return_pct': 0.0,
                'total_signals_considered': 0,
                'signals_above_threshold': 0,
                'signals_acted_on': 0,
                'avg_weighted_score': 0.0,
                'unique_strategies_used': 0,
                'trades': []
            }
        
        # Get OHLCV data for price tracking and buy-hold comparison
        # Parse date strings to datetime objects
        start_dt = datetime.strptime(start_date, '%Y-%m-%d') if isinstance(start_date, str) else start_date
        end_dt = datetime.strptime(end_date, '%Y-%m-%d') if isinstance(end_date, str) else end_date
        
        candles = get_candles(symbol, start_date=start_dt, end_date=end_dt, limit=100000)
        
        if not candles:
            raise ValueError(f"No candle data available for {symbol}")
        
        df = pd.DataFrame(candles)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp')
        df['close'] = df['close'].astype(float)
        
        # Cluster signals by time window
        signal_clusters = cluster_signals_by_window(signals, signal_cluster_window_minutes)
        
        logger.info("ensemble_backtest_started",
                   symbol=symbol,
                   total_signals=len(signals),
                   clusters=len(signal_clusters),
                   lookback_days=lookback_days)
        
        # Trading state
        capital = initial_capital
        position = None
        trades = []
        equity_curve = [initial_capital]
        total_volume = 0
        
        signals_above_threshold = 0
        signals_acted_on = 0
        all_weighted_scores = []
        strategies_used = set()
        
        # Get initial fee tier
        fees = get_kraken_fees(0)
        maker_fee = fees['maker_fee']
        taker_fee = fees['taker_fee']
        
        # Check if we have performance data (bootstrap mode)
        has_performance_data = check_has_performance_data(symbol)
        bootstrap_mode = not has_performance_data
        
        if bootstrap_mode:
            logger.info("bootstrap_mode_active",
                       symbol=symbol,
                       configured_threshold=min_weighted_score,
                       effective_threshold=50.0,
                       reason="No performance data available yet")
        
        # Process each signal cluster
        for cluster in signal_clusters:
            cluster_time = cluster[0]['generated_at']
            
            # Calculate strategy performance for each strategy in cluster at this point in time
            strategy_ids = list(set(s['strategy_id'] for s in cluster))
            strategy_performances = {}
            
            for strategy_id in strategy_ids:
                perf = calculate_strategy_performance_at_time(
                    strategy_id, symbol, cluster_time, lookback_days
                )
                strategy_performances[strategy_id] = perf
            
            # Apply ensemble voting (with bootstrap mode if needed)
            ensemble_decision = ensemble_weighted_vote(
                cluster, strategy_performances, min_weighted_score, bootstrap_mode
            )
            
            if ensemble_decision:
                signals_above_threshold += len(ensemble_decision['contributing_signals'])
                all_weighted_scores.append(ensemble_decision['avg_weighted_score'])
                
                # Track strategies used
                for sig in ensemble_decision['contributing_signals']:
                    strategies_used.add(sig['strategy_id'])
                
                # Get current price from candles (nearest timestamp)
                cluster_timestamp = ensemble_decision['timestamp']
                price_row = df[df['timestamp'] <= cluster_timestamp].tail(1)
                
                if price_row.empty:
                    continue  # Skip if no price data available yet
                
                current_price = float(price_row['close'].iloc[0])
                current_time = price_row['timestamp'].iloc[0]
                
                # Check if we should close existing position (stop loss/take profit)
                if position:
                    pnl_pct = ((current_price - position['entry_price']) / position['entry_price']) * 100
                    
                    should_close = False
                    close_reason = None
                    
                    if stop_loss_pct and pnl_pct <= -stop_loss_pct:
                        should_close = True
                        close_reason = 'stop_loss'
                    elif take_profit_pct and pnl_pct >= take_profit_pct:
                        should_close = True
                        close_reason = 'take_profit'
                    
                    if should_close:
                        exit_price = current_price
                        exit_value = position['amount'] * exit_price
                        exit_fee = calculate_fee(exit_value, taker_fee)
                        
                        pnl = exit_value - (position['amount'] * position['entry_price']) - position['entry_fee'] - exit_fee
                        capital += exit_value - exit_fee
                        total_volume += exit_value
                        
                        position['exit_price'] = exit_price
                        position['exit_time'] = current_time
                        position['exit_fee'] = exit_fee
                        position['pnl'] = pnl
                        position['pnl_pct'] = pnl_pct
                        position['close_reason'] = close_reason
                        
                        trades.append(position)
                        position = None
                
                # Open new position if we don't have one
                if not position:
                    signals_acted_on += 1
                    
                    entry_price = current_price
                    position_value = capital * (position_size_pct / 100)
                    amount = position_value / entry_price
                    entry_fee = calculate_fee(position_value, taker_fee)
                    
                    capital -= (position_value + entry_fee)
                    total_volume += position_value
                    
                    # Update fee tier
                    fees = get_kraken_fees(total_volume)
                    maker_fee = fees['maker_fee']
                    taker_fee = fees['taker_fee']
                    
                    position = {
                        'entry_price': entry_price,
                        'entry_time': current_time,
                        'amount': amount,
                        'entry_fee': entry_fee,
                        'side': ensemble_decision['action'],
                        'num_signals': ensemble_decision['num_signals'],
                        'avg_weighted_score': ensemble_decision['avg_weighted_score'],
                        'strategies': [s['strategy_id'] for s in ensemble_decision['contributing_signals']]
                    }
            
            # Track equity
            if position:
                # Get latest price for equity calculation
                latest_price_row = df[df['timestamp'] <= cluster_time].tail(1)
                if not latest_price_row.empty:
                    latest_price = float(latest_price_row['close'].iloc[0])
                    current_value = capital + (position['amount'] * latest_price)
                    equity_curve.append(current_value)
            else:
                equity_curve.append(capital)
        
        # Close any remaining position at end
        if position:
            last_price = float(df.iloc[-1]['close'])
            last_time = df.iloc[-1]['timestamp']
            
            exit_value = position['amount'] * last_price
            exit_fee = calculate_fee(exit_value, taker_fee)
            
            pnl = exit_value - (position['amount'] * position['entry_price']) - position['entry_fee'] - exit_fee
            capital += exit_value - exit_fee
            
            pnl_pct = ((last_price - position['entry_price']) / position['entry_price']) * 100
            
            position['exit_price'] = last_price
            position['exit_time'] = last_time
            position['exit_fee'] = exit_fee
            position['pnl'] = pnl
            position['pnl_pct'] = pnl_pct
            position['close_reason'] = 'backtest_end'
            
            trades.append(position)
        
        # Calculate metrics
        final_capital = capital
        total_return_pct = ((final_capital - initial_capital) / initial_capital) * 100
        
        # Buy and hold return
        buy_hold_return_pct = ((df.iloc[-1]['close'] - df.iloc[0]['close']) / df.iloc[0]['close']) * 100
        
        # Win rate
        winning_trades = [t for t in trades if t.get('pnl', 0) > 0]
        losing_trades = [t for t in trades if t.get('pnl', 0) <= 0]
        win_rate = (len(winning_trades) / len(trades) * 100) if trades else 0
        
        # Sharpe ratio
        if len(equity_curve) > 1:
            returns = pd.Series(equity_curve).pct_change().dropna()
            sharpe_ratio = (returns.mean() / returns.std()) * np.sqrt(252) if returns.std() > 0 else None
        else:
            sharpe_ratio = None
        
        # Max drawdown
        equity_series = pd.Series(equity_curve)
        running_max = equity_series.expanding().max()
        drawdown = (equity_series - running_max) / running_max * 100
        max_drawdown_pct = abs(drawdown.min()) if len(drawdown) > 0 else 0
        
        # Total fees
        total_fees_paid = sum(t['entry_fee'] + t.get('exit_fee', 0) for t in trades)
        
        # Average weighted score
        avg_weighted_score = sum(all_weighted_scores) / len(all_weighted_scores) if all_weighted_scores else 0
        
        # Convert timestamps in trades to ISO format
        for trade in trades:
            if 'entry_time' in trade and hasattr(trade['entry_time'], 'isoformat'):
                trade['entry_time'] = trade['entry_time'].isoformat()
            if 'exit_time' in trade and hasattr(trade['exit_time'], 'isoformat'):
                trade['exit_time'] = trade['exit_time'].isoformat()
        
        logger.info("ensemble_backtest_complete",
                   total_trades=len(trades),
                   win_rate=win_rate,
                   total_return_pct=total_return_pct,
                   signals_considered=len(signals),
                   signals_acted_on=signals_acted_on)
        
        return {
            'starting_capital': float(initial_capital),
            'ending_capital': round(float(final_capital), 2),
            'total_trades': len(trades),
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': round(float(win_rate), 2),
            'total_return_pct': round(float(total_return_pct), 2),
            'sharpe_ratio': round(float(sharpe_ratio), 2) if sharpe_ratio is not None else None,
            'max_drawdown_pct': round(float(max_drawdown_pct), 2),
            'total_fees_paid': round(float(total_fees_paid), 2),
            'buy_hold_return_pct': round(float(buy_hold_return_pct), 2),
            'total_signals_considered': len(signals),
            'signals_above_threshold': signals_above_threshold,
            'signals_acted_on': signals_acted_on,
            'avg_weighted_score': round(float(avg_weighted_score), 2),
            'unique_strategies_used': len(strategies_used),
            'trades': trades
        }
    
    except Exception as e:
        logger.error("ensemble_backtest_error", error=str(e), symbol=symbol)
        raise

@app.post("/ensemble", response_model=EnsembleBacktestResult)
async def run_ensemble_backtest(request: EnsembleBacktestRequest):
    """Run ensemble backtest using historical signals with weighted voting"""
    try:
        logger.info("ensemble_backtest_requested",
                   symbol=request.symbol,
                   date_range=f"{request.start_date} to {request.end_date}",
                   min_weighted_score=request.min_weighted_score,
                   lookback_days=request.lookback_days)
        
        # Run simulation
        result = simulate_ensemble_backtest(
            symbol=request.symbol,
            start_date=request.start_date,
            end_date=request.end_date,
            initial_capital=request.initial_capital,
            position_size_pct=request.position_size_pct,
            stop_loss_pct=request.stop_loss_pct,
            take_profit_pct=request.take_profit_pct,
            min_weighted_score=request.min_weighted_score,
            lookback_days=request.lookback_days,
            signal_cluster_window_minutes=request.signal_cluster_window_minutes
        )
        
        # Add ensemble parameters to result
        result['ensemble_parameters'] = {
            'min_weighted_score': request.min_weighted_score,
            'lookback_days': request.lookback_days,
            'signal_cluster_window_minutes': request.signal_cluster_window_minutes,
            'position_size_pct': request.position_size_pct,
            'stop_loss_pct': request.stop_loss_pct,
            'take_profit_pct': request.take_profit_pct
        }
        
        return EnsembleBacktestResult(
            symbol=request.symbol,
            start_date=request.start_date,
            end_date=request.end_date,
            **result
        )
    
    except Exception as e:
        logger.error("ensemble_backtest_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/ensemble/optimized-params")
async def get_optimized_ensemble_params(symbol: str = None):
    """Get optimized ensemble parameters for a symbol or all symbols"""
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                if symbol:
                    cursor.execute("""
                        SELECT 
                            symbol,
                            min_weighted_score,
                            lookback_days,
                            signal_cluster_window_minutes,
                            position_size_pct,
                            stop_loss_pct,
                            take_profit_pct,
                            backtest_return_pct,
                            backtest_win_rate,
                            backtest_sharpe_ratio,
                            backtest_total_trades,
                            optimization_score,
                            tested_combinations,
                            optimized_at
                        FROM ensemble_optimized_params
                        WHERE symbol = %s
                    """, (symbol,))
                    result = cursor.fetchone()
                    if result:
                        return dict(result)
                    else:
                        return {"message": f"No optimized parameters found for {symbol}"}
                else:
                    cursor.execute("""
                        SELECT 
                            symbol,
                            min_weighted_score,
                            lookback_days,
                            signal_cluster_window_minutes,
                            position_size_pct,
                            stop_loss_pct,
                            take_profit_pct,
                            backtest_return_pct,
                            backtest_win_rate,
                            backtest_sharpe_ratio,
                            backtest_total_trades,
                            optimization_score,
                            tested_combinations,
                            optimized_at
                        FROM ensemble_optimized_params
                        ORDER BY optimization_score DESC
                    """)
                    results = cursor.fetchall()
                    return [dict(r) for r in results]
    
    except Exception as e:
        logger.error("get_optimized_params_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ensemble/trigger-optimization")
async def trigger_ensemble_optimization():
    """Manually trigger ensemble parameter optimization task"""
    try:
        from celery import Celery
        
        celery_app = Celery(
            broker=settings.redis_url,
            backend=settings.redis_url
        )
        
        result = celery_app.send_task('optimize_ensemble_parameters')
        
        return {
            "status": "success",
            "message": "Ensemble optimization task triggered",
            "task_id": result.id
        }
    except Exception as e:
        logger.error("trigger_optimization_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/ensemble/optimization-status")
async def get_optimization_status():
    """Get status of ensemble optimization - last run and results"""
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                # Get summary of last optimization run
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_symbols,
                        MAX(optimized_at) as last_run,
                        AVG(optimization_score) as avg_score,
                        SUM(tested_combinations) as total_tests,
                        AVG(backtest_return_pct) as avg_return,
                        AVG(backtest_win_rate) as avg_win_rate
                    FROM ensemble_optimized_params
                """)
                summary = cursor.fetchone()
                
                # Get individual symbol results
                cursor.execute("""
                    SELECT 
                        symbol,
                        backtest_return_pct,
                        backtest_win_rate,
                        backtest_sharpe_ratio,
                        backtest_total_trades,
                        optimization_score,
                        optimized_at
                    FROM ensemble_optimized_params
                    ORDER BY optimization_score DESC
                """)
                symbols = cursor.fetchall()
                
                return {
                    "summary": dict(summary) if summary else None,
                    "symbols": [dict(s) for s in symbols],
                    "last_run_time_ago": None if not summary or not summary['last_run'] else str(datetime.now() - summary['last_run'])
                }
    
    except Exception as e:
        logger.error("get_optimization_status_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    # Run with 4 workers so health checks aren't blocked by running backtests
    # Must use import string format when using workers
    uvicorn.run("services.backtest_api.main:app", host="0.0.0.0", port=settings.port_backtest_api, workers=4)
