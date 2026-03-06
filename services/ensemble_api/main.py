"""Ensemble API - Trust-Ranked Multi-Strategy Voting Engine (Port 8021)"""
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Optional, Any
from datetime import datetime
import sys
import os
import json
import httpx

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.database import get_connection
from shared.config import get_settings
from shared.logging_config import setup_logging

settings = get_settings()
logger = setup_logging('ensemble_api', settings.log_level)

app = FastAPI(title="Ensemble API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

AI_API_URL = f"http://{settings.service_host}:{settings.port_ai_api}"
SIGNAL_API_URL = f"http://{settings.service_host}:{settings.port_signal_api}"
BACKTEST_API_URL = f"http://{settings.service_host}:{settings.port_backtest_api}"

MIN_SIGNALS_REQUIRED = 3
MIN_TRUST_FACTOR = 0.10
DECISION_THRESHOLD = 0.55  # weighted vote ratio to act


class EnsembleDecideRequest(BaseModel):
    symbol: str
    use_ai_weighting: bool = True
    min_trust_factor: float = MIN_TRUST_FACTOR
    min_signals: int = MIN_SIGNALS_REQUIRED


class AssignStrategiesRequest(BaseModel):
    symbol: str
    backtest_days: int = 90


class RerankRequest(BaseModel):
    symbol: str
    recalculate_backtests: bool = False


@app.get("/")
def root():
    return {"service": "Ensemble API", "status": "running", "version": "1.0.0"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/status")
def get_status():
    """Current ensemble system state — active strategies, mode, recent decisions."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Count symbol_strategy assignments by status
                cur.execute("""
                    SELECT status, COUNT(*) AS cnt
                    FROM symbol_strategies
                    GROUP BY status
                """)
                strategy_counts = {row['status']: row['cnt'] for row in cur.fetchall()}

                # Latest trading mode
                cur.execute("""
                    SELECT mode, profitable_days_streak, unprofitable_days_streak,
                           days_to_promote, days_to_demote, reevaluation_triggered,
                           updated_at
                    FROM trading_mode_config
                    ORDER BY updated_at DESC LIMIT 1
                """)
                mode_row = cur.fetchone()

                # Last 5 ensemble decisions
                cur.execute("""
                    SELECT symbol, decision, total_signals, threshold_met,
                           buy_votes_weighted, sell_votes_weighted, created_at
                    FROM ensemble_decisions
                    ORDER BY created_at DESC LIMIT 5
                """)
                recent = cur.fetchall()

        return {
            "status": "ok",
            "strategy_assignments": strategy_counts,
            "trading_mode": dict(mode_row) if mode_row else None,
            "recent_decisions": [dict(r) for r in recent],
        }
    except Exception as e:
        logger.error("ensemble_status_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/trust-rankings/{symbol}")
def get_trust_rankings(symbol: str, limit: int = Query(20, ge=1, le=100)):
    """Return strategies ranked by trust_factor for a given symbol."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT ss.id, ss.symbol, ss.strategy_id, s.name AS strategy_name,
                           ss.trust_factor, ss.profit_factor, ss.win_rate,
                           ss.total_trades, ss.fee_drag_pct, ss.rank, ss.status,
                           ss.last_backtest_at
                    FROM symbol_strategies ss
                    JOIN strategies s ON s.id = ss.strategy_id
                    WHERE ss.symbol = %s
                    ORDER BY ss.trust_factor DESC
                    LIMIT %s
                """, (symbol, limit))
                rows = cur.fetchall()

        if not rows:
            raise HTTPException(status_code=404, detail=f"No strategy assignments found for {symbol}")

        return {
            "symbol": symbol,
            "count": len(rows),
            "rankings": [dict(r) for r in rows],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("trust_rankings_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/rerank/{symbol}")
def rerank_strategies(symbol: str, body: RerankRequest = None):
    """Recompute trust_factor = PF × (WR/100) × (1 - fee_drag) and re-rank."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, profit_factor, win_rate, fee_drag_pct
                    FROM symbol_strategies
                    WHERE symbol = %s
                """, (symbol,))
                rows = cur.fetchall()

                if not rows:
                    raise HTTPException(status_code=404, detail=f"No assignments for {symbol}")

                updated = 0
                for row in rows:
                    pf = float(row['profit_factor'] or 1.0)
                    wr = float(row['win_rate'] or 0.0)
                    fee = float(row['fee_drag_pct'] or 0.001)
                    trust = pf * (wr / 100.0) * (1.0 - fee)
                    cur.execute("""
                        UPDATE symbol_strategies
                        SET trust_factor = %s, updated_at = NOW()
                        WHERE id = %s
                    """, (round(trust, 6), row['id']))
                    updated += 1

                # Re-assign rank ordering by trust_factor DESC
                cur.execute("""
                    WITH ranked AS (
                        SELECT id,
                               ROW_NUMBER() OVER (
                                   PARTITION BY symbol
                                   ORDER BY trust_factor DESC
                               ) AS new_rank
                        FROM symbol_strategies
                        WHERE symbol = %s
                    )
                    UPDATE symbol_strategies ss
                    SET rank = ranked.new_rank
                    FROM ranked
                    WHERE ss.id = ranked.id
                """, (symbol,))

                conn.commit()

        logger.info("rerank_complete", symbol=symbol, updated=updated)
        return {"status": "success", "symbol": symbol, "updated": updated}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("rerank_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/assign-all-strategies/{symbol}")
def assign_all_strategies(symbol: str):
    """
    Assign every enabled strategy from the strategies table to this symbol.
    Uses last backtest results if available; otherwise sets trust_factor = 0
    (will be populated by Celery rank_strategies_per_symbol task).
    """
    try:
        assigned = 0
        skipped = 0
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, name FROM strategies WHERE enabled = true")
                strategies = cur.fetchall()

                for strat in strategies:
                    # Check if backtest results exist
                    cur.execute("""
                        SELECT profit_factor, win_rate, total_trades
                        FROM backtests
                        WHERE strategy_id = %s AND symbol = %s
                        ORDER BY created_at DESC LIMIT 1
                    """, (strat['id'], symbol))
                    bt = cur.fetchone()

                    pf = float(bt['profit_factor']) if bt and bt['profit_factor'] else 1.0
                    wr = float(bt['win_rate']) if bt and bt['win_rate'] else 0.0
                    total = int(bt['total_trades']) if bt and bt['total_trades'] else 0
                    fee = 0.001  # 0.1% default fee drag
                    trust = pf * (wr / 100.0) * (1.0 - fee)

                    cur.execute("""
                        INSERT INTO symbol_strategies
                            (symbol, strategy_id, trust_factor, profit_factor,
                             win_rate, total_trades, fee_drag_pct, status)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, 'active')
                        ON CONFLICT (symbol, strategy_id) DO UPDATE SET
                            trust_factor = EXCLUDED.trust_factor,
                            profit_factor = EXCLUDED.profit_factor,
                            win_rate = EXCLUDED.win_rate,
                            total_trades = EXCLUDED.total_trades,
                            updated_at = NOW()
                    """, (symbol, strat['id'], round(trust, 6), pf, wr, total, fee))
                    assigned += 1

                # Rank them
                cur.execute("""
                    WITH ranked AS (
                        SELECT id,
                               ROW_NUMBER() OVER (
                                   PARTITION BY symbol
                                   ORDER BY trust_factor DESC
                               ) AS new_rank
                        FROM symbol_strategies
                        WHERE symbol = %s
                    )
                    UPDATE symbol_strategies ss
                    SET rank = ranked.new_rank
                    FROM ranked
                    WHERE ss.id = ranked.id
                """, (symbol,))
                conn.commit()

        logger.info("assign_all_strategies_complete", symbol=symbol, assigned=assigned)
        return {"status": "success", "symbol": symbol, "assigned": assigned, "skipped": skipped}
    except Exception as e:
        logger.error("assign_strategies_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/decide")
def ensemble_decide(req: EnsembleDecideRequest):
    """
    Run a full trust-weighted ensemble vote for the symbol.

    Steps:
    1. Fetch latest BUY/SELL signals for symbol from trusted strategies
    2. Optionally call AI API to get per-signal weight adjustments
    3. Tally weighted votes → BUY / SELL / HOLD
    4. Require MIN_SIGNALS_REQUIRED total signals to act
    5. Log decision to ensemble_decisions table
    6. Return decision + confidence
    """
    symbol = req.symbol

    # ── Step 1: fetch recent signals for trusted strategies ──────────────────
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Get trusted strategy IDs for this symbol
                cur.execute("""
                    SELECT ss.strategy_id, ss.trust_factor, ss.profit_factor,
                           ss.win_rate, s.name AS strategy_name
                    FROM symbol_strategies ss
                    JOIN strategies s ON s.id = ss.strategy_id
                    WHERE ss.symbol = %s
                      AND ss.trust_factor >= %s
                      AND ss.status = 'active'
                    ORDER BY ss.trust_factor DESC
                """, (symbol, req.min_trust_factor))
                trusted = cur.fetchall()

                if not trusted:
                    return _hold_response(symbol, "no_trusted_strategies", 0)

                trusted_ids = [t['strategy_id'] for t in trusted]
                trust_map = {t['strategy_id']: t for t in trusted}

                # Fetch latest signal per strategy (within last 60 minutes)
                cur.execute("""
                    SELECT DISTINCT ON (strategy_id)
                           id, symbol, strategy_id, signal_type, quality_score,
                           price_at_signal, generated_at
                    FROM signals
                    WHERE symbol = %s
                      AND strategy_id = ANY(%s)
                      AND generated_at > NOW() - INTERVAL '60 minutes'
                      AND acted_on = false
                    ORDER BY strategy_id, generated_at DESC
                """, (symbol, trusted_ids))
                signals = cur.fetchall()

                # Fetch last close price for context
                cur.execute("""
                    SELECT close FROM ohlcv_candles
                    WHERE symbol = %s
                    ORDER BY timestamp DESC LIMIT 1
                """, (symbol,))
                price_row = cur.fetchone()
                current_price = float(price_row['close']) if price_row else None

                # Fetch current market regime
                cur.execute("""
                    SELECT regime FROM market_regime
                    WHERE symbol = %s
                    ORDER BY detected_at DESC LIMIT 1
                """, (symbol,))
                regime_row = cur.fetchone()
                market_regime = regime_row['regime'] if regime_row else 'unknown'

    except Exception as e:
        logger.error("ensemble_fetch_error", symbol=symbol, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

    if len(signals) < req.min_signals:
        return _hold_response(symbol, "insufficient_signals", len(signals))

    # ── Step 2: collect AI weight adjustments ────────────────────────────────
    signals_considered = []
    buy_weighted = 0.0
    sell_weighted = 0.0
    total_signals = len(signals)

    for sig in signals:
        strategy_id = sig['strategy_id']
        trust_info = trust_map.get(strategy_id, {})
        base_trust = float(trust_info.get('trust_factor', 0.5))
        pf = float(trust_info.get('profit_factor', 1.0))
        wr = float(trust_info.get('win_rate', 50.0))
        strategy_name = trust_info.get('strategy_name', 'unknown')
        signal_direction = sig['signal_type'].upper()  # 'BUY' or 'SELL'
        quality = float(sig['quality_score'] or 50) / 100.0

        # Start with base weight = trust_factor × quality_score_ratio
        weight = base_trust * quality

        # Optionally ask AI to adjust weight
        if req.use_ai_weighting:
            try:
                with httpx.Client(timeout=5.0) as client:
                    ai_resp = client.post(
                        f"{AI_API_URL}/weigh-ensemble-signal",
                        json={
                            "symbol": symbol,
                            "signal_type": signal_direction,
                            "trust_factor": base_trust,
                            "profit_factor": pf,
                            "win_rate": wr,
                            "strategy_name": strategy_name,
                            "market_regime": market_regime,
                            "recent_candles_summary": f"price={current_price}"
                        }
                    )
                    if ai_resp.status_code == 200:
                        ai_data = ai_resp.json()
                        ai_multiplier = float(ai_data.get("adjusted_weight", 1.0))
                        weight = weight * ai_multiplier
            except Exception:
                pass  # Graceful fallback — keep base weight

        signals_considered.append({
            "signal_id": sig['id'],
            "strategy_id": strategy_id,
            "strategy_name": strategy_name,
            "direction": signal_direction,
            "quality_score": sig['quality_score'],
            "trust_factor": base_trust,
            "final_weight": round(weight, 4),
        })

        if signal_direction == "BUY":
            buy_weighted += weight
        elif signal_direction == "SELL":
            sell_weighted += weight

    # ── Step 3: tally votes ──────────────────────────────────────────────────
    total_votes = buy_weighted + sell_weighted
    if total_votes == 0:
        return _hold_response(symbol, "zero_vote_weight", total_signals)

    buy_ratio = buy_weighted / total_votes
    sell_ratio = sell_weighted / total_votes

    if buy_ratio >= DECISION_THRESHOLD:
        decision = "BUY"
        confidence = round(buy_ratio, 4)
    elif sell_ratio >= DECISION_THRESHOLD:
        decision = "SELL"
        confidence = round(sell_ratio, 4)
    else:
        decision = "HOLD"
        confidence = round(max(buy_ratio, sell_ratio), 4)

    threshold_met = decision != "HOLD"

    # ── Step 4: log to ensemble_decisions ───────────────────────────────────
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO ensemble_decisions
                        (symbol, decision, total_signals, buy_votes_weighted,
                         sell_votes_weighted, ai_weight_adjustment,
                         signals_considered, threshold_met, executed)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, false)
                    RETURNING id
                """, (
                    symbol, decision, total_signals,
                    round(buy_weighted, 6), round(sell_weighted, 6),
                    1.0,  # aggregate AI weight adjustment placeholder
                    json.dumps(signals_considered),
                    threshold_met,
                ))
                decision_id = cur.fetchone()['id']
                conn.commit()
    except Exception as e:
        logger.error("ensemble_log_error", symbol=symbol, error=str(e))
        decision_id = None

    logger.info("ensemble_decided",
                symbol=symbol, decision=decision, confidence=confidence,
                buy_weighted=buy_weighted, sell_weighted=sell_weighted,
                total_signals=total_signals)

    return {
        "symbol": symbol,
        "decision": decision,
        "confidence": confidence,
        "buy_votes_weighted": round(buy_weighted, 4),
        "sell_votes_weighted": round(sell_weighted, 4),
        "total_signals": total_signals,
        "threshold_met": threshold_met,
        "market_regime": market_regime,
        "signals_considered": signals_considered,
        "decision_id": decision_id,
    }


def _hold_response(symbol: str, reason: str, signal_count: int) -> dict:
    return {
        "symbol": symbol,
        "decision": "HOLD",
        "confidence": 0.0,
        "buy_votes_weighted": 0.0,
        "sell_votes_weighted": 0.0,
        "total_signals": signal_count,
        "threshold_met": False,
        "reason": reason,
        "signals_considered": [],
        "decision_id": None,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("services.ensemble_api.main:app", host="0.0.0.0", port=settings.port_ensemble_api, workers=2)  # port 8022
