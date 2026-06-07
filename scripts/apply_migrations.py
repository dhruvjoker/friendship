"""Apply simple schema migrations for development.
This script will attempt to add `preferred_region` and `preferred_timezone` columns
to the `users` table if they don't already exist.

Usage:
    python scripts/apply_migrations.py

It reads the SQLALCHEMY_DATABASE_URI from the project's `config.Config`.
"""
from sqlalchemy import create_engine, text
import os, sys

# Ensure project root is on sys.path so `import config` works when invoked from workspace
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from config import Config
import sys

uri = Config.SQLALCHEMY_DATABASE_URI
# If the instance DB exists, prefer it (the app creates tables there)
instance_db_path = os.path.join(project_root, 'instance', 'friendship_app.db')
if os.path.exists(instance_db_path):
    uri = f"sqlite:///{os.path.join('instance','friendship_app.db')}"
engine = create_engine(uri)

alter_statements = [
    "ALTER TABLE users ADD COLUMN preferred_region VARCHAR(64);",
    "ALTER TABLE users ADD COLUMN preferred_timezone VARCHAR(128);",
]

with engine.connect() as conn:
    for stmt in alter_statements:
        try:
            conn.execute(text(stmt))
            print('Executed:', stmt)
        except Exception as e:
            # Column may already exist or DB may not support direct ALTER; skip with message
            print('Skipped/failed:', stmt)
            print('  Reason:', str(e))

print('Done. If your DB uses migrations (Alembic), please create a proper migration file instead.')
