"""Local support queue and operator CLI (python -m handoffs)."""
import argparse
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from dotenv import load_dotenv

SCHEMA = """
CREATE TABLE IF NOT EXISTS handoffs (
    event_id TEXT PRIMARY KEY,
    reply_to TEXT NOT NULL,
    received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT
)
"""


def database_path() -> Path:
    return Path(os.getenv("HANDOFF_DB_PATH") or "data/handoffs.sqlite3")


def enqueue(event_id: str, reply_to: str) -> None:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(SCHEMA)
        db.execute(
            "INSERT INTO handoffs (event_id, reply_to) VALUES (?, ?) ON CONFLICT(event_id) DO NOTHING",
            (event_id, reply_to),
        )


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Review pending Threadline handoffs")
    parser.add_argument("--resolve", metavar="EVENT_ID", help="mark a request resolved")
    args = parser.parse_args()
    path = database_path()
    if not path.is_file():
        if args.resolve:
            parser.exit(1, "No pending request with that event ID.\n")
        print("No pending requests.")
        return
    with closing(sqlite3.connect(path)) as db, db:
        db.row_factory = sqlite3.Row
        db.execute(SCHEMA)
        if args.resolve:
            result = db.execute(
                "UPDATE handoffs SET resolved_at = CURRENT_TIMESTAMP WHERE event_id = ? AND resolved_at IS NULL",
                (args.resolve,),
            )
            if not result.rowcount:
                parser.exit(1, "No pending request with that event ID.\n")
            print("Request resolved.")
        else:
            for row in db.execute(
                "SELECT event_id, reply_to, received_at FROM handoffs "
                "WHERE resolved_at IS NULL ORDER BY received_at, event_id"
            ):
                print(json.dumps(dict(row)))


if __name__ == "__main__":
    main()
