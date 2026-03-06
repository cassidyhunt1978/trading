#!/bin/bash
# Quick test AfterAction API endpoints

echo "Testing AfterAction API..."
echo ""

echo "1. Health Check:"
curl -s http://localhost:8018/health
echo ""
echo ""

echo "2. Stats (should not error anymore):"
curl -s http://localhost:8018/stats
echo ""
echo ""

echo "3. Reports:"
curl -s http://localhost:8018/reports?limit=5
echo ""
echo ""

echo "Done! If you see JSON responses above without 500 errors, the fix worked."
