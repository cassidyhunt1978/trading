"""Report API - Accountability & Proof Dashboard (Port 8023)"""
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
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

# ── Simple TTL response cache ────────────────────────────────────────────────
import time as _time
_resp_cache: dict = {}

def _cache_get(key: str):
    entry = _resp_cache.get(key)
    if entry and _time.monotonic() < entry[1]:
        return entry[0]
    return None

def _cache_set(key: str, value, ttl: float = 45.0):
    _resp_cache[key] = (value, _time.monotonic() + ttl)
# ─────────────────────────────────────────────────────────────────────────────

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
                    SELECT timestamp, total_capital, total_pnl, daily_pnl
                    FROM portfolio_snapshots
                    WHERE timestamp >= %s
                    ORDER BY timestamp ASC
                """, (since,))
                rows = cur.fetchall()
        return {
            "days": days,
            "points": [
                {
                    "time": r["timestamp"].isoformat() if r["timestamp"] else None,
                    "total_capital": float(r["total_capital"]) if r["total_capital"] is not None else None,
                    "realized_pnl": float(r["total_pnl"]) if r["total_pnl"] is not None else None,
                    "open_pnl": float(r["daily_pnl"]) if r["daily_pnl"] is not None else None,
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
    """Daily P&L log. Uses daily_profitability_log if populated, otherwise computes from positions."""
    cache_key = f"daily_log:{days}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    since = date.today() - timedelta(days=days)
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Check if daily_profitability_log has enough data
                cur.execute("SELECT COUNT(*) AS cnt FROM daily_profitability_log WHERE date >= %s", (since,))
                row_count = cur.fetchone()["cnt"]

                if row_count >= 5:
                    # Use the log table enriched with fees from positions
                    cur.execute("""
                        SELECT d.date, d.mode, d.total_pnl, d.is_profitable,
                               d.trades_count, d.winning_trades,
                               COALESCE(f.total_fees, 0) AS total_fees
                        FROM daily_profitability_log d
                        LEFT JOIN (
                            SELECT DATE(entry_time) AS day, mode,
                                   SUM(COALESCE(entry_fee, 0) + COALESCE(exit_fee, 0)) AS total_fees
                            FROM positions
                            WHERE status = 'closed' AND entry_time >= %s
                            GROUP BY DATE(entry_time), mode
                        ) f ON f.day = d.date AND f.mode = d.mode
                        WHERE d.date >= %s
                        ORDER BY d.date DESC, d.mode
                    """, (since, since))
                    rows = cur.fetchall()
                    entries = []
                    for r in rows:
                        trades = r["trades_count"] or 0
                        wins   = r["winning_trades"] or 0
                        entries.append({
                            "date":         str(r["date"]),
                            "mode":         r["mode"],
                            "total_pnl":    float(r["total_pnl"]) if r["total_pnl"] is not None else 0.0,
                            "is_profitable": bool(r["is_profitable"]),
                            "trades_count": trades,
                            "winning_trades": wins,
                            "win_rate":     round(wins / trades * 100, 1) if trades > 0 else None,
                            "total_fees":   float(r["total_fees"]),
                        })
                else:
                    # Fall back: compute directly from positions table
                    cur.execute("""
                        SELECT DATE(entry_time) AS day,
                               mode,
                               SUM(realized_pnl) AS total_pnl,
                               COUNT(*)           AS trades_count,
                               SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) AS winning_trades,
                               SUM(COALESCE(entry_fee, 0) + COALESCE(exit_fee, 0)) AS total_fees
                        FROM positions
                        WHERE status = 'closed'
                          AND entry_time >= %s
                        GROUP BY DATE(entry_time), mode
                        ORDER BY day DESC, mode
                    """, (since,))
                    rows = cur.fetchall()
                    entries = []
                    for r in rows:
                        pnl    = float(r["total_pnl"]) if r["total_pnl"] is not None else 0.0
                        trades = r["trades_count"] or 0
                        wins   = r["winning_trades"] or 0
                        entries.append({
                            "date":         str(r["day"]),
                            "mode":         r["mode"],
                            "total_pnl":    pnl,
                            "is_profitable": pnl > 0,
                            "trades_count": trades,
                            "winning_trades": wins,
                            "win_rate":     round(wins / trades * 100, 1) if trades > 0 else None,
                            "total_fees":   float(r["total_fees"]),
                        })

        result = {"days": days, "entries": entries, "count": len(entries)}
        _cache_set(cache_key, result, ttl=45.0)
        return result
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
                    SELECT mode, profitable_days_streak, unprofitable_days_streak,
                           days_to_promote, days_to_demote, updated_at
                    FROM trading_mode_config
                    ORDER BY id
                """)
                rows = cur.fetchall()
        results = []
        for r in rows:
            profit_streak = r["profitable_days_streak"] or 0
            unprofit_streak = r["unprofitable_days_streak"] or 0
            days_promote = r["days_to_promote"] or 7
            days_demote = r["days_to_demote"] or 5
            results.append({
                "mode": r["mode"],
                "profitable_days_streak": profit_streak,
                "unprofitable_days_streak": unprofit_streak,
                "days_to_promote": days_promote,
                "days_to_demote": days_demote,
                "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
                "promote_progress_pct": round(profit_streak / max(days_promote, 1) * 100),
                "demote_risk_pct": round(unprofit_streak / max(days_demote, 1) * 100),
            })
        modes = [r["mode"] for r in results]
        summary = {
            "live_count": modes.count("live"),
            "paper_count": modes.count("paper"),
            "stopped_count": modes.count("stopped"),
            "total_symbols": len(results),
        }
        return {"summary": summary, "modes": results}
    except Exception as e:
        logger.error(f"streak error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/trust_rankings")
