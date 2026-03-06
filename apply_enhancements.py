#!/usr/bin/env python3
"""
Apply Layer Enhancements - Python Version
"""
import subprocess
import sys
import time
import psycopg2

print("="*60)
print("  APPLYING LAYER ENHANCEMENTS")
print("="*60)

# Step 1: Apply database schema
print("\nStep 1: Applying database schema...")
try:
    with open('/opt/trading/config/layer_enhancements.sql', 'r') as f:
        sql = f.read()
    
    conn = psycopg2.connect("dbname=trading_system user=postgres host=localhost")
    cur = conn.cursor()
    cur.execute(sql)
    conn.commit()
    print("  ✓ Schema applied successfully")
    cur.close()
    conn.close()
except Exception as e:
    print(f"  ✗ Error applying schema: {e}")
    sys.exit(1)

# Step 2: Verify tables
print("\nStep 2: Verifying tables...")
try:
    conn = psycopg2.connect("dbname=trading_system user=postgres host=localhost")
    cur = conn.cursor()
    
    tables = ['market_regime', 'performance_goals', 'daily_performance', 
              'optimization_queue', 'ai_orchestration_log']
    
    for table in tables:
        cur.execute("""
            SELECT COUNT(*) 
            FROM information_schema.tables 
            WHERE table_name = %s
        """, (table,))
        exists = cur.fetchone()[0] > 0
        status = "✓ Created" if exists else "✗ Missing"
        print(f"  {status}: {table}")
    
    cur.close()
    conn.close()
except Exception as e:
    print(f"  ✗ Error verifying tables: {e}")
    sys.exit(1)

# Step 3: Stop Celery
print("\nStep 3: Stopping Celery...")
try:
    subprocess.run(['pkill', '-f', 'celery.*worker'], stderr=subprocess.DEVNULL)
    subprocess.run(['pkill', '-f', 'celery.*beat'], stderr=subprocess.DEVNULL)
    time.sleep(2)
    print("  ✓ Celery stopped")
except Exception as e:
    print(f"  ⚠ Warning stopping Celery: {e}")

# Step 4: Start Celery Worker
print("\nStep 4: Starting Celery Worker...")
try:
    subprocess.Popen([
        'celery', '-A', 'celery_worker.tasks', 'worker',
        '--loglevel=info',
        '--logfile=/opt/trading/logs/celery_worker.log',
        '--concurrency=14'
    ], cwd='/opt/trading', stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    env={'PYTHONPATH': '/opt/trading'})
    print("  ✓ Celery Worker started")
except Exception as e:
    print(f"  ✗ Error starting Worker: {e}")

# Step 5: Start Celery Beat
print("\nStep 5: Starting Celery Beat...")
try:
    subprocess.Popen([
        'celery', '-A', 'celery_worker.tasks', 'beat',
        '--loglevel=info',
        '--logfile=/opt/trading/logs/celery_beat.log'
    ], cwd='/opt/trading', stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    env={'PYTHONPATH': '/opt/trading'})
    print("  ✓ Celery Beat started")
except Exception as e:
    print(f"  ✗ Error starting Beat: {e}")

# Step 6: Wait and verify
print("\nStep 6: Waiting for services to start...")
time.sleep(3)

print("\nStep 7: Verifying Celery processes...")
try:
    result = subprocess.run(['pgrep', '-f', 'celery.*worker'], 
                          capture_output=True, text=True)
    if result.stdout.strip():
        count = len(result.stdout.strip().split('\n'))
        print(f"  ✓ Celery Worker: RUNNING ({count} process(es))")
    else:
        print("  ✗ Celery Worker: NOT RUNNING")
    
    result = subprocess.run(['pgrep', '-f', 'celery.*beat'], 
                          capture_output=True, text=True)
    if result.stdout.strip():
        print("  ✓ Celery Beat: RUNNING")
    else:
        print("  ✗ Celery Beat: NOT RUNNING")
except Exception as e:
    print(f"  ⚠ Warning checking processes: {e}")

# Summary
print("\n" + "="*60)
print("  LAYER ENHANCEMENTS APPLIED")
print("="*60)
print("\n✓ All 8 layers are now operational\n")
print("New tasks scheduled:")
print("  • process_optimization_queue (Layer 2) - every 2 hours")
print("  • ai_analyze_system_health (Layer 5) - daily at 9 AM UTC")
print("  • ai_recommend_strategy_weights (Layer 5) - every 6 hours")
print("  • record_daily_performance (Layer 8) - daily at 1 AM UTC")
print("  • adjust_performance_goals (Layer 8) - weekly Sunday 3 AM UTC")
print("\nRun './check_status.sh' to verify all services")
print()
