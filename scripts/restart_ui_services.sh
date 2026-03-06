#!/bin/bash

echo "Restarting UI services..."

# Kill existing processes
pkill -f "signal_api" 2>/dev/null
pkill -f "server_new" 2>/dev/null
sleep 2

# Start signal API
cd /opt/trading
nohup /opt/trading/venv/bin/python -m uvicorn services.signal_api.main:app --host 0.0.0.0 --port 8015 > logs/signal_api.log 2>&1 &
sleep 2

# Start UI server
cd /opt/trading/ui
nohup /opt/trading/ui/venv/bin/python server_new.py > ../logs/ui_server.log 2>&1 &
sleep 2

echo "Services restarted!"
echo ""
echo "Signal API: http://localhost:8015/docs"
echo "UI Server: http://localhost:3000"
echo ""
echo "Check logs:"
echo "  tail -f /opt/trading/logs/signal_api.log"
echo "  tail -f /opt/trading/logs/ui_server.log"
