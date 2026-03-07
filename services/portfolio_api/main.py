"""Portfolio API - Capital Allocation & Position Management"""
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Dict, Optional, Any
from datetime import datetime
from decimal import Decimal
import sys
import os
import ccxt
import time
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.database import get_connection, get_portfolio_state, get_open_positions
from shared.config import get_settings
from shared.logging_config import setup_logging

settings = get_settings()
logger = setup_logging('portfolio_api', settings.log_level)

class DecimalEncoder(json.JSONEncoder):
    """Custom JSON encoder that converts Decimal to float"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)

# Create custom JSONResponse class
class DecimalJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(
            content,
            cls=DecimalEncoder,
            ensure_ascii=False,
            allow_nan=False,
            indent=None,
            separators=(",", ":"),
        ).encode("utf-8")

app = FastAPI(title="Portfolio API", version="1.0.0", default_response_class=DecimalJSONResponse)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize exchange for live balance queries
# Note: Kraken requires nonces to be strictly increasing. Using microseconds ensures high values.
exchange = None
_nonce_counter = 0

def get_kraken_nonce():
    """Generate an always-increasing nonce for Kraken API"""
    global _nonce_counter
    _nonce_counter += 1
    # Use microseconds + counter to ensure uniqueness
    return int(time.time() * 1000000) + _nonce_counter

if settings.kraken_api_key and settings.kraken_secret_key:
    try:
        exchange = ccxt.kraken({
            'apiKey': settings.kraken_api_key,
            'secret': settings.kraken_secret_key,
            'enableRateLimit': True,
            'nonce': get_kraken_nonce,  # Custom nonce generator
        })
        # Test connection
        exchange.load_markets()
        logger.info("kraken_exchange_initialized")
    except Exception as e:
        logger.warning("exchange_init_failed", error=str(e))

class PortfolioState(BaseModel):
    mode: str
    total_capital: float
    deployed_capital: float
    available_capital: float
    open_positions: int
    total_pnl: Optional[float]
    total_pnl_pct: Optional[float]
    daily_pnl: Optional[float]
    daily_pnl_pct: Optional[float]
    daily_target_met: bool
    timestamp: datetime

@app.get("/")
def root():
    return {"service": "Portfolio API", "status": "running", "version": "1.0.0"}

@app.get("/health")
def health():
    return {"status": "healthy", "live_balance_enabled": exchange is not None}

@app.get("/balance/live")
def get_live_balance():
    """Get live account balance from Kraken"""
    try:
        if not exchange:
            return {
                "status": "disabled",
                "message": "Live trading not configured",
                "total_usd": 0,
                "balances": {}
            }
        
        # Fetch balance from exchange
        balance = exchange.fetch_balance()
        
        # Get total balance in USD
        total_balance = {}
        usd_value = 0
        
        for currency, amounts in balance.get('total', {}).items():
            if amounts and amounts > 0:
                total_balance[currency] = {
                    'total': float(amounts),
                    'free': float(balance.get('free', {}).get(currency, 0)),
                    'used': float(balance.get('used', {}).get(currency, 0))
                }
                
                # Try to convert to USD value
                if currency == 'USD' or currency == 'USDT' or currency == 'USDC':
                    usd_value += float(amounts)
                elif currency != 'USD':
                    try:
                        ticker = exchange.fetch_ticker(f'{currency}/USD')
                        usd_value += float(amounts) * float(ticker['last'])
                    except:
                        pass  # Skip if can't get USD price
        
        logger.info("live_balance_fetched", total_usd=usd_value, currencies=len(total_balance))
        
        return {
            "status": "success",
            "total_usd": round(usd_value, 2),
            "balances": total_balance,
            "timestamp": datetime.now().isoformat()
        }
    
    except Exception as e:
        logger.error("live_balance_error", error=str(e))
        return {
            "status": "error",
            "message": str(e),
            "total_usd": 0,
            "balances": {}
        }

@app.get("/portfolio", response_model=PortfolioState)
def get_portfolio(mode: str = Query("paper", regex="^(paper|live)$")):
    """Get current portfolio state"""
    try:
        portfolio = get_portfolio_state(mode)
        
        if not portfolio:
            raise HTTPException(status_code=404, detail=f"No portfolio found for mode: {mode}")
        
        logger.info("portfolio_fetched", mode=mode)
        return portfolio
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error("portfolio_fetch_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/positions")
def get_positions(
    mode: str = Query("paper", regex="^(paper|live)$"),
    status: Optional[str] = Query(None, regex="^(open|closed|stopped_out)$"),
    position_type: Optional[str] = Query(None, regex="^(strategy|ensemble)$")
):
    """Get positions with optional filtering by position_type"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Build query dynamically based on filters
                query = """
                    SELECT p.*, s.name as strategy_name
                    FROM positions p
                    LEFT JOIN strategies s ON p.strategy_id = s.id
                    WHERE p.mode = %s
                """
                params = [mode]
                
                if status:
                    query += " AND p.status = %s"
                    params.append(status)
                
                if position_type:
                    query += " AND p.position_type = %s"
                    params.append(position_type)
                
                query += " ORDER BY p.entry_time DESC LIMIT 50"
                
                cur.execute(query, params)
                positions = [dict(row) for row in cur.fetchall()]
        
        logger.info("positions_fetched", mode=mode, count=len(positions))
        
        return {
            "status": "success",
            "mode": mode,
            "count": len(positions),
            "positions": positions
        }
    
    except Exception as e:
        logger.error("positions_fetch_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/rebalance")
