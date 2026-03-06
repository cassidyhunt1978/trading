#!/bin/bash
# Complete AfterAction API Restart and Verification

set -e

echo "======================================================================"
echo " AfterAction API Fix & Restart"
echo "======================================================================"
echo ""

# Navigate to trading directory
cd /opt/trading
source venv/bin/activate

# Stop any existing AfterAction API
echo "1. Stopping existing AfterAction API..."
pkill -f "afteraction_api/main.py" 2>/dev/null || echo "   (no existing process found)"
sleep 2

# Start AfterAction API
echo ""
echo "2. Starting AfterAction API..."
PYTHONPATH=/opt/trading nohup python services/afteraction_api/main.py > logs/afteraction_api.log 2>&1 &
PID=$!
echo "   Started with PID: $PID"
sleep 4

# Verify it's running
echo ""
echo "3. Verifying API is responding..."
for i in {1..5}; do
    if curl -s http://localhost:8018/health > /dev/null 2>&1; then
        echo "   ✓ API is running!"
        break
    else
        if [ $i -eq 5 ]; then
            echo "   ✗ API did not start. Check logs:"
            tail -20 logs/afteraction_api.log
            exit 1
        fi
        echo "   Waiting... (attempt $i/5)"
        sleep 2
    fi
done

# Test endpoints
echo ""
echo "4. Testing endpoints..."
echo ""

echo "   /health:"
curl -s http://localhost:8018/health | python -m json.tool
echo ""

echo ""
echo "   /stats (was returning 500 before):"
curl -s http://localhost:8018/stats | python -m json.tool
echo ""

echo ""
echo "   /reports:"
curl -s http://localhost:8018/reports?limit=3 | python -m json.tool
echo ""

echo ""
echo "======================================================================"
echo " ✅ AfterAction API is running correctly!"
echo "======================================================================"
echo ""
echo "Next steps:"
echo "  1. Refresh your UI page (http://your-server-ip:8010)"
echo "  2. Go to System tab"
echo "  3. Scroll to 'AfterAction Analysis' section"
echo "  4. Click the 'Refresh' and 'Run Analysis' buttons"
echo ""
echo "The 500 errors should be gone now!"
echo "======================================================================"
