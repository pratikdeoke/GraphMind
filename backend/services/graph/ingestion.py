"""
Graph Ingestion Service - Store structured data in Neo4j.

Handles:
- Node creation with user isolation
- Relationship creation
- Duplicate detection (MERGE logic)
- Performance tracking
"""

from typing import Dict, List, Any, Optional
from datetime import datetime
import uuid
from neo4j import GraphDatabase
from config.settings import Settings
from services.encryption.crypto_service import (
    encrypt_field,
    encrypt_node_properties,
)


class GraphIngestion:
    """
    Handles ingestion of structured data into Neo4j graph.
    """
    
    def __init__(self):
        """Initialize Neo4j connection."""
        try:
            self.driver = GraphDatabase.driver(
                Settings.NEO4J_URI,
                auth=(Settings.NEO4J_USER, Settings.NEO4J_PASSWORD)
            )
            # Test connection
            self.driver.verify_connectivity()
        except Exception as e:
            print(f"Warning: Could not connect to Neo4j: {e}")
            self.driver = None
    
    def ingest_memory(
        self, 
        user_id: str,
        message_text: str,
        facts: List[Dict[str, Any]],
        nodes: List[Dict[str, Any]], 
        relationships: List[Dict[str, Any]],
        skip_contradiction_detection: bool = False,
        source_type: str = "chat",
        encryption_key: Optional[bytes] = None
        source_type: str = "chat"
    ) -> Dict[str, int]:
        """
        Ingest message, facts, nodes and relationships into the graph.
        
        Args:
            user_id: User identifier
            message_text: Original user message
            facts: List of extracted facts
            nodes: List of node dictionaries
            relationships: List of relationship dictionaries
            skip_contradiction_detection: Whether to skip contradiction detection
            source_type: Source type for the message node ('chat' or 'document')
            encryption_key: Optional 32-byte AES key. When provided, sensitive
                fields (see crypto_service.FIELDS_TO_ENCRYPT) are encrypted with
                AES-256-GCM before being written to Neo4j (E2EE at rest).
                
            
        Returns:
            Dictionary with counts of nodes and relationships created
        """
        if not self.driver:
            print("Warning: Neo4j driver not initialized, skipping ingestion")
            return {"nodes_created": 0, "relationships_created": 0, "facts_created": 0}
        
        nodes_created = 0
        relationships_created = 0
        facts_created = 0
        message_id = None
        
        try:
            with self.driver.session() as session:
                # 1. Ensure User node exists
                self._ensure_user_node(session, user_id)
                
                # 2. Create Message node (encrypt its text when E2EE is on)
                message_id = self._create_message_node(
                    session, user_id, message_text,
                    source_type=source_type, encryption_key=encryption_key
                )
                # 2. Create Message node
                message_id = self._create_message_node(session, user_id, message_text, source_type=source_type)
                
                # 3. Create Fact nodes
                fact_ids = []  # list of (fact_id, fact_text)
                for fact in facts:
                    fact_id = self._create_fact_node(
                        session, user_id, fact, message_id,
                        encryption_key=encryption_key
                    )
                    fact_id = self._create_fact_node(session, user_id, fact, message_id)
                    if fact_id:
                        fact_ids.append((fact_id, fact.get("text", "")))
                        facts_created += 1
                
                # 4. Create/merge entity nodes
                node_map = {}  # Track created nodes: {type: [id1, id2, ...]}
                for node in nodes:
                    self._merge_node(session, user_id, node, encryption_key=encryption_key)
                    self._merge_node(session, user_id, node)
                    nodes_created += 1
                    node_type = node.get("type")
                    node_id = node.get("properties", {}).get("id")
                    if node_type and node_id:
                        if node_type not in node_map:
                            node_map[node_type] = []
                        node_map[node_type].append(node_id)
                
                
                # 5. Create canonical relationships (truth layer)
                # Link all transactions and assets (can be multiple)
                transaction_ids = node_map.get("Transaction", [])
                asset_ids = node_map.get("Asset", [])
                
                for transaction_id in transaction_ids:
                    # Core ownership: User made this transaction
                    self._link_user_made_transaction(session, user_id, transaction_id)
                    relationships_created += 1
                    
                    # Link each transaction to all assets
                    for asset_id in asset_ids:
                        self._link_transaction_affects_asset(session, user_id, transaction_id, asset_id)
                        relationships_created += 1
                
                # 6. Create extracted relationships (additional context)
                for rel in relationships:
                    self._merge_relationship(session, user_id, rel)
                    relationships_created += 1
                
                # 7. Link facts to structured nodes using CONFIRMS (evidence layer)
                # Facts should CONFIRM structured data (Transaction, Asset, Goal)
                transaction_ids = node_map.get("Transaction", [])
                asset_ids = node_map.get("Asset", [])
                goal_ids = node_map.get("Goal", [])
                
                for fact_id, _ in fact_ids:
                    # Primary: Link fact to all Transaction nodes (if exist)
                    if transaction_ids:
                        for transaction_id in transaction_ids:
                            self._link_fact_confirms(session, user_id, fact_id, transaction_id, "Transaction")
                        
                        # Also link Fact to all Assets via RELATES_TO for semantic recall
                        for asset_id in asset_ids:
                            self._link_fact_to_node(session, user_id, fact_id, asset_id, "Asset")
                    
                    # Secondary: Link fact to all Asset/Goal nodes (if exists and no transaction)
                    elif asset_ids:
                        for asset_id in asset_ids:
                            self._link_fact_confirms(session, user_id, fact_id, asset_id, "Asset")
                    elif goal_ids:
                        for goal_id in goal_ids:
                            self._link_fact_confirms(session, user_id, fact_id, goal_id, "Goal")
                    
                    # Fallback: Link to entities by name (for generic facts)
                    else:
                        for node in nodes:
                            node_name = node.get("properties", {}).get("name")
                            if node_name:
                                self._link_fact_to_entity_by_name(session, user_id, fact_id, node_name)
        
                # 8. Detect and mark contradictions for new facts (skip for document ingestion)
                if not skip_contradiction_detection:
                    for fact_id, fact_text in fact_ids:
                        if fact_text:
                            self._detect_and_mark_contradictions(session, user_id, fact_id, fact_text, nodes)
        
        except Exception as e:
            print(f"Error during graph ingestion: {e}")
            raise
        
        return {
            "nodes_created": nodes_created,
            "relationships_created": relationships_created,
            "facts_created": facts_created
        }
    
    def _ensure_user_node(self, session, user_id: str):
        """Ensure a User node exists for the given user_id."""
        query = """
        MERGE (u:User {id: $user_id})
        SET u.last_active = datetime()
        RETURN u
        """
        session.run(query, user_id=user_id)
    
    def _create_message_node(self, session, user_id: str, text: str, source_type: str = "chat", encryption_key: Optional[bytes] = None) -> str:
        """Create a Message node and link to User.

        When an encryption_key is supplied, the message text is encrypted with
        AES-256-GCM before being written (E2EE at rest).
        """
        message_id = f"msg_{uuid.uuid4().hex[:12]}"
        stored_text = encrypt_field(text, encryption_key) if encryption_key else text
    def _create_message_node(self, session, user_id: str, text: str, source_type: str = "chat") -> str:
        """Create a Message node and link to User."""
        message_id = f"msg_{uuid.uuid4().hex[:12]}"
        query = """
        MATCH (u:User {id: $user_id})
        CREATE (m:Message {
            id: $message_id,
            user_id: $user_id,
            text: $text,
            timestamp: datetime(),
            source_type: $source_type,
            created_at: datetime()
        })
        CREATE (u)-[:OWNS_MESSAGE]->(m)
        RETURN m.id as id
        """
        result = session.run(query, user_id=user_id, message_id=message_id, text=stored_text, source_type=source_type)
        record = result.single()
        return record["id"] if record else message_id
    
    def _create_fact_node(self, session, user_id: str, fact: Dict[str, Any], message_id: str, encryption_key: Optional[bytes] = None) -> Optional[str]:
        """Create a Fact node with deduplication - reinforce if exists.

        When an encryption_key is supplied, the fact text is encrypted with
        AES-256-GCM before storage (E2EE at rest).

        NOTE (E2EE trade-off): AES-256-GCM uses a random nonce, so identical
        plaintext produces different ciphertext. Exact-text deduplication and
        the contradiction heuristic therefore cannot match against already
        encrypted facts; under encryption each incoming fact is stored as a new
        node. This is an inherent and accepted limitation of encrypting data at
        rest while keeping the key client-side.
        """
        result = session.run(query, user_id=user_id, message_id=message_id, text=text, source_type=source_type)
        record = result.single()
        return record["id"] if record else message_id
    
    def _create_fact_node(self, session, user_id: str, fact: Dict[str, Any], message_id: str) -> Optional[str]:
        """Create a Fact node with deduplication - reinforce if exists."""
        fact_text = fact.get("text", "")
        confidence = fact.get("confidence", 0.8)
        
        if not fact_text:
            return None

        # Value actually persisted (ciphertext when E2EE is enabled).
        stored_fact_text = encrypt_field(fact_text, encryption_key) if encryption_key else fact_text
        
        # Check if fact already exists (deduplication).
        # Under encryption this compares ciphertext and will not match existing
        # nodes (non-deterministic GCM), so new facts are created instead.
        
        # Check if fact already exists (deduplication)
        check_query = """
        MATCH (f:Fact {user_id: $user_id})
        WHERE f.text = $fact_text
        RETURN f.id as id
        """
        
        result = session.run(check_query, user_id=user_id, fact_text=stored_fact_text)
        result = session.run(check_query, user_id=user_id, fact_text=fact_text)
        existing = result.single()
        
        if existing:
            # Fact exists - reinforce it
            fact_id = existing["id"]
            reinforce_query = """
            MATCH (f:Fact {id: $fact_id, user_id: $user_id})
            SET f.reinforcement_count = coalesce(f.reinforcement_count, 0) + 1,
                f.last_reinforced = datetime(),
                f.confidence = ($confidence + f.confidence) / 2
            RETURN f.id as id
            """
            session.run(reinforce_query, fact_id=fact_id, user_id=user_id, confidence=confidence)
            print(f"Reinforced existing fact: {fact_id}")
            return fact_id
        
        # Fact doesn't exist - create new
        fact_id = f"fact_{uuid.uuid4().hex[:12]}"
        create_query = """
        MATCH (u:User {id: $user_id})
        MATCH (m:Message {id: $message_id, user_id: $user_id})
        CREATE (f:Fact {
            id: $fact_id,
            user_id: $user_id,
            text: $fact_text,
            confidence: $confidence,
            reinforcement_count: 0,
            timestamp: datetime(),
            last_reinforced: datetime(),
            created_at: datetime(),
            updated_at: datetime()
        })
        CREATE (m)-[:DERIVED_FACT]->(f)
        RETURN f.id as id
        """
        result = session.run(
            create_query,
            user_id=user_id,
            message_id=message_id,
            fact_id=fact_id,
            fact_text=stored_fact_text,
            fact_text=fact_text,
            confidence=confidence
        )
        record = result.single()
        return record["id"] if record else fact_id
    
    def _link_fact_to_entity_by_name(self, session, user_id: str, fact_id: str, entity_name: str):
        """Link a Fact to an Entity using RELATES_TO relationship (fallback for generic entities)."""
        query = """
        MATCH (f:Fact {id: $fact_id, user_id: $user_id})
        MATCH (e {name: $entity_name, user_id: $user_id})
        MERGE (f)-[:RELATES_TO]->(e)
        """
        try:
            session.run(query, fact_id=fact_id, entity_name=entity_name, user_id=user_id)
        except Exception as e:
            print(f"Warning: Could not link fact to entity: {e}")
    
    def _link_fact_to_node(self, session, user_id: str, fact_id: str, node_id: str, node_type: str):
        """Link a Fact to a specific node by ID using RELATES_TO (for semantic recall)."""
        query = f"""
        MATCH (f:Fact {{id: $fact_id, user_id: $user_id}})
        MATCH (n:{node_type} {{id: $node_id, user_id: $user_id}})
        MERGE (f)-[:RELATES_TO]->(n)
        """
        try:
            session.run(query, fact_id=fact_id, node_id=node_id, user_id=user_id)
            print(f"Linked Fact {fact_id} → RELATES_TO → {node_type} {node_id}")
        except Exception as e:
            print(f"Warning: Could not link fact to {node_type}: {e}")
    
    def _link_fact_confirms(self, session, user_id: str, fact_id: str, node_id: str, node_type: str):
        """Link a Fact to structured node using CONFIRMS relationship (canonical pattern)."""
        query = f"""
        MATCH (f:Fact {{id: $fact_id, user_id: $user_id}})
        MATCH (n:{node_type} {{id: $node_id, user_id: $user_id}})
        MERGE (f)-[:CONFIRMS]->(n)
        """
        try:
            session.run(query, fact_id=fact_id, node_id=node_id, user_id=user_id)
            print(f"Linked Fact {fact_id} → CONFIRMS → {node_type} {node_id}")
        except Exception as e:
            print(f"Warning: Could not link fact to {node_type}: {e}")
    
    def _link_user_made_transaction(self, session, user_id: str, transaction_id: str):
        """Create canonical User → MADE_TRANSACTION → Transaction relationship."""
        query = """
        MATCH (u:User {id: $user_id})
        MATCH (t:Transaction {id: $transaction_id, user_id: $user_id})
        MERGE (u)-[:MADE_TRANSACTION]->(t)
        """
        try:
            session.run(query, user_id=user_id, transaction_id=transaction_id)
            print(f"Linked User {user_id} → MADE_TRANSACTION → {transaction_id}")
        except Exception as e:
            print(f"Warning: Could not link user to transaction: {e}")
    
    def _link_transaction_affects_asset(self, session, user_id: str, transaction_id: str, asset_id: str):
        """Create canonical Transaction → AFFECTS_ASSET → Asset relationship."""
        query = """
        MATCH (t:Transaction {id: $transaction_id, user_id: $user_id})
        MATCH (a:Asset {id: $asset_id, user_id: $user_id})
        MERGE (t)-[:AFFECTS_ASSET]->(a)
        """
        try:
            session.run(query, transaction_id=transaction_id, asset_id=asset_id, user_id=user_id)
            print(f"Linked Transaction {transaction_id} → AFFECTS_ASSET → {asset_id}")
        except Exception as e:
            print(f"Warning: Could not link transaction to asset: {e}")
    
    def _merge_node(self, session, user_id: str, node: Dict[str, Any], encryption_key: Optional[bytes] = None):
    def _merge_node(self, session, user_id: str, node: Dict[str, Any]):
        """
        Merge a single node into the graph.
        
        Uses MERGE to avoid duplicates.
        Adds user_id, metadata, and reinforcement fields automatically.

        When an encryption_key is supplied, sensitive fields listed in
        crypto_service.FIELDS_TO_ENCRYPT (amount, value, price, notes,
        description, ...) are encrypted with AES-256-GCM before storage.
        Structural fields (id, user_id, name, entity_type, timestamps) are left
        in plaintext so graph traversal and MERGE keys keep working.
        """
        node_type = node.get("type", "Entity")
        properties = node.get("properties", {})
        
        # Ensure node has an ID
        if "id" not in properties:
            properties["id"] = f"{node_type.lower()}_{uuid.uuid4().hex[:8]}"
        
        # Add user_id for isolation
        properties["user_id"] = user_id
        
        # Add metadata fields if not present
        if "source_type" not in properties:
            properties["source_type"] = "user_input"

        # Encrypt sensitive fields for E2EE (id/user_id/name are untouched).
        if encryption_key:
            properties = encrypt_node_properties(properties, encryption_key)
        
        # Create Cypher query with labels and metadata
        # Note: Only Message has OWNS_MESSAGE edge from User
        # Fact is linked via Message->DERIVED_FACT->Fact
        # Transaction is linked via User->MADE_TRANSACTION->Transaction
        # Asset is linked via Transaction->AFFECTS_ASSET->Asset
        query = f"""
        MERGE (n:{node_type} {{id: $id, user_id: $user_id}})
        ON CREATE SET 
            n.created_at = datetime(),
            n.timestamp = datetime(),
            n.confidence = 0.8,
            n.reinforcement_count = 0,
            n.last_reinforced = datetime()
        SET n += $properties, 
            n.updated_at = datetime()
        RETURN n
        """
        
        session.run(
            query,
            id=properties["id"],
            user_id=user_id,
            properties=properties
        )
    
    def _merge_relationship(self, session, user_id: str, relationship: Dict[str, Any]):
        """
        Merge a relationship between two nodes.
        
        Ensures both nodes exist before creating relationship.
        Supports matching by name or id.
        """
        rel_type = relationship.get("type", "RELATED_TO")
        from_type = relationship.get("from_type", "Entity")
        to_type = relationship.get("to_type", "Entity")
        from_name = relationship.get("from_name")
        to_name = relationship.get("to_name")
        from_id = relationship.get("from_id")
        to_id = relationship.get("to_id")
        properties = relationship.get("properties", {})
        
        # Build source node match
        if from_type == "User":
            from_match = f"(a:User {{id: $user_id}})"
            from_params = {"user_id": user_id}
        elif from_id:
            # Match by ID (for Transaction, Asset, etc.)
            from_match = f"(a:{from_type} {{id: $from_id, user_id: $user_id}})"
            from_params = {"from_id": from_id, "user_id": user_id}
        else:
            # Match by name (fallback)
            from_match = f"(a:{from_type} {{name: $from_name, user_id: $user_id}})"
            from_params = {"from_name": from_name, "user_id": user_id}
        
        # Build target node match
        if to_id:
            # Match by ID
            to_match = f"(b:{to_type} {{id: $to_id, user_id: $user_id}})"
            to_params = {"to_id": to_id, "user_id": user_id}
        else:
            # Match by name
            to_match = f"(b:{to_type} {{name: $to_name, user_id: $user_id}})"
            to_params = {"to_name": to_name, "user_id": user_id}
        
        # Build relationship query
        query = f"""
        MATCH {from_match}
        MATCH {to_match}
        MERGE (a)-[r:{rel_type}]->(b)
        ON CREATE SET r.created_at = datetime()
        SET r += $properties, r.updated_at = datetime()
        RETURN r
        """
        
        params = {**from_params, **to_params, "properties": properties}
        
        try:
            session.run(query, **params)
        except Exception as e:
            print(f"Warning: Could not create relationship {rel_type}: {e}")
    
    def _detect_and_mark_contradictions(
        self,
        session,
        user_id: str,
        new_fact_id: str,
        new_fact_text: str,
        nodes: List[Dict[str, Any]]
    ):
        """
        After creating a new fact, find existing facts about the same entities
        that may contradict the new one, create CONTRADICTS edges, and reduce
        confidence of the older facts.

        Heuristic (strict): two facts are only treated as contradicting when they
        (a) share a concrete entity anchor (a proper noun such as "HDFC", "TCS",
        "Apple") present in BOTH facts, (b) have high content-word overlap, and
        (c) mention different numeric values. This prevents sibling facts that
        merely share template words (e.g. "User holds N shares of X ... value Y")
        from being wrongly flagged against each other.
        """
        import re

        STOP_WORDS = {"i", "a", "in", "of", "the", "is", "my", "to",
                      "and", "or", "at", "for", "have", "has", "had",
                      "by", "it", "be", "an", "on", "user", "that"}

        COMMON_CAPS = {"user", "according", "this", "the", "october",
                       "january", "february", "march", "april", "may", "june",
                       "july", "august", "september", "november", "december"}

        def significant_words(text: str):
            tokens = re.findall(r'[a-z0-9]+', text.lower())
            return set(t for t in tokens if t not in STOP_WORDS and len(t) > 1)

        def proper_nouns(text: str):
            """Entity anchors: capitalised words (excluding sentence starters)."""
            tokens = re.findall(r'\b[A-Za-z][a-zA-Z]+\b', text)
            return {t.lower() for t in tokens
                    if t[0].isupper() and t.lower() not in COMMON_CAPS}

        new_words = significant_words(new_fact_text)
        if not new_words:
            return

        new_anchors = proper_nouns(new_fact_text)
        # Without a concrete entity anchor we cannot safely judge a contradiction.
        if not new_anchors:
            return

        # Find existing facts for this user (excluding the new one)
        find_query = """
        MATCH (f:Fact {user_id: $user_id})
        WHERE f.id <> $new_fact_id
        RETURN f.id AS fact_id, f.text AS fact_text, f.confidence AS confidence
        ORDER BY f.created_at DESC
        LIMIT 30
        """
        result = session.run(find_query, user_id=user_id, new_fact_id=new_fact_id)
        candidates = [
            {"fact_id": r["fact_id"], "fact_text": r["fact_text"], "confidence": r["confidence"]}
            for r in result if r["fact_text"]
        ]

        for candidate in candidates:
            old_words = significant_words(candidate["fact_text"])
            overlap = new_words & old_words

            min_size = min(len(new_words), len(old_words)) or 1
            overlap_ratio = len(overlap) / min_size

            # CRITICAL: both facts must reference the SAME concrete entity.
            old_anchors = proper_nouns(candidate["fact_text"])
            shared_anchors = new_anchors & old_anchors
            if not shared_anchors:
                continue  # different subjects → not a contradiction

            # Check if both contain numbers (possibly conflicting amounts)
            new_nums = set(re.findall(r'\d+', new_fact_text))
            old_nums = set(re.findall(r'\d+', candidate["fact_text"]))
            conflicting_amounts = bool(new_nums and old_nums and new_nums != old_nums)

            is_contradiction = (
                overlap_ratio >= 0.4 and bool(shared_anchors) and conflicting_amounts
            )

            if is_contradiction:
                print(f"[Contradiction] Old: '{candidate['fact_text']}' vs New: '{new_fact_text}'")
                mark_query = """
                MATCH (old:Fact {id: $old_id, user_id: $user_id})
                MATCH (new:Fact {id: $new_id, user_id: $user_id})
                MERGE (old)-[:CONTRADICTS]->(new)
                SET old.confidence = old.confidence * 0.5,
                    old.updated_at = datetime()
                """
                try:
                    session.run(
                        mark_query,
                        old_id=candidate["fact_id"],
                        new_id=new_fact_id,
                        user_id=user_id
                    )
                    print(f"Marked CONTRADICTS: {candidate['fact_id']} → {new_fact_id}")
                except Exception as e:
                    print(f"Warning: Could not mark contradiction: {e}")

    def close(self):
        """Close Neo4j connection."""
        if self.driver:
            self.driver.close()
