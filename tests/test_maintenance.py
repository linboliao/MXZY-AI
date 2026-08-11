import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from delete_failed_jobs import backup_database, delete_failed_snapshot, failed_jobs
from webviewer.jobs import JobStore


class DeleteFailedJobsTests(unittest.TestCase):
    def test_backup_and_delete_only_failed_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "jobs.sqlite3"
            store = JobStore(database)
            common = {
                "source_type": "upload",
                "input_path": str(root / "slide.svs"),
                "output_path": str(root / "output"),
            }
            store.create(id="failed-job", original_name="failed.svs", **common)
            store.update("failed-job", status="failed", error="test failure")
            store.create(id="completed-job", original_name="completed.svs", **common)
            store.update("completed-job", status="completed")

            snapshot = failed_jobs(database)
            self.assertEqual([row["id"] for row in snapshot], ["failed-job"])
            backup = backup_database(database)
            deleted = delete_failed_snapshot(
                database,
                [row["id"] for row in snapshot],
            )

            self.assertEqual(deleted, 1)
            self.assertIsNone(store.get("failed-job"))
            self.assertIsNotNone(store.get("completed-job"))
            with closing(sqlite3.connect(backup)) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM jobs WHERE id = 'failed-job'"
                    ).fetchone()[0],
                    1,
                )


if __name__ == "__main__":
    unittest.main()
