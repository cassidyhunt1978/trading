#!/usr/bin/env python3
"""Quick test script to verify AfterAction integration"""

import requests
import json

print("=" * 60)
print("AfterAction Integration Test")
print("=" * 60)

# Test 1: AfterAction API Health
print("\n1. Testing AfterAction API Health (port 8018)...")
try:
    response = requests.get("http://localhost:8018/health", timeout=3)
    if response.ok:
        print("   ✓ AfterAction API is running")
        print(f"   Response: {response.json()}")
    else:
        print(f"   ✗ Failed with status {response.status_code}")
except Exception as e:
    print(f"   ✗ Error: {e}")

# Test 2: AfterAction Stats
print("\n2. Testing AfterAction Stats endpoint...")
try:
    response = requests.get("http://localhost:8018/stats", timeout=3)
    if response.ok:
        data = response.json()
        print("   ✓ Stats endpoint working")
        print(f"   Total Reports: {data.get('total_reports', 0)}")
        print(f"   Avg Win Rate: {data.get('avg_win_rate', 0)}%")
        print(f"   Missed Opportunities: {data.get('total_missed_opportunities', 0)}")
        print(f"   False Signals: {data.get('total_false_signals', 0)}")
    else:
        print(f"   ✗ Failed with status {response.status_code}")
except Exception as e:
    print(f"   ✗ Error: {e}")

# Test 3: Testing API AfterAction Endpoint
print("\n3. Testing Testing API AfterAction endpoint (port 8019)...")
try:
    response = requests.get("http://localhost:8019/test/afteraction", timeout=10)
    if response.ok:
        data = response.json()
        print("   ✓ Testing API endpoint working")
        print(f"   Status: {data.get('status')}")
        print(f"   Health: {data.get('health')}")
    else:
        print(f"   ✗ Failed with status {response.status_code}")
except Exception as e:
    print(f"   ✗ Error: {e}")

# Test 4: UI Server
print("\n4. Testing UI Server (port 3000)...")
try:
    response = requests.get("http://localhost:3000", timeout=3)
    if response.ok:
        print("   ✓ UI Server is running")
    else:
        print(f"   ✗ Failed with status {response.status_code}")
except Exception as e:
    print(f"   ✗ Error: {e}")

print("\n" + "=" * 60)
print("Test complete! Check UI at http://localhost:3000 (System tab)")
print("=" * 60)
