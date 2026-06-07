"""
scripts/migrate_new_features.py
================================
Run this ONCE to add new tables + columns for the feature update.

Usage:
    cd friendship_app
    python scripts/migrate_new_features.py

Safe to re-run — each ALTER is wrapped in try/except.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from run import app        # imports create_app()
from app.models import db

DDL_STATEMENTS = [
    # ── New tables ──────────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS user_blocks (
        id          TEXT PRIMARY KEY,
        blocker_id  TEXT NOT NULL REFERENCES users(id),
        blocked_id  TEXT NOT NULL REFERENCES users(id),
        block_type  TEXT NOT NULL DEFAULT 'block',
        created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(blocker_id, blocked_id, block_type)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS match_scores (
        id                TEXT PRIMARY KEY,
        connection_id     TEXT NOT NULL REFERENCES user_connections(id),
        interest_overlap  REAL DEFAULT 0,
        timezone_compat   REAL DEFAULT 0,
        activity_score    REAL DEFAULT 0,
        overall_score     REAL DEFAULT 0,
        computed_at       DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS message_images (
        id          TEXT PRIMARY KEY,
        message_id  TEXT NOT NULL REFERENCES messages(id),
        filename    TEXT NOT NULL,
        mime_type   TEXT NOT NULL,
        size_bytes  INTEGER,
        moderated   INTEGER DEFAULT 0,
        uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,

    # ── New columns on existing tables ──────────────────────────────────────
    # users: language, badge_list (JSON array string), support_score, last_active_at
]

# ALTER TABLE statements that may fail if column exists — handled per-item
ALTER_STATEMENTS = [
    "ALTER TABLE users ADD COLUMN language TEXT",
    "ALTER TABLE users ADD COLUMN badge_list TEXT",     # JSON array string
    "ALTER TABLE users ADD COLUMN support_score INTEGER DEFAULT 0",
    # last_seen already exists; we use it as last_active
    # messages: is_deleted flag (soft-delete for account deletion)
    "ALTER TABLE messages ADD COLUMN is_deleted INTEGER DEFAULT 0",
    # user_connections: unmatched_at
    "ALTER TABLE user_connections ADD COLUMN unmatched_at DATETIME",
]


def run():
    with app.app_context():
        conn = db.engine.raw_connection()
        cur  = conn.cursor()

        for stmt in DDL_STATEMENTS:
            try:
                cur.execute(stmt)
                print(f"OK  (CREATE): {stmt.strip()[:60]}...")
            except Exception as e:
                print(f"SKIP: {e}")

        for stmt in ALTER_STATEMENTS:
            try:
                cur.execute(stmt)
                print(f"OK  (ALTER): {stmt}")
            except Exception as e:
                print(f"SKIP (already exists?): {e}")

        conn.commit()
        conn.close()
        print("\nMigration complete.")


if __name__ == '__main__':
    run()
