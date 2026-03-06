#!/usr/bin/env python3
"""Test if AfterAction API responds correctly with table auto-creation fix"""

import requests
import time

print("="*70)
print("AfterAction API Post-Fix Verification")
print("="*70)

# Give API time to start if it was just restarted
print("\nWaiting for API to be ready...")
time.sleep(2)

tests_passed = 0
tests_failed = 0

# Test 1: Health
print("\n1. Testing /health endpoint...")
try:
    r = requests.get("http://localhost:8018/health", timeout=5)
    if r.ok:
        print(f"   ✓ PASS - Status: {r.status_code}, Response: {r.json()}")
        tests_passed += 1
    else:
        print(f"   ✗ FAIL - Status: {r.status_code}")
        tests_failed += 1
except Exception as e:
    print(f"   ✗ FAIL - Error: {e}")
    tests_failed += 1

# Test 2: Stats (this was failing before)
print("\n2. Testing /stats endpoint (previously returned 500 error)...")
try:
    r = requests.get("http://localhost:8018/stats", timeout=5)
    if r.ok:
        data = r.json()
        print(f"   ✓ PASS - Status: {r.status_code}")
        print(f"   Data: Total Reports={data['total_reports']}, Win Rate={data['avg_win_rate']}%")
        tests_passed += 1
    else:
        print(f"   ✗ FAIL - Status: {r.status_code}, Response: {r.text}")
        tests_failed += 1
except Exception as e:
    print(f"   ✗ FAIL - Error: {e}")
    tests_failed += 1

# Test 3: Reports
print("\n3. Testing /reports endpoint...")
try:
    r = requests.get("http://localhost:8018/reports?limit=5", timeout=5)
    if r.ok:
        reports = r.json()
        print(f"   ✓ PASS - Status: {r.status_code}, Reports: {len(reports)}")
        tests_passed += 1
    else:
        print(f"   ✗ FAIL - Status: {r.status_code}, Response: {r.text}")
        tests_failed += 1
except Exception as e:
    print(f"   ✗ FAIL - Error: {e}")
    tests_failed += 1

# Summary
print("\n" + "="*70)
print(f"Results: {tests_passed} passed, {tests_failed} failed")
if tests_failed == 0:
    print("✅ All tests passed! AfterAction API is working correctly.")
    print("\nYou can now:")
    print("1. Refresh the UI (port 8010) and go to System tab")
    print("2. Click the AfterAction buttons - they should work now!")
    print("3. Run your first analysis and see the results")
else:
    print("❌ Some tests failed. Check the AfterAction API logs:")
    print("   tail -50 /opt/trading/logs/afteraction_api.log")
print("="*70)
