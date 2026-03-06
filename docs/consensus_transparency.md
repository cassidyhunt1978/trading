# Consensus Decision Transparency

## Overview

The trading system now provides full transparency into ensemble consensus decisions, allowing you to see which signals were considered, how the voting worked, and what outcomes resulted from each decision.

## How It Works

### 1. Consensus Voting System

When multiple strategies generate signals for the same symbol:

1. **Strategy Votes**: Each strategy that generated a signal votes with weight based on its performance
   - Weight formula: `1 + (win_rate - 0.5)` 
   - Range: 0.5 to 1.5
   - Example: 70% win rate = 1.2x weight

2. **AI Vote** (1.5x multiplier):
   - AI analyzes the signal using Claude Haiku
   - Returns: `vote` (BUY/SELL), `confidence` (0-1), `reasoning`
   - Can vote FOR (+1.5), AGAINST (-1.5), or ABSTAIN (0)

3. **Sentiment Vote** (1.0x multiplier):
   - Fetches crypto news from RSS feeds
   - AI scores sentiment 0-100 (0=bearish, 50=neutral, 100=bullish)
   - Converts to directional weight: `(score - 50) / 50 * direction`

4. **Supermajority Check**:
   - Regular: 60% threshold (runs every 5 minutes)
   - Expedited: 70% threshold + 80%+ consensus + 85+ quality (runs every 60 seconds)

### 2. Decision Recording

Every consensus decision is recorded to `consensus_decisions` table:

```sql
CREATE TABLE consensus_decisions (
    id SERIAL PRIMARY KEY,
    
    -- Basic Decision Info
    symbol VARCHAR(20),
    signal_type VARCHAR(10),  -- BUY or SELL
    consensus_pct NUMERIC(5,2),
    strategy_count INTEGER,
    best_quality NUMERIC(5,2),
    avg_quality NUMERIC(5,2),
    price_at_signal NUMERIC(20,8),
    projected_return_pct NUMERIC(5,2),
    
    -- Voting Breakdown (JSONB for full detail)
    strategy_votes JSONB,  -- Array of {strategy_name, quality, weight, win_rate}
    ai_vote JSONB,          -- {vote, weight, confidence, reasoning}
    sentiment_vote JSONB,   -- {score, weight, recommendation, sources}
    total_weight NUMERIC(10,3),
    total_possible NUMERIC(10,3),
    
    -- Approval & Execution
    approved BOOLEAN,
    executed BOOLEAN,
    position_id INTEGER REFERENCES positions(id),
    
    -- Source Signals
    signal_ids INTEGER[],
    
    -- Timestamps
    generated_at TIMESTAMP,
    decided_at TIMESTAMP DEFAULT NOW(),
    
    -- Outcome Tracking (updated after trade closes)
    trade_outcome VARCHAR(20),  -- 'win', 'loss', 'breakeven'
    realized_pnl_pct NUMERIC(5,2),
    afteraction_notes TEXT
);
```

### 3. Decision Flow

```
┌─────────────────────────────────────────────────────┐
│ 1. Strategies Generate Signals                      │
│    (Multiple strategies agree on same symbol)       │
└──────────────────┬──────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────┐
│ 2. Consensus Endpoint (/signals/consensus)          │
│    • Groups signals by symbol + type                │
│    • Calls AI API for vote (/vote-signal)          │
│    • Calls AI API for sentiment (/sentiment/symbol) │
│    • Calculates weighted consensus                  │
└──────────────────┬──────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────┐
│ 3. Celery Task (execute_consensus_ensemble_trades)  │
│    • Receives consensus signals                     │
│    • For each signal:                               │
│       → Calls Portfolio API to open position        │
│       → Records decision with /consensus/record     │
│       → Links position_id to decision               │
└──────────────────┬──────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────┐
│ 4. Database Record Created                          │
│    • Full voting details preserved                  │
│    • Linked to position for outcome tracking        │
└─────────────────────────────────────────────────────┘
```

## API Endpoints

### 1. Record Consensus Decision

**POST** `/consensus/record`

Records a consensus decision for transparency.

```json
{
  "symbol": "BTC/USDT",
  "signal_type": "BUY",
  "consensus_pct": 85.5,
  "strategy_count": 3,
  "best_quality": 92,
  "avg_quality": 87,
  "price_at_signal": 43250.50,
  "projected_return_pct": 2.5,
  "votes": {
    "strategies": [
      {"strategy_name": "RSI Momentum", "quality": 92, "weight": 1.3, "win_rate": 65.0},
      {"strategy_name": "MACD Cross", "quality": 85, "weight": 1.15, "win_rate": 57.5}
    ],
    "ai": {
      "vote": "BUY",
      "weight": 1.5,
      "confidence": 0.82,
      "reasoning": "Strong upward momentum with positive sentiment"
    },
    "sentiment": {
      "score": 75,
      "weight": 0.5,
      "recommendation": "BULLISH",
      "sources": 5
    },
    "total_weight": 4.45,
    "total_possible": 5.2
  },
  "signal_ids": [12345, 12346],
  "approved": true,
  "executed": true,
  "position_id": 789,
  "generated_at": "2026-02-26T16:30:00Z"
}
```

