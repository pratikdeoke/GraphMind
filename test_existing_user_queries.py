#!/usr/bin/env python3
"""Test financial summary for users with existing Neo4j data"""
import sys
sys.path.insert(0, '/media/muon/New Volume4/ACM_Hack-IOTAs/ACM-GraphMind/backend')

from neo4j import GraphDatabase
import os
from dotenv import load_dotenv

load_dotenv('/media/muon/New Volume4/ACM_Hack-IOTAs/ACM-GraphMind/backend/.env')

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "graphmind123")

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

def test_query_methods():
    """Test the three Neo4j queries with real existing users"""
    from services.graph.retrieval import GraphRetrieval
    
    retrieval = GraphRetrieval()
    
    # Users we know have data in the database
    test_users = [
        "user_79874e4c31744d56",
        "user_f47d3c2979d942bd"
    ]
    
    print("=== Testing Neo4j Query Methods with Existing Users ===\n")
    
    for user_id in test_users:
        print(f"\n--- Testing user: {user_id} ---")
        
        # Test total invested
        total = retrieval._query_total_invested(user_id)
        print(f"Total invested: {total}")
        
        # Test banks
        banks = retrieval._query_banks(user_id)
        print(f"Banks: {banks}")
        
        # Test investments
        investments = retrieval._query_investments(user_id)
        print(f"Investments: {investments}")
        
        # Simulate full financial summary
        total_assets = sum(inv.get('amount', 0) for inv in investments) if investments else 0
        is_empty = (total == 0.0 and len(banks) == 0 and len(investments) == 0)
        
        print(f"Total assets: {total_assets}")
        print(f"Is empty: {is_empty}")

try:
    test_query_methods()
finally:
    driver.close()
