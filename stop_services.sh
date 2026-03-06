#!/bin/bash
# Stop all trading services

echo "========================================"
echo "  Stopping all trading services..."
echo "========================================"

cd /opt/trading

stop_service() {
    local name=$1
    local pidfile=$2
    
    if [ -f "$pidfile" ]; then
        PID=$(cat "$pidfile")
        if ps -p $PID > /dev/null 2>&1; then
            kill $PID
            echo "✓ Stopped $name (PID: $PID)"
        else
            echo "- $name was not running"
        fi
        rm -f "$pidfile"
    else
        echo "- No PID file for $name"
    fi
}

stop_service "AI API       " logs/ai_api.pid
stop_service "OHLCV API    " logs/ohlcv_api.pid
stop_service "Backtest API " logs/backtest_api.pid
stop_service "Optimization " logs/optimization_api.pid
stop_service "Signal API   " logs/signal_api.pid
stop_service "Portfolio API" logs/portfolio_api.pid
stop_service "Trading API  " logs/trading_api.pid
stop_service "AfterAction  " logs/afteraction_api.pid
stop_service "Testing API  " logs/testing_api.pid
stop_service "Strategy Config" logs/strategy_config_api.pid
stop_service "System Monitor" logs/system_monitor_api.pid
stop_service "Ensemble API " logs/ensemble_api.pid
stop_service "Web UI       " logs/ui.pid

# Kill any remaining Python services (backup)
echo ""
echo "Cleaning up any remaining processes..."
pkill -f "services/.*/main.py"
pkill -f "ui/server.py"

echo ""
echo "========================================"
echo "  All services stopped"
echo "========================================"
