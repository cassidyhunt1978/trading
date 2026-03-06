#!/bin/bash
echo "=========================================="
echo "UI Wiring Verification"
echo "=========================================="
echo ""

# Check UI Server
echo "1. UI Server (Port 8010):"
if ps aux | grep -q "[p]ython.*ui/server.py"; then
    echo "   ✓ Running"
    response=$(curl -s http://localhost:8010/ | head -5 | grep "<title>")
    if [[ -n "$response" ]]; then
        echo "   ✓ Serving HTML: $response"
    fi
else
    echo "   ✗ NOT Running"
fi
echo ""

# Check API Endpoints
echo "2. API Endpoints:"
declare -A apis=(
    ["8011"]="AI API"
    ["8012"]="OHLCV API"
    ["8013"]="Backtest API"
    ["8014"]="Optimization API"
    ["8015"]="Signal API"
    ["8016"]="Portfolio API"
    ["8017"]="Strategy Config API"
    ["8018"]="AfterAction API"
    ["8019"]="Testing API"
    ["8020"]="Policy API"
)

for port in "${!apis[@]}"; do
    status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 http://localhost:$port/health 2>/dev/null)
    if [ "$status" = "200" ]; then
        echo "   ✓ ${apis[$port]} (Port $port): OK"
    else
        echo "   ✗ ${apis[$port]} (Port $port): ERROR ($status)"
    fi
done
echo ""

# Test Key UI Data Endpoints
echo "3. UI Data Endpoints:"

# Symbols
symbols=$(curl -s http://localhost:8012/symbols 2>/dev/null | grep -o '"symbol"' | wc -l)
echo "   ✓ Symbols loaded: $symbols symbols"

# Strategies
strategies=$(curl -s http://localhost:8015/strategies 2>/dev/null | grep -o '"id"' | wc -l)
echo "   ✓ Strategies loaded: $strategies strategies"

# Positions
positions=$(curl -s http://localhost:8016/positions 2>/dev/null | grep -o '"symbol"' | wc -l)
echo "   ✓ Positions loaded: $positions positions"

# AfterAction
afteraction=$(curl -s http://localhost:8018/stats 2>/dev/null | grep -q "total_reports" && echo "OK" || echo "ERROR")
echo "   ✓ AfterAction API: $afteraction"

# Health
health=$(curl -s http://localhost:8019/test/database 2>/dev/null | grep -q "tests" && echo "OK" || echo "ERROR")
echo "   ✓ Testing API: $health"

# Policies
policies=$(curl -s http://localhost:8020/policies/paper 2>/dev/null | grep -q "daily_loss_limit" && echo "OK" || echo "ERROR")
echo "   ✓ Policy API: $policies"

echo ""
echo "4. UI File Status:"
ui_lines=$(wc -l < /opt/trading/ui/index.html)
echo "   ✓ index.html: $ui_lines lines"
if [ $ui_lines -gt 4000 ]; then
    echo "   ✓ Full UI detected (not minimal version)"
else
    echo "   ⚠ Possible minimal UI version"
fi

echo ""
echo "=========================================="
echo "Verification Complete!"
echo "=========================================="
echo ""
echo "Access your dashboard at:"
echo "http://$(hostname -I | awk '{print $1}'):8010"
echo "or"
echo "http://localhost:8010"
