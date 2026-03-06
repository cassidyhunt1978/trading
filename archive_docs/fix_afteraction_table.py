#!/usr/bin/env python3
"""Create afteraction_reports table with correct schema"""

import sys
import os
sys.path.append('/opt/trading')

from shared.database import get_connection

try:
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Drop old table if exists (to ensure clean schema)
            cur.execute('DROP TABLE IF EXISTS afteraction_reports CASCADE')
            print('✓ Dropped old afteraction_reports table if it existed')
            
            # Create table with correct schema matching API code
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
            print('✓ Created afteraction_reports table')
            
            # Create indexes
            cur.execute('''
                CREATE INDEX idx_afteraction_created 
                ON afteraction_reports(created_at DESC)
            ''')
            
            cur.execute('''
                CREATE INDEX idx_afteraction_mode 
                ON afteraction_reports(mode)
            ''')
            print('✓ Created indexes')
            
            conn.commit()
            print('\n✅ AfterAction table setup complete!')
            
except Exception as e:
    print(f'❌ Error: {e}')
    sys.exit(1)
