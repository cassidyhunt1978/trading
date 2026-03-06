"""AfterAction API - Post-Trade Analysis & Learning"""
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.database import get_connection
from shared.config import get_settings
from shared.logging_config import setup_logging

settings = get_settings()
logger = setup_logging('afteraction_api', settings.log_level)

app = FastAPI(title="AfterAction API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class AfterActionReport(BaseModel):
    report_id: int
    mode: str
    period_start: datetime
    period_end: datetime
    total_trades_analyzed: int
    winning_trades: int
    losing_trades: int
    missed_opportunities: int
    false_signals: int
    recommendations: List[Dict]
    regime_detected: Optional[str]
    created_at: datetime

@app.get("/")
def root():
    return {"service": "AfterAction API", "status": "running", "version": "1.0.0"}

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.post("/analyze")
async def run_afteraction_analysis(
    mode: str = Query("paper", regex="^(paper|live)$"),
    hours: int = Query(12, ge=1, le=168)
):
    """Run after-action analysis on recent trades"""
    try:
        # Ensure table exists before proceeding
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS afteraction_reports (
                        id SERIAL PRIMARY KEY,
                        mode TEXT NOT NULL,
                        period_start TIMESTAMP NOT NULL,
                        period_end TIMESTAMP NOT NULL,
                        total_trades_analyzed INTEGER DEFAULT 0,
                        winning_trades INTEGER DEFAULT 0,
                        losing_trades INTEGER DEFAULT 0,
                        missed_opportunities INTEGER DEFAULT 0,
                        false_signals INTEGER DEFAULT 0,
                        recommendations JSONB,
                        regime_detected TEXT,
                        created_at TIMESTAMP DEFAULT NOW()
                    )
                """)
                conn.commit()
        
        period_end = datetime.utcnow()
        period_start = period_end - timedelta(hours=hours)
        
        logger.info("afteraction_started", mode=mode, hours=hours)
        
        # Get trades in period
        trades = get_trades_in_period(mode, period_start, period_end)
        
        # Get signals in period
        signals = get_signals_in_period(period_start, period_end)
        
        # Analyze trades
        analysis = analyze_trades(trades)
        
        # Detect missed opportunities
        missed = detect_missed_opportunities(signals, trades)
        
        # Detect false signals
        false_signals = detect_false_signals(signals, trades)
        
        # Detect market regime
        regime = detect_market_regime(mode, hours)
        
        # Generate recommendations
        recommendations = generate_recommendations(analysis, missed, false_signals, regime)
        
        # Save report
        report_id = save_afteraction_report(
            mode=mode,
            period_start=period_start,
            period_end=period_end,
            trades=trades,
            missed=missed,
            false_signals=false_signals,
            recommendations=recommendations,
            regime=regime
        )
        
        logger.info("afteraction_complete", report_id=report_id, recommendations=len(recommendations))
        
        return {
            "status": "success",
            "report_id": report_id,
            "period": {
                "start": period_start.isoformat(),
                "end": period_end.isoformat()
            },
            "summary": {
                "total_trades": len(trades),
                "winning_trades": analysis['winning_trades'],
                "losing_trades": analysis['losing_trades'],
                "win_rate": analysis['win_rate'],
                "missed_opportunities": missed['count'],
                "false_signals": false_signals['count'],
                "regime": regime
            },
            "recommendations": recommendations
        }
    
    except Exception as e:
        import traceback
        logger.error("afteraction_error", error=str(e), traceback=traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

def get_trades_in_period(mode: str, start: datetime, end: datetime) -> List[dict]:
    """Get all trades in time period"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM positions
                WHERE mode = %s
                AND entry_time >= %s
                AND entry_time <= %s
                ORDER BY entry_time
            """, (mode, start, end))
            
            return [dict(row) for row in cur.fetchall()]

def get_signals_in_period(start: datetime, end: datetime) -> List[dict]:
    """Get all signals in time period"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM signals
                WHERE generated_at >= %s
                AND generated_at <= %s
                ORDER BY generated_at
            """, (start, end))
            
            return [dict(row) for row in cur.fetchall()]

def analyze_trades(trades: List[dict]) -> dict:
    """Analyze trade performance"""
    if not trades:
        return {
            'winning_trades': 0,
            'losing_trades': 0,
            'win_rate': 0,
            'avg_pnl': 0,
            'avg_hold_time': 0
        }
    
    # Filter out trades with None realized_pnl and ensure numeric comparison
    valid_trades = [t for t in trades if t.get('realized_pnl') is not None]
    
    winning = [t for t in valid_trades if float(t.get('realized_pnl', 0)) > 0]
    losing = [t for t in valid_trades if float(t.get('realized_pnl', 0)) <= 0]
    
    # Average hold time
    closed_trades = [t for t in valid_trades if t.get('status') == 'closed' and t.get('exit_time')]
    if closed_trades:
        hold_times = [(t['exit_time'] - t['entry_time']).total_seconds() / 60 for t in closed_trades]
        avg_hold_time = sum(hold_times) / len(hold_times)
    else:
        avg_hold_time = 0
    
    trade_count = len(valid_trades) if valid_trades else len(trades)
    
    return {
        'winning_trades': len(winning),
        'losing_trades': len(losing),
        'win_rate': (len(winning) / trade_count * 100) if trade_count else 0,
        'avg_pnl': sum(float(t.get('realized_pnl', 0)) for t in valid_trades) / trade_count if trade_count else 0,
        'avg_hold_time': avg_hold_time
    }

def detect_missed_opportunities(signals: List[dict], trades: List[dict]) -> dict:
    """Find high-quality signals that weren't acted on"""
    missed = []
    
    for signal in signals:
        # Skip if acted on
        if signal['acted_on']:
            continue
        
        # Skip if low quality (handle None values)
        quality = signal.get('quality_score')
        if quality is None or quality < 70:
            continue
        
        # Check if would have been profitable
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT close FROM ohlcv_candles
                    WHERE symbol = %s
                    AND timestamp > %s
                    AND timestamp < %s + INTERVAL '30 minutes'
                    ORDER BY timestamp
                    LIMIT 10
                """, (signal['symbol'], signal['generated_at'], signal['generated_at']))
                
                future_candles = [dict(row) for row in cur.fetchall()]
        
        if future_candles:
            entry_price = future_candles[0].get('close')
            if entry_price is None:
                continue
                
            max_price = max((c.get('close') for c in future_candles if c.get('close') is not None), default=None)
            min_price = min((c.get('close') for c in future_candles if c.get('close') is not None), default=None)
            
            if max_price is None or min_price is None:
                continue
            
            if signal['signal_type'].upper() == 'BUY':
                potential_profit = ((max_price - entry_price) / entry_price) * 100
            else:
                potential_profit = ((entry_price - min_price) / entry_price) * 100
            
            if potential_profit is not None and potential_profit > 2.0:  # Missed opportunity if >2% profit potential
                missed.append({
                    'signal_id': signal['id'],
                    'symbol': signal['symbol'],
                    'signal_type': signal['signal_type'],
                    'quality': signal['quality_score'],
                    'potential_profit_pct': round(potential_profit, 2),
                    'generated_at': signal['generated_at'].isoformat()
                })
    
    return {
        'count': len(missed),
        'opportunities': missed[:10]  # Top 10
    }

def detect_false_signals(signals: List[dict], trades: List[dict]) -> dict:
    """Find signals that led to losing trades"""
    false = []
    
    for trade in trades:
        if not trade.get('signal_id'):
            continue
        
        # Handle None realized_pnl values
        realized_pnl = trade.get('realized_pnl')
        if realized_pnl is None or float(realized_pnl) >= 0:
            continue  # Not a losing trade
        
        # Find the signal
        signal = next((s for s in signals if s['id'] == trade['signal_id']), None)
        
        if signal:
            false.append({
                'signal_id': signal['id'],
                'symbol': signal['symbol'],
                'signal_type': signal['signal_type'],
                'quality': signal['quality_score'],
                'actual_loss_pct': round(trade.get('realized_pnl_pct', 0), 2),
                'generated_at': signal['generated_at'].isoformat()
            })
    
    return {
        'count': len(false),
        'false_signals': false[:10]
    }

def detect_market_regime(mode: str, hours: int) -> str:
    """Detect current market regime"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Get recent BTC price action (proxy for market)
            cur.execute("""
                SELECT close, high, low, volume, timestamp
                FROM ohlcv_candles
                WHERE symbol = 'BTC/USDT'
                AND timestamp > NOW() - INTERVAL '%s hours'
                ORDER BY timestamp DESC
                LIMIT 50
            """, (hours,))
            
            candles = [dict(row) for row in cur.fetchall()]
    
    if not candles or len(candles) < 20:
        return "unknown"
    
    # Calculate volatility
    prices = [c['close'] for c in candles]
    avg_price = sum(prices) / len(prices)
    volatility = sum(abs(p - avg_price) for p in prices) / len(prices) / avg_price * 100
    
    # Calculate trend
    recent_avg = sum(prices[:10]) / 10
    older_avg = sum(prices[-10:]) / 10
    trend_pct = ((recent_avg - older_avg) / older_avg) * 100
    
    # Classify regime
    if volatility > 3.0:
        regime = "high_volatility"
    elif abs(trend_pct) > 5.0:
        regime = "trending_" + ("up" if trend_pct > 0 else "down")
    elif abs(trend_pct) < 1.0:
        regime = "ranging"
    else:
        regime = "normal"
    
    logger.info("regime_detected", regime=regime, volatility=round(volatility, 2), trend=round(trend_pct, 2))
    
    return regime

def generate_recommendations(analysis: dict, missed: dict, false_signals: dict, regime: str) -> List[dict]:
    """Generate actionable recommendations"""
    recommendations = []
    
    # Win rate recommendations
    if analysis['win_rate'] < 50:
        recommendations.append({
            'priority': 'high',
            'category': 'strategy',
            'title': 'Low win rate detected',
            'description': f"Current win rate is {round(analysis['win_rate'], 1)}%. Consider tightening entry criteria or adjusting stop-loss levels.",
            'action': 'Increase minimum signal quality threshold to 70+'
        })
    
    # Missed opportunities
    if missed['count'] > 5:
        recommendations.append({
            'priority': 'medium',
            'category': 'execution',
            'title': f"{missed['count']} missed opportunities detected",
            'description': f"Found {missed['count']} high-quality signals that weren't acted on but had good potential.",
            'action': 'Consider faster signal execution or increasing capital allocation'
        })
    
    # False signals
    if false_signals['count'] > 3:
        recommendations.append({
            'priority': 'high',
            'category': 'signal_quality',
            'title': f"{false_signals['count']} false signals resulted in losses",
            'description': "Multiple signals led to losing trades despite good quality scores.",
            'action': 'Review signal generation logic, especially quality scoring'
        })
    
    # Regime-specific recommendations
    if regime == "high_volatility":
        recommendations.append({
            'priority': 'high',
            'category': 'risk',
            'title': 'High volatility regime detected',
            'description': 'Market showing elevated volatility. Higher risk of stop-outs.',
            'action': 'Reduce position sizes by 30-50% and widen stop-loss levels'
        })
    
    elif regime == "ranging":
        recommendations.append({
            'priority': 'medium',
            'category': 'strategy',
            'title': 'Ranging market detected',
            'description': 'Market moving sideways without clear trend.',
            'action': 'Focus on mean-reversion strategies, avoid breakout trades'
        })
    
    elif regime.startswith("trending"):
        direction = "upward" if "up" in regime else "downward"
        recommendations.append({
            'priority': 'medium',
            'category': 'strategy',
            'title': f'Strong {direction} trend detected',
            'description': f'Market showing clear {direction} momentum.',
            'action': f"Favor {'buy' if 'up' in regime else 'sell'} signals, use wider profit targets"
        })
    
    # Hold time analysis
    if analysis['avg_hold_time'] > 0:
        if analysis['avg_hold_time'] < 30:
            recommendations.append({
                'priority': 'low',
                'category': 'execution',
                'title': 'Very short hold times',
                'description': f"Average hold time is {round(analysis['avg_hold_time'], 1)} minutes.",
                'action': 'Consider if frequent trading is driving up fees unnecessarily'
            })
    
    return recommendations

def save_afteraction_report(mode: str, period_start: datetime, period_end: datetime,
                           trades: List[dict], missed: dict, false_signals: dict,
                           recommendations: List[dict], regime: str) -> int:
    """Save after-action report to database"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            import psycopg2.extras
            
            # Filter out None realized_pnl values before comparison
            valid_trades = [t for t in trades if t.get('realized_pnl') is not None]
            winning_trades = len([t for t in valid_trades if float(t.get('realized_pnl', 0)) > 0])
            losing_trades = len([t for t in valid_trades if float(t.get('realized_pnl', 0)) <= 0])
            
            cur.execute("""
                INSERT INTO afteraction_reports
                (mode, period_start, period_end, total_trades_analyzed,
                 winning_trades, losing_trades, missed_opportunities, false_signals,
                 recommendations, regime_detected, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                RETURNING id
            """, (
                mode, period_start, period_end, len(trades),
                winning_trades, losing_trades, missed['count'], false_signals['count'],
                psycopg2.extras.Json(recommendations), regime
            ))
            
            return cur.fetchone()['id']

@app.get("/reports")
def get_reports(
    mode: Optional[str] = Query(None, regex="^(paper|live)$"),
    limit: int = Query(20, ge=1, le=100)
):
    """Get after-action reports"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Ensure table exists
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS afteraction_reports (
                        id SERIAL PRIMARY KEY,
                        mode TEXT NOT NULL,
                        period_start TIMESTAMP NOT NULL,
                        period_end TIMESTAMP NOT NULL,
                        total_trades_analyzed INTEGER DEFAULT 0,
                        winning_trades INTEGER DEFAULT 0,
                        losing_trades INTEGER DEFAULT 0,
                        missed_opportunities INTEGER DEFAULT 0,
                        false_signals INTEGER DEFAULT 0,
                        recommendations JSONB,
                        regime_detected TEXT,
                        created_at TIMESTAMP DEFAULT NOW()
                    )
                """)
                conn.commit()
                
                if mode:
                    cur.execute("""
                        SELECT * FROM afteraction_reports
                        WHERE mode = %s
                        ORDER BY created_at DESC
                        LIMIT %s
                    """, (mode, limit))
                else:
                    cur.execute("""
                        SELECT * FROM afteraction_reports
                        ORDER BY created_at DESC
                        LIMIT %s
                    """, (limit,))
                
                reports = [dict(row) for row in cur.fetchall()]
        
        return {
            "status": "success",
            "count": len(reports),
            "reports": reports
        }
    
    except Exception as e:
        logger.error("reports_fetch_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/reports/{report_id}")
def get_report_detail(report_id: int):
    """Get detailed after-action report"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM afteraction_reports WHERE id = %s", (report_id,))
                report = cur.fetchone()
                
                if not report:
                    raise HTTPException(status_code=404, detail="Report not found")
                
                return dict(report)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error("report_detail_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/stats")
def get_afteraction_stats():
    """Get after-action statistics"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Ensure table exists
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS afteraction_reports (
                        id SERIAL PRIMARY KEY,
                        mode TEXT NOT NULL,
                        period_start TIMESTAMP NOT NULL,
                        period_end TIMESTAMP NOT NULL,
                        total_trades_analyzed INTEGER DEFAULT 0,
                        winning_trades INTEGER DEFAULT 0,
                        losing_trades INTEGER DEFAULT 0,
                        missed_opportunities INTEGER DEFAULT 0,
                        false_signals INTEGER DEFAULT 0,
                        recommendations JSONB,
                        regime_detected TEXT,
                        created_at TIMESTAMP DEFAULT NOW()
                    )
                """)
                conn.commit()  # Commit table creation
                
                cur.execute("""
                    SELECT 
                        COUNT(*) as total_reports,
                        AVG(CAST(winning_trades AS FLOAT) / NULLIF(total_trades_analyzed, 0) * 100) as avg_win_rate,
                        SUM(missed_opportunities) as total_missed,
                        SUM(false_signals) as total_false_signals,
                        MAX(created_at) as last_run
                    FROM afteraction_reports
                """)
                
                stats = dict(cur.fetchone())
        
        return {
            "status": "success",
            "total_reports": stats['total_reports'] or 0,
            "avg_win_rate": round(float(stats['avg_win_rate'] or 0), 2),
            "total_missed_opportunities": stats['total_missed'] or 0,
            "total_false_signals": stats['total_false_signals'] or 0,
            "last_run": stats['last_run'].isoformat() if stats['last_run'] else None
        }
    
    except Exception as e:
        logger.error("stats_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("services.afteraction_api.main:app", host="0.0.0.0", port=settings.port_afteraction_api, workers=4)
