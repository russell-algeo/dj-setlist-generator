"""Apply Drizzle SQL migrations directly with psycopg."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from psycopg import connect as pg_connect


def _read_journal(migrations_dir: Path) -> list[dict[str, object]]:
    journal_path = migrations_dir / "meta" / "_journal.json"
    payload = json.loads(journal_path.read_text())
    return list(payload.get("entries", []))


def _read_migration(migrations_dir: Path, tag: str) -> tuple[str, list[str]]:
    sql_path = migrations_dir / f"{tag}.sql"
    raw_sql = sql_path.read_text()
    statements = [part.strip() for part in raw_sql.split("--> statement-breakpoint") if part.strip()]
    return raw_sql, statements


def _ensure_migrations_table(cur) -> None:
    cur.execute(
        """
        create table if not exists __drizzle_migrations (
          id serial primary key,
          hash text not null,
          created_at numeric
        )
        """
    )


def _latest_applied_millis(cur) -> int | None:
    cur.execute("select created_at from __drizzle_migrations order by created_at desc limit 1")
    row = cur.fetchone()
    return int(row[0]) if row else None


def _insert_migration_row(cur, raw_sql: str, folder_millis: int) -> None:
    migration_hash = hashlib.sha256(raw_sql.encode()).hexdigest()
    cur.execute(
        """
        insert into __drizzle_migrations ("hash", "created_at")
        values (%s, %s)
        """,
        (migration_hash, folder_millis),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply Drizzle SQL migrations with psycopg")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--migrations-dir", default="drizzle/migrations")
    parser.add_argument("--baseline-through-tag")
    args = parser.parse_args()

    migrations_dir = Path(args.migrations_dir)
    journal_entries = _read_journal(migrations_dir)

    with pg_connect(args.database_url, autocommit=True) as conn, conn.cursor() as cur:
        _ensure_migrations_table(cur)
        latest_millis = _latest_applied_millis(cur)

        if latest_millis is None and args.baseline_through_tag:
            for entry in journal_entries:
                raw_sql, _ = _read_migration(migrations_dir, str(entry["tag"]))
                _insert_migration_row(cur, raw_sql, int(entry["when"]))
                if entry["tag"] == args.baseline_through_tag:
                    latest_millis = int(entry["when"])
                    break

        for entry in journal_entries:
            folder_millis = int(entry["when"])
            if latest_millis is not None and folder_millis <= latest_millis:
                continue

            raw_sql, statements = _read_migration(migrations_dir, str(entry["tag"]))
            for statement in statements:
                cur.execute(statement)
            _insert_migration_row(cur, raw_sql, folder_millis)
            latest_millis = folder_millis
            print(f"applied {entry['tag']}")


if __name__ == "__main__":
    main()
