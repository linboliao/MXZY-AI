import base64
import binascii
import hmac
import shutil
import tempfile
import zipfile
import json
from pathlib import Path

from flask import Blueprint, Response, abort, current_app, jsonify, render_template, request, send_file, url_for
from werkzeug.exceptions import RequestEntityTooLarge

from .jobs import ALLOWED_EXTENSIONS, public_job
from .slides import SlideUnavailable


api = Blueprint("webviewer", __name__)


def _encode_server_path(root_index, relative_path):
    payload = json.dumps([root_index, relative_path], ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_server_path(token):
    try:
        padded = token + "=" * (-len(token) % 4)
        root_index, relative_path = json.loads(
            base64.urlsafe_b64decode(padded).decode("utf-8")
        )
        roots = current_app.config["WEBVIEWER_SERVER_ROOTS"]
        root = Path(roots[int(root_index)][1]).resolve()
        candidate = (root / relative_path).resolve()
        candidate.relative_to(root)
        if candidate.suffix.lower() not in ALLOWED_EXTENSIONS or not candidate.is_file():
            raise ValueError
        return candidate
    except (ValueError, TypeError, IndexError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError):
        abort(400, description="无效的服务端切片标识")


def _job_or_404(job_id):
    row = current_app.extensions["webviewer_store"].get(job_id)
    if not row:
        abort(404, description="诊断任务不存在")
    return row


def _authenticate_worker():
    expected = current_app.config.get("WEBVIEWER_WORKER_TOKEN", "")
    authorization = request.headers.get("Authorization", "")
    supplied = authorization[7:] if authorization.startswith("Bearer ") else ""
    if not expected:
        abort(503, description="海外网关未配置 Worker Token")
    if not supplied or not hmac.compare_digest(supplied, expected):
        abort(401, description="Worker 身份验证失败")


def _worker_id_from_request():
    worker_id = request.headers.get("X-Worker-ID", "").strip()
    if not worker_id:
        payload = request.get_json(silent=True) or {}
        worker_id = str(payload.get("workerId", "")).strip()
    if not worker_id or len(worker_id) > 200:
        abort(400, description="缺少有效的 Worker ID")
    return worker_id


def _leased_job(job_id, worker_id):
    row = _job_or_404(job_id)
    if row["status"] != "running" or row["worker_id"] != worker_id:
        abort(409, description="任务租约不存在、已过期或不属于当前 Worker")
    return row


def _extract_result_bundle(bundle, output_dir, max_bytes):
    with tempfile.TemporaryDirectory(prefix="result-upload-", dir=output_dir.parent) as temporary:
        archive_path = Path(temporary) / "result.zip"
        bundle.save(archive_path)
        if archive_path.stat().st_size > max_bytes:
            raise ValueError("结果压缩包超过服务器限制")

        extract_dir = Path(temporary) / "extracted"
        extract_dir.mkdir()
        with zipfile.ZipFile(archive_path) as archive:
            members = archive.infolist()
            if len(members) > 10000:
                raise ValueError("结果压缩包文件数量异常")
            if sum(member.file_size for member in members) > max_bytes * 4:
                raise ValueError("结果压缩包解压后超过服务器限制")
            for member in members:
                member_path = Path(member.filename.replace("\\", "/"))
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise ValueError("结果压缩包包含不安全路径")
                (extract_dir / member_path).resolve().relative_to(extract_dir.resolve())
            archive.extractall(extract_dir)

        result_path = extract_dir / "exist_cancer.json"
        if not result_path.is_file():
            raise ValueError("结果压缩包缺少 exist_cancer.json")
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"exist_cancer.json 无效: {error}") from error
        entries = result.get("geojson_files")
        if not isinstance(entries, list) or not entries:
            raise ValueError("exist_cancer.json 缺少 geojson_files")
        for entry in entries:
            filename = Path(str(entry.get("filename", "")))
            if filename.name != str(filename) or filename.suffix.lower() != ".geojson":
                raise ValueError("结果中包含无效 GeoJSON 文件名")
            if not (extract_dir / filename).is_file():
                raise ValueError(f"结果压缩包缺少 {filename.name}")

        output_dir.mkdir(parents=True, exist_ok=True)
        for child in extract_dir.iterdir():
            destination = output_dir / child.name
            if child.is_dir():
                shutil.copytree(child, destination, dirs_exist_ok=True)
            else:
                shutil.copy2(child, destination)
        return result


