#!/usr/bin/env python3
"""Diagnostic script to check user_ids and financial data mismatch"""
import sys
sys.path.insert(0, '/media/muon/New Volume4/ACM_Hack-IOTAs/ACM-GraphMind/backend')

import requests
from pathlib import Path

print("\n" + "="*80)
print("🔍 FINANCIAL SUMMARY DIAGNOSTIC TOOL")
print("="*80)

# Get token from localStorage (simulated from browser)
TEST_TOKEN = input("\n📍 Paste your JWT token from the browser (from DevTools > Application > localStorage > 'token'): ").strip()
if not TEST_TOKEN.startswith('Bearer'):
    TEST_TOKEN = f'Bearer {TEST_TOKEN}'

BASE_URL = "http://localhost:8000"
headers = {"Authorization": TEST_TOKEN}

print(f"\n🔗 Testing with token: {TEST_TOKEN[:50]}...")

# Test 1: Get current user from debug endpoint
print("\n" + "-"*80)
print("1️⃣  AUTHENTICATING - Getting your user details")
print("-"*80)
try:
    response = requests.get(f"{BASE_URL}/user/graph-debug", headers=headers)
    if response.status_code == 200:
        data = response.json()
        current_user = data.get("current_user_id")
        has_data = data.get("current_user_has_data")
        print(f"✅ Your user ID: {current_user}")
        print(f"✅ You have graph data: {has_data}")
        
        print(f"\n2️⃣  YOUR GRAPH DATA:")
        print(f"   Node counts: {data.get('current_user_node_counts', {})}")
        
        print(f"\n3️⃣  ALL USERS IN DATABASE:")
        all_users = data.get("all_users_in_database", [])
        for user in all_users:
            match = "✅ MATCH!" if user == current_user else ""
            print(f"   • {user} {match}")
        
        print(f"\n4️⃣  YOUR STATUS:")
        if has_data:
            print(f"   ✅ YOU HAVE DATA - Fix might be in query execution")
        else:
            print(f"   ⚠️  NO DATA FOUND for your user ID")
            print(f"   ")
            print(f"   This could mean:")
            print(f"   a) Your user_id in JWT doesn't match any data in Neo4j")
            print(f"   b) You haven't sent any financial messages yet")
            print(f"   c) Data exists but under a different user_id")
    else:
        print(f"❌ Error: {response.status_code}")
        print(f"   Response: {response.text}")
except Exception as e:
    print(f"❌ Failed to connect: {e}")

# Test 2: Get financial summary
print("\n" + "-"*80)
print("5️⃣  FINANCIAL SUMMARY ENDPOINT RESULT")
print("-"*80)
try:
    response = requests.get(f"{BASE_URL}/user/financial-summary", headers=headers)
    if response.status_code == 200:
        data = response.json()
        print(f"   Total Invested: ₹{data.get('totalInvested', 0)}")
        print(f"   Total Assets: ₹{data.get('totalAssets', 0)}")
        print(f"   Net Worth: ₹{data.get('netWorth', 0)}")
        print(f"   Banks: {data.get('banks', [])}")
        print(f"   Investments: {data.get('investments', [])}")
        print(f"   Is Empty: {data.get('isEmpty', True)}")
    else:
        print(f"❌ Error: {response.status_code}")
except Exception as e:
    print(f"❌ Failed: {e}")

print("\n" + "="*80)
print("📋 NEXT STEPS:")
print("="*80)
print("1. Check the backend server logs - look for lines starting with [🔍 DEBUG]")
print("2. If your user_id is NOT in the database, that's the issue")
print("3. You may need to send chat messages with financial data to populate the graph")
print("="*80 + "\n")
