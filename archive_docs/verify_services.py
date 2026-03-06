#!/usr/bin/env python3
import requests
import json

print("Testing API endpoints...")
print("=" * 60)

tests = [
    ("Portfolio API", "http://localhost:8016/portfolio?mode=paper"),
    ("Signal API", "http://localhost:8015/signals/active"),
    ("Trading API", "http://localhost:8017/positions?mode=paper"),
    ("Backtest API", "http://localhost:8013/results?limit=1"),
    ("AfterAction API", "http://localhost:8018/reports?limit=1"),
    ("Health API", "http://localhost:8019/health"),
]

all_ok = True
for name, url in tests:
    try:
        response = requests.get(url, timeout=3)
        if response.status_code == 200:
            data = response.json()
            print(f"✓ {name:20s} OK ({response.status_code})")
            if name == "Portfolio API":
                print(f"  → Capital: ${data.get('current_capital_usd', 0):.2f}")
            elif name == "Signal API":
                print(f"  → Signals: {len(data) if isinstance(data, list) else 0}")
            elif name == "Trading API":
                print(f"  → Positions: {data.get('count', 0)}")
            elif name == "Backtest API":
                print(f"  → Results: {data.get('count', 0)}")
            elif name == "AfterAction API":
                print(f"  → Reports: {data.get('count', 0)}")
        else:
            print(f"✗ {name:20s} ERROR ({response.status_code})")
            print(f"  → {response.text[:100]}")
            all_ok = False
    except requests.exceptions.ConnectionError:
        print(f"✗ {name:20s} CONNECTION REFUSED")
        all_ok = False
    except Exception as e:
        print(f"✗ {name:20s} {str(e)[:50]}")
        all_ok = False

print("=" * 60)
if all_ok:
    print("✓ ALL SERVICES OPERATIONAL")
else:
    print("✗ SOME SERVICES HAVE ISSUES")
