# Clean Crypto Trading System

**Goal:** Automated crypto trading achieving 0.05% daily profit through AI-powered strategy discovery, rigorous backtesting, and dynamic portfolio rebalancing.

## System Status

✅ Infrastructure Setup Complete
- Python 3.12.3 with virtual environment
- PostgreSQL 16 with trading database
- Redis server running
- All Python packages installed

✅ Database Schema Created
- 9 tables created (OHLCV, symbols, strategies, backtests, signals, positions, portfolio, afteraction, system_health)
- 3 test symbols added (BTC, ETH, SOL)
- Initial paper trading capital ($10,000)
- 1 test strategy created

## Quick Start

```bash
# Activate virtual environment
source /opt/trading/venv/bin/activate

# Start individual services (coming soon)
cd /opt/trading
python services/ohlcv_api/main.py
python services/signal_api/main.py
# etc...

# Or use the startup script (to be created)
./start_all.sh
```

## Architecture

8 Independent API Services:
- **AI API** (8011): Symbol discovery, strategy optimization, sentiment analysis
- **OHLCV API** (8012): Candle data fetching, indicator computation
- **Backtesting API** (8013): Strategy validation, performance metrics
- **Optimization API** (8014): Parameter tuning, walk-forward analysis
- **Signal API** (8015): Real-time signal generation, quality scoring
- **Portfolio API** (8016): Capital allocation, position rotation
- **Trading API** (8017): Trade execution (paper/live), ledger
- **AfterAction API** (8018): Learning from trades, regime detection
- **Testing API** (8019): System health monitoring

## Configuration

Edit `.env` file to configure:
- Database credentials
- API keys (Anthropic, OpenAI, Reddit, Twitter, NewsAPI, Kraken)
- Trading parameters (starting capital, target percentages)

## Next Steps

1. ✅ Infrastructure setup
2. ✅ Database schema
3. ⏳ Build core API services
4. ⏳ Create Celery tasks for automation
5. ⏳ Build simple web UI
6. ⏳ Test paper trading
7. ⏳ Deploy to production

## Documentation

See [governing_plan.md](./governing_plan.md) for complete specifications.

## Trading Philosophy

- **Day trader mindset**: Focus on hourly/daily gains
- **Always deployed**: No idle cash sitting around
- **Velocity-based rotation**: Move to better opportunities quickly
- **Strong signal + short timeframe = 80% allocation**
- **Learn from every trade**: Wins and losses improve the system

## Risk Management

- Start with paper trading
- Min 3 consecutive days hitting 0.05% target before going live
- Stop-loss and take-profit on every position
- Velocity monitoring: rotate out of stagnant positions
- AfterAction reports twice daily to catch issues early
