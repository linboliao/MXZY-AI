import io
import json
import re
import tempfile
import unittest
import zipfile
from pathlib import Path

from webviewer import create_app
from webviewer.jobs import JobStore


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HAN_TEXT = re.compile(r"[\u3400-\u9fff]")


class WebViewerApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.server_root = self.root / "server-slides"
        self.server_root.mkdir()
        self.server_slide = self.server_root / "case-001.svs"
        self.server_slide.write_bytes(b"fake-svs-for-api-test")
        self.app = create_app(
            {
                "TESTING": True,
                "WEBVIEWER_DATA_DIR": str(self.root / "data"),
                "WEBVIEWER_SERVER_ROOTS": [("测试切片库", self.server_root)],
                "WEBVIEWER_PIPELINE_MODE": "mock",
                "WEBVIEWER_SYNC_JOBS": True,
                "MAX_CONTENT_LENGTH": 1024 * 1024,
                "WEBVIEWER_MAX_UPLOAD_BYTES": 1024 * 1024,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.app.extensions["webviewer_jobs"].executor.shutdown(wait=True)
        self.temp_dir.cleanup()

    def test_health(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")

    def test_frontend_copy_is_english(self):
        index = self.client.get("/")
        self.assertEqual(index.status_code, 200)
        html = index.get_data(as_text=True)
        javascript = (PROJECT_ROOT / "webviewer/static/app.js").read_text(
            encoding="utf-8"
        )
        self.assertIn('<html lang="en">', html)
        self.assertIn("Prostate Pathology Diagnosis", html)
        self.assertIsNone(HAN_TEXT.search(html))
        self.assertIsNone(HAN_TEXT.search(javascript))

    def test_upload_creates_completed_mock_job(self):
        response = self.client.post(
            "/api/jobs",
            data={"slide": (io.BytesIO(b"slide"), "patient.svs")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 202)
        job = response.get_json()["job"]
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["message"], "Diagnosis completed (simulation mode)")
        self.assertEqual(job["result"]["geojson_files"][0]["type"], "Benign")
        self.assertNotIn("input_path", job)
        self.assertNotIn("output_path", job)

        overlay = self.client.get(f"/api/jobs/{job['id']}/slide/overlay")
        self.assertEqual(overlay.status_code, 200)
        self.assertEqual(overlay.get_json()["type"], "FeatureCollection")

    def test_rejects_non_svs_upload(self):
        response = self.client.post(
            "/api/jobs",
            data={"slide": (io.BytesIO(b"image"), "patient.png")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("SVS", response.get_json()["error"].upper())
        self.assertIn("only supports", response.get_json()["error"])

    def test_server_slide_token_is_resolved_inside_configured_root(self):
        listing = self.client.get("/api/server-slides").get_json()["slides"]
        self.assertEqual(len(listing), 1)
        response = self.client.post("/api/jobs", json={"serverSlideId": listing[0]["id"]})
        self.assertEqual(response.status_code, 202)
        job = response.get_json()["job"]
        self.assertEqual(job["source_type"], "server")
        self.assertEqual(job["original_name"], "case-001.svs")

    def test_invalid_server_token_is_rejected(self):
        response = self.client.post("/api/jobs", json={"serverSlideId": "invalid"})
        self.assertEqual(response.status_code, 400)


class RemoteWorkerApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.token = "test-worker-token"
        self.worker_id = "china-gpu-test"
        self.app = create_app(
            {
                "TESTING": True,
                "WEBVIEWER_DATA_DIR": str(self.root / "data"),
                "WEBVIEWER_SERVER_ROOTS": [],
                "WEBVIEWER_PIPELINE_MODE": "real",
                "WEBVIEWER_EXECUTION_BACKEND": "remote",
                "WEBVIEWER_WORKER_TOKEN": self.token,
                "WEBVIEWER_WORKER_LEASE_SECONDS": 300,
                "WEBVIEWER_RESULT_BUNDLE_MAX_BYTES": 1024 * 1024,
                "MAX_CONTENT_LENGTH": 2 * 1024 * 1024,
                "WEBVIEWER_MAX_UPLOAD_BYTES": 2 * 1024 * 1024,
            }
        )
        self.client = self.app.test_client()
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "X-Worker-ID": self.worker_id,
        }

    def tearDown(self):
        self.app.extensions["webviewer_jobs"].executor.shutdown(wait=True)
        self.temp_dir.cleanup()

    def _create_job(self, filename="patient.svs"):
        response = self.client.post(
            "/api/jobs",
            data={"slide": (io.BytesIO(b"remote-slide"), filename)},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 202)
        job = response.get_json()["job"]
        self.assertEqual(job["status"], "queued")
        return job

    def _lease(self):
        response = self.client.post("/api/worker/jobs/lease", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        return response.get_json()["job"]

    def test_remote_worker_download_heartbeat_and_complete(self):
        self._create_job("patient.svs")
        self.assertEqual(self.client.get("/api/worker/health").status_code, 401)
        self.assertEqual(
            self.client.get("/api/worker/health", headers=self.headers).status_code, 200
        )

        leased = self._lease()
        slide = self.client.get(leased["slideUrl"], headers=self.headers)
        self.assertEqual(slide.status_code, 200)
        self.assertEqual(slide.data, b"remote-slide")
        slide.close()

        heartbeat = self.client.post(
            leased["heartbeatUrl"],
            headers=self.headers,
            json={"progress": 44, "message": "Running inference on the GPU worker"},
        )
        self.assertEqual(heartbeat.status_code, 200)

        stem = Path(leased["storedFilename"]).stem
        summary = {
            "geojson_files": [
                {
                    "filename": f"{stem}.geojson",
                    "type": "Malignant",
                    "conf": "strong",
                    "percentage": "10%",
                    "Gleason": "3+4",
                    "ISUP": "2",
                }
            ]
        }
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("exist_cancer.json", json.dumps(summary, ensure_ascii=False))
            bundle.writestr(
                f"{stem}.geojson",
                json.dumps({"type": "FeatureCollection", "features": []}),
            )
        archive.seek(0)
        complete = self.client.post(
            leased["completeUrl"],
            headers=self.headers,
            data={"bundle": (archive, "result.zip")},
            content_type="multipart/form-data",
        )
        self.assertEqual(complete.status_code, 200)

        job = self.client.get(f"/api/jobs/{leased['id']}").get_json()["job"]
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["result"]["geojson_files"][0]["type"], "Malignant")
        overlay = self.client.get(f"/api/jobs/{leased['id']}/slide/overlay")
        self.assertEqual(overlay.status_code, 200)
        self.assertEqual(overlay.get_json()["type"], "FeatureCollection")

    def test_result_bundle_rejects_path_traversal(self):
        self._create_job()
        leased = self._lease()
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("../outside.txt", "unsafe")
        archive.seek(0)
        response = self.client.post(
            leased["completeUrl"],
            headers=self.headers,
            data={"bundle": (archive, "result.zip")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse((self.root / "outside.txt").exists())


class LegacyJobCopyMigrationTests(unittest.TestCase):
    def test_existing_chinese_job_copy_is_migrated_to_english(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "jobs.sqlite3"
            store = JobStore(database)
            row = store.create(
                id="legacy-job",
                source_type="upload",
                original_name="legacy.svs",
                input_path=str(Path(directory) / "legacy.svs"),
                output_path=str(Path(directory) / "output"),
            )
            store.update(
                row["id"],
                message="正在提取病理特征",
                error="服务重启导致任务中断",
            )

            migrated = JobStore(database).get(row["id"])
            self.assertEqual(migrated["message"], "Extracting pathology features")
            self.assertEqual(
                migrated["error"], "Task interrupted by a service restart"
            )


if __name__ == "__main__":
    unittest.main()
