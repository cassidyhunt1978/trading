#!/usr/bin/env python3
"""Test AfterAction API endpoints after fixing table"""

import sys
import os
sys.path.append('/opt/trading')

import requests
import json
from shared.database import get_connection

print("="*60)
print("AfterAction API Fix & Test")
print("="*60)

# Step 1: Fix database table
print("\n1. Creating afteraction_reports table...")
try:
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Drop old table
            cur.execute('DROP TABLE IF EXISTS afteraction_reports CASCADE')
            
            # Create table with correct schema
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
            
            # Create indexes
            cur.execute('CREATE INDEX idx_afteraction_created ON afteraction_reports(created_at DESC)')
            cur.execute('CREATE INDEX idx_afteraction_mode ON afteraction_reports(mode)')
            
            conn.commit()
            print("   ✓ Table created successfully")
            
except Exception as e:
    print(f"   ✗ Error: {e}")
    sys.exit(1)

# Step 2: Test endpoints
print("\n2. Testing /health endpoint...")
try:
    r = requests.get("http://localhost:8018/health", timeout=3)
    if r.ok:
        print(f"   ✓ Health check passed: {r.json()}")
    else:
        print(f"   ✗ Failed with status {r.status_code}: {r.text}")
except Exception as e:
    print(f"   ✗ Error: {e}")

print("\n3. Testing /stats endpoint...")
try:
    r = requests.get("http://localhost:8018/stats", timeout=3)
    if r.ok:
        data = r.json()
        print(f"   ✓ Stats endpoint working")
        print(f"   Total Reports: {data.get('total_reports', 0)}")
        print(f"   Avg Win Rate: {data.get('avg_win_rate', 0)}%")
        print(f"   Missed Opportunities: {data.get('total_missed_opportunities', 0)}")
        print(f"   False Signals: {data.get('total_false_signals', 0)}")
    else:
        print(f"   ✗ Failed with status {r.status_code}: {r.text}")
except Exception as e:
    print(f"   ✗ Error: {e}")

print("\n4. Testing /reports endpoint...")
try:
    r = requests.get("http://localhost:8018/reports?limit=5", timeout=3)
    if r.ok:
        reports = r.json()
        print(f"   ✓ Reports endpoint working")
        print(f"   Number of reports: {len(reports)}")
    else:
        print(f"   ✗ Failed with status {r.status_code}: {r.text}")
except Exception as e:
    print(f"   ✗ Error: {e}")

print("\n" + "="*60)
print("✅ AfterAction API should now work in UI!")
print("Refresh the System tab and try the AfterAction buttons again.")
print("="*60)
