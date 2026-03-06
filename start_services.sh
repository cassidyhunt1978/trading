#!/bin/bash
# Trading System Startup Script

echo "========================================"
echo "  Clean Crypto Trading System"
echo "  Starting all services..."
echo "========================================"

# Set working directory
cd /opt/trading

# Activate virtual environment
source venv/bin/activate

# Set Python path
export PYTHONPATH=/opt/trading

# Start AI API
echo "[1/11] Starting AI API on port 8011..."
nohup python services/ai_api/main.py > logs/ai_api.log 2>&1 &
echo $! > logs/ai_api.pid
sleep 1

# Start OHLCV API  
echo "[2/11] Starting OHLCV API on port 8012..."
nohup python services/ohlcv_api/main.py > logs/ohlcv_api.log 2>&1 &
echo $! > logs/ohlcv_api.pid
sleep 1

# Start Backtest API
echo "[3/11] Starting Backtest API on port 8013..."
nohup python services/backtest_api/main.py > logs/backtest_api.log 2>&1 &
echo $! > logs/backtest_api.pid
sleep 1

# Start Optimization API
echo "[4/11] Starting Optimization API on port 8014..."
nohup python services/optimization_api/main.py > logs/optimization_api.log 2>&1 &
echo $! > logs/optimization_api.pid
sleep 1

# Start Signal API
echo "[5/11] Starting Signal API on port 8015..."
nohup python services/signal_api/main.py > logs/signal_api.log 2>&1 &
echo $! > logs/signal_api.pid
sleep 1

# Start Portfolio API
echo "[6/11] Starting Portfolio API on port 8016..."
nohup python services/portfolio_api/main.py > logs/portfolio_api.log 2>&1 &
echo $! > logs/portfolio_api.pid
sleep 1

# Start Trading API
echo "[7/11] Starting Trading API on port 8017..."
nohup python services/trading_api/main.py > logs/trading_api.log 2>&1 &
echo $! > logs/trading_api.pid
sleep 1

# Start AfterAction API
echo "[8/11] Starting AfterAction API on port 8018..."
nohup python services/afteraction_api/main.py > logs/afteraction_api.log 2>&1 &
echo $! > logs/afteraction_api.pid
sleep 1

# Start Testing API
echo "[9/11] Starting Testing API on port 8019..."
nohup python services/testing_api/main.py > logs/testing_api.log 2>&1 &
echo $! > logs/testing_api.pid
sleep 1

# Start Strategy Config API
echo "[10/11] Starting Strategy Config API on port 8020..."
nohup python services/strategy_config_api/main.py > logs/strategy_config_api.log 2>&1 &
echo $! > logs/strategy_config_api.pid
sleep 1

# Start System Monitor API
echo "[11/11] Starting System Monitor API on port 8021..."
nohup python services/system_monitor_api/main.py > logs/system_monitor_api.log 2>&1 &
echo $! > logs/system_monitor_api.pid
sleep 1

# Start Celery Worker
echo "[12/14] Starting Celery Worker..."
nohup celery -A celery_worker.tasks worker --loglevel=info > logs/celery_worker.log 2>&1 &
echo $! > logs/celery_worker.pid
sleep 2

# Start Celery Beat
echo "[13/14] Starting Celery Beat Scheduler..."
nohup celery -A celery_worker.tasks beat --loglevel=info > logs/celery_beat.log 2>&1 &
echo $! > logs/celery_beat.pid
sleep 2

# Start UI
echo "[14/14] Starting Web UI on port 8010..."
cd ui && nohup /opt/trading/venv/bin/python server.py > ../logs/ui.log 2>&1 &
echo $! > ../logs/ui.pid
cd ..

echo ""
echo "Waiting for services to initialize..."
sleep 5

# Health checks
echo ""
echo "========================================"
echo "  Services Health Check"
echo "========================================"

check_service() {
    local name=$1
    local port=$2
    if curl -s http://localhost:$port/health > /dev/null 2>&1; then
        echo "✓ $name (port $port)"
    else
        echo "✗ $name (port $port) - FAILED"
    fi
}

check_service "AI API       " 8011
check_service "OHLCV API    " 8012
check_service "Backtest API " 8013
check_service "Optimization " 8014
check_service "Signal API   " 8015
check_service "Portfolio API" 8016
check_service "Trading API  " 8017
check_service "AfterAction  " 8018
check_service "Testing API  " 8019
check_service "Strategy Cfg " 8020
check_service "Web UI       " 8010

echo ""
echo "========================================"
echo "  Quick Access URLs"
echo "========================================"
echo "Web Dashboard:    http://localhost:8010"
echo "Full Health Test: http://localhost:8019/test/run-all"
echo ""
echo "View logs:        tail -f logs/*.log"
echo "Stop services:    ./stop_services.sh"
echo "========================================"
