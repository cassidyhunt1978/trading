"""OHLCV API - Market Data & Indicators"""
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict
from datetime import datetime, timedelta
import sys
import os
import pandas as pd
import pandas_ta as ta
import psycopg2.extras
import ccxt
import time
import hashlib
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.database import get_connection, save_candle, get_candles, get_active_symbols
from shared.config import get_settings
from shared.logging_config import setup_logging

settings = get_settings()
logger = setup_logging('ohlcv_api', settings.log_level)

# Simple TTL cache for candle data (30 second TTL)
_candle_cache = {}
CACHE_TTL = 30

def get_cache_key(symbol: str, limit: int, days_back: int, start_date: Optional[str], end_date: Optional[str]) -> str:
    """Generate cache key for candle request"""
    key_data = f"{symbol}:{limit}:{days_back}:{start_date}:{end_date}"
    return hashlib.md5(key_data.encode()).hexdigest()

def get_cached_candles(cache_key: str) -> Optional[List[Dict]]:
    """Get cached candles if still valid"""
    if cache_key in _candle_cache:
        cached_data, timestamp = _candle_cache[cache_key]
        if time.time() - timestamp < CACHE_TTL:
            return cached_data
        else:
            del _candle_cache[cache_key]
    return None

def cache_candles(cache_key: str, candles: List[Dict]):
    """Cache candles with current timestamp"""
    _candle_cache[cache_key] = (candles, time.time())
    # Simple cleanup: remove oldest entries if cache grows too large
    if len(_candle_cache) > 100:
        oldest_key = min(_candle_cache.keys(), key=lambda k: _candle_cache[k][1])
        del _candle_cache[oldest_key]

