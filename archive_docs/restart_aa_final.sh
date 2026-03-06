#!/bin/bash
# Restart AfterAction API and test

cd /opt/trading
source venv/bin/activate
export PYTHONPATH=/opt/trading

echo "Stopping AfterAction API..."
pkill -9 -f "afteraction_api/main.py" 2>/dev/null
sleep 2

echo "Starting AfterAction API..."
nohup python services/afteraction_api/main.py > logs/afteraction_api_new.log 2>&1 &
PID=$!
echo "Started with PID: $PID"

sleep 5

echo ""
echo "Testing endpoints..."
echo "===================="
echo ""

echo "1. Health:"
curl -s http://localhost:8018/health | python3 -m json.tool 2>/dev/null || curl -s http://localhost:8018/health
echo ""

echo ""
echo "2. Stats:"
curl -s http://localhost:8018/stats | python3 -m json.tool 2>/dev/null || curl -s http://localhost:8018/stats
echo ""

echo ""
echo "3. Reports:"
curl -s http://localhost:8018/reports | python3 -m json.tool 2>/dev/null || curl -s http://localhost:8018/reports
echo ""

echo ""
echo "===================="
echo "Check for errors in log:"
tail -20 logs/afteraction_api_new.log
