#!/usr/bin/env python3
"""
Fetch 180 days of historical data for all symbols
"""
import sys
import time
import requests
from shared.config import Settings

settings = Settings()
symbols = ['BTC', 'ETH', 'SOL']

# We'll fetch in chunks to avoid rate limits
# 180 days = ~4320 hours, but let's fetch daily candles (180) first, then hourly
timeframes_to_fetch = [
    ('1d', 180),  # 180 daily candles (6 months)
    ('1h', 1000), # 1000 hourly candles (~42 days)
    ('1h', 1000), # Another 1000 hourly (total ~84 days)
    ('1h', 1000), # Another 1000 hourly (total ~126 days)
    ('1h', 1000), # Another 1000 hourly (total ~168 days)
]

print("🚀 Starting historical data fetch for 180 days...")
print(f"Symbols: {', '.join(symbols)}")
print("=" * 60)

total_fetched = 0

for symbol in symbols:
    print(f"\n📊 Fetching data for {symbol}...")
    symbol_total = 0
    
    for timeframe, limit in timeframes_to_fetch:
        try:
            url = f"http://127.0.0.1:8012/candles/fetch"
            params = {
                'symbol': symbol,
                'timeframe': timeframe,
                'limit': limit
            }
            
            print(f"  - Fetching {limit} {timeframe} candles...", end=' ', flush=True)
            
            response = requests.post(url, params=params, timeout=60)
            response.raise_for_status()
            
            result = response.json()
            
            if result.get('status') == 'success':
                fetched = result.get('candles_fetched', 0)
                symbol_total += fetched
                print(f"✓ Got {fetched} candles")
                
                # Respect rate limits - wait between requests
                time.sleep(2)
            else:
                print(f"✗ Failed: {result.get('message', 'Unknown error')}")
                
        except Exception as e:
            print(f"✗ Error: {e}")
            continue
    
    print(f"  Total for {symbol}: {symbol_total} candles")
    total_fetched += symbol_total

print("\n" + "=" * 60)
print(f"✅ Complete! Total candles fetched: {total_fetched}")
print("\nVerifying database...")

# Query the database to confirm
import psycopg2
try:
    conn = psycopg2.connect(settings.database_url)
    cursor = conn.cursor()
    
    cursor.execute("SELECT symbol, COUNT(*) FROM ohlcv_candles GROUP BY symbol ORDER BY symbol")
    results = cursor.fetchall()
    
    print("\nDatabase candle counts:")
    for symbol, count in results:
        print(f"  {symbol}: {count:,} candles")
    
    cursor.execute("SELECT symbol, MIN(timestamp), MAX(timestamp) FROM ohlcv_candles GROUP BY symbol ORDER BY symbol")
    date_ranges = cursor.fetchall()
    
    print("\nDate ranges:")
    for symbol, min_date, max_date in date_ranges:
        days = (max_date - min_date).days if min_date and max_date else 0
        print(f"  {symbol}: {min_date} to {max_date} ({days} days)")
    
    conn.close()
    
except Exception as e:
    print(f"Error verifying: {e}")

print("\n✨ Historical data fetch complete!")
