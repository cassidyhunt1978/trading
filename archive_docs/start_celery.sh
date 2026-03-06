#!/bin/bash
# Start Celery worker and beat scheduler

cd /opt/trading

# Activate virtual environment
source venv/bin/activate

# Set Python path
export PYTHONPATH=/opt/trading

echo "========================================"
echo "  Starting Celery Worker & Beat"
echo "========================================"

# Start Celery worker
echo "Starting Celery worker..."
nohup celery -A celery_worker.tasks worker --loglevel=info > logs/celery_worker.log 2>&1 &
echo $! > logs/celery_worker.pid
sleep 2

# Start Celery beat scheduler
echo "Starting Celery beat scheduler..."
nohup celery -A celery_worker.tasks beat --loglevel=info > logs/celery_beat.log 2>&1 &
echo $! > logs/celery_beat.pid
sleep 2

echo ""
echo "========================================"
echo "  Celery Status"
echo "========================================"
echo "✓ Worker started (PID: $(cat logs/celery_worker.pid))"
echo "✓ Beat started (PID: $(cat logs/celery_beat.pid))"
echo ""
echo "Scheduled tasks:"
echo "  - Fetch 1m candles: every 60 seconds"
echo "  - Compute indicators: every 2 minutes"
echo "  - Generate signals: every 5 minutes"
echo "  - Rebalance portfolio: every 15 minutes"
echo "  - After-action: twice daily (12:00, 18:00 UTC)"
echo "  - Health check: every 10 minutes"
echo ""
echo "View logs:"
echo "  tail -f logs/celery_worker.log"
echo "  tail -f logs/celery_beat.log"
echo "========================================"
