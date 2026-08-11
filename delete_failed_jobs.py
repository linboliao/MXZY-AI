"""Safely remove failed Web Viewer job records from SQLite."""

import argparse
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from webviewer.config import WebViewerConfig
from webviewer.envfile import load_env_file


def resolve_database(env_file=None, database=None):
    if database:
        return Path(database).expanduser().resolve()
    load_env_file(env_file, override=True)
    return WebViewerConfig.from_environment().data_dir / "jobs.sqlite3"


def failed_jobs(database):
    with closing(sqlite3.connect(database, timeout=30)) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(
            """
            SELECT id, original_name, error, created_at
            FROM jobs
            WHERE status = 'failed'
            ORDER BY created_at
            """
        ).fetchall()


def backup_database(database):
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup_path = database.with_name(f"{database.name}.backup-{timestamp}")
    with closing(sqlite3.connect(database, timeout=30)) as source:
        with closing(sqlite3.connect(backup_path)) as destination:
            source.backup(destination)
    return backup_path


def delete_failed_snapshot(database, job_ids, *, vacuum=False):
    if not job_ids:
        return 0
    with closing(sqlite3.connect(database, timeout=30)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        before = connection.total_changes
        connection.executemany(
            "DELETE FROM jobs WHERE id = ? AND status = 'failed'",
            ((job_id,) for job_id in job_ids),
        )
        deleted = connection.total_changes - before
        connection.commit()
        if vacuum:
            connection.execute("VACUUM")
    return deleted


def main():
    parser = argparse.ArgumentParser(
        description="Back up SQLite and delete failed Web Viewer job records"
    )
    parser.add_argument(
        "--env-file",
        default=".env.campus-server-ui.local",
        help="Deployment environment file used to locate WEBVIEWER_DATA_DIR",
    )
    parser.add_argument(
        "--database",
        help="Explicit jobs.sqlite3 path; overrides --env-file",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List failed records without changing the database",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm deletion without an interactive prompt",
    )
    parser.add_argument(
        "--vacuum",
        action="store_true",
        help="Run VACUUM after deletion to compact SQLite",
    )
    args = parser.parse_args()

    database = resolve_database(args.env_file, args.database)
    if not database.is_file():
        raise SystemExit(f"SQLite database not found: {database}")

    rows = failed_jobs(database)
    print(f"Database: {database}")
    print(f"Failed records: {len(rows)}")
    for row in rows:
        error = (row["error"] or "No error details").replace("\n", " ")[:160]
        print(f"- {row['id']} | {row['original_name']} | {error}")

    if not rows:
        return 0
    if args.dry_run:
        print("Dry run only; no records were deleted")
        return 0
    if not args.yes:
        confirmation = input(f"Delete these {len(rows)} failed records? Type DELETE: ")
        if confirmation != "DELETE":
            print("Cancelled; no records were deleted")
            return 1

    backup_path = backup_database(database)
    deleted = delete_failed_snapshot(
        database,
        [row["id"] for row in rows],
        vacuum=args.vacuum,
    )
    print(f"Backup created: {backup_path}")
    print(f"Deleted failed records: {deleted}")
    print("Task files under WEBVIEWER_DATA_DIR/jobs were not deleted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
