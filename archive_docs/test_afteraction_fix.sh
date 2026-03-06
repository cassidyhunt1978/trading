#!/bin/bash
# Test AfterAction API after fixing table

echo "================================"
echo "AfterAction API Fix Test"
echo "================================"

cd /opt/trading
source venv/bin/activate

echo ""
echo "1. Creating afteraction_reports table..."
python fix_afteraction_table.py

echo ""
echo "2. Testing /health endpoint..."
curl -s http://localhost:8018/health | python -m json.tool

echo ""
echo "3. Testing /stats endpoint..."
curl -s http://localhost:8018/stats | python -m json.tool

echo ""
echo "4. Testing /reports endpoint..."
curl -s http://localhost:8018/reports?limit=5 | python -m json.tool

echo ""
echo "================================"
echo "Test complete!"
echo "================================"
