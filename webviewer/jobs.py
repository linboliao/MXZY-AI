import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from werkzeug.utils import secure_filename


ALLOWED_EXTENSIONS = {".svs"}

LEGACY_JOB_MESSAGES = {
    "等待诊断": "Waiting for diagnosis",
    "诊断中断": "Diagnosis interrupted",
    "等待国内计算节点": "Waiting for a GPU worker",
    "国内计算节点已领取任务": "GPU worker accepted the task",
    "诊断完成": "Diagnosis completed",
    "诊断失败": "Diagnosis failed",
    "正在初始化诊断": "Initializing diagnosis",
    "诊断完成（模拟模式）": "Diagnosis completed (simulation mode)",
    "正在生成分类切块": "Generating classification patches",
    "正在提取病理特征": "Extracting pathology features",
    "正在进行癌症诊断": "Assessing malignancy",
    "正在评估 Gleason 分级": "Assessing Gleason grade",
    "正在生成癌区切块": "Generating tumor-region patches",
    "正在定位疑似癌区": "Locating suspected tumor regions",
    "正在整理诊断结果": "Preparing diagnostic results",
    "正在传输病理切片到国内服务器": "Transferring the pathology slide to the GPU worker",
    "国内计算节点准备下载切片": "GPU worker is preparing to download the slide",
    "切片传输完成，正在启动推理": "Slide transfer completed; starting inference",
    "推理完成，正在回传结果": "Inference completed; uploading results",
    "正在执行医学图像推理": "Running medical image inference",
}

LEGACY_JOB_ERRORS = {
    "服务重启导致任务中断": "Task interrupted by a service restart",
}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def processing_seconds(row):
    """Return wall-clock processing time without including time spent queued."""
    started_at = row.get("started_at") if isinstance(row, dict) else row["started_at"]
    if not started_at:
        return None
    completed_at = row.get("completed_at") if isinstance(row, dict) else row["completed_at"]
    try:
        started = datetime.fromisoformat(started_at)
        completed = datetime.fromisoformat(completed_at) if completed_at else datetime.now(timezone.utc)
        elapsed = (completed - started).total_seconds()
    except (TypeError, ValueError):
        return None
    return max(0, round(elapsed, 1))


def server_source_current(row):
    values = row if isinstance(row, dict) else dict(row)
    if values.get("source_type") != "server" or not values.get("source_path"):
        return True
    try:
        stat = Path(values["source_path"]).stat()
    except OSError:
        return False
    return bool(
        stat.st_size == values.get("source_size")
        and stat.st_mtime_ns == values.get("source_mtime_ns")
    )


def public_job(row):
    if not row:
        return None
    result = dict(row)
    result["processing_seconds"] = processing_seconds(result)
    if result.get("source_type") == "server":
        result["source_current"] = server_source_current(result)
    for private_key in (
        "input_path",
        "output_path",
        "worker_id",
        "lease_expires_at",
        "source_path",
        "source_size",
        "source_mtime_ns",
    ):
        result.pop(private_key, None)
    if result.get("result_json"):
        try:
            result["result"] = json.loads(result.pop("result_json"))
        except json.JSONDecodeError:
            result["result"] = None
    else:
        result.pop("result_json", None)
        result["result"] = None
    return result


