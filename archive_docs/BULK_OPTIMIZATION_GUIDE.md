# Bulk Optimization Feature Guide

## Overview
The **Bulk Optimize All** feature allows you to automatically find the best parameters for ALL enabled strategies across ALL symbols in a single operation.

## How It Works

### 1. Access the Feature
- Go to the **Strategies** tab in the trading UI
- Click the **🚀 Bulk Optimize All** button (purple, top-right corner)

### 2. Configure the Optimization
A modal will open with the following options:
- **Start Date**: Beginning of the backtest period (default: 30 days ago)
- **End Date**: End of the backtest period (default: today)
- **Initial Capital**: Starting capital for each backtest (default: $1000)

### 3. Start the Process
Click **🚀 Start Bulk Optimization** to begin.

The system will:
1. Get all enabled strategies from your database
2. For each strategy on each symbol (BTC, ETH, SOL):
   - Test 3 parameter combinations (min, mid, max values)
   - Run backtests with each combination
   - Calculate a score: `Return × (Win Rate / 100)`
   - Save the best-performing parameters

### 4. Monitor Progress
The modal shows real-time progress:
- **Progress bar**: Visual completion percentage
- **Status text**: Current strategy-symbol being optimized
- **Counter**: Completed jobs / Total jobs
- **Results panel**: Live results for each optimization

### 5. Review Results
Each result shows:
- ✅ **Green box** = Profitable optimization found and saved
  - Shows: Return %, Win Rate %, Number of Trades
- ⚠️ **Gray box** = No profitable combinations found
- ⚠️ **Yellow box** = Strategy has no tunable parameters (skipped)
- ❌ **Red box** = Error occurred

## What Gets Optimized

### Strategies Included
- Only **enabled** strategies are optimized
- Disabled strategies are automatically skipped

### Symbols
- BTC (Bitcoin)
- ETH (Ethereum)  
- SOL (Solana)

### Parameters Optimized
All tunable parameters for each strategy:
- RSI: period, oversold, overbought
- MACD: fast, slow, signal periods
- Williams %R: period
- CCI: period
- ADX: period
- Stochastic: period, smoothing
- ROC: period
- ATR: period
- EMA: period
- Bollinger Bands: period, std deviation
- Risk: stop_loss_pct, take_profit_pct

## Performance

### Estimated Time
- **Per strategy-symbol**: ~5-15 seconds (3 backtests)
- **Total time** = (# enabled strategies × 3 symbols × ~10 seconds)
  - 10 strategies: ~5 minutes
  - 20 strategies: ~10 minutes
  - 36 strategies: ~18 minutes

### Recommendations
1. **Start with fewer strategies**: Enable only your top 5-10 strategies first
2. **Longer date ranges**: More data = more reliable optimization (30+ days)
3. **Run during off-hours**: This is a compute-intensive operation
4. **Check results**: Review the results panel to see which strategies performed best

## After Optimization

### Using Optimized Parameters
The best parameters are **automatically saved** to the database for each strategy-symbol combination.

When you:
1. Open a symbol's backtest modal
2. Select an optimized strategy
3. The saved parameters will automatically load

You can then:
- Run tests with the optimized parameters
- Further refine them manually
- Run "Optimize All" again for that specific symbol for more fine-tuning

### Viewing Saved Parameters
1. Go to any symbol card (BTC, ETH, SOL)
2. Click **Test**
3. Select a strategy
4. If optimized parameters exist, you'll see:
   - ✅ **"Custom parameters saved"** badge (green)
   - Sliders pre-set to optimized values

## Tips & Best Practices

### 1. Strategic Selection
- Enable only strategies you trust or want to test
- Disable underperforming strategies before bulk optimization
- Focus on strategies with 5-10 tunable parameters (sweet spot)

### 2. Date Range Selection
- **Short range (7 days)**: Quick tests, less reliable
- **Medium range (30 days)**: Balanced, recommended
- **Long range (90+ days)**: More reliable, takes longer

### 3. Capital Amount
- Use realistic capital ($1000-$10000)
- Higher capital = more realistic fee impact
- Lower capital = faster backtests

### 4. Interpreting Results
Good optimization results show:
- ✅ Positive return %
- ✅ Win rate > 50%
- ✅ Multiple trades (>5)
- ✅ Consistent across symbols

Red flags:
- ⚠️ Only 1-2 trades total
- ⚠️ Win rate < 30%
- ⚠️ Wildly different results between symbols

### 5. Follow-Up Actions
After bulk optimization:
1. **Review top performers**: Check which strategies scored best
2. **Disable poor performers**: Strategies with no profitable combinations
3. **Fine-tune winners**: Use per-symbol "Optimize All" for deeper optimization
4. **Monitor live trading**: Deploy top strategies with optimized parameters

## Example Workflow

1. **Initial Setup**
   - Create/import 15-20 diverse strategies
   - Enable the top 10 you want to test

2. **Bulk Optimization**
   - Click "Bulk Optimize All"
   - Set 30-day date range
   - Start optimization (~10 minutes)

3. **Review Results**
   - Note strategies with positive returns on multiple symbols
   - Disable strategies that failed on all symbols

4. **Fine-Tune Winners**
   - For top 3 performers, run per-symbol optimization
   - Test more parameter combinations
   - Adjust ranges based on results

5. **Deploy**
   - Enable only optimized strategies
   - Monitor live performance
   - Re-optimize monthly

## Technical Details

### Optimization Algorithm
- **Simplified grid search**: Tests min, mid, max values for primary parameter
- **Scoring function**: `score = total_return_pct × (win_rate / 100)`
- **Best result**: Highest score with trades > 0

### Data Saved
For each strategy-symbol combination with positive score:
```json
{
  "strategy_id": 18,
  "symbol": "BTC",
  "parameter_overrides": {
    "williams_period": 14,
    "adx_period": 14,
    "macd_fast": 12,
    // ... all optimized parameters
  },
  "optimization_score": 2.45
}
```

### API Endpoints Used
- `GET /strategies` (port 8015) - Fetch all strategies
- `GET /strategies/{id}/config` (port 8020) - Get tunable parameters
- `POST /run` (port 8013) - Run backtests
- `POST /strategies/overrides` (port 8020) - Save optimized parameters

## Troubleshooting

### "No enabled strategies found"
- Go to Strategies tab
- Enable at least one strategy (green "✓ Active" button)

### "Error during bulk optimization"
- Check all APIs are running (ports 8013, 8015, 8020)
- Verify sufficient OHLCV data exists for date range
- Check browser console for detailed error messages

### Optimization too slow
- Reduce number of enabled strategies
- Use shorter date range (7-14 days)
- Optimize fewer symbols at once (future feature)

### No profitable combinations found
- Strategy may not suit current market conditions
- Try different date ranges
- Adjust parameter ranges in strategy definition
- Consider disabling underperforming strategies

## Future Enhancements

Planned improvements:
- [ ] Parallel backtesting (run multiple at once)
- [ ] More sophisticated grid search (5+ combinations per param)
- [ ] Multi-parameter optimization (test all param combinations)
- [ ] Symbol selection (optimize only BTC, or only ETH, etc.)
- [ ] Time-based filtering (only test certain hours/days)
- [ ] Export optimization report (CSV/PDF)
- [ ] Optimization scheduling (run nightly)
