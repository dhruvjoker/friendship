import sqlite3
import os

dbs = ['friendship_app.db', os.path.join('instance','friendship_app.db')]
for path in dbs:
    print('\nDB file:', path)
    if not os.path.exists(path):
        print('  (not found)')
        continue
    try:
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [r[0] for r in cur.fetchall()]
        print('  Tables:', tables)
        for t in tables:
            cur.execute(f"PRAGMA table_info({t});")
            cols = cur.fetchall()
            print('   ', t, 'columns:', [c[1] for c in cols])
        conn.close()
    except Exception as e:
        print('  Error:', e)
