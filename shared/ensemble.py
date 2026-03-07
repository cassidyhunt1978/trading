"""
shared/ensemble.py

EnsembleVoter — reusable trust-weighted ensemble logic.

Can be imported by ensemble_api, celery tasks, or any service that needs
to run a consensus vote for a symbol without going through HTTP.

Usage:
    from shared.ensemble import EnsembleVoter
    from shared.config import get_settings

    voter = EnsembleVoter(get_settings())
    result = voter.decide("BTC/USDT")
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import httpx

from shared.database import get_connection

logger = logging.getLogger("ensemble_voter")

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_MIN_TRUST        = 0.10   # minimum trust_factor to include a strategy
DEFAULT_MIN_SIGNALS      = 3      # minimum signals required to act
DEFAULT_WINDOW_MINUTES   = 60     # how far back to look for signals
DECISION_THRESHOLD       = 0.55   # weighted-vote ratio required to decide


# ── Data shapes ───────────────────────────────────────────────────────────────
@dataclass
class SignalVote:
    signal_id:     int
    strategy_id:   int
    strategy_name: str
    direction:     str   # "BUY" | "SELL"
    quality_score: float
    trust_factor:  float
    final_weight:  float


@dataclass
class EnsembleResult:
    symbol:            str
    decision:          str          # "BUY" | "SELL" | "HOLD"
    confidence:        float
    buy_votes_weighted:  float
    sell_votes_weighted: float
    total_signals:     int
    threshold_met:     bool
    market_regime:     str
    signals_considered: list[SignalVote]
    hold_reason:       Optional[str] = None   # set when decision == HOLD


# ── EnsembleVoter ─────────────────────────────────────────────────────────────
class EnsembleVoter:
    """
    Trust-weighted ensemble voter for a single symbol.

    Parameters
    ----------
    settings : shared.config.Settings
        Application settings (needed for service_host, port_ai_api, etc.)
    min_trust_factor : float
        Only include strategies with trust_factor >= this.
    min_signals : int
        Require at least this many signals before acting.
    window_minutes : int
        Only consider signals generated within this many minutes.
    decision_threshold : float
        Weighted-vote ratio (0–1) required to decide BUY or SELL.
    """

    def __init__(
        self,
        settings,
        min_trust_factor: float  = DEFAULT_MIN_TRUST,
        min_signals:      int    = DEFAULT_MIN_SIGNALS,
        window_minutes:   int    = DEFAULT_WINDOW_MINUTES,
        decision_threshold: float = DECISION_THRESHOLD,
    ):
        self.settings           = settings
        self.min_trust_factor   = min_trust_factor
        self.min_signals        = min_signals
        self.window_minutes     = window_minutes
        self.decision_threshold = decision_threshold
        self._ai_url = (
            f"http://{settings.service_host}:{settings.port_ai_api}"
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def get_signals_for_symbol(self, symbol: str) -> tuple[list, list, str, Optional[float]]:
        """
        Query DB for recent signals from trusted strategies.

        Returns
        -------
        (trusted_strategies, signals, market_regime, current_price)
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Trusted strategies for this symbol
                cur.execute("""
                    SELECT ss.strategy_id, ss.trust_factor, ss.profit_factor,
                           ss.win_rate, s.name AS strategy_name
                    FROM symbol_strategies ss
                    JOIN strategies s ON s.id = ss.strategy_id
                    WHERE ss.symbol = %s
                      AND ss.trust_factor >= %s
                      AND ss.status = 'active'
                    ORDER BY ss.trust_factor DESC
                """, (symbol, self.min_trust_factor))
                trusted = cur.fetchall()

                if not trusted:
                    return [], [], "unknown", None

                trusted_ids = [t["strategy_id"] for t in trusted]

                # Latest un-acted signal per strategy (within window)
                cur.execute("""
                    SELECT DISTINCT ON (strategy_id)
                           id, symbol, strategy_id, signal_type,
                           quality_score, price_at_signal, generated_at
                    FROM signals
                    WHERE symbol = %s
                      AND strategy_id = ANY(%s)
                      AND generated_at > NOW() - INTERVAL '%s minutes'
                      AND acted_on = false
                    ORDER BY strategy_id, generated_at DESC
                """, (symbol, trusted_ids, self.window_minutes))
                signals = cur.fetchall()

                # Last close price
                cur.execute("""
                    SELECT close FROM ohlcv_candles
                    WHERE symbol = %s
                    ORDER BY timestamp DESC LIMIT 1
                """, (symbol,))
                price_row = cur.fetchone()
                current_price = float(price_row["close"]) if price_row else None

                # Market regime
                cur.execute("""
                    SELECT regime FROM market_regime
                    WHERE symbol = %s
                    ORDER BY detected_at DESC LIMIT 1
                """, (symbol,))
                regime_row = cur.fetchone()
                market_regime = regime_row["regime"] if regime_row else "unknown"

        return list(trusted), list(signals), market_regime, current_price

    def ai_weight_signal(
        self,
        symbol:        str,
        signal_type:   str,
        trust_factor:  float,
        profit_factor: float,
        win_rate:      float,
        strategy_name: str,
        market_regime: str,
        current_price: Optional[float],
        timeout:       float = 5.0,
    ) -> float:
        """
        Ask the AI API to return an adjusted weight multiplier (0.0–2.0).
        Falls back to 1.0 on any error or timeout.
        """
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(
                    f"{self._ai_url}/weigh-ensemble-signal",
                    json={
                        "symbol":               symbol,
                        "signal_type":          signal_type,
                        "trust_factor":         trust_factor,
                        "profit_factor":        profit_factor,
                        "win_rate":             win_rate,
                        "strategy_name":        strategy_name,
                        "market_regime":        market_regime,
                        "recent_candles_summary": f"price={current_price}",
                    },
                )
                if resp.status_code == 200:
                    multiplier = float(resp.json().get("adjusted_weight", 1.0))
                    # Clamp to valid range
                    return max(0.0, min(2.0, multiplier))
        except Exception:
            pass
        return 1.0

    def get_consensus(
        self,
        symbol:         str,
        use_ai:         bool = True,
    ) -> EnsembleResult:
        """
        Run a full weighted ensemble vote for `symbol`.

        1. Fetch signals from trusted strategies
        2. Optionally call AI API to adjust each weight
        3. Tally votes → BUY / SELL / HOLD
        4. Require ≥ min_signals to act; prefer multi-strategy

        Returns an EnsembleResult (never raises — worst case returns HOLD).
        """
        try:
            trusted, signals, market_regime, current_price = (
                self.get_signals_for_symbol(symbol)
            )
        except Exception as e:
            logger.error("ensemble_db_error", extra={"symbol": symbol, "error": str(e)})
            return self._hold(symbol, "db_error")

        trust_map = {t["strategy_id"]: t for t in trusted}

        if not trusted:
            return self._hold(symbol, "no_trusted_strategies")

        if len(signals) < self.min_signals:
            return self._hold(symbol, "insufficient_signals",
                              total_signals=len(signals),
                              market_regime=market_regime)

        # ── Tally weighted votes ──────────────────────────────────────────────
        votes:         list[SignalVote] = []
        buy_weighted   = 0.0
        sell_weighted  = 0.0

        for sig in signals:
            sid   = sig["strategy_id"]
            info  = trust_map.get(sid, {})
            trust = float(info.get("trust_factor", 0.5))
            pf    = float(info.get("profit_factor", 1.0))
            wr    = float(info.get("win_rate", 50.0))
            name  = info.get("strategy_name", "unknown")
            direction = sig["signal_type"].upper()
            quality   = float(sig["quality_score"] or 50) / 100.0

            weight = trust * quality  # base weight

            if use_ai:
                multiplier = self.ai_weight_signal(
                    symbol=symbol,
                    signal_type=direction,
                    trust_factor=trust,
                    profit_factor=pf,
                    win_rate=wr,
                    strategy_name=name,
                    market_regime=market_regime,
                    current_price=current_price,
                )
                weight *= multiplier

            votes.append(SignalVote(
                signal_id=sig["id"],
                strategy_id=sid,
                strategy_name=name,
                direction=direction,
                quality_score=float(sig["quality_score"] or 0),
                trust_factor=trust,
                final_weight=round(weight, 4),
            ))

            if direction == "BUY":
                buy_weighted += weight
            elif direction == "SELL":
                sell_weighted += weight

        total_votes = buy_weighted + sell_weighted
        if total_votes == 0:
            return self._hold(symbol, "zero_vote_weight",
                              total_signals=len(signals),
                              market_regime=market_regime,
                              votes=votes)

        buy_ratio  = buy_weighted  / total_votes
        sell_ratio = sell_weighted / total_votes

        if buy_ratio >= self.decision_threshold:
            decision   = "BUY"
            confidence = round(buy_ratio, 4)
        elif sell_ratio >= self.decision_threshold:
            decision   = "SELL"
            confidence = round(sell_ratio, 4)
        else:
            decision   = "HOLD"
            confidence = round(max(buy_ratio, sell_ratio), 4)

        return EnsembleResult(
            symbol=symbol,
            decision=decision,
            confidence=confidence,
            buy_votes_weighted=round(buy_weighted, 4),
            sell_votes_weighted=round(sell_weighted, 4),
            total_signals=len(signals),
            threshold_met=(decision != "HOLD"),
            market_regime=market_regime,
            signals_considered=votes,
        )

    def log_decision(self, result: EnsembleResult) -> Optional[int]:
        """
        Persist the ensemble result to the ensemble_decisions table.
        Returns the new row ID, or None on failure.
        """
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO ensemble_decisions
                            (symbol, decision, total_signals,
                             buy_votes_weighted, sell_votes_weighted,
                             ai_weight_adjustment, signals_considered,
                             threshold_met, executed)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, false)
                        RETURNING id
                    """, (
                        result.symbol,
                        result.decision,
                        result.total_signals,
                        float(result.buy_votes_weighted),
                        float(result.sell_votes_weighted),
                        1.0,  # aggregate AI multiplier placeholder
                        json.dumps([
                            {
                                "signal_id":     v.signal_id,
                                "strategy_id":   v.strategy_id,
                                "strategy_name": v.strategy_name,
                                "direction":     v.direction,
                                "quality_score": v.quality_score,
                                "trust_factor":  v.trust_factor,
                                "final_weight":  v.final_weight,
                            }
                            for v in result.signals_considered
                        ]),
                        result.threshold_met,
                    ))
                    row_id = cur.fetchone()["id"]
                    conn.commit()
            return row_id
        except Exception as e:
            logger.warning("ensemble_log_failed", extra={"error": str(e)})
            return None

    # ── Private helpers ───────────────────────────────────────────────────────

    def _hold(
        self,
        symbol: str,
        reason: str,
        total_signals: int = 0,
        market_regime: str = "unknown",
        votes: list = None,
    ) -> EnsembleResult:
        return EnsembleResult(
            symbol=symbol,
            decision="HOLD",
            confidence=0.0,
            buy_votes_weighted=0.0,
            sell_votes_weighted=0.0,
            total_signals=total_signals,
            threshold_met=False,
            market_regime=market_regime,
            signals_considered=votes or [],
            hold_reason=reason,
        )
