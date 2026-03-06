#!/usr/bin/env python3
"""Drop and recreate afteraction_reports table"""
import sys
sys.path.append('/opt/trading')

from shared.database import get_connection

print("Dropping and recreating afteraction_reports table...")

try:
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Drop old table
            cur.execute('DROP TABLE IF EXISTS afteraction_reports CASCADE')
            print("✓ Old table dropped")
            
            # Create new table with correct schema
            cur.execute('''
                CREATE TABLE afteraction_reports (
                    id SERIAL PRIMARY KEY,
                    mode TEXT NOT NULL,
                    period_start TIMESTAMP NOT NULL,
                    period_end TIMESTAMP NOT NULL,
                    total_trades_analyzed INTEGER DEFAULT 0,
                    winning_trades INTEGER DEFAULT 0,
                    losing_trades INTEGER DEFAULT 0,
                    missed_opportunities INTEGER DEFAULT 0,
                    false_signals INTEGER DEFAULT 0,
                    recommendations JSONB,
                    regime_detected TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            print("✓ New table created")
            
            # Create indexes
            cur.execute('CREATE INDEX idx_afteraction_created ON afteraction_reports(created_at DESC)')
            cur.execute('CREATE INDEX idx_afteraction_mode ON afteraction_reports(mode)')
            print("✓ Indexes created")
            
            conn.commit()
            print("\n✅ Table recreated successfully!")
            
except Exception as e:
    print(f"❌ Error: {e}")
    sys.exit(1)
