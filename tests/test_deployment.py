import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import requests
from waitress import create_server

from tools import model_assets
from webviewer import create_app
from webviewer.envfile import load_env_file
from webviewer.preflight import required_pipeline_assets


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class EnvironmentFileTests(unittest.TestCase):
    def test_loads_bom_comments_quotes_and_export(self):
        keys = ("MXZY_TEST_ALPHA", "MXZY_TEST_BETA", "MXZY_TEST_GAMMA")
        for key in keys:
            os.environ.pop(key, None)
        try:
            with tempfile.TemporaryDirectory() as directory:
                env_file = Path(directory) / "worker.env"
                env_file.write_text(
                    "\ufeff# deployment config\n"
                    "MXZY_TEST_ALPHA=one\n"
                    "export MXZY_TEST_BETA=\"two words\"\n"
                    "MXZY_TEST_GAMMA='three'\n",
                    encoding="utf-8",
                )
                load_env_file(env_file)
            self.assertEqual(os.environ["MXZY_TEST_ALPHA"], "one")
            self.assertEqual(os.environ["MXZY_TEST_BETA"], "two words")
            self.assertEqual(os.environ["MXZY_TEST_GAMMA"], "three")
        finally:
            for key in keys:
                os.environ.pop(key, None)

    def test_does_not_override_existing_value_by_default(self):
        os.environ["MXZY_TEST_EXISTING"] = "original"
        try:
            with tempfile.TemporaryDirectory() as directory:
                env_file = Path(directory) / "ui.env"
                env_file.write_text("MXZY_TEST_EXISTING=replaced\n", encoding="utf-8")
                load_env_file(env_file)
            self.assertEqual(os.environ["MXZY_TEST_EXISTING"], "original")
        finally:
            os.environ.pop("MXZY_TEST_EXISTING", None)


class DeploymentAssetTests(unittest.TestCase):
    def test_normal_pipeline_asset_manifest(self):
        assets = required_pipeline_assets(normal=True)
        self.assertIn("MIL_BASELINE/ckpts/cancer/10x-normal/best_f1.pth", assets)
        self.assertIn("ultralytics/runs/detect/cbam/weights/best.pt", assets)
        self.assertEqual(len(assets), len(set(assets)))

    def test_model_asset_package_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = {}
            for index, relative in enumerate(model_assets.YOLO_ASSETS):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                content = f"weight-{index}".encode()
                path.write_bytes(content)
                expected[relative] = content
            archive = root / "weights.zip"
            with patch.object(model_assets, "PROJECT_ROOT", root):
                model_assets.package_assets(archive)
                for relative in model_assets.YOLO_ASSETS:
                    (root / relative).unlink()
                model_assets.install_assets(archive)
            for relative, content in expected.items():
                self.assertEqual((root / relative).read_bytes(), content)

    def test_campus_server_template_uses_local_pipeline_backend(self):
        content = (PROJECT_ROOT / ".env.campus-server-ui.example").read_text(
            encoding="utf-8"
        )
        self.assertIn("WEBVIEWER_EXECUTION_BACKEND=local", content)
        self.assertIn("WEBVIEWER_PIPELINE_MODE=real", content)
        self.assertIn("WEBVIEWER_HOST=100.64.0.20", content)
        self.assertNotIn("WEBVIEWER_GATEWAY_URL=", content)

    def test_server_service_uses_server_ui_environment(self):
        script = (PROJECT_ROOT / "deploy/linux/start_server_ui.sh").read_text(
            encoding="utf-8"
        )
        service = (
            PROJECT_ROOT / "deploy/linux/mxzy-server-ui.service.example"
        ).read_text(encoding="utf-8")
        self.assertIn("run_webviewer.py --env-file", script)
        self.assertIn("MXZY_SERVER_UI_ENV", script)
        self.assertIn("tailscaled.service", service)
        self.assertIn("campus-server-ui.env", service)

    def test_vps_proxy_requires_auth_and_uses_private_upstream(self):
        caddyfile = (PROJECT_ROOT / "deploy/vps/Caddyfile.example").read_text(
            encoding="utf-8"
        )
        environment = (PROJECT_ROOT / "deploy/vps/mxzy.env.example").read_text(
            encoding="utf-8"
        )
        self.assertIn("basic_auth", caddyfile)
        self.assertIn("reverse_proxy {$MXZY_CAMPUS_UPSTREAM}", caddyfile)
        self.assertIn("MXZY_CAMPUS_UPSTREAM=http://100.64.0.20:5000", environment)
        self.assertNotIn("172.27.", environment)

    def test_tailnet_grant_restricts_vps_to_web_port(self):
        policy = (
            PROJECT_ROOT / "deploy/tailscale/grants.example.hujson"
        ).read_text(encoding="utf-8")
        self.assertIn('"src": ["tag:mxzy-vps"]', policy)
        self.assertIn('"dst": ["tag:mxzy-campus"]', policy)
        self.assertIn('"ip": ["tcp:5000"]', policy)
        self.assertNotIn('"ip": ["*"]', policy)


class WaitressDeploymentTests(unittest.TestCase):
    def test_waitress_serves_authenticated_worker_health(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(
                {
                    "TESTING": True,
                    "WEBVIEWER_DATA_DIR": directory,
                    "WEBVIEWER_EXECUTION_BACKEND": "remote",
                    "WEBVIEWER_WORKER_TOKEN": "deployment-test-token",
                }
            )
            server = create_server(app, host="127.0.0.1", port=0)
            thread = threading.Thread(target=server.run, daemon=True)
            thread.start()
            try:
                response = requests.get(
                    f"http://127.0.0.1:{server.effective_port}/api/worker/health",
                    headers={"Authorization": "Bearer deployment-test-token"},
                    timeout=5,
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["executionBackend"], "remote")
            finally:
                server.close()
                thread.join(timeout=5)
                server.task_dispatcher.shutdown()


if __name__ == "__main__":
    unittest.main()