@api.get("/")
def index():
    return render_template("index.html")


@api.get("/api/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "service": "MXZY-AI Web Viewer",
            "executionBackend": current_app.config["WEBVIEWER_EXECUTION_BACKEND"],
        }
    )


@api.get("/api/worker/health")
def worker_health():
    _authenticate_worker()
    return jsonify({"status": "ok", "service": "MXZY-AI Worker Gateway"})


@api.post("/api/worker/jobs/lease")
def worker_lease():
    _authenticate_worker()
    worker_id = _worker_id_from_request()
    row = current_app.extensions["webviewer_store"].lease_next(
        worker_id, current_app.config["WEBVIEWER_WORKER_LEASE_SECONDS"]
    )
    if not row:
        return "", 204
    return jsonify(
        {
            "job": {
                "id": row["id"],
                "originalName": row["original_name"],
                "storedFilename": Path(row["input_path"]).name,
                "size": Path(row["input_path"]).stat().st_size,
                "model": current_app.config["WEBVIEWER_PIPELINE_MODEL"],
                "normal": bool(current_app.config["WEBVIEWER_PIPELINE_NORMAL"]),
                "leaseSeconds": current_app.config["WEBVIEWER_WORKER_LEASE_SECONDS"],
                "slideUrl": url_for("webviewer.worker_slide", job_id=row["id"]),
                "heartbeatUrl": url_for("webviewer.worker_heartbeat", job_id=row["id"]),
                "completeUrl": url_for("webviewer.worker_complete", job_id=row["id"]),
                "failUrl": url_for("webviewer.worker_fail", job_id=row["id"]),
            }
        }
    )


@api.get("/api/worker/jobs/<job_id>/slide")
def worker_slide(job_id):
    _authenticate_worker()
    worker_id = _worker_id_from_request()
    row = _leased_job(job_id, worker_id)
    return send_file(
        row["input_path"],
        as_attachment=True,
        download_name=Path(row["input_path"]).name,
        conditional=True,
    )


@api.post("/api/worker/jobs/<job_id>/heartbeat")
def worker_heartbeat(job_id):
    _authenticate_worker()
    worker_id = _worker_id_from_request()
    payload = request.get_json(silent=True) or {}
    updated = current_app.extensions["webviewer_store"].heartbeat(
        job_id,
        worker_id,
        current_app.config["WEBVIEWER_WORKER_LEASE_SECONDS"],
        progress=payload.get("progress"),
        message=payload.get("message"),
    )
    if not updated:
        abort(409, description="任务租约不存在、已过期或不属于当前 Worker")
    return jsonify({"status": "ok"})


@api.post("/api/worker/jobs/<job_id>/complete")
def worker_complete(job_id):
    _authenticate_worker()
    worker_id = _worker_id_from_request()
    row = _leased_job(job_id, worker_id)
    max_bytes = current_app.config["WEBVIEWER_RESULT_BUNDLE_MAX_BYTES"]
    if request.content_length and request.content_length > max_bytes:
        abort(413, description="结果压缩包超过服务器限制")
    bundle = request.files.get("bundle")
    if not bundle or not bundle.filename:
        abort(400, description="缺少结果压缩包")
    try:
        result = _extract_result_bundle(bundle, Path(row["output_path"]), max_bytes)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        abort(400, description=str(error))
    completed = current_app.extensions["webviewer_store"].complete_remote(
        job_id, worker_id, json.dumps(result, ensure_ascii=False)
    )
    if not completed:
        abort(409, description="任务租约已失效")
    return jsonify({"status": "completed"})


@api.post("/api/worker/jobs/<job_id>/fail")
def worker_fail(job_id):
    _authenticate_worker()
    worker_id = _worker_id_from_request()
    payload = request.get_json(silent=True) or {}
    error = str(payload.get("error") or "国内计算节点未提供错误信息")
    failed = current_app.extensions["webviewer_store"].fail_remote(
        job_id, worker_id, error
    )
    if not failed:
        abort(409, description="任务租约已失效")
    return jsonify({"status": "failed"})


