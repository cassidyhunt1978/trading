#!/usr/bin/env python3
"""Quick script to check which strategies have active signals"""
import requests
import json
from collections import defaultdict

# Fetch signals
response = requests.get('http://localhost:8015/signals/active?min_quality=0')
signals = response.json()

print(f"\n{'='*60}")
print(f"ACTIVE SIGNALS SUMMARY")
print(f"{'='*60}\n")
print(f"Total active signals: {len(signals)}\n")

# Group by strategy and symbol
by_strategy = defaultdict(lambda: {'BTC': [], 'ETH': [], 'SOL': []})

for sig in signals:
    strategy_id = sig['strategy_id']
    symbol = sig['symbol']
    by_strategy[strategy_id][symbol].append(sig)

# Show strategies with signals
print("Strategies with BTC signals:")
print("-" * 60)
for strategy_id in sorted(by_strategy.keys()):
    btc_sigs = by_strategy[strategy_id]['BTC']
    if btc_sigs:
        print(f"  Strategy {strategy_id}: {len(btc_sigs)} signal(s)")
        for sig in btc_sigs:
            print(f"    - {sig['signal_type']} at {sig['generated_at'][:19]} (Quality: {sig['quality_score']}%)")

print("\n" + "="*60)
print("RECOMMENDATION: Try viewing one of the strategies above")
print("="*60)
