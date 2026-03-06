#!/bin/bash
# Simple manual test you can run to verify the fix

echo "Testing AfterAction API endpoints..."
echo ""
echo "1. Health:"
curl -s http://localhost:8018/health | python3 -m json.tool 2>/dev/null || curl -s http://localhost:8018/health
echo ""
echo ""
echo "2. Stats (was failing with 500):"
curl -s http://localhost:8018/stats | python3 -m json.tool 2>/dev/null || curl -s http://localhost:8018/stats
echo ""
echo ""
echo "3. Reports:"
curl -s http://localhost:8018/reports | python3 -m json.tool 2>/dev/null || curl -s http://localhost:8018/reports
echo ""
