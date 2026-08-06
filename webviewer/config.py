import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _parse_bool(value: str, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_server_roots(value: str) -> List[Tuple[str, Path]]:
    roots = []
    for index, raw_item in enumerate(filter(None, (value or "").split(";"))):
        item = raw_item.strip()
        if "=" in item:
            name, raw_path = item.split("=", 1)
        else:
            raw_path = item
            name = Path(raw_path).name or f"切片库 {index + 1}"
        path = Path(raw_path).expanduser().resolve()
        if path.is_dir():
            roots.append((name.strip(), path))
    return roots


@dataclass(frozen=True)
class WebViewerConfig:
    data_dir: Path
    server_roots: List[Tuple[str, Path]]
    max_upload_bytes: int
    pipeline_mode: str
    pipeline_model: str
    pipeline_normal: bool
    execution_backend: str
    worker_token: str
    worker_lease_seconds: int
    result_bundle_max_bytes: int
    sync_jobs: bool
    slide_cache_size: int
    secret_key: str

    @classmethod
    def from_environment(cls):
        max_upload_gb = float(os.getenv("WEBVIEWER_MAX_UPLOAD_GB", "20"))
        result_bundle_max_mb = int(os.getenv("WEBVIEWER_RESULT_BUNDLE_MAX_MB", "512"))
        return cls(
            data_dir=Path(
                os.getenv("WEBVIEWER_DATA_DIR", str(PROJECT_ROOT / "webviewer_data"))
            ).expanduser().resolve(),
            server_roots=_parse_server_roots(os.getenv("WEBVIEWER_SERVER_SLIDE_ROOTS", "")),
            max_upload_bytes=int(max_upload_gb * 1024**3),
            pipeline_mode=os.getenv("WEBVIEWER_PIPELINE_MODE", "real").strip().lower(),
            pipeline_model=os.getenv("WEBVIEWER_PIPELINE_MODEL", "h-optimus-1"),
            pipeline_normal=_parse_bool(os.getenv("WEBVIEWER_PIPELINE_NORMAL"), True),
            execution_backend=os.getenv("WEBVIEWER_EXECUTION_BACKEND", "local").strip().lower(),
            worker_token=os.getenv("WEBVIEWER_WORKER_TOKEN", ""),
            worker_lease_seconds=max(60, int(os.getenv("WEBVIEWER_WORKER_LEASE_SECONDS", "300"))),
            result_bundle_max_bytes=max(1, result_bundle_max_mb) * 1024**2,
            sync_jobs=_parse_bool(os.getenv("WEBVIEWER_SYNC_JOBS"), False),
            slide_cache_size=max(1, int(os.getenv("WEBVIEWER_SLIDE_CACHE_SIZE", "4"))),
            secret_key=os.getenv("WEBVIEWER_SECRET_KEY", "local-development-only"),
        )

    def as_flask_config(self):
        return {
            "MAX_CONTENT_LENGTH": self.max_upload_bytes,
            "SECRET_KEY": self.secret_key,
            "WEBVIEWER_DATA_DIR": str(self.data_dir),
            "WEBVIEWER_SERVER_ROOTS": self.server_roots,
            "WEBVIEWER_MAX_UPLOAD_BYTES": self.max_upload_bytes,
            "WEBVIEWER_PIPELINE_MODE": self.pipeline_mode,
            "WEBVIEWER_PIPELINE_MODEL": self.pipeline_model,
            "WEBVIEWER_PIPELINE_NORMAL": self.pipeline_normal,
            "WEBVIEWER_EXECUTION_BACKEND": self.execution_backend,
            "WEBVIEWER_WORKER_TOKEN": self.worker_token,
            "WEBVIEWER_WORKER_LEASE_SECONDS": self.worker_lease_seconds,
            "WEBVIEWER_RESULT_BUNDLE_MAX_BYTES": self.result_bundle_max_bytes,
            "WEBVIEWER_SYNC_JOBS": self.sync_jobs,
            "WEBVIEWER_SLIDE_CACHE_SIZE": self.slide_cache_size,
            "WEBVIEWER_PROJECT_ROOT": str(PROJECT_ROOT),
        }
