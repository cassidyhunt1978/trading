"""Trading API - Execute Trades & Manage Positions"""
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Literal
from datetime import datetime
import sys
import os
import ccxt

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.database import get_connection
from shared.config import get_settings
from shared.logging_config import setup_logging

settings = get_settings()
logger = setup_logging('trading_api', settings.log_level)

app = FastAPI(title="Trading API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize exchange (Coinbase preferred, fallback to Kraken)
exchange = None
if settings.coinbase_api_key and settings.coinbase_api_secret:
    exchange = ccxt.coinbase({
        'apiKey': settings.coinbase_api_key,
        'secret': settings.coinbase_api_secret,
        'enableRateLimit': True,
    })
    logger.info("coinbase_exchange_initialized")
elif settings.kraken_api_key and settings.kraken_secret_key:
    exchange = ccxt.kraken({
        'apiKey': settings.kraken_api_key,
        'secret': settings.kraken_secret_key,
        'enableRateLimit': True,
    })
    logger.info("kraken_exchange_initialized")
else:
    logger.warning("exchange_credentials_missing", msg="Live trading disabled")

class TradeRequest(BaseModel):
    symbol: str
    side: Literal['buy', 'sell']
    amount: float
    price: Optional[float] = None  # None = market order
    mode: Literal['paper', 'live']
    signal_id: Optional[int] = None
    strategy_id: Optional[int] = None
    stop_loss_pct: Optional[float] = 5.0
    take_profit_pct: Optional[float] = 10.0
    position_type: Optional[str] = 'ensemble'  # 'ensemble' or 'strategy'

class ClosePositionRequest(BaseModel):
    position_id: int
    mode: Literal['paper', 'live']
    reason: Optional[str] = "manual"

@app.get("/")
def root():
    return {"service": "Trading API", "status": "running", "version": "1.0.0"}

@app.get("/health")
def health():
    return {
        "status": "healthy",
        "live_trading_enabled": exchange is not None
    }

@app.post("/execute")
async def execute_trade(trade: TradeRequest):
    """Execute a trade (paper or live)"""
    try:
        logger.info("trade_requested", 
                   symbol=trade.symbol, 
                   side=trade.side, 
                   amount=trade.amount,
                   mode=trade.mode)
        
        if trade.mode == "live":
            if not exchange:
                raise HTTPException(status_code=400, 
                                  detail="Live trading not configured (missing API keys)")
            
            # Execute live trade via exchange (Coinbase/Kraken)
            result = execute_live_trade(trade)
        else:
            # Execute paper trade (simulated)
            result = execute_paper_trade(trade)
        
        # Mark signal as acted upon if provided
        if trade.signal_id:
            mark_signal_acted(trade.signal_id)
        
        logger.info("trade_executed", result=result)
        
        return {
            "status": "success",
            "trade": result
        }
    
    except ccxt.InsufficientFunds as e:
        logger.error("insufficient_funds", error=str(e))
        raise HTTPException(status_code=400, detail="Insufficient funds")
    
    except ccxt.ExchangeError as e:
        logger.error("exchange_error", error=str(e))
        raise HTTPException(status_code=500, detail=f"Exchange error: {str(e)}")
    
    except Exception as e:
        logger.error("trade_execution_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

def execute_live_trade(trade: TradeRequest) -> dict:
    """Execute a live trade on the exchange (Coinbase/Kraken)"""
    try:
        # Place order
        if trade.price:
            # Limit order
            order = exchange.create_limit_order(
                symbol=trade.symbol,
                side=trade.side,
                amount=trade.amount,
                price=trade.price
            )
        else:
            # Market order
            order = exchange.create_market_order(
                symbol=trade.symbol,
                side=trade.side,
                amount=trade.amount
            )
        
        # Record position
        position_id = record_position(
            symbol=trade.symbol,
            side=trade.side,
            amount=trade.amount,
            entry_price=order.get('price', order.get('average', 0)),
            mode='live',
            signal_id=trade.signal_id,
            strategy_id=trade.strategy_id,
            stop_loss_pct=trade.stop_loss_pct,
            take_profit_pct=trade.take_profit_pct,
            order_id=order['id']
        )
        
        return {
            "position_id": position_id,
            "order_id": order['id'],
            "symbol": trade.symbol,
            "side": trade.side,
            "amount": order['amount'],
            "price": order.get('price', order.get('average', 0)),
            "fee": order.get('fee', {}),
            "timestamp": order['timestamp']
        }
    
    except Exception as e:
        logger.error("live_trade_failed", error=str(e))
        raise

def execute_paper_trade(trade: TradeRequest) -> dict:
    """Execute a simulated paper trade"""
    from shared.fee_tiers import get_kraken_fees, get_trading_volume_30d
    
    # Get current market price
    current_price = trade.price if trade.price else get_current_price(trade.symbol)
    
    # Calculate fees based on volume tier
    volume_30d = get_trading_volume_30d(mode=trade.mode)
    fees = get_kraken_fees(volume_30d)
    fee_pct = fees['maker_fee'] if trade.price else fees['taker_fee']  # Limit vs market
    fee_amount = trade.amount * current_price * fee_pct
    
    # Calculate total cost including fees
    if trade.side == 'buy':
        total_cost = (trade.amount * current_price) + fee_amount
        
        # Check if sufficient funds
        available = get_available_capital(trade.mode)
        if total_cost > available:
            raise HTTPException(status_code=400, 
                              detail=f"Insufficient funds. Need {total_cost}, have {available}")
    
    # Record position
    position_id = record_position(
        symbol=trade.symbol,
        side=trade.side,
        amount=trade.amount,
        entry_price=current_price,
        mode='paper',
        signal_id=trade.signal_id,
        strategy_id=trade.strategy_id,
        stop_loss_pct=trade.stop_loss_pct,
        take_profit_pct=trade.take_profit_pct,
        fee_amount=fee_amount,
        position_type=trade.position_type
    )
    
    # Update portfolio capital
    if trade.side == 'buy':
        update_portfolio_capital(trade.mode, -total_cost)
    
    return {
        "position_id": position_id,
        "symbol": trade.symbol,
        "side": trade.side,
        "amount": trade.amount,
        "price": current_price,
        "fee": fee_amount,
        "total_cost": total_cost if trade.side == 'buy' else trade.amount * current_price,
        "timestamp": datetime.utcnow().isoformat()
    }

def get_current_price(symbol: str) -> float:
    """Get current market price for symbol"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT close FROM ohlcv_candles
                WHERE symbol = %s
                ORDER BY timestamp DESC
                LIMIT 1
            """, (symbol,))
            
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"No price data for {symbol}")
            
            return float(row['close'])

