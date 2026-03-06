# Trading System Analysis & Improvement Plan
**Date:** March 2, 2026
**Issue:** System gradually blacklists all symbols, limited trading activity

---

## 🔍 ROOT CAUSE ANALYSIS

### Current State
- **Total Symbols:** 23 active cryptocurrencies
- **Blacklisted:** 5 symbols (21.7% of universe)
  - GRT: -$5.71 (6 trades, avg -$0.95/trade)
  - COMP: -$5.61 (11 trades, avg -$0.51/trade)
  - SNX: -$5.26 (6 trades, avg -$0.88/trade)
  - ETC: -$5.20 (5 trades, avg -$1.04/trade)
  - ALGO: -$5.17 (5 trades, avg -$1.04/trade)

### Problem #1: Overly Aggressive Blacklist
**Current Logic** (`shared/risk_manager.py` line 23, 246-297):
```python
self.symbol_blacklist_threshold = -5.0  # < -$5 P&L → blacklist

# Blacklists on FIRST occurrence of -$5 cumulative loss
# No minimum trade requirement
# No consideration of win rate or sample size
```

**Issues:**
1. **Too Sensitive:** Just 5-11 small losing trades ($0.50-$1.04 avg loss) blacklists permanently
2. **No Sample Size Filter:** Can blacklist after only 5 trades (statistically insignificant)
3. **No Recovery Window:** 30-day rolling window makes escape difficult
4. **Ignores Win Rate:** Could be winning 40%+ of trades but still blacklisted

### Problem #2: SELL Signal Timing
**Current Exit Logic** (`celery_worker/tasks.py` lines 1908-1950):
- Requires **2+ strategies** to agree on SELL OR **1 strategy with quality ≥85**
- Only checks **last 10 minutes** of signals
- Runs every **2 minutes**

**Issues:**
1. **Consensus Too Strict:** In volatile markets, may miss optimal exit waiting for 2+ strategies
2. **Short Signal Window:** 10-minute lookback might miss earlier SELL signals
3. **No Trailing Stops:** Missing gains by not protecting profits
4. **No Momentum Exits:** Doesn't exit on breakdown even without SELL signals

### Problem #3: Limited Symbol Participation
**Current Filters** (`celery_worker/tasks.py` lines 1247-1324):
1. Must be BUY signal (SELL handled separately)
2. Must pass blacklist check
3. Must have consensus (2+ strategies) OR quality ≥80
4. Must pass RSI filter
5. Must pass volume filter  
6. Must pass volatility filter
7. Must pass correlation check
8. Must have available capital

**Issues:**
- **Cascade Effect:** Each filter removes opportunities
- **Conservative Consensus:** Requiring 2+ strategies reduces actionable signals by ~70%
- **Blacklist Compounds:** As symbols fail, fewer opportunities remain

---

## 💡 TARGETED SOLUTIONS (No Recreation)

### Solution 1: Adaptive Blacklist ⭐ PRIORITY
**File:** `shared/risk_manager.py` lines 246-297

**Changes:**
```python
# OLD:
self.symbol_blacklist_threshold = -5.0
# Blacklists after any -$5 loss

# NEW:
self.symbol_blacklist_threshold = -15.0  # More tolerance
self.min_trades_for_blacklist = 10       # Require statistical significance
self.max_loss_per_trade = -2.0           # Block if consistently losing $2+/trade
```

**Logic:**
```python
if not result or result['trade_count'] < self.min_trades_for_blacklist:
    return {'approved': True, 'reason': f'{symbol}: Insufficient data ({trade_count} trades)'}

total_pnl = float(result['total_pnl'])
avg_pnl = total_pnl / trade_count

# Blacklist only if BOTH:
# 1. Total loss > -$15 AND
# 2. Average loss > -$2/trade (shows consistent poor performance)
if total_pnl < self.symbol_blacklist_threshold and avg_pnl < self.max_loss_per_trade:
    return {'approved': False, 'reason': f'{symbol}: Consistent loser (${total_pnl:.2f}, avg ${avg_pnl:.2f})'
}
```

**Impact:** Immediately unblocks 4 of 5 blacklisted symbols (COMP, GRT, SN, ETC, ALGO all have <-$2 avg loss)

### Solution 2: Improved Exit Strategy ⭐ PRIORITY
**File:** `celery_worker/tasks.py` lines 1867-2023

**Add Trailing Stop:**
```python
# After line 1867, add:
# Check trailing stop (protect profits)
if current_pnl_pct > 2.0:  # In profit
    trailing_stop_pct = 0.015  # 1.5% trailing
    peak_price = position.get('peak_price', entry_price)
    
    # Update peak
    if current_price > peak_price:
        # Update peak in database for next check
        update_position_peak(position['id'], current_price)
        peak_price = current_price
    
    # Check if dropped from peak
    drop_from_peak = (peak_price - current_price) /peak_price
    if drop_from_peak > trailing_stop_pct:
        should_close = True
        close_reason = f"trailing_stop_triggered (peak: ${peak_price:.2f}, current: ${current_price:.2f}, P&L: +{pnl_pct:.2f}%)"
```

**Relax SELL Consensus:**
```python  
# Change line 1928 from:
if len(sell_signals) >= 2:  # Strict consensus

# To:
if len(sell_signals) >= 1 and avg_quality >= 70:  # Single strong SELL allowed
    should_close = True
    close_reason = f"strong_sell_signal (quality={avg_quality:.0f}, P&L: {pnl_pct:.2f}%)"
```

**Impact:** Protects gains, exits losing positions faster

### Solution 3: Symbol Rotation & Second Chances
**File:** `shared/risk_manager.py` line 246