def trust_rankings(
    symbol: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=500)
):
    """Top strategies ranked by trust_factor from symbol_strategies."""
    cache_key = f"trust_rankings:{symbol}:{limit}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                if symbol:
                    cur.execute("""
                        SELECT ss.symbol, s.name AS strategy_name, ss.trust_factor,
                               ss.profit_factor, ss.win_rate, ss.total_trades,
                               ss.status, ss.updated_at,
                               s.description
                        FROM symbol_strategies ss
                        LEFT JOIN strategies s ON s.id = ss.strategy_id
                        WHERE ss.symbol = %s
                          AND ss.total_trades > 0
                          AND s.name NOT IN ('Test Constraint Fix', 'MOCK Momentum Long')
                        ORDER BY ss.trust_factor DESC NULLS LAST
                        LIMIT %s
                    """, (symbol, limit))
                else:
                    cur.execute("""
                        SELECT ss.symbol, s.name AS strategy_name, ss.trust_factor,
                               ss.profit_factor, ss.win_rate, ss.total_trades,
                               ss.status, ss.updated_at,
                               s.description
                        FROM symbol_strategies ss
                        LEFT JOIN strategies s ON s.id = ss.strategy_id
                        WHERE ss.total_trades > 0
                          AND s.name NOT IN ('Test Constraint Fix', 'MOCK Momentum Long')
                        ORDER BY ss.trust_factor DESC NULLS LAST
                        LIMIT %s
                    """, (limit,))
                rows = cur.fetchall()
        result = {
            "symbol_filter": symbol,
            "rankings": [
                {
                    "symbol": r["symbol"],
                    "strategy_name": r["strategy_name"] or "(unnamed)",
                    "trust_factor": float(r["trust_factor"]) if r["trust_factor"] is not None else 0.0,
                    "profit_factor": float(r["profit_factor"]) if r["profit_factor"] is not None else 0.0,
                    "win_rate": float(r["win_rate"]) if r["win_rate"] is not None else 0.0,
                    "total_trades": r["total_trades"] or 0,
                    "status": r["status"],
                    "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
                    "description": r["description"],
                }
                for r in rows
            ],
            "count": len(rows),
        }
        _cache_set(cache_key, result, ttl=60.0)
        return result
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
                        SUM(COALESCE(entry_fee,0) + COALESCE(exit_fee,0)) AS total_fees,
                        AVG(COALESCE(entry_fee,0) + COALESCE(exit_fee,0)) AS avg_fee
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

                # Current mode from trading_mode_config
                cur.execute("""
                    SELECT mode, profitable_days_streak, unprofitable_days_streak
                    FROM trading_mode_config
                    ORDER BY id LIMIT 1
                """)
                mode_row = cur.fetchone()

        total_trades = trade_row["total_trades"] or 0
        winning_trades = trade_row["winning_trades"] or 0
        total_pnl = float(trade_row["total_pnl"]) if trade_row["total_pnl"] else 0.0
        avg_pnl = float(trade_row["avg_pnl"]) if trade_row["avg_pnl"] else 0.0
        total_fees = float(trade_row["total_fees"]) if trade_row["total_fees"] else 0.0
        avg_fee = float(trade_row["avg_fee"]) if trade_row["avg_fee"] else 0.0

        total_signals = sig_row["total_signals"] or 0
        avg_quality = float(sig_row["avg_quality"]) if sig_row["avg_quality"] else 0.0

        total_days = days_row["total_days"] or 0
        profitable_days = days_row["profitable_days"] or 0
        profitable_days_pct = round(profitable_days / total_days * 100, 1) if total_days > 0 else 0.0

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
                "buy_count": sig_row["buy_signals"] or 0,
                "sell_count": sig_row["sell_signals"] or 0,
            },
            "daily": {
                "total_days_logged": total_days,
                "profitable_days": profitable_days,
                "profitable_days_pct": profitable_days_pct,
            },
            "mode": {
                "current": mode_row["mode"] if mode_row else "unknown",
                "profitable_streak": mode_row["profitable_days_streak"] if mode_row else 0,
                "unprofitable_streak": mode_row["unprofitable_days_streak"] if mode_row else 0,
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
                    WHERE date = %s
                    ORDER BY mode LIMIT 1
                """, (target_date,))
                day_row = cur.fetchone()

                # Top 5 performing closed positions that day
                cur.execute("""
                    SELECT p.symbol, s.name AS strategy_name,
                           p.realized_pnl, p.entry_price, p.exit_price
                    FROM positions p
                    LEFT JOIN strategies s ON s.id = p.strategy_id
                    WHERE DATE(p.exit_time) = %s AND p.status = 'closed'
                    ORDER BY p.realized_pnl DESC
                    LIMIT 5
                """, (target_date,))
                top_pos = cur.fetchall()

                # Bottom 5
                cur.execute("""
                    SELECT p.symbol, s.name AS strategy_name,
                           p.realized_pnl, p.entry_price, p.exit_price
                    FROM positions p
                    LEFT JOIN strategies s ON s.id = p.strategy_id
                    WHERE DATE(p.exit_time) = %s AND p.status = 'closed'
                    ORDER BY p.realized_pnl ASC
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
                    SELECT total_capital, timestamp
                    FROM portfolio_snapshots
                    WHERE DATE(timestamp) = %s
                    ORDER BY timestamp DESC
                    LIMIT 1
                """, (target_date,))
                snap = cur.fetchone()

        def pos_fmt(rows):
            return [
                {
                    "symbol": r["symbol"],
                    "strategy": r["strategy_name"],
                    "pnl": float(r["realized_pnl"]) if r["realized_pnl"] else 0.0,
                    "entry": float(r["entry_price"]) if r["entry_price"] else None,
                    "exit": float(r["exit_price"]) if r["exit_price"] else None,
                }
                for r in rows
            ]

        return {
            "date": str(target_date),
            "summary": {
                "total_pnl": float(day_row["total_pnl"]) if day_row and day_row["total_pnl"] else 0.0,
                "is_profitable": bool(day_row["is_profitable"]) if day_row else None,
                "trades_count": day_row["trades_count"] if day_row else 0,
                "winning_trades": day_row["winning_trades"] if day_row else 0,
            },
            "signals": {
                "count": sig_row["count"] if sig_row else 0,
                "avg_quality": round(float(sig_row["avg"]), 1) if sig_row and sig_row["avg"] else 0.0,
            },
            "portfolio_eod": {
                "total_capital": float(snap["total_capital"]) if snap and snap["total_capital"] else None,
                "snapshot_time": snap["timestamp"].isoformat() if snap and snap["timestamp"] else None,
            },
            "top_performers": pos_fmt(top_pos),
            "bottom_performers": pos_fmt(bot_pos),
        }
    except Exception as e:
        logger.error(f"daily_report error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────────────────────────────
#  Pro-Grade: Composite Trust Score per Symbol
# ──────────────────────────────────────────────────────────────────

@app.get("/trust_score/{symbol}")
def trust_score(symbol: str):
    """Composite trust score: backtest PF + walk-forward PF + regime alignment + prediction accuracy."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # One CTE query replaces four sequential round-trips
                cur.execute("""
                    WITH bt AS (
                        SELECT MAX(profit_factor) AS best_pf,
                               MAX(trust_factor)  AS best_trust,
                               MAX(win_rate)       AS best_win
                        FROM symbol_strategies
                        WHERE symbol = %(sym)s AND total_trades >= 3
                    ),
                    wf AS (
                        SELECT AVG(wfr.oos_profit_factor) AS avg_wf_pf,
                               COUNT(*)                    AS num_windows
                        FROM walk_forward_results wfr
                        JOIN symbol_strategies ss
                             ON ss.strategy_id = wfr.strategy_id AND ss.symbol = %(sym)s
                        WHERE wfr.training_end >= NOW() - INTERVAL '90 days'
                    ),
                    reg AS (
                        SELECT regime, regime_confidence
                        FROM market_regime
                        WHERE symbol = %(sym)s
                        ORDER BY detected_at DESC LIMIT 1
                    ),
                    pred AS (
                        SELECT true_predictions, false_predictions
                        FROM price_predictions
                        WHERE symbol = %(sym)s
                        ORDER BY created_at DESC LIMIT 1
                    )
                    SELECT bt.best_pf, bt.best_trust, bt.best_win,
                           wf.avg_wf_pf, wf.num_windows,
                           reg.regime, reg.regime_confidence,
                           pred.true_predictions, pred.false_predictions
                    FROM (SELECT 1) AS _
                    LEFT JOIN bt   ON true
                    LEFT JOIN wf   ON true
                    LEFT JOIN reg  ON true
                    LEFT JOIN pred ON true
                """, {"sym": symbol})
                row = cur.fetchone()

        backtest_pf  = float(row["best_pf"])    if row and row["best_pf"]    else 0.0
        trust_factor = float(row["best_trust"]) if row and row["best_trust"] else 0.0
        wf_pf        = float(row["avg_wf_pf"])  if row and row["avg_wf_pf"]  else 0.0
        wf_windows   = int(row["num_windows"])  if row and row["num_windows"] else 0

        regime       = (row["regime"] or "unknown").lower() if row and row["regime"] else "unknown"
        regime_conf  = float(row["regime_confidence"]) if row and row["regime_confidence"] else 0.5
        if "bull" in regime or "break" in regime:
            regime_alignment = regime_conf
        elif "bear" in regime:
            regime_alignment = 1.0 - regime_conf
        else:
            regime_alignment = 0.5

        if row and (row["true_predictions"] or row["false_predictions"]):
            tp = int(row["true_predictions"] or 0)
            fp = int(row["false_predictions"] or 0)
            prediction_accuracy = tp / max(tp + fp, 1)
        else:
            prediction_accuracy = 0.5

        wf_norm = min(1.0, wf_pf / 2.0)
        trust_score_val = (
            trust_factor        * 0.40 +
            wf_norm             * 0.25 +
            regime_alignment    * 0.20 +
            prediction_accuracy * 0.15
        )

        return {
            "symbol": symbol,
            "trust_score": round(trust_score_val, 4),
            "backtest_pf": round(backtest_pf, 4),
            "trust_factor": round(trust_factor, 4),
            "walkfwd_pf": round(wf_pf, 4),
            "wf_windows": wf_windows,
            "regime": regime,
            "regime_alignment": round(regime_alignment, 4),
            "prediction_accuracy": round(prediction_accuracy, 4),
        }
    except Exception as e:
        logger.error(f"trust_score error for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────────────────────────────
#  Walk-Forward Results per Symbol
# ──────────────────────────────────────────────────────────────────

@app.get("/walkforward/{symbol}")
def walkforward_symbol(symbol: str):
    """Walk-forward folds and summary for a symbol."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        s.name AS strategy_name,
                        wfr.test_start, wfr.test_end,
                        wfr.oos_profit_factor, wfr.oos_win_rate,
                        wfr.oos_total_trades, wfr.oos_return_pct
                    FROM walk_forward_results wfr
                    JOIN strategies s ON s.id = wfr.strategy_id
                    JOIN symbol_strategies ss ON ss.strategy_id = wfr.strategy_id AND ss.symbol = %s
                    ORDER BY wfr.test_end DESC
                    LIMIT 20
                """, (symbol,))
                rows = cur.fetchall()

        if not rows:
            return {"symbol": symbol, "folds": [], "summary": {}, "num_windows": 0}

        folds = []
        for r in rows:
            ts_str = str(r["test_start"])[:10] if r["test_start"] else "?"
            te_str = str(r["test_end"])[:10]   if r["test_end"]   else "?"
            folds.append({
                "name": r["strategy_name"],
                "period": f"{ts_str} → {te_str}",
                "profit_factor": float(r["oos_profit_factor"]) if r["oos_profit_factor"] else 0.0,
                "win_rate": float(r["oos_win_rate"]) if r["oos_win_rate"] else 0.0,
                "trades": r["oos_total_trades"] or 0,
                "return_pct": float(r["oos_return_pct"]) if r["oos_return_pct"] else 0.0,
            })

        pfs  = [f["profit_factor"] for f in folds]
        wrs  = [f["win_rate"]      for f in folds]
        avg_pf      = sum(pfs) / len(pfs) if pfs else 0
        avg_wr      = sum(wrs) / len(wrs) if wrs else 0
        consistency = sum(1 for p in pfs if p >= 1.0) / len(pfs) if pfs else 0

        return {
            "symbol": symbol,
            "folds": folds,
            "num_windows": len(folds),
            "summary": {
                "avg_profit_factor": round(avg_pf, 4),
                "avg_win_rate": round(avg_wr, 4),
                "consistency": round(consistency, 4),
            },
        }
    except Exception as e:
        logger.error(f"walkforward error for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────────────────────────────
#  Import Chart Strategy (from chart export button)
# ──────────────────────────────────────────────────────────────────

class ChartStrategyImport(BaseModel):
    symbol: str
    strategy_id: Any
    timeframe: str = "15m"
    source: str = "chart_export"
    notes: Optional[str] = None


@app.post("/import_charts_strategy")
def import_charts_strategy(payload: ChartStrategyImport):
    """Persist a chart-selected strategy for a symbol and trigger refinement."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                strategy_db_id = None
                try:
                    strategy_db_id = int(payload.strategy_id)
                except (ValueError, TypeError):
                    cur.execute("SELECT id FROM strategies WHERE name = %s LIMIT 1", (str(payload.strategy_id),))
                    row = cur.fetchone()
                    if row:
                        strategy_db_id = row["id"]

                if not strategy_db_id:
                    raise HTTPException(status_code=404, detail=f"Strategy '{payload.strategy_id}' not found")

                cur.execute("""
                    INSERT INTO symbol_strategies (symbol, strategy_id, status, metadata, updated_at)
                    VALUES (%s, %s, 'active',
                            jsonb_build_object('source', %s, 'timeframe', %s, 'imported_at', NOW()::text),
                            NOW())
                    ON CONFLICT (symbol, strategy_id)
                    DO UPDATE SET
                        status     = 'active',
                        metadata   = symbol_strategies.metadata || EXCLUDED.metadata,
                        updated_at = NOW()
                """, (payload.symbol, strategy_db_id, payload.source, payload.timeframe))
                conn.commit()

        logger.info(f"chart_strategy_imported symbol={payload.symbol} strategy={strategy_db_id} tf={payload.timeframe}")

        # Trigger refinement (non-critical, fire-and-forget)
        try:
            import requests as _req
            _req.post(
                f"http://{settings.service_host}:{settings.port_optimization_api}/optimize/symbol",
                json={"symbol": payload.symbol, "strategy_id": strategy_db_id, "reason": "chart_export"},
                timeout=3,
            )
        except Exception:
            pass

        return {
            "status": "imported",
            "symbol": payload.symbol,
            "strategy_id": strategy_db_id,
            "timeframe": payload.timeframe,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"import_charts_strategy error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("services.report_api.main:app", host="0.0.0.0", port=8023,
                log_level=settings.log_level.lower(), workers=4)
