#!/usr/bin/env python3
"""
Manually trigger optimization processing
Run this to process a batch of optimizations without waiting for the scheduled task
"""

import sys
import os
sys.path.insert(0, '/opt/trading')

from celery_worker.layer_tasks import process_optimization_queue
from shared.logging_config import setup_logging

logger = setup_logging('run_optimizations', 'INFO')

def main():
    """Process a batch of optimizations"""
    print("=" * 60)
    print("  MANUAL OPTIMIZATION PROCESSING")
    print("=" * 60)
    print()
    
    # Ask user how many to process
    try:
        batch_size = input("How many optimizations to process? (default: 10): ").strip()
        batch_size = int(batch_size) if batch_size else 10
    except (ValueError, KeyboardInterrupt):
        print("\nCancelled.")
        return
    
    print(f"\n⚙️  Processing {batch_size} optimizations...")
    print("   This may take several minutes...")
    print()
    
    try:
        result = process_optimization_queue(max_concurrent=batch_size)
        processed = result.get('processed', 0)
        
        print(f"\n✅ Processed {processed} optimizations")
        print()
        print("Next steps:")
        print("  1. Check optimization_queue: SELECT status, COUNT(*) FROM optimization_queue GROUP BY status;")
        print("  2. Wait for calculate_strategy_performance task (runs every 2-4 hours)")
        print("  3. Or manually run: cd /opt/trading && python3 scripts/calculate_performance.py")
        print()
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    try:
        sys.exit(main() or 0)
    except KeyboardInterrupt:
        print("\n\nCancelled by user.")
        sys.exit(1)