**Add Weekly Reset:**
```python
def check_symbol_blacklist(self, symbol: str) -> Dict:
    # ... existing code ...
    
    # Grace period: Give blacklisted symbols one trade per week to prove themselves
    if total_pnl < self.symbol_blacklist_threshold:
        # Check if we've tried this symbol recently
        cur.execute("""
            SELECT MAX(entry_time) as last_entry
            FROM positions
            WHERE symbol = %s AND mode = %s
            AND entry_time >= NOW() - INTERVAL '7 days'
        """, (symbol, self.mode))
        
        last_trade = cur.fetchone()
        
        if not last_trade or not last_trade['last_entry']:
            # Haven't traded this in 7 days - give it one chance
            return {
                'approved': True,
                'reason': f'{symbol}: Weekly redemption attempt (${total_pnl:.2f} historical)'
            }
        else:
            return {
                'approved': False,
                'reason': f'{symbol}: Poor performer (${total_pnl:.2f} in {trade_count} trades)'
            }
```

**Impact:** Even blacklisted symbols get periodic retries as market conditions change

### Solution 4: Reduce Position Size for Risky Symbols
**File:** `shared/risk_manager.py` line 323

**Add Risk-Adjusted Sizing:**
```python
def evaluate_new_position(self, symbol: str, proposed_value: float) -> Dict:
    # ... after blacklist check ...
    
    # If symbol has negative but not blacklist-level performance, reduce size
    if checks['blacklist']['approved']:
        # Check if symbol is struggling
        cur.execute("""
            SELECT SUM(realized_pnl) as total_pnl, COUNT(*) as trades
            FROM positions
            WHERE symbol = %s AND mode = %s
            AND status = 'closed'
            AND entry_time >= NOW() - INTERVAL '14 days'
        """, (symbol, self.mode))
        
        recent = cur.fetchone()
        if recent and recent['trades'] >= 3:
            recent_pnl = float(recent['total_pnl'])
            if recent_pnl < -2.0:  # Struggling but not blacklisted
                # Reduce position size by 50%
                actual_value = proposed_value * 0.5
                adjustments.append(f"risky_symbol_half_size (${recent_pnl:.2f} 14d P&L)")
```

**Impact:** Limits losses while still participating in opportunities

### Solution 5: Better Signal Quality Filtering
**File:** `celery_worker/tasks.py` line 1120

**Current:** Fetches top 50 signals, requires consensus or quality ≥80

**Improvement:**
```python
# Change line 1156 from:
if signal['has_consensus'] or signal['weighted_score'] >= 80:

# To allow quality signals through:
if signal['has_consensus'] or signal['weighted_score'] >= 75:  # Lower threshold
    # But add quality check - don't trade low-quality consensus
    if signal['has_consensus'] and signal['weighted_score'] < 65:
        logger.info("signal_rejected", reason="consensus_but_low_quality", score=signal['weighted_score'])
        continue
    
    actionable_signals.append(signal)
```

**Impact:** Balanced approach - more signals but maintains minimum quality bar

---

## 📊 EXPECTED OUTCOMES

**Before:**
- 5 symbols blacklisted (22% of universe)
- ~3-5 trades per day
- Limited diversification
- Death spiral: losses → blacklist → fewer opportunities → more concentration → more losses

**After:**
- 0-2 symbols blacklisted (only worst consistent losers)
- ~8-15 trades per day
- Better diversification across 18-20 symbols  
- Trailing stops protect profits
- Smaller positions on risky symbols limit downside
- Weekly rotation gives symbols second chances
- Adaptive system learns without permanently blocking opportunities

---

## 🚀 IMPLEMENTATION ORDER

### Phase 1: Stop the Bleeding (30 min)
1. **Relax Blacklist** - Change threshold -$5 → -$15, add min 10 trades
2. **Add Trailing Stops** - Protect profits on winners

### Phase 2: Improve Exits (30 min)
3. **Relax SELL Consensus** - Allow single strong SELL (quality ≥70)
4. **Extend Signal Window** - Check last 20 minutes instead of 10

### Phase 3: Expand Opportunities (30 min)
5. **Symbol Rotation** - Weekly redemption attempts
6. **Risk-Adjusted Sizing** - Half size on struggling symbols
7. **Lower Consensus Threshold** - Accept quality ≥75 signals

---

## 📈 MONITORING METRICS

After implementation, track:
1. **Blacklist Count** - Should drop to 0-2 symbols
2. **Daily Trade Volume** - Should increase to 8-15/day
3. **Symbol Diversity** - Should see 12+ different symbols traded per week
4. **Win Rate** - Should improve with trailing stops (target 45%+)
5. **P&L per Symbol** - Watch for persistent losers to adjust thresholds

---

## ⚠️ RISKS & MITIGATION

**Risk:** Reduced blacklist allows more bad trades
**Mitigation:** Risk-adjusted position sizing limits exposure

**Risk:** More signals → more fees
**Mitigation:** Quality threshold (≥65) prevents junk signals

**Risk:** Trailing stops trigger too early
**Mitigation:** Only activate after 2%+ profit, 1.5% tolerance

---

## 🎯 SUCCESS CRITERIA

System is healthy when:
- ✅ Trading 15+ different symbols per week
- ✅ Blacklist has ≤2 symbols (≤10% of universe)
- ✅ Win rate ≥45%
- ✅ Average trade holds 4+ hours (not overtrading)
- ✅ Daily P&L positive 3+ days per week
- ✅ No single symbol represents >15% of losses

**This plan keeps existing architecture intact while making surgical improvements to the most problematic areas.**
