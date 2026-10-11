#!/usr/bin/env python3
"""Test current user ID and financial summary endpoint"""
import sys
sys.path.insert(0, '/media/muon/New Volume4/ACM_Hack-IOTAs/ACM-GraphMind/backend')

import requests
import json
from dotenv import load_dotenv
import os

load_dotenv('/media/muon/New Volume4/ACM_Hack-IOTAs/ACM-GraphMind/backend/.env')

BASE_URL = "http://localhost:8000"

# First, let's check what your current session/token is
# We'll need you to provide a token or login

print("=== FINANCIAL SUMMARY TEST ===\n")
print("This script tests the financial summary endpoint.")
print("You need to provide a JWT token from your current browser session.\n")

token = input("Paste your Authorization token (from browser DevTools -> Network -> copy Authorization header): ").strip()

if not token.startswith("Bearer "):
    token = f"Bearer {token}"

# Test the endpoint
headers = {"Authorization": token}

print("\n1. Testing financial-summary endpoint...")
try:
    response = requests.get(f"{BASE_URL}/api/v1/user/financial-summary", headers=headers)
    print(f"  Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"  Response: {json.dumps(data, indent=2)}")
    else:
        print(f"  Error: {response.text}")
except Exception as e:
    print(f"  Error: {e}")

print("\n2. Testing graph-debug endpoint...")
try:
    response = requests.get(f"{BASE_URL}/api/v1/user/graph-debug", headers=headers)
    print(f"  Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"  Your user ID: {data.get('user_id')}")
        print(f"  Your nodes: {json.dumps(data.get('nodes'), indent=2)}")
    else:
        print(f"  Error: {response.text}")
except Exception as e:
    print(f"  Error: {e}")
