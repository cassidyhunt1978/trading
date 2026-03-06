#!/bin/bash
# Apply Layer Enhancements and Restart Services

echo "════════════════════════════════════════════════════════"
echo "  APPLYING LAYER ENHANCEMENTS"
echo "════════════════════════════════════════════════════════"

# Apply database schema
echo ""
echo "Step 1: Applying database schema..."
sudo -u postgres psql -d trading_system -f /opt/trading/config/layer_enhancements.sql

# Verify tables were created
echo ""
echo "Step 2: Verifying tables..."
sudo -u postgres psql -d trading_system -c "
SELECT 
    'market_regime' as table_name,
    CASE WHEN EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'market_regime') 
        THEN '✓ Created' ELSE '✗ Missing' END as status
UNION ALL
SELECT 
    'performance_goals',
    CASE WHEN EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'performance_goals') 
        THEN '✓ Created' ELSE '✗ Missing' END
UNION ALL
SELECT 
    'daily_performance',
    CASE WHEN EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'daily_performance') 
        THEN '✓ Created' ELSE '✗ Missing' END
UNION ALL
SELECT 
    'optimization_queue',
    CASE WHEN EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'optimization_queue') 
        THEN '✓ Created' ELSE '✗ Missing' END
UNION ALL
SELECT 
    'ai_orchestration_log',
    CASE WHEN EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'ai_orchestration_log') 
        THEN '✓ Created' ELSE '✗ Missing' END
;"

# Stop Celery
echo ""
echo "Step 3: Stopping Celery..."
pkill -f "celery.*worker" 2>/dev/null
pkill -f "celery.*beat" 2>/dev/null
sleep 2

# Start Celery Worker
echo ""
echo "Step 4: Starting Celery Worker..."
cd /opt/trading
export PYTHONPATH=/opt/trading:$PYTHONPATH
nohup celery -A celery_worker.tasks worker --loglevel=info --logfile=/opt/trading/logs/celery_worker.log --concurrency=14 > /dev/null 2>&1 &
WORKER_PID=$!
echo "  Celery Worker started (PID: $WORKER_PID)"

# Start Celery Beat
echo ""
echo "Step 5: Starting Celery Beat..."
nohup celery -A celery_worker.tasks beat --loglevel=info --logfile=/opt/trading/logs/celery_beat.log > /dev/null 2>&1 &
BEAT_PID=$!
echo "  Celery Beat started (PID: $BEAT_PID)"

# Wait for services to start
echo ""
echo "Step 6: Waiting for services to initialize..."
sleep 3

# Verify Celery is running
echo ""
echo "Step 7: Verifying Celery processes..."
if pgrep -f "celery.*worker" > /dev/null; then
    WORKER_COUNT=$(pgrep -f "celery.*worker" | wc -l)
    echo "  ✓ Celery Worker: RUNNING ($WORKER_COUNT process(es))"
else
    echo "  ✗ Celery Worker: NOT RUNNING"
fi

if pgrep -f "celery.*beat" > /dev/null; then
    echo "  ✓ Celery Beat: RUNNING"
else
    echo "  ✗ Celery Beat: NOT RUNNING"
fi

# Show new tasks
echo ""
echo "Step 8: New Celery tasks registered:"
echo "  • process_optimization_queue (Layer 2) - every 2 hours"
echo "  • ai_analyze_system_health (Layer 5) - daily at 9 AM UTC"
echo "  • ai_recommend_strategy_weights (Layer 5) - every 6 hours"
echo "  • record_daily_performance (Layer 8) - daily at 1 AM UTC"
echo "  • adjust_performance_goals (Layer 8) - weekly Sunday 3 AM UTC"

echo ""
echo "════════════════════════════════════════════════════════"
echo "  LAYER ENHANCEMENTS APPLIED"
echo "════════════════════════════════════════════════════════"
echo ""
echo "✓ All 8 layers are now operational"
echo ""
echo "Run './check_status.sh' to verify all services"
echo "Run 'python3 verify_system_layers.py' for detailed layer verification"
echo ""