async def rebalance_portfolio(mode: str = Query("paper", regex="^(paper|live)$")):
    """
    Rebalance portfolio - reallocate capital from underperforming positions to better opportunities
    
    Philosophy:
    - This is NOT a stop-loss mechanism (stop-loss handles exits)
    - Only close positions if there's a demonstrably better opportunity available
    - Compare opportunity cost: current position vs available signals
    - Let ensemble trading and strategy signals compete for capital
    """
    try:
        # Get current portfolio state
        portfolio = get_portfolio_state(mode)
        if not portfolio:
            raise HTTPException(status_code=404, detail="Portfolio not found")
        
        # Get open positions
        open_positions = get_open_positions(mode)
        
        # Get top active signals (both strategy and ensemble)
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Get strategy signals
                cur.execute("""
                    SELECT s.*, st.name as strategy_name, 'strategy' as signal_source
                    FROM signals s
                    LEFT JOIN strategies st ON s.strategy_id = st.id
                    WHERE NOT s.acted_on 
                    AND s.expires_at > NOW()
                    AND s.quality_score >= %s
                    ORDER BY s.quality_score DESC
                    LIMIT 20
                """, (settings.min_signal_quality,))
                signals = [dict(row) for row in cur.fetchall()]
                
                # Get ensemble signals (look for signal_votes indicating consensus)
                cur.execute("""
                    SELECT 
                        symbol,
                        signal_type,
                        AVG(quality_score) as quality_score,
                        COUNT(*) as vote_count,
                        'ensemble' as signal_source,
                        MAX(generated_at) as generated_at
                    FROM signals
                    WHERE NOT acted_on
                    AND expires_at > NOW()
                    AND quality_score >= 70
                    GROUP BY symbol, signal_type
                    HAVING COUNT(*) >= 3
                    ORDER BY AVG(quality_score) DESC, COUNT(*) DESC
                    LIMIT 10
                """)
                ensemble_signals = [dict(row) for row in cur.fetchall()]
                
        # Combine and sort all opportunities by quality
        all_opportunities = signals + ensemble_signals
        all_opportunities.sort(key=lambda x: float(x.get('quality_score', 0)), reverse=True)
        
        actions_taken = {
            "positions_closed": 0,
            "positions_opened": 0,
            "positions_reinforced": 0,
            "capital_reallocated": 0.0,
            "close_reasons": [],
            "reallocation_details": []
        }
        
        # STEP 1: Identify underperforming positions that could be reallocated
        # Only close if there's a better opportunity available
        positions_to_close = []
        
        for position in open_positions:
            # Score the current position
            position_quality = evaluate_position_quality(position)
            current_pnl_pct = float(position.get('current_pnl_pct', 0))
            
            # Only consider reallocation if position is underperforming
            # (losing money OR flat with low momentum)
            if not is_underperforming(position):
                continue
            
            # Find best available opportunity that's significantly better
            best_opportunity = None
            quality_delta = 0
            
            for opp in all_opportunities:
                # Skip if already have position in this symbol
                if opp['symbol'] == position['symbol']:
                    continue
                if has_position_in_symbol(opp['symbol'], mode):
                    continue
                
                opp_quality = float(opp.get('quality_score', 0))
                
                # Require significant quality improvement to justify reallocation
                # (10+ points for strategy signals, 15+ points for ensemble due to higher threshold)
                min_improvement = 15 if opp.get('signal_source') == 'ensemble' else 10
                
                if opp_quality > position_quality + min_improvement:
                    best_opportunity = opp
                    quality_delta = opp_quality - position_quality
                    break
            
            # If we found a significantly better opportunity, mark for reallocation
            if best_opportunity:
                positions_to_close.append({
                    'position': position,
                    'reason': 'reallocation',
                    'current_quality': position_quality,
                    'target_opportunity': best_opportunity,
                    'quality_delta': quality_delta
                })
        
        # Execute reallocations
        capital_freed = 0.0
        available = float(portfolio['available_capital'])
        
        for realloc in positions_to_close:
            position = realloc['position']
            opportunity = realloc['target_opportunity']
            
            # Track why we're closing
            actions_taken["close_reasons"].append({
                "symbol": position['symbol'],
                "pnl": float(position.get('current_pnl', 0)),
                "pnl_pct": float(position.get('current_pnl_pct', 0)),
                "reason": "reallocation_to_better_opportunity",
                "target_symbol": opportunity['symbol'],
                "quality_improvement": f"+{realloc['quality_delta']:.1f}"
            })
            
            actions_taken["reallocation_details"].append({
                "from": position['symbol'],
                "to": opportunity['symbol'],
                "quality_delta": realloc['quality_delta'],
                "pnl_pct": float(position.get('current_pnl_pct', 0))
            })
            
            # Close the underperforming position
            close_position(position['id'], mode)
            actions_taken["positions_closed"] += 1
            
            qty = float(position.get('quantity', 0))
            price = float(position.get('entry_price', 0))
            capital_freed += qty * price
        
        # Refresh portfolio after closes
        portfolio = get_portfolio_state(mode)
        open_positions = get_open_positions(mode)
        available = float(portfolio['available_capital'])
        
        logger.info("rebalance_step1_complete", 
                   closed=actions_taken["positions_closed"],
                   capital_freed=capital_freed,
                   available_now=available,
                   reallocations=len(positions_to_close))
        
        # STEP 2: Evaluate existing winners - should we add to them?
        # Score existing positions by momentum
        position_scores = []
        for position in open_positions:
            momentum = get_position_momentum_score(position)
            pnl_pct = float(position.get('current_pnl_pct', 0))
            
            # Only consider adding to profitable positions with strong momentum
            if pnl_pct > 0 and momentum > 0.5:
                position_scores.append({
                    'position': position,
                    'momentum': float(momentum),
                    'pnl_pct': float(pnl_pct),
                    'score': float(momentum * (1 + pnl_pct/100))  # Combined score
                })
        
        # Sort by score (best opportunities first)
        position_scores.sort(key=lambda x: x['score'], reverse=True)
        
        # Add to top performing winners if they're still hot
        for scored in position_scores[:2]:  # Top 2 winners
            if available < 20:  # Need meaningful capital to add
                break
            
            position = scored['position']
            additional_allocation = float(min(available * 0.3, available - 10))  # 30% or leave $10 reserve
            
            if additional_allocation > 10:
                logger.info("reinforcing_winner",
                           symbol=position['symbol'],
                           current_pnl_pct=scored['pnl_pct'],
                           momentum=scored['momentum'],
                           additional_amount=additional_allocation)
                
                # Would call Trading API to add to position
                actions_taken["positions_reinforced"] += 1
                actions_taken["capital_reallocated"] += additional_allocation
                available -= additional_allocation
        
        # STEP 3: Allocate available capital to best opportunities (strategy + ensemble)
        for opportunity in all_opportunities:
            if available < 10:  # Keep minimum reserve
                break
            
            # Check if already have position in this symbol
            if has_position_in_symbol(opportunity['symbol'], mode):
                continue
            
            # Calculate allocation based on signal quality
            allocation = calculate_allocation(opportunity, available)
            
            if allocation > 0:
                # Log the planned allocation
                logger.info("allocation_planned", 
                           symbol=opportunity['symbol'], 
                           amount=allocation,
                           quality=opportunity.get('quality_score'),
                           source=opportunity.get('signal_source', 'strategy'))
                actions_taken["positions_opened"] += 1
                actions_taken["capital_reallocated"] += allocation
                available -= allocation
        
        # Save new snapshot
        save_portfolio_snapshot(mode)
        
        logger.info("rebalance_complete", 
                   mode=mode, 
                   closed=actions_taken["positions_closed"],
                   opened=actions_taken["positions_opened"],
                   reinforced=actions_taken["positions_reinforced"],
                   reallocated=actions_taken["capital_reallocated"])
        
        # Convert any remaining Decimal values to float for JSON serialization
        result = {
            "status": "success",
            "mode": mode,
            "actions": {
                "positions_closed": actions_taken["positions_closed"],
                "positions_opened": actions_taken["positions_opened"],
                "positions_reinforced": actions_taken["positions_reinforced"],
                "capital_reallocated": float(actions_taken["capital_reallocated"]),
                "close_reasons": actions_taken["close_reasons"],
                "reallocations": actions_taken["reallocation_details"]
            },
            "available_capital": float(available),
            "summary": {
                "positions_closed": actions_taken["positions_closed"],
                "positions_opened": actions_taken["positions_opened"],
                "winners_reinforced": actions_taken["positions_reinforced"],
                "total_reallocated": round(float(actions_taken["capital_reallocated"]), 2),
                "close_reasons": actions_taken["close_reasons"],
                "reallocations": actions_taken["reallocation_details"]
            }
        }
        return result
    
    except Exception as e:
        import traceback
        logger.error("rebalance_error", error=str(e), traceback=traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

def evaluate_position_quality(position: Dict) -> float:
    """
    Evaluate the quality/score of a current position for comparison with available signals
    Returns a score comparable to signal quality scores
    
    Factors:
    - Current P&L percentage (winning positions score higher)
    - Momentum score (positive momentum adds to score)
    - Hold time (very new or very old positions scored differently)
    """
    from datetime import datetime, timezone
    
    current_pnl_pct = float(position.get('current_pnl_pct', 0))
    momentum = get_position_momentum_score(position)
    
    # Base score starts at 50 (neutral)
    base_score = 50.0
    
    # P&L contribution: +/- 20 points max based on performance
    # Scale: +5% = +20pts, -5% = -20pts
    pnl_contribution = current_pnl_pct * 4.0  # Each 1% = 4 points
    pnl_contribution = max(-20, min(20, pnl_contribution))
    
    # Momentum contribution: +/- 15 points
    # Strong positive momentum = +15, strong negative = -15
    momentum_contribution = momentum * 15.0
    
    # Calculate hold time
    entry_time = position.get('entry_time')
    if isinstance(entry_time, str):
        entry_time = datetime.fromisoformat(entry_time.replace('Z', '+00:00'))
    
    if entry_time and entry_time.tzinfo:
        now = datetime.now(timezone.utc)
    else:
        now = datetime.utcnow()
        if entry_time:
            entry_time = entry_time.replace(tzinfo=None)
    
    hold_time_minutes = (now - entry_time).total_seconds() / 60 if entry_time else 0
    
    # Hold time penalty: positions held too long with no progress lose value
    # Under 120 min: no penalty
    # 120-360 min: -0 to -10 pts (gradual)
    # Over 360 min: -10 pts
    hold_time_penalty = 0
    if hold_time_minutes > 120:
        if hold_time_minutes > 360:
            hold_time_penalty = -10
        else:
            # Gradual penalty from 0 to -10 over 120-360 min range
            hold_time_penalty = -((hold_time_minutes - 120) / 240) * 10
    
    quality_score = base_score + pnl_contribution + momentum_contribution + hold_time_penalty
    
    return float(quality_score)

def is_underperforming(position: Dict) -> bool:
    """
    Determine if a position is underperforming and should be considered for reallocation
    
    Criteria for underperforming:
    - Losing money (negative P&L)
    - OR flat/minimal gains with weak momentum
    - BUT NOT if it's a very new position (give it time to develop)
    """
    from datetime import datetime, timezone
    
    current_pnl_pct = float(position.get('current_pnl_pct', 0))
    momentum = get_position_momentum_score(position)
    
    # Calculate hold time
    entry_time = position.get('entry_time')
    if isinstance(entry_time, str):
        entry_time = datetime.fromisoformat(entry_time.replace('Z', '+00:00'))
    
    if entry_time and entry_time.tzinfo:
        now = datetime.now(timezone.utc)
    else:
        now = datetime.utcnow()
        if entry_time:
            entry_time = entry_time.replace(tzinfo=None)
    
    hold_time_minutes = (now - entry_time).total_seconds() / 60 if entry_time else 0
    
    # Give new positions time to develop (at least 60 minutes)
    if hold_time_minutes < 60:
        return False
    
    # Clearly losing with negative momentum
    if current_pnl_pct < -1.0 and momentum < 0:
        return True
    
    # Losing modestly but stagnant (no momentum)
    if current_pnl_pct < -0.5 and momentum < 0.1:
        return True
    
    # Flat/small gains but completely stagnant for a long time
    if hold_time_minutes > 180 and current_pnl_pct < 1.0 and momentum < 0.05:
        return True
    
    return False

def get_position_momentum_score(position: Dict) -> float:
    """
    Calculate momentum score for a position based on recent price action and volume
    Returns: -1.0 (strong bearish) to +1.0 (strong bullish)
    
    Analyzes:
    - Short-term price momentum (last 15-30 min)
    - Volume trend (increasing/decreasing)
    - Price velocity (rate of change)
    """
    symbol = position['symbol']
    
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Get recent candles (last 30 minutes of 5-min data)
                cur.execute("""
                    SELECT timestamp, close, volume, high, low
                    FROM ohlcv_candles
                    WHERE symbol = %s
                    AND timestamp > NOW() - INTERVAL '30 minutes'
                    ORDER BY timestamp DESC
                    LIMIT 6
                """, (symbol,))
                
                candles = [dict(row) for row in cur.fetchall()]
        
        if len(candles) < 4:
            return 0.0  # Not enough data
        
        # Reverse to chronological order
        candles = list(reversed(candles))
        
        # Calculate price momentum (recent vs older)
        recent_prices = [c['close'] for c in candles[-3:]]  # Last 15 min
        older_prices = [c['close'] for c in candles[:3]]    # Previous 15 min
        
        recent_avg = sum(recent_prices) / len(recent_prices)
        older_avg = sum(older_prices) / len(older_prices)
        
        price_momentum = ((recent_avg - older_avg) / older_avg) * 100 if older_avg > 0 else 0
        
        # Calculate volume trend
        recent_volume = sum(c['volume'] for c in candles[-3:])
        older_volume = sum(c['volume'] for c in candles[:3])
        
        volume_trend = ((recent_volume - older_volume) / older_volume) if older_volume > 0 else 0
        
        # Calculate price velocity (acceleration)
        prices = [c['close'] for c in candles]
        velocity = 0
        for i in range(1, len(prices)):
            velocity += (prices[i] - prices[i-1]) / prices[i-1] if prices[i-1] > 0 else 0
        velocity /= len(prices) - 1
        
        # Combine signals into momentum score
        # Positive momentum with volume support = bullish
        # Negative momentum with volume = bearish
        momentum_score = 0
        
        # Price momentum component (40% weight)
        if price_momentum > 1.0:  # Strong upward price movement
            momentum_score += 0.4
        elif price_momentum > 0.3:  # Moderate upward
            momentum_score += 0.2
        elif price_momentum < -1.0:  # Strong downward
            momentum_score -= 0.4
        elif price_momentum < -0.3:  # Moderate downward
            momentum_score -= 0.2
        
        # Volume trend component (30% weight)
        if volume_trend > 0.5 and price_momentum > 0:  # Volume supporting uptrend
            momentum_score += 0.3
        elif volume_trend > 0.5 and price_momentum < 0:  # Volume on downtrend (bad)
            momentum_score -= 0.3
        elif volume_trend < -0.3:  # Decreasing volume (weakening)
            momentum_score -= 0.15
        
        # Velocity component (30% weight)
        if velocity > 0.005:  # Accelerating up
            momentum_score += 0.3
        elif velocity < -0.005:  # Accelerating down
            momentum_score -= 0.3
        
        # Clamp to [-1, 1]
        momentum_score = max(-1.0, min(1.0, momentum_score))
        
        logger.debug("momentum_calculated", 
                    symbol=symbol,
                    score=round(momentum_score, 3),
                    price_momentum=round(price_momentum, 2),
                    volume_trend=round(volume_trend, 2),
                    velocity=round(velocity, 4))
        
        return momentum_score
        
    except Exception as e:
        logger.error("momentum_calc_error", symbol=symbol, error=str(e))
        return 0.0  # Default to neutral on error

def close_position(position_id: int, mode: str):
    """Close a position with proper exit price and P&L calculation"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Get position details first
            cur.execute("""
                SELECT * FROM positions
                WHERE id = %s AND mode = %s AND status = 'open'
            """, (position_id, mode))
            position = cur.fetchone()
            
            if not position:
                logger.warning("close_position_not_found", position_id=position_id, mode=mode)
                return
            
            # Get current market price for exit
            cur.execute("""
                SELECT close FROM ohlcv_candles
                WHERE symbol = %s
                ORDER BY timestamp DESC
                LIMIT 1
            """, (position['symbol'],))
            candle = cur.fetchone()
            
            if not candle or candle['close'] is None:
                logger.error("close_position_no_price", position_id=position_id, symbol=position['symbol'])
                # Don't close if we can't get a price!
                return
            
            exit_price = float(candle['close'])
            quantity = float(position['quantity'])
            entry_price = float(position['entry_price'])
            entry_fee = float(position.get('entry_fee', 0))
            
            # Calculate exit fee
            exit_fee = quantity * exit_price * 0.0026  # Market order fee
            
            # Calculate P&L
            pnl = (exit_price - entry_price) * quantity - exit_fee - entry_fee
            pnl_pct = (pnl / (entry_price * quantity)) * 100 if (entry_price * quantity) > 0 else 0
            
            # Update position with complete closing data
            cur.execute("""
                UPDATE positions
                SET status = 'closed',
                    exit_time = NOW(),
                    exit_price = %s,
                    exit_fee = %s,
                    realized_pnl = %s,
                    realized_pnl_pct = %s,
                    trade_result = %s
                WHERE id = %s AND mode = %s
            """, (exit_price, exit_fee, pnl, pnl_pct, 
                  ('win' if pnl > 0 else 'loss'), position_id, mode))
            
            logger.info("position_closed_by_rebalance",
                       position_id=position_id,
                       symbol=position['symbol'],
                       entry=entry_price,
                       exit=exit_price,
                       pnl=round(pnl, 2))

def has_position_in_symbol(symbol: str, mode: str) -> bool:
    """Check if already have an open position in this symbol"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) as count FROM positions
                WHERE symbol = %s AND mode = %s AND status = 'open'
            """, (symbol, mode))
            return cur.fetchone()['count'] > 0

def calculate_allocation(signal: Dict, available_capital: float) -> float:
    """Calculate capital allocation for a signal"""
    quality = signal['quality_score']
    timeframe = signal.get('projected_timeframe_minutes', 240)
    
    # Strong signal (80+) + short timeframe (<120 min) = 80% of available
    if quality >= 80 and timeframe < 120:
        return available_capital * 0.80
    
    # Good signal (70-79) + medium timeframe (120-240 min) = 50% of available  
    elif quality >= 70 and timeframe < 240:
        return available_capital * 0.50
    
    # Decent signal (60-69) = 20% of available
    elif quality >= 60:
        return available_capital * 0.20
    
    return 0

def save_portfolio_snapshot(mode: str):
    """Save current portfolio state snapshot"""
    portfolio = get_portfolio_state(mode)
    open_positions = get_open_positions(mode)
    
    with get_connection() as conn:
        with conn.cursor() as cur:
            import psycopg2.extras
            import json
            from decimal import Decimal
            from datetime import datetime
            
            def clean_value(value):
                """Convert Decimal and datetime to JSON-serializable types"""
                if isinstance(value, Decimal):
                    return float(value)
                elif isinstance(value, datetime):
                    return value.isoformat()
                return value
            
            # Convert problematic values in positions before serializing
            clean_positions = []
            for p in open_positions:
                clean_pos = {key: clean_value(value) for key, value in dict(p).items()}
                clean_positions.append(clean_pos)
            
            cur.execute("""
                INSERT INTO portfolio_snapshots 
                (mode, total_capital, deployed_capital, available_capital, 
                 open_positions, positions_snapshot, timestamp)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
            """, (
                mode,
                float(portfolio['total_capital']),
                float(portfolio['deployed_capital']),
                float(portfolio['available_capital']),
                len(open_positions),
                psycopg2.extras.Json(clean_positions)
            ))

@app.get("/performance")
def get_performance(
    mode: str = Query("paper", regex="^(paper|live)$"),
    days: int = Query(7, ge=1, le=90)
):
    """Get portfolio performance over time"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        DATE(timestamp) as date,
                        AVG(total_capital) as avg_capital,
                        AVG(daily_pnl_pct) as avg_daily_pnl_pct,
                        COUNT(*) as snapshots
                    FROM portfolio_snapshots
                    WHERE mode = %s 
                    AND timestamp > NOW() - INTERVAL '%s days'
                    GROUP BY DATE(timestamp)
                    ORDER BY date DESC
                """, (mode, days))
                
                performance = [dict(row) for row in cur.fetchall()]
        
        return {
            "status": "success",
            "mode": mode,
            "days": days,
            "performance": performance
        }
    
    except Exception as e:
        logger.error("performance_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/stats")
def get_stats(mode: str = Query("paper", regex="^(paper|live)$")):
    """Get portfolio statistics"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Total trades
                cur.execute("""
                    SELECT COUNT(*) as count FROM positions WHERE mode = %s
                """, (mode,))
                total_trades = cur.fetchone()['count']
                
                # Win/loss breakdown
                cur.execute("""
                    SELECT 
                        trade_result,
                        COUNT(*) as count,
                        AVG(realized_pnl_pct) as avg_pnl_pct
                    FROM positions
                    WHERE mode = %s AND status = 'closed'
                    GROUP BY trade_result
                """, (mode,))
                trade_results = {row['trade_result']: dict(row) for row in cur.fetchall()}
                
                # Current state
                portfolio = get_portfolio_state(mode)
        
        wins = trade_results.get('win', {}).get('count', 0)
        losses = trade_results.get('loss', {}).get('count', 0)
        win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
        
        return {
            "status": "success",
            "mode": mode,
            "total_trades": total_trades,
            "win_rate": round(win_rate, 2),
            "trade_results": trade_results,
            "current_capital": float(portfolio['total_capital']),
            "total_pnl": float(portfolio.get('total_pnl', 0) or 0),
            "total_pnl_pct": float(portfolio.get('total_pnl_pct', 0) or 0)
        }
    
    except Exception as e:
        logger.error("stats_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/symbols/stats")
def get_symbol_stats(mode: str = Query("paper", regex="^(paper|live)$")):
    """Get per-symbol trading statistics including win rates and fees"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Get stats for 24h, 7d, and 30d windows
                cur.execute("""
                    WITH symbol_stats AS (
                        SELECT 
                            symbol,
                            -- 24h stats
                            COUNT(*) FILTER (WHERE entry_time >= NOW() - INTERVAL '24 hours') as trades_24h,
                            SUM(CASE WHEN realized_pnl_pct > 0 AND entry_time >= NOW() - INTERVAL '24 hours' THEN 1 ELSE 0 END) as wins_24h,
                            SUM(CASE WHEN realized_pnl_pct <= 0 AND entry_time >= NOW() - INTERVAL '24 hours' THEN 1 ELSE 0 END) as losses_24h,
                            COALESCE(SUM(realized_pnl) FILTER (WHERE entry_time >= NOW() - INTERVAL '24 hours'), 0) as pnl_24h,
                            COALESCE(SUM(entry_fee + COALESCE(exit_fee, 0)) FILTER (WHERE entry_time >= NOW() - INTERVAL '24 hours'), 0) as fees_24h,
                            
                            -- 7d stats
                            COUNT(*) FILTER (WHERE entry_time >= NOW() - INTERVAL '7 days') as trades_7d,
                            SUM(CASE WHEN realized_pnl_pct > 0 AND entry_time >= NOW() - INTERVAL '7 days' THEN 1 ELSE 0 END) as wins_7d,
                            SUM(CASE WHEN realized_pnl_pct <= 0 AND entry_time >= NOW() - INTERVAL '7 days' THEN 1 ELSE 0 END) as losses_7d,
                            COALESCE(SUM(realized_pnl) FILTER (WHERE entry_time >= NOW() - INTERVAL '7 days'), 0) as pnl_7d,
                            COALESCE(SUM(entry_fee + COALESCE(exit_fee, 0)) FILTER (WHERE entry_time >= NOW() - INTERVAL '7 days'), 0) as fees_7d,
                            
                            -- 30d stats
                            COUNT(*) FILTER (WHERE entry_time >= NOW() - INTERVAL '30 days') as trades_30d,
                            SUM(CASE WHEN realized_pnl_pct > 0 AND entry_time >= NOW() - INTERVAL '30 days' THEN 1 ELSE 0 END) as wins_30d,
                            SUM(CASE WHEN realized_pnl_pct <= 0 AND entry_time >= NOW() - INTERVAL '30 days' THEN 1 ELSE 0 END) as losses_30d,
                            COALESCE(SUM(realized_pnl) FILTER (WHERE entry_time >= NOW() - INTERVAL '30 days'), 0) as pnl_30d,
                            COALESCE(SUM(entry_fee + COALESCE(exit_fee, 0)) FILTER (WHERE entry_time >= NOW() - INTERVAL '30 days'), 0) as fees_30d
                        FROM positions
                        WHERE mode = %s AND status = 'closed'
                        GROUP BY symbol
                    )
                    SELECT 
                        s.symbol,
                        s.name,
                        COALESCE(st.trades_24h, 0) as trades_24h,
                        COALESCE(st.wins_24h, 0) as wins_24h,
                        COALESCE(st.losses_24h, 0) as losses_24h,
                        ROUND(CAST(st.pnl_24h AS NUMERIC), 2) as pnl_24h,
                        ROUND(CAST(st.fees_24h AS NUMERIC), 4) as fees_24h,
                        
                        COALESCE(st.trades_7d, 0) as trades_7d,
                        COALESCE(st.wins_7d, 0) as wins_7d,
                        COALESCE(st.losses_7d, 0) as losses_7d,
                        ROUND(CAST(st.pnl_7d AS NUMERIC), 2) as pnl_7d,
                        ROUND(CAST(st.fees_7d AS NUMERIC), 4) as fees_7d,
                        
                        COALESCE(st.trades_30d, 0) as trades_30d,
                        COALESCE(st.wins_30d, 0) as wins_30d,
                        COALESCE(st.losses_30d, 0) as losses_30d,
                        ROUND(CAST(st.pnl_30d AS NUMERIC), 2) as pnl_30d,
                        ROUND(CAST(st.fees_30d AS NUMERIC), 4) as fees_30d,
                        COALESCE(tr.best_trust, 0.0) as best_trust_factor,
                        COALESCE(tr.best_pf, 0.0) as best_profit_factor,
                        COALESCE(tr.strategy_trades, 0) as strategy_trades
                    FROM symbols s
                    LEFT JOIN symbol_stats st ON s.symbol = st.symbol
                    LEFT JOIN (
                        SELECT symbol,
                               MAX(trust_factor) AS best_trust,
                               MAX(profit_factor) AS best_pf,
                               SUM(total_trades) AS strategy_trades
                        FROM symbol_strategies
                        WHERE status = 'active'
                        GROUP BY symbol
                    ) tr ON tr.symbol = s.symbol
                    WHERE s.status = 'active'
                    ORDER BY COALESCE(tr.best_trust, 0.0) DESC, s.symbol
                """, (mode,))
                
                stats = [dict(row) for row in cur.fetchall()]
                
                logger.info("symbol_stats_fetched", mode=mode, symbols=len(stats))
                return {
                    "status": "success",
                    "mode": mode,
                    "symbols": stats
                }
    
    except Exception as e:
        logger.error("symbol_stats_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/config")
def get_config():
    """Get system-wide policy configuration"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT config_value FROM system_config WHERE config_key = 'policies'
                """)
                row = cur.fetchone()
                
                # Default policies if none exist
                defaults = {
                    "position_size_pct": 10.0,
                    "max_positions": 5,
                    "stop_loss_pct": 2.0,
                    "take_profit_pct": 5.0,
                    "trailing_stop_pct": 1.5,
                    "max_drawdown_pct": 10.0,
                    "daily_loss_limit": 3.0,
                    "max_hold_minutes": 1440,
                    "min_time_between_trades": 30,
                    "min_signal_quality": 60,
                    "require_confirmation": False
                }
                
                if row:
                    return row['config_value']
                else:
                    return defaults
    
    except Exception as e:
        logger.error("config_get_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/config")
def update_config(config: Dict):
    """Update system-wide policy configuration"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO system_config (config_key, config_value, updated_at)
                    VALUES ('policies', %s, NOW())
                    ON CONFLICT (config_key)
                    DO UPDATE SET config_value = %s, updated_at = NOW()
                    RETURNING config_value
                """, (config, config))
                
                conn.commit()
                result = cur.fetchone()
                
                logger.info("config_updated", config=config)
                return {"status": "success", "config": result['config_value']}
    
    except Exception as e:
        logger.error("config_update_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/risk/blacklist")
def get_blacklist():
    """Get symbol blacklist from Phase 3 risk manager
    
    Returns symbols with <-$5 P&L in last 30 days that are blocked from trading.
    Blacklist is rolling - symbols auto-unblock when performance improves.
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Get symbols with poor performance (< -$5 P&L in 30 days)
                cur.execute("""
                    SELECT 
                        symbol,
                        COUNT(*) as trade_count,
                        SUM(realized_pnl) as total_pnl,
                        AVG(realized_pnl) as avg_pnl
                    FROM positions
                    WHERE mode = 'paper'
                    AND position_type = 'ensemble'
                    AND status = 'closed'
                    AND entry_time >= NOW() - INTERVAL '30 days'
                    GROUP BY symbol
                    HAVING SUM(realized_pnl) < -5.0
                    ORDER BY SUM(realized_pnl) ASC
                """)
                
                blacklisted = []
                for row in cur.fetchall():
                    blacklisted.append({
                        'symbol': row['symbol'],
                        'trade_count': int(row['trade_count']),
                        'total_pnl': float(row['total_pnl']),
                        'avg_pnl': float(row['avg_pnl'])
                    })
                
                logger.info("blacklist_fetched", count=len(blacklisted))
                return {
                    'status': 'success',
                    'blacklisted': blacklisted,
                    'threshold': -5.0,
                    'window_days': 30,
                    'note': 'Symbols auto-unblock when 30-day P&L improves above -$5'
                }
    
    except Exception as e:
        logger.error("blacklist_fetch_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/risk/evaluations")
def get_signal_evaluations(limit: int = 20):
    """Get recent signal evaluations showing accept/reject decisions
    
    Shows real-time risk manager decisions with reasons, including position lifecycle data.
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Fetch evaluations with associated position data
                cur.execute("""
                    SELECT 
                        se.id,
                        se.timestamp,
                        se.symbol,
                        se.signal_type,
                        se.weighted_score,
                        se.proposed_value,
                        se.approved,
                        se.rejection_reason,
                        se.risk_checks,
                        se.mode,
                        p.id as position_id,
                        p.status as position_status,
                        p.entry_price,
                        p.exit_price,
                        p.current_price,
                        p.current_pnl,
                        p.current_pnl_pct,
                        p.realized_pnl,
                        p.realized_pnl_pct,
                        p.entry_time,
                        p.exit_time,
                        p.trade_result
                    FROM signal_evaluations se
                    LEFT JOIN positions p ON 
                        se.symbol = p.symbol 
                        AND se.mode = p.mode
                        AND p.entry_time >= se.timestamp - INTERVAL '5 minutes'
                        AND p.entry_time <= se.timestamp + INTERVAL '5 minutes'
                    ORDER BY se.timestamp DESC
                    LIMIT %s
                """, (limit,))
                
                evaluations = []
                for row in cur.fetchall():
                    eval_data = {
                        'id': row['id'],
                        'timestamp': row['timestamp'].isoformat() if row['timestamp'] else None,
                        'symbol': row['symbol'],
                        'signal_type': row['signal_type'],
                        'weighted_score': float(row['weighted_score']) if row['weighted_score'] else None,
                        'proposed_value': float(row['proposed_value']) if row['proposed_value'] else None,
                        'approved': row['approved'],
                        'rejection_reason': row['rejection_reason'],
                        'risk_checks': row['risk_checks'],
                        'mode': row['mode']
                    }
                    
                    # Add position data if exists
                    if row['position_id']:
                        eval_data['position'] = {
                            'position_id': row['position_id'],
                            'status': row['position_status'],
                            'entry_price': float(row['entry_price']) if row['entry_price'] else None,
                            'exit_price': float(row['exit_price']) if row['exit_price'] else None,
                            'current_price': float(row['current_price']) if row['current_price'] else None,
                            'current_pnl': float(row['current_pnl']) if row['current_pnl'] else None,
                            'current_pnl_pct': float(row['current_pnl_pct']) if row['current_pnl_pct'] else None,
                            'realized_pnl': float(row['realized_pnl']) if row['realized_pnl'] else None,
                            'realized_pnl_pct': float(row['realized_pnl_pct']) if row['realized_pnl_pct'] else None,
                            'entry_time': row['entry_time'].isoformat() if row['entry_time'] else None,
                            'exit_time': row['exit_time'].isoformat() if row['exit_time'] else None,
                            'trade_result': row['trade_result']
                        }
                    else:
                        eval_data['position'] = None
                    
                    evaluations.append(eval_data)
                
                logger.info("evaluations_fetched", count=len(evaluations))
                return {
                    'status': 'success',
                    'evaluations': evaluations,
                    'count': len(evaluations)
                }
    
    except Exception as e:
        logger.error("evaluations_fetch_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ─── Phase 8 Vision: Daily Allocation ───────────────────────────────────────

class DailyAllocationRequest(BaseModel):
    target_daily_pct: float = 0.005   # 0.5% daily target
    kelly_min: float = 0.10           # floor: 10% of capital per trade
    kelly_max: float = 0.25           # ceiling: 25% of capital per trade
    max_open_positions: int = 5


@app.post("/daily_allocation")
def daily_allocation(req: DailyAllocationRequest):
    """
    Compute recommended position sizes for today using Kelly Criterion.

    Kelly fraction = WR - (1 - WR) / RR  clamped to [kelly_min, kelly_max].
    Returns per-symbol allocation based on ensemble-ranked strategies.
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Available capital
                cur.execute("""
                    SELECT available_capital, total_capital
                    FROM portfolio_snapshots
                    ORDER BY snapshot_time DESC LIMIT 1
                """)
                snap = cur.fetchone()
                available = float(snap['available_capital']) if snap else settings.paper_starting_capital
                total = float(snap['total_capital']) if snap else settings.paper_starting_capital

                # Current open positions count
                cur.execute("""
                    SELECT COUNT(*) AS cnt FROM positions WHERE status = 'open'
                """)
                open_count = cur.fetchone()['cnt']

                slots_available = max(0, req.max_open_positions - open_count)
                if slots_available == 0:
                    return {
                        "status": "no_slots",
                        "open_positions": open_count,
                        "max_open_positions": req.max_open_positions,
                        "allocations": [],
                    }

                # Top symbols by best trust_factor strategy
                cur.execute("""
                    SELECT ss.symbol,
                           MAX(ss.trust_factor) AS best_trust,
                           MAX(ss.profit_factor) AS best_pf,
                           MAX(ss.win_rate)      AS best_wr
                    FROM symbol_strategies ss
                    WHERE ss.status = 'active'
                      AND ss.trust_factor > 0.1
                    GROUP BY ss.symbol
                    ORDER BY best_trust DESC
                    LIMIT %s
                """, (slots_available,))
                candidates = cur.fetchall()

        allocations = []
        for row in candidates:
            symbol = row['symbol']
            wr = float(row['best_wr'] or 50) / 100.0
            pf = float(row['best_pf'] or 1.0)
            # Reward-to-risk ratio derived from profit factor
            rr = pf if pf > 0 else 1.0
            # Kelly fraction
            kelly = wr - (1.0 - wr) / rr
            kelly = min(req.kelly_max, max(req.kelly_min, kelly))
            position_capital = round(available * kelly, 2)

            allocations.append({
                "symbol": symbol,
                "kelly_fraction": round(kelly, 4),
                "position_capital": position_capital,
                "win_rate_pct": round(wr * 100, 2),
                "profit_factor": round(pf, 3),
                "trust_factor": round(float(row['best_trust']), 4),
            })

        logger.info("daily_allocation_computed",
                    slots=slots_available, available=available,
                    symbols=[a['symbol'] for a in allocations])

        return {
            "status": "success",
            "available_capital": available,
            "total_capital": total,
            "open_positions": open_count,
            "slots_available": slots_available,
            "target_daily_pct": req.target_daily_pct,
            "allocations": allocations,
            "computed_at": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        logger.error("daily_allocation_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))



@app.post("/force-refresh/{symbol}")
async def force_refresh_symbol(symbol: str, background_tasks: BackgroundTasks):
    """
    Trigger a full evaluation cycle for the given symbol:
    1. Assign all enabled strategies to symbol (via ensemble_api)
    2. Rerank strategies based on trust_factor
    Returns a summary of steps triggered; backtests run asynchronously.
    """
    import httpx
    steps = []
    host = settings.service_host

    try:
        # Step 1: Assign all strategies to symbol
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"http://{host}:{settings.port_ensemble_api}/assign-all-strategies/{symbol}"
            )
            if resp.status_code == 200:
                data = resp.json()
                steps.append({"step": "assign_strategies", "status": "ok",
                               "assigned": data.get("assigned", 0)})
            else:
                steps.append({"step": "assign_strategies", "status": "error",
                               "detail": resp.text[:200]})

        # Step 2: Rerank
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"http://{host}:{settings.port_ensemble_api}/rerank/{symbol}"
            )
            if resp.status_code == 200:
                steps.append({"step": "rerank", "status": "ok"})
            else:
                steps.append({"step": "rerank", "status": "error",
                               "detail": resp.text[:200]})

        return {
            "status": "triggered",
            "symbol": symbol,
            "steps": steps,
        }

    except Exception as e:
        logger.error("force_refresh_error", symbol=symbol, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("services.portfolio_api.main:app", host="0.0.0.0", port=settings.port_portfolio_api, workers=4)
