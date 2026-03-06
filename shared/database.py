"""Database connection and utilities"""
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
import os
from typing import Optional, Dict, List, Any
from datetime import datetime

DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://postgres:postgres@127.0.0.1:5432/trading_system')

# Connection pool - one per process
_connection_pools = {}

def get_pool():
    """Get or create connection pool for current process"""
    import os
    pid = os.getpid()
    
    if pid not in _connection_pools:
        _connection_pools[pid] = pool.ThreadedConnectionPool(
            1,  # minconn
            5,  # maxconn (reduced: 13 services × 4 workers × 5 = 260 max connections)
            DATABASE_URL
        )
    
    return _connection_pools[pid]

@contextmanager
def get_connection():
    """Context manager for database connections from pool.
    
    Handles stale/closed connections by discarding them and retrying,
    which prevents 'connection already closed' errors after idle periods.
    """
    conn_pool = get_pool()
    conn = None

    # Attempt up to 3 times to obtain a live connection
    for attempt in range(3):
        candidate = conn_pool.getconn()

        # If the connection object is flagged as closed, discard it
        if candidate.closed:
            try:
                conn_pool.putconn(candidate, close=True)
            except Exception:
                pass
            continue

        # Ping the server to confirm the connection is truly alive
        try:
            candidate.cursor().execute('SELECT 1')
            conn = candidate
            break
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            try:
                conn_pool.putconn(candidate, close=True)
            except Exception:
                pass

    if conn is None:
        raise psycopg2.OperationalError(
            "Could not obtain a live database connection after 3 attempts"
        )

    # Set cursor factory for dict-like results
    conn.cursor_factory = RealDictCursor

    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        # Return connection to pool instead of closing
        try:
            conn_pool.putconn(conn)
        except Exception:
            # If putconn fails, just close the connection
            try:
                conn.close()
            except Exception:
                pass

def get_latest_candle(symbol: str) -> Optional[Dict]:
    """Get most recent candle for symbol"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM ohlcv_candles
                WHERE symbol = %s
                ORDER BY timestamp DESC
                LIMIT 1
            """, (symbol,))
            return dict(cur.fetchone()) if cur.rowcount > 0 else None

def get_candles(symbol: str, start_date: datetime, end_date: datetime, limit: int = None) -> List[Dict]:
    """Get OHLCV candles for a symbol in date range"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Optimized query using index and DESC order for recent data
            if limit:
                cur.execute("""
                    SELECT id, symbol, timestamp, open, high, low, close, volume, indicators
                    FROM ohlcv_candles
                    WHERE symbol = %s 
                    AND timestamp >= %s 
                    AND timestamp <= %s
                    ORDER BY timestamp DESC
                    LIMIT %s
                """, (symbol, start_date, end_date, limit))
            else:
                # No limit - fetch all candles in range
                cur.execute("""
                    SELECT id, symbol, timestamp, open, high, low, close, volume, indicators
                    FROM ohlcv_candles
                    WHERE symbol = %s 
                    AND timestamp >= %s 
                    AND timestamp <= %s
                    ORDER BY timestamp DESC
                """, (symbol, start_date, end_date))
            results = [dict(row) for row in cur.fetchall()]
            # Return in ascending order as expected
            return list(reversed(results))

def get_active_symbols() -> List[Dict]:
    """Get list of active symbols"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM symbols
                WHERE status = 'active'
                ORDER BY symbol
            """)
            return [dict(row) for row in cur.fetchall()]

def save_candle(symbol: str, timestamp: datetime, open_price: float, high: float, 
                low: float, close: float, volume: float, timeframe: str = '1m', indicators: Dict = None):
    """Save or update a candle"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO ohlcv_candles (symbol, timeframe, timestamp, open, high, low, close, volume, indicators)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (symbol, timeframe, timestamp) 
                DO UPDATE SET 
                    open = EXCLUDED.open,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    close = EXCLUDED.close,
                    volume = EXCLUDED.volume,
                    indicators = EXCLUDED.indicators
            """, (symbol, timeframe, timestamp, open_price, high, low, close, volume, 
                  psycopg2.extras.Json(indicators) if indicators else None))

def get_portfolio_state(mode: str = 'paper') -> Optional[Dict]:
    """Get latest portfolio snapshot"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM portfolio_snapshots
                WHERE mode = %s
                ORDER BY timestamp DESC
                LIMIT 1
            """, (mode,))
            return dict(cur.fetchone()) if cur.rowcount > 0 else None

def get_open_positions(mode: str = 'paper') -> List[Dict]:
    """Get all open positions"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM positions
                WHERE mode = %s AND status = 'open'
                ORDER BY entry_time DESC
            """, (mode,))
            return [dict(row) for row in cur.fetchall()]

def get_active_strategies() -> List[Dict]:
    """Get all enabled strategies"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM strategies
                WHERE enabled = true
                ORDER BY created_at DESC
            """)
            return [dict(row) for row in cur.fetchall()]
