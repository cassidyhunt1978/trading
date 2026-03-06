#!/usr/bin/env python3
"""Trigger 1-minute candle fetch"""
import sys
sys.path.append('/opt/trading')

from celery_worker.tasks import fetch_historical_1min_candles

print("🚀 Dispatching 1-minute candle fetch task...")
print("This will fetch 5000 recent 1-minute candles for each symbol")
print("(approximately 3.5 days of 1-minute data)")
print("")

result = fetch_historical_1min_candles.delay()

print(f"✓ Task dispatched! Task ID: {result.id}")
print("")
print("Monitor progress:")
print("  tail -f logs/celery_worker.log")
print("")
print("Check results in ~60 seconds:")
print("  psql -d trading_system -c 'SELECT symbol, COUNT(*) FROM ohlcv_candles GROUP BY symbol;'")