app = FastAPI(title="OHLCV API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Coinbase exchange (better free tier than Kraken)
exchange = ccxt.coinbase({
    'enableRateLimit': True,
})

class CandleResponse(BaseModel):
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    indicators: Optional[Dict] = None

class SymbolAdd(BaseModel):
    symbol: str
    name: Optional[str] = None
    exchange: str = 'coinbase'

@app.get("/")
def root():
    return {"service": "OHLCV API", "status": "running", "version": "1.0.0"}

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.get("/candles")  # Removed response_model for better performance
def get_candles_endpoint(
    symbol: str = Query(..., description="Trading symbol (e.g., BTC, ETH)"),
    limit: int = Query(100, ge=1, le=10000, description="Number of candles to fetch"),
    days_back: int = Query(7, ge=1, le=365, description="Days of history"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    include_indicators: bool = Query(True, description="Include indicator data")
):
    """Get historical candles for a symbol"""
    try:
        # Check cache first (include include_indicators in cache key)
        cache_key = get_cache_key(symbol, limit, days_back, start_date, end_date) + f":{include_indicators}"
        cached_candles = get_cached_candles(cache_key)
        if cached_candles is not None:
            logger.info("candles_from_cache", symbol=symbol, count=len(cached_candles))
            return cached_candles
        
        # Use explicit date range if provided, otherwise use days_back
        if start_date and end_date:
            start_dt = datetime.fromisoformat(start_date)
            end_dt = datetime.fromisoformat(end_date)
            # For date range queries, fetch ALL candles in range (no limit)
            effective_limit = None
            logger.info("candles_requested_with_dates", symbol=symbol, start_date=start_date, end_date=end_date, limit="unlimited")
        else:
            end_dt = datetime.now()
            start_dt = end_dt - timedelta(days=days_back)
            effective_limit = limit
            logger.info("candles_requested_with_days_back", symbol=symbol, days_back=days_back, limit=limit)
        
        candles = get_candles(symbol, start_dt, end_dt, effective_limit)
        
        # Optionally strip indicators for faster response
        if not include_indicators:
            for candle in candles:
                candle['indicators'] = None
        
        if not candles:
            logger.warning("no_candles_found", symbol=symbol)
            return []
        
        # Cache the results
        cache_candles(cache_key, candles)
        
        logger.info("candles_fetched", symbol=symbol, count=len(candles))
        return candles
    
    except Exception as e:
        logger.error("fetch_candles_error", symbol=symbol, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/candles/bulk")
def get_candles_bulk(
    symbol: str = Query(..., description="Trading symbol (e.g., BTC, ETH)"),
    limit: Optional[int] = Query(None, ge=0, description="Max candles to return. Omit or set to 0 for ALL candles in range."),
    days_back: int = Query(30, ge=1, description="Days of history when no start/end date is given (no upper bound)"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    include_indicators: bool = Query(False, description="Include indicator data (can be slow for large datasets)")
):
    """Get candles with no hard upper limit.

    - Omit ``limit`` or pass ``limit=0`` to return **all** candles in the requested range.
    - Use ``start_date`` + ``end_date`` for a precise date window.
    - Use ``days_back`` (no maximum) for a rolling window from now.
    - ``include_indicators`` defaults to False to keep large responses fast.
    """
    try:
        # Treat limit=0 as "all" (None)
        effective_limit = None if (limit is None or limit == 0) else limit

        if start_date and end_date:
            start_dt = datetime.fromisoformat(start_date)
            end_dt = datetime.fromisoformat(end_date)
        else:
            end_dt = datetime.now()
            start_dt = end_dt - timedelta(days=days_back)

        logger.info(
            "bulk_candles_requested",
            symbol=symbol,
            start=start_dt.isoformat(),
            end=end_dt.isoformat(),
            limit=effective_limit if effective_limit else "all",
        )

        candles = get_candles(symbol, start_dt, end_dt, effective_limit)

        if not include_indicators:
            for candle in candles:
                candle["indicators"] = None

        logger.info("bulk_candles_fetched", symbol=symbol, count=len(candles))

        return {
            "symbol": symbol,
            "count": len(candles),
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "limit_applied": effective_limit,
            "candles": candles,
        }

    except Exception as e:
        logger.error("bulk_candles_error", symbol=symbol, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/candles/fetch")
async def fetch_candles_from_exchange(
    symbol: str = Query(..., description="Trading symbol"),
    timeframe: str = Query("1m", description="Timeframe (1m, 5m, 1h, etc.)"),
    limit: int = Query(100, ge=1, le=1000),
    fetch_latest: bool = Query(True, description="If True, fetch latest candles; if False, backfill historical")
):
    """Fetch fresh candles from Coinbase exchange"""
    try:
        # Convert symbol format (BTC -> BTC-USD for Coinbase)
        coinbase_symbol = f"{symbol}-USD"
        
        since_ms = None
        
        if not fetch_latest:
            # BACKFILL MODE: Check if we have existing candles - if so, fetch BEFORE the earliest one
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT MIN(timestamp) as earliest FROM ohlcv_candles WHERE symbol = %s",                        (symbol,)
                    )
                    result = cur.fetchone()
                    if result and result['earliest']:
                        # Fetch candles BEFORE our earliest timestamp
                        earliest_ts = result['earliest']
                        since_ms = int((earliest_ts.timestamp() - (limit * 60)) * 1000)
                        logger.info("fetching_historical", 
                                  symbol=coinbase_symbol, 
                                  timeframe=timeframe,
                                  since=earliest_ts)
                    else:
                        # NO EXISTING CANDLES: Start from 180 days ago
                        days_ago_180 = datetime.now() - timedelta(days=180)
                        since_ms = int(days_ago_180.timestamp() * 1000)
                        logger.info("fetching_from_scratch",
                                  symbol=coinbase_symbol,
                                  start_date=days_ago_180.isoformat())
        else:
            # LATEST MODE: Fetch most recent candles
            logger.info("fetching_latest", 
                      symbol=coinbase_symbol, 
                      timeframe=timeframe)
        
        # Fetch OHLCV data
        if since_ms:
            ohlcv = exchange.fetch_ohlcv(coinbase_symbol, timeframe, since=since_ms, limit=limit)
        else:
            ohlcv = exchange.fetch_ohlcv(coinbase_symbol, timeframe, limit=limit)
        
        candles_saved = 0
        candles_duplicate = 0
        
        for candle in ohlcv:
            timestamp = datetime.fromtimestamp(candle[0] / 1000)
            open_price = float(candle[1])
            high = float(candle[2])
            low = float(candle[3])
            close = float(candle[4])
            volume = float(candle[5])
            
            # Save to database (will skip duplicates due to unique constraint)
            try:
                save_candle(symbol, timestamp, open_price, high, low, close, volume, timeframe)
                candles_saved += 1
            except Exception as e:
                # Likely a duplicate - that's okay
                candles_duplicate += 1
        
        logger.info("candles_saved", 
                   symbol=symbol, 
                   count=candles_saved,
                   duplicates=candles_duplicate)
        
        # Update last_candle_at timestamp on successful fetch
        if candles_saved > 0:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE symbols 
                        SET last_candle_at = NOW()
                        WHERE symbol = %s
                    """, (symbol,))
                    conn.commit()
            logger.info("last_candle_updated", symbol=symbol)
        
        return {
            "status": "success",
            "symbol": symbol,
            "candles_fetched": candles_saved,
            "candles_duplicate": candles_duplicate,
            "timeframe": timeframe
        }
    
    except ccxt.NetworkError as e:
        logger.error("network_error", symbol=symbol, error=str(e))
        raise HTTPException(status_code=503, detail=f"Exchange connection error: {str(e)}")
    except ccxt.ExchangeError as e:
        # Exchange errors often mean symbol not available (like MATIC on Coinbase)
        logger.error("exchange_error", symbol=symbol, error=str(e))
        raise HTTPException(status_code=400, detail=f"Exchange error: {str(e)}")
    except Exception as e:
        logger.error("fetch_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/indicators/compute")
async def compute_indicators(
    symbol: str = Query(...),
    indicator: str = Query(..., description="Indicator name (RSI, MACD, BBANDS, etc.)")
):
    """Compute technical indicators for stored candles"""
    try:
        # Fetch recent candles
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)
        candles = get_candles(symbol, start_date, end_date, limit=500)
        
        if len(candles) < 20:
            raise HTTPException(status_code=400, detail="Not enough data for indicators")
        
        # Convert to DataFrame - exclude 'indicators' column to avoid dict values
        df = pd.DataFrame(candles)
        # Keep only OHLCV columns for indicator computation
        df = df[['symbol', 'timestamp', 'open', 'high', 'low', 'close', 'volume']]
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        # Ensure OHLCV columns are float64 (not Decimal or object)
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)
        df = df.sort_values('timestamp')
        
        # Drop duplicate timestamps (keep the most recent record)
        df = df.drop_duplicates(subset=['timestamp'], keep='last')
        
        # Set timestamp as index for indicators that need it (like VWAP)
        df_indexed = df.set_index('timestamp')
        
        # Compute indicator
        computed = None
        if indicator.upper() == 'RSI':
            df_indexed.ta.rsi(length=14, append=True)
            computed = 'RSI_14'
        elif indicator.upper() == 'MACD':
            df_indexed.ta.macd(append=True)
            computed = 'MACD_12_26_9'
        elif indicator.upper() == 'BBANDS':
            df_indexed.ta.bbands(length=20, append=True)
            computed = 'BBANDS'
        elif indicator.upper() == 'SMA':
            df_indexed.ta.sma(length=20, append=True)
            df_indexed.ta.sma(length=50, append=True)
            computed = 'SMA'
        elif indicator.upper() == 'EMA':
            # Core EMA periods for charts strategy evaluation
            df_indexed.ta.ema(length=9,   append=True)  # fast EMA (ema_cross_up)
            df_indexed.ta.ema(length=12,  append=True)
            df_indexed.ta.ema(length=21,  append=True)  # slow EMA (ema_cross_up)
            df_indexed.ta.ema(length=26,  append=True)
            df_indexed.ta.ema(length=50,  append=True)  # ema_above_slow reference
            df_indexed.ta.ema(length=200, append=True)  # long-term trend filter
            computed = 'EMA'
        elif indicator.upper() == 'VWAP':
            df_indexed.ta.vwap(append=True)
            computed = 'VWAP'
        elif indicator.upper() == 'ADX':
            # ADX — needed for adx_trending / adx_above charts conditions
            df_indexed.ta.adx(length=14, append=True)
            computed = 'ADX'
        elif indicator.upper() == 'ATR':
            # ATR — needed for atr_breakout charts condition
            df_indexed.ta.atr(length=14, append=True)
            computed = 'ATR'
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported indicator: {indicator}")
        
        # Reset index to get timestamp back as column
        df = df_indexed.reset_index()
        
        # Update database with computed indicators (merge with existing indicators)
        with get_connection() as conn:
            with conn.cursor() as cur:
                for _, row in df.iterrows():
                    new_indicators = {}
                    for col in df.columns:
                        if col not in ['id', 'symbol', 'timestamp', 'open', 'high', 'low', 'close', 'volume', 'created_at']:
                            if pd.notna(row[col]):
                                new_indicators[col] = float(row[col])
                    
                    if new_indicators:
                        # Merge with existing indicators instead of overwriting
                        cur.execute("""
                            UPDATE ohlcv_candles 
                            SET indicators = COALESCE(indicators, '{}'::jsonb) || %s::jsonb
                            WHERE symbol = %s AND timestamp = %s
                        """, (psycopg2.extras.Json(new_indicators), symbol, row['timestamp']))
        
        logger.info("indicators_computed", symbol=symbol, indicator=indicator)
        
        return {
            "status": "success",
            "symbol": symbol,
            "indicator": indicator,
            "candles_updated": len(df)
        }
    
    except Exception as e:
        logger.error("compute_indicators_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/symbols")
def get_symbols():
    """Get all active trading symbols"""
    try:
        symbols = get_active_symbols()
        return {
            "status": "success",
            "count": len(symbols),
            "symbols": symbols
        }
    except Exception as e:
        logger.error("get_symbols_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/symbols/add")
def add_symbol(symbol_data: SymbolAdd):
    """Add a new trading symbol"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO symbols (symbol, name, exchange, status)
                    VALUES (%s, %s, %s, 'active')
                    ON CONFLICT (symbol) DO UPDATE
                    SET name = EXCLUDED.name, exchange = EXCLUDED.exchange, status = 'active'
                    RETURNING id
                """, (symbol_data.symbol, symbol_data.name, symbol_data.exchange))
                
                result = cur.fetchone()
                
        logger.info("symbol_added", symbol=symbol_data.symbol)
        
        return {
            "status": "success",
            "symbol": symbol_data.symbol,
            "id": result['id']
        }
    
    except Exception as e:
        logger.error("add_symbol_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/symbols/{symbol}")
def delete_symbol(symbol: str):
    """Deactivate a trading symbol"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE symbols
                    SET status = 'inactive'
                    WHERE symbol = %s
                    RETURNING id
                """, (symbol,))
                
                result = cur.fetchone()
                if not result:
                    raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")
                
        logger.info("symbol_deactivated", symbol=symbol)
        
        return {
            "status": "success",
            "symbol": symbol,
            "message": "Symbol deactivated"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error("delete_symbol_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/symbols/{symbol}/toggle")
def toggle_symbol(symbol: str):
    """Toggle symbol between active and inactive"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE symbols
                    SET status = CASE 
                        WHEN status = 'active' THEN 'inactive'
                        ELSE 'active'
                    END
                    WHERE symbol = %s
                    RETURNING status
                """, (symbol,))
                
                result = cur.fetchone()
                if not result:
                    raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")
                
        logger.info("symbol_toggled", symbol=symbol, new_status=result['status'])
        
        return {
            "status": "success",
            "symbol": symbol,
            "new_status": result['status']
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error("toggle_symbol_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/stats")
def get_stats():
    """Get OHLCV database statistics"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) as count FROM ohlcv_candles")
                candle_count = cur.fetchone()['count']
                
                cur.execute("SELECT COUNT(DISTINCT symbol) as count FROM ohlcv_candles")
                symbol_count = cur.fetchone()['count']
                
                cur.execute("""
                    SELECT symbol, MAX(timestamp) as latest
                    FROM ohlcv_candles
                    GROUP BY symbol
                    ORDER BY symbol
                """)
                latest_candles = cur.fetchall()
        
        return {
            "status": "success",
            "total_candles": candle_count,
            "symbols_with_data": symbol_count,
            "latest_candles": latest_candles
        }
    
    except Exception as e:
        logger.error("stats_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

# =============================================================================
# VISION PHASE 8: Add symbol with auto 180-day backfill trigger
# =============================================================================

class SymbolAddWithBackfill(BaseModel):
    symbol: str
    name: Optional[str] = None
    exchange: str = 'coinbase'
    backfill_days: int = 180


@app.post("/symbols/add-with-backfill")
async def add_symbol_with_backfill(symbol_data: SymbolAddWithBackfill):
    """
    Add a new symbol AND immediately trigger a 180-day backfill in the background.
    Returns immediately; backfill proceeds via Celery (if available) or inline batch.
    """
    try:
        import time as _time

        coinbase_symbol = f"{symbol_data.symbol}-USD"

        # 1. Verify symbol exists on exchange
        try:
            markets = exchange.load_markets()
            if coinbase_symbol not in markets:
                raise HTTPException(
                    status_code=400,
                    detail=f"{coinbase_symbol} not found on Coinbase. Check symbol name.",
                )
        except ccxt.ExchangeError as e:
            raise HTTPException(status_code=400, detail=f"Exchange error: {str(e)}")

        # 2. Add to symbols table
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO symbols (symbol, name, exchange, status)
                    VALUES (%s, %s, %s, 'active')
                    ON CONFLICT (symbol) DO UPDATE
                        SET status = 'active',
                            name   = COALESCE(EXCLUDED.name, symbols.name),
                            exchange = EXCLUDED.exchange
                    RETURNING id
                    """,
                    (symbol_data.symbol, symbol_data.name or symbol_data.symbol, symbol_data.exchange),
                )
                row = cur.fetchone()
                symbol_id = row["id"]

        logger.info("symbol_added_for_backfill", symbol=symbol_data.symbol, id=symbol_id)

        # 3. Trigger backfill — try Celery first, fall back to synchronous mini-batch
        backfill_status = "queued"
        try:
            import requests as _req
            # Kick off via Celery by posting to its trigger endpoint if available
            from shared.config import get_settings as _gs
            _s = _gs()
            _req.post(
                f"http://{_s.service_host}:{_s.port_ohlcv_api}/symbols/trigger-backfill",
                json={"symbol": symbol_data.symbol, "days": symbol_data.backfill_days},
                timeout=2,
            )
        except Exception:
            pass  # Will fall back to inline mini-batch below

        # 4. Sync mini-batch: fetch first 500 candles now so symbol isn't empty
        try:
            since_dt = datetime.now() - timedelta(days=symbol_data.backfill_days)
            since_ms = int(since_dt.timestamp() * 1000)
            ohlcv = exchange.fetch_ohlcv(coinbase_symbol, "1m", since=since_ms, limit=500)
            saved = 0
            for candle in ohlcv:
                ts = datetime.fromtimestamp(candle[0] / 1000)
                try:
                    save_candle(
                        symbol_data.symbol, ts,
                        float(candle[1]), float(candle[2]),
                        float(candle[3]), float(candle[4]),
                        float(candle[5]), "1m",
                    )
                    saved += 1
                except Exception:
                    pass
            logger.info("initial_backfill_batch", symbol=symbol_data.symbol, saved=saved)
            if saved > 0:
                backfill_status = f"started ({saved} candles loaded, full backfill via Celery)"
        except Exception as e:
            logger.warning("initial_backfill_failed", symbol=symbol_data.symbol, error=str(e))
            backfill_status = "symbol added, backfill will retry via Celery"

        return {
            "status": "success",
            "symbol": symbol_data.symbol,
            "symbol_id": symbol_id,
            "backfill_status": backfill_status,
            "message": f"Symbol {symbol_data.symbol} added. 180-day backfill in progress.",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("add_symbol_backfill_error", symbol=symbol_data.symbol, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/timescale-views/status")
def timescale_views_status():
    """Check status of TimescaleDB continuous aggregate views"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT view_name, materialization_hypertable_schema,
                           refresh_lag, refresh_interval
                    FROM timescaledb_information.continuous_aggregates
                    ORDER BY view_name
                    """
                )
                views = [dict(r) for r in cur.fetchall()]
        return {"status": "success", "views": views, "count": len(views)}
    except Exception as e:
        return {"status": "error", "error": str(e), "views": []}


if __name__ == "__main__":
    import uvicorn
    import psycopg2.extras
    # Run with 4 workers so candle fetching doesn't block health checks
    uvicorn.run("services.ohlcv_api.main:app", host="0.0.0.0", port=settings.port_ohlcv_api, workers=4)
