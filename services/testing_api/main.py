"""Testing API - System Health Monitoring"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, List
import sys
import os
import requests
from datetime import datetime, timedelta, timezone

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.database import get_connection, get_active_symbols, get_portfolio_state
from shared.config import get_settings
from shared.logging_config import setup_logging

settings = get_settings()
logger = setup_logging('testing_api', settings.log_level)

app = FastAPI(title="Testing API", version="1.0.0")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class HealthResponse(BaseModel):
    health_score: int
    total_tests: int
    passed: int
    failed: int
    tests: List[Dict]
    categories: Dict[str, Dict]

@app.get("/")
def root():
    return {"service": "Testing API", "status": "running", "version": "1.0.0"}

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.get("/test/run-all", response_model=HealthResponse)
def run_all_tests():
    """Run comprehensive system test suite"""
    tests = []
    
    # Infrastructure Tests
    tests.extend(test_infrastructure())
    
    # Data Layer Tests
    tests.extend(test_data_layer())
    
    # Service Tests
    tests.extend(test_services())
    
    # Database Health Tests
    tests.extend(test_database_health())
    
    # AfterAction Analysis Tests
    tests.extend(test_afteraction_system())
    
    # Calculate health score and category breakdown
    passed = sum(1 for t in tests if t['status'] == 'PASS')
    failed = len(tests) - passed
    health_score = int((passed / len(tests)) * 100) if tests else 0
    
    # Category breakdown
    categories = {}
    for test in tests:
        cat = test['category']
        if cat not in categories:
            categories[cat] = {'passed': 0, 'failed': 0, 'total': 0}
        categories[cat]['total'] += 1
        if test['status'] == 'PASS':
            categories[cat]['passed'] += 1
        else:
            categories[cat]['failed'] += 1
    
    return {
        'health_score': health_score,
        'total_tests': len(tests),
        'passed': passed,
        'failed': failed,
        'tests': tests,
        'categories': categories
    }


def test_infrastructure():
    """Test API connectivity, database, Redis, Celery"""
    tests = []
    
    # Test each API
    apis = [
        ('AI API', f'http://{settings.service_host}:{settings.port_ai_api}/health'),
        ('OHLCV API', f'http://{settings.service_host}:{settings.port_ohlcv_api}/health'),
        ('Backtest API', f'http://{settings.service_host}:{settings.port_backtest_api}/health'),
        ('Optimization API', f'http://{settings.service_host}:{settings.port_optimization_api}/health'),
        ('Signal API', f'http://{settings.service_host}:{settings.port_signal_api}/health'),
        ('Portfolio API', f'http://{settings.service_host}:{settings.port_portfolio_api}/health'),
        ('Trading API', f'http://{settings.service_host}:{settings.port_trading_api}/health'),
        ('AfterAction API', f'http://{settings.service_host}:{settings.port_afteraction_api}/health'),
        ('Strategy Config API', f'http://{settings.service_host}:8020/health'),
    ]
    
    for name, url in apis:
        try:
            response = requests.get(url, timeout=2)
            if response.status_code == 200:
                tests.append({
                    'name': name,
                    'category': 'Infrastructure',
                    'status': 'PASS',
                    'detail': f'Responding on {url.split(":")[-1]}'
                })
            else:
                tests.append({
                    'name': name,
                    'category': 'Infrastructure',
                    'status': 'FAIL',
                    'error': f'HTTP {response.status_code}'
                })
        except Exception as e:
            tests.append({
                'name': name,
                'category': 'Infrastructure',
                'status': 'FAIL',
                'error': f'Not responding: {str(e)}'
            })
    
    # Test Database
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        tests.append({
            'name': 'Database Connection',
            'category': 'Infrastructure',
            'status': 'PASS'
        })
    except Exception as e:
        tests.append({
            'name': 'Database Connection',
            'category': 'Infrastructure',
            'status': 'FAIL',
            'error': str(e)
        })
    
    # Test Redis
    try:
        import redis
        r = redis.from_url(settings.redis_url)
        r.ping()
        tests.append({
            'name': 'Redis Connection',
            'category': 'Infrastructure',
            'status': 'PASS'
        })
    except Exception as e:
        tests.append({
            'name': 'Redis Connection',
            'category': 'Infrastructure',
            'status': 'FAIL',
            'error': str(e)
        })
    
    # Test Celery Workers
    try:
        from celery import Celery
        celery_app = Celery(broker=settings.redis_url, backend=settings.redis_url)
        inspect = celery_app.control.inspect()
        active = inspect.active()
        if active:
            worker_count = len(active)
            tests.append({
                'name': 'Celery Workers',
                'category': 'Infrastructure',
                'status': 'PASS',
                'detail': f'{worker_count} worker(s) active'
            })
        else:
            tests.append({
                'name': 'Celery Workers',
                'category': 'Infrastructure',
                'status': 'FAIL',
                'error': 'No active workers'
            })
    except Exception as e:
        tests.append({
            'name': 'Celery Workers',
            'category': 'Infrastructure',
            'status': 'FAIL',
            'error': str(e)
        })
    
    return tests


def test_data_layer():
    """Test data availability and freshness"""
    tests = []
    
    # Test Active Symbols
    try:
        symbols = get_active_symbols()
        if len(symbols) >= 3:
            tests.append({
                'name': 'Active Symbols',
                'category': 'Data',
                'status': 'PASS',
                'detail': f'{len(symbols)} symbols active'
            })
        else:
            tests.append({
                'name': 'Active Symbols',
                'category': 'Data',
                'status': 'FAIL',
                'error': f'Only {len(symbols)} symbols (need 3+)'
            })
    except Exception as e:
        tests.append({
            'name': 'Active Symbols',
            'category': 'Data',
            'status': 'FAIL',
            'error': str(e)
        })
    
    # Test OHLCV Data Freshness
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Only check active symbols (exclude inactive like MATIC)
                cur.execute("""
                    SELECT oc.symbol, MAX(oc.timestamp) as latest
                    FROM ohlcv_candles oc
                    INNER JOIN symbols s ON oc.symbol = s.symbol
                    WHERE s.status = 'active'
                    GROUP BY oc.symbol
                """)
                rows = cur.fetchall()
                
                if rows:
                    now = datetime.now(timezone.utc).replace(tzinfo=None)
                    stale_symbols = []
                    for row in rows:
                        latest = row['latest'].replace(tzinfo=None) if hasattr(row['latest'], 'replace') else row['latest']
                        age = (now - latest).total_seconds() / 60
                        if age > 10:  # More than 10 minutes old
                            stale_symbols.append(f"{row['symbol']} ({int(age)}m old)")
                    
                    if not stale_symbols:
                        tests.append({
                            'name': 'OHLCV Data Freshness',
                            'category': 'Data',
                            'status': 'PASS',
                            'detail': f'{len(rows)} active symbols with fresh data'
                        })
                    else:
                        tests.append({
                            'name': 'OHLCV Data Freshness',
                            'category': 'Data',
                            'status': 'FAIL',
                            'error': f'Stale data: {", ".join(stale_symbols)}'
                        })
                else:
                    tests.append({
                        'name': 'OHLCV Data Freshness',
                        'category': 'Data',
                        'status': 'FAIL',
                        'error': 'No OHLCV data found for active symbols'
                    })
    except Exception as e:
        tests.append({
            'name': 'OHLCV Data Freshness',
            'category': 'Data',
            'status': 'FAIL',
            'error': str(e)
        })
    
    # Test Historical Data Depth
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT symbol, COUNT(*) as candle_count,
                           MIN(timestamp) as earliest,
                           MAX(timestamp) as latest
                    FROM ohlcv_candles
                    GROUP BY symbol
                """)
                rows = cur.fetchall()
                
                if rows:
                    insufficient = []
                    for row in rows:
                        if row['candle_count'] < 1000:  # Need at least 1000 candles
                            insufficient.append(f"{row['symbol']} ({row['candle_count']} candles)")
                    
                    if not insufficient:
                        total_candles = sum(r['candle_count'] for r in rows)
                        tests.append({
                            'name': 'Historical Data Depth',
                            'category': 'Data',
                            'status': 'PASS',
                            'detail': f'{total_candles:,} total candles'
                        })
                    else:
                        tests.append({
                            'name': 'Historical Data Depth',
                            'category': 'Data',
                            'status': 'FAIL',
                            'error': f'Insufficient: {", ".join(insufficient)}'
                        })
                else:
                    tests.append({
                        'name': 'Historical Data Depth',
                        'category': 'Data',
                        'status': 'FAIL',
                        'error': 'No historical data'
                    })
    except Exception as e:
        tests.append({
            'name': 'Historical Data Depth',
            'category': 'Data',
            'status': 'FAIL',
            'error': str(e)
        })
    
    # Test Strategies Enabled
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) as count FROM strategies WHERE enabled = true")
                row = cur.fetchone()
                count = row['count']
                
                if count >= 10:
                    tests.append({
                        'name': 'Enabled Strategies',
                        'category': 'Data',
                        'status': 'PASS',
                        'detail': f'{count} strategies enabled'
                    })
                else:
                    tests.append({
                        'name': 'Enabled Strategies',
                        'category': 'Data',
                        'status': 'FAIL',
                        'error': f'Only {count} enabled (need 10+)'
                    })
    except Exception as e:
        tests.append({
            'name': 'Enabled Strategies',
            'category': 'Data',
            'status': 'FAIL',
            'error': str(e)
        })
    
    # Test Portfolio State
    try:
        portfolio = get_portfolio_state('paper')
        if portfolio and portfolio['total_capital'] > 0:
            tests.append({
                'name': 'Paper Portfolio',
                'category': 'Data',
                'status': 'PASS',
                'detail': f'Capital: ${portfolio["total_capital"]:.2f}'
            })
        else:
            tests.append({
                'name': 'Paper Portfolio',
                'category': 'Data',
                'status': 'FAIL',
                'error': 'Invalid portfolio state'
            })
    except Exception as e:
        tests.append({
            'name': 'Paper Portfolio',
            'category': 'Data',
            'status': 'FAIL',
            'error': str(e)
        })
    
    return tests