def get_available_capital(mode: str) -> float:
    """Get available capital for trading"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT available_capital FROM portfolio_snapshots
                WHERE mode = %s
                ORDER BY timestamp DESC
                LIMIT 1
            """, (mode,))
            
            row = cur.fetchone()
            if not row:
                # No snapshot yet, use starting capital
                return float(settings.paper_starting_capital)
            
            return float(row['available_capital'])

def record_position(symbol: str, side: str, amount: float, entry_price: float,
                   mode: str, signal_id: Optional[int] = None, 
                   strategy_id: Optional[int] = None,
                   stop_loss_pct: Optional[float] = None,
                   take_profit_pct: Optional[float] = None,
                   order_id: Optional[str] = None,
                   fee_amount: float = 0,
                   position_type: str = 'ensemble') -> int:
    """Record a position in the database"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Calculate stop loss and take profit prices
            stop_loss_price = entry_price * (1 - stop_loss_pct / 100) if stop_loss_pct else None
            take_profit_price = entry_price * (1 + take_profit_pct / 100) if take_profit_pct else None
            
            cur.execute("""
                INSERT INTO positions 
                (symbol, strategy_id, mode, status, signal_id,
                 entry_price, entry_time, entry_fee, quantity, capital_allocated,
                 stop_loss_price, take_profit_price,
                 current_price, current_pnl, current_pnl_pct,
                 max_hold_minutes, position_type)
                VALUES (%s, %s, %s, 'open', %s, %s, NOW(), %s, %s, %s, %s, %s, %s, 0, 0, 240, %s)
                RETURNING id
            """, (symbol, strategy_id, mode, signal_id,
                  entry_price, fee_amount, amount, amount * entry_price,
                  stop_loss_price, take_profit_price, entry_price, position_type))
            
            position_id = cur.fetchone()['id']
            logger.info("position_recorded", position_id=position_id, symbol=symbol, position_type=position_type)
            return position_id

def update_portfolio_capital(mode: str, change: float):
    """Update available capital in portfolio"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Get current snapshot
            cur.execute("""
                SELECT * FROM portfolio_snapshots
                WHERE mode = %s
                ORDER BY timestamp DESC
                LIMIT 1
            """, (mode,))
            
            current = cur.fetchone()
            
            if current:
                new_available = float(current['available_capital']) + change
                new_deployed = float(current['deployed_capital']) - change
            else:
                # First trade, create initial snapshot
                new_available = float(settings.paper_starting_capital) + change
                new_deployed = -change
            
            # Count currently open positions
            cur.execute("""
                SELECT COUNT(*) as count FROM positions
                WHERE mode = %s AND status = 'open'
            """, (mode,))
            open_count = cur.fetchone()['count']
            
            # Insert new snapshot with open position count
            cur.execute("""
                INSERT INTO portfolio_snapshots
                (mode, total_capital, deployed_capital, available_capital, open_positions, timestamp)
                VALUES (%s, %s, %s, %s, %s, NOW())
            """, (mode, new_available + new_deployed, new_deployed, new_available, open_count))

