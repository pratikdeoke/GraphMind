#!/usr/bin/env python3
"""Test script to verify sidebar financial summary endpoint"""
import requests
import json
import time

API_BASE = "http://localhost:8000"

def test_financial_summary():
    """Test the financial summary endpoint"""
    
    # First, signup to create a test user
    print("1. Creating test user...")
    signup_response = requests.post(
        f"{API_BASE}/auth/signup",
        json={
            "email": f"testuser{int(time.time())}@example.com",
            "password": "TestPassword123!",
            "full_name": "Test User"
        }
    )
    
    if signup_response.status_code not in [200, 201]:
        print(f"Signup failed: {signup_response.status_code}")
        print(f"Response: {signup_response.text}")
        return
    
    signup_data = signup_response.json()
    print(f"✓ User created successfully")
    
    # Now login to get a token
    email = signup_data.get("email") or signup_response.json().get("email")
    print(f"\n2. Logging in as {email}...")
    login_response = requests.post(
        f"{API_BASE}/auth/login",
        json={
            "email": email,
            "password": "TestPassword123!"
        }
    )
    
    if login_response.status_code != 200:
        print(f"Login failed: {login_response.status_code}")
        print(f"Response: {login_response.text}")
        return
    
    token_data = login_response.json()
    token = token_data.get("access_token") or token_data.get("token")
    user_id = token_data.get("user_id")
    print(f"✓ Got token: {token[:20]}...")
    print(f"✓ User ID: {user_id}")
    
    # Now test the financial summary endpoint
    print("\n3. Testing financial summary endpoint...")
    headers = {"Authorization": f"Bearer {token}"}
    
    summary_response = requests.get(
        f"{API_BASE}/user/financial-summary",
        headers=headers
    )
    
    print(f"Status: {summary_response.status_code}")
    print(f"Response:")
    print(json.dumps(summary_response.json(), indent=2))
    
    # Test the debug endpoint
    print("\n4. Testing debug endpoint...")
    debug_response = requests.get(
        f"{API_BASE}/user/graph-debug",
        headers=headers
    )
    
    print(f"Status: {debug_response.status_code}")
    print(f"Graph data:")
    print(json.dumps(debug_response.json(), indent=2))

if __name__ == "__main__":
    test_financial_summary()
