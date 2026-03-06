#!/usr/bin/env python3
import sys
sys.path.append('/opt/trading')
import psycopg2
from shared.config import Settings

settings = Settings()
conn = psycopg2.connect(settings.database_url)
cursor = conn.cursor()

cursor.execute("SELECT symbol, COUNT(*) as candles FROM ohlcv_candles GROUP BY symbol ORDER BY symbol")
results = cursor.fetchall()

print("Current database status:")
if results:
    for symbol, count in results:
        print(f"  {symbol}: {count} candles")
else:
    print("  No candles in database")

cursor.close()
conn.close()

# Now dispatch the historical fetch
print("\nDispatching historical fetch task...")
from celery_worker.tasks import fetch_historical_1min_candles
result = fetch_historical_1min_candles.delay()
print(f"Task ID: {result.id}")
print("\nMonitor: tail -f logs/celery_worker.log")
