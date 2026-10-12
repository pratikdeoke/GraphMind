import importlib
print("=== dep check ===")
for m in ["fastapi", "uvicorn", "cryptography", "neo4j", "psycopg2", "bcrypt", "jose", "dotenv", "pydantic"]:
    try:
        mod = importlib.import_module(m)
        print(m, "OK", getattr(mod, "__version__", "?"))
    except Exception as e:
        print(m, "MISSING", type(e).__name__, str(e)[:150])

print("=== ports ===")
import socket
for port, name in [(8001, "backend?"), (5432, "pg-local?"), (5433, "pg-docker?"), (7687, "neo4j-bolt"), (7474, "neo4j-http"), (5173, "frontend?")]:
    s = socket.socket()
    s.settimeout(1.5)
    try:
        s.connect(("127.0.0.1", port))
        print(f"port {port} ({name}): OPEN")
    except Exception as e:
        print(f"port {port} ({name}): CLOSED ({e})")
    finally:
        s.close()

print("=== pg attempts ===")
import psycopg2
for host, port, user, pw in [
    ("localhost", 5433, "graphmind_user", "graphmind_pass_2026"),
    ("127.0.0.1", 5433, "graphmind_user", "graphmind_pass_2026"),
    ("localhost", 5432, "graphmind_user", "graphmind_pass_2026"),
]:
    try:
        c = psycopg2.connect(host=host, port=port, dbname="graphmind", user=user, password=pw, connect_timeout=4)
        cur = c.cursor()
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='users' AND column_name LIKE 'encryption%'")
        print(f"PG OK {host}:{port} enc-cols={[r[0] for r in cur.fetchall()]}")
        c.close()
        break
    except Exception as e:
        print(f"PG FAIL {host}:{port}: {str(e).splitlines()[0]}")

print("=== neo4j ===")
try:
    from neo4j import GraphDatabase
    for pw in ["graphmind123", "password"]:
        try:
            d = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", pw))
            d.verify_connectivity()
            print(f"NEO4J OK pw={pw}")
            d.close()
            break
        except Exception as e:
            print(f"NEO4J FAIL pw={pw}: {str(e).splitlines()[0]}")
except Exception as e:
    print("neo4j import failed:", e)