def mark_signal_acted(signal_id: int):
    """Mark a signal as acted upon"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE signals SET acted_on = TRUE WHERE id = %s
            """, (signal_id,))

@app.post("/close")
async def close_position(request: ClosePositionRequest):
    """Close an open position"""
    try:
        logger.info("=== CODE VERSION 2026-02-20-17:48 ===", position_id=request.position_id)
        
        # Get position details
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT * FROM positions
                    WHERE id = %s AND mode = %s AND status = 'open'
                """, (request.position_id, request.mode))
                
                position = cur.fetchone()
                
                if not position:
                    raise HTTPException(status_code=404, detail="Position not found or already closed")
        
        position = dict(position)
        logger.info("closing_position", position_id=request.position_id, symbol=position['symbol'], position_keys=list(position.keys()))
        
        if request.mode == "live":
            # Close live position
            result = close_live_position(position)
        else:
            # Close paper position
            result = close_paper_position(position, request.reason)
        
        logger.info("position_closed", result=result)
        
        return {
            "status": "success",
            "position_close": result
        }
    
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error("close_position_error", error=str(e), traceback=traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

def close_live_position(position: dict) -> dict:
    """Close a live position on exchange"""
    try:
        # Get quantity (amount for order)
        quantity = float(position['quantity'])
        entry_price = float(position['entry_price'])
        entry_fee = float(position.get('entry_fee', 0))
        
        # For BUY positions, we SELL to close
        close_side = 'sell'
        
        # Execute market order to close
        order = exchange.create_market_order(
            symbol=position['symbol'],
            side=close_side,
            amount=quantity
        )
        
        exit_price = order.get('price', order.get('average', 0))
        exit_fee = order.get('fee', {}).get('cost', 0)
        
        # Calculate P&L (for BUY positions)
        pnl = (exit_price - entry_price) * quantity - exit_fee - entry_fee
        pnl_pct = (pnl / (entry_price * quantity)) * 100 if (entry_price * quantity) > 0 else 0
        
        # Update position record
        update_position_close(
            position_id=position['id'],
            exit_price=exit_price,
            exit_fee=exit_fee,
            realized_pnl=pnl,
            realized_pnl_pct=pnl_pct,
            trade_result='win' if pnl > 0 else 'loss'
        )
        
        return {
            "position_id": position['id'],
            "order_id": order['id'],
            "exit_price": exit_price,
            "pnl": pnl,
            "pnl_pct": round(pnl_pct, 2)
        }
    
    except Exception as e:
        logger.error("live_close_failed", error=str(e))
        raise

def close_paper_position(position: dict, reason: str) -> dict:
    """Close a paper position"""
    logger.info("close_paper_position_called", position_id=position.get('id'), keys=list(position.keys())[:10])
    
    # Get current market price
    exit_price = get_current_price(position['symbol'])
    
    # Get quantity (amount)
    quantity = float(position['quantity'])
    entry_price = float(position['entry_price'])
    entry_fee = float(position.get('entry_fee', 0))
    
    logger.info("close_paper_values", quantity=quantity, entry_price=entry_price, exit_price=exit_price)
    
    # Calculate exit fee
    exit_fee = quantity * exit_price * 0.0026  # Market order fee
    
    # Calculate P&L (for BUY positions with quantity > 0)
    pnl = (exit_price - entry_price) * quantity - exit_fee - entry_fee
    pnl_pct = (pnl / (entry_price * quantity)) * 100 if (entry_price * quantity) > 0 else 0
    
    # Update position record
    update_position_close(
        position_id=position['id'],
        exit_price=exit_price,
        exit_fee=exit_fee,
        realized_pnl=pnl,
        realized_pnl_pct=pnl_pct,
        trade_result='win' if pnl > 0 else 'loss',
        notes=f"Closed: {reason}"
    )
    
    # Return capital to portfolio
    proceeds = quantity * exit_price - exit_fee
    update_portfolio_capital(position['mode'], proceeds)
    
    return {
        "position_id": position['id'],
        "exit_price": exit_price,
        "pnl": round(pnl, 2),
        "pnl_pct": round(pnl_pct, 2),
        "reason": reason
    }

def update_position_close(position_id: int, exit_price: float, exit_fee: float,
                         realized_pnl: float, realized_pnl_pct: float,
                         trade_result: str, notes: Optional[str] = None):
    """Update position record on close"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE positions
                SET status = 'closed',
                    exit_price = %s,
                    exit_time = NOW(),
                    exit_fee = %s,
                    realized_pnl = %s,
                    realized_pnl_pct = %s,
                    trade_result = %s
                WHERE id = %s
            """, (exit_price, exit_fee, realized_pnl, realized_pnl_pct, 
                  trade_result, position_id))

@app.get("/positions")
def get_positions(
    mode: str = Query("paper", regex="^(paper|live)$"),
    status: Optional[str] = Query(None, regex="^(open|closed|stopped_out)$"),
    limit: int = Query(50, ge=1, le=500)
):
    """Get positions"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                if status:
                    cur.execute("""
                        SELECT * FROM positions
                        WHERE mode = %s AND status = %s
                        ORDER BY entry_time DESC
                        LIMIT %s
                    """, (mode, status, limit))
                else:
                    cur.execute("""
                        SELECT * FROM positions
                        WHERE mode = %s
                        ORDER BY entry_time DESC
                        LIMIT %s
                    """, (mode, limit))
                
                positions = [dict(row) for row in cur.fetchall()]
        
        return {
            "status": "success",
            "count": len(positions),
            "positions": positions
        }
    
    except Exception as e:
        logger.error("positions_fetch_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/stats")
