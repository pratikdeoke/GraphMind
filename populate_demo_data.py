#!/usr/bin/env python3
"""Populate demo financial data for a user"""
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

def populate_demo_data(user_id):
    """Create demo financial data for the user"""
    with driver.session() as session:
        print(f"\n📊 Creating demo financial data for user: {user_id}\n")
        
        # 1. Create Transaction nodes (investments)
        transactions = [
            {"description": "HDFC Mutual Fund Investment", "amount": 50000, "type": "investment"},
            {"description": "Stock Market Investment - TCS", "amount": 30000, "type": "investment"},
            {"description": "SBI Savings Account", "amount": 100000, "type": "savings"},
            {"description": "PPF Investment", "amount": 20000, "type": "investment"},
        ]
        
        for tx in transactions:
            session.run("""
                CREATE (t:Transaction {
                    user_id: $user_id,
                    description: $desc,
                    amount: $amount,
                    type: $type,
                    timestamp: datetime()
                })
            """, user_id=user_id, desc=tx['description'], amount=tx['amount'], type=tx['type'])
            print(f"✅ Created: {tx['description']} - ₹{tx['amount']}")
        
        # 2. Create Asset nodes
        assets = [
            {"name": "HDFC Mutual Fund", "value": 55000},
            {"name": "TCS Stock", "value": 35000},
            {"name": "SBI Savings Account", "value": 105000},
            {"name": "PPF Account", "value": 21000},
        ]
        
        for asset in assets:
            session.run("""
                CREATE (a:Asset {
                    user_id: $user_id,
                    name: $name,
                    value: $value,
                    timestamp: datetime()
                })
            """, user_id=user_id, name=asset['name'], value=asset['value'])
            print(f"✅ Created asset: {asset['name']} - ₹{asset['value']}")
        
        # 3. Link transactions to assets (AFFECTS_ASSET relationship)
        session.run("""
            MATCH (t:Transaction {user_id: $user_id, description: "HDFC Mutual Fund Investment"})
            MATCH (a:Asset {user_id: $user_id, name: "HDFC Mutual Fund"})
            CREATE (t)-[:AFFECTS_ASSET]->(a)
        """, user_id=user_id)
        print(f"✅ Linked: HDFC Mutual Fund Investment → Asset")
        
        session.run("""
            MATCH (t:Transaction {user_id: $user_id, description: "Stock Market Investment - TCS"})
            MATCH (a:Asset {user_id: $user_id, name: "TCS Stock"})
            CREATE (t)-[:AFFECTS_ASSET]->(a)
        """, user_id=user_id)
        print(f"✅ Linked: TCS Stock Investment → Asset")
        
        # Verify
        result = session.run("""
            MATCH (n {user_id: $user_id})
            RETURN labels(n)[0] as type, count(*) as count
        """, user_id=user_id)
        
        print(f"\n📈 Summary:")
        for record in result:
            print(f"   • {record['type']}: {record['count']} nodes")
        
        print(f"\n✨ Done! Refresh your app to see the data in the sidebar!")

if __name__ == "__main__":
    # You can change this to your actual user_id from the database
    user_id = input("Enter your user_id (or press Enter for default 'w@gmail.com'): ").strip()
    if not user_id:
        user_id = "w@gmail.com"
    
    try:
        populate_demo_data(user_id)
    finally:
        driver.close()
