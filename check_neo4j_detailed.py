#!/usr/bin/env python3
"""Check what data exists in Neo4j - detailed version"""
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
        print("\n=== NEO4J DATABASE AUDIT ===\n")
        
        print("1. Total nodes in graph...")
        result = session.run("MATCH (n) RETURN count(*) as total")
        for record in result:
            print(f"  Total nodes: {record['total']}\n")
        
        print("2. Node types distribution...")
        result = session.run("MATCH (n) RETURN distinct labels(n)[0] as type ORDER BY type")
        types = [r['type'] for r in result]
        print(f"  Types: {', '.join(types)}\n")
        
        print("3. Transaction nodes by user...")
        result = session.run("MATCH (t:Transaction) RETURN DISTINCT t.user_id as user_id, count(*) as count ORDER BY user_id")
        for record in result:
            print(f"  User {record['user_id']}: {record['count']} transactions")
        print()
        
        print("4. Asset nodes by user...")
        result = session.run("MATCH (a:Asset) RETURN DISTINCT a.user_id as user_id, count(*) as count ORDER BY user_id")
        for record in result:
            print(f"  User {record['user_id']}: {record['count']} assets")
        print()
        
        print("5. Sample transaction details...")
        result = session.run("""
            MATCH (t:Transaction) 
            RETURN t.user_id as user_id, t.description as desc, t.amount as amount LIMIT 5
        """)
        for record in result:
            print(f"  User {record['user_id']}: {record['desc']} = {record['amount']}")
        print()
        
        print("6. Sample asset details...")
        result = session.run("""
            MATCH (a:Asset) 
            RETURN a.user_id as user_id, a.name as name, a.value as value LIMIT 5
        """)
        for record in result:
            print(f"  User {record['user_id']}: {record['name']} = {record['value']}")

try:
    check_graph()
finally:
    driver.close()