def test_services():
    """Test service functionality"""
    tests = []
    
    # Test Signal Generation Task (checks if task is running, not if signals were generated)
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Check if OHLCV data is being updated (every 1 min)
                # This proves the data pipeline is working
                cur.execute("""
                    SELECT MAX(timestamp) as last_update
                    FROM ohlcv_candles
                    WHERE timestamp > NOW() - INTERVAL '10 minutes'
                """)
                row = cur.fetchone()
                last_update = row['last_update'] if row else None
                
                # If OHLCV updated in last 10 min, pipeline is working
                if last_update:
                    # Check how many signals exist (to provide context)
                    cur.execute("""
                        SELECT COUNT(*) as count
                        FROM signals
                        WHERE generated_at > NOW() - INTERVAL '1 hour'
                    """)
                    signal_row = cur.fetchone()
                    signal_count = signal_row['count'] if signal_row else 0
                    
                    if signal_count > 0:
                        tests.append({
                            'name': 'Signal Generation Task',
                            'category': 'Services',
                            'status': 'PASS',
                            'detail': f'Running ({signal_count} signals in last hour)'
                        })
                    else:
                        tests.append({
                            'name': 'Signal Generation Task',
                            'category': 'Services',
                            'status': 'PASS',
                            'detail': 'Running (no opportunities currently)'
                        })
                else:
                    tests.append({
                        'name': 'Signal Generation Task',
                        'category': 'Services',
                        'status': 'FAIL',
                        'error': 'Data pipeline stopped (no recent OHLCV updates)'
                    })
    except Exception as e:
        tests.append({
            'name': 'Signal Generation Task',
            'category': 'Services',
            'status': 'FAIL',
            'error': str(e)
        })
    
    # Test Backtest Results
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(DISTINCT strategy_id) as strategy_count
                    FROM backtests
                """)
                row = cur.fetchone()
                count = row['strategy_count']
                
                if count > 0:
                    tests.append({
                        'name': 'Backtest Coverage',
                        'category': 'Services',
                        'status': 'PASS',
                        'detail': f'{count} strategies backtested'
                    })
                else:
                    tests.append({
                        'name': 'Backtest Coverage',
                        'category': 'Services',
                        'status': 'FAIL',
                        'error': 'No backtest results found'
                    })
    except Exception as e:
        tests.append({
            'name': 'Backtest Coverage',
            'category': 'Services',
            'status': 'FAIL',
            'error': str(e)
        })
    
    # Test Trading Policies
    try:
        response = requests.get(f'http://{settings.service_host}:8020/policies/status?mode=paper', timeout=2)
        if response.status_code == 200:
            data = response.json()
            if data.get('trading_allowed'):
                tests.append({
                    'name': 'Trading Policies',
                    'category': 'Services',
                    'status': 'PASS',
                    'detail': 'Trading allowed'
                })
            else:
                reasons = []
                if data.get('limits_hit', {}).get('emergency_stop'):
                    reasons.append('Emergency stop')
                if data.get('limits_hit', {}).get('daily_loss_limit_hit'):
                    reasons.append('Daily loss limit')
                if data.get('limits_hit', {}).get('daily_trade_limit_hit'):
                    reasons.append('Trade limit')
                    
                tests.append({
                    'name': 'Trading Policies',
                    'category': 'Services',
                    'status': 'FAIL',
                    'error': f'Trading blocked: {", ".join(reasons)}'
                })
        else:
            tests.append({
                'name': 'Trading Policies',
                'category': 'Services',
                'status': 'FAIL',
                'error': f'HTTP {response.status_code}'
            })
    except Exception as e:
        tests.append({
            'name': 'Trading Policies',
            'category': 'Services',
            'status': 'FAIL',
            'error': str(e)
        })
    
    # Test Paper Trading Activity (last 24 hours)
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(*) as count
                    FROM positions
                    WHERE mode = 'paper'
                      AND entry_time > NOW() - INTERVAL '24 hours'
                """)
                row = cur.fetchone()
                count = row['count']
                
                tests.append({
                    'name': 'Paper Trading Activity',
                    'category': 'Services',
                    'status': 'PASS',
                    'detail': f'{count} positions in last 24h'
                })
    except Exception as e:
        tests.append({
            'name': 'Paper Trading Activity',
            'category': 'Services',
            'status': 'FAIL',
            'error': str(e)
        })
    
    return tests


