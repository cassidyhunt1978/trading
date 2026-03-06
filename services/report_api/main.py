"""Report API - Accountability & Proof Dashboard (Port 8023)"""
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Optional, Any
from datetime import datetime, date, timedelta, timezone
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.database import get_connection
from shared.config import get_settings
from shared.logging_config import setup_logging

settings = get_settings()
logger = setup_logging('report_api', settings.log_level)

app = FastAPI(title="Report API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"service": "Report API", "status": "running", "version": "1.0.0"}


@app.get("/health")
def health():
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        return {"status": "healthy", "service": "report_api", "port": 8023}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Database unavailable")


@app.get("/equity_curve")
def equity_curve(days: int = Query(30, ge=1, le=365)):
    """Time-series equity curve from portfolio_snapshots."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT snapshot_time, total_capital, realized_pnl, open_pnl
                    FROM portfolio_snapshots
                    WHERE snapshot_time >= %s
                    ORDER BY snapshot_time ASC
                """, (since,))
                rows = cur.fetchall()
        return {
            "days": days,
            "points": [
                {
                    "time": r[0].isoformat() if r[0] else None,
                    "total_capital": float(r[1]) if r[1] is not None else None,
                    "realized_pnl": float(r[2]) if r[2] is not None else None,
                    "open_pnl": float(r[3]) if r[3] is not None else None,
                }
                for r in rows
            ],
            "count": len(rows),
        }
    except Exception as e:
        logger.error(f"equity_curve error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/daily_log")
def daily_log(days: int = Query(30, ge=1, le=180)):
    """Daily P&L log with win/loss streaks from daily_profitability_log."""
    since = date.today() - timedelta(days=days)
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT log_date, total_pnl, is_profitable,
                           trades_count, winning_trades, created_at
                    FROM daily_profitability_log
                    WHERE log_date >= %s
                    ORDER BY log_date DESC
                """, (since,))
                rows = cur.fetchall()
        entries = []
        for r in rows:
            trades = r[3] or 0
            wins = r[4] or 0
            entries.append({
                "date": str(r[0]),
                "total_pnl": float(r[1]) if r[1] is not None else 0.0,
                "is_profitable": bool(r[2]),
                "trades_count": trades,
                "winning_trades": wins,
                "win_rate": round(wins / trades * 100, 1) if trades > 0 else None,
            })
        return {"days": days, "entries": entries, "count": len(entries)}
    except Exception as e:
        logger.error(f"daily_log error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/streak")
def streak():
    """Current trading mode and streak from trading_mode_config."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT symbol, trading_mode,
                           profitable_days_streak, unprofitable_days_streak,
                           days_to_promote, days_to_demote,
                           updated_at
                    FROM trading_mode_config
                    ORDER BY updated_at DESC
                    LIMIT 50
                """)
                rows = cur.fetchall()
        results = []
        for r in rows:
            results.append({
                "symbol": r[0],
                "trading_mode": r[1],
                "profitable_days_streak": r[2] or 0,
                "unprofitable_days_streak": r[3] or 0,
                "days_to_promote": r[4] or 7,
                "days_to_demote": r[5] or 5,
                "updated_at": r[6].isoformat() if r[6] else None,
                "promote_progress_pct": round((r[2] or 0) / max(r[4] or 7, 1) * 100),
                "demote_risk_pct": round((r[3] or 0) / max(r[5] or 5, 1) * 100),
            })
        # Aggregate summary
        modes = [r["trading_mode"] for r in results]
        summary = {
            "live_count": modes.count("live"),
            "paper_count": modes.count("paper"),
            "stopped_count": modes.count("stopped"),
            "total_symbols": len(results),
        }
        return {"summary": summary, "symbols": results}
    except Exception as e:
        logger.error(f"streak error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/trust_rankings")
def trust_rankings(
    symbol: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100)
):
    """Top strategies ranked by trust_factor from symbol_strategies."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                if symbol:
                    cur.execute("""
                        SELECT ss.symbol, ss.strategy_name, ss.trust_factor,
                               ss.profit_factor, ss.win_rate, ss.total_trades,
                               ss.status, ss.updated_at,
                               s.description
                        FROM symbol_strategies ss
                        LEFT JOIN strategies s ON s.name = ss.strategy_name
                        WHERE ss.symbol = %s
                        ORDER BY ss.trust_factor DESC NULLS LAST
                        LIMIT %s
                    """, (symbol, limit))
                else:
                    cur.execute("""
                        SELECT ss.symbol, ss.strategy_name, ss.trust_factor,
                               ss.profit_factor, ss.win_rate, ss.total_trades,
                               ss.status, ss.updated_at,
                               s.description
                        FROM symbol_strategies ss
                        LEFT JOIN strategies s ON s.name = ss.strategy_name
                        ORDER BY ss.trust_factor DESC NULLS LAST
                        LIMIT %s
                    """, (limit,))
                rows = cur.fetchall()
        return {
            "symbol_filter": symbol,
            "rankings": [
                {
                    "symbol": r[0],
                    "strategy_name": r[1],
                    "trust_factor": float(r[2]) if r[2] is not None else 0.0,
                    "profit_factor": float(r[3]) if r[3] is not None else 0.0,
                    "win_rate": float(r[4]) if r[4] is not None else 0.0,
                    "total_trades": r[5] or 0,
                    "status": r[6],
                    "updated_at": r[7].isoformat() if r[7] else None,
                    "description": r[8],
                }
                for r in rows
            ],
            "count": len(rows),
        }
    except Exception as e:
        logger.error(f"trust_rankings error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/accountability")
