"""Pull-based GPU worker for the overseas Web Viewer gateway."""

import json
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULT_PATTERNS = (
    "exist_cancer.json",
    "*.geojson",
    "pipeline.log",
    "cancer/*.csv",
    "gleason/*.csv",
    "yolo/*.csv",
    "yolo/*.geojson",
)


def _parse_bool(value, default=True):
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class RemoteWorkerConfig:
    gateway_url: str
    token: str
    worker_id: str
    data_dir: Path
    poll_seconds: int
    heartbeat_seconds: int
    verify_tls: bool

    @classmethod
    def from_environment(cls):
        gateway_url = os.getenv("WEBVIEWER_GATEWAY_URL", "").strip().rstrip("/")
        token = os.getenv("WEBVIEWER_WORKER_TOKEN", "").strip()
        if not gateway_url:
            raise RuntimeError("缺少 WEBVIEWER_GATEWAY_URL")
        if not token:
            raise RuntimeError("缺少 WEBVIEWER_WORKER_TOKEN")
        return cls(
            gateway_url=gateway_url,
            token=token,
            worker_id=os.getenv("WEBVIEWER_WORKER_ID", f"worker-{uuid.uuid4().hex[:12]}"),
            data_dir=Path(os.getenv("WEBVIEWER_WORKER_DATA_DIR", "./worker_data")).expanduser().resolve(),
            poll_seconds=max(2, int(os.getenv("WEBVIEWER_WORKER_POLL_SECONDS", "10"))),
            heartbeat_seconds=max(5, int(os.getenv("WEBVIEWER_WORKER_HEARTBEAT_SECONDS", "30"))),
            verify_tls=_parse_bool(os.getenv("WEBVIEWER_VERIFY_TLS"), True),
        )


class GatewayClient:
    def __init__(self, config):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {config.token}",
                "X-Worker-ID": config.worker_id,
                "User-Agent": "MXZY-AI-Remote-Worker/1.0",
            }
        )

    def _url(self, path):
        return urljoin(f"{self.config.gateway_url}/", str(path).lstrip("/"))

    def health(self):
        response = self.session.get(
            self._url("/api/worker/health"), timeout=(15, 30), verify=self.config.verify_tls
        )
        response.raise_for_status()
        return response.json()

    def lease(self):
        response = self.session.post(
            self._url("/api/worker/jobs/lease"),
            json={"workerId": self.config.worker_id},
            timeout=(15, 60),
            verify=self.config.verify_tls,
        )
        if response.status_code == 204:
            return None
        response.raise_for_status()
        return response.json()["job"]

    def heartbeat(self, job, progress, message):
        response = self.session.post(
            self._url(job["heartbeatUrl"]),
            json={"progress": progress, "message": message},
            timeout=(15, 30),
            verify=self.config.verify_tls,
        )
        response.raise_for_status()

    def download_slide(self, job, destination):
        partial = destination.with_suffix(destination.suffix + ".part")
        downloaded = partial.stat().st_size if partial.exists() else 0
        headers = {"Range": f"bytes={downloaded}-"} if downloaded else {}
        response = self.session.get(
            self._url(job["slideUrl"]),
            headers=headers,
            stream=True,
            timeout=(30, 300),
            verify=self.config.verify_tls,
        )
        if response.status_code == 416 and downloaded == int(job["size"]):
            partial.replace(destination)
            return
        response.raise_for_status()
        append = downloaded > 0 and response.status_code == 206
        if not append:
            downloaded = 0
        mode = "ab" if append else "wb"
        last_heartbeat = time.monotonic()
        with partial.open(mode) as output:
            for chunk in response.iter_content(chunk_size=8 * 1024**2):
                if not chunk:
                    continue
                output.write(chunk)
                downloaded += len(chunk)
                if time.monotonic() - last_heartbeat >= self.config.heartbeat_seconds:
                    ratio = downloaded / max(1, int(job["size"]))
                    self.heartbeat(job, min(18, 3 + int(ratio * 15)), "正在传输病理切片到国内服务器")
                    last_heartbeat = time.monotonic()
        if downloaded != int(job["size"]):
            raise RuntimeError(f"切片下载不完整: {downloaded}/{job['size']} bytes")
        partial.replace(destination)

    def complete(self, job, bundle_path):
        with bundle_path.open("rb") as bundle:
            response = self.session.post(
                self._url(job["completeUrl"]),
                files={"bundle": ("result.zip", bundle, "application/zip")},
                timeout=(30, 1800),
                verify=self.config.verify_tls,
            )
        response.raise_for_status()

    def fail(self, job, error):
        response = self.session.post(
            self._url(job["failUrl"]),
            json={"error": str(error)[:4000]},
            timeout=(15, 60),
            verify=self.config.verify_tls,
        )
        response.raise_for_status()