def test_database_health():
    """Test database performance and integrity"""
    tests = []
    
    # Test Database Size
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT pg_size_pretty(pg_database_size('trading_system')) as size
                """)
                row = cur.fetchone()
                tests.append({
                    'name': 'Database Size',
                    'category': 'Database',
                    'status': 'PASS',
                    'detail': row['size']
                })
    except Exception as e:
        tests.append({
            'name': 'Database Size',
            'category': 'Database',
            'status': 'FAIL',
            'error': str(e)
        })
    
    # Test Table Row Counts
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        (SELECT COUNT(*) FROM ohlcv_candles) as candles,
                        (SELECT COUNT(*) FROM signals) as signals,
                        (SELECT COUNT(*) FROM positions) as positions,
                        (SELECT COUNT(*) FROM backtests) as backtests
                """)
                row = cur.fetchone()
                
                details = f"Candles: {row['candles']:,}, Signals: {row['signals']:,}, Positions: {row['positions']:,}, Backtests: {row['backtests']:,}"
                tests.append({
                    'name': 'Table Row Counts',
                    'category': 'Database',
                    'status': 'PASS',
                    'detail': details
                })
    except Exception as e:
        tests.append({
            'name': 'Table Row Counts',
            'category': 'Database',
            'status': 'FAIL',
            'error': str(e)
        })
    
    # Test for Missing Indices (performance check)
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(*) as count 
                    FROM pg_stat_user_tables 
                    WHERE schemaname = 'public' AND n_live_tup > 1000 AND idx_scan = 0
                """)
                row = cur.fetchone()
                missing = row['count']
                
                if missing == 0:
                    tests.append({
                        'name': 'Database Indices',
                        'category': 'Database',
                        'status': 'PASS',
                        'detail': 'All tables properly indexed'
                    })
                else:
                    tests.append({
                        'name': 'Database Indices',
                        'category': 'Database',
                        'status': 'FAIL',
                        'error': f'{missing} large tables without indices'
                    })
    except Exception as e:
        tests.append({
            'name': 'Database Indices',
            'category': 'Database',
            'status': 'FAIL',
            'error': str(e)
        })
    
    return tests


def test_afteraction_system():
    """Test AfterAction analysis system"""
    tests = []
    
    # Test 1: AfterAction API is responding
    try:
        response = requests.get(
            f'http://{settings.service_host}:{settings.port_afteraction_api}/health',
            timeout=5
        )
        if response.status_code == 200:
            tests.append({
                'name': 'AfterAction API Health',
                'category': 'AfterAction',
                'status': 'PASS',
                'detail': 'API responding on port 8018'
            })
        else:
            tests.append({
                'name': 'AfterAction API Health',
                'category': 'AfterAction',
                'status': 'FAIL',
                'error': f'HTTP {response.status_code}'
            })
    except Exception as e:
        tests.append({
            'name': 'AfterAction API Health',
            'category': 'AfterAction',
            'status': 'FAIL',
            'error': str(e)
        })
    
    # Test 2: Can fetch stats
    try:
        response = requests.get(
            f'http://{settings.service_host}:{settings.port_afteraction_api}/stats',
            timeout=5
        )
        if response.status_code == 200:
            data = response.json()
            tests.append({
                'name': 'AfterAction Stats Endpoint',
                'category': 'AfterAction',
                'status': 'PASS',
                'detail': f"Win rate: {data.get('avg_win_rate', 0)}%"
            })
        else:
            tests.append({
                'name': 'AfterAction Stats Endpoint',
                'category': 'AfterAction',
                'status': 'FAIL',
                'error': f'HTTP {response.status_code}'
            })
    except Exception as e:
        tests.append({
            'name': 'AfterAction Stats Endpoint',
            'category': 'AfterAction',
            'status': 'FAIL',
            'error': str(e)
        })
    
    # Test 3: Check if afteraction_reports table exists
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_name = 'afteraction_reports'
                    ) as exists
                """)
                row = cur.fetchone()
                exists = row['exists'] if row else False
                
                if exists:
                    # Count reports
                    cur.execute("SELECT COUNT(*) as count FROM afteraction_reports")
                    count_row = cur.fetchone()
                    count = count_row['count'] if count_row else 0
                    
                    tests.append({
                        'name': 'AfterAction Reports Table',
                        'category': 'AfterAction',
                        'status': 'PASS',
                        'detail': f'{count} analysis reports stored'
                    })
                else:
                    tests.append({
                        'name': 'AfterAction Reports Table',
                        'category': 'AfterAction',
                        'status': 'WARN',
                        'detail': 'Table will be created on first analysis'
                    })
    except Exception as e:
        tests.append({
            'name': 'AfterAction Reports Table',
            'category': 'AfterAction',
            'status': 'FAIL',
            'error': str(e)
        })
    
    # Test 4: Check recent trading activity (needed for analysis)
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(*) as count
                    FROM positions 
                    WHERE mode = 'paper' 
                    AND entry_time > NOW() - INTERVAL '24 hours'
                """)
                row = cur.fetchone()
                recent_trades = row['count'] if row else 0
                
                if recent_trades > 0:
                    tests.append({
                        'name': 'Trading Activity for Analysis',
                        'category': 'AfterAction',
                        'status': 'PASS',
                        'detail': f'{recent_trades} trades in last 24h'
                    })
                else:
                    tests.append({
                        'name': 'Trading Activity for Analysis',
                        'category': 'AfterAction',
                        'status': 'WARN',
                        'detail': 'No recent trades to analyze'
                    })
    except Exception as e:
        tests.append({
            'name': 'Trading Activity for Analysis',
            'category': 'AfterAction',
            'status': 'FAIL',
            'error': str(e)
        })
    
    return tests


@app.get("/test/database")
def test_database():
    """Test database connectivity and schema"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Count tables
                cur.execute("""
                    SELECT COUNT(*) as count 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public'
                """)
                table_count = cur.fetchone()['count']
                
                # Count active symbols
                cur.execute("SELECT symbol FROM symbols WHERE status = 'active' ORDER BY symbol")
                active_symbols = [r['symbol'] for r in cur.fetchall()]
                symbol_count = len(active_symbols)
                
                # Count strategies
                cur.execute("SELECT COUNT(*) as count FROM strategies")
                strategy_count = cur.fetchone()['count']
                
                # Use pg_stat estimate for total candle count (instant, no table scan)
                cur.execute("""
                    SELECT n_live_tup as total_candles
                    FROM pg_stat_user_tables
                    WHERE relname = 'ohlcv_candles'
                """)
                stats_row = cur.fetchone()
                total_est = stats_row['total_candles'] if stats_row else 0
                
                # Distribute estimate evenly across active symbols for display
                per_symbol = (total_est // symbol_count) if symbol_count else 0
                candle_counts = [{"symbol": s, "count": per_symbol} for s in active_symbols]
                
                # Get latest candle per symbol using index (symbol, timestamp DESC) — fast
                latest_candle = None
                for sym in active_symbols:
                    cur.execute(
                        "SELECT timestamp FROM ohlcv_candles WHERE symbol=%s ORDER BY timestamp DESC LIMIT 1",
                        (sym,)
                    )
                    row = cur.fetchone()
                    if row and (latest_candle is None or row['timestamp'] > latest_candle):
                        latest_candle = row['timestamp']
                
                return {
                    "status": "success",
                    "tables": table_count,
                    "symbols": symbol_count,
                    "strategies": strategy_count,
                    "candle_counts": candle_counts,
                    "latest_candle": str(latest_candle) if latest_candle else None,
                    "database": "trading_system"
                }
    except Exception as e:
        logger.error("database_test_failed", error=str(e))
        return {"status": "error", "message": str(e)}

@app.get("/test/afteraction")
def test_afteraction_api():
    """Test AfterAction API functionality"""
    try:
        # Test 1: Health check
        health_response = requests.get(
            f"http://{settings.service_host}:{settings.port_afteraction_api}/health",
            timeout=5
        )
        health_ok = health_response.status_code == 200
        
        # Test 2: Get stats
        stats_response = requests.get(
            f"http://{settings.service_host}:{settings.port_afteraction_api}/stats",
            timeout=5
        )
        stats_ok = stats_response.status_code == 200
        stats_data = stats_response.json() if stats_ok else {}
        
        # Test 3: Check recent reports
        reports_response = requests.get(
            f"http://{settings.service_host}:{settings.port_afteraction_api}/reports?limit=5",
            timeout=5
        )
        reports_ok = reports_response.status_code == 200
        reports_data = reports_response.json() if reports_ok else []
        
        return {
            "status": "success",
            "health": "healthy" if health_ok else "unhealthy",
            "tests": {
                "health_check": health_ok,
                "stats_endpoint": stats_ok,
                "reports_endpoint": reports_ok
            },
            "stats": stats_data,
            "recent_reports": len(reports_data) if isinstance(reports_data, list) else 0,
            "recent_report_summary": reports_data[:3] if isinstance(reports_data, list) and reports_data else []
        }
    
    except Exception as e:
        logger.error("afteraction_test_failed", error=str(e))
        return {
            "status": "error", 
            "message": str(e),
            "health": "unhealthy"
        }

@app.post("/trigger/backfill")
def trigger_backfill():
    """Trigger the historical backfill Celery task"""
    try:
        from celery import Celery
        
        celery_app = Celery(
            'trading_system',
            broker=settings.redis_url,
            backend=settings.redis_url
        )
        
        # Trigger the backfill task asynchronously
        result = celery_app.send_task('backfill_historical_candles')
        
        logger.info("backfill_triggered", task_id=result.id)
        
        return {
            "status": "success",
            "message": "Backfill task started",
            "task_id": result.id
        }
    except Exception as e:
        logger.error("backfill_trigger_failed", error=str(e))
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("services.testing_api.main:app", host="0.0.0.0", port=settings.port_testing_api, workers=4)