def accountability():
    """Proof-of-concept: win rate, signal quality, profitable days, fee drag."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Overall trade stats (closed positions)
                cur.execute("""
                    SELECT
                        COUNT(*) AS total_trades,
                        SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) AS winning_trades,
                        SUM(realized_pnl) AS total_pnl,
                        AVG(realized_pnl) AS avg_pnl,
                        SUM(fees) AS total_fees,
                        AVG(fees) AS avg_fee
                    FROM positions
                    WHERE status = 'closed'
                """)
                trade_row = cur.fetchone()

                # Signal quality stats (last 30 days)
                cur.execute("""
                    SELECT
                        COUNT(*) AS total_signals,
                        AVG(quality_score) AS avg_quality,
                        SUM(CASE WHEN signal_type = 'buy' THEN 1 ELSE 0 END) AS buy_signals,
                        SUM(CASE WHEN signal_type = 'sell' THEN 1 ELSE 0 END) AS sell_signals
                    FROM signals
                    WHERE generated_at >= NOW() - INTERVAL '30 days'
                """)
                sig_row = cur.fetchone()

                # Profitable days percentage
                cur.execute("""
                    SELECT
                        COUNT(*) AS total_days,
                        SUM(CASE WHEN is_profitable THEN 1 ELSE 0 END) AS profitable_days
                    FROM daily_profitability_log
                """)
                days_row = cur.fetchone()

                # Live vs paper breakdown
                cur.execute("""
                    SELECT trading_mode, COUNT(*) as cnt
                    FROM trading_mode_config
                    GROUP BY trading_mode
                """)
                mode_rows = cur.fetchall()

        total_trades = trade_row[0] or 0
        winning_trades = trade_row[1] or 0
        total_pnl = float(trade_row[2]) if trade_row[2] else 0.0
        avg_pnl = float(trade_row[3]) if trade_row[3] else 0.0
        total_fees = float(trade_row[4]) if trade_row[4] else 0.0
        avg_fee = float(trade_row[5]) if trade_row[5] else 0.0

        total_signals = sig_row[0] or 0
        avg_quality = float(sig_row[1]) if sig_row[1] else 0.0

        total_days = days_row[0] or 0
        profitable_days = days_row[1] or 0
        profitable_days_pct = round(profitable_days / total_days * 100, 1) if total_days > 0 else 0.0

        mode_map = {r[0]: r[1] for r in mode_rows}

        win_rate = round(winning_trades / total_trades * 100, 1) if total_trades > 0 else 0.0
        fee_drag_pct = round(total_fees / max(abs(total_pnl), 0.01) * 100, 1) if total_pnl != 0 else 0.0

        return {
            "trades": {
                "total": total_trades,
                "winning": winning_trades,
                "win_rate_pct": win_rate,
                "total_pnl": round(total_pnl, 4),
                "avg_pnl_per_trade": round(avg_pnl, 4),
                "total_fees": round(total_fees, 4),
                "avg_fee_per_trade": round(avg_fee, 4),
                "fee_drag_pct": fee_drag_pct,
            },
            "signals": {
                "total_last_30d": total_signals,
                "avg_quality_score": round(avg_quality, 1),
                "buy_count": sig_row[2] or 0,
                "sell_count": sig_row[3] or 0,
            },
            "daily": {
                "total_days_logged": total_days,
                "profitable_days": profitable_days,
                "profitable_days_pct": profitable_days_pct,
            },
            "modes": {
                "live": mode_map.get("live", 0),
                "paper": mode_map.get("paper", 0),
                "stopped": mode_map.get("stopped", 0),
            },
        }
    except Exception as e:
        logger.error(f"accountability error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/daily_report")
def daily_report(report_date: Optional[str] = Query(None)):
    """Full daily report: P&L summary, top signals, top/bottom performers."""
    try:
        target_date = date.fromisoformat(report_date) if report_date else date.today()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format; use YYYY-MM-DD")

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Day P&L log
                cur.execute("""
                    SELECT total_pnl, is_profitable, trades_count, winning_trades
                    FROM daily_profitability_log
                    WHERE log_date = %s
                """, (target_date,))
                day_row = cur.fetchone()

                # Top 5 performing closed positions that day
                cur.execute("""
                    SELECT symbol, strategy_name, realized_pnl, entry_price, exit_price
                    FROM positions
                    WHERE DATE(closed_at) = %s AND status = 'closed'
                    ORDER BY realized_pnl DESC
                    LIMIT 5
                """, (target_date,))
                top_pos = cur.fetchall()

                # Bottom 5
                cur.execute("""
                    SELECT symbol, strategy_name, realized_pnl, entry_price, exit_price
                    FROM positions
                    WHERE DATE(closed_at) = %s AND status = 'closed'
                    ORDER BY realized_pnl ASC
                    LIMIT 5
                """, (target_date,))
                bot_pos = cur.fetchall()

                # Signals generated that day
                cur.execute("""
                    SELECT COUNT(*), AVG(quality_score)
                    FROM signals
                    WHERE DATE(generated_at) = %s
                """, (target_date,))
                sig_row = cur.fetchone()

                # Portfolio snapshot nearest to end of that day
                cur.execute("""
                    SELECT total_capital, snapshot_time
                    FROM portfolio_snapshots
                    WHERE DATE(snapshot_time) = %s
                    ORDER BY snapshot_time DESC
                    LIMIT 1
                """, (target_date,))
                snap = cur.fetchone()

        def pos_fmt(rows):
            return [
                {
                    "symbol": r[0],
                    "strategy": r[1],
                    "pnl": float(r[2]) if r[2] else 0.0,
                    "entry": float(r[3]) if r[3] else None,
                    "exit": float(r[4]) if r[4] else None,
                }
                for r in rows
            ]

        return {
            "date": str(target_date),
            "summary": {
                "total_pnl": float(day_row[0]) if day_row and day_row[0] else 0.0,
                "is_profitable": bool(day_row[1]) if day_row else None,
                "trades_count": day_row[2] if day_row else 0,
                "winning_trades": day_row[3] if day_row else 0,
            },
            "signals": {
                "count": sig_row[0] if sig_row else 0,
                "avg_quality": round(float(sig_row[1]), 1) if sig_row and sig_row[1] else 0.0,
            },
            "portfolio_eod": {
                "total_capital": float(snap[0]) if snap and snap[0] else None,
                "snapshot_time": snap[1].isoformat() if snap and snap[1] else None,
            },
            "top_performers": pos_fmt(top_pos),
            "bottom_performers": pos_fmt(bot_pos),
        }
    except Exception as e:
        logger.error(f"daily_report error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8023, log_level=settings.log_level.lower())
