#!/bin/bash
# Canonical Celery restart script
# DO NOT CHANGE THESE PATHS - they are the standard configuration

echo "Stopping Celery..."
pkill -9 -f "celery.*worker"
pkill -9 -f "celery.*beat"
sleep 2

echo "Starting Celery with canonical configuration..."
cd /opt/trading
source venv/bin/activate
export PYTHONPATH=/opt/trading

# Start Worker (from /opt/trading directory, NOT celery_worker)
echo "  Starting Celery Worker..."
nohup celery -A celery_worker.tasks worker --loglevel=info --concurrency=12 > logs/celery_worker.log 2>&1 &
echo $! > logs/celery_worker.pid
sleep 2

# Start Beat (from /opt/trading directory, NOT celery_worker)
echo "  Starting Celery Beat..."
nohup celery -A celery_worker.tasks beat --loglevel=info > logs/celery_beat.log 2>&1 &
echo $! > logs/celery_beat.pid
sleep 2

# Verify
WORKER_COUNT=$(pgrep -f "celery.*worker" | wc -l)
BEAT_COUNT=$(pgrep -f "celery.*beat" | wc -l)

echo ""
if [ "$WORKER_COUNT" -gt 0 ] && [ "$BEAT_COUNT" -gt 0 ]; then
    echo "✓ Celery started successfully"
    echo "  Workers: $WORKER_COUNT processes"
    echo "  Beat: Running"
else
    echo "✗ Celery failed to start"
    echo "  Workers: $WORKER_COUNT processes"
    echo "  Beat: $BEAT_COUNT processes"
    tail -20 logs/celery_worker.log
    tail -20 logs/celery_beat.log
fi
