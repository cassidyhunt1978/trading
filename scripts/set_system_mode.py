#!/usr/bin/env python3
"""
Set system operation mode (startup or production) and restart Celery Beat

Usage:
    python scripts/set_system_mode.py startup
    python scripts/set_system_mode.py production
    python scripts/set_system_mode.py status
"""

import sys
import os
import json
import signal
import subprocess
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.database import get_connection

def get_current_mode():
    """Get current system mode"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT config_value 
                    FROM system_config 
                    WHERE config_key = 'system_mode'
                """)
                result = cur.fetchone()
                if result:
                    # psycopg2 DictCursor auto-deserializes JSONB
                    mode = result['config_value']
                    if isinstance(mode, str):
                        return mode
                    return json.loads(mode) if mode else None
    except Exception as e:
        print(f"Error getting mode: {e}")
    return None

def set_mode(mode):
    """Set system mode in database"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO system_config (config_key, config_value)
                VALUES ('system_mode', %s)
                ON CONFLICT (config_key) 
                DO UPDATE SET config_value = %s
            """, (json.dumps(mode), json.dumps(mode)))
    print(f"✅ System mode set to: {mode.upper()}")

def restart_celery_beat():
    """Restart Celery Beat to pick up new schedule"""
    print("\n🔄 Restarting Celery Beat...")
    
    try:
        # Find and kill existing beat process
        result = subprocess.run(
            ['pgrep', '-f', 'celery.*beat'],
            capture_output=True,
            text=True
        )
        
        if result.stdout.strip():
            pids = result.stdout.strip().split('\n')
            for pid in pids:
                try:
                    os.kill(int(pid), signal.SIGTERM)
                    print(f"  Stopped Celery Beat (PID {pid})")
                except:
                    pass
        
        # Wait a moment
        import time
        time.sleep(2)
        
        # Restart beat
        beat_cmd = [
            '/opt/trading/venv/bin/celery',
            '-A', 'celery_worker.tasks',
            'beat',
            '--loglevel=info',
            '--detach',
            '--pidfile=/opt/trading/logs/celery_beat.pid',
            '--logfile=/opt/trading/logs/celery_beat.log'
        ]
        
        subprocess.run(beat_cmd, cwd='/opt/trading', check=True)
        print("  ✅ Celery Beat restarted with new schedule")
        
    except Exception as e:
        print(f"  ⚠️  Could not restart Celery Beat: {e}")
        print("  Please restart manually: pkill -f 'celery.*beat' && celery -A celery_worker.tasks beat --detach")

def show_schedules(mode):
    """Show schedule comparison"""
    schedules = {
        'Walk-forward optimization': {
            'startup': 'Every 4 hours (6x/day)',
            'production': 'Weekly (Sunday 2 AM)'
        },
        'Ensemble optimization': {
            'startup': 'Every 4 hours (6x/day)', 
            'production': 'Daily (4 AM)'
        },
        'Strategy performance calc': {
            'startup': 'Every 2 hours (12x/day)',
            'production': 'Every 4 hours (6x/day)'
        },
        'Market regime detection': {
            'startup': 'Every 15 minutes',
            'production': 'Every 15 minutes'
        },
        'AfterAction analysis': {
            'startup': 'Every 3 hours (8x/day)',
            'production': 'Every 6 hours (4x/day)'
        },
        'AI agent decisions': {
            'startup': 'Every 30 minutes (48x/day)',
            'production': 'Every hour (24x/day)'
        }
    }
    
    print(f"\n{'='*78}")
    print(f"ACTIVE SCHEDULE (Mode: {mode.upper()})")
    print(f"{'='*78}\n")
    
    print(f"{'Task':<32} {'Startup':<24} {'Production':<24}")
    print("-"*78)
    
    for task, modes in schedules.items():
        marker = "→" if mode == 'startup' else " " if mode == 'production' else " "
        startup_freq = modes['startup']
        prod_freq = modes['production']
        
        # Highlight active column
        if mode == 'startup':
            startup_freq = f"• {startup_freq}"
        elif mode == 'production':
            prod_freq = f"• {prod_freq}"
            
        print(f"{marker} {task:<30} {startup_freq:<24} {prod_freq:<24}")
    
    print(f"\n{'='*78}")
    
    if mode == 'startup':
        print("""
STARTUP MODE BENEFITS:
  • 42x faster walk-forward iteration (4hrs vs weekly)
  • Quick problem detection and debugging
  • Accumulate ~50 parameter versions/day (vs 7/week)
  • Test new strategies and regime changes immediately
  
⚠️  RESOURCE IMPACT:
  • Higher CPU usage (6x more optimization runs)
  • ~300MB/day database growth vs ~50MB/day
  • More log file generation
        """)
    else:
        print("""
PRODUCTION MODE BENEFITS:
  • Lower resource usage (stable operation)
  • Statistical significance (longer test periods)
  • Less parameter churn (more stable strategies)
  • Reduced log noise
  
WHEN TO USE:
  • System proven stable for 2-3 weeks
  • 5+ strategies consistently promoting
  • Average Sharpe ratio > 0.5
  • No code changes for 7 days
        """)
    
    print(f"{'='*78}\n")

def show_status():
    """Show current status"""
    current_mode = get_current_mode()
    
    if not current_mode:
        print("❌ System mode not configured")
        print("   Run: python scripts/set_system_mode.py startup")
        return
    
    show_schedules(current_mode)
    
    # Show recent optimization activity
    print("RECENT OPTIMIZATION ACTIVITY:\n")
    
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Check parameter versions
                cur.execute("""
                    SELECT 
                        COUNT(*) as total,
                        COUNT(DISTINCT strategy_id) as strategies,
                        COUNT(DISTINCT symbol) as symbols,
                        MAX(created_at) as last_run,
                        SUM(CASE WHEN status = 'promoted' THEN 1 ELSE 0 END) as promoted
                    FROM parameter_versions
                    WHERE created_at > NOW() - INTERVAL '24 hours'
                """)
                
                stats = cur.fetchone()
                
                print(f"  Last 24 hours:")
                print(f"    • Parameter versions created: {stats['total']}")
                print(f"    • Strategies tested: {stats['strategies']}")
                print(f"    • Symbols tested: {stats['symbols']}")
                print(f"    • Promoted to live: {stats['promoted']}")
                if stats['last_run']:
                    print(f"    • Last optimization: {stats['last_run']}")
                else:
                    print(f"    • Last optimization: Never")
                    
    except Exception as e:
        print(f"  Could not fetch stats: {e}")

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == 'status':
        show_status()
        
    elif command in ['startup', 'production']:
        current = get_current_mode()
        
        if current == command:
            print(f"ℹ️  System already in {command.upper()} mode")
            show_schedules(command)
        else:
            set_mode(command)
            restart_celery_beat()
            show_schedules(command)
            
    else:
        print(f"❌ Unknown command: {command}")
        print(__doc__)
        sys.exit(1)

if __name__ == '__main__':
    main()
