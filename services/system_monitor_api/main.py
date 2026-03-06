"""System Monitor API - CPU, Memory, Disk metrics"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import psutil
import os
import sys
from datetime import datetime, timezone

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.config import get_settings
from shared.logging_config import setup_logging
from shared.database import get_connection

settings = get_settings()
logger = setup_logging('system_monitor_api', settings.log_level)

app = FastAPI(title="System Monitor API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"service": "System Monitor API", "status": "running", "version": "1.0.0"}

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.get("/metrics")
def get_system_metrics():
    """Get all system metrics in one call"""
    try:
        # CPU metrics - use interval=1 for accurate 1-second average
        # This prevents catching momentary spikes
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_count = psutil.cpu_count()
        load_avg = os.getloadavg()
        
        # Memory metrics
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        
        # Disk metrics
        disk = psutil.disk_usage('/')
        disk_io = psutil.disk_io_counters()
        
        # Process count
        process_count = len(psutil.pids())
        
        return {
            "status": "success",
            "cpu": {
                "percent": round(cpu_percent, 1),
                "count": cpu_count,
                "load_avg_1m": round(load_avg[0], 2),
                "load_avg_5m": round(load_avg[1], 2),
                "load_avg_15m": round(load_avg[2], 2)
            },
            "memory": {
                "total_gb": round(mem.total / (1024**3), 2),
                "used_gb": round(mem.used / (1024**3), 2),
                "available_gb": round(mem.available / (1024**3), 2),
                "percent": round(mem.percent, 1),
                "swap_total_gb": round(swap.total / (1024**3), 2),
                "swap_used_gb": round(swap.used / (1024**3), 2),
                "swap_percent": round(swap.percent, 1)
            },
            "disk": {
                "total_gb": round(disk.total / (1024**3), 2),
                "used_gb": round(disk.used / (1024**3), 2),
                "free_gb": round(disk.free / (1024**3), 2),
                "percent": round(disk.percent, 1)
            },
            "disk_io": {
                "read_mb": round(disk_io.read_bytes / (1024**2), 2) if disk_io else 0,
                "write_mb": round(disk_io.write_bytes / (1024**2), 2) if disk_io else 0,
                "read_count": disk_io.read_count if disk_io else 0,
                "write_count": disk_io.write_count if disk_io else 0
            },
            "processes": process_count
        }
    except Exception as e:
        logger.error("metrics_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/cpu")
def get_cpu_metrics():
    """Get CPU metrics only"""
    try:
        # Use interval=1 for accurate 1-second average
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_count = psutil.cpu_count()
        load_avg = os.getloadavg()
        
        return {
            "status": "success",
            "percent": round(cpu_percent, 1),
            "count": cpu_count,
            "load_avg_1m": round(load_avg[0], 2),
            "load_avg_5m": round(load_avg[1], 2),
            "load_avg_15m": round(load_avg[2], 2)
        }
    except Exception as e:
        logger.error("cpu_metrics_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/memory")
def get_memory_metrics():
    """Get memory metrics only"""
    try:
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        
        return {
            "status": "success",
            "total_gb": round(mem.total / (1024**3), 2),
            "used_gb": round(mem.used / (1024**3), 2),
            "available_gb": round(mem.available / (1024**3), 2),
            "percent": round(mem.percent, 1),
            "swap_total_gb": round(swap.total / (1024**3), 2),
            "swap_used_gb": round(swap.used / (1024**3), 2),
            "swap_percent": round(swap.percent, 1)
        }
    except Exception as e:
        logger.error("memory_metrics_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/disk")
def get_disk_metrics():
    """Get disk metrics only"""
    try:
        disk = psutil.disk_usage('/')
        disk_io = psutil.disk_io_counters()
        
        return {
            "status": "success",
            "usage": {
                "total_gb": round(disk.total / (1024**3), 2),
                "used_gb": round(disk.used / (1024**3), 2),
                "free_gb": round(disk.free / (1024**3), 2),
                "percent": round(disk.percent, 1)
            },
            "io": {
                "read_mb": round(disk_io.read_bytes / (1024**2), 2) if disk_io else 0,
                "write_mb": round(disk_io.write_bytes / (1024**2), 2) if disk_io else 0,
                "read_count": disk_io.read_count if disk_io else 0,
                "write_count": disk_io.write_count if disk_io else 0
            }
        }
    except Exception as e:
        logger.error("disk_metrics_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/top_processes")
def get_top_processes(limit: int = 10):
    """Get top processes by CPU usage"""
    try:
        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
            try:
                processes.append({
                    'pid': proc.info['pid'],
                    'name': proc.info['name'],
                    'cpu_percent': round(proc.info['cpu_percent'], 1),
                    'memory_percent': round(proc.info['memory_percent'], 1)
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        # Sort by CPU usage
        processes.sort(key=lambda x: x['cpu_percent'], reverse=True)
        
        return {
            "status": "success",
            "processes": processes[:limit]
        }
    except Exception as e:
        logger.error("top_processes_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/activity")
def get_trading_activity():
    """Get trading system activity status"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            
            # Get last candle fetched time
            cursor.execute("""
                SELECT MAX(timestamp) as last_candle
                FROM ohlcv_candles
            """)
            last_candle = cursor.fetchone()
            
            # Get last signal generation time
            cursor.execute("""
                SELECT MAX(generated_at) as last_signal
                FROM signals
            """)
            last_signal = cursor.fetchone()
            
            # Get active signals count
            cursor.execute("""
                SELECT COUNT(*) as active_count
                FROM signals
                WHERE acted_on = false 
                  AND expires_at > NOW()
            """)
            active_signals = cursor.fetchone()
            
            # Get last trade execution times for both modes and position types
            cursor.execute("""
                SELECT 
                    mode,
                    position_type,
                    MAX(entry_time) as last_trade,
                    COUNT(*) FILTER (WHERE DATE(entry_time) = CURRENT_DATE) as trades_today
                FROM positions
                GROUP BY mode, position_type
            """)
            trades_data = cursor.fetchall()
            
            # Also get ensemble-specific stats (multiple strategies agreeing)
            cursor.execute("""
                SELECT 
                    COUNT(DISTINCT symbol) as ensemble_symbols_today
                FROM signals
                WHERE acted_on = true
                  AND DATE(generated_at) = CURRENT_DATE
                  AND quality_score >= 70
                GROUP BY symbol, signal_type
                HAVING COUNT(DISTINCT strategy_id) >= 3
            """)
            ensemble_consensus = cursor.fetchone()
            
            # Check celery worker status
            celery_workers = 0
            celery_beat = False
            for proc in psutil.process_iter(['name', 'cmdline']):
                try:
                    proc_name = proc.info['name'].lower() if proc.info.get('name') else ''
                    cmdline = proc.info.get('cmdline', [])
                    
                    # Check if this is a celery process
                    if 'celery' in proc_name or (cmdline and any('celery' in str(arg).lower() for arg in cmdline)):
                        cmdline_str = ' '.join(str(arg) for arg in cmdline) if cmdline else ''
                        
                        # Check for beat FIRST (before worker) since beat cmdline contains "celery_worker"
                        if ' beat ' in cmdline_str or cmdline_str.endswith(' beat'):
                            celery_beat = True
                        elif ' worker ' in cmdline_str or cmdline_str.endswith(' worker'):
                            celery_workers += 1
                            
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, TypeError, AttributeError):
                    # Skip processes that error (zombie, terminated, or no access)
                    pass
            
            # Format response
            paper_strategy = next((t for t in trades_data if t['mode'] == 'paper' and t['position_type'] == 'strategy'), None)
            paper_ensemble = next((t for t in trades_data if t['mode'] == 'paper' and t['position_type'] == 'ensemble'), None)
            live_strategy = next((t for t in trades_data if t['mode'] == 'live' and t['position_type'] == 'strategy'), None)
            live_ensemble = next((t for t in trades_data if t['mode'] == 'live' and t['position_type'] == 'ensemble'), None)
            
            now = datetime.now(timezone.utc)
            
            return {
                "status": "success",
                "timestamp": now.isoformat(),
                "candles": {
                    "last_fetched": last_candle['last_candle'].isoformat() if last_candle and last_candle['last_candle'] else None,
                    "seconds_ago": int((now - last_candle['last_candle']).total_seconds()) if last_candle and last_candle['last_candle'] else None
                },
                "signals": {
                    "last_generated": last_signal['last_signal'].isoformat() if last_signal and last_signal['last_signal'] else None,
                    "seconds_ago": int((now - last_signal['last_signal']).total_seconds()) if last_signal and last_signal['last_signal'] else None,
                    "active_count": active_signals['active_count'] if active_signals else 0
                },
                "trades": {
                    "paper": {
                        "strategy": {
                            "last_executed": paper_strategy['last_trade'].isoformat() if paper_strategy and paper_strategy['last_trade'] else None,
                            "seconds_ago": int((now - paper_strategy['last_trade']).total_seconds()) if paper_strategy and paper_strategy['last_trade'] else None,
                            "today_count": paper_strategy['trades_today'] if paper_strategy else 0
                        },
                        "ensemble": {
                            "last_executed": paper_ensemble['last_trade'].isoformat() if paper_ensemble and paper_ensemble['last_trade'] else None,
                            "seconds_ago": int((now - paper_ensemble['last_trade']).total_seconds()) if paper_ensemble and paper_ensemble['last_trade'] else None,
                            "today_count": paper_ensemble['trades_today'] if paper_ensemble else 0
                        }
                    },
                    "live": {
                        "strategy": {
                            "last_executed": live_strategy['last_trade'].isoformat() if live_strategy and live_strategy['last_trade'] else None,
                            "seconds_ago": int((now - live_strategy['last_trade']).total_seconds()) if live_strategy and live_strategy['last_trade'] else None,
                            "today_count": live_strategy['trades_today'] if live_strategy else 0
                        },
                        "ensemble": {
                            "last_executed": live_ensemble['last_trade'].isoformat() if live_ensemble and live_ensemble['last_trade'] else None,
                            "seconds_ago": int((now - live_ensemble['last_trade']).total_seconds()) if live_ensemble and live_ensemble['last_trade'] else None,
                            "today_count": live_ensemble['trades_today'] if live_ensemble else 0
                        }
                    }
                },
                "workers": {
                    "celery_workers": celery_workers,
                    "celery_beat": celery_beat,
                    "status": "healthy" if celery_workers > 0 and celery_beat else "degraded"
                }
            }
    except Exception as e:
        logger.error("activity_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("services.system_monitor_api.main:app", host="0.0.0.0", port=settings.port_system_monitor_api, workers=4)
