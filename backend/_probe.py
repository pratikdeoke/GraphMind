import psycopg2

attempts = [
    ("graphmind_user", "graphmind_pass_2026"),
    ("graphmind_user", "graphmind_pass"),
    ("postgres", "postgres"),
    ("postgres", "password"),
    ("postgres", "admin"),
    ("postgres", "root"),
]
print("=== PostgreSQL probe (localhost:5432 / db=graphmind) ===")
for user, pw in attempts:
    try:
        c = psycopg2.connect(host="localhost", port=5432, dbname="graphmind", user=user, password=pw, connect_timeout=4)
        print(f"PG OK: user={user} pw={pw}")
        c.close()
        break
    except Exception as e:
        print(f"PG FAIL user={user} pw={pw}: {str(e).splitlines()[0]}")

print("=== Neo4j probe (bolt://localhost:7687) ===")
try:
    from neo4j import GraphDatabase
    for user, pw in [("neo4j", "graphmind123"), ("neo4j", "password"), ("neo4j", "neo4j")]:
        try:
            d = GraphDatabase.driver("bolt://localhost:7687", auth=(user, pw))
            d.verify_connectivity()
            print(f"NEO4J OK: user={user} pw={pw}")
            d.close()
            break
        except Exception as e:
            print(f"NEO4J FAIL user={user} pw={pw}: {str(e).splitlines()[0]}")
except Exception as e:
    print("neo4j import failed:", e)
