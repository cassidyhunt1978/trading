#!/usr/bin/env python3
import requests
import sys

print("Testing API endpoints...")
print("=" * 50)

endpoints = [
    ("Portfolio API", "http://localhost:8016/portfolio?mode=paper"),
    ("Signal API", "http://localhost:8015/signals/active"),
    ("Trading API", "http://localhost:8017/positions?mode=paper"),
    ("Backtest API", "http://localhost:8013/results?limit=1"),
    ("AfterAction API", "http://localhost:8018/reports?limit=1"),
]

for name, url in endpoints:
    try:
        response = requests.get(url, timeout=2)
        if response.status_code == 200:
            print(f"✓ {name}: OK ({response.status_code})")
        else:
            print(f"✗ {name}: ERROR ({response.status_code})")
    except requests.exceptions.ConnectionError:
        print(f"✗ {name}: CONNECTION REFUSED")
    except Exception as e:
        print(f"✗ {name}: {str(e)}")

print("=" * 50)
