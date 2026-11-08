"""Сводка по БД: схемы, schema_hash, число CSV. Только чтение. Запуск: python scripts/probe_db_state.py data\\new.db ..."""
import sqlite3
import sys

for db in sys.argv[1:]:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    print(db, "user_version =", c.execute("pragma user_version").fetchone()[0])
    print("  files:", c.execute("select count(*) from files").fetchone()[0],
          "| без schema_hash:", c.execute("select count(*) from files where schema_hash is null or schema_hash=''").fetchone()[0])
    print("  schemas:", c.execute("select count(*) from schemas").fetchone()[0])
    for row in c.execute("select s.schema_hash, count(f.id) from schemas s left join files f on f.schema_hash=s.schema_hash group by s.schema_hash order by 2 desc"):
        print("   ", row)