class RemoteWorker:
    def __init__(self, config):
        self.config = config
        self.client = GatewayClient(config)
        config.data_dir.mkdir(parents=True, exist_ok=True)

    def run_forever(self, once=False):
        self.client.health()
        while True:
            job = self.client.lease()
            if job:
                self._run_job(job)
                if once:
                    return True
            elif once:
                return False
            else:
                time.sleep(self.config.poll_seconds)

    def _run_job(self, job):
        job_dir = self.config.data_dir / "jobs" / job["id"]
        input_dir = job_dir / "input"
        output_dir = job_dir / "output"
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = Path(job["storedFilename"])
        if filename.name != str(filename) or filename.suffix.lower() != ".svs":
            raise RuntimeError("海外网关返回了无效切片文件名")
        slide_path = input_dir / filename
        try:
            self.client.heartbeat(job, 3, "国内计算节点准备下载切片")
            if not slide_path.is_file() or slide_path.stat().st_size != int(job["size"]):
                self.client.download_slide(job, slide_path)
            self.client.heartbeat(job, 20, "切片传输完成，正在启动推理")
            self._run_pipeline(job, input_dir, output_dir)
            bundle_path = self._build_result_bundle(output_dir, job_dir / "result.zip")
            self.client.heartbeat(job, 97, "推理完成，正在回传结果")
            self.client.complete(job, bundle_path)
        except Exception as error:
            try:
                self.client.fail(job, error)
            except Exception:
                pass
            raise

    def _run_pipeline(self, job, input_dir, output_dir):
        command = [
            sys.executable,
            "-u",
            str(PROJECT_ROOT / "webviewer" / "pipeline_worker.py"),
            "--wsi-dir",
            str(input_dir),
            "--output-dir",
            str(output_dir),
            "--model",
            job.get("model") or "h-optimus-1",
            "--normal" if job.get("normal", True) else "--no-normal",
        ]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        process = subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        lines = queue.Queue()

        def read_output():
            try:
                for line in iter(process.stdout.readline, ""):
                    lines.put(line)
            finally:
                lines.put(None)

        threading.Thread(target=read_output, daemon=True).start()
        progress, message = 20, "正在执行医学图像推理"
        last_heartbeat = 0.0
        reader_finished = False
        log_path = output_dir / "pipeline.log"
        with log_path.open("a", encoding="utf-8") as log:
            while process.poll() is None or not reader_finished or not lines.empty():
                try:
                    line = lines.get(timeout=1)
                    if line is None:
                        reader_finished = True
                    else:
                        log.write(line)
                        log.flush()
                        parsed = self._progress_from_line(line)
                        if parsed:
                            progress, message = parsed
                except queue.Empty:
                    pass
                if time.monotonic() - last_heartbeat >= self.config.heartbeat_seconds:
                    self.client.heartbeat(job, progress, message)
                    last_heartbeat = time.monotonic()
        return_code = process.wait()
        if return_code != 0:
            raise RuntimeError(f"推理进程异常退出（代码 {return_code}），详见 pipeline.log")
        if not (output_dir / "exist_cancer.json").is_file():
            raise RuntimeError("推理未生成 exist_cancer.json")

    @staticmethod
    def _progress_from_line(line):
        checkpoints = (
            ("WSI生成", 25, "正在生成分类切块"),
            ("WSI特征提取", 35, "正在提取病理特征"),
            ("癌症诊断", 55, "正在进行癌症诊断"),
            ("Gleason", 65, "正在评估 Gleason 分级"),
            ("yolo patching", 73, "正在生成癌区切块"),
            ("Infer Patches", 82, "正在定位疑似癌区"),
            ("总执行时间", 95, "正在整理诊断结果"),
        )
        for marker, progress, message in checkpoints:
            if marker in line:
                return progress, message
        return None

    @staticmethod
    def _build_result_bundle(output_dir, bundle_path):
        result_path = output_dir / "exist_cancer.json"
        if not result_path.is_file():
            raise RuntimeError("缺少 exist_cancer.json")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        for entry in result.get("geojson_files", []):
            filename = Path(str(entry.get("filename", "")))
            if filename.name != str(filename) or not (output_dir / filename).is_file():
                raise RuntimeError(f"缺少结果 GeoJSON: {filename}")

        files = set()
        for pattern in RESULT_PATTERNS:
            files.update(path for path in output_dir.glob(pattern) if path.is_file())
        with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            for path in sorted(files):
                archive.write(path, path.relative_to(output_dir).as_posix())
        return bundle_path
