#!/usr/bin/env python3
"""
Process ALL pending optimizations systematically in batches
Runs optimizations in parallel batches to complete the queue efficiently
"""

import sys
import os
import time
from datetime import datetime
sys.path.insert(0, '/opt/trading')

from celery_worker.layer_tasks import process_optimization_queue
from shared.database import get_connection
from shared.logging_config import setup_logging

logger = setup_logging('process_all_optimizations', 'INFO')

def get_queue_status():
    """Get current optimization queue counts by status"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT status, COUNT(*) as count
                FROM optimization_queue
                GROUP BY status
                ORDER BY status
            """)
            return {row['status']: row['count'] for row in cur.fetchall()}

def main():
    """Process all pending optimizations in batches"""
    print("=" * 70)
    print("  BATCH PROCESS ALL OPTIMIZATIONS")
    print("=" * 70)
    print()
    
    # Get initial status
    status = get_queue_status()
    pending = status.get('pending', 0)
    completed = status.get('completed', 0)
    failed = status.get('failed', 0)
    
    print(f"📊 Current Queue Status:")
    print(f"   Pending:   {pending:,}")
    print(f"   Completed: {completed:,}")
    print(f"   Failed:    {failed:,}")
    print()
    
    if pending == 0:
        print("✅ No pending optimizations to process!")
        return 0
    
    # Configuration
    BATCH_SIZE = 20  # Process 20 optimizations per batch
    BATCH_DELAY = 5  # Wait 5 seconds between batches to avoid overwhelming system
    
    print(f"⚙️  Configuration:")
    print(f"   Batch size: {BATCH_SIZE} optimizations per batch")
    print(f"   Batch delay: {BATCH_DELAY} seconds between batches")
    print(f"   Estimated batches: {(pending + BATCH_SIZE - 1) // BATCH_SIZE}")
    print(f"   Estimated time: ~{((pending // BATCH_SIZE) * (BATCH_DELAY + 30)) / 60:.1f} minutes")
    print()
    
    response = input(f"Process all {pending:,} optimizations? (yes/no): ").strip().lower()
    if response not in ['yes', 'y']:
        print("Cancelled.")
        return 0
    
    print()
    print("🚀 Starting batch processing...")
    print("   Press Ctrl+C to stop gracefully after current batch")
    print()
    
    start_time = datetime.now()
    total_processed = 0
    batch_num = 0
    
    try:
        while True:
            batch_num += 1
            batch_start = datetime.now()
            
            # Check remaining
            status = get_queue_status()
            remaining = status.get('pending', 0)
            
            if remaining == 0:
                print()
                print("✅ All optimizations processed!")
                break
            
            print(f"[Batch {batch_num}] Processing {min(BATCH_SIZE, remaining)} optimizations... ", end='', flush=True)
            
            # Process batch
            try:
                result = process_optimization_queue(max_concurrent=BATCH_SIZE)
                processed = result.get('processed', 0)
                total_processed += processed
                
                batch_time = (datetime.now() - batch_start).total_seconds()
                elapsed = (datetime.now() - start_time).total_seconds()
                
                print(f"✓ {processed} done ({batch_time:.1f}s)")
                
                # Show progress
                status = get_queue_status()
                new_remaining = status.get('pending', 0)
                new_completed = status.get('completed', 0)
                new_failed = status.get('failed', 0)
                
                progress_pct = ((pending - new_remaining) / pending * 100) if pending > 0 else 100
                rate = total_processed / elapsed if elapsed > 0 else 0
                eta_seconds = new_remaining / rate if rate > 0 else 0
                
                print(f"   Progress: {progress_pct:.1f}% | Remaining: {new_remaining:,} | "
                      f"Completed: {new_completed:,} | Failed: {new_failed:,} | "
                      f"Rate: {rate:.1f}/min | ETA: {eta_seconds/60:.1f} min")
                print()
                
                # Wait between batches (unless we're done)
                if new_remaining > 0 and BATCH_DELAY > 0:
                    time.sleep(BATCH_DELAY)
                    
            except Exception as e:
                print(f"❌ Error: {e}")
                print(f"   Continuing with next batch...")
                print()
                time.sleep(BATCH_DELAY)
                
    except KeyboardInterrupt:
        print()
        print()
        print("⚠️  Interrupted by user")
    
    # Final status
    print()
    print("=" * 70)
    print("  FINAL STATUS")
    print("=" * 70)
    
    status = get_queue_status()
    elapsed = (datetime.now() - start_time).total_seconds()
    
    print(f"   Processed: {total_processed:,} optimizations")
    print(f"   Time: {elapsed/60:.1f} minutes")
    print(f"   Rate: {total_processed/(elapsed/60):.1f} optimizations/minute")
    print()
    print(f"📊 Queue Status:")
    print(f"   Pending:   {status.get('pending', 0):,}")
    print(f"   Completed: {status.get('completed', 0):,}")
    print(f"   Failed:    {status.get('failed', 0):,}")
    print()
    
    if status.get('pending', 0) == 0:
        print("✅ All optimizations complete!")
        print()
        print("Next steps:")
        print("  1. Calculate strategy performance:")
        print("     python3 scripts/calculate_performance.py")
        print()
        print("  2. Check signals:")
        print("     curl http://localhost:8015/signals/ensemble | python3 -m json.tool")
        print()
    else:
        print("⚠️  Some optimizations still pending")
        print("   Run this script again or wait for scheduled processing")
        print()
    
    print("=" * 70)
    
    return 0

if __name__ == '__main__':
    try:
        sys.exit(main() or 0)
    except KeyboardInterrupt:
        print("\n\n⚠️  Cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
