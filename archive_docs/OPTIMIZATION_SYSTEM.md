# Symbol-Level Strategy Optimization System

## Overview
Built a complete system for symbol-specific strategy parameter optimization and policy management using existing APIs and database infrastructure.

## Implementation Summary

### 1. Database Schema
**New Table: `strategy_overrides`**
- Stores symbol-specific parameter and risk management overrides
- Tracks optimization scores and methods
- Unique constraint on (strategy_id, symbol)
- Indexes on strategy_id, symbol, and optimization_score

```sql
CREATE TABLE strategy_overrides (
    id SERIAL PRIMARY KEY,
    strategy_id INT REFERENCES strategies(id),
    symbol TEXT NOT NULL,
    parameter_overrides JSONB DEFAULT '{}',
    risk_overrides JSONB DEFAULT '{}',
    optimization_score FLOAT,
    optimization_method TEXT,
    optimization_date TIMESTAMPTZ,
    UNIQUE(strategy_id, symbol)
);
```

### 2. Fee Tier System
**File: `/opt/trading/shared/fee_tiers.py`**
- Kraken fee tiers (9 levels from 0.16%/0.26% down to 0%/0.1%)
- Coinbase Advanced Trade fee tiers (9 levels)
- Dynamic fee calculation based on 30-day trading volume
- Volume tracking from positions table

**Benefits:**
- Realistic backtest profitability
- Fee optimization as trading volume increases
- Automatic tier upgrades based on actual volume

### 3. Optimization API Enhancements
**File: `/opt/trading/services/optimization_api/main.py`**

**Updated Functions:**
- `run_backtest_with_params()` - Now calls Backtest API (port 8013) instead of using stubs
- `save_optimization_result()` - Saves to strategy_overrides table instead of metadata
- `get_optimization_results()` - Retrieves from strategy_overrides with baseline comparison

**Features:**
- Grid search: Tests all parameter combinations
- Random search: Samples parameter space randomly
- Bayesian optimization: Intelligent parameter exploration
- Saves best parameters per symbol automatically
- Returns top 10 results ranked by score

**API Endpoints:**
- `POST /optimize` - Run optimization (grid/random/bayesian)
- `GET /results/{strategy_id}` - Get optimization results
- `GET /suggest-ranges/{strategy_id}` - Get recommended parameter ranges

### 4. Signal API Enhancements
**File: `/opt/trading/services/signal_api/main.py`**

**New Function:**
- `get_strategy_parameters(strategy_id, symbol)` - Merges baseline + overrides

**Updated Function:**
- `evaluate_strategy()` - Uses actual strategy parameters instead of hardcoded values
- Reads rsi_period, rsi_oversold, rsi_overbought from database
- Quality score scales with distance from threshold

**Parameter Resolution:**
1. Load baseline parameters from strategies.parameters
2. Check for symbol-specific override in strategy_overrides
3. Merge: override values take precedence
4. Use merged parameters for signal generation

### 5. Backtest API Enhancements
**File: `/opt/trading/services/backtest_api/main.py`**

**New Features:**
- `parameters_override` field in BacktestRequest
- Dynamic fee tier calculation during backtest
- Volume-based fee tier progression

**Updated Function:**
- `simulate_backtest()` - Uses dynamic fee tiers instead of hardcoded fees
- Tracks cumulative volume during backtest
- Updates fee tier as volume increases
- Applies parameters_override if provided

**Example Usage:**
```python
{
  "strategy_id": 1,
  "symbol": "BTC/USD",
  "start_date": "2026-01-18",
  "end_date": "2026-02-17",
  "initial_capital": 1000,
  "parameters_override": {
    "rsi_oversold": 35,
    "rsi_overbought": 75
  }
}
```

### 6. Trading API Enhancements
**File: `/opt/trading/services/trading_api/main.py`**

**Updated Function:**
- `execute_paper_trade()` - Uses dynamic fee tiers based on 30-day volume
- Calculates maker/taker fees from volume tier
- More realistic paper trading simulation

### 7. Strategy Config API (NEW)
**File: `/opt/trading/services/strategy_config_api/main.py`**
**Port: 8020**

**Purpose:** Expose what parameters can be optimized per strategy

**API Endpoints:**

**GET `/strategies/{strategy_id}/config`**
Returns strategy configuration with tunable parameters:
```json
{
  "strategy_id": 1,
  "strategy_name": "Simple RSI Strategy",
  "parameters": {"RSI_period": 14},
  "risk_management": {"stop_loss_pct": 2.0},
  "tunable_parameters": [
    {
      "name": "rsi_oversold",
      "type": "int",
      "current_value": 30,
      "min_value": 10,
      "max_value": 40,
      "step": 5,
      "description": "RSI oversold threshold"
    }
  ]
}
```

**GET `/strategies/{strategy_id}/overrides`**
Get all symbol-specific overrides:
```json
{
  "overrides": [
    {
      "symbol": "BTC/USD",
      "parameter_overrides": {"rsi_oversold": 35},
      "optimization_score": 0.68,
      "optimization_method": "grid_search"
    }
  ]
}
```