class JobStore:
    def __init__(self, database_path):
        self.database_path = str(database_path)
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self):
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    original_name TEXT NOT NULL,
                    input_path TEXT NOT NULL,
                    output_path TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    message TEXT NOT NULL DEFAULT '',
                    error TEXT,
                    result_json TEXT,
                    worker_id TEXT,
                    lease_expires_at TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    source_path TEXT,
                    source_size INTEGER,
                    source_mtime_ns INTEGER,
                    started_at TEXT,
                    completed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
            }
            migrations = {
                "worker_id": "ALTER TABLE jobs ADD COLUMN worker_id TEXT",
                "lease_expires_at": "ALTER TABLE jobs ADD COLUMN lease_expires_at TEXT",
                "attempts": "ALTER TABLE jobs ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0",
                "source_path": "ALTER TABLE jobs ADD COLUMN source_path TEXT",
                "source_size": "ALTER TABLE jobs ADD COLUMN source_size INTEGER",
                "source_mtime_ns": "ALTER TABLE jobs ADD COLUMN source_mtime_ns INTEGER",
                "started_at": "ALTER TABLE jobs ADD COLUMN started_at TEXT",
                "completed_at": "ALTER TABLE jobs ADD COLUMN completed_at TEXT",
            }
            for column, statement in migrations.items():
                if column not in columns:
                    connection.execute(statement)
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_jobs_server_source
                ON jobs(source_path, source_size, source_mtime_ns, created_at)
                """
            )
            for old_message, new_message in LEGACY_JOB_MESSAGES.items():
                connection.execute(
                    "UPDATE jobs SET message = ? WHERE message = ?",
                    (new_message, old_message),
                )
            for old_error, new_error in LEGACY_JOB_ERRORS.items():
                connection.execute(
                    "UPDATE jobs SET error = ? WHERE error = ?",
                    (new_error, old_error),
                )

    def create(self, **values):
        now = utc_now()
        row = {
            "id": values["id"],
            "status": "queued",
            "source_type": values["source_type"],
            "original_name": values["original_name"],
            "input_path": values["input_path"],
            "output_path": values["output_path"],
            "progress": 0,
            "message": "Waiting for diagnosis",
            "error": None,
            "result_json": None,
            "worker_id": None,
            "lease_expires_at": None,
            "attempts": 0,
            "source_path": values.get("source_path"),
            "source_size": values.get("source_size"),
            "source_mtime_ns": values.get("source_mtime_ns"),
            "started_at": None,
            "completed_at": None,
            "created_at": now,
            "updated_at": now,
        }
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    id, status, source_type, original_name, input_path, output_path,
                    progress, message, error, result_json,
                    source_path, source_size, source_mtime_ns, started_at, completed_at,
                    created_at, updated_at
                ) VALUES (
                    :id, :status, :source_type, :original_name, :input_path, :output_path,
                    :progress, :message, :error, :result_json,
                    :source_path, :source_size, :source_mtime_ns, :started_at, :completed_at,
                    :created_at, :updated_at
                )
                """,
                row,
            )
        return self.get(row["id"])

    def get(self, job_id):
        with self._lock, self._connect() as connection:
            return connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()

    def list(self, limit=50):
        with self._lock, self._connect() as connection:
            return connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()

    def list_server_jobs(self, source_path=None):
        with self._lock, self._connect() as connection:
            if source_path is not None:
                return connection.execute(
                    """
                    SELECT * FROM jobs
                    WHERE source_type = 'server' AND source_path = ?
                    ORDER BY created_at DESC
                    """,
                    (str(source_path),),
                ).fetchall()
            return connection.execute(
                """
                SELECT * FROM jobs
                WHERE source_type = 'server' AND source_path IS NOT NULL
                ORDER BY created_at DESC
                """
            ).fetchall()

    def list_queued(self):
        with self._lock, self._connect() as connection:
            return connection.execute(
                "SELECT * FROM jobs WHERE status = 'queued' ORDER BY created_at"
            ).fetchall()

    def update(self, job_id, **values):
        allowed = {
            "status",
            "progress",
            "message",
            "error",
            "result_json",
            "started_at",
            "completed_at",
        }
        updates = {key: value for key, value in values.items() if key in allowed}
        if not updates:
            return self.get(job_id)
        updates["updated_at"] = utc_now()
        assignments = ", ".join(f"{key} = :{key}" for key in updates)
        updates["id"] = job_id
        with self._lock, self._connect() as connection:
            connection.execute(f"UPDATE jobs SET {assignments} WHERE id = :id", updates)
        return self.get(job_id)

    def mark_interrupted(self):
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE jobs
                SET status = 'failed', error = 'Task interrupted by a service restart',
                    message = 'Diagnosis interrupted', completed_at = ?, updated_at = ?
                WHERE status = 'running'
                """,
                (now, now),
            )

    def requeue_expired(self):
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE jobs
                SET status = 'queued', worker_id = NULL, lease_expires_at = NULL,
                    progress = 0, message = 'Waiting for a GPU worker',
                    started_at = NULL, completed_at = NULL, updated_at = ?
                WHERE status = 'running' AND lease_expires_at IS NOT NULL
                  AND lease_expires_at <= ?
                """,
                (now, now),
            )

    def lease_next(self, worker_id, lease_seconds):
        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(seconds=lease_seconds)).isoformat()
        now_text = now.isoformat()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE jobs
                SET status = 'queued', worker_id = NULL, lease_expires_at = NULL,
                    progress = 0, message = 'Waiting for a GPU worker',
                    started_at = NULL, completed_at = NULL, updated_at = ?
                WHERE status = 'running' AND lease_expires_at IS NOT NULL
                  AND lease_expires_at <= ?
                """,
                (now_text, now_text),
            )
            row = connection.execute(
                "SELECT * FROM jobs WHERE status = 'queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if not row:
                return None
            connection.execute(
                """
                UPDATE jobs
                SET status = 'running', worker_id = ?, lease_expires_at = ?,
                    attempts = attempts + 1, progress = 2,
                    message = 'GPU worker accepted the task',
                    started_at = COALESCE(started_at, ?), updated_at = ?
                WHERE id = ? AND status = 'queued'
                """,
                (worker_id, expires_at, now_text, now_text, row["id"]),
            )
            return connection.execute("SELECT * FROM jobs WHERE id = ?", (row["id"],)).fetchone()

    def heartbeat(self, job_id, worker_id, lease_seconds, progress=None, message=None):
        now = datetime.now(timezone.utc)
        values = {
            "id": job_id,
            "worker_id": worker_id,
            "lease_expires_at": (now + timedelta(seconds=lease_seconds)).isoformat(),
            "updated_at": now.isoformat(),
            "progress": max(2, min(99, int(progress))) if progress is not None else None,
            "message": str(message)[:500] if message else None,
        }
        assignments = ["lease_expires_at = :lease_expires_at", "updated_at = :updated_at"]
        if values["progress"] is not None:
            assignments.append("progress = :progress")
        if values["message"] is not None:
            assignments.append("message = :message")
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE jobs SET {', '.join(assignments)}
                WHERE id = :id AND status = 'running' AND worker_id = :worker_id
                """,
                values,
            )
            return cursor.rowcount == 1

    def complete_remote(self, job_id, worker_id, result_json):
        now = utc_now()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = 'completed', progress = 100, message = 'Diagnosis completed',
                    result_json = ?, error = NULL, worker_id = NULL,
                    lease_expires_at = NULL, completed_at = ?, updated_at = ?
                WHERE id = ? AND status = 'running' AND worker_id = ?
                """,
                (result_json, now, now, job_id, worker_id),
            )
            return cursor.rowcount == 1

    def fail_remote(self, job_id, worker_id, error):
        now = utc_now()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = 'failed', message = 'Diagnosis failed', error = ?,
                    worker_id = NULL, lease_expires_at = NULL,
                    completed_at = ?, updated_at = ?
                WHERE id = ? AND status = 'running' AND worker_id = ?
                """,
                (str(error)[:4000], now, now, job_id, worker_id),
            )
            return cursor.rowcount == 1


