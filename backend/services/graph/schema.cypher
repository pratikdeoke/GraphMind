// ======================================================
// GRAPHMIND - USER SCOPED MEMORY GRAPH SCHEMA
// Production Ready - Hybrid Graph + RAG Architecture
// ======================================================



// ======================================================
// 1. USER CONSTRAINT
// ======================================================

CREATE CONSTRAINT user_id_unique IF NOT EXISTS
FOR (u:User)
REQUIRE u.id IS UNIQUE;



// ======================================================
// 2. CORE MEMORY NODE CONSTRAINTS
// ======================================================

CREATE CONSTRAINT message_id_unique IF NOT EXISTS
FOR (m:Message)
REQUIRE m.id IS UNIQUE;

CREATE CONSTRAINT fact_id_unique IF NOT EXISTS
FOR (f:Fact)
REQUIRE f.id IS UNIQUE;

CREATE CONSTRAINT entity_user_unique IF NOT EXISTS
FOR (e:Entity)
REQUIRE (e.user_id, e.name) IS UNIQUE;

CREATE CONSTRAINT preference_id_unique IF NOT EXISTS
FOR (p:Preference)
REQUIRE p.id IS UNIQUE;

CREATE CONSTRAINT goal_id_unique IF NOT EXISTS
FOR (g:Goal)
REQUIRE g.id IS UNIQUE;

CREATE CONSTRAINT event_id_unique IF NOT EXISTS
FOR (ev:Event)
REQUIRE ev.id IS UNIQUE;

CREATE CONSTRAINT chunk_id_unique IF NOT EXISTS
FOR (c:DocumentChunk)
REQUIRE c.id IS UNIQUE;



// ======================================================
// 3. INDEXES FOR FAST RETRIEVAL
// ======================================================

CREATE INDEX entity_name_index IF NOT EXISTS
FOR (e:Entity)
ON (e.name);

CREATE INDEX fact_text_index IF NOT EXISTS
FOR (f:Fact)
ON (f.text);

CREATE INDEX timestamp_index IF NOT EXISTS
FOR (n)
ON (n.timestamp);

CREATE INDEX reinforcement_index IF NOT EXISTS
FOR (n)
ON (n.last_reinforced);

CREATE INDEX confidence_index IF NOT EXISTS
FOR (n)
ON (n.confidence);



// ======================================================
// 4. MEMORY NODE DEFINITIONS (PROPERTY REFERENCE)
// ======================================================

/*

---------------------------
User
---------------------------
(:User {
    id: STRING,
    name: STRING,
    email: STRING,
    created_at: DATETIME
})

---------------------------
Message (Raw Chat Storage)
---------------------------
(:Message {
    id: STRING,
    text: STRING,
    timestamp: DATETIME,
    source_type: "chat" | "upload",
    created_at: DATETIME
})

---------------------------
Fact (Atomic Memory Unit)
---------------------------
(:Fact {
    id: STRING,
    text: STRING,
    confidence: FLOAT,
    reinforcement_score: FLOAT,
    timestamp: DATETIME,
    last_reinforced: DATETIME,
    created_at: DATETIME,
    updated_at: DATETIME
})

---------------------------
Entity (Generic Concept Node)
---------------------------
(:Entity {
    name: STRING,
    entity_type: STRING,      // person | org | financial_asset | concept | etc.
    user_id: STRING,
    confidence: FLOAT,
    timestamp: DATETIME,
    last_reinforced: DATETIME
})

---------------------------
Preference
---------------------------
(:Preference {
    id: STRING,
    text: STRING,
    confidence: FLOAT,
    timestamp: DATETIME,
    last_reinforced: DATETIME
})

---------------------------
Goal
---------------------------
(:Goal {
    id: STRING,
    name: STRING,
    target_amount: FLOAT,
    target_date: DATE,
    confidence: FLOAT,
    timestamp: DATETIME,
    last_reinforced: DATETIME
})

---------------------------
Event
---------------------------
(:Event {
    id: STRING,
    name: STRING,
    event_date: DATE,
    confidence: FLOAT,
    timestamp: DATETIME,
    last_reinforced: DATETIME
})

---------------------------
DocumentChunk (Hybrid RAG)
---------------------------
(:DocumentChunk {
    id: STRING,
    text: STRING,
    embedding_id: STRING,     // Milvus vector reference
    confidence: FLOAT,
    timestamp: DATETIME,
    last_reinforced: DATETIME
})

*/



// ======================================================
// 5. RELATIONSHIP TYPES
// ======================================================

/*

---------------------------
USER ISOLATION ROOT
---------------------------
(User)-[:OWNS_MEMORY]->(Message)
(User)-[:OWNS_MEMORY]->(Fact)
(User)-[:OWNS_MEMORY]->(Entity)
(User)-[:OWNS_MEMORY]->(Preference)
(User)-[:OWNS_MEMORY]->(Goal)
(User)-[:OWNS_MEMORY]->(Event)
(User)-[:OWNS_MEMORY]->(DocumentChunk)

⚠ ALL RETRIEVAL MUST START FROM:
MATCH (u:User {id:$user_id})-[:OWNS_MEMORY]->(...)

This guarantees strict user isolation.

---------------------------
INGESTION RELATIONS
---------------------------
(Message)-[:DERIVED_FROM]->(Fact)
(Fact)-[:RELATES_TO]->(Entity)
(DocumentChunk)-[:MENTIONS]->(Entity)

---------------------------
USER BEHAVIOR RELATIONS
---------------------------
(User)-[:PREFERS]->(Preference)
(User)-[:WORKS_ON]->(Goal)
(User)-[:PARTICIPATES_IN]->(Event)

---------------------------
KNOWLEDGE RELATIONS
---------------------------
(Fact)-[:CONFIRMS]->(Fact)
(Fact)-[:CONTRADICTS]->(Fact)
(Entity)-[:RELATED_TO]->(Entity)

*/



// ======================================================
// 6. REINFORCEMENT MECHANISM LOGIC
// ======================================================

/*

ON CREATE:
    confidence = 0.8
    reinforcement_score = 1.0
    last_reinforced = datetime()

ON RETRIEVAL:
    SET n.last_reinforced = datetime(),
        n.reinforcement_score = n.reinforcement_score + 0.05

OPTIONAL MEMORY DECAY JOB:
    MATCH (n)
    SET n.reinforcement_score = n.reinforcement_score * 0.98

Retrieval ordering:
    ORDER BY n.reinforcement_score DESC, n.confidence DESC

*/



// ======================================================
// 7. SAMPLE SAFE RETRIEVAL QUERY TEMPLATE
// ======================================================

/*

MATCH (u:User {id:$user_id})-[:OWNS_MEMORY]->(f:Fact)
WHERE f.text CONTAINS $query
OPTIONAL MATCH (f)-[:RELATES_TO]->(e:Entity)
RETURN f, e
ORDER BY f.reinforcement_score DESC
LIMIT 10

*/


// ======================================================
// END OF GRAPHMIND SCHEMA
// ======================================================