import io
import json
import tempfile
import threading
import unittest
from pathlib import Path

from werkzeug.serving import make_server

from webviewer import create_app
from webviewer.remote_worker import RemoteWorker, RemoteWorkerConfig


class RemoteWorkerEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.token = "end-to-end-worker-token"
        self.app = create_app(
            {
                "TESTING": True,
                "WEBVIEWER_DATA_DIR": str(self.root / "gateway"),
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
        self.server = make_server("127.0.0.1", 0, self.app, threaded=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.app.extensions["webviewer_jobs"].executor.shutdown(wait=True)
        self.temp_dir.cleanup()

    def test_worker_transfers_slide_and_result_over_http(self):
        client = self.app.test_client()
        created = client.post(
            "/api/jobs",
            data={"slide": (io.BytesIO(b"large-slide-placeholder"), "case.svs")},
            content_type="multipart/form-data",
        ).get_json()["job"]

        config = RemoteWorkerConfig(
            gateway_url=f"http://127.0.0.1:{self.server.server_port}",
            token=self.token,
            worker_id="china-test-worker",
            data_dir=self.root / "worker",
            poll_seconds=2,
            heartbeat_seconds=5,
            verify_tls=True,
        )
        worker = RemoteWorker(config)

        def fake_pipeline(job, input_dir, output_dir):
            slide_path = next(input_dir.glob("*.svs"))
            self.assertEqual(slide_path.read_bytes(), b"large-slide-placeholder")
            stem = slide_path.stem
            overlay = {"type": "FeatureCollection", "features": []}
            (output_dir / f"{stem}.geojson").write_text(
                json.dumps(overlay), encoding="utf-8"
            )
            result = {
                "geojson_files": [
                    {
                        "filename": f"{stem}.geojson",
                        "type": "Benign",
                        "conf": "strong",
                        "percentage": "0%",
                        "Gleason": "N/A",
                        "ISUP": "N/A",
                    }
                ]
            }
            (output_dir / "exist_cancer.json").write_text(
                json.dumps(result, ensure_ascii=False), encoding="utf-8"
            )
            (output_dir / "pipeline.log").write_text("mock remote inference", encoding="utf-8")

        worker._run_pipeline = fake_pipeline
        try:
            self.assertTrue(worker.run_forever(once=True))
        finally:
            worker.client.session.close()

        completed = client.get(f"/api/jobs/{created['id']}").get_json()["job"]
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["result"]["geojson_files"][0]["type"], "Benign")
        overlay = client.get(f"/api/jobs/{created['id']}/slide/overlay")
        self.assertEqual(overlay.status_code, 200)
        self.assertEqual(overlay.get_json()["type"], "FeatureCollection")


if __name__ == "__main__":
    unittest.main()