**Response:**
```json
{
  "status": "success",
  "decision_id": 123
}
```

### 2. Get Recent Decisions

**GET** `/consensus/decisions`

Query Parameters:
- `limit` (int, default=20): Max results to return
- `approved_only` (bool, default=false): Only show approved decisions
- `executed_only` (bool, default=false): Only show executed trades

```bash
curl "http://localhost:8015/consensus/decisions?limit=10&executed_only=true"
```

**Response:**
```json
{
  "status": "success",
  "decisions": [
    {
      "id": 123,
      "symbol": "BTC/USDT",
      "signal_type": "BUY",
      "consensus_pct": 85.5,
      "strategy_count": 3,
      "approved": true,
      "executed": true,
      "position_id": 789,
      "decided_at": "2026-02-26T16:30:15Z",
      "votes": { ... },
      "realized_pnl_pct": 2.3,
      "trade_result": "win"
    }
  ],
  "count": 10
}
```

### 3. Get Decision Detail

**GET** `/consensus/decisions/{decision_id}`

Returns full details for a specific decision including original signals and trade outcome.

```bash
curl "http://localhost:8015/consensus/decisions/123"
```

**Response:**
```json
{
  "status": "success",
  "decision": {
    "id": 123,
    "symbol": "BTC/USDT",
    "signal_type": "BUY",
    "consensus_pct": 85.5,
    "strategy_count": 3,
    "votes": {
      "strategies": [...],
      "ai": {...},
      "sentiment": {...}
    },
    "original_signals": [
      {
        "id": 12345,
        "strategy_name": "RSI Momentum",
        "quality_score": 92,
        "generated_at": "2026-02-26T16:29:45Z"
      }
    ],
    "position_id": 789,
    "actual_entry_price": 43255.00,
    "exit_price": 44250.00,
    "realized_pnl_pct": 2.3,
    "trade_result": "win",
    "entry_time": "2026-02-26T16:30:20Z",
    "exit_time": "2026-02-26T18:45:00Z",
    "hold_duration_minutes": 135
  }
}
```

### 4. Get Consensus Stats

**GET** `/consensus/stats`

Returns aggregate statistics about consensus decisions over the last 7 days.

```bash
curl "http://localhost:8015/consensus/stats"
```

**Response:**
```json
{
  "status": "success",
  "stats": {
    "total_decisions": 245,
    "approved_count": 180,
    "executed_count": 165,
    "wins": 102,
    "losses": 58,
    "avg_consensus_pct": 72.5,
    "avg_strategy_count": 2.8,
    "avg_return": 1.15,
    "by_symbol": [
      {
        "symbol": "BTC/USDT",
        "decision_count": 45,
        "executed_count": 38,
        "avg_consensus": 75.2
      }
    ]
  }
}
```

## Use Cases

### 1. Review Recent Consensus Decisions

```bash
# See last 20 decisions
curl "http://localhost:8015/consensus/decisions"

# See only executed trades
curl "http://localhost:8015/consensus/decisions?executed_only=true&limit=10"
```

### 2. Analyze Decision Quality

Check which decisions led to wins vs losses:

```bash
# Get stats
curl "http://localhost:8015/consensus/stats"
```

### 3. Debug Why Signal Didn't Execute

Check if a signal reached consensus but wasn't approved:

```bash
# Filter to specific symbol (via response filtering)
curl "http://localhost:8015/consensus/decisions?limit=50" | jq '.decisions[] | select(.symbol == "ETH/USDT")'
```

### 4. Audit AI Vote Accuracy

Get detailed decision breakdown to see AI reasoning:

```bash
curl "http://localhost:8015/consensus/decisions/123"
```

Check `votes.ai.reasoning` against `trade_result` to analyze AI prediction accuracy.

### 5. After-Action Analysis Integration

The consensus decisions feed into the After-Action API for performance analysis:

```bash
# Trigger after-action analysis
curl -X POST "http://localhost:8018/analyze" -H "Content-Type: application/json" -d '{
  "mode": "consensus",
  "period_hours": 24
}'
```

## Celery Tasks

### Regular Consensus (Every 5 Minutes)

**Task:** `execute_consensus_ensemble_trades`
- Supermajority: 60%
- Min strategies: 2
- Includes AI vote (1.5x weight)
- Includes sentiment (1.0x weight)
- Records all decisions to database