def get_stats(mode: str = Query("paper", regex="^(paper|live)$")):
    """Get trading statistics"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Overall stats
                cur.execute("""
                    SELECT 
                        COUNT(*) as total_trades,
                        COUNT(CASE WHEN status = 'open' THEN 1 END) as open_trades,
                        COUNT(CASE WHEN status = 'closed' THEN 1 END) as closed_trades,
                        COUNT(CASE WHEN trade_result = 'win' THEN 1 END) as wins,
                        COUNT(CASE WHEN trade_result = 'loss' THEN 1 END) as losses,
                        AVG(CASE WHEN status = 'closed' THEN realized_pnl END) as avg_pnl,
                        SUM(CASE WHEN status = 'closed' THEN realized_pnl END) as total_pnl,
                        AVG(CASE WHEN status = 'closed' THEN realized_pnl_pct END) as avg_pnl_pct
                    FROM positions
                    WHERE mode = %s
                """, (mode,))
                
                stats = dict(cur.fetchone())
        
        wins = stats['wins'] or 0
        losses = stats['losses'] or 0
        win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
        
        return {
            "status": "success",
            "mode": mode,
            "total_trades": stats['total_trades'],
            "open_trades": stats['open_trades'],
            "closed_trades": stats['closed_trades'],
            "win_rate": round(win_rate, 2),
            "total_pnl": round(float(stats['total_pnl'] or 0), 2),
            "avg_pnl": round(float(stats['avg_pnl'] or 0), 2),
            "avg_pnl_pct": round(float(stats['avg_pnl_pct'] or 0), 2)
        }
    
    except Exception as e:
        logger.error("stats_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("services.trading_api.main:app", host="0.0.0.0", port=settings.port_trading_api, workers=4)
