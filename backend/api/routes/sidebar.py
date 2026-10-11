from fastapi import APIRouter, Depends, Header, status, HTTPException
from typing import Optional, List
from api.models import DocumentUploadResponse
from services.auth.auth_service import auth_service
from services.database.chat_service import ChatService
from services.database.user_service import UserService
from services.graph.retrieval import GraphRetrieval

router = APIRouter()
user_service = UserService()
chat_service = ChatService()
graph_retrieval = GraphRetrieval()

async def get_current_user_id(authorization: Optional[str] = Header(None)) -> str:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise ValueError()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = auth_service.verify_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token claims",
        )
    return user_id

@router.get(
    "/documents/list",
    response_model=List[dict],
    tags=["documents"],
    summary="List all uploaded documents for the user",
    description="Return all uploaded documents for the authenticated user."
)
async def list_uploaded_documents(
    pg_user_id: str = Depends(get_current_user_id)
):
    # This assumes uploaded documents are stored as chat messages with intent 'MEMORY' and source 'document_upload'.
    docs = []
    messages = chat_service.get_user_recent_messages(pg_user_id, limit=100)
    for msg in messages:
        if msg.get('memory_storage', {}).get('source') == 'document_upload':
            docs.append({
                'name': msg.get('memory_storage', {}).get('document_name', 'Unknown'),
                'size': msg.get('memory_storage', {}).get('text_length', 0),
                'format': msg.get('memory_storage', {}).get('format', 'Unknown'),
                'timestamp': msg.get('created_at')
            })
    return docs

@router.get(
    "/user/financial-summary",
    tags=["user"],
    summary="Get user's financial summary with banks and investments",
    description="Return enhanced financial summary with real data from graph."
)
async def get_financial_summary(
    pg_user_id: str = Depends(get_current_user_id)
):
    """
    Fetch financial summary from Neo4j graph:
    - Total invested (sum of transactions)
    - Banks (entities with bank-related names)
    - Investments (assets linked to transactions)
    - Net worth calculation
    """
    # Get neo4j_user_id from PostgreSQL (chat also does this)
    user = user_service.get_user_by_id(pg_user_id)
    if not user:
        print(f"[❌ ERROR] User not found: {pg_user_id}")
        return {
            "totalInvested": 0,
            "totalAssets": 0,
            "netWorth": 0,
            "banks": [],
            "investments": [],
            "isEmpty": True
        }
    
    neo4j_user_id = user.get("neo4j_user_id")
    print(f"\n[📊 FINANCIAL SUMMARY] PostgreSQL user_id: {pg_user_id}")
    print(f"[📊 FINANCIAL SUMMARY] Neo4j user_id: {neo4j_user_id}")
    
    try:
        # Query total invested from transactions
        total_invested = graph_retrieval._query_total_invested(neo4j_user_id)
        print(f"[💰 TOTAL INVESTED] {neo4j_user_id}: ₹{total_invested}")
        
        # Query banks from the graph
        banks = graph_retrieval._query_banks(neo4j_user_id)
        print(f"[🏦 BANKS] {neo4j_user_id}: {len(banks)} banks found - {banks}")
        
        # Query investments (assets with amounts)
        investments = graph_retrieval._query_investments(neo4j_user_id)
        print(f"[📈 INVESTMENTS] {neo4j_user_id}: {len(investments)} investments found")
        for inv in investments:
            print(f"   • {inv.get('name')}: ₹{inv.get('amount')}")
        
        # Calculate total assets
        total_assets = sum(inv.get('amount', 0) for inv in investments) if investments else 0
        print(f"[💵 TOTAL ASSETS] {neo4j_user_id}: ₹{total_assets}")
        
        # Calculate net worth (simplified: total_assets - total_invested assumptions)
        net_worth = total_assets if total_assets > 0 else 0
        
        # Check if user has any financial data
        is_empty = total_invested == 0 and len(banks) == 0 and len(investments) == 0
        print(f"[⚠️ EMPTY STATE] {neo4j_user_id}: {is_empty}")
        
        if is_empty:
            print(f"[ℹ️ NOTE] User {neo4j_user_id} has no financial data in graph yet")
            print(f"[💡 SOLUTION] Send a financial message like: 'I invested ₹50000 in HDFC Mutual Fund'")
        
        response = {
            "totalInvested": total_invested,
            "totalAssets": total_assets,
            "netWorth": net_worth,
            "banks": banks,
            "investments": investments,
            "isEmpty": is_empty
        }
        print(f"[✅ RESPONSE] {pg_user_id}: {response}")
        return response
    except Exception as e:
        print(f"Error fetching financial summary: {e}")
        import traceback
        traceback.print_exc()
        # Return empty state on error
        return {
            "totalInvested": 0,
            "totalAssets": 0,
            "netWorth": 0,
            "banks": [],
            "investments": [],
            "isEmpty": True
        }