**POST `/strategies/overrides`**
Create/update symbol-specific override:
```json
{
  "strategy_id": 1,
  "symbol": "BTC/USD",
  "parameter_overrides": {"rsi_oversold": 35},
  "risk_overrides": {"stop_loss_pct": 3.5}
}
```

**DELETE `/strategies/overrides/{override_id}`**
Remove a symbol-specific override

## Workflow

### Optimization Workflow
1. **Discover Tunable Parameters**
   ```bash
   GET /strategies/1/config
   ```

2. **Run Optimization**
   ```bash
   POST /optimize
   {
     "strategy_id": 1,
     "symbol": "BTC/USD",
     "method": "grid_search",
     "parameter_ranges": {
       "rsi_oversold": [20, 25, 30, 35],
       "rsi_overbought": [65, 70, 75, 80]
     }
   }
   ```

3. **Optimization Process**
   - Tests all combinations (4×4 = 16 backtests)
   - Ranks by sharpe_ratio/total_return/win_rate
   - Saves best result to strategy_overrides table
   - Returns top 10 results

4. **Results Applied Automatically**
   - Signal API reads overrides
   - Uses optimized parameters for BTC/USD
   - Falls back to baseline for other symbols

### Manual Override Workflow
1. **Create Override**
   ```bash
   POST /strategies/overrides
   {
     "strategy_id": 1,
     "symbol": "ETH/USD",
     "parameter_overrides": {"rsi_oversold": 28}
   }
   ```

2. **Signals Use Override**
   - Signal API detects override for ETH/USD
   - Generates signals using rsi_oversold=28 for ETH
   - Uses baseline rsi_oversold=30 for other symbols

## Architecture Benefits

### Leverage Existing Infrastructure ✅
- Uses existing Optimization API (port 8014)
- Uses existing Backtest API (port 8013)
- Uses existing database layer (no custom queries)
- No reinvented wheels

### Symbol-Fungible Parameters ✅
- Baseline in strategies.parameters
- Symbol overrides in strategy_overrides
- Automatic merge in Signal API
- Clean separation of concerns

### Realistic Fee Modeling ✅
- Kraken fee tiers (9 levels)
- Volume-based progression
- Accurate profitability projections
- Encourages volume optimization

### Extensible Design ✅
- Easy to add new parameters
- Easy to add new optimization methods
- Easy to add new risk management rules
- Clean API boundaries

## Testing

### Test 1: Create Override
```bash
curl -X POST http://127.0.0.1:8020/strategies/overrides \
  -H "Content-Type: application/json" \
  -d '{"strategy_id": 1, "symbol": "BTC/USD", "parameter_overrides": {"rsi_oversold": 35}}'
```
✅ **Result:** Override created successfully

### Test 2: Get Configuration
```bash
curl http://127.0.0.1:8020/strategies/1/config
```
✅ **Result:** Returns tunable parameters with ranges

### Test 3: List Overrides
```bash
curl http://127.0.0.1:8020/strategies/1/overrides
```
✅ **Result:** Shows all symbol-specific overrides

## Database State
```
strategy_overrides: 1 override
- Strategy 1 (Simple RSI Strategy)
- Symbol: BTC/USD  
- Parameters: rsi_oversold=35, rsi_overbought=75
- Risk: stop_loss_pct=3.5
```

## API Status
All 11 APIs running:
- Port 8011: AI API ✅
- Port 8012: OHLCV API ✅
- Port 8013: Backtest API ✅
- Port 8014: Optimization API ✅
- Port 8015: Signal API ✅
- Port 8016: Portfolio API ✅
- Port 8017: Trading API ✅
- Port 8018: AfterAction API ✅
- Port 8019: Testing API ✅
- Port 8020: Strategy Config API ✅ (NEW)
- Port 8010: UI Server ✅

## Files Modified
1. `/opt/trading/services/optimization_api/main.py` - Backtest integration
2. `/opt/trading/services/signal_api/main.py` - Parameter override support
3. `/opt/trading/services/backtest_api/main.py` - Fee tiers + parameter override
4. `/opt/trading/services/trading_api/main.py` - Dynamic fees
5. `/opt/trading/shared/fee_tiers.py` - Fee tier calculations (NEW)
6. `/opt/trading/services/strategy_config_api/main.py` - Strategy config API (NEW)
7. `/opt/trading/restart_all.sh` - Added Strategy Config API

## Next Steps (Optional Enhancements)

### UI Integration
- Add "Optimize Strategy" button in Strategy Lab
- Show tunable parameters with sliders
- Display per-symbol overrides in strategy details
- Visualize optimization results

### Advanced Optimization
- Walk-forward validation (prevent overfitting)
- Multi-objective optimization (balance risk/return)
- Ensemble strategies (combine multiple parameter sets)
- Adaptive parameters (change based on market conditions)

### Risk Management
- Portfolio-level constraints
- Correlation-based position sizing
- Dynamic stop loss adjustment
- Maximum drawdown limits

### Fee Optimization
- Track volume towards next tier
- Suggest trades to reach tier threshold
- Compare tier upgrade value vs. opportunity cost
- Real-time tier display in UI
