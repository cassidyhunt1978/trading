#!/bin/bash

echo "Testing API endpoints..."
echo ""

echo "1. Health API (8019):"
curl -s http://localhost:8019/health | python3 -c "import sys, json; data=json.load(sys.stdin); print(f\"Status: {data.get('status', 'N/A')}\")"; echo ""

echo "2. Portfolio API (8016):"
curl -s http://localhost:8016/portfolio?mode=paper | python3 -c "import sys, json; data=json.load(sys.stdin); print(f\"Capital: ${data.get('current_capital_usd', 0):.2f}\")"; echo ""

echo "3. Signal API (8015):"
curl -s http://localhost:8015/signals/active | python3 -c "import sys, json; data=json.load(sys.stdin); print(f\"Signals: {len(data) if isinstance(data, list) else 'Error'}\")"; echo ""

echo "4. Trading API (8017):"
curl -s http://localhost:8017/positions?mode=paper | python3 -c "import sys, json; data=json.load(sys.stdin); print(f\"Positions: {data.get('count', 0)}\")"; echo ""

echo "5. Backtest API (8013):"
curl -s http://localhost:8013/results?limit=1 | python3 -c "import sys, json; data=json.load(sys.stdin); print(f\"Results: {data.get('count', 0)}\")"; echo ""

echo "6. AfterAction API (8018):"
curl -s http://localhost:8018/reports?limit=1 | python3 -c "import sys, json; data=json.load(sys.stdin); print(f\"Reports: {data.get('count', 0)}\")"; echo ""

echo "All tests complete!"
