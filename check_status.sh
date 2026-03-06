#!/bin/bash
# Quick status check for all services

echo "════════════════════════════════════════════════════════"
echo "  CRYPTO TRADING SYSTEM - STATUS CHECK"
echo "════════════════════════════════════════════════════════"
echo ""

# Function to check if service is running and responding
check_service() {
    local name=$1
    local port=$2
    local endpoint=${3:-/health}
    
    # Check if port is listening
    if ss -tuln | grep -q ":$port "; then
        # Check if endpoint responds
        if curl -s -f "http://localhost:$port$endpoint" > /dev/null 2>&1; then
            echo "✓ $name (port $port) - RUNNING"
            return 0
        else
            echo "⚠ $name (port $port) - PORT OPEN BUT NOT RESPONDING"
            return 1
        fi
    else
        echo "✗ $name (port $port) - NOT RUNNING"
        return 1
    fi
}

# Check all API services
echo "API SERVICES:"
check_service "AI API         " 8011
check_service "OHLCV API      " 8012
check_service "Backtest API   " 8013
check_service "Optimization   " 8014
check_service "Signal API     " 8015
check_service "Portfolio API  " 8016
check_service "Trading API    " 8017
check_service "AfterAction    " 8018
check_service "Testing API    " 8019
check_service "Strategy Config" 8020
check_service "System Monitor " 8021

echo ""
echo "WEB INTERFACE:"
check_service "Web Dashboard  " 8010 "/"

echo ""
echo "BACKGROUND TASKS:"
# Check Celery Worker
if pgrep -f "celery.*worker" > /dev/null 2>&1; then
    WORKER_COUNT=$(pgrep -f "celery.*worker" | wc -l)
    echo "✓ Celery Worker - RUNNING ($WORKER_COUNT process(es))"
else
    echo "✗ Celery Worker - NOT RUNNING"
fi

# Check Celery Beat
if pgrep -f "celery.*beat" > /dev/null 2>&1; then
    echo "✓ Celery Beat - RUNNING"
else
    echo "✗ Celery Beat - NOT RUNNING"
fi

echo ""
echo "DATABASE & CACHE:"
# Check PostgreSQL
if pg_isready -h localhost -p 5432 > /dev/null 2>&1; then
    echo "✓ PostgreSQL - RUNNING"
else
    echo "✗ PostgreSQL - NOT RUNNING"
fi

# Check Redis
if redis-cli ping > /dev/null 2>&1; then
    echo "✓ Redis - RUNNING"
else
    echo "✗ Redis - NOT RUNNING"
fi

echo ""
echo "════════════════════════════════════════════════════════"
echo "SYSTEM METRICS:"
if command -v free &> /dev/null; then
    MEMORY=$(free -h | awk '/^Mem:/ {printf "Memory: %s / %s (%.0f%%)", $3, $2, ($3/$2)*100}')
    echo $MEMORY
fi
if command -v df &> /dev/null; then
    DISK=$(df -h / | awk 'NR==2 {printf "Disk: %s / %s (%s used)", $3, $2, $5}')
    echo $DISK
fi
if [ -f /proc/loadavg ]; then
    LOAD=$(cat /proc/loadavg | awk '{printf "Load Average: %.2f, %.2f, %.2f", $1, $2, $3}')
    echo $LOAD
fi
echo ""
echo "════════════════════════════════════════════════════════"
echo "SYSTEM LAYER STATUS:"

# Quick layer verification
echo ""
echo "Layer 1 - Symbol Collection:"
SYMBOLS=$(curl -s -f "http://localhost:8012/health" > /dev/null 2>&1 && echo "✓ Active" || echo "✗ Inactive")
echo "  OHLCV API: $SYMBOLS"

echo ""
echo "Layer 2 - Strategy & Optimization:"
STRAT=$(curl -s -f "http://localhost:8020/health" > /dev/null 2>&1 && echo "✓ Active" || echo "✗ Inactive")
OPTIM=$(curl -s -f "http://localhost:8014/health" > /dev/null 2>&1 && echo "✓ Active" || echo "✗ Inactive")
echo "  Strategy Config API: $STRAT"
echo "  Optimization API: $OPTIM"

echo ""
echo "Layer 3 - Performance Tracking:"
SIGNALS=$(curl -s -f "http://localhost:8015/health" > /dev/null 2>&1 && echo "✓ Active" || echo "✗ Inactive")
echo "  Signal API: $SIGNALS"

echo ""
echo "Layer 4 - Regime Detection:"
echo "  Task: detect_market_regimes (runs every 15 min)"

echo ""
echo "Layer 5 - AI Orchestration:"
AI=$(curl -s -f "http://localhost:8011/health" > /dev/null 2>&1 && echo "✓ Active" || echo "✗ Inactive")
echo "  AI API: $AI"

echo ""
echo "Layer 6 - Ensemble Voting:"
echo "  Task: execute_ensemble_trades (runs every 10 min)"

echo ""
echo "Layer 7 - Accounting & P&L:"
PORTFOLIO=$(curl -s -f "http://localhost:8016/health" > /dev/null 2>&1 && echo "✓ Active" || echo "✗ Inactive")
echo "  Portfolio API: $PORTFOLIO"

echo ""
echo "Layer 8 - Goal Management:"
echo "  Task: record_daily_performance (daily at 1 AM UTC)"
echo "  Task: adjust_performance_goals (weekly Sunday 3 AM UTC)"

echo ""
echo "════════════════════════════════════════════════════════"
echo "Total Services: 11 APIs + UI + Celery (Worker & Beat)"
echo "Access Dashboard: http://localhost:8010"
echo "System Metrics: http://localhost:8021/metrics"
echo "View Logs: tail -f /opt/trading/logs/*.log"
echo "Restart All: /opt/trading/restart_all.sh"
echo "Verify Layers: python3 /opt/trading/verify_system_layers.py"
echo "════════════════════════════════════════════════════════"
