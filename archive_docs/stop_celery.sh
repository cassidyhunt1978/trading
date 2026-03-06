#!/bin/bash
# Stop Celery worker and beat

echo "Stopping Celery services..."

cd /opt/trading

# Stop worker
if [ -f logs/celery_worker.pid ]; then
    PID=$(cat logs/celery_worker.pid)
    if ps -p $PID > /dev/null 2>&1; then
        kill $PID
        echo "✓ Stopped Celery worker (PID: $PID)"
    fi
    rm -f logs/celery_worker.pid
fi

# Stop beat
if [ -f logs/celery_beat.pid ]; then
    PID=$(cat logs/celery_beat.pid)
    if ps -p $PID > /dev/null 2>&1; then
        kill $PID
        echo "✓ Stopped Celery beat (PID: $PID)"
    fi
    rm -f logs/celery_beat.pid
fi

# Kill any remaining celery processes
pkill -f "celery.*trading_system"

echo "Celery services stopped."