@router.get(
    "/user/graph-debug",
    tags=["debug"],
    summary="Debug: Show all graph data for user"
)
async def debug_graph_data(
    pg_user_id: str = Depends(get_current_user_id)
):
    """Debug endpoint to show all nodes/relationships for user AND all users in database"""
    if not graph_retrieval.driver:
        return {"error": "Neo4j not connected"}
    
    # Get neo4j_user_id from PostgreSQL
    user = user_service.get_user_by_id(pg_user_id)
    if not user:
        return {"error": f"User not found: {pg_user_id}"}
    
    neo4j_user_id = user.get("neo4j_user_id")
    
    try:
        with graph_retrieval.driver.session() as session:
            print(f"\n\n{'='*80}")
            print(f"[🔍 DEBUG] Graph Debug for User: {pg_user_id} (neo4j_id: {neo4j_user_id})")
            print(f"{'='*80}")
            
            # Get all nodes for THIS user using neo4j_user_id
            result = session.run("""
                MATCH (n {user_id: $user_id})
                RETURN labels(n) as labels, properties(n) as props
                LIMIT 50
            """, user_id=neo4j_user_id)
            
            nodes = [{"labels": r["labels"], "props": r["props"]} for r in result]
            
            # Count nodes by type for THIS user
            result2 = session.run("""
                MATCH (n {user_id: $user_id})
                RETURN labels(n)[0] as type, count(*) as count
                ORDER BY type
            """, user_id=neo4j_user_id)
            
            counts = {r["type"]: r["count"] for r in result2}
            print(f"[📊] Current user node counts: {counts}")
            
            # Show ALL USERS in database
            print(f"\n[🌍] ALL USERS IN DATABASE:")
            result3 = session.run("""
                MATCH (n)
                WHERE n.user_id IS NOT NULL
                RETURN DISTINCT n.user_id as user_id
                ORDER BY n.user_id
            """)
            
            all_users = []
            for record in result3:
                user_id = record["user_id"]
                all_users.append(user_id)
                
                # Count this user's data
                result_counts = session.run("""
                    MATCH (tx:Transaction {user_id: $uid})
                    RETURN count(*) as tx_count
                """, uid=user_id)
                tx_count = result_counts.single()["tx_count"]
                
                result_counts = session.run("""
                    MATCH (a:Asset {user_id: $uid})
                    RETURN count(*) as asset_count
                """, uid=user_id)
                asset_count = result_counts.single()["asset_count"]
                
                status = "✓ HAS DATA" if (tx_count > 0 or asset_count > 0) else "- no data"
                is_current = "👤 CURRENT USER" if user_id == neo4j_user_id else ""
                print(f"  • {user_id}: {tx_count} transactions, {asset_count} assets  {status}  {is_current}")
            
            print(f"\n[📌] CURRENT USER (PostgreSQL): {pg_user_id}")
            print(f"[📌] CURRENT USER (Neo4j): {neo4j_user_id}")
            print(f"[✓] Match found: {neo4j_user_id in all_users}")
            print(f"{'='*80}\n")
            
            return {
                "pg_user_id": pg_user_id,
                "neo4j_user_id": neo4j_user_id,
                "current_user_node_counts": counts,
                "current_user_sample_nodes": nodes[:10],
                "all_users_in_database": all_users,
                "current_user_has_data": len(counts) > 0 and sum(counts.values()) > 0
            }
    except Exception as e:
        print(f"Debug error: {e}")
        return {"error": str(e)}
