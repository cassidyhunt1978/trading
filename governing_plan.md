# Clean Crypto Trading System - Complete Implementation Guide

**Target Deployment:** Fresh Linux container  
**Access:** http://localhost:8010/ (local) | https://www.cassidyhunt.net/trading (public)  | http://172.16.1.92:8010
**Philosophy:** Day trader mindset - focus on daily gains, celebrate monthly success

---

## Table of Contents
1. [System Overview](#system-overview)
2. [Service Architecture](#service-architecture)
3. [Technology Stack](#technology-stack)
4. [Database Schema](#database-schema)
5. [API Specifications](#api-specifications)
6. [Implementation Guide](#implementation-guide)
7. [Testing Strategy](#testing-strategy)
8. [Deployment Instructions](#deployment-instructions)

---

## System Overview

**Goal:** Automated crypto trading system that achieves 0.05% daily profit through:
- AI-powered symbol and strategy discovery
- Rigorous backtesting with realistic fee accounting
- Multi-method parameter optimization
- Real-time signal generation with sentiment analysis
- Dynamic portfolio rebalancing toward best opportunities
- Continuous learning from trades (wins and losses)

**Trading Philosophy:**
- Day trader approach: hourly/daily/weekly focus
- Always have capital deployed (no idle cash)
- Rotate to better opportunities quickly
- Strong signal + short timeframe = 80% allocation
- Monitor velocity: if position stagnates, rotate out

---

## Service Architecture

### Core Services (8 Independent APIs)

```
┌─────────────────────────────────────────────────────────────┐
│                         AI API (Port 8011)                   │
│  Discovery | Optimization | Sentiment | Validation | Why     │
└─────────────────────────────────────────────────────────────┘
                              ↓ ↑
┌─────────────────────────────────────────────────────────────┐
│                      OHLCV API (Port 8012)                   │
│      1-min Candles | Timeframe Aggregation | Indicators      │
└─────────────────────────────────────────────────────────────┘
                              ↓ ↑
┌─────────────────────────────────────────────────────────────┐
│                   Backtesting API (Port 8013)                │
│    Historical Sim | Perfect Strategy | Fee Calculator        │
└─────────────────────────────────────────────────────────────┘
                              ↓ ↑
┌─────────────────────────────────────────────────────────────┐
│                  Optimization API (Port 8014)                │
│   Bayesian | Genetic | Walk-Forward | Velocity Tuning        │
└─────────────────────────────────────────────────────────────┘
                              ↓ ↑
┌─────────────────────────────────────────────────────────────┐
│                     Signal API (Port 8015)                   │
│   Real-time Monitoring | Quality Scoring | Ranked List       │
└─────────────────────────────────────────────────────────────┘
                              ↓ ↑
┌─────────────────────────────────────────────────────────────┐
│                   Portfolio API (Port 8016)                  │
│   Position Sizing | Rotation | 0.05% Daily Target            │
└─────────────────────────────────────────────────────────────┘
                              ↓ ↑
┌─────────────────────────────────────────────────────────────┐
│                    Trading API (Port 8017)                   │
│      Paper/Live Execution | Ledger | Account Summary         │
└─────────────────────────────────────────────────────────────┘
                              ↓ ↑
┌─────────────────────────────────────────────────────────────┐
│                  AfterAction API (Port 8018)                 │
│   Twice Daily | Missed Opportunities | Regime Detection      │
└─────────────────────────────────────────────────────────────┘

        Supporting Infrastructure
┌──────────────────────┬──────────────────────┬────────────────┐
│   Database API       │   Celery/Redis       │  Testing API   │
│   PostgreSQL         │   Task Scheduler     │  Dummy Data    │
│   TimescaleDB        │   Task Monitoring    │  Health Score  │
└──────────────────────┴──────────────────────┴────────────────┘
```

---

## Technology Stack

### Backend
- **Framework:** FastAPI (Python 3.12+)
- **Database:** PostgreSQL 16 with TimescaleDB extension (time-series optimization)
- **Task Queue:** Celery with Redis backend
- **Caching:** Redis (hot data: latest prices, signals)
- **AI Integration:** 
  - Claude 3.5 Sonnet API (primary reasoning)
  - OpenAI GPT-4 (backup/comparison)
  - Anthropic SDK for Claude, OpenAI SDK for GPT
- **Sentiment Analysis:** 
  - NewsAPI for articles
  - Reddit API (PRAW) for social buzz
  - Twitter/X API for trending topics
  - VADER sentiment scoring
- **Technical Analysis:** TA-Lib or pandas-ta
- **Optimization:** 
  - scikit-optimize (Bayesian)
  - DEAP (genetic algorithms)
  - Custom walk-forward implementation

### Frontend
- **Core:** Vanilla JavaScript (ES6 modules), HTML5
- **Styling:** Tailwind CSS
- **Charts:** Chart.js with zoom/pan plugins
- **HTTP:** Fetch API
- **Responsive:** Mobile-first design (phone, tablet, desktop, TV)

### Deployment
- **Containerization:** Docker + Docker Compose
- **Reverse Proxy:** Nginx (handles HTTPS, routes to services)
- **Process Management:** systemd (optional, for non-Docker deployment)
- **Monitoring:** Prometheus + Grafana (optional, but recommended)

---

## Database Schema

### Core Tables

```sql
-- =================================================================
-- OHLCV Data (with TimescaleDB hypertable for performance)
-- =================================================================
CREATE TABLE ohlcv_candles (
    id BIGSERIAL,
    symbol TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    open NUMERIC(20, 8) NOT NULL,
    high NUMERIC(20, 8) NOT NULL,
    low NUMERIC(20, 8) NOT NULL,
    close NUMERIC(20, 8) NOT NULL,
    volume NUMERIC(20, 4) NOT NULL,
    indicators JSONB,  -- Pre-computed indicators added as they're discovered
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (symbol, timestamp)
);

-- Convert to TimescaleDB hypertable (automatic partitioning by time)
SELECT create_hypertable('ohlcv_candles', 'timestamp', 
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

-- Retention policy: auto-delete old data
SELECT add_retention_policy('ohlcv_candles', INTERVAL '30 days');

CREATE INDEX idx_ohlcv_symbol ON ohlcv_candles(symbol);
CREATE INDEX idx_ohlcv_indicators ON ohlcv_candles USING gin(indicators);

-- =================================================================
-- Symbols (Active coins being traded)
-- =================================================================
CREATE TABLE symbols (
    id SERIAL PRIMARY KEY,
    symbol TEXT UNIQUE NOT NULL,
    name TEXT,
    exchange TEXT DEFAULT 'kraken',
    status TEXT DEFAULT 'active',  -- active, paused, delisted
    market_cap_usd NUMERIC(20, 2),
    volume_24h_usd NUMERIC(20, 2),
    buzz_score INTEGER DEFAULT 0,  -- 0-100 from AI sentiment
    added_at TIMESTAMPTZ DEFAULT NOW(),
    last_candle_at TIMESTAMPTZ,
    metadata JSONB  -- {reddit_mentions, news_articles, twitter_trending}
);

CREATE INDEX idx_symbols_status ON symbols(status);
CREATE INDEX idx_symbols_buzz ON symbols(buzz_score DESC);

-- =================================================================
-- Strategies (Indicator combinations and logic)
-- =================================================================
CREATE TABLE strategies (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    indicator_logic JSONB NOT NULL,  
    /* Example:
    {
      "buy_conditions": [
        {"indicator": "VWAP", "operator": "crosses_above", "compare_to": "RSI"},
        {"indicator": "close", "operator": ">", "compare_to": "previous_close"}
      ],
      "sell_conditions": [
        {"indicator": "RSI", "operator": ">", "value": 70}
      ],
      "required_indicators": ["VWAP", "RSI", "close", "previous_close"]
    }
    */
    parameters JSONB NOT NULL,  -- {RSI_period: 14, VWAP_period: 20, ...}
    risk_management JSONB,  -- {stop_loss_pct: 2.0, take_profit_pct: 5.0, max_hold_minutes: 240}
    created_by TEXT DEFAULT 'AI',  -- 'AI' or 'human'
    enabled BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- =================================================================
-- Backtests (Historical performance of strategies)
-- =================================================================
CREATE TABLE backtests (
    id SERIAL PRIMARY KEY,
    strategy_id INTEGER REFERENCES strategies(id),
    symbol TEXT NOT NULL,
    start_date TIMESTAMPTZ NOT NULL,
    end_date TIMESTAMPTZ NOT NULL,
    starting_capital NUMERIC(20, 8) NOT NULL,
    ending_capital NUMERIC(20, 8),
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    losing_trades INTEGER DEFAULT 0,
    win_rate NUMERIC(5, 2),
    total_return_pct NUMERIC(10, 4),
    max_drawdown_pct NUMERIC(10, 4),
    sharpe_ratio NUMERIC(10, 4),
    total_fees_paid NUMERIC(20, 8),
    perfect_strategy_return_pct NUMERIC(10, 4),  -- What could've been earned
    trades JSONB,  -- Array of all trades with entry/exit/fees
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_backtests_strategy ON backtests(strategy_id);
CREATE INDEX idx_backtests_symbol ON backtests(symbol);
CREATE INDEX idx_backtests_win_rate ON backtests(win_rate DESC);

-- =================================================================
-- Signals (Real-time buy/sell/hold signals)
-- =================================================================
CREATE TABLE signals (
    id SERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    strategy_id INTEGER REFERENCES strategies(id),
    signal_type TEXT NOT NULL,  -- BUY, SELL, HOLD
    quality_score INTEGER NOT NULL,  -- 0-100
    /* Quality components:
       - Backtest win rate: 0-30 points
       - Sentiment buzz: 0-25 points
       - Historical predictability: 0-20 points
       - AI intuition: 0-15 points
       - Real-time price action: 0-10 points
    */
    quality_breakdown JSONB,  -- {"backtest": 28, "sentiment": 20, ...}
    
    projected_return_pct NUMERIC(10, 4),
    projected_timeframe_minutes INTEGER,
    projected_trajectory TEXT,  -- 'vertical' (fast), 'diagonal' (steady), 'horizontal' (slow)
    velocity_score NUMERIC(10, 4),  -- Expected $/hour or %/hour
    
    price_at_signal NUMERIC(20, 8),
    sentiment_summary TEXT,  -- "Strong Reddit buzz, 5 positive news articles"
    ai_reasoning TEXT,  -- Why AI thinks this is a good/bad signal
    
    generated_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ,  -- Signals expire after X minutes
    acted_on BOOLEAN DEFAULT false
);

CREATE INDEX idx_signals_quality ON signals(quality_score DESC);
CREATE INDEX idx_signals_symbol ON signals(symbol);
CREATE INDEX idx_signals_active ON signals(acted_on, expires_at) WHERE NOT acted_on;

-- =================================================================
-- Positions (Open and closed trades)
-- =================================================================
CREATE TABLE positions (
    id SERIAL PRIMARY KEY,
    signal_id INTEGER REFERENCES signals(id),
    symbol TEXT NOT NULL,
    strategy_id INTEGER REFERENCES strategies(id),
    
    mode TEXT NOT NULL,  -- 'paper' or 'live'
    status TEXT NOT NULL,  -- 'open', 'closed', 'stopped_out'
    
    entry_price NUMERIC(20, 8) NOT NULL,
    entry_time TIMESTAMPTZ NOT NULL,
    entry_fee NUMERIC(20, 8),
    
    exit_price NUMERIC(20, 8),
    exit_time TIMESTAMPTZ,
    exit_fee NUMERIC(20, 8),
    
    quantity NUMERIC(20, 8) NOT NULL,
    capital_allocated NUMERIC(20, 8) NOT NULL,
    
    current_price NUMERIC(20, 8),  -- Updated in real-time
    current_pnl NUMERIC(20, 8),  -- Unrealized P&L
    current_pnl_pct NUMERIC(10, 4),
    
    realized_pnl NUMERIC(20, 8),  -- After close
    realized_pnl_pct NUMERIC(10, 4),
    
    stop_loss_price NUMERIC(20, 8),
    take_profit_price NUMERIC(20, 8),
    
    velocity_at_entry NUMERIC(10, 4),  -- Expected velocity
    current_velocity NUMERIC(10, 4),  -- Actual velocity
    velocity_threshold NUMERIC(10, 4),  -- Min acceptable velocity
    
    minutes_held INTEGER,
    max_hold_minutes INTEGER,
    
    trade_result TEXT,  -- 'win', 'loss', 'draw', 'stopped_out', 'rotated'
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_positions_status ON positions(status);
CREATE INDEX idx_positions_symbol ON positions(symbol);
CREATE INDEX idx_positions_mode ON positions(mode);

-- =================================================================
-- Portfolio State (Snapshot of portfolio at any time)
-- =================================================================
CREATE TABLE portfolio_snapshots (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    mode TEXT NOT NULL,  -- 'paper' or 'live'
    
    total_capital NUMERIC(20, 8) NOT NULL,
    deployed_capital NUMERIC(20, 8) NOT NULL,  -- In positions
    available_capital NUMERIC(20, 8) NOT NULL,  -- Cash
    
    open_positions INTEGER DEFAULT 0,
    total_pnl NUMERIC(20, 8),
    total_pnl_pct NUMERIC(10, 4),
    
    daily_pnl NUMERIC(20, 8),
    daily_pnl_pct NUMERIC(10, 4),
    
    daily_target_met BOOLEAN DEFAULT false,  -- Hit 0.05% today?
    consecutive_days_target_met INTEGER DEFAULT 0,
    
    positions_snapshot JSONB  -- Array of current positions
);

CREATE INDEX idx_portfolio_timestamp ON portfolio_snapshots(timestamp DESC);
CREATE INDEX idx_portfolio_mode ON portfolio_snapshots(mode);

-- =================================================================
-- AfterAction Reports (Twice daily analysis)
-- =================================================================
CREATE TABLE afteraction_reports (
    id SERIAL PRIMARY KEY,
    report_date DATE NOT NULL,
    report_time TEXT NOT NULL,  -- 'midday' or 'eod'
    
    trades_analyzed INTEGER,
    wins INTEGER,
    losses INTEGER,
    draws INTEGER,
    
    missed_opportunities JSONB,  
    /* {
        symbol: 'BTC',
        reason: 'Signal quality threshold not met (68/100)',
        potential_profit_pct: 3.2,
        what_we_learned: 'Lower quality threshold for high-volume coins'
    } */
    
    false_signals JSONB,
    /* {
        symbol: 'ETH',
        strategy_id: 5,
        why_false: 'Sentiment was stale, news broke after signal',
        prevention: 'Add real-time news freshness check'
    } */
    
    regime_changes JSONB,
    /* {
        detected: 'Transition from bullish to bearish regime',
        indicators: ['Decreasing volume', 'Lower highs', 'Sentiment shift'],
        recommendation: 'Pause aggressive strategies, increase stop-loss tightness'
    } */
    
    trading_logic_flaws JSONB,
    
    recommendations JSONB,
    /* Actionable changes:
       - Adjust strategy parameters
       - Pause underperforming strategies
       - Add new indicators
       - Change quality thresholds
    */
    
    auto_applied BOOLEAN DEFAULT false,  -- Did system auto-apply recommendations?
    human_review_required BOOLEAN DEFAULT false,
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_afteraction_date ON afteraction_reports(report_date DESC);

-- =================================================================
-- System Health (API status, task status, data freshness)
-- =================================================================
CREATE TABLE system_health (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    
    api_statuses JSONB NOT NULL,
    /* {
        "ai_api": {"status": "healthy", "response_time_ms": 245},
        "ohlcv_api": {"status": "healthy", "response_time_ms": 12},
        ...
    } */
    
    celery_task_statuses JSONB NOT NULL,
    /* {
        "fetch_1min_candles": {"last_run": "2026-02-17T10:05:00Z", "status": "success"},
        "generate_signals": {"last_run": "2026-02-17T10:05:15Z", "status": "success"},
        ...
    } */
    
    data_freshness JSONB,
    /* {
        "BTC": {"last_candle": "2026-02-17T10:04:00Z", "age_seconds": 45},
        ...
    } */
    
    overall_health_score INTEGER,  -- 0-100
    issues JSONB  -- Array of current problems
);

CREATE INDEX idx_health_timestamp ON system_health(timestamp DESC);
```

---

## API Specifications

### 1. AI API (Port 8011)

**Responsibilities:**
- Discover symbols by scanning Kraken + analyzing internet buzz
- Discover/suggest indicator combinations
- Validate signals using AI "intuition" (sentiment + pattern recognition)
- Optimize strategy parameters via ML-assisted search
- Explain "why" behind signals (human-readable reasoning)

**Key Endpoints:**

```python
POST /ai/discover-symbols
# Scans Kraken for new symbols + scrapes Reddit/Twitter/News for buzz
# Returns: [{"symbol": "DOGE", "buzz_score": 85, "mentions": 1240, "reasoning": "..."}]

POST /ai/suggest-indicators
# Given: {symbol, recent_performance, market_conditions}
# Returns: Recommended indicators and logic
# Example: {"indicators": ["VWAP", "RSI"], "logic": "VWAP crosses above RSI", "confidence": 0.82}

POST /ai/validate-signal
# Given: {symbol, strategy, technical_signal_quality, current_price_action}
# Returns: {intuition_boost: +15, reasoning: "GameStop-like Reddit momentum detected", confidence: 0.88}

POST /ai/optimize-parameters
# Given: {strategy_id, symbol, parameter_ranges}
# Uses Claude to suggest promising parameter combinations, then tests them
# Returns: {optimized_params: {RSI_period: 12, VWAP_period: 18}, expected_improvement_pct: 2.3}

POST /ai/explain-signal
# Given: {signal_id}
# Returns: Human-readable explanation: "This BUY signal fired because VWAP crossed above RSI (bullish),
#          Reddit mentions increased 300% in last hour (GameStop-like pattern), 
#          and historical win rate for this pattern is 78%"
```

**Implementation Notes:**
- Use Anthropic Claude 3.5 Sonnet via API (primary)
- OpenAI GPT-4 as fallback/comparison
- Cache AI responses for 5 minutes (same question = same answer)
- Implement retry logic with exponential backoff
- Rate limit: respect API provider limits (Claude: 5 req/min, GPT-4: 10 req/min)

**Sentiment Data Sources:**
```python
# Reddit
import praw
reddit = praw.Reddit(client_id='...', client_secret='...', user_agent='...')
subreddit = reddit.subreddit('CryptoCurrency+Bitcoin+ethtrader')
hot_posts = subreddit.hot(limit=100)
# Count symbol mentions, analyze post sentiment

# News
from newsapi import NewsApiClient
newsapi = NewsApiClient(api_key='...')
articles = newsapi.get_everything(q='Bitcoin', language='en', sort_by='publishedAt')
# Analyze article titles/descriptions with VADER sentiment

# Twitter/X
import tweepy
client = tweepy.Client(bearer_token='...')
tweets = client.search_recent_tweets(query='$BTC OR #Bitcoin', max_results=100)
# Count mentions, analyze sentiment
```

---

### 2. OHLCV API (Port 8012)

**Responsibilities:**
- Fetch 1-minute candles from Kraken every minute
- Store in TimescaleDB with automatic partitioning
- Aggregate to any timeframe on-demand (5m, 15m, 1h, 4h, 1d)
- Pre-compute indicators as they're discovered by AI
- Maintain list of active symbols
- Backfill historical candles for new symbols

**Key Endpoints:**

```python
GET /ohlcv/candles?symbol=BTC&timeframe=1m&start=2026-02-01&end=2026-02-17
# Returns: OHLCV candles with pre-computed indicators
# Response: [
#   {
#     "timestamp": "2026-02-17T10:00:00Z",
#     "open": 50000.00,
#     "high": 50100.00,
#     "low": 49950.00,
#     "close": 50050.00,
#     "volume": 123.45,
#     "indicators": {
#       "RSI_14": 62.3,
#       "MACD_12_26_9": {"macd": 120.5, "signal": 115.2, "histogram": 5.3},
#       "VWAP": 50025.00
#     }
#   },
#   ...
# ]

POST /ohlcv/add-symbol
# Body: {symbol: 'DOGE', exchange: 'kraken'}
# Adds symbol to tracking list, kicks off historical backfill
# Returns: {status: 'added', backfill_started: true, estimated_completion: '2026-02-17T10:15:00Z'}

POST /ohlcv/add-indicator
# Body: {indicator_name: 'BBANDS', parameters: {period: 20, std: 2}}
# AI discovered new indicator, start computing for all candles
# Returns: {status: 'computing', affected_symbols: 37, eta: '5 minutes'}

GET /ohlcv/symbols
# Returns: [{symbol: 'BTC', status: 'active', last_candle_at: '2026-02-17T10:04:00Z', ...}]
```

**Implementation Notes:**
```python
# Celery task: runs every 1 minute
@celery_app.task
def fetch_1min_candles():
    """Fetch latest 1-minute candle for all active symbols"""
    symbols = get_active_symbols()  # From database
    
    for symbol in symbols:
        try:
            # Kraken OHLC endpoint
            candle = fetch_kraken_ohlc(symbol, interval=1, count=1)
            
            # Compute all active indicators for this candle
            indicators = compute_indicators(symbol, candle)
            
            # Store in database
            save_candle(symbol, candle, indicators)
            
        except Exception as e:
            logger.error(f"Failed to fetch {symbol}: {e}")
            # Alert if data is stale (> 5 minutes old)
            check_data_staleness(symbol)

def compute_indicators(symbol, candle):
    """Compute all indicators that AI has discovered"""
    # Get last 200 candles (most indicators need history)
    recent_candles = get_recent_candles(symbol, limit=200)
    recent_candles.append(candle)
    
    df = pd.DataFrame(recent_candles)
    
    indicators = {}
    
    # Get active indicator list from database
    active_indicators = get_active_indicators()
    
    for ind in active_indicators:
        if ind['name'] == 'RSI':
            indicators['RSI_' + str(ind['period'])] = talib.RSI(df['close'], timeperiod=ind['period'])[-1]
        
        elif ind['name'] == 'MACD':
            macd, signal, hist = talib.MACD(df['close'], 
                                           fastperiod=ind['fast'],
                                           slowperiod=ind['slow'],
                                           signalperiod=ind['signal'])
            indicators[f"MACD_{ind['fast']}_{ind['slow']}_{ind['signal']}"] = {
                'macd': macd[-1],
                'signal': signal[-1],
                'histogram': hist[-1]
            }
        
        # ... add more as AI discovers them
    
    return indicators
```

---

### 3. Backtesting API (Port 8013)

**Responsibilities:**
- Run strategy against historical OHLCV data
- Calculate realistic fees (Kraken: 0.16% maker, 0.26% taker)
- Compute "perfect strategy" benchmark (buy every low, sell every high)
- Generate detailed trade log
- Calculate performance metrics (win rate, Sharpe ratio, max drawdown)
- Save results to database

**Key Endpoints:**

```python
POST /backtest/run
# Body: {
#   strategy_id: 5,
#   symbol: 'BTC',
#   start_date: '2026-01-01',
#   end_date: '2026-02-01',
#   starting_capital: 10000,
#   use_perfect_benchmark: true
# }
# Returns: {
#   backtest_id: 1234,
#   total_trades: 45,
#   win_rate: 62.2,
#   total_return_pct: 8.7,
#   ending_capital: 10870.00,
#   total_fees_paid: 127.40,
#   perfect_strategy_return_pct: 24.3,  # What could've been
#   efficiency_ratio: 0.358  # 8.7 / 24.3 = how close to perfect
# }

GET /backtest/results/{backtest_id}
# Returns: Full backtest details including all trades
# {
#   backtest_id: 1234,
#   strategy: {...},
#   summary: {...},
#   trades: [
#     {
#       entry_time: '2026-01-05T10:23:00Z',
#       entry_price: 45000.00,
#       exit_time: '2026-01-05T14:17:00Z',
#       exit_price: 45900.00,
#       pnl_pct: 2.0,
#       pnl_after_fees: 1.58,
#       fees_paid: 18.90,
#       hold_minutes: 234,
#       result: 'win'
#     },
#     ...
#   ],
#   perfect_strategy_trades: [...],  # For comparison
#   charts: {
#     equity_curve: [...],
#     drawdown: [...],
#     win_loss_distribution: [...]
#   }
# }

POST /backtest/compare-strategies
# Body: {strategy_ids: [1, 5, 12], symbol: 'BTC', start_date: '...', end_date: '...'}
# Returns: Side-by-side comparison of multiple strategies
```

**Implementation Notes:**
```python
class Backtester:
    def __init__(self, strategy, symbol, start_date, end_date, starting_capital):
        self.strategy = strategy
        self.symbol = symbol
        self.start_date = start_date
        self.end_date = end_date
        self.capital = starting_capital
        self.position = None
        self.trades = []
        self.fees_paid = 0
        
        # Kraken fees
        self.maker_fee_pct = 0.16 / 100  # Limit orders
        self.taker_fee_pct = 0.26 / 100  # Market orders
        
    def run(self):
        # Fetch OHLCV data from OHLCV API
        candles = fetch_candles(self.symbol, self.start_date, self.end_date, timeframe='1m')
        
        # Evaluate strategy on each candle
        for candle in candles:
            signal = self.evaluate_strategy(candle)
            
            if signal == 'BUY' and self.position is None:
                self.enter_position(candle)
            
            elif signal == 'SELL' and self.position is not None:
                self.exit_position(candle)
            
            # Check stop-loss / take-profit
            if self.position:
                self.check_risk_management(candle)
        
        # Close any open position at end
        if self.position:
            self.exit_position(candles[-1], reason='backtest_end')
        
        # Calculate metrics
        results = self.calculate_metrics()
        
        # Calculate perfect strategy benchmark
        perfect_results = self.calculate_perfect_strategy(candles)
        results['perfect_strategy_return_pct'] = perfect_results['return_pct']
        results['efficiency_ratio'] = results['total_return_pct'] / perfect_results['return_pct']
        
        # Save to database
        backtest_id = self.save_results(results)
        
        return results
    
    def evaluate_strategy(self, candle):
        """Evaluate strategy indicator logic"""
        # Parse strategy.indicator_logic
        # Example: VWAP crosses above RSI
        
        indicators = candle['indicators']
        
        for condition in self.strategy['buy_conditions']:
            if not self.check_condition(condition, indicators):
                return 'HOLD'
        
        # All buy conditions met
        return 'BUY'
        
        # (similar for sell_conditions)
    
    def enter_position(self, candle):
        entry_price = candle['close']
        fee = self.capital * self.taker_fee_pct  # Assume market order (taker)
        quantity = (self.capital - fee) / entry_price
        
        self.position = {
            'entry_time': candle['timestamp'],
            'entry_price': entry_price,
            'quantity': quantity,
            'entry_fee': fee,
            'stop_loss': entry_price * (1 - self.strategy['risk_management']['stop_loss_pct'] / 100),
            'take_profit': entry_price * (1 + self.strategy['risk_management']['take_profit_pct'] / 100)
        }
        
        self.fees_paid += fee
        self.capital -= (quantity * entry_price + fee)
    
    def exit_position(self, candle, reason='signal'):
        exit_price = candle['close']
        proceeds = self.position['quantity'] * exit_price
        fee = proceeds * self.taker_fee_pct
        
        net_proceeds = proceeds - fee
        self.capital += net_proceeds
        self.fees_paid += fee
        
        pnl = net_proceeds - (self.position['quantity'] * self.position['entry_price'])
        pnl_pct = (pnl / (self.position['quantity'] * self.position['entry_price'])) * 100
        
        trade = {
            'entry_time': self.position['entry_time'],
            'entry_price': self.position['entry_price'],
            'exit_time': candle['timestamp'],
            'exit_price': exit_price,
            'quantity': self.position['quantity'],
            'entry_fee': self.position['entry_fee'],
            'exit_fee': fee,
            'pnl': pnl,
            'pnl_pct': pnl_pct,
            'hold_minutes': (candle['timestamp'] - self.position['entry_time']).total_seconds() / 60,
            'result': 'win' if pnl > 0 else 'loss' if pnl < 0 else 'draw',
            'exit_reason': reason
        }
        
        self.trades.append(trade)
        self.position = None
    
    def calculate_perfect_strategy(self, candles):
        """Calculate what profit would be if you bought every local min, sold every local max"""
        # Find all local minimums and maximums
        lows = find_local_minima(candles)
        highs = find_local_maxima(candles)
        
        # Pair them up (buy low, sell high)
        perfect_trades = pair_min_max(lows, highs)
        
        # Calculate profit with same fee structure
        capital = self.starting_capital
        for trade in perfect_trades:
            # Simulate buying at low
            fee = capital * self.taker_fee_pct
            quantity = (capital - fee) / trade['low_price']
            
            # Simulate selling at high
            proceeds = quantity * trade['high_price']
            exit_fee = proceeds * self.taker_fee_pct
            capital = proceeds - exit_fee
        
        return {
            'ending_capital': capital,
            'return_pct': ((capital - self.starting_capital) / self.starting_capital) * 100,
            'num_trades': len(perfect_trades)
        }
```

---

### 4. Optimization API (Port 8014)

**Responsibilities:**
- Optimize strategy parameters using Bayesian, genetic, and walk-forward methods
- Set profit trajectory and velocity thresholds based on optimization
- Determine optimal stop-loss and max hold time
- Calculate "velocity without profit" threshold (when to rotate out)

**Key Endpoints:**

```python
POST /optimize/bayesian
# Body: {
#   strategy_id: 5,
#   symbol: 'BTC',
#   parameter_ranges: {
#     RSI_period: [10, 20],
#     VWAP_period: [15, 30],
#     stop_loss_pct: [1.0, 5.0]
#   },
#   optimization_target: 'sharpe_ratio',  # or 'total_return', 'win_rate'
#   max_iterations: 50
# }
# Uses scikit-optimize to intelligently search parameter space
# Returns: {
#   best_params: {RSI_period: 14, VWAP_period: 22, stop_loss_pct: 2.5},
#   best_score: 1.82,  # Sharpe ratio
#   iterations: 50,
#   improvement_over_baseline: 0.34
# }

POST /optimize/genetic
# Similar to Bayesian but uses genetic algorithm (DEAP library)
# Better for complex multi-parameter strategies

POST /optimize/walk-forward
# Body: {
#   strategy_id: 5,
#   symbol: 'BTC',
#   in_sample_days: 30,  # Train on 30 days
#   out_sample_days: 7,  # Test on next 7 days
#   total_period_days: 180,
#   optimization_method: 'bayesian'
# }
# Splits time into windows: train → test → train → test...
# Returns average performance across all out-of-sample periods
# This prevents overfitting!

POST /optimize/velocity-thresholds
# Body: {strategy_id: 5, symbol: 'BTC', backtest_results: [...]}
# Analyzes winning trades to determine optimal velocity thresholds
# Returns: {
#   expected_velocity: 0.5,  # %/hour
#   min_acceptable_velocity: 0.2,  # Below this = rotate out
#   max_hold_without_velocity_minutes: 30  # If no velocity for 30 min, exit
# }

GET /optimize/results/{optimization_id}
# Returns: Full optimization results with parameter convergence charts
```

**Implementation Notes:**
```python
from skopt import gp_minimize
from skopt.space import Real, Integer

def bayesian_optimize(strategy_id, symbol, parameter_ranges, target, max_iterations):
    """Use Bayesian optimization to find best parameters"""
    
    # Define search space
    space = []
    param_names = []
    for param, range_values in parameter_ranges.items():
        param_names.append(param)
        if isinstance(range_values[0], int):
            space.append(Integer(range_values[0], range_values[1], name=param))
        else:
            space.append(Real(range_values[0], range_values[1], name=param))
    
    # Objective function: run backtest and return negative score (gp_minimize minimizes)
    def objective(params):
        param_dict = dict(zip(param_names, params))
        
        # Update strategy with these parameters
        strategy = get_strategy(strategy_id)
        strategy['parameters'].update(param_dict)
        
        # Run backtest
        backtest_results = run_backtest(strategy, symbol, start_date, end_date)
        
        # Return negative score (we want to maximize, but gp_minimize minimizes)
        if target == 'sharpe_ratio':
            return -backtest_results['sharpe_ratio']
        elif target == 'total_return':
            return -backtest_results['total_return_pct']
        elif target == 'win_rate':
            return -backtest_results['win_rate']
    
    # Run optimization
    result = gp_minimize(objective, space, n_calls=max_iterations, random_state=42)
    
    best_params = dict(zip(param_names, result.x))
    best_score = -result.fun  # Convert back to positive
    
    return {
        'best_params': best_params,
        'best_score': best_score,
        'iterations': max_iterations,
        'convergence_history': [-y for y in result.func_vals]  # For charting
    }

def calculate_velocity_thresholds(backtest_results):
    """Analyze winning trades to set velocity expectations"""
    winning_trades = [t for t in backtest_results['trades'] if t['result'] == 'win']
    
    velocities = []
    for trade in winning_trades:
        # Velocity = % gain per hour
        pnl_pct = trade['pnl_pct']
        minutes_held = trade['hold_minutes']
        velocity = (pnl_pct / minutes_held) * 60  # Convert to %/hour
        velocities.append(velocity)
    
    # Expected velocity = median of winning trades
    expected_velocity = np.median(velocities)
    
    # Min acceptable = 40% of expected (below this, position is underperforming)
    min_acceptable_velocity = expected_velocity * 0.4
    
    # Max hold without velocity = median hold time of winning trades
    max_hold_minutes = np.median([t['hold_minutes'] for t in winning_trades])
    
    return {
        'expected_velocity': expected_velocity,
        'min_acceptable_velocity': min_acceptable_velocity,
        'max_hold_without_velocity_minutes': max_hold_minutes
    }
```

---

### 5. Signal API (Port 8015)

**Responsibilities:**
- Monitor OHLCV data in real-time (every minute)
- Evaluate all active strategies against current market data
- Generate BUY/SELL/HOLD signals
- Score signal quality (0-100) based on multiple factors
- Calculate projected trajectory, velocity, and timeframe
- Fetch sentiment data (Reddit, Twitter, news) for each symbol
- Get AI "intuition" boost from AI API
- Maintain ranked list of active signals (sorted by quality × profitability × urgency)

**Key Endpoints:**

```python
GET /signals/active
# Returns: List of active signals sorted by ranking algorithm
# [
#   {
#     signal_id: 1234,
#     symbol: 'BTC',
#     signal_type: 'BUY',
#     quality_score: 87,
#     quality_breakdown: {
#       backtest_win_rate: 28,  # /30
#       sentiment_buzz: 23,  # /25
#       historical_predictability: 18,  # /20
#       ai_intuition: 12,  # /15
#       realtime_price_action: 6  # /10
#     },
#     projected_return_pct: 3.2,
#     projected_timeframe_minutes: 120,
#     projected_trajectory: 'vertical',  # fast profit expected
#     velocity_score: 0.96,  # %/hour
#     price_at_signal: 50100.00,
#     sentiment_summary: 'Strong Reddit buzz (340 mentions/hour), 3 positive news articles',
#     ai_reasoning: 'Pattern similar to previous 78% win-rate signals. GameStop-like momentum detected.',
#     generated_at: '2026-02-17T10:05:00Z',
#     expires_at: '2026-02-17T10:15:00Z'  # Signals expire after 10 minutes
#   },
#   ...
# ]

GET /signals/history?symbol=BTC&days=7
# Returns: Historical signals for analysis

POST /signals/manual-evaluation
# Body: {symbol: 'ETH'}
# Force immediate evaluation of one symbol (for testing/debugging)
```

**Implementation Notes:**
```python
# Celery task: runs every 1-2 minutes
@celery_app.task
def generate_signals():
    """Evaluate all strategies against current market data"""
    
    # Get all enabled strategies
    strategies = get_enabled_strategies()
    
    # Get all active symbols
    symbols = get_active_symbols()
    
    for symbol in symbols:
        for strategy in strategies:
            try:
                signal = evaluate_strategy_for_signal(symbol, strategy)
                
                if signal['type'] != 'HOLD':
                    # Calculate quality score
                    quality = calculate_signal_quality(symbol, strategy, signal)
                    
                    # Get AI intuition
                    ai_boost = get_ai_intuition(symbol, strategy, signal)
                    quality['ai_intuition'] = ai_boost
                    
                    # Calculate total quality score
                    total_quality = sum(quality.values())
                    
                    # Only create signal if quality > threshold (e.g., 60)
                    if total_quality >= 60:
                        create_signal(symbol, strategy, signal['type'], total_quality, quality, signal)
                
            except Exception as e:
                logger.error(f"Error evaluating {symbol} with strategy {strategy['id']}: {e}")

def calculate_signal_quality(symbol, strategy, signal):
    """Calculate quality score components (0-100 total)"""
    quality = {}
    
    # 1. Backtest win rate (0-30 points)
    recent_backtests = get_recent_backtests(strategy['id'], symbol, days=30)
    if recent_backtests:
        avg_win_rate = np.mean([b['win_rate'] for b in recent_backtests])
        quality['backtest_win_rate'] = min(30, int(avg_win_rate / 100 * 30))
    else:
        quality['backtest_win_rate'] = 0
    
    # 2. Sentiment buzz (0-25 points)
    sentiment = get_sentiment_data(symbol)
    buzz_score = sentiment['reddit_mentions'] / 100 * 10  # Reddit
    buzz_score += sentiment['news_count'] * 5  # News articles
    buzz_score += sentiment['twitter_trend'] / 100 * 10  # Twitter
    quality['sentiment_buzz'] = min(25, int(buzz_score))
    
    # 3. Historical predictability (0-20 points)
    # How often has this pattern led to profit in the past?
    similar_patterns = find_similar_historical_patterns(symbol, signal)
    if similar_patterns:
        success_rate = sum([1 for p in similar_patterns if p['profitable']]) / len(similar_patterns)
        quality['historical_predictability'] = int(success_rate * 20)
    else:
        quality['historical_predictability'] = 10  # Default
    
    # 4. AI intuition (0-15 points) - fetched from AI API
    # (This is a placeholder, will be replaced by AI API call)
    quality['ai_intuition'] = 0
    
    # 5. Real-time price action (0-10 points)
    # Is price moving in the direction we expect?
    recent_candles = get_recent_candles(symbol, limit=10)
    if signal['type'] == 'BUY':
        # Good if price is starting to move up
        price_momentum = calculate_momentum(recent_candles)
        quality['realtime_price_action'] = min(10, max(0, int(price_momentum * 100)))
    else:  # SELL
        price_momentum = calculate_momentum(recent_candles)
        quality['realtime_price_action'] = min(10, max(0, int(-price_momentum * 100)))
    
    return quality

def get_sentiment_data(symbol):
    """Fetch sentiment from Reddit, Twitter, NewsAPI"""
    sentiment = {
        'reddit_mentions': 0,
        'news_count': 0,
        'twitter_trend': 0,
        'summary': ''
    }
    
    # Reddit (PRAW)
    try:
        reddit = praw.Reddit(client_id='...', client_secret='...', user_agent='...')
        subreddit = reddit.subreddit('CryptoCurrency+Bitcoin+ethtrader')
        mentions = 0
        for post in subreddit.hot(limit=100):
            if symbol.upper() in post.title.upper() or symbol.upper() in (post.selftext or '').upper():
                mentions += 1
        sentiment['reddit_mentions'] = mentions
    except Exception as e:
        logger.error(f"Reddit API error: {e}")
    
    # News (NewsAPI)
    try:
        newsapi = NewsApiClient(api_key='...')
        articles = newsapi.get_everything(q=symbol, language='en', sort_by='publishedAt', page_size=100)
        sentiment['news_count'] = len(articles['articles'])
    except Exception as e:
        logger.error(f"NewsAPI error: {e}")
    
    # Twitter (Tweepy)
    try:
        client = tweepy.Client(bearer_token='...')
        tweets = client.search_recent_tweets(query=f'${symbol} OR #{symbol}', max_results=100)
        sentiment['twitter_trend'] = len(tweets.data) if tweets.data else 0
    except Exception as e:
        logger.error(f"Twitter API error: {e}")
    
    # Summary
    summary_parts = []
    if sentiment['reddit_mentions'] > 50:
        summary_parts.append(f"Strong Reddit buzz ({sentiment['reddit_mentions']} mentions/hour)")
    if sentiment['news_count'] > 3:
        summary_parts.append(f"{sentiment['news_count']} news articles")
    if sentiment['twitter_trend'] > 100:
        summary_parts.append(f"Trending on Twitter ({sentiment['twitter_trend']} tweets)")
    
    sentiment['summary'] = ', '.join(summary_parts) if summary_parts else 'Low buzz'
    
    return sentiment

def rank_signals(signals):
    """Sort signals by quality × expected_profit × urgency"""
    for signal in signals:
        # Ranking score = quality * expected_return * urgency_factor
        urgency_factor = 1.0
        if signal['projected_timeframe_minutes'] < 60:
            urgency_factor = 1.5  # Fast opportunities get boost
        elif signal['projected_timeframe_minutes'] > 240:
            urgency_factor = 0.7  # Slow opportunities get penalty
        
        signal['rank_score'] = (
            signal['quality_score'] * 
            signal['projected_return_pct'] * 
            urgency_factor
        )
    
    # Sort descending by rank_score
    signals.sort(key=lambda s: s['rank_score'], reverse=True)
    
    return signals
```

---

### 6. Portfolio API (Port 8016)

**Responsibilities:**
- Read ranked signal list from Signal API
- Decide position sizing based on signal quality + timeframe
- Strong signal (80+) + short timeframe (<2h) = 80% allocation
- Spread remaining 20% among other signals
- Monitor open positions in real-time
- Calculate velocity for each position
- Flag stagnant positions (velocity < threshold)
- Rotate capital from stagnant to better opportunities
- Ensure 100% capital deployment (always have positions)
- Track daily profit target (0.05%)
- After 3 consecutive days hitting target in paper mode, enable live trading

**Key Endpoints:**

```python
GET /portfolio/status?mode=paper
# Returns: Current portfolio state
# {
#   mode: 'paper',
#   total_capital: 10000.00,
#   deployed_capital: 9985.00,  # 99.85% deployed
#   available_capital: 15.00,
#   open_positions: 5,
#   positions: [
#     {
#       position_id: 1234,
#       symbol: 'BTC',
#       strategy_id: 5,
#       entry_price: 50000.00,
#       current_price: 50120.00,
#       pnl_pct: 0.24,
#       capital_allocated: 8000.00,  # 80% of portfolio
#       velocity: 0.48,  # %/hour
#       expected_velocity: 0.60,
#       velocity_status: 'healthy',  # 'healthy', 'warning', 'stagnant'
#       minutes_held: 45,
#       max_hold_minutes: 120
#     },
#     {
#       position_id: 1235,
#       symbol: 'ETH',
#       capital_allocated: 500.00,  # 5% of portfolio
#       velocity: 0.15,
#       expected_velocity: 0.50,
#       velocity_status: 'stagnant',  # CANDIDATE FOR ROTATION
#       ...
#     },
#     ...
#   ],
#   daily_pnl: 0.03,  # 0.03% today
#   daily_target_met: false,
#   consecutive_days_target_met: 0
# }

POST /portfolio/rebalance
# Triggered by Celery task every 5 minutes
# Checks for rotation opportunities:
#   - Close stagnant positions
#   - Take profits on positions at take_profit_pct
#   - Stop out losing positions at stop_loss_pct
#   - Open new positions from top-ranked signals
# Returns: {
#   actions_taken: [
#     {action: 'rotate_out', position_id: 1235, symbol: 'ETH', reason: 'stagnant velocity'},
#     {action: 'rotate_in', symbol: 'SOL', allocation_pct: 5, reason: 'high quality signal (85)'},
#     ...
#   ]
# }

GET /portfolio/performance?mode=paper&period=daily
# Returns: Performance metrics (hourly, daily, weekly, monthly, yearly)
# {
#   period: 'daily',
#   data: [
#     {date: '2026-02-17', pnl_pct: 0.08, target_met: true},
#     {date: '2026-02-16', pnl_pct: 0.06, target_met: true},
#     {date: '2026-02-15', pnl_pct: 0.04, target_met: false},
#     ...
#   ],
#   summary: {
#     avg_daily_pnl_pct: 0.05,
#     best_day: 0.12,
#     worst_day: -0.02,
#     win_rate: 71.4,
#     consecutive_target_days: 2
#   }
# }

POST /portfolio/enable-live-trading
# Manual override to enable live trading (after 3 days paper target met)
# Requires: consecutive_days_target_met >= 3
# Returns: {status: 'live_trading_enabled', warning: 'Real money at risk!'}
```

**Implementation Notes:**
```python
# Celery task: runs every 5 minutes
@celery_app.task
def rebalance_portfolio():
    """Check for rotation opportunities and rebalance portfolio"""
    
    modes = ['paper']  # Start with paper
    # After 3 consecutive days hitting target, add 'live'
    if check_ready_for_live():
        modes.append('live')
    
    for mode in modes:
        portfolio = get_portfolio_status(mode)
        actions = []
        
        # 1. Check for positions to close
        for position in portfolio['positions']:
            close_reason = should_close_position(position)
            
            if close_reason:
                close_position(position, reason=close_reason, mode=mode)
                actions.append({
                    'action': 'close',
                    'position_id': position['position_id'],
                    'symbol': position['symbol'],
                    'reason': close_reason
                })
        
        # 2. Get available capital (after closes)
        available_capital = calculate_available_capital(mode)
        
        # 3. Get top signals from Signal API
        signals = get_active_signals()  # Pre-sorted by rank
        
        # 4. Allocate capital to top signals
        for signal in signals:
            if available_capital < 10:  # Keep $10 minimum reserve
                break
            
            # Check if we already have a position in this symbol
            if has_open_position(signal['symbol'], mode):
                continue
            
            # Calculate allocation
            allocation = calculate_allocation(signal, available_capital)
            
            # Open position
            if allocation > 0:
                open_position(signal, allocation, mode)
                available_capital -= allocation
                actions.append({
                    'action': 'open',
                    'symbol': signal['symbol'],
                    'allocation': allocation,
                    'reason': f"High quality signal ({signal['quality_score']})"
                })
        
        # 5. Log actions
        log_portfolio_actions(mode, actions)
        
        # 6. Take snapshot
        save_portfolio_snapshot(mode)

def should_close_position(position):
    """Determine if position should be closed and why"""
    
    # Stop loss hit
    if position['current_price'] <= position['stop_loss_price']:
        return 'stop_loss'
    
    # Take profit hit
    if position['current_price'] >= position['take_profit_price']:
        return 'take_profit'
    
    # Stagnant velocity
    if position['velocity_status'] == 'stagnant':
        # Check if there's a better opportunity
        better_signal = get_better_signal_available(position)
        if better_signal:
            return 'rotate_to_better_opportunity'
    
    # Max hold time exceeded
    if position['minutes_held'] >= position['max_hold_minutes']:
        # Check if still profitable
        if position['pnl_pct'] > 0:
            return 'max_hold_time_take_profit'
        else:
            return 'max_hold_time_cut_loss'
    
    return None

def calculate_allocation(signal, available_capital):
    """Determine how much capital to allocate to this signal"""
    
    quality = signal['quality_score']
    timeframe = signal['projected_timeframe_minutes']
    
    # Strong signal (80+) + short timeframe (<120 min) = 80% of available
    if quality >= 80 and timeframe < 120:
        return available_capital * 0.80
    
    # Good signal (70-79) + medium timeframe (120-240 min) = 50% of available
    elif quality >= 70 and timeframe < 240:
        return available_capital * 0.50
    
    # Decent signal (60-69) = 20% of available
    elif quality >= 60:
        return available_capital * 0.20
    
    # Below 60 quality = skip
    else:
        return 0

def check_ready_for_live():
    """Check if paper trading has hit target for 3 consecutive days"""
    recent_snapshots = get_recent_portfolio_snapshots(mode='paper', days=3)
    
    if len(recent_snapshots) < 3:
        return False
    
    # Check if all 3 days hit target
    for snapshot in recent_snapshots:
        if not snapshot['daily_target_met']:
            return False
    
    return True
```

---

### 7. Trading API (Port 8017)

**Responsibilities:**
- Execute trades (paper or live mode)
- Log every trade to ledger with full details
- Simulate fees on paper trades (same as live)
- Integrate with Kraken API for live trades
- Track position status (open, closed, stopped_out)
- Rank trades as win/loss/draw
- Provide account summary (capital, positions, P&L)

**Key Endpoints:**

```python
POST /trade/execute
# Body: {
#   mode: 'paper',  # or 'live'
#   action: 'BUY',  # or 'SELL'
#   symbol: 'BTC',
#   quantity: 0.1,
#   order_type: 'market',  # or 'limit'
#   limit_price: 50000.00,  # only if order_type = 'limit'
#   exchange: 'kraken'
# }
# Returns: {
#   trade_id: 1234,
#   status: 'executed',
#   execution_price: 50050.00,
#   quantity: 0.1,
#   fees: 13.01,  # Kraken taker fee (0.26%)
#   timestamp: '2026-02-17T10:05:23Z'
# }

GET /trade/ledger?mode=paper&limit=100
# Returns: Recent trades
# [
#   {
#     trade_id: 1234,
#     mode: 'paper',
#     symbol: 'BTC',
#     action: 'BUY',
#     quantity: 0.1,
#     price: 50050.00,
#     fees: 13.01,
#     timestamp: '2026-02-17T10:05:23Z',
#     position_id: 5678
#   },
#   ...
# ]

GET /trade/account-summary?mode=paper
# Returns: Account state
# {
#   mode: 'paper',
#   starting_capital: 10000.00,
#   current_capital: 10087.00,
#   total_pnl: 87.00,
#   total_pnl_pct: 0.87,
#   total_fees_paid: 142.30,
#   open_positions: 5,
#   total_trades: 127,
#   winning_trades: 79,
#   losing_trades: 45,
#   draw_trades: 3,
#   win_rate: 62.2,
#   best_trade_pnl: 187.50,
#   worst_trade_pnl: -52.10
# }

POST /trade/simulate-fees
# Body: {symbol: 'BTC', quantity: 0.1, price: 50000.00, order_type: 'market'}
# Returns: {maker_fee: 8.00, taker_fee: 13.00, slippage_estimate: 0.05}
# Useful for UI to show expected costs before trading
```

**Implementation Notes:**
```python
def execute_trade(mode, action, symbol, quantity, order_type, limit_price, exchange):
    """Execute trade (paper or live)"""
    
    if mode == 'paper':
        # Simulate trade
        return execute_paper_trade(action, symbol, quantity, order_type, limit_price)
    
    elif mode == 'live':
        # Real trade via exchange API
        return execute_live_trade_kraken(action, symbol, quantity, order_type, limit_price)
    
def execute_paper_trade(action, symbol, quantity, order_type, limit_price):
    """Simulate trade with realistic fees and slippage"""
    
    # Get current market price
    current_price = get_current_price(symbol)
    
    # Simulate slippage (market orders only)
    if order_type == 'market':
        # Assume 0.05% slippage on market orders
        if action == 'BUY':
            execution_price = current_price * 1.0005  # Buy slightly higher
        else:  # SELL
            execution_price = current_price * 0.9995  # Sell slightly lower
    else:  # limit order
        execution_price = limit_price
    
    # Calculate fees (Kraken rates)
    if order_type == 'market':
        fee_pct = 0.0026  # Taker fee (0.26%)
    else:
        fee_pct = 0.0016  # Maker fee (0.16%)
    
    trade_value = quantity * execution_price
    fees = trade_value * fee_pct
    
    # Log to database
    trade = {
        'mode': 'paper',
        'symbol': symbol,
        'action': action,
        'quantity': quantity,
        'price': execution_price,
        'fees': fees,
        'order_type': order_type,
        'exchange': 'kraken_simulated',
        'timestamp': datetime.now()
    }
    
    trade_id = save_trade_to_ledger(trade)
    
    return {
        'trade_id': trade_id,
        'status': 'executed',
        'execution_price': execution_price,
        'quantity': quantity,
        'fees': fees,
        'timestamp': trade['timestamp']
    }

def execute_live_trade_kraken(action, symbol, quantity, order_type, limit_price):
    """Execute real trade via Kraken API"""
    
    import krakenex
    from pykrakenapi import KrakenAPI
    
    api = krakenex.API()
    api.load_key('/path/to/kraken.key')  # Secure key storage
    k = KrakenAPI(api)
    
    # Kraken pair format: BTCUSD, ETHUSD, etc.
    pair = f'{symbol}USD'
    
    try:
        if action == 'BUY':
            order = k.add_standard_order(
                pair=pair,
                type='buy',
                ordertype=order_type,
                volume=quantity,
                price=limit_price if order_type == 'limit' else None
            )
        else:  # SELL
            order = k.add_standard_order(
                pair=pair,
                type='sell',
                ordertype=order_type,
                volume=quantity,
                price=limit_price if order_type == 'limit' else None
            )
        
        # Log to database
        trade = {
            'mode': 'live',
            'symbol': symbol,
            'action': action,
            'quantity': quantity,
            'price': order['descr']['price'],
            'fees': order['fee'],
            'order_type': order_type,
            'exchange': 'kraken',
            'kraken_order_id': order['txid'][0],
            'timestamp': datetime.now()
        }
        
        trade_id = save_trade_to_ledger(trade)
        
        return {
            'trade_id': trade_id,
            'status': 'executed',
            'execution_price': float(order['descr']['price']),
            'quantity': quantity,
            'fees': float(order['fee']),
            'kraken_order_id': order['txid'][0],
            'timestamp': trade['timestamp']
        }
        
    except Exception as e:
        logger.error(f"Kraken trade failed: {e}")
        raise Exception(f"Live trade execution failed: {str(e)}")
```

---

### 8. AfterAction API (Port 8018)

**Responsibilities:**
- Run twice daily (midday + end-of-day analysis)
- Analyze all trades since last report
- Identify missed opportunities (signals we didn't act on that would've won)
- Identify false signals (acted on but lost)
- Detect regime changes (market conditions shifting)
- Find trading logic flaws
- Generate actionable recommendations
- Auto-apply safe recommendations, flag risky ones for human review

**Key Endpoints:**

```python
POST /afteraction/run-analysis
# Body: {report_time: 'midday'}  # or 'eod'
# Analyzes recent performance and generates report
# Returns: {
#   report_id: 123,
#   trades_analyzed: 45,
#   wins: 28,
#   losses: 15,
#   draws: 2,
#   missed_opportunities: 7,
#   false_signals: 12,
#   regime_changes_detected: 1,
#   recommendations_generated: 5,
#   auto_applied: 2,
#   human_review_required: 3
# }

GET /afteraction/report/{report_id}
# Returns: Full afteraction report with details
# {
#   report_id: 123,
#   report_date: '2026-02-17',
#   report_time: 'midday',
#   
#   summary: {
#     trades_analyzed: 45,
#     win_rate: 62.2,
#     total_pnl_pct: 0.08
#   },
#   
#   missed_opportunities: [
#     {
#       symbol: 'SOL',
#       signal_quality: 68,
#       reason_not_acted: 'Quality below threshold (70)',
#       actual_outcome: 'Would have gained 4.2% in 90 minutes',
#       lesson: 'Consider lowering quality threshold for high-velocity signals'
#     },
#     ...
#   ],
#   
#   false_signals: [
#     {
#       symbol: 'DOGE',
#       strategy_id: 12,
#       quality_score: 75,
#       why_false: 'Sentiment was stale - news article from 6 hours ago',
#       actual_outcome: 'Lost 1.8%',
#       prevention: 'Add news freshness check (< 1 hour old only)'
#     },
#     ...
#   ],
#   
#   regime_changes: [
#     {
#       detected: 'Transition from bullish to bearish regime',
#       indicators: [
#         'Overall market volume down 40%',
#         'Bitcoin dominance increasing (flight to safety)',
#         'Negative sentiment across all major coins'
#       ],
#       recommendation: 'Pause aggressive strategies, tighten stop-losses, reduce position sizes'
#     }
#   ],
#   
#   recommendations: [
#     {
#       type: 'parameter_adjustment',
#       description: 'Lower quality threshold from 70 to 65 for signals with timeframe < 60 min',
#       reasoning: 'Missed 3 fast opportunities that won',
#       auto_applicable: true,
#       status: 'applied'
#     },
#     {
#       type: 'strategy_pause',
#       description: 'Pause strategy #12 (DOGE VWAP cross)',
#       reasoning: 'Generated 5 false signals today, 0% win rate',
#       auto_applicable: false,
#       status: 'requires_human_review'
#     },
#     ...
#   ]
# }

GET /afteraction/recent-reports?days=7
# Returns: Last 7 days of reports for trend analysis
```

**Implementation Notes:**
```python
# Celery task: runs at 12:00 PM and 11:59 PM daily
@celery_app.task
def run_afteraction_analysis(report_time):
    """Run twice-daily analysis of trading performance"""
    
    # Get all trades since last report
    if report_time == 'midday':
        start_time = datetime.now().replace(hour=0, minute=0, second=0)  # Since midnight
    else:  # eod
        last_report = get_last_report()
        start_time = last_report['created_at']
    
    trades = get_trades_since(start_time)
    signals_generated = get_signals_since(start_time)
    
    report = {
        'report_date': datetime.now().date(),
        'report_time': report_time,
        'trades_analyzed': len(trades),
        'wins': len([t for t in trades if t['trade_result'] == 'win']),
        'losses': len([t for t in trades if t['trade_result'] == 'loss']),
        'draws': len([t for t in trades if t['trade_result'] == 'draw']),
        'missed_opportunities': [],
        'false_signals': [],
        'regime_changes': [],
        'recommendations': []
    }
    
    # 1. Find missed opportunities
    report['missed_opportunities'] = find_missed_opportunities(signals_generated, trades)
    
    # 2. Identify false signals
    report['false_signals'] = identify_false_signals(trades)
    
    # 3. Detect regime changes
    report['regime_changes'] = detect_regime_changes()
    
    # 4. Generate recommendations
    report['recommendations'] = generate_recommendations(report)
    
    # 5. Auto-apply safe recommendations
    for rec in report['recommendations']:
        if rec['auto_applicable']:
            apply_recommendation(rec)
            rec['status'] = 'applied'
        else:
            rec['status'] = 'requires_human_review'
    
    # 6. Save report
    report_id = save_afteraction_report(report)
    
    return report

def find_missed_opportunities(signals, trades):
    """Find signals we didn't act on that would've been profitable"""
    missed = []
    
    for signal in signals:
        # Was this signal acted on?
        acted_on = any(t['signal_id'] == signal['id'] for t in trades)
        
        if not acted_on:
            # Simulate: what would've happened if we acted?
            outcome = simulate_trade(signal)
            
            if outcome['pnl_pct'] > 0.5:  # Would've made > 0.5%
                missed.append({
                    'symbol': signal['symbol'],
                    'signal_quality': signal['quality_score'],
                    'reason_not_acted': determine_why_not_acted(signal),
                    'actual_outcome': f"Would have gained {outcome['pnl_pct']:.1f}% in {outcome['minutes']} minutes",
                    'lesson': generate_lesson(signal, outcome)
                })
    
    return missed

def identify_false_signals(trades):
    """Find signals that led to losses and determine why"""
    false_signals = []
    
    losing_trades = [t for t in trades if t['trade_result'] == 'loss']
    
    for trade in losing_trades:
        signal = get_signal(trade['signal_id'])
        
        # Analyze why signal failed
        why_false = []
        
        # Check sentiment staleness
        if signal['sentiment_summary']:
            news_age = check_news_age(signal)
            if news_age > 60:  # minutes
                why_false.append(f'Sentiment was stale ({news_age} minutes old)')
        
        # Check if market regime shifted
        if detect_regime_shift_at_time(trade['entry_time']):
            why_false.append('Market regime shifted during trade (bullish → bearish)')
        
        # Check if strategy has recent poor performance
        strategy_win_rate = get_recent_strategy_win_rate(signal['strategy_id'], days=7)
        if strategy_win_rate < 40:
            why_false.append(f'Strategy has poor recent performance ({strategy_win_rate}% win rate)')
        
        false_signals.append({
            'symbol': signal['symbol'],
            'strategy_id': signal['strategy_id'],
            'quality_score': signal['quality_score'],
            'why_false': ' | '.join(why_false),
            'actual_outcome': f"Lost {abs(trade['realized_pnl_pct']):.1f}%",
            'prevention': suggest_prevention(why_false)
        })
    
    return false_signals

def detect_regime_changes():
    """Detect if market conditions have fundamentally changed"""
    regime_changes = []
    
    # Get market data for last 24 hours
    market_data = get_market_overview(hours=24)
    historical_data = get_market_overview(hours=168)  # 7 days
    
    # Check volume trends
    current_volume = market_data['avg_volume']
    historical_volume = historical_data['avg_volume']
    
    if current_volume < historical_volume * 0.6:
        regime_changes.append({
            'detected': 'Low volume regime - market losing interest',
            'indicators': ['Overall market volume down 40%'],
            'recommendation': 'Reduce position sizes, increase quality thresholds'
        })
    
    # Check Bitcoin dominance
    btc_dominance_now = market_data['btc_dominance']
    btc_dominance_7d_ago = historical_data['btc_dominance']
    
    if btc_dominance_now > btc_dominance_7d_ago + 5:  # 5% increase
        regime_changes.append({
            'detected': 'Flight to safety - capital moving to Bitcoin',
            'indicators': ['Bitcoin dominance +5%', 'Altcoins bleeding'],
            'recommendation': 'Focus on BTC, reduce altcoin exposure'
        })
    
    # Check sentiment shift
    sentiment = get_overall_sentiment()
    if sentiment['score'] < -50:  # Very bearish
        regime_changes.append({
            'detected': 'Bearish sentiment across all major coins',
            'indicators': ['Negative news articles', 'Reddit FUD', 'Twitter panic'],
            'recommendation': 'Tighten stop-losses, consider moving to stablecoins temporarily'
        })
    
    return regime_changes

def generate_recommendations(report):
    """Generate actionable recommendations based on report findings"""
    recommendations = []
    
    # From missed opportunities
    if len(report['missed_opportunities']) >= 3:
        # We're being too strict on quality threshold
        recommendations.append({
            'type': 'parameter_adjustment',
            'description': 'Lower signal quality threshold from 70 to 65 for fast signals (< 60 min)',
            'reasoning': f"Missed {len(report['missed_opportunities'])} profitable opportunities due to quality threshold",
            'auto_applicable': True
        })
    
    # From false signals
    for false_signal in report['false_signals']:
        if 'stale' in false_signal['why_false']:
            recommendations.append({
                'type': 'feature_addition',
                'description': 'Add news freshness check (only use news < 60 minutes old)',
                'reasoning': 'Multiple false signals due to stale sentiment data',
                'auto_applicable': False  # Requires code change
            })
    
    # From regime changes
    for regime in report['regime_changes']:
        recommendations.append({
            'type': 'regime_adaptation',
            'description': regime['recommendation'],
            'reasoning': regime['detected'],
            'auto_applicable': False  # Human should decide
        })
    
    # Strategy performance
    underperforming = find_underperforming_strategies()
    for strategy in underperforming:
        recommendations.append({
            'type': 'strategy_pause',
            'description': f"Pause strategy #{strategy['id']} ({strategy['name']})",
            'reasoning': f"Win rate dropped to {strategy['win_rate']}% (below 40% threshold)",
            'auto_applicable': True
        })
    
    return recommendations
```

---

### 9. Testing API (Port 8019)

**Responsibilities:**
- Provide test endpoints for all system functionality
- Use dummy data and separate test database
- Isolate code from production data
- Generate health score (0-100)
- List failing tests and their details

**Key Endpoints:**

```python
GET /test/run-all
# Runs complete test suite
# Returns: {
#   health_score: 87,
#   total_tests: 45,
#   passed: 39,
#   failed: 6,
#   tests: [
#     {name: 'API Connectivity', category: 'Infrastructure', status: 'PASS'},
#     {name: 'Database Connection', category: 'Infrastructure', status: 'PASS'},
#     {name: 'OHLCV Data Fresh', category: 'Data', status: 'FAIL', error: 'BTC data 10 minutes stale'},
#     ...
#   ]
# }

GET /test/category/{category}
# Run tests for specific category: Infrastructure, Data, Backtesting, Signals, Portfolio, Trading
# Returns: Same format as /test/run-all but filtered

POST /test/dummy-backtest
# Run full backtest with dummy data (ensures backtesting logic works)
# Returns: {status: 'success', trades: 12, win_rate: 58.3}

POST /test/dummy-signal-generation
# Generate signals using dummy OHLCV data
# Returns: {status: 'success', signals_generated: 5}

POST /test/dummy-paper-trade
# Execute full paper trading cycle with dummy data
# Returns: {status: 'success', position_opened: true, position_closed: true, pnl_pct: 1.2}
```

**Implementation Notes:**
```python
def run_all_tests():
    """Execute comprehensive test suite"""
    tests = []
    
    # Infrastructure tests
    tests.extend(test_infrastructure())
    
    # Data tests
    tests.extend(test_data_layer())
    
    # Backtesting tests
    tests.extend(test_backtesting())
    
    # Signal generation tests
    tests.extend(test_signal_generation())
    
    # Portfolio management tests
    tests.extend(test_portfolio_management())
    
    # Trading execution tests
    tests.extend(test_trading_execution())
    
    # Calculate health score
    passed = sum(1 for t in tests if t['status'] == 'PASS')
    health_score = int((passed / len(tests)) * 100)
    
    return {
        'health_score': health_score,
        'total_tests': len(tests),
        'passed': passed,
        'failed': len(tests) - passed,
        'tests': tests
    }

def test_infrastructure():
    """Test API connectivity, database, Redis, Celery"""
    tests = []
    
    # Test each API
    apis = [
        ('AI API', 'http://localhost:8011/health'),
        ('OHLCV API', 'http://localhost:8012/health'),
        ('Backtest API', 'http://localhost:8013/health'),
        ('Optimization API', 'http://localhost:8014/health'),
        ('Signal API', 'http://localhost:8015/health'),
        ('Portfolio API', 'http://localhost:8016/health'),
        ('Trading API', 'http://localhost:8017/health'),
        ('AfterAction API', 'http://localhost:8018/health'),
    ]
    
    for name, url in apis:
        try:
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                tests.append({'name': name, 'category': 'Infrastructure', 'status': 'PASS'})
            else:
                tests.append({'name': name, 'category': 'Infrastructure', 'status': 'FAIL', 'error': f'HTTP {response.status_code}'})
        except Exception as e:
            tests.append({'name': name, 'category': 'Infrastructure', 'status': 'FAIL', 'error': str(e)})
    
    # Test database
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                tests.append({'name': 'Database Connection', 'category': 'Infrastructure', 'status': 'PASS'})
    except Exception as e:
        tests.append({'name': 'Database Connection', 'category': 'Infrastructure', 'status': 'FAIL', 'error': str(e)})
    
    # Test Redis
    try:
        import redis
        r = redis.Redis()
        r.ping()
        tests.append({'name': 'Redis Connection', 'category': 'Infrastructure', 'status': 'PASS'})
    except Exception as e:
        tests.append({'name': 'Redis Connection', 'category': 'Infrastructure', 'status': 'FAIL', 'error': str(e)})
    
    return tests

def test_data_layer():
    """Test OHLCV data availability and freshness"""
    tests = []
    
    symbols = ['BTC', 'ETH', 'SOL']  # Test a few key symbols
    
    for symbol in symbols:
        try:
            latest_candle = get_latest_candle(symbol)
            age_seconds = (datetime.now() - latest_candle['timestamp']).total_seconds()
            
            if age_seconds < 300:  # < 5 minutes
                tests.append({'name': f'{symbol} Data Freshness', 'category': 'Data', 'status': 'PASS', 'detail': f'{age_seconds:.0f}s old'})
            else:
                tests.append({'name': f'{symbol} Data Freshness', 'category': 'Data', 'status': 'FAIL', 'error': f'Data {age_seconds:.0f}s old (stale)'})
        except Exception as e:
            tests.append({'name': f'{symbol} Data Availability', 'category': 'Data', 'status': 'FAIL', 'error': str(e)})
    
    return tests
```

---

### 10. Database API (Implicit)

**Not a separate service, but a shared library used by all services:**

```python
# api/database.py

import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
import os

DATABASE_URL = os.getenv('DATABASE_URL')

@contextmanager
def get_connection():
    """Context manager for database connections"""
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def get_latest_candle(symbol):
    """Get most recent candle for symbol"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM ohlcv_candles
                WHERE symbol = %s
                ORDER BY timestamp DESC
                LIMIT 1
            """, (symbol,))
            return cur.fetchone()

# ... more helper functions
```

---

## Implementation Guide

### Phase 1: Infrastructure Setup (Day 1-2)

1. **Spin up fresh Linux container**
   ```bash
   docker run -d --name trading-system \
     -p 8010:8010 \
     -p 8011-8019:8011-8019 \
     -v /opt/trading-data:/data \
     ubuntu:22.04
   
   docker exec -it trading-system bash
   ```

2. **Install dependencies**
   ```bash
   apt update && apt install -y python3.12 python3-pip postgresql-16 redis-server nginx
   
   # Install TimescaleDB
   apt install -y postgresql-16-timescaledb
   
   pip install fastapi uvicorn psycopg2-binary redis celery anthropic openai \
               pandas numpy talib scikit-optimize deap praw tweepy newsapi-python \
               requests pydantic python-dotenv
   ```

3. **Setup PostgreSQL with TimescaleDB**
   ```bash
   sudo -u postgres psql
   CREATE DATABASE trading_system;
   \c trading_system
   CREATE EXTENSION timescaledb;
   \q
   ```

4. **Apply database schema**
   ```bash
   psql -U postgres -d trading_system -f schema.sql
   ```

5. **Setup Nginx reverse proxy**
   ```nginx
   # /etc/nginx/sites-available/trading
   server {
       listen 8010;
       server_name localhost;
       
       location /ai/ {
           proxy_pass http://localhost:8011/;
       }
       location /ohlcv/ {
           proxy_pass http://localhost:8012/;
       }
       location /backtest/ {
           proxy_pass http://localhost:8013/;
       }
       # ... etc for all services
       
       location / {
           root /opt/trading-system/ui;
           try_files $uri $uri/ /index.html;
       }
   }
   ```

### Phase 2: Core Services (Day 3-5)

1. **OHLCV API** - Get data flowing first (foundation for everything)
2. **Backtesting API** - Validate strategies work
3. **Signal API** - Generate real-time signals
4. **Trading API** - Execute paper trades
5. **Portfolio API** - Manage capital allocation

### Phase 3: Intelligence Layer (Day 6-8)

1. **AI API** - Add discovery and validation
2. **Optimization API** - Tune parameters
3. **AfterAction API** - Learn from results

### Phase 4: Testing & UI (Day 9-10)

1. **Testing API** - Health monitoring
2. **UI** - 3-tab interface (Portfolio, Symbol, Health)
3. **Celery tasks** - Scheduled automation

---

## Deployment Instructions

### Docker Compose (Recommended)

```yaml
# docker-compose.yml
version: '3.8'

services:
  postgres:
    image: timescale/timescaledb:latest-pg16
    environment:
      POSTGRES_DB: trading_system
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - pg-data:/var/lib/postgresql/data
      - ./schema.sql:/docker-entrypoint-initdb.d/schema.sql
    ports:
      - "5432:5432"
  
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
  
  ai-api:
    build: ./services/ai_api
    ports:
      - "8011:8011"
    environment:
      DATABASE_URL: postgresql://postgres:${DB_PASSWORD}@postgres:5432/trading_system
      REDIS_URL: redis://redis:6379
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
      OPENAI_API_KEY: ${OPENAI_API_KEY}
    depends_on:
      - postgres
      - redis
  
  ohlcv-api:
    build: ./services/ohlcv_api
    ports:
      - "8012:8012"
    environment:
      DATABASE_URL: postgresql://postgres:${DB_PASSWORD}@postgres:5432/trading_system
    depends_on:
      - postgres
  
  # ... repeat for backtest-api, optimization-api, signal-api, portfolio-api, trading-api, afteraction-api
  
  celery-worker:
    build: ./services/celery_worker
    command: celery -A tasks worker --loglevel=info
    environment:
      DATABASE_URL: postgresql://postgres:${DB_PASSWORD}@postgres:5432/trading_system
      REDIS_URL: redis://redis:6379
    depends_on:
      - postgres
      - redis
  
  celery-beat:
    build: ./services/celery_worker
    command: celery -A tasks beat --loglevel=info
    environment:
      DATABASE_URL: postgresql://postgres:${DB_PASSWORD}@postgres:5432/trading_system
      REDIS_URL: redis://redis:6379
    depends_on:
      - postgres
      - redis
  
  nginx:
    image: nginx:alpine
    ports:
      - "8010:8010"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
      - ./ui:/usr/share/nginx/html
    depends_on:
      - ai-api
      - ohlcv-api
      # ... all other services

volumes:
  pg-data:
```

### Start System

```bash
# Set environment variables
export DB_PASSWORD="your_secure_password"
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."
export REDDIT_CLIENT_ID="..."
export REDDIT_CLIENT_SECRET="..."
export TWITTER_BEARER_TOKEN="..."
export NEWSAPI_KEY="..."

# Start all services
docker-compose up -d

# Check health
curl http://localhost:8010/test/run-all

# View logs
docker-compose logs -f
```

---

## Success Criteria

After full implementation, you should be able to:

1. ✅ Access http://localhost:8010/ and see 3-tab UI (Portfolio, Symbol, Health)
2. ✅ See active positions in Portfolio tab with real-time P&L
3. ✅ View hourly/daily/weekly performance charts
4. ✅ Click any symbol to see chart + indicators + active signals
5. ✅ Check Health tab to see all APIs green and Celery tasks running
6. ✅ Watch paper trading generate 0.05% daily profit consistently
7. ✅ After 3 consecutive days hitting target, enable live trading
8. ✅ View AfterAction reports twice daily with insights and lessons learned
9. ✅ See AI discovering new symbols based on Reddit/Twitter buzz
10. ✅ Watch portfolio automatically rotate capital from stagnant to hot opportunities

---

## Key Differences from Current Broken System

**What we're REMOVING:**
- ❌ Tangled plugin architecture with circular dependencies
- ❌ Multiple competing backtest implementations
- ❌ Single price_usd trying to be OHLCV
- ❌ COALESCE fallback hacks that crash the system
- ❌ Mixing automation_os_dashboard with app.main
- ❌ Multiple services fighting for port 8000
- ❌ Lack of clear service boundaries

**What we're ADDING:**
- ✅ Clean service-oriented architecture (8 independent APIs)
- ✅ Proper OHLCV data with TimescaleDB (no more single-price hacks)
- ✅ AI-powered discovery and intuition
- ✅ Velocity-based position management (rotate to better opportunities)
- ✅ AfterAction learning system (continuous improvement)
- ✅ Day trader mindset (hourly/daily focus, 0.05% daily target)
- ✅ Comprehensive testing with dummy data
- ✅ Clear path from paper → live trading (3 consecutive days hitting target)

---

This implementation guide is ready to hand to any AI assistant in a fresh container. All vague concepts from your original design have been clarified with concrete technical solutions.
