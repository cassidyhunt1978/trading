#!/bin/bash
echo "Testing all API endpoints..."
echo ""

echo "Portfolio API: $(curl -s http://localhost:8016/portfolio?mode=paper | python3 -c 'import sys,json; d=json.load(sys.stdin); print(f"Capital: ${d.get(\"current_capital_usd\", 0)}")')"

echo "Signal API: $(curl -s http://localhost:8015/signals/active | python3 -c 'import sys,json; d=json.load(sys.stdin); print(f"Signals: {len(d) if isinstance(d, list) else 0}")')"

echo "Trading API: $(curl -s http://localhost:8017/positions?mode=paper | python3 -c 'import sys,json; d=json.load(sys.stdin); print(f"Positions: {d.get(\"count\", 0)}")')"

echo "Backtest API: $(curl -s http://localhost:8013/results?limit=1 | python3 -c 'import sys,json; d=json.load(sys.stdin); print(f"Status: {d.get(\"status\", \"error\")}")')"

echo "AfterAction API: $(curl -s http://localhost:8018/reports?limit=1 | python3 -c 'import sys,json; d=json.load(sys.stdin); print(f"Status: {d.get(\"status\", \"error\")}")')"

echo ""
echo "All endpoints tested!"
