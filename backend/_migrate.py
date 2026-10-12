import psycopg2
c = psycopg2.connect(host="localhost", port=5433, dbname="graphmind",
                     user="graphmind_user", password="graphmind_pass_2026")
c.autocommit = True
cur = c.cursor()
with open("database/migrations/20261011_add_encryption_columns.sql") as f:
    cur.execute(f.read())
cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='users' AND column_name LIKE 'encryption%' ORDER BY 1")
print("enc-cols:", [r[0] for r in cur.fetchall()])
c.close()
print("MIGRATION_DONE")
