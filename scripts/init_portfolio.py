#!/usr/bin/env python3
"""Initialize portfolio snapshots for paper and live modes"""
import sys
import os
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.database import get_connection
from shared.config import get_settings

settings = get_settings()

def init_portfolio_snapshots():
    """Create initial portfolio snapshots for paper and live modes"""
    
    print("=" * 60)
    print("  INITIALIZE PORTFOLIO SNAPSHOTS")
    print("=" * 60)
    print()
    
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Check for existing snapshots
            cur.execute("SELECT mode, COUNT(*) FROM portfolio_snapshots GROUP BY mode")
            existing = {row['mode']: row['count'] for row in cur.fetchall()}
            
            if existing:
                print(f"📊 Existing snapshots found:")
                for mode, count in existing.items():
                    print(f"   - {mode}: {count} snapshots")
                print()
            
            # Initialize paper mode
            if 'paper' not in existing or existing['paper'] == 0:
                print(f"💰 Initializing paper portfolio...")
                print(f"   Starting capital: ${settings.paper_starting_capital:.2f}")
                
                cur.execute("""
                    INSERT INTO portfolio_snapshots (
                        timestamp,
                        mode,
                        total_capital,
                        deployed_capital,
                        available_capital,
                        open_positions,
                        total_pnl,
                        total_pnl_pct,
                        daily_pnl,
                        daily_pnl_pct,
                        daily_target_met,
                        consecutive_days_target_met,
                        positions_snapshot
                    ) VALUES (
                        NOW(),
                        'paper',
                        %s,
                        0,
                        %s,
                        0,
                        0,
                        0,
                        0,
                        0,
                        false,
                        0,
                        '[]'::jsonb
                    )
                """, (settings.paper_starting_capital, settings.paper_starting_capital))
                
                print("   ✅ Paper portfolio initialized")
            else:
                print(f"   ⏭️  Paper portfolio already exists ({existing['paper']} snapshots)")
            
            # Initialize live mode (with 0 capital - actual balance will be fetched from exchange)
            if 'live' not in existing or existing['live'] == 0:
                print(f"\n💵 Initializing live portfolio...")
                print(f"   Starting capital: $0.00 (will sync from exchange)")
                
                cur.execute("""
                    INSERT INTO portfolio_snapshots (
                        timestamp,
                        mode,
                        total_capital,
                        deployed_capital,
                        available_capital,
                        open_positions,
                        total_pnl,
                        total_pnl_pct,
                        daily_pnl,
                        daily_pnl_pct,
                        daily_target_met,
                        consecutive_days_target_met,
                        positions_snapshot
                    ) VALUES (
                        NOW(),
                        'live',
                        0,
                        0,
                        0,
                        0,
                        0,
                        0,
                        0,
                        0,
                        false,
                        0,
                        '[]'::jsonb
                    )
                """)
                
                print("   ✅ Live portfolio initialized")
            else:
                print(f"   ⏭️  Live portfolio already exists ({existing['live']} snapshots)")
    
    print()
    print("=" * 60)
    print("✅ Portfolio initialization complete!")
    print("=" * 60)
    print()
    print("Verify at: http://localhost:8010")
    print()

if __name__ == '__main__':
    try:
        init_portfolio_snapshots()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
