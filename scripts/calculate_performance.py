#!/usr/bin/env python3
"""
Calculate strategy performance/trust scores from optimization results
"""

import sys
import os
sys.path.insert(0, '/opt/trading')

from celery_worker.layer_tasks import calculate_strategy_performance
from shared.logging_config import setup_logging

logger = setup_logging('calculate_performance', 'INFO')

def main():
    """Calculate strategy performance metrics"""
    print("=" * 60)
    print("  CALCULATE STRATEGY PERFORMANCE")
    print("=" * 60)
    print()
    
    print("⚙️  Calculating strategy performance and trust scores...")
    print("   This analyzes optimization results and assigns trust scores")
    print()
    
    try:
        result = calculate_strategy_performance()
        
        print(f"\n✅ Performance calculation complete")
        print(f"   Result: {result}")
        print()
        print("Next steps:")
        print("  1. Check trust scores: SELECT COUNT(*) FROM strategy_performance;")
        print("  2. Signals should now generate: wait for generate_signals task (every 5 min)")
        print("  3. Or check signals manually: curl http://localhost:8015/signals/ensemble")
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