class JobManager:
    def __init__(self, app, store):
        self.app = app
        self.store = store
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wsi-diagnosis")
        self.sync_jobs = bool(app.config["WEBVIEWER_SYNC_JOBS"])
        self.execution_backend = app.config["WEBVIEWER_EXECUTION_BACKEND"]
        self._server_job_lock = threading.RLock()

    def recover(self):
        if self.execution_backend == "remote":
            self.store.requeue_expired()
            return
        self.store.mark_interrupted()
        for row in self.store.list_queued():
            self._submit(row["id"])

    def create_from_upload(self, upload):
        original_name = Path(upload.filename or "").name
        extension = Path(original_name).suffix.lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise ValueError("The current diagnostic pipeline only supports .svs pathology slides")

        job_id, input_dir, output_dir = self._new_job_directories()
        safe_stem = secure_filename(Path(original_name).stem) or "slide"
        input_path = input_dir / f"{safe_stem}-{job_id[:8]}{extension}"
        upload.save(input_path)
        if input_path.stat().st_size == 0:
            raise ValueError("The uploaded file is empty")

        self.store.create(
            id=job_id,
            source_type="upload",
            original_name=original_name,
            input_path=str(input_path),
            output_path=str(output_dir),
        )
        self._submit(job_id)
        return self.store.get(job_id)

    @staticmethod
    def _completed_job_available(row):
        return bool(
            row
            and row["status"] == "completed"
            and row["result_json"]
            and Path(row["input_path"]).is_file()
            and Path(row["output_path"]).is_dir()
        )

    def describe_server_slide(self, source_path, stat, rows):
        source_path = str(Path(source_path).resolve())
        exact = [
            row
            for row in rows
            if row["source_path"] == source_path
            and row["source_size"] == stat.st_size
            and row["source_mtime_ns"] == stat.st_mtime_ns
        ]
        active = next(
            (row for row in exact if row["status"] in {"queued", "running"}),
            None,
        )
        completed = next(
            (row for row in exact if self._completed_job_available(row)),
            None,
        )
        failed = next((row for row in exact if row["status"] == "failed"), None)
        selected = active or completed or failed
        if selected:
            status = {
                "queued": "queued",
                "running": "processing",
                "completed": "ready",
                "failed": "failed",
            }[selected["status"]]
            job = public_job(selected)
            return {
                "analysisStatus": status,
                "jobId": selected["id"],
                "progress": selected["progress"],
                "message": selected["message"],
                "processingSeconds": job["processing_seconds"],
                "completedAt": selected["completed_at"],
            }
        if exact:
            return {
                "analysisStatus": "outdated",
                "jobId": None,
                "progress": 0,
                "message": "The saved result is unavailable; recomputation is required",
                "processingSeconds": None,
                "completedAt": None,
            }
        if any(row["source_path"] == source_path for row in rows):
            return {
                "analysisStatus": "outdated",
                "jobId": None,
                "progress": 0,
                "message": "The slide changed after its last analysis",
                "processingSeconds": None,
                "completedAt": None,
            }
        return {
            "analysisStatus": "not_analyzed",
            "jobId": None,
            "progress": 0,
            "message": "Awaiting administrator precomputation",
            "processingSeconds": None,
            "completedAt": None,
        }

    def create_from_server_path(self, source_path):
        source_path = Path(source_path).resolve()
        if source_path.suffix.lower() not in ALLOWED_EXTENSIONS:
            raise ValueError("The current diagnostic pipeline only supports .svs pathology slides")
        if not source_path.is_file():
            raise ValueError("The server-side slide does not exist")
        stat = source_path.stat()

        with self._server_job_lock:
            existing_rows = self.store.list_server_jobs(str(source_path))
            active = next(
                (
                    row
                    for row in existing_rows
                    if row["source_size"] == stat.st_size
                    and row["source_mtime_ns"] == stat.st_mtime_ns
                    and row["status"] in {"queued", "running"}
                ),
                None,
            )
            completed = next(
                (
                    row
                    for row in existing_rows
                    if row["source_size"] == stat.st_size
                    and row["source_mtime_ns"] == stat.st_mtime_ns
                    and self._completed_job_available(row)
                ),
                None,
            )
            if active or completed:
                return active or completed, True

            job_id, input_dir, output_dir = self._new_job_directories()
            staged_path = input_dir / f"{secure_filename(source_path.stem) or 'slide'}-{job_id[:8]}.svs"
            try:
                os.link(source_path, staged_path)
            except OSError:
                try:
                    os.symlink(source_path, staged_path)
                except OSError as error:
                    shutil.rmtree(input_dir.parent, ignore_errors=True)
                    raise ValueError(
                        "Unable to mount the server-side slide without copying; place the slide library and runtime directory on the same filesystem"
                    ) from error

            self.store.create(
                id=job_id,
                source_type="server",
                original_name=source_path.name,
                input_path=str(staged_path),
                output_path=str(output_dir),
                source_path=str(source_path),
                source_size=stat.st_size,
                source_mtime_ns=stat.st_mtime_ns,
            )
            self._submit(job_id)
            return self.store.get(job_id), False

    def _new_job_directories(self):
        job_id = uuid.uuid4().hex
        job_dir = Path(self.app.config["WEBVIEWER_DATA_DIR"]) / "jobs" / job_id
        input_dir = job_dir / "input"
        output_dir = job_dir / "output"
        input_dir.mkdir(parents=True, exist_ok=False)
        output_dir.mkdir(parents=True, exist_ok=False)
        return job_id, input_dir, output_dir

    def _submit(self, job_id):
        if self.execution_backend == "remote":
            self.store.update(job_id, message="Waiting for a GPU worker")
            return
        if self.sync_jobs:
            self._run(job_id)
        else:
            self.executor.submit(self._run, job_id)

    def _run(self, job_id):
        row = self.store.get(job_id)
        if not row:
            return
        if row["source_type"] == "server" and not server_source_current(row):
            self.store.update(
                job_id,
                status="failed",
                message="Diagnosis failed",
                error="The server slide changed before precomputation started",
                completed_at=utc_now(),
            )
            return
        self.store.update(
            job_id,
            status="running",
            progress=3,
            message="Initializing diagnosis",
            started_at=utc_now(),
        )
        try:
            if self.app.config["WEBVIEWER_PIPELINE_MODE"] == "mock":
                self._run_mock(row)
            else:
                self._run_real(row)
        except Exception as error:
            self.store.update(
                job_id,
                status="failed",
                message="Diagnosis failed",
                error=str(error),
                completed_at=utc_now(),
            )

    def _run_mock(self, row):
        output_dir = Path(row["output_path"])
        slide_id = Path(row["input_path"]).stem
        overlay = {
            "type": "FeatureCollection",
            "features": [],
        }
        (output_dir / f"{slide_id}.geojson").write_text(
            json.dumps(overlay), encoding="utf-8"
        )
        result = {
            "geojson_files": [
                {
                    "filename": f"{slide_id}.geojson",
                    "type": "Benign",
                    "conf": "strong",
                    "percentage": 0,
                    "Gleason": "N/A",
                    "ISUP": "N/A",
                }
            ]
        }
        result_path = output_dir / "exist_cancer.json"
        result_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        self.store.update(
            row["id"],
            status="completed",
            progress=100,
            message="Diagnosis completed (simulation mode)",
            result_json=json.dumps(result, ensure_ascii=False),
            completed_at=utc_now(),
        )

    def _run_real(self, row):
        project_root = Path(self.app.config["WEBVIEWER_PROJECT_ROOT"])
        input_dir = Path(row["input_path"]).parent
        output_dir = Path(row["output_path"])
        command = [
            sys.executable,
            "-u",
            str(project_root / "webviewer" / "pipeline_worker.py"),
            "--wsi-dir",
            str(input_dir),
            "--output-dir",
            str(output_dir),
            "--model",
            self.app.config["WEBVIEWER_PIPELINE_MODEL"],
        ]
        command.append(
            "--normal" if self.app.config["WEBVIEWER_PIPELINE_NORMAL"] else "--no-normal"
        )
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        process = subprocess.Popen(
            command,
            cwd=project_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        log_path = output_dir / "pipeline.log"
        with log_path.open("a", encoding="utf-8") as log:
            for line in iter(process.stdout.readline, ""):
                log.write(line)
                log.flush()
                progress, message = self._progress_from_line(line)
                if progress is not None:
                    self.store.update(row["id"], progress=progress, message=message)
        return_code = process.wait()
        result_path = output_dir / "exist_cancer.json"
        if return_code != 0:
            raise RuntimeError(f"The diagnostic process exited with code {return_code}; see pipeline.log for details")
        if not result_path.is_file():
            raise RuntimeError("The diagnostic process did not generate exist_cancer.json; see pipeline.log for details")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        self.store.update(
            row["id"],
            status="completed",
            progress=100,
            message="Diagnosis completed",
            result_json=json.dumps(result, ensure_ascii=False),
            completed_at=utc_now(),
        )

    @staticmethod
    def _progress_from_line(line):
        checkpoints = (
            ("create_patch_cls", 12, "Generating classification patches"),
            ("WSI特征提取", 30, "Extracting pathology features"),
            ("癌症诊断", 52, "Assessing malignancy"),
            ("Gleason", 64, "Assessing Gleason grade"),
            ("yolo patching", 72, "Generating tumor-region patches"),
            ("run_yolo", 82, "Locating suspected tumor regions"),
            ("总执行时间", 95, "Preparing diagnostic results"),
        )
        for marker, progress, message in checkpoints:
            if marker in line:
                return progress, message
        return None, None