### Expedited Exceptional (Every 60 Seconds)

**Task:** `monitor_exceptional_signals`
- Supermajority: 70%
- Filters to 80%+ final consensus
- Requires 85+ quality score
- For high-conviction quick execution
- Also records decisions to database

## Database Queries

### Find High-Consensus Wins

```sql
SELECT 
    symbol, 
    consensus_pct, 
    realized_pnl_pct,
    votes->'ai'->>'vote' as ai_vote,
    votes->'sentiment'->>'score' as sentiment_score
FROM consensus_decisions
WHERE executed = true
  AND trade_outcome = 'win'
  AND consensus_pct >= 80
ORDER BY realized_pnl_pct DESC
LIMIT 10;
```

### Analyze AI Vote Accuracy

```sql
SELECT 
    votes->'ai'->>'vote' as ai_vote,
    COUNT(*) as total,
    COUNT(*) FILTER (WHERE trade_outcome = 'win') as wins,
    AVG(realized_pnl_pct) as avg_return
FROM consensus_decisions
WHERE executed = true
  AND trade_outcome IN ('win', 'loss')
GROUP BY votes->'ai'->>'vote';
```

### Find Sentiment Score Impact

```sql
SELECT 
    CASE 
        WHEN (votes->'sentiment'->>'score')::numeric >= 70 THEN 'Bullish (70+)'
        WHEN (votes->'sentiment'->>'score')::numeric >= 50 THEN 'Neutral (50-70)'
        ELSE 'Bearish (<50)'
    END as sentiment_range,
    COUNT(*) as decisions,
    AVG(realized_pnl_pct) as avg_return,
    COUNT(*) FILTER (WHERE trade_outcome = 'win') * 100.0 / COUNT(*) as win_rate
FROM consensus_decisions
WHERE executed = true
  AND votes->'sentiment' IS NOT NULL
GROUP BY sentiment_range
ORDER BY avg_return DESC;
```

## Monitoring & Logs

### Check Celery Logs for Decision Recording

```bash
tail -f logs/celery_worker.log | grep -E "consensus_decision_recorded|expedited_decision_recorded"
```

### View Signal API Logs for Consensus Evaluation

```bash
tail -f logs/signal_api.log | grep -E "consensus_signals_generated|ai_vote_received|sentiment_received"
```

## Integration with After-Action API

Consensus decisions are designed to integrate with the After-Action API:

1. **Decisions are recorded** with full context (voting, strategies, AI reasoning)
2. **Position outcomes** are linked via `position_id`
3. **After-action analysis** can query consensus data to:
   - Identify patterns in winning consensus decisions
   - Analyze which strategies vote most accurately
   - Measure AI vote accuracy over time
   - Correlate sentiment scores with outcomes

Future enhancement: Automatic after-action analysis of consensus performance trends.

## Configuration

### AI API Settings

```python
# shared/config.py
port_ai_api: int = 8011
anthropic_api_key: str = env("ANTHROPIC_API_KEY")
```

**Model:** `claude-3-haiku-20240307` (fastest model for voting/sentiment)

**Rate Limits:**
- 50 requests/minute
- 50,000 input tokens/minute
- 10,000 output tokens/minute

### Consensus Thresholds

**Regular Consensus (5-minute cycle):**
- Min strategies: 2
- Supermajority: 60%

**Expedited Consensus (60-second cycle):**
- Min strategies: 2
- Supermajority: 70%
- Final consensus filter: 80%+
- Quality filter: 85+

**Vote Weights:**
- Strategy: 0.5x to 1.5x (based on win rate)
- AI: 1.5x multiplier
- Sentiment: 1.0x multiplier

## Troubleshooting

### No AI Votes Appearing

Check AI API is running:
```bash
curl http://localhost:8011/health
```

Check logs for errors:
```bash
tail -f logs/ai_api.log
```

### No Sentiment Data

Sentiment requires internet access to fetch RSS feeds. Check network connectivity and logs:
```bash
tail -f logs/ai_api.log | grep sentiment
```

### Decisions Not Being Recorded

Check Celery worker logs:
```bash
tail -f logs/celery_worker.log | grep decision_record
```

Verify Signal API is accepting records:
```bash
curl -X POST http://localhost:8015/consensus/record -H "Content-Type: application/json" -d '{...test data...}'
```

## Summary

The consensus transparency system provides:

✅ **Full visibility** into every consensus decision  
✅ **Detailed voting breakdown** (strategies, AI, sentiment)  
✅ **Trade outcome tracking** linked to decisions  
✅ **Statistical analysis** of consensus performance  
✅ **After-action integration** for learning and improvement  
✅ **Audit trail** for regulatory compliance or debugging  

All consensus decisions are preserved forever in the database, allowing historical analysis of what worked and what didn't.
