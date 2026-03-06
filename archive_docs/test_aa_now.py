#!/usr/bin/env python3
import requests
import time

print("Waiting for AfterAction API to start...")
time.sleep(3)

print("\nTesting AfterAction API...")
print("="*60)

# Test health
try:
    r = requests.get("http://localhost:8018/health", timeout=5)
    print(f"\n1. Health: {r.status_code}")
    print(f"   Response: {r.json()}")
except Exception as e:
    print(f"\n1. Health: ERROR - {e}")

# Test stats
try:
    r = requests.get("http://localhost:8018/stats", timeout=5)
    print(f"\n2. Stats: {r.status_code}")
    if r.ok:
        print(f"   Response: {r.json()}")
    else:
        print(f"   Error: {r.text}")
except Exception as e:
    print(f"\n2. Stats: ERROR - {e}")

# Test reports
try:
    r = requests.get("http://localhost:8018/reports", timeout=5)
    print(f"\n3. Reports: {r.status_code}")
    if r.ok:
        print(f"   Response: {r.json()}")
    else:
        print(f"   Error: {r.text}")
except Exception as e:
    print(f"\n3. Reports: ERROR - {e}")

print("\n" + "="*60)
print("If all show 200 status codes, the API is working!")
print("Try refreshing your UI now and clicking the AfterAction buttons.")
