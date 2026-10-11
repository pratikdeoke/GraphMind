#!/usr/bin/env python3
"""Check what data exists in Neo4j"""
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

def check_graph():
    with driver.session() as session:
        print("1. Checking total nodes in graph...")
        result = session.run("MATCH (n) RETURN count(*) as total")
        for record in result:
            print(f"  Total nodes: {record['total']}")
        
        print("\n2. Checking node types...")
        result = session.run("MATCH (n) RETURN distinct labels(n)[0] as type")
        types = [r['type'] for r in result]
        print(f"  Node types found: {types}")
        
        print("\n2. Checking users with transactions...")
        result = session.run("""
            MATCH (u:User)-[:MADE_TRANSACTION]->(t:Transaction)
            RETURN u.id as user_id, count(t) as tx_count
            LIMIT 5
        """)
        
        users = list(result)
        if users:
            for record in users:
                print(f"  User {record['user_id']}: {record['tx_count']} transactions")
        else:
            print("  No users have transactions yet")
        
        print("\n3. Checking users with assets...")
        result = session.run("""
            MATCH (u:User), (a:Asset {user_id: u.id})
            RETURN u.id as user_id, count(a) as asset_count
            LIMIT 5
        """)
        
        users = list(result)
        if users:
            for record in users:
                print(f"  User {record['user_id']}: {record['asset_count']} assets")
        else:
            print("  No users have assets yet")

try:
    check_graph()
finally:
    driver.close()