@api.get("/api/config")
def config():
    return jsonify(
        {
            "maxUploadBytes": current_app.config["WEBVIEWER_MAX_UPLOAD_BYTES"],
            "allowedExtensions": sorted(ALLOWED_EXTENSIONS),
            "hasServerSlides": bool(current_app.config["WEBVIEWER_SERVER_ROOTS"]),
            "pipelineMode": current_app.config["WEBVIEWER_PIPELINE_MODE"],
            "executionBackend": current_app.config["WEBVIEWER_EXECUTION_BACKEND"],
        }
    )


@api.get("/api/server-slides")
def server_slides():
    items = []
    roots = current_app.config["WEBVIEWER_SERVER_ROOTS"]
    for root_index, (root_name, root) in enumerate(roots):
        root = Path(root)
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in ALLOWED_EXTENSIONS:
                relative = path.relative_to(root).as_posix()
                stat = path.stat()
                items.append(
                    {
                        "id": _encode_server_path(root_index, relative),
                        "name": path.name,
                        "folder": root_name,
                        "relativePath": relative,
                        "size": stat.st_size,
                        "modified": stat.st_mtime,
                    }
                )
                if len(items) >= 5000:
                    break
    items.sort(key=lambda item: item["modified"], reverse=True)
    return jsonify({"slides": items})


@api.get("/api/jobs")
def list_jobs():
    rows = current_app.extensions["webviewer_store"].list(limit=50)
    return jsonify({"jobs": [public_job(row) for row in rows]})


@api.post("/api/jobs")
def create_job():
    manager = current_app.extensions["webviewer_jobs"]
    try:
        if request.content_type and request.content_type.startswith("multipart/form-data"):
            upload = request.files.get("slide")
            if not upload or not upload.filename:
                abort(400, description="请选择要上传的 .svs 切片")
            row = manager.create_from_upload(upload)
        else:
            payload = request.get_json(silent=True) or {}
            token = payload.get("serverSlideId")
            if not token:
                abort(400, description="请选择服务端切片")
            row = manager.create_from_server_path(_decode_server_path(token))
    except ValueError as error:
        abort(400, description=str(error))
    return jsonify({"job": public_job(row)}), 202


@api.get("/api/jobs/<job_id>")
def get_job(job_id):
    return jsonify({"job": public_job(_job_or_404(job_id))})


@api.get("/api/jobs/<job_id>/slide/metadata")
def slide_metadata(job_id):
    row = _job_or_404(job_id)
    try:
        metadata = current_app.extensions["webviewer_slides"].metadata(row["input_path"])
    except SlideUnavailable as error:
        abort(503, description=str(error))
    metadata["name"] = row["original_name"]
    metadata["tileUrlTemplate"] = f"/api/jobs/{job_id}/slide/tiles/{{level}}/{{col}}_{{row}}.jpg"
    return jsonify(metadata)


@api.get("/api/jobs/<job_id>/slide/tiles/<int:level>/<int:col>_<int:row>.jpg")
def slide_tile(job_id, level, col, row):
    job = _job_or_404(job_id)
    try:
        tile = current_app.extensions["webviewer_slides"].tile(
            job["input_path"], level, col, row
        )
    except SlideUnavailable as error:
        abort(503, description=str(error))
    except ValueError as error:
        abort(404, description=str(error))
    return Response(tile, mimetype="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


@api.get("/api/jobs/<job_id>/slide/overlay")
def slide_overlay(job_id):
    job = _job_or_404(job_id)
    output_dir = Path(job["output_path"])
    stem = Path(job["input_path"]).stem
    candidates = (
        output_dir / f"{stem}.geojson",
        output_dir / "yolo" / f"{stem}-detect.geojson",
    )
    for path in candidates:
        if path.is_file():
            return Response(path.read_text(encoding="utf-8"), mimetype="application/geo+json")
    return jsonify({"type": "FeatureCollection", "features": []})


@api.errorhandler(RequestEntityTooLarge)
def upload_too_large(_error):
    if request.path.startswith("/api/worker/"):
        return jsonify({"error": "结果压缩包超过服务器配置的大小限制"}), 413
    return jsonify({"error": "上传文件超过服务器配置的大小限制"}), 413


@api.app_errorhandler(400)
@api.app_errorhandler(401)
@api.app_errorhandler(404)
@api.app_errorhandler(409)
@api.app_errorhandler(413)
@api.app_errorhandler(503)
def api_error(error):
    if request.path.startswith("/api/"):
        return jsonify({"error": getattr(error, "description", str(error))}), error.code
    return error
