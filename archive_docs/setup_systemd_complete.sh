#!/bin/bash
# Complete setup script - Run this once to configure everything

set -e

echo "========================================"
echo "  Trading System Systemd Setup"
echo "========================================"
echo ""

# Step 1: Stop any running services
echo "[1/8] Stopping any currently running services..."
cd /opt/trading
./stop_services.sh 2>/dev/null || true
./stop_celery.sh 2>/dev/null || true
pkill -f "celery.*trading_system" || true
pkill -f "services/.*/main.py" || true
pkill -f "ui/server.py" || true
sleep 2
echo "✓ Services stopped"
echo ""

# Step 2: Update database capital
echo "[2/8] Updating paper trading capital to \$1,000..."
export PGPASSWORD=postgres
psql -U postgres -d trading_system -c "UPDATE portfolio_snapshots SET total_capital = 1000.00, available_capital = 1000.00 WHERE mode = 'paper';" 2>/dev/null || {
    echo "⚠ Could not update database (this is OK if no snapshots exist yet)"
}
echo "✓ Database updated"
echo ""

# Step 3: Reload systemd
echo "[3/8] Reloading systemd daemon..."
systemctl daemon-reload
echo "✓ Systemd reloaded"
echo ""

# Step 4: Enable services
echo "[4/8] Enabling services to start on boot..."
systemctl enable trading-apis.service
systemctl enable trading-celery-worker.service
systemctl enable trading-celery-beat.service
echo "✓ Services enabled"
echo ""

# Step 5: Start trading APIs
echo "[5/8] Starting trading APIs..."
systemctl start trading-apis.service
echo "⏳ Waiting 12 seconds for APIs to initialize..."
sleep 12
echo "✓ APIs started"
echo ""

# Step 6: Start Celery worker
echo "[6/8] Starting Celery worker..."
systemctl start trading-celery-worker.service
echo "⏳ Waiting 5 seconds..."
sleep 5
echo "✓ Worker started"
echo ""

# Step 7: Start Celery beat
echo "[7/8] Starting Celery beat scheduler..."
systemctl start trading-celery-beat.service
echo "⏳ Waiting 3 seconds..."
sleep 3
echo "✓ Beat started"
echo ""

# Step 8: Verify all services
echo "[8/8] Verifying services..."
echo ""
echo "========================================"
echo "  Service Status"
echo "========================================"

check_service() {
    local service=$1
    local name=$2
    if systemctl is-active --quiet $service; then
        echo "✓ $name is RUNNING"
        return 0
    else
        echo "✗ $name FAILED"
        return 1
    fi
}

all_good=true

check_service "trading-apis.service" "Trading APIs       " || all_good=false
check_service "trading-celery-worker.service" "Celery Worker      " || all_good=false
check_service "trading-celery-beat.service" "Celery Beat        " || all_good=false

echo ""

if [ "$all_good" = true ]; then
    echo "========================================"
    echo "  ✅ SUCCESS - All Services Running!"
    echo "========================================"
    echo ""
    echo "Testing API health..."
    sleep 2
    
    if curl -s http://localhost:8019/health > /dev/null 2>&1; then
        echo "✓ Testing API is responding"
        echo ""
        echo "🎉 System is fully operational!"
        echo ""
        echo "Quick Access:"
        echo "  Dashboard:    http://localhost:8010"
        echo "  Health Check: http://localhost:8019/test/run-all"
        echo ""
        echo "Services will now start automatically on boot."
        echo ""
        echo "View logs:"
        echo "  journalctl -u trading-apis.service -f"
        echo "  tail -f /opt/trading/logs/*.log"
        echo ""
    else
        echo "⚠ APIs started but not responding yet (may need more time)"
        echo ""
        echo "Check status in 30 seconds:"
        echo "  curl http://localhost:8019/test/run-all"
    fi
else
    echo "========================================"
    echo "  ⚠ SOME SERVICES FAILED"
    echo "========================================"
    echo ""
    echo "Check status with:"
    echo "  systemctl status trading-apis.service"
    echo "  systemctl status trading-celery-worker.service"
    echo "  systemctl status trading-celery-beat.service"
    echo ""
    echo "View logs:"
    echo "  journalctl -u trading-apis.service -n 50"
    echo "  tail -50 /opt/trading/logs/*.log"
fi

echo ""
echo "========================================"
echo "  Commands Reference"
echo "========================================"
echo "Stop services:    systemctl stop trading-apis.service"
echo "Restart services: systemctl restart trading-apis.service"
echo "View logs:        journalctl -u trading-apis.service -f"
echo "Disable auto-start: systemctl disable trading-apis.service"
echo ""
echo "Full docs: /opt/trading/SYSTEMD_SETUP.md"
echo "========================================"
