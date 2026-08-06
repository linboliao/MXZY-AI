from pathlib import Path

from flask import Flask

from .config import WebViewerConfig
from .jobs import JobManager, JobStore
from .routes import api
from .slides import SlideCache


def create_app(config_overrides=None):
    app = Flask(__name__, template_folder="templates", static_folder="static")
    config = WebViewerConfig.from_environment()
    app.config.update(config.as_flask_config())
    if config_overrides:
        app.config.update(config_overrides)
    backend = app.config["WEBVIEWER_EXECUTION_BACKEND"]
    if backend not in {"local", "remote"}:
        raise RuntimeError("WEBVIEWER_EXECUTION_BACKEND 只能是 local 或 remote")
    if backend == "remote" and not app.config["WEBVIEWER_WORKER_TOKEN"]:
        raise RuntimeError("远程执行模式必须配置 WEBVIEWER_WORKER_TOKEN")

    data_dir = Path(app.config["WEBVIEWER_DATA_DIR"]).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)

    store = JobStore(data_dir / "jobs.sqlite3")
    manager = JobManager(app, store)
    slides = SlideCache(max_items=app.config["WEBVIEWER_SLIDE_CACHE_SIZE"])

    app.extensions["webviewer_store"] = store
    app.extensions["webviewer_jobs"] = manager
    app.extensions["webviewer_slides"] = slides
    app.register_blueprint(api)

    manager.recover()
    return app
