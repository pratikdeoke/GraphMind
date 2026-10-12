"""Verify E2EE ciphertext actually lands in Neo4j."""
from neo4j import GraphDatabase
from config.settings import Settings

s = Settings()
d = GraphDatabase.driver(s.NEO4J_URI, auth=(s.NEO4J_USER, s.NEO4J_PASSWORD))
with d.session() as ss:
    rows = list(ss.run("MATCH (n) WHERE n.text IS NOT NULL RETURN n.text AS t, n.user_id AS u LIMIT 8"))
    print("NODES_WITH_TEXT:", len(rows))
    for rec in rows[:8]:
        t = rec["t"]
        looks_enc = str(t).startswith("enc:v1:")
        tag = "CIPHERTEXT" if looks_enc else "PLAINTEXT "
        print(tag, "|", str(t)[:70])
    rc = ss.run("MATCH (c:EncryptionCanary) RETURN count(c) AS n").single()
    print("CANARY_NODES:", rc["n"])
d.close()
